# -*- coding: utf-8 -*-
"""Shared constants / loaders for the Native 3D experiment."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path

from .. import common as C
from ..reheight21 import model as M

# ---------------------------------------------------------------- directories
ROOT = C.ROOT
OUTPUT_ROOT = C.OUTPUT_ROOT
#: frozen accepted C4-free baseline (E5) -- READ ONLY
E5_DIR = OUTPUT_ROOT / 'NON_C4_CROSSING_OPT_1024' / 'E5_joint_repair_final'
#: previous balanced 21-height success baseline (READ ONLY)
BASELINE_21H_DIR = OUTPUT_ROOT / 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'
#: new experiment root
RUN_DIR = OUTPUT_ROOT / 'NATIVE_3D_CROSSING_OPT_1024'

#: path length used by the 3D S-curves
R15 = 15.0
MIN_3D_CLEARANCE = 0.05
#: transition "shadow": horizontal distance where the S-curve is still closer
#: than 50 um to the plane it leaves ( h = d^2 / (2R) -> d = sqrt(2*R*gap) )
SHADOW_MM = math.sqrt(2.0 * R15 * MIN_3D_CLEARANCE)   # 1.2247 mm
#: minimum flat length at the travel height between the two S-curves
MIN_MIDDLE_MM = 1.0
#: practical upper bound for a single excursion (mm at the travel height)
MAX_MIDDLE_MM = 120.0

# ---------------------------------------------------------------- heights
#: the 13 non-manual routing heights usable by movable routes
MOVABLE_PLANES = (6, 7, 20, 1001, 8, 9, 14, 15, 16, 1002, 17, 18, 19)
MANUAL_PLANES = tuple(int(pid) for pid in M.MANUAL_PLANE_IDS)

PLANE_Z = OrderedDict((int(pid), float(M.plane_z(pid))) for pid in M.PLANE_IDS)
Z_PLANE = OrderedDict((round(z, 9), int(pid)) for pid, z in PLANE_Z.items())
PLANE_LABEL = OrderedDict((int(pid), M.plane_label(pid)) for pid in M.PLANE_IDS)


def plane_of_z(z_mm, tol=1e-6):
    """Plane id whose physical z equals ``z_mm`` (None when not a 21-height)."""
    key = round(float(z_mm), 9)
    if key in Z_PLANE:
        return Z_PLANE[key]
    for plane_id, z in PLANE_Z.items():
        if abs(z - float(z_mm)) <= tol:
            return plane_id
    return None


def z_of_plane(plane_id):
    return float(PLANE_Z[int(plane_id)])


def movable_heights():
    return [float(PLANE_Z[pid]) for pid in MOVABLE_PLANES]


def all_heights():
    """Every one of the 21 physical routing heights (manual planes included)."""
    return [float(z) for z in PLANE_Z.values()]


def sorted_by_abs_dz(z_from, plane_ids=None):
    plane_ids = list(plane_ids if plane_ids is not None else MOVABLE_PLANES)
    return sorted(plane_ids, key=lambda pid: (abs(PLANE_Z[pid] - z_from),
                                              PLANE_Z[pid]))


# ---------------------------------------------------------------- io helpers
def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    return C.write_json(Path(path), payload)


def load_e5_payload(run_dir=None):
    run_dir = Path(run_dir or E5_DIR)
    return load_json(run_dir / 'routes_l3d.json')


def load_routes(run_dir=None):
    payload = load_e5_payload(run_dir)
    return payload, [record for record in payload['routes']
                     if str(record.get('status') or '') != 'failed']


def routes_by_id(routes):
    return {int(route['route_id']): route for route in routes}


def load_assignment(run_dir=None):
    run_dir = Path(run_dir or E5_DIR)
    rows, digest = C.read_csv_rows(run_dir / 'assignment_1024.csv')
    return rows, digest


def assignment_by_id(rows):
    return {int(row['route_id']): row for row in rows}


# ---------------------------------------------------------------- part helpers
def flat_parts(route):
    return [(index, part) for index, part in enumerate(route.get('parts') or ())
            if part.get('kind') == 'flat']


def transition_parts(route):
    return [(index, part) for index, part in enumerate(route.get('parts') or ())
            if part.get('kind') == 'transition']


def is_direct(route):
    return int(route.get('n_transitions') or 0) == 0


def body_flat_indices(route):
    """Indices of the body flat parts (lead flats at the interface excluded).

    Baseline convention: a non-direct route is
    ``[lead?, transition, body, transition, lead?]``; a direct route is a single
    flat body at its interface height.  Native routes may have more body flats.
    """
    flats = flat_parts(route)
    if is_direct(route):
        return [index for index, _part in flats]
    if not flats:
        return []
    return [index for index, _part in flats[1:-1]]


def body_flats(route):
    return [(index, route['parts'][index]) for index in body_flat_indices(route)]


def prim_length(prim):
    if prim.get('kind') == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if prim.get('kind') == 'arc':
        return abs(float(prim['radius']) * float(prim['sweep']))
    raise ValueError('unknown primitive kind %r' % prim.get('kind'))


def chain_length(primitives):
    return float(sum(prim_length(prim) for prim in primitives or ()))


def part_length(part):
    if part.get('kind') == 'flat':
        value = part.get('length_mm')
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = None
        return value if value is not None else chain_length(part.get('primitives'))
    return float(part.get('length_mm') or 0.0)


def is_manual_route(route, assignment=None):
    if str(route.get('manual_group') or '').strip():
        return True
    if assignment is not None:
        row = assignment.get(int(route['route_id'])) or {}
        return bool(str(row.get('manual_group') or '').strip())
    return False


# ---------------------------------------------------------------- metadata
def rebuild_route_metadata(route, interface_z=None):
    """Recompute the derived route fields from the actual parts (native-safe)."""
    route = copy.deepcopy(route)
    parts = route['parts']
    body_indices = body_flat_indices(route)
    body_heights = [float(route['parts'][index]['z_mm']) for index in body_indices]
    if not body_heights:  # defensive: use all flats
        body_heights = [float(part['z_mm']) for _index, part in flat_parts(route)]
    transitions = transition_parts(route)
    n_transitions = len(transitions)
    mid_transitions = []
    for index, part in transitions:
        mid_transitions.append(dict(part_index=int(index),
                                    from_z=float(part['z0']),
                                    to_z=float(part['z1']),
                                    tag=part.get('tag') or ''))
    native_indices = [item for item in mid_transitions
                      if item['tag'] == 'mid']
    if interface_z is None:
        interface_z = float(route.get('start_z_mm',
                                      body_heights[0] if body_heights else 0.0))
    if route.get('n_transitions') == 0 or route.get('start_z_mm') is None:
        interface_z = float(route.get('start_z_mm') or interface_z)
    plane_ids = []
    for z in body_heights:
        pid = plane_of_z(z)
        if pid is None:
            raise ValueError('body height %.6f is not one of the 21 heights' % z)
        plane_ids.append(int(pid))
    # primary body plane = plane of the longest body flat
    longest = max(body_indices, key=lambda index: part_length(route['parts'][index])) \
        if body_indices else None
    primary_z = float(route['parts'][longest]['z_mm']) if longest is not None else body_heights[0]
    target_layer = int(plane_of_z(primary_z))
    route['target_layer'] = target_layer
    route['target_plane'] = target_layer
    route['target_plane_label'] = PLANE_LABEL.get(target_layer, str(target_layer))
    route['target_z_mm'] = primary_z
    if n_transitions == 0:
        route['layer_sequence'] = [target_layer]
        route['layer_z_sequence'] = [primary_z]
        route['layers_used'] = [target_layer]
        route['start_z_mm'] = primary_z
        route['end_z_mm'] = primary_z
        route['lifted'] = False
    else:
        route['layer_sequence'] = [1] + plane_ids + [1]
        route['layer_z_sequence'] = [interface_z] + body_heights + [interface_z]
        route['layers_used'] = [1] + sorted(set(plane_ids))
        route['start_z_mm'] = interface_z
        route['end_z_mm'] = interface_z
        route['lifted'] = True
    route['n_transitions'] = n_transitions
    route['n_mid_transitions'] = len(native_indices)
    route['native_3d'] = bool(native_indices) or bool(route.get('native_3d'))
    route['body_heights'] = body_heights
    route['mid_transitions'] = native_indices
    route['length_mm'] = round(sum(part_length(part) for part in parts), 9)
    route['xy_length_mm'] = round(
        sum(chain_length(part.get('primitives')) for _i, part in flat_parts(route))
        + sum(float(part.get('footprint_mm') or 0.0)
              for _i, part in transitions), 9)
    if body_heights:
        route['z_span_mm'] = round(max(body_heights) - min(body_heights), 9)
    if n_transitions == 0:
        route['z_span_mm'] = 0.0
    return route


def route_heights(route):
    """Ordered list of the physical heights the route visits (flat parts)."""
    return [float(part['z_mm']) for _index, part in flat_parts(route)]


def excursion_summary(route):
    return [dict(item) for item in route.get('excursions') or ()]
