# -*- coding: utf-8 -*-
"""Data access + route-family metadata for the C4-free experiment.

All connection identities, port coordinates and the 368 manual group members
come from the frozen 21-height baseline assignment.  This module only reads.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from .. import common as C
from ..reheight21 import model as M
from . import paths as P

#: the eight frozen manual planes (8 groups, 368 routes)
MANUAL_PLANES = tuple(int(pid) for pid in M.MANUAL_PLANE_IDS)
#: plane sets allowed for the non-manual routes (first round: the existing
#: 21-height partition, per the research spec section 7.1)
Z1_OTHER_PLANES = (6, 7, 20, 1001, 8)
Z2_OTHER_PLANES = (9, 14, 15, 16, 1002, 17, 18, 19)

FAMILIES = ('Z1V', 'Z1H', 'Z2_NE', 'Z2_SE', 'Z2_NW', 'Z2_SW')
FAMILY_LABELS = {
    'Z1V': 'Z1 opposite vertical (N<->S)',
    'Z1H': 'Z1 opposite horizontal (E<->W)',
    'Z2_NE': 'Z2 adjacent NE corner (E->N)',
    'Z2_SE': 'Z2 adjacent SE corner (E->S)',
    'Z2_NW': 'Z2 adjacent NW corner (N->W)',
    'Z2_SW': 'Z2 adjacent SW corner (S->W)',
}
ALLOWED_PLANES = {
    'Z1V': Z1_OTHER_PLANES,
    'Z1H': Z1_OTHER_PLANES,
    'Z2_NE': Z2_OTHER_PLANES,
    'Z2_SE': Z2_OTHER_PLANES,
    'Z2_NW': Z2_OTHER_PLANES,
    'Z2_SW': Z2_OTHER_PLANES,
}
#: (source_side, target_side) -> corner family
_CORNER = {
    ('E', 'N'): 'Z2_NE', ('N', 'E'): 'Z2_NE',
    ('E', 'S'): 'Z2_SE', ('S', 'E'): 'Z2_SE',
    ('N', 'W'): 'Z2_NW', ('W', 'N'): 'Z2_NW',
    ('S', 'W'): 'Z2_SW', ('W', 'S'): 'Z2_SW',
}


# --------------------------------------------------------------------- basic IO
def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    return C.write_json(path, payload)


def read_csv_rows(path):
    """Raw CSV rows (strings) with the original header order preserved."""
    text = Path(path).read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(text.splitlines()))
    return rows, (list(rows[0].keys()) if rows else [])


# ------------------------------------------------------------------- assignment
def load_baseline_assignment():
    """Typed rows of the frozen 21-height assignment (all port data intact)."""
    from ..reheight21 import run21
    return run21.read_assignment(P.BASELINE_21H_DIR / 'assignment_1024.csv')


def load_assignment(exp_dir):
    from ..reheight21 import run21
    return run21.read_assignment(Path(exp_dir) / 'assignment_1024.csv')


def assignment_rows(exp_dir):
    """Typed assignment rows of one experiment directory."""
    return load_assignment(exp_dir)


def baseline_columns():
    _rows, header = read_csv_rows(P.BASELINE_21H_DIR / 'assignment_1024.csv')
    return header


def rows_by_id(rows):
    return {int(row['route_id']): row for row in rows}


# ---------------------------------------------------------------------- family
def is_manual(row):
    return bool(str(row.get('manual_group') or '').strip())


def is_direct(row):
    value = row.get('needs_transition')
    if isinstance(value, bool):
        return not value
    return str(value).strip().lower() in ('false', '0', 'no', 'direct')


def family_of(row):
    """Direction family of one assignment row (``MANUAL:<group>`` for manuals)."""
    group = str(row.get('manual_group') or '').strip()
    if group:
        return 'MANUAL:' + group
    side_a = str(row.get('source_side') or '').strip().upper()
    side_b = str(row.get('target_side') or '').strip().upper()
    plane = str(row.get('plane') or '').strip().lower()
    if plane == 'z1':
        if {side_a, side_b} <= {'N', 'S'}:
            return 'Z1V'
        if {side_a, side_b} <= {'E', 'W'}:
            return 'Z1H'
        raise ValueError(f'route {row.get("route_id")}: unexpected z1 sides '
                         f'{side_a}->{side_b}')
    if plane == 'z2':
        key = (side_a, side_b)
        if key in _CORNER:
            return _CORNER[key]
        raise ValueError(f'route {row.get("route_id")}: unexpected z2 sides '
                         f'{side_a}->{side_b}')
    raise ValueError(f'route {row.get("route_id")}: unknown plane {plane!r}')


def family_map(rows):
    return OrderedDict((int(row['route_id']), family_of(row)) for row in rows)


def nonmanual_rows(rows):
    return [row for row in rows if not is_manual(row)]


def manual_rows(rows):
    return [row for row in rows if is_manual(row)]


def family_members(rows):
    """``{family: [rows]}`` for the 6 non-manual families (baseline order)."""
    grouped = OrderedDict((name, []) for name in FAMILIES)
    for row in rows:
        if is_manual(row):
            continue
        grouped[family_of(row)].append(row)
    return grouped


def port_sort_key(row):
    """Deterministic ordering of a family's rows along its source side.

    For Z1 vertical/horizontal families the connecting chord is essentially
    controlled by the source coordinate along its side, so routing proximity is
    preserved when a family is split over several planes in this order.
    """
    side = str(row.get('source_side') or '')
    x = float(row.get('source_x_mm'))
    y = float(row.get('source_y_mm'))
    if side in ('N', 'S'):
        return (0, x, y)
    return (1, y, x)


# ------------------------------------------------------------------- geometry
def body_part(route):
    """The flat body part of one assembled 3D route (on its target plane)."""
    target = route.get('target_layer', route.get('target_plane'))
    try:
        target = int(target)
    except (TypeError, ValueError):
        target = None
    flats = [part for part in (route.get('parts') or [])
             if isinstance(part, dict) and part.get('kind') == 'flat']
    if target is not None:
        for part in flats:
            try:
                if int(part.get('layer_id')) == target:
                    return part
            except (TypeError, ValueError):
                continue
    if len(flats) == 1:
        return flats[0]
    return None


def body_primitives(route):
    part = body_part(route)
    if part is None:
        return None
    return [dict(prim) for prim in (part.get('primitives') or [])]


def flat_parts(route):
    return [part for part in (route.get('parts') or [])
            if isinstance(part, dict) and part.get('kind') == 'flat']


def route_records(payload_or_path):
    """Route records of ``routes_l3d.json`` (payload or path)."""
    payload = payload_or_path
    if isinstance(payload_or_path, (str, Path)):
        payload = load_json(payload_or_path)
    return [record for record in (payload.get('routes') or [])
            if str(record.get('status') or '').lower() != 'failed']


# ------------------------------------------------------------------ endpoints
def endpoints():
    return C.endpoints()


def endpoint_pose(endpoint_id):
    return C.endpoint_pose(endpoint_id)


def route_families(rows=None):
    rows = rows if rows is not None else load_baseline_assignment()
    return family_map(rows)


def family_counts(rows=None):
    rows = rows if rows is not None else load_baseline_assignment()
    counts = Counter(family_of(row) for row in rows)
    return OrderedDict(sorted(counts.items()))


# ------------------------------------------------------------------ baseline
def baseline_routes():
    return route_records(P.BASELINE_21H_DIR / 'routes_l3d.json')


def baseline_assignment():
    return load_baseline_assignment()


def baseline_fanout_selected():
    payload = load_json(P.BASELINE_21H_DIR / 'fanout_selected.json')
    return {int(rid): value for rid, value in (payload.get('selected') or {}).items()}


def baseline_crossing_stats():
    return load_json(P.BASELINE_21H_DIR / 'crossing_stats.json')


def layer_planes(exp_dir):
    return load_json(Path(exp_dir) / 'layer_planes.json')


def plane_z_map(exp_dir=None):
    if exp_dir is None:
        return OrderedDict((int(pid), float(M.plane_z(pid))) for pid in M.PLANE_IDS)
    payload = layer_planes(exp_dir)
    return OrderedDict((int(item['plane_id']), float(item['z_mm']))
                       for item in payload['planes'])


def plane_label_map(exp_dir=None):
    if exp_dir is None:
        return OrderedDict((int(pid), M.plane_label(pid)) for pid in M.PLANE_IDS)
    payload = layer_planes(exp_dir)
    return OrderedDict((int(item['plane_id']), item['label'])
                       for item in payload['planes'])


def manual_groups(rows=None):
    rows = rows if rows is not None else load_baseline_assignment()
    grouped = defaultdict(list)
    for row in rows:
        group = str(row.get('manual_group') or '').strip()
        if group:
            grouped[group].append(row)
    return OrderedDict(sorted(grouped.items()))
