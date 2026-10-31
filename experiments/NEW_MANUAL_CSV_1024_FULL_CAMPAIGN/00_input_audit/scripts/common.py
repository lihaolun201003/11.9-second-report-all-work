# -*- coding: utf-8 -*-
"""Shared helpers for the independent input audit of the new manual 1024-channel CSVs.

Only reads the project's frozen port model / manual CSVs; writes nothing.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
AUDIT = ROOT / 'outputs' / 'manual_c4_new_connectivity' / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN' / '00_input_audit'
EXPORTS = ROOT / 'manual_z1_router' / 'data' / 'exports'
OLD_CAMPAIGN = ROOT / 'outputs' / 'manual_c4_new_connectivity' / 'inputs'
NEW_CAMPAIGN = ROOT / 'outputs' / 'manual_c4_new_connectivity' / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN' / 'inputs'

Z1_NEW = EXPORTS / 'manual_z1_c4_full_section2.csv'
Z2_NEW = EXPORTS / 'manual_z2_c4_full_section2.csv'
Z1_OLD = EXPORTS / 'manual_z1_c4_full.csv'
Z2_OLD = EXPORTS / 'manual_z2_c4_full.csv'
Z1_OLD_CAMPAIGN = OLD_CAMPAIGN / 'manual_z1_c4_full.csv'
Z2_OLD_CAMPAIGN = OLD_CAMPAIGN / 'manual_z2_c4_full.csv'
OLD_COMBINED = OLD_CAMPAIGN / 'connectivity_1024.csv'
NEW_CAMPAIGN_Z2_EXPANDED = NEW_CAMPAIGN / 'manual_z2_c4_full_section2_expanded_row2.csv'
NEW_CAMPAIGN_COMBINED = NEW_CAMPAIGN / 'connectivity_1024.csv'

BOARD_MM = 150.0
TOL = 1e-9
SIDES = 'NSEW'
MANUAL_FIELDS = ['route_id', 'source_side', 'source_connector', 'source_row',
                 'source_column', 'source_channel', 'target_side', 'target_connector',
                 'target_row', 'target_column', 'target_channel', 'relation',
                 'source_port_id', 'target_port_id', 'source_x_mm', 'source_y_mm',
                 'target_x_mm', 'target_y_mm', 'layer']
COMBINED_FIELDS = ['route_id', 'source_side', 'source_connector', 'source_row',
                   'source_column', 'source_channel', 'target_side', 'target_connector',
                   'target_row', 'target_column', 'target_channel', 'relation']
PLANES = ('z1', 'z2')
Z_MM = {'z1': 0.0, 'z2': 0.5}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fslw.ports import build_plane_endpoints  # noqa: E402
from four_side_1024.inputs import board_xy  # noqa: E402


# ---------------------------------------------------------------------------
# basic IO / hashing
# ---------------------------------------------------------------------------
def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_manual_csv(path):
    """Read one manual CSV preserving encoding facts; returns a descriptive dict."""
    raw = Path(path).read_bytes()
    bom = raw[:3] == b'\xef\xbb\xbf'
    text = raw.decode('utf-8-sig')
    lines = text.splitlines()
    crlf_only = b'\n' not in raw.replace(b'\r\n', b'')
    reader = csv.DictReader(lines)
    rows = list(reader)
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw), bom=bom, crlf_only=crlf_only,
                line_count=len(lines), header=list(reader.fieldnames or []),
                data_lines=len(lines) - 1, rows=rows)


def read_plain_csv(path):
    raw = Path(path).read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    reader = csv.DictReader(raw.decode('utf-8-sig').splitlines())
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw), header=list(reader.fieldnames or []), rows=rows)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding='utf-8')
    return path


def write_csv(path, fieldnames, rows, bom=True, crlf=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = 'utf-8-sig' if bom else 'utf-8'
    with path.open('w', encoding=encoding, newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                lineterminator='\r\n' if crlf else '\n')
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# frozen port model
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def endpoints():
    return build_plane_endpoints()


@lru_cache(maxsize=1)
def coord_index():
    index = {}
    for eid, ep in endpoints().items():
        key = (round(float(ep['routing_xy'][0]), 6),
               round(float(ep['routing_xy'][1]), 6),
               float(ep['z_mm']))
        if key in index:
            raise ValueError(f'duplicate endpoint coordinate {key}')
        index[key] = eid
    return index


@lru_cache(maxsize=1)
def rot90_map():
    idx = coord_index()
    mapping = {}
    for eid, ep in endpoints().items():
        x, y = ep['routing_xy']
        mapping[eid] = idx[(round(BOARD_MM - float(y), 6), round(float(x), 6),
                            float(ep['z_mm']))]
    # rotation must be a fixed-point-free involution-power-4 permutation
    for eid in mapping:
        if mapping[mapping[mapping[mapping[eid]]]] != eid:
            raise ValueError(f'rot90 is not order-4 for {eid}')
    return mapping


def rot90_port(eid):
    return rot90_map()[eid]


def rot_power(step):
    rot = rot90_map()
    power = {}
    for eid in endpoints():
        cur = eid
        for _ in range(step):
            cur = rot[cur]
        power[eid] = cur
    return power


def plane_ports(plane):
    return {eid for eid, ep in endpoints().items() if ep['plane'] == plane}


def connector_names():
    return [f'{s}{i:02d}' for s in SIDES for i in range(1, 17)]


@lru_cache(maxsize=1)
def connector_centers():
    return {f'{s}{i:02d}': tuple(board_xy(s, 7.5 + (i - 1) * 9.0))
            for s in SIDES for i in range(1, 17)}


def row1_to_row2(eid):
    ep = endpoints()[eid]
    return f"{ep['connector']}:2:{ep['column']}"


# ---------------------------------------------------------------------------
# CSV row helpers
# ---------------------------------------------------------------------------
def ep_of(row, role):
    return f"{row[role + '_connector']}:{row[role + '_row']}:{row[role + '_column']}"


def relation_of_sides(a, b):
    if a == b:
        return 'same'
    return 'opposite' if {a, b} in ({'N', 'S'}, {'E', 'W'}) else 'adjacent'


def canonical_connection(a, b):
    return tuple(sorted((a, b)))


def side_pair(a, b):
    return ''.join(sorted((a, b)))


# ---------------------------------------------------------------------------
# Z2 C4 expansion (single independent implementation used by all stages)
# ---------------------------------------------------------------------------
def load_z2_expansion():
    """Expand the 128 base rows (legacy row-1 ids) by real C4 rotation on z2 ports.

    Returns a dict with the base rows, the row-1 -> row-2 remap evidence, the
    512 expanded connections (physical z2 ids, deterministic route ids 1..512)
    and structural counters.  Pure function of the frozen inputs.
    """
    base = read_manual_csv(Z2_NEW)
    eps = endpoints()
    rot = rot90_map()
    # equivalence of rotation between the legacy row-1 labels and physical row-2 ids
    equivalence_mismatch = []
    for eid, ep in eps.items():
        if ep['row'] != 1:
            continue
        if row1_to_row2(rot[eid]) != rot[row1_to_row2(eid)]:
            equivalence_mismatch.append(eid)
    base_conns = []
    for row in base['rows']:
        src = ep_of(row, 'source')
        tgt = ep_of(row, 'target')
        p_src, p_tgt = row1_to_row2(src), row1_to_row2(tgt)
        rel = relation_of_sides(eps[p_src]['side'], eps[p_tgt]['side'])
        base_conns.append(dict(base_route_id=int(row['route_id']),
                               source=src, target=tgt,
                               plane2_source=p_src, plane2_target=p_tgt,
                               relation=rel,
                               csv_relation=row['relation']))
    per_base = {}
    conflicts = []
    for conn in base_conns:
        orbit = []
        a, b = conn['plane2_source'], conn['plane2_target']
        for phase in range(4):
            orbit.append(canonical_connection(a, b))
            a, b = rot[a], rot[b]
        per_base[conn['base_route_id']] = orbit
    ordered = []
    seen_conn = {}
    for conn in sorted(base_conns, key=lambda c: c['base_route_id']):
        orbit = per_base[conn['base_route_id']]
        for phase, key in enumerate(orbit):
            if key in seen_conn:
                conflicts.append(dict(base_route_id=conn['base_route_id'],
                                      other_base=seen_conn[key], phase=phase,
                                      connection=list(key)))
                continue
            seen_conn[key] = conn['base_route_id']
            ordered.append(dict(ex_base_route_id=conn['base_route_id'],
                                phase=phase * 90,
                                source=key[0], target=key[1],
                                relation=relation_of_sides(
                                    eps[key[0]]['side'], eps[key[1]]['side'])))
    for index, cell in enumerate(ordered, start=1):
        cell['route_id'] = index
    return dict(base=base, base_conns=base_conns, per_base=per_base,
                expanded=ordered, conflicts=conflicts,
                equivalence_mismatch=equivalence_mismatch)


def expanded_row(cell):
    """19-column manual CSV row for one expanded c4 connection (physical z2)."""
    eps = endpoints()
    se, te = eps[cell['source']], eps[cell['target']]
    out = dict(route_id=cell['route_id'],
               source_side=se['side'], source_connector=se['connector'],
               source_row=int(se['row']), source_column=int(se['column']),
               source_channel=int(se['channel']),
               target_side=te['side'], target_connector=te['connector'],
               target_row=int(te['row']), target_column=int(te['column']),
               target_channel=int(te['channel']),
               relation=cell['relation'],
               source_port_id=cell['source'], target_port_id=cell['target'],
               source_x_mm=float(se['routing_xy'][0]),
               source_y_mm=float(se['routing_xy'][1]),
               target_x_mm=float(te['routing_xy'][0]),
               target_y_mm=float(te['routing_xy'][1]),
               layer='z2')
    return out


# ---------------------------------------------------------------------------
# combined 1024 topology (Z1 rows as-is, Z2 expanded renumbered 513..1024)
# ---------------------------------------------------------------------------
def load_combined():
    z1 = read_manual_csv(Z1_NEW)
    z2 = load_z2_expansion()
    eps = endpoints()
    rows = []
    for row in z1['rows']:
        rid = int(row['route_id'])
        src, tgt = ep_of(row, 'source'), ep_of(row, 'target')
        rows.append(dict(route_id=rid, plane='z1',
                         source=src, target=tgt,
                         source_side=row['source_side'],
                         target_side=row['target_side'],
                         relation=relation_of_sides(eps[src]['side'],
                                                    eps[tgt]['side']),
                         csv_relation=row['relation'],
                         layer=row['layer'],
                         source_row=int(row['source_row']),
                         target_row=int(row['target_row']),
                         source_connector=row['source_connector'],
                         target_connector=row['target_connector'],
                         source_column=int(row['source_column']),
                         target_column=int(row['target_column']),
                         source_channel=int(row['source_channel']),
                         target_channel=int(row['target_channel']),
                         source_x_mm=float(row['source_x_mm']),
                         source_y_mm=float(row['source_y_mm']),
                         target_x_mm=float(row['target_x_mm']),
                         target_y_mm=float(row['target_y_mm']),
                         pair=side_pair(row['source_side'], row['target_side']),
                         z_mm=Z_MM['z1']))
    for cell in z2['expanded']:
        src, tgt = cell['source'], cell['target']
        se, te = eps[src], eps[tgt]
        rows.append(dict(route_id=cell['route_id'] + 512, plane='z2',
                         source=src, target=tgt,
                         source_side=se['side'], target_side=te['side'],
                         relation=cell['relation'], csv_relation=cell['relation'],
                         layer='z2', source_row=int(se['row']),
                         target_row=int(te['row']),
                         source_connector=se['connector'],
                         target_connector=te['connector'],
                         source_column=int(se['column']),
                         target_column=int(te['column']),
                         source_channel=int(se['channel']),
                         target_channel=int(te['channel']),
                         source_x_mm=float(se['routing_xy'][0]),
                         source_y_mm=float(se['routing_xy'][1]),
                         target_x_mm=float(te['routing_xy'][0]),
                         target_y_mm=float(te['routing_xy'][1]),
                         pair=side_pair(se['side'], te['side']),
                         z_mm=Z_MM['z2'],
                         ex_base_route_id=cell['ex_base_route_id'],
                         ex_phase=cell['phase']))
    rows.sort(key=lambda r: r['route_id'])
    return dict(z1=z1, z2=z2, routes=rows)


# ---------------------------------------------------------------------------
# C4 orbit analysis of one connection set
# ---------------------------------------------------------------------------
def rotation_analysis(connections, plane=None):
    """Closure at 90/180/270 + orbit size histogram + relation mix of 4-orbits.

    ``connections`` is a list of (source_eid, target_eid) using ids of one plane.
    """
    eps = endpoints()
    rot = rot90_map()
    pairs = {}
    for src, tgt in connections:
        key = frozenset((src, tgt))
        if key in pairs:
            raise ValueError(f'duplicate unordered connection {sorted(key)}')
        pairs[key] = (src, tgt)
    closure = {}
    for step in (1, 2, 3):
        power = rot_power(step)
        missing = [p for p in pairs
                   if frozenset(power[e] for e in p) not in pairs]
        closure[f'{step * 90}deg'] = len(missing)
    seen, sizes = set(), Counter()
    orbit_kinds = Counter()
    orbit_relations = Counter()
    orbit_ids = []
    for p in pairs:
        if p in seen:
            continue
        orbit, cur = [], p
        while cur not in seen and len(orbit) <= 5:
            orbit.append(cur)
            seen.add(cur)
            cur = frozenset(rot[e] for e in cur)
        sizes[str(len(orbit))] += 1
        # relation of a connection is well-defined from its two sides
        src, tgt = pairs[orbit[0]]
        rel = relation_of_sides(eps[src]['side'], eps[tgt]['side'])
        orbit_relations[rel] += 1
        orbit_ids.append([sorted(pairs[k]) for k in orbit])
    return dict(connections=len(pairs), closure_missing=closure,
                orbit_size_histogram=dict(sizes),
                orbit_relations=dict(orbit_relations),
                orbits=orbit_ids)
