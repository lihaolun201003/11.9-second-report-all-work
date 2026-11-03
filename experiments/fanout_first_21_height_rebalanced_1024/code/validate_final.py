# -*- coding: utf-8 -*-
"""Independent final validator for the fanout-first Z2-manual-verified 1024 run.

This module is the *independent authority* of the round.  It never trusts the
route builder: it reloads ``routes_l3d.json`` from disk, rebuilds a fresh
``four_side_1024.l3d.world.World`` from ``fanout1024.common.layer_stack()`` with
the confirmed 50 um true-3D clearance, and re-checks every routed route.

Checks (all reported with real route ids, failures are never hidden):

a. structure / continuity / port poses / declared route fields,
b. R15: every flat arc is exactly 15 mm and every transition S-curve has true
   sampled 3D curvature radius >= 15 mm - 1e-6,
c. glass bounds (x, y in [0, 150], z in [-0.35, +0.65]) + edge margin report,
d. true 3D clearance: fresh ``World(layer_stack, clearance=0.05)`` and
   ``check_route(..., check_self=True)`` for every route in route-id order,
   plus an exact-ish minimum 3D centreline distance scan,
e. port coverage / identity / uniqueness against ``common.routes()``,
f. layer assignment audit against ``assignment_1024.csv`` + fixed manual layers,
g. validator-vs-online-world consistency spot checks on the 50/49 um boundary,
h. same-physical-plane strict D56 pair audit (legal crossings exempt) and
   crossing / length / transition counts.

CLI::

    python -m four_side_1024.fanout1024.validate_final \
        [--routes PATH] [--assignment PATH] [--out PATH] \
        [--consistency-out PATH] [--run-dir DIR] [--skip-min-clearance] \
        [--skip-crossings]

Exit codes: 0 = no violation, 1 = geometry/contract violations, 2 = the
validator's own consistency self-tests failed.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np

from . import common
from ..fsd25d import path3d as P
from ..l3d.world import World

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = common.OUTPUT_ROOT
RUN_DIR = common.RUN_DIR
PREV_DIR = common.PREV_DIR

VALIDATOR_SCHEMA = 'fanout_first_z2_manual_verified_1024_validation_v1'
CONSISTENCY_SCHEMA = 'fanout_first_z2_manual_verified_1024_consistency_v1'

# -- tolerances -------------------------------------------------------------
TOL_POS_MM = 1e-6            # part/port position continuity
TOL_Z_MM = 1e-6              # part/port height continuity
TOL_RADIUS_MM = 1e-6         # every flat arc must be exactly 15 mm
TOL_LEN_FIELD_MM = 1e-4      # declared length fields
TOL_FIELD_Z_MM = 1e-6        # declared z sequences
TOL_TANGENT = 1e-6           # unit tangent continuity
TOL_GLASS_MM = 1e-6          # centerline glass bound tolerance
TOL_PLANE_GAP_MM = 1e-9      # layer pitch comparison epsilon
R15_MM = 15.0
MIN_R15_SAMPLED_MM = R15_MM - 1e-6
GLASS_XY_MM = 150.0
GLASS_Z_MIN_MM = -0.35
GLASS_Z_MAX_MM = 0.65
WAVEGUIDE_HALF_WIDTH_MM = common.WIDTH_MM / 2.0
MIN_3D_CLEARANCE_MM = 0.05
D56_CLEARANCE_MM = common.CLEARANCE_2D_MM       # width 0.05 + edge gap 0.03
SAGITTA_MM = 0.0005
INTERFACE_LAYER_ID = 1
TRANSITION_SAMPLE_STEP_MM = 0.01                # dense sampling of true 3D curvature
CURVATURE_JOIN_MIN_LENGTH_MM = 1e-9
ARC_SAMPLE_STEP_MM = 0.05
GLASS_TRANSITION_STEP_MM = 0.02

ROUTED_STATUSES = {'routed', 'ok', 'success', 'valid', 'accepted', 'done'}
FAILED_STATUSES = {'failed', 'fail', 'error', 'unrouted', 'invalid', 'rejected'}
FAILED_REASON_KEYS = ('reason', 'failure_reason', 'error', 'fail_reason',
                      'detail', 'message')

#: manual group -> fixed physical layer (new naming, DESIGN.md section 1)
MANUAL_GROUP_LAYER = OrderedDict([
    ('Z1-U1', 2), ('Z1-U2', 3), ('Z1-U3', 4), ('Z1-U4', 5),
    ('Z2-U1', 10), ('Z2-U2', 11), ('Z2-U3', 12), ('Z2-U4', 13),
])
#: previous-round naming of the same four Z1 groups (comparison baseline only)
MANUAL_GROUP_ALIASES = {'NS-1': 'Z1-U1', 'NS-2': 'Z1-U2',
                        'EW-1': 'Z1-U3', 'EW-2': 'Z1-U4'}
MANUAL_LAYERS = {2, 3, 4, 5, 10, 11, 12, 13}


# ===========================================================================
# small helpers
# ===========================================================================
def _now():
    return datetime.now().isoformat(timespec='seconds')


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + '\n', encoding='utf-8')
    return path


def _round(value, digits=9):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), digits)


def _layer_z(layer_id):
    """True physical z of a routing layer (interface L1 has no single z)."""
    if int(layer_id) == INTERFACE_LAYER_ID:
        return None
    return float(common.PHYSICAL_LAYERS[int(layer_id)])


def _is_interface_layer(layer_id):
    try:
        return int(layer_id) == INTERFACE_LAYER_ID
    except (TypeError, ValueError):
        return False


def normalize_status(record):
    """Return 'routed' / 'failed' for one route record (default routed)."""
    status = record.get('status')
    if status is None:
        return 'routed'
    text = str(status).strip().lower()
    if text in ROUTED_STATUSES:
        return 'routed'
    if text in FAILED_STATUSES:
        return 'failed'
    # unknown status is never silently promoted to success
    return 'failed'


def failure_reason(record):
    for key in FAILED_REASON_KEYS:
        value = record.get(key)
        if value not in (None, ''):
            return str(value)
    return str(record.get('status') or 'unknown')


def load_payload(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'routes file not found: {path}')
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f'routes file must be a JSON object, got {type(payload)}')
    records = payload.get('routes')
    if records is None:
        records = payload.get('routes_l3d')
    if not isinstance(records, list):
        raise ValueError('routes file has no "routes" list')
    return payload, records


def split_records(records):
    """Split into (routed records, failed records) keeping real route ids."""
    routed, failed = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        if normalize_status(record) == 'routed':
            routed.append(record)
        else:
            failed.append(record)
    routed.sort(key=lambda item: int(item.get('route_id', 0)))
    failed.sort(key=lambda item: int(item.get('route_id', 0)))
    return routed, failed


def build_true_routes():
    """Ground-truth 1024 route table (identity, plane, endpoint pairs)."""
    routes = common.routes()
    return {int(route['route_id']): route for route in routes}


def _route_ids(records):
    ids = []
    for record in records:
        try:
            ids.append(int(record.get('route_id')))
        except (TypeError, ValueError):
            ids.append(None)
    return ids


def _route_plane(record):
    plane = record.get('plane')
    if plane is None:
        for key in ('source_endpoint', 'target_endpoint'):
            endpoint = record.get(key)
            if endpoint in common.endpoints():
                return str(common.endpoints()[endpoint].get('plane'))
        return None
    return str(plane)


def interface_z_of_plane(plane):
    return float(common.INTERFACE_Z[str(plane)])


def prim_xy(point):
    return (float(point[0]), float(point[1]))


def _finite_xy(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def _prim_tangent(prim, t):
    return P.prim_tangent_at(prim, t)


def _part_flat_z(part):
    try:
        return float(part.get('z_mm'))
    except (TypeError, ValueError):
        return None


def body_flat_parts(route):
    """Flat parts that are not on the interface layer (body/travel parts)."""
    out = []
    for index, part in enumerate(route.get('parts') or []):
        if part.get('kind') != 'flat':
            continue
        if _is_interface_layer(part.get('layer_id')):
            continue
        out.append((index, part))
    return out


def route_body_layer_z(route):
    """(layer_id, z_mm) of the single body flat of a canonical route, or None."""
    bodies = body_flat_parts(route)
    if not bodies:
        return None
    index, part = bodies[0]
    return (int(part['layer_id']), float(part['z_mm']))


def manual_group_layer(name):
    """Fixed physical layer of a manual group name (new or old naming)."""
    if name is None:
        return None
    text = str(name).strip()
    if not text:
        return None
    if text in MANUAL_GROUP_LAYER:
        return MANUAL_GROUP_LAYER[text]
    if text in MANUAL_GROUP_ALIASES:
        return MANUAL_GROUP_LAYER[MANUAL_GROUP_ALIASES[text]]
    return None


def read_assignment(path):
    """Read assignment_1024.csv -> (rows_by_route_id, duplicate_column_names)."""
    path = Path(path)
    if not path.exists():
        return None, []
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        duplicates = sorted({name for name in fieldnames
                             if fieldnames.count(name) > 1 and name})
        rows = {}
        for row in reader:
            try:
                route_id = int(str(row.get('route_id')).strip())
            except (TypeError, ValueError):
                continue
            rows[route_id] = row
    return rows, duplicates


# ===========================================================================
# a) structure / continuity / port poses / declared fields
# ===========================================================================
def _check_primitive_list(route_id, part_index, primitives, violations):
    """Structural sanity of one flat part's primitive chain."""
    if not isinstance(primitives, list) or not primitives:
        violations.append(dict(kind='empty_flat_part',
                               route_id=route_id,
                               detail=f'part={part_index} has no primitives'))
        return
    previous = None
    for index, prim in enumerate(primitives):
        if not isinstance(prim, dict):
            violations.append(dict(kind='primitive_not_mapping',
                                   route_id=route_id,
                                   detail=f'part={part_index} prim={index}'))
            continue
        kind = prim.get('kind')
        p0 = _finite_xy(prim.get('p0'))
        p1 = _finite_xy(prim.get('p1'))
        if p0 is None or p1 is None:
            violations.append(dict(kind='primitive_missing_endpoints',
                                   route_id=route_id,
                                   detail=f'part={part_index} prim={index}'))
            previous = None
            continue
        if kind == 'line':
            if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) <= 1e-12:
                violations.append(dict(kind='zero_length_line',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
        elif kind == 'arc':
            try:
                center = _finite_xy(prim.get('center'))
                radius = float(prim.get('radius'))
                start = float(prim.get('start_angle'))
                sweep = float(prim.get('sweep'))
            except (TypeError, ValueError):
                violations.append(dict(
                    kind='arc_missing_parameters', route_id=route_id,
                    detail=f'part={part_index} prim={index}'))
                previous = None
                continue
            if center is None or not (math.isfinite(start) and math.isfinite(sweep)):
                violations.append(dict(kind='arc_invalid_parameters',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
                previous = None
                continue
            if radius <= 0.0:
                violations.append(dict(kind='arc_nonpositive_radius',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index} r={radius!r}'))
            if not (0.0 < abs(sweep) <= 2.0 * math.pi + 1e-12):
                violations.append(dict(kind='arc_invalid_sweep',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index} sweep={sweep!r}'))
            expected_p0 = (center[0] + radius * math.cos(start),
                           center[1] + radius * math.sin(start))
            expected_p1 = (center[0] + radius * math.cos(start + sweep),
                           center[1] + radius * math.sin(start + sweep))
            if math.dist(expected_p0, p0) > TOL_POS_MM:
                violations.append(dict(kind='arc_start_inconsistent',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index} '
                                              f'd={math.dist(expected_p0, p0):.3g}'))
            if math.dist(expected_p1, p1) > TOL_POS_MM:
                violations.append(dict(kind='arc_end_inconsistent',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index} '
                                              f'd={math.dist(expected_p1, p1):.3g}'))
        else:
            violations.append(dict(kind='unknown_primitive_kind',
                                   route_id=route_id,
                                   detail=f'part={part_index} prim={index} kind={kind!r}'))
            previous = None
            continue
        if previous is not None:
            prev_p1 = _finite_xy(previous.get('p1'))
            if prev_p1 is not None and math.dist(prev_p1, p0) > TOL_POS_MM:
                violations.append(dict(
                    kind='flat_primitive_discontinuity', route_id=route_id,
                    detail=f'part={part_index} prim={index} '
                           f'd={math.dist(prev_p1, p0):.3g}'))
                previous = None
                continue
            try:
                tangent_a = _prim_tangent(previous, 1.0)
                tangent_b = _prim_tangent(prim, 0.0)
                tangent_gap = math.hypot(tangent_a[0] - tangent_b[0],
                                         tangent_a[1] - tangent_b[1])
            except (KeyError, ValueError, TypeError):
                tangent_gap = 0.0
            if tangent_gap > TOL_TANGENT:
                violations.append(dict(
                    kind='flat_tangent_discontinuity', route_id=route_id,
                    detail=f'part={part_index} prim={index} '
                           f'tangent_gap={tangent_gap:.3g}'))
        previous = prim


def _check_flat_part(route_id, plane, part_index, part, stack_layer_ids,
                     violations):
    z = _part_flat_z(part)
    if z is None:
        violations.append(dict(kind='flat_missing_z', route_id=route_id,
                               detail=f'part={part_index}'))
        return
    try:
        layer_id = int(part.get('layer_id'))
    except (TypeError, ValueError):
        violations.append(dict(kind='flat_missing_layer_id', route_id=route_id,
                               detail=f'part={part_index}'))
        return
    if layer_id not in stack_layer_ids:
        violations.append(dict(kind='flat_unknown_layer_id', route_id=route_id,
                               detail=f'part={part_index} layer_id={layer_id}'))
    elif layer_id == INTERFACE_LAYER_ID:
        expected = interface_z_of_plane(plane) if plane in common.INTERFACE_Z else None
        if expected is not None and abs(z - expected) > TOL_Z_MM:
            violations.append(dict(kind='interface_flat_wrong_z',
                                   route_id=route_id,
                                   detail=f'part={part_index} z={z!r} expected={expected!r}'))
    else:
        expected = _layer_z(layer_id)
        if expected is None or abs(z - expected) > TOL_Z_MM:
            violations.append(dict(kind='body_flat_wrong_z',
                                   route_id=route_id,
                                   detail=f'part={part_index} layer={layer_id} '
                                          f'z={z!r} expected={expected!r}'))
    primitives = part.get('primitives')
    _check_primitive_list(route_id, part_index, primitives, violations)
    if isinstance(primitives, list) and primitives:
        try:
            length = P.path_length(primitives)
        except (KeyError, ValueError, TypeError):
            length = None
        declared = part.get('length_mm')
        if length is not None and declared is not None:
            try:
                if abs(float(declared) - length) > TOL_LEN_FIELD_MM:
                    violations.append(dict(
                        kind='flat_part_length_mismatch', route_id=route_id,
                        detail=f'part={part_index} declared={declared!r} '
                               f'rebuilt={length:.9g}'))
            except (TypeError, ValueError):
                violations.append(dict(kind='flat_part_length_invalid',
                                       route_id=route_id,
                                       detail=f'part={part_index} {declared!r}'))


def _check_transition(route_id, index, parts, violations):
    part = parts[index]
    prev_part, next_part = parts[index - 1], parts[index + 1]
    for key in ('start', 'direction', 'z0', 'z1', 'end', 'radius_mm',
                'footprint_mm', 'theta_rad', 'length_mm'):
        if key not in part:
            violations.append(dict(kind='transition_missing_field',
                                   route_id=route_id,
                                   detail=f'part={index} field={key}'))
    start = _finite_xy(part.get('start'))
    end = _finite_xy(part.get('end'))
    direction = _finite_xy(part.get('direction'))
    try:
        z0 = float(part.get('z0'))
        z1 = float(part.get('z1'))
        radius = float(part.get('radius_mm'))
        footprint = float(part.get('footprint_mm'))
        theta = float(part.get('theta_rad'))
        length = float(part.get('length_mm'))
    except (TypeError, ValueError):
        z0 = z1 = radius = footprint = theta = length = None
    if start is None or end is None or direction is None or z0 is None:
        return
    norm = math.hypot(direction[0], direction[1])
    if abs(norm - 1.0) > TOL_TANGENT:
        violations.append(dict(kind='transition_direction_not_unit',
                               route_id=route_id,
                               detail=f'part={index} norm={norm:.9g}'))
        if norm > 0.0:
            direction = (direction[0] / norm, direction[1] / norm)
    prev_z = _part_flat_z(prev_part)
    next_z = _part_flat_z(next_part)
    if prev_z is not None and abs(z0 - prev_z) > TOL_Z_MM:
        violations.append(dict(kind='transition_prev_height_mismatch',
                               route_id=route_id,
                               detail=f'part={index} z0={z0!r} prev_z={prev_z!r}'))
    if next_z is not None and abs(z1 - next_z) > TOL_Z_MM:
        violations.append(dict(kind='transition_next_height_mismatch',
                               route_id=route_id,
                               detail=f'part={index} z1={z1!r} next_z={next_z!r}'))
    try:
        prev_prim = prev_part['primitives'][-1]
        next_prim = next_part['primitives'][0]
        prev_end = _finite_xy(prev_prim.get('p1'))
        next_start = _finite_xy(next_prim.get('p0'))
        prev_tangent = _prim_tangent(prev_prim, 1.0)
        next_tangent = _prim_tangent(next_prim, 0.0)
    except (KeyError, IndexError, TypeError, ValueError):
        prev_end = next_start = None
        prev_tangent = next_tangent = None
    if prev_end is not None and math.dist(prev_end, start) > TOL_POS_MM:
        violations.append(dict(kind='transition_start_position_mismatch',
                               route_id=route_id,
                               detail=f'part={index} d={math.dist(prev_end, start):.3g}'))
    if next_start is not None and math.dist(end, next_start) > TOL_POS_MM:
        violations.append(dict(kind='transition_end_position_mismatch',
                               route_id=route_id,
                               detail=f'part={index} d={math.dist(end, next_start):.3g}'))
    if prev_tangent is not None:
        gap = math.hypot(prev_tangent[0] - direction[0],
                         prev_tangent[1] - direction[1])
        if gap > TOL_TANGENT:
            violations.append(dict(kind='transition_start_tangent_mismatch',
                                   route_id=route_id,
                                   detail=f'part={index} gap={gap:.3g}'))
    if next_tangent is not None:
        gap = math.hypot(next_tangent[0] - direction[0],
                         next_tangent[1] - direction[1])
        if gap > TOL_TANGENT:
            violations.append(dict(kind='transition_end_tangent_mismatch',
                                   route_id=route_id,
                                   detail=f'part={index} gap={gap:.3g}'))
    if radius is not None and radius > 0.0 and z0 is not None and z1 is not None:
        dz = abs(z1 - z0)
        if dz <= 0.0:
            violations.append(dict(kind='zero_height_transition',
                                   route_id=route_id, detail=f'part={index}'))
        elif dz > 2.0 * radius + 1e-9:
            violations.append(dict(kind='transition_height_exceeds_diameter',
                                   route_id=route_id,
                                   detail=f'part={index} dz={dz!r} r={radius!r}'))
        else:
            expected_theta = math.acos(max(-1.0, min(1.0, 1.0 - dz / (2.0 * radius))))
            expected_footprint = 2.0 * radius * math.sin(expected_theta)
            expected_length = 2.0 * radius * expected_theta
            if theta is not None and abs(theta - expected_theta) > 1e-6:
                violations.append(dict(kind='transition_theta_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index} declared={theta!r} '
                                              f'expected={expected_theta:.12g}'))
            if footprint is not None and abs(footprint - expected_footprint) > TOL_POS_MM:
                violations.append(dict(kind='transition_footprint_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index} declared={footprint!r} '
                                              f'expected={expected_footprint:.12g}'))
            if length is not None and abs(length - expected_length) > TOL_POS_MM:
                violations.append(dict(kind='transition_length_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index} declared={length!r} '
                                              f'expected={expected_length:.12g}'))
            if footprint is not None:
                moved = math.hypot(end[0] - start[0], end[1] - start[1])
                if abs(moved - footprint) > TOL_POS_MM:
                    violations.append(dict(kind='transition_end_not_on_direction',
                                           route_id=route_id,
                                           detail=f'part={index} moved={moved:.12g} '
                                                  f'footprint={footprint:.12g}'))
                expected_end = (start[0] + direction[0] * footprint,
                                start[1] + direction[1] * footprint)
                if math.dist(expected_end, end) > TOL_POS_MM:
                    violations.append(dict(kind='transition_end_mismatch',
                                           route_id=route_id,
                                           detail=f'part={index} '
                                                  f'd={math.dist(expected_end, end):.3g}'))
    # declared from/to layer ids (optional metadata)
    prev_layer = prev_part.get('layer_id')
    next_layer = next_part.get('layer_id')
    if 'from_layer' in part and prev_layer is not None:
        try:
            if int(part['from_layer']) != int(prev_layer):
                violations.append(dict(kind='transition_from_layer_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index} from={part["from_layer"]!r} '
                                              f'prev_layer={prev_layer!r}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='transition_from_layer_invalid',
                                   route_id=route_id, detail=f'part={index}'))
    if 'to_layer' in part and next_layer is not None:
        try:
            if int(part['to_layer']) != int(next_layer):
                violations.append(dict(kind='transition_to_layer_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index} to={part["to_layer"]!r} '
                                              f'next_layer={next_layer!r}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='transition_to_layer_invalid',
                                   route_id=route_id, detail=f'part={index}'))


def _declared_rebuild(route, parts):
    """Rebuilt declared route fields for contract comparison."""
    flat_lengths, transition_lengths = [], []
    xy_total = 0.0
    z_values = []
    layer_sequence = []
    n_transitions = 0
    for index, part in enumerate(parts):
        if part.get('kind') == 'flat':
            try:
                primitive_length = P.path_length(part.get('primitives') or [])
            except (KeyError, TypeError, ValueError):
                primitive_length = None
            flat_lengths.append(primitive_length)
            if primitive_length is not None:
                xy_total += primitive_length
            if index == 0:
                layer_sequence.append(part.get('layer_id'))
            z = _part_flat_z(part)
            if z is not None:
                z_values.append(z)
        else:
            n_transitions += 1
            try:
                transition_lengths.append(float(part.get('length_mm')))
            except (TypeError, ValueError):
                transition_lengths.append(None)
            try:
                xy_total += float(part.get('footprint_mm'))
            except (TypeError, ValueError):
                pass
            for key in ('z0', 'z1'):
                try:
                    z_values.append(float(part.get(key)))
                except (TypeError, ValueError):
                    pass
            to_layer = part.get('to_layer')
            if to_layer is not None:
                try:
                    layer_sequence.append(int(to_layer))
                except (TypeError, ValueError):
                    pass
            elif index + 1 < len(parts):
                layer_sequence.append(parts[index + 1].get('layer_id'))
    total = None
    if all(value is not None for value in flat_lengths) and \
            all(value is not None for value in transition_lengths):
        total = float(sum(flat_lengths) + sum(transition_lengths))
    z_span = (max(z_values) - min(z_values)) if z_values else 0.0
    return dict(layer_sequence=layer_sequence,
                n_transitions=n_transitions,
                lifted=bool(n_transitions),
                layers_used=sorted({int(part['layer_id'])
                                    for part in parts
                                    if part.get('kind') == 'flat'
                                    and part.get('layer_id') is not None}),
                total_length=total,
                xy_length=xy_total,
                z_span=z_span)


def check_route_structure(route, stack_layer_ids):
    """(a) structure, continuity, port poses, declared route fields."""
    violations = []
    try:
        route_id = int(route.get('route_id'))
    except (TypeError, ValueError):
        violations.append(dict(kind='route_missing_route_id', route_id=None,
                               detail=repr(route.get('route_id'))))
        return violations, {}
    plane = _route_plane(route)
    if plane not in common.INTERFACE_Z:
        violations.append(dict(kind='route_unknown_plane', route_id=route_id,
                               detail=repr(route.get('plane'))))
        return violations, {'plane': plane}
    parts = route.get('parts')
    if not isinstance(parts, list) or not parts:
        violations.append(dict(kind='route_missing_parts', route_id=route_id,
                               detail=repr(type(parts))))
        return violations, {'plane': plane}
    kinds = [part.get('kind') if isinstance(part, dict) else None for part in parts]
    for index, kind in enumerate(kinds):
        if kind not in ('flat', 'transition'):
            violations.append(dict(kind='unknown_part_kind', route_id=route_id,
                                   detail=f'part={index} kind={kind!r}'))
    if kinds and kinds[0] != 'flat':
        violations.append(dict(kind='route_does_not_start_with_flat',
                               route_id=route_id, detail=repr(kinds[0])))
    if kinds and kinds[-1] != 'flat':
        violations.append(dict(kind='route_does_not_end_with_flat',
                               route_id=route_id, detail=repr(kinds[-1])))
    for index in range(1, len(kinds)):
        if kinds[index] == kinds[index - 1] and kinds[index] in ('flat', 'transition'):
            violations.append(dict(kind='parts_do_not_alternate', route_id=route_id,
                                   detail=f'part={index} kind={kinds[index]!r}'))
    # world-side structural check (online code path, raw 1e-9 tolerances)
    try:
        raw_errors = World.check_structure(route)
    except Exception as error:  # noqa: BLE001 - malformed record must be reported
        raw_errors = [f'structure_check_exception:{type(error).__name__}:{error}']
    # per-part checks
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            _check_flat_part(route_id, plane, index, part, stack_layer_ids,
                             violations)
        elif part.get('kind') == 'transition':
            if index == 0 or index == len(parts) - 1:
                violations.append(dict(kind='transition_not_between_flats',
                                       route_id=route_id, detail=f'part={index}'))
            else:
                _check_transition(route_id, index, parts, violations)
    # port poses against the true port table
    endpoints = common.endpoints()
    port_info = {}
    for name, field in (('source', 'source_endpoint'),
                        ('target', 'target_endpoint')):
        endpoint_id = route.get(field)
        if endpoint_id is None:
            violations.append(dict(kind=f'{name}_endpoint_missing_field',
                                   route_id=route_id))
            continue
        if endpoint_id not in endpoints:
            violations.append(dict(kind=f'{name}_endpoint_not_a_port',
                                   route_id=route_id, detail=repr(endpoint_id)))
            continue
        (port_xy, port_inward, port_z) = common.endpoint_pose(str(endpoint_id))
        port_info[name] = dict(endpoint=str(endpoint_id), xy=port_xy,
                               inward=port_inward, z_mm=port_z,
                               plane=str(endpoints[endpoint_id].get('plane')))
        if port_info[name]['plane'] != plane:
            violations.append(dict(kind=f'{name}_endpoint_wrong_plane',
                                   route_id=route_id,
                                   detail=f'{endpoint_id} plane='
                                          f'{port_info[name]["plane"]!r} route={plane!r}'))
        if kinds and kinds[0] == 'flat' and name == 'source':
            prims = parts[0].get('primitives') or []
            start = _finite_xy(prims[0].get('p0')) if prims else None
            if start is None or math.dist(start, port_xy) > TOL_POS_MM:
                violations.append(dict(kind='route_start_not_at_source_port',
                                       route_id=route_id,
                                       detail=f'start={start} port={port_xy}'))
            part_z = _part_flat_z(parts[0])
            if part_z is None or abs(part_z - port_z) > TOL_Z_MM:
                violations.append(dict(kind='route_start_wrong_height',
                                       route_id=route_id,
                                       detail=f'z={part_z!r} port_z={port_z!r}'))
            try:
                tangent = _prim_tangent(prims[0], 0.0)
                gap = math.hypot(tangent[0] - port_inward[0],
                                 tangent[1] - port_inward[1])
                if gap > TOL_TANGENT:
                    violations.append(dict(kind='route_start_tangent_mismatch',
                                           route_id=route_id,
                                           detail=f'tangent={tangent} '
                                                  f'inward={port_inward} gap={gap:.3g}'))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        if kinds and kinds[-1] == 'flat' and name == 'target':
            prims = parts[-1].get('primitives') or []
            end = _finite_xy(prims[-1].get('p1')) if prims else None
            if end is None or math.dist(end, port_xy) > TOL_POS_MM:
                violations.append(dict(kind='route_end_not_at_target_port',
                                       route_id=route_id,
                                       detail=f'end={end} port={port_xy}'))
            part_z = _part_flat_z(parts[-1])
            if part_z is None or abs(part_z - port_z) > TOL_Z_MM:
                violations.append(dict(kind='route_end_wrong_height',
                                       route_id=route_id,
                                       detail=f'z={part_z!r} port_z={port_z!r}'))
            try:
                tangent = _prim_tangent(prims[-1], 1.0)
                gap = math.hypot(tangent[0] + port_inward[0],
                                 tangent[1] + port_inward[1])
                if gap > TOL_TANGENT:
                    violations.append(dict(kind='route_end_tangent_mismatch',
                                           route_id=route_id,
                                           detail=f'tangent={tangent} '
                                                  f'-inward={(-port_inward[0], -port_inward[1])} '
                                                  f'gap={gap:.3g}'))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
    # declared route fields (DESIGN.md section 2).  A missing optional field is
    # a contract warning (parts are authoritative); a *wrong* declared value is
    # an error because it would mislead downstream consumers.
    rebuilt = _declared_rebuild(route, parts)
    interface_z = interface_z_of_plane(plane)
    for field in ('start_z_mm', 'end_z_mm'):
        if field in route and route[field] is not None:
            try:
                if abs(float(route[field]) - interface_z) > TOL_FIELD_Z_MM:
                    violations.append(dict(kind=f'{field}_mismatch',
                                           route_id=route_id,
                                           detail=f'{route[field]!r} != {interface_z!r}'))
            except (TypeError, ValueError):
                violations.append(dict(kind=f'{field}_invalid', route_id=route_id,
                                       detail=repr(route[field])))
        else:
            rebuilt.setdefault('missing_fields', []).append(field)
    declared_sequence = route.get('layer_sequence')
    if declared_sequence is not None:
        try:
            declared = [int(value) for value in declared_sequence]
        except (TypeError, ValueError):
            declared = None
        if declared is not None and declared != rebuilt['layer_sequence']:
            violations.append(dict(kind='layer_sequence_mismatch', route_id=route_id,
                                   detail=f'declared={declared} '
                                          f'rebuilt={rebuilt["layer_sequence"]}'))
    else:
        rebuilt.setdefault('missing_fields', []).append('layer_sequence')
    declared_z_sequence = route.get('layer_z_sequence')
    if declared_z_sequence is not None:
        expected_z = []
        for layer_id in rebuilt['layer_sequence']:
            try:
                if int(layer_id) == INTERFACE_LAYER_ID:
                    expected_z.append(interface_z)
                else:
                    expected_z.append(_layer_z(int(layer_id)))
            except (TypeError, ValueError):
                expected_z.append(None)
        try:
            declared_z = [float(value) for value in declared_z_sequence]
        except (TypeError, ValueError):
            declared_z = None
        if declared_z is not None and len(declared_z) == len(expected_z):
            for index, (declared, expected) in enumerate(zip(declared_z, expected_z)):
                if expected is None or abs(declared - expected) > TOL_FIELD_Z_MM:
                    violations.append(dict(
                        kind='layer_z_sequence_mismatch', route_id=route_id,
                        detail=f'index={index} declared={declared!r} '
                               f'expected={expected!r}'))
                    break
        elif declared_z is not None:
            violations.append(dict(kind='layer_z_sequence_length_mismatch',
                                   route_id=route_id,
                                   detail=f'declared={declared_z} expected_len={len(expected_z)}'))
    else:
        rebuilt.setdefault('missing_fields', []).append('layer_z_sequence')
    for field, rebuilt_key, tolerance in (
            ('n_transitions', 'n_transitions', 0),
            ('length_mm', 'total_length', TOL_LEN_FIELD_MM),
            ('xy_length_mm', 'xy_length', TOL_LEN_FIELD_MM),
            ('z_span_mm', 'z_span', TOL_FIELD_Z_MM)):
        if field not in route or route[field] is None:
            rebuilt.setdefault('missing_fields', []).append(field)
            continue
        declared = route[field]
        expected = rebuilt[rebuilt_key]
        try:
            if expected is None:
                violations.append(dict(kind=f'{field}_not_recomputable',
                                       route_id=route_id))
            elif tolerance == 0:
                if int(declared) != int(expected):
                    violations.append(dict(kind=f'{field}_mismatch', route_id=route_id,
                                           detail=f'declared={declared!r} '
                                                  f'rebuilt={expected!r}'))
            elif abs(float(declared) - float(expected)) > tolerance:
                violations.append(dict(kind=f'{field}_mismatch', route_id=route_id,
                                       detail=f'declared={declared!r} '
                                              f'rebuilt={expected!r}'))
        except (TypeError, ValueError):
            violations.append(dict(kind=f'{field}_invalid', route_id=route_id,
                                   detail=repr(declared)))
    lifted = route.get('lifted')
    if lifted is None:
        rebuilt.setdefault('missing_fields', []).append('lifted')
    elif bool(lifted) != rebuilt['lifted']:
        violations.append(dict(kind='lifted_mismatch', route_id=route_id,
                               detail=f'declared={lifted!r} rebuilt={rebuilt["lifted"]!r}'))
    layers_used = route.get('layers_used')
    if layers_used is None:
        rebuilt.setdefault('missing_fields', []).append('layers_used')
    else:
        try:
            declared_used = sorted({int(value) for value in layers_used})
            if declared_used != rebuilt['layers_used']:
                violations.append(dict(kind='layers_used_mismatch', route_id=route_id,
                                       detail=f'declared={declared_used} '
                                              f'rebuilt={rebuilt["layers_used"]}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='layers_used_invalid', route_id=route_id,
                                   detail=repr(layers_used)))
    return violations, {'plane': plane, 'raw_structure_errors': list(raw_errors),
                        'rebuilt': rebuilt}


# ===========================================================================
# b) R15 radius audit
# ===========================================================================
def _min_circumradius(points):
    """Minimum sampled (discrete) circumradius of a 3D point list."""
    if len(points) < 3:
        return None
    array = np.asarray(points, dtype=float)
    a = array[:-2]
    b = array[1:-1]
    c = array[2:]
    ab = b - a
    ac = c - a
    double_area = np.linalg.norm(np.cross(ab, ac), axis=1)
    length_ab = np.linalg.norm(ab, axis=1)
    length_ac = np.linalg.norm(ac, axis=1)
    length_bc = np.linalg.norm(c - b, axis=1)
    with np.errstate(divide='ignore', invalid='ignore'):
        radius = (length_ab * length_ac * length_bc) / (2.0 * double_area)
    shortest = np.minimum(np.minimum(length_ab, length_ac), length_bc)
    usable = (double_area > 1e-16) & (shortest > CURVATURE_JOIN_MIN_LENGTH_MM)
    if not np.any(usable):
        return None
    return float(np.min(radius[usable]))


def check_route_radius(route):
    """(b) flat arcs exactly R15; transition true 3D radius >= 15 - 1e-6."""
    violations = []
    try:
        route_id = int(route.get('route_id'))
    except (TypeError, ValueError):
        return violations, {}
    arcs = []
    transitions = []
    for index, part in enumerate(route.get('parts') or []):
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            for prim_index, prim in enumerate(part.get('primitives') or []):
                if not isinstance(prim, dict) or prim.get('kind') != 'arc':
                    continue
                try:
                    radius = float(prim.get('radius'))
                except (TypeError, ValueError):
                    violations.append(dict(kind='arc_radius_invalid',
                                           route_id=route_id,
                                           detail=f'part={index} prim={prim_index}'))
                    continue
                arcs.append(radius)
                if abs(radius - R15_MM) > TOL_RADIUS_MM:
                    violations.append(dict(
                        kind='flat_arc_radius_not_r15', route_id=route_id,
                        detail=f'part={index} prim={prim_index} radius={radius!r}'))
        elif part.get('kind') == 'transition':
            try:
                declared_radius = float(part.get('radius_mm'))
            except (TypeError, ValueError):
                declared_radius = None
                violations.append(dict(kind='transition_radius_missing',
                                       route_id=route_id, detail=f'part={index}'))
            if declared_radius is not None and abs(declared_radius - R15_MM) > TOL_RADIUS_MM:
                violations.append(dict(
                    kind='transition_declared_radius_not_r15', route_id=route_id,
                    detail=f'part={index} radius_mm={declared_radius!r}'))
            try:
                samples = P.transition_samples(part, step=TRANSITION_SAMPLE_STEP_MM)
            except (KeyError, TypeError, ValueError) as error:
                violations.append(dict(kind='transition_sampling_failed',
                                       route_id=route_id,
                                       detail=f'part={index} {error!r}'))
                continue
            minimum = _min_circumradius(samples)
            if minimum is not None and minimum < MIN_R15_SAMPLED_MM:
                violations.append(dict(
                    kind='transition_true_3d_radius_below_r15', route_id=route_id,
                    detail=f'part={index} min_sampled_radius={minimum:.9g}'))
            transitions.append(dict(index=index, declared_radius=declared_radius,
                                    min_sampled_radius=minimum,
                                    samples=len(samples)))
    details = dict(
        flat_arc_count=len(arcs),
        flat_arc_radii=sorted({round(value, 9) for value in arcs}),
        transition_count=len(transitions),
        transition_declared_radii=sorted({round(item['declared_radius'], 9)
                                          for item in transitions
                                          if item.get('declared_radius') is not None}),
        transition_min_sampled_radius=min(
            (item['min_sampled_radius'] for item in transitions
             if item.get('min_sampled_radius') is not None), default=None),
        transition_samples_total=sum(item.get('samples', 0) for item in transitions),
    )
    return violations, details


# ===========================================================================
# c) glass bounds
# ===========================================================================
def _flat_sample_points(part):
    """Sample points of one flat part: line endpoints, dense arc points."""
    points = []
    for prim in part.get('primitives') or []:
        if not isinstance(prim, dict):
            continue
        kind = prim.get('kind')
        p0 = _finite_xy(prim.get('p0'))
        p1 = _finite_xy(prim.get('p1'))
        if kind == 'line':
            if p0 is not None:
                points.append(p0)
            if p1 is not None:
                points.append(p1)
        elif kind == 'arc':
            center = _finite_xy(prim.get('center'))
            try:
                radius = float(prim.get('radius'))
                start = float(prim.get('start_angle'))
                sweep = float(prim.get('sweep'))
            except (TypeError, ValueError):
                continue
            if center is None or radius <= 0.0:
                continue
            count = max(2, int(math.ceil(abs(sweep) * radius / ARC_SAMPLE_STEP_MM)) + 1)
            angles = np.linspace(start, start + sweep, count)
            xs = center[0] + radius * np.cos(angles)
            ys = center[1] + radius * np.sin(angles)
            points.extend(zip(xs.tolist(), ys.tolist()))
    return points


def check_route_glass(route):
    """(c) glass XY/Z bounds + waveguide edge margin report."""
    violations = []
    try:
        route_id = int(route.get('route_id'))
    except (TypeError, ValueError):
        return violations, {}
    samples = []
    for part in route.get('parts') or []:
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            z = _part_flat_z(part)
            if z is None:
                continue
            for x, y in _flat_sample_points(part):
                samples.append((x, y, z))
        elif part.get('kind') == 'transition':
            try:
                for sample in P.transition_samples(part, step=GLASS_TRANSITION_STEP_MM):
                    samples.append((float(sample[0]), float(sample[1]), float(sample[2])))
            except (KeyError, TypeError, ValueError):
                continue
    if not samples:
        return violations, {}
    array = np.asarray(samples, dtype=float)
    xs, ys, zs = array[:, 0], array[:, 1], array[:, 2]
    center_margin = np.minimum(np.minimum(xs, GLASS_XY_MM - xs),
                               np.minimum(ys, GLASS_XY_MM - ys))
    min_center_margin = float(np.min(center_margin))
    min_edge_margin = min_center_margin - WAVEGUIDE_HALF_WIDTH_MM
    if min_center_margin < -TOL_GLASS_MM:
        violations.append(dict(
            kind='outside_glass_xy', route_id=route_id,
            detail=f'min_centerline_margin={min_center_margin:.9g} mm'))
    min_z = float(np.min(zs))
    max_z = float(np.max(zs))
    if min_z < GLASS_Z_MIN_MM - TOL_GLASS_MM or max_z > GLASS_Z_MAX_MM + TOL_GLASS_MM:
        violations.append(dict(kind='outside_glass_z', route_id=route_id,
                               detail=f'z_range=[{min_z:.9g},{max_z:.9g}]'))
    return violations, dict(min_centerline_margin_mm=min_center_margin,
                            min_edge_margin_mm=min_edge_margin,
                            min_z_mm=min_z, max_z_mm=max_z,
                            samples=len(samples),
                            edge_margin_negative=bool(min_edge_margin < 0.0))


# ===========================================================================
# d) true 3D clearance
# ===========================================================================
def check_true_3d_clearance(routed):
    """(d) fresh World rebuilt from the finished routes; check every route."""
    stack = common.layer_stack()
    world = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    violations = []
    by_kind = Counter()
    offending = set()
    pairs = []
    checked = 0
    added = 0
    for route in routed:
        try:
            route_id = int(route.get('route_id'))
        except (TypeError, ValueError):
            continue
        checked += 1
        try:
            route_violations = world.check_route(route, check_self=True)
        except Exception as error:  # noqa: BLE001 - report, never hide
            violations.append(dict(kind='clearance_check_exception',
                                   route_id=route_id,
                                   detail=f'{type(error).__name__}: {error}'))
            by_kind['clearance_check_exception'] += 1
            offending.add(route_id)
            continue
        for item in route_violations:
            kind = str(item.get('kind'))
            by_kind[kind] += 1
            offending.add(route_id)
            other = item.get('other_route')
            entry = dict(kind=kind, route_id=route_id,
                         other_route=int(other) if other is not None else None)
            if 'distance_mm' in item and item['distance_mm'] is not None:
                entry['distance_mm'] = float(item['distance_mm'])
            if item.get('point') is not None:
                entry['point'] = item['point']
            if item.get('z_mm') is not None:
                entry['z_mm'] = float(item['z_mm'])
                entry['other_z_mm'] = float(item.get('other_z_mm', item['z_mm']))
            if item.get('blockers'):
                entry['blockers'] = item['blockers'][:10]
            violations.append(entry)
        try:
            world.add_route(route)
            added += 1
        except Exception as error:  # noqa: BLE001
            violations.append(dict(kind='world_add_route_exception',
                                   route_id=route_id,
                                   detail=f'{type(error).__name__}: {error}'))
            by_kind['world_add_route_exception'] += 1
            offending.add(route_id)
    return dict(violations=violations, by_kind=dict(sorted(by_kind.items())),
                offending_route_ids=sorted(offending),
                checked=checked, added=added,
                violation_count=len(violations),
                world=dict(layer_stack_schema=str(stack.to_dict().get('schema')),
                           clearance_mm=MIN_3D_CLEARANCE_MM))


# ---------------------------------------------------------------------------
# exact-ish minimum true-3D centreline distance
# ---------------------------------------------------------------------------
def _segments_from_polyline(points):
    if len(points) < 2:
        empty = np.zeros((0, 3))
        return empty, empty
    array = np.asarray(points, dtype=float)
    return array[:-1], array[1:]


def _segment_segment_closest(p1, q1, p2, q2):
    """Vectorised closest points between paired 3D segments (Ericson, clamped)."""
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = np.einsum('ij,ij->i', d1, d1)
    e = np.einsum('ij,ij->i', d2, d2)
    f = np.einsum('ij,ij->i', d2, r)
    c = np.einsum('ij,ij->i', d1, r)
    b = np.einsum('ij,ij->i', d1, d2)
    safe_a = np.where(a > 1e-24, a, 1.0)
    safe_e = np.where(e > 1e-24, e, 1.0)
    denom = a * e - b * b
    parallel = denom <= 1e-18 * safe_a * safe_e
    s_inner = np.where(parallel, 0.0,
                       (b * f - c * e) / np.where(parallel, 1.0, denom))
    s = np.clip(s_inner, 0.0, 1.0)
    t = (b * s + f) / safe_e
    negative = t < 0.0
    positive = t > 1.0
    s = np.where(negative, np.clip(-c / safe_a, 0.0, 1.0),
                 np.where(positive, np.clip((b - c) / safe_a, 0.0, 1.0), s))
    t = np.where(negative, 0.0, np.where(positive, 1.0, np.clip(t, 0.0, 1.0)))
    point_a = p1 + s[:, None] * d1
    point_b = p2 + t[:, None] * d2
    diff = point_a - point_b
    return np.sqrt(np.einsum('ij,ij->i', diff, diff)), point_a, point_b


def _iter_candidate_pairs(tree, query_points, radius, chunk_size=32768):
    total = len(query_points)
    for start in range(0, total, chunk_size):
        stop = min(total, start + chunk_size)
        neighbours = tree.query_ball_point(query_points[start:stop], r=radius,
                                           workers=-1)
        counts = np.fromiter((len(item) for item in neighbours), dtype=np.int64,
                             count=len(neighbours))
        if counts.sum() == 0:
            continue
        query_index = np.repeat(np.arange(start, stop, dtype=np.int64), counts)
        tree_index = np.concatenate([np.asarray(item, dtype=np.int64)
                                     for item in neighbours])
        yield query_index, tree_index


def _build_3d_segment_stores(routed):
    """Dense flat/transition segment stores for the true-3D minimum scan."""
    flat_a, flat_b, flat_route = [], [], []
    trans_a, trans_b, trans_route = [], [], []
    for route in routed:
        try:
            route_id = int(route.get('route_id'))
        except (TypeError, ValueError):
            continue
        for part in route.get('parts') or []:
            if not isinstance(part, dict):
                continue
            if part.get('kind') == 'flat':
                points = []
                for prim in part.get('primitives') or []:
                    if not isinstance(prim, dict):
                        continue
                    p0 = _finite_xy(prim.get('p0'))
                    p1 = _finite_xy(prim.get('p1'))
                    if prim.get('kind') == 'line':
                        if p0 is not None and p1 is not None and math.dist(p0, p1) > 1e-12:
                            points.append((p0[0], p0[1], float(part['z_mm'])))
                            points.append((p1[0], p1[1], float(part['z_mm'])))
                    elif prim.get('kind') == 'arc':
                        center = _finite_xy(prim.get('center'))
                        try:
                            radius = float(prim.get('radius'))
                            start = float(prim.get('start_angle'))
                            sweep = float(prim.get('sweep'))
                        except (TypeError, ValueError):
                            continue
                        if center is None or radius <= 0.0:
                            continue
                        count = max(2, int(math.ceil(abs(sweep) * radius / 0.02)) + 1)
                        angles = np.linspace(start, start + sweep, count)
                        z = float(part['z_mm'])
                        for angle in angles.tolist():
                            points.append((center[0] + radius * math.cos(angle),
                                           center[1] + radius * math.sin(angle), z))
                if len(points) >= 2:
                    a, b = _segments_from_polyline(points)
                    flat_a.append(a)
                    flat_b.append(b)
                    flat_route.append(np.full(len(a), route_id, dtype=np.int64))
            elif part.get('kind') == 'transition':
                try:
                    samples = P.transition_samples(part, step=0.02)
                except (KeyError, TypeError, ValueError):
                    continue
                if len(samples) < 2:
                    continue
                a, b = _segments_from_polyline(samples)
                trans_a.append(a)
                trans_b.append(b)
                trans_route.append(np.full(len(a), route_id, dtype=np.int64))

    def _stack(parts_a, parts_b, parts_route):
        if not parts_a:
            empty = np.zeros((0, 3))
            return empty, empty, np.zeros(0, dtype=np.int64)
        return (np.vstack(parts_a), np.vstack(parts_b),
                np.concatenate(parts_route))

    return {'flat': _stack(flat_a, flat_b, flat_route),
            'transition': _stack(trans_a, trans_b, trans_route)}


def measure_min_3d_clearance(routed, clearance=MIN_3D_CLEARANCE_MM,
                             query_radius_mm=0.20, limit_mm=None):
    """Exact-ish minimum true 3D centreline distance (transition-involved pairs).

    Flat-vs-flat on the same physical plane is covered by the strict 2D audit
    (>= 0.08 mm for non-crossing pairs, legal crossings exempt); flat-vs-flat on
    different physical planes is >= the plane pitch (>= 0.05 mm).  The measured
    minimum is therefore taken over transition-vs-flat and
    transition-vs-transition pairs, exactly like the previous-round validator.
    """
    import scipy.spatial as spatial

    limit = MIN_3D_CLEARANCE_MM if limit_mm is None else float(limit_mm)
    started = time.time()
    store = _build_3d_segment_stores(routed)
    flat_a, flat_b, flat_route = store['flat']
    trans_a, trans_b, trans_route = store['transition']
    result = dict(
        flat_segments=int(len(flat_a)), transition_segments=int(len(trans_a)),
        query_radius_mm=float(query_radius_mm),
        transition_vs_flat=dict(violations=0, min_mm=None, pairs=[]),
        transition_vs_transition=dict(violations=0, min_mm=None, pairs=[]),
    )
    if len(trans_a) == 0:
        result['min_3d_clearance_mm'] = None
        result['runtime_seconds'] = round(time.time() - started, 2)
        return result
    # ---- transition vs flat -------------------------------------------------
    if len(flat_a) and len(trans_a):
        flat_mid = 0.5 * (flat_a + flat_b)
        trans_mid = 0.5 * (trans_a + trans_b)
        tree = spatial.cKDTree(flat_mid)
        minimum = float('inf')
        min_pair = None
        pair_set = set()
        for query_index, flat_index in _iter_candidate_pairs(
                tree, trans_mid, query_radius_mm):
            keep = trans_route[query_index] != flat_route[flat_index]
            if not np.any(keep):
                continue
            query_index = query_index[keep]
            flat_index = flat_index[keep]
            distance, point_a, _point_b = _segment_segment_closest(
                trans_a[query_index], trans_b[query_index],
                flat_a[flat_index], flat_b[flat_index])
            local_min = float(np.min(distance))
            if local_min < minimum:
                minimum = local_min
                index = int(np.argmin(distance))
                min_pair = dict(route_id=int(trans_route[query_index[index]]),
                                other_route=int(flat_route[flat_index[index]]),
                                distance_mm=_round(local_min),
                                point=[_round(value) for value in point_a[index]])
            bad = np.flatnonzero(distance < limit - 1e-9)
            if bad.size:
                result['transition_vs_flat']['violations'] += int(bad.size)
                for index in bad[:50]:
                    pair = (int(trans_route[query_index[index]]),
                            int(flat_route[flat_index[index]]))
                    if pair in pair_set:
                        continue
                    pair_set.add(pair)
                    result['transition_vs_flat']['pairs'].append(
                        dict(route_id=pair[0], other_route=pair[1],
                             distance_mm=_round(distance[index]),
                             point=[_round(value) for value in point_a[index]]))
        result['transition_vs_flat']['min_mm'] = (
            _round(minimum) if math.isfinite(minimum) else None)
        result['transition_vs_flat']['min_pair'] = min_pair
    # ---- transition vs transition ------------------------------------------
    if len(trans_a) > 1:
        trans_mid = 0.5 * (trans_a + trans_b)
        tree = spatial.cKDTree(trans_mid)
        minimum = float('inf')
        min_pair = None
        pair_set = set()
        for query_index, other_index in _iter_candidate_pairs(
                tree, trans_mid, query_radius_mm):
            keep = trans_route[query_index] != trans_route[other_index]
            keep &= query_index < other_index
            if not np.any(keep):
                continue
            query_index = query_index[keep]
            other_index = other_index[keep]
            distance, point_a, _point_b = _segment_segment_closest(
                trans_a[query_index], trans_b[query_index],
                trans_a[other_index], trans_b[other_index])
            local_min = float(np.min(distance))
            if local_min < minimum:
                minimum = local_min
                index = int(np.argmin(distance))
                min_pair = dict(route_id=int(trans_route[query_index[index]]),
                                other_route=int(trans_route[other_index[index]]),
                                distance_mm=_round(local_min),
                                point=[_round(value) for value in point_a[index]])
            bad = np.flatnonzero(distance < limit - 1e-9)
            if bad.size:
                result['transition_vs_transition']['violations'] += int(bad.size)
                for index in bad[:50]:
                    pair = (int(trans_route[query_index[index]]),
                            int(trans_route[other_index[index]]))
                    if pair in pair_set:
                        continue
                    pair_set.add(pair)
                    result['transition_vs_transition']['pairs'].append(
                        dict(route_id=pair[0], other_route=pair[1],
                             distance_mm=_round(distance[index]),
                             point=[_round(value) for value in point_a[index]]))
        result['transition_vs_transition']['min_mm'] = (
            _round(minimum) if math.isfinite(minimum) else None)
        result['transition_vs_transition']['min_pair'] = min_pair
    measured = [value for value in (result['transition_vs_flat']['min_mm'],
                                    result['transition_vs_transition']['min_mm'])
                if value is not None]
    result['min_3d_clearance_mm'] = min(measured) if measured else None
    result['violation_count'] = (result['transition_vs_flat']['violations']
                                 + result['transition_vs_transition']['violations'])
    # conservative global lower bound: layer pitch is exactly 0.05 mm
    plane_gap = min(abs(b - a) for a, b in
                    zip(sorted(common.PHYSICAL_LAYERS.values()),
                        sorted(common.PHYSICAL_LAYERS.values())[1:]))
    result['min_plane_gap_mm'] = plane_gap
    result['min_3d_clearance_lower_bound_mm'] = (
        min(measured + [plane_gap]) if measured else plane_gap)
    result['runtime_seconds'] = round(time.time() - started, 2)
    return result


# ===========================================================================
# e) port coverage / identity / uniqueness
# ===========================================================================
def check_ports(routed, failed, all_records, true_routes):
    """(e) true ports, 1024 unique ids, 512/512 planes, exact endpoint pairs."""
    violations = []
    endpoints = common.endpoints()
    ids_all = _route_ids(all_records)
    ids_routed = set(_route_ids(routed))
    ids_failed = set(_route_ids(failed))
    expected_ids = set(true_routes)
    duplicate_ids = sorted({value for value in ids_all
                            if value is not None and ids_all.count(value) > 1})
    missing_ids = sorted(expected_ids - set(value for value in ids_all if value is not None))
    extra_ids = sorted(set(value for value in ids_all if value is not None) - expected_ids)
    for route_id in missing_ids:
        violations.append(dict(kind='route_id_missing', route_id=route_id,
                               detail='not present in routes_l3d.json'))
    for route_id in extra_ids:
        violations.append(dict(kind='route_id_not_in_true_data', route_id=route_id))
    for route_id in duplicate_ids:
        violations.append(dict(kind='duplicate_route_id', route_id=route_id))
    # plane coverage: every true route id must carry the true plane
    plane_counts = Counter()
    pair_pairs = {}
    missing_endpoint_records = []
    routed_missing_endpoint = []
    identity_checked = 0
    for record in all_records:
        route_id = record.get('route_id')
        try:
            route_id = int(route_id)
        except (TypeError, ValueError):
            continue
        true = true_routes.get(route_id)
        source = record.get('source_endpoint')
        target = record.get('target_endpoint')
        plane = _route_plane(record)
        plane_counts[str(plane)] += 1
        if true is not None:
            if plane != str(true['plane']):
                violations.append(dict(kind='route_plane_mismatch', route_id=route_id,
                                       detail=f'{plane!r} != {true["plane"]!r}'))
        if source is None or target is None:
            missing_endpoint_records.append(route_id)
            if route_id in ids_routed:
                routed_missing_endpoint.append(route_id)
            continue
        identity_checked += 1
        if true is not None:
            expected = (str(true['source_endpoint']), str(true['target_endpoint']))
            actual = (str(source), str(target))
            if actual != expected:
                violations.append(dict(kind='port_pair_not_true_data',
                                       route_id=route_id,
                                       detail=f'{actual} != {expected} '
                                              f'(status='
                                              f'{"routed" if route_id in ids_routed else "failed"})'))
        for name, endpoint_id in (('source', source), ('target', target)):
            if endpoint_id not in endpoints:
                violations.append(dict(kind=f'{name}_endpoint_not_a_port',
                                       route_id=route_id, detail=repr(endpoint_id)))
                continue
            port_plane = str(endpoints[endpoint_id].get('plane'))
            if plane is not None and port_plane != plane:
                violations.append(dict(kind=f'{name}_endpoint_plane_mismatch',
                                       route_id=route_id,
                                       detail=f'{endpoint_id} plane={port_plane!r} '
                                              f'record={plane!r}'))
        pair_pairs[route_id] = (str(source), str(target))
    for route_id in routed_missing_endpoint:
        violations.append(dict(kind='routed_record_missing_endpoints',
                               route_id=route_id))
    true_pairs = {int(route['route_id']):
                  (str(route['source_endpoint']), str(route['target_endpoint']))
                  for route in common.routes()}
    port_pair_set_matches = True
    for route_id, pair in pair_pairs.items():
        if true_pairs.get(route_id) != pair:
            port_pair_set_matches = False
            break
    if port_pair_set_matches and len(pair_pairs) == len(true_pairs):
        pass
    elif port_pair_set_matches:
        # some records did not declare endpoints; compare declared subset
        port_pair_set_matches = all(true_pairs.get(route_id) == pair
                                    for route_id, pair in pair_pairs.items())
    plane_routed = Counter(str(_route_plane(record)) for record in routed)
    plane_failed = Counter(str(_route_plane(record)) for record in failed)
    details = dict(
        records=len(all_records), routed=len(routed), failed=len(failed),
        unique_route_ids=len(set(value for value in ids_all if value is not None)),
        expected_route_ids=len(expected_ids),
        duplicate_route_ids=duplicate_ids,
        missing_route_ids=missing_ids[:50],
        missing_route_id_count=len(missing_ids),
        extra_route_ids=extra_ids,
        planes_all=dict(sorted(plane_counts.items())),
        planes_routed=dict(sorted(plane_routed.items())),
        planes_failed=dict(sorted(plane_failed.items())),
        identity_checked=identity_checked,
        port_pair_set_matches=bool(port_pair_set_matches),
        routes_missing_endpoints=len(missing_endpoint_records),
        routed_routes_missing_endpoints=len(routed_missing_endpoint),
        endpoint_table_size=len(endpoints),
    )
    return violations, details


# ===========================================================================
# f) layer assignment audit
# ===========================================================================
def _parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def check_assignment(routed, failed, assignment_rows, true_routes):
    """(f) routed body layer/z vs assignment; fixed manual layers."""
    violations = []
    if assignment_rows is None:
        return [dict(kind='assignment_file_missing',
                     detail='assignment_1024.csv not found')], {'available': False}
    ids_all = _route_ids(routed + failed)
    missing_rows = sorted(set(value for value in ids_all if value is not None)
                          - set(assignment_rows))
    extra_rows = sorted(set(assignment_rows)
                        - set(value for value in ids_all if value is not None))
    for route_id in missing_rows:
        violations.append(dict(kind='assignment_row_missing', route_id=route_id))
    for route_id in extra_rows:
        violations.append(dict(kind='assignment_row_unknown_route', route_id=route_id))
    group_counts_all = Counter()
    group_counts_routed = Counter()
    layer_counts_routed = Counter()
    manual_wrong_layer = []
    body_checked = 0
    for record in routed:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        row = assignment_rows.get(route_id)
        if row is None:
            continue
        manual_group = (row.get('manual_group') or '').strip()
        if manual_group:
            group_counts_all[manual_group] += 1
            group_counts_routed[manual_group] += 1
        target_layer = _parse_int(row.get('physical_layer'))
        if target_layer is None:
            target_layer = _parse_int(row.get('target_layer'))
        target_z = _parse_float(row.get('target_z_mm'))
        body = body_flat_parts(record)
        body_checked += 1
        if target_layer is None:
            # assigned to "stay on the interface plane" (historical interface rows)
            if body:
                violations.append(dict(
                    kind='body_flat_on_interface_assignment', route_id=route_id,
                    detail=f'{[(int(part["layer_id"]), part["z_mm"]) for _i, part in body]}'))
            for _index, part in enumerate(record.get('parts') or []):
                if part.get('kind') != 'flat':
                    continue
                if not _is_interface_layer(part.get('layer_id')):
                    violations.append(dict(kind='non_interface_flat_without_target',
                                           route_id=route_id,
                                           detail=f'layer_id={part.get("layer_id")!r}'))
        else:
            if not body:
                violations.append(dict(kind='missing_body_flat', route_id=route_id,
                                       detail=f'assigned L{target_layer}'))
                continue
            for _index, part in body:
                try:
                    layer_id = int(part.get('layer_id'))
                    z = float(part.get('z_mm'))
                except (TypeError, ValueError):
                    violations.append(dict(kind='body_flat_invalid', route_id=route_id))
                    continue
                if layer_id != target_layer:
                    violations.append(dict(
                        kind='body_layer_mismatch_assignment', route_id=route_id,
                        detail=f'body=L{layer_id} assignment=L{target_layer}'))
                if target_z is not None and abs(z - target_z) > TOL_Z_MM:
                    violations.append(dict(
                        kind='body_z_mismatch_assignment', route_id=route_id,
                        detail=f'body_z={z!r} assignment_z={target_z!r}'))
            layer_counts_routed[target_layer] += 1
        if manual_group:
            expected_layer = manual_group_layer(manual_group)
            if expected_layer is None:
                violations.append(dict(kind='unknown_manual_group', route_id=route_id,
                                       detail=manual_group))
            else:
                if target_layer is not None and target_layer != expected_layer:
                    violations.append(dict(
                        kind='manual_group_assignment_layer_mismatch',
                        route_id=route_id,
                        detail=f'group={manual_group} assignment=L{target_layer} '
                               f'expected=L{expected_layer}'))
                present_layers = {int(part['layer_id']) for _i, part in body
                                  if part.get('layer_id') is not None}
                if expected_layer not in present_layers:
                    manual_wrong_layer.append(route_id)
                    violations.append(dict(
                        kind='manual_route_not_on_fixed_layer', route_id=route_id,
                        detail=f'group={manual_group} expected=L{expected_layer} '
                               f'body_layers={sorted(present_layers)}'))
    # manual layers must not be overwritten by non-manual routes (new fixed-layer
    # policy only; the historical round used a different assignment scheme)
    overwritten = []
    for route_id, row in assignment_rows.items():
        manual_group = (row.get('manual_group') or '').strip()
        target_layer = _parse_int(row.get('physical_layer'))
        if target_layer is None:
            target_layer = _parse_int(row.get('target_layer'))
        if manual_group or target_layer not in MANUAL_LAYERS:
            continue
        overwritten.append(route_id)
    new_naming = any(str(name).startswith('Z2-U') for name in group_counts_all)
    if new_naming:
        for route_id in overwritten[:50]:
            violations.append(dict(kind='manual_layer_overwritten_by_nonmanual',
                                   route_id=route_id,
                                   detail=f'non-manual route on a fixed manual layer'))
    # expected manual group counts (new naming only; historical names differ)
    expected_group_counts = {'Z1-U1': 64, 'Z1-U2': 64, 'Z1-U3': 64, 'Z1-U4': 64,
                             'Z2-U1': 16, 'Z2-U2': 16, 'Z2-U3': 40, 'Z2-U4': 40}
    group_count_mismatches = {}
    if new_naming:
        for group, expected in expected_group_counts.items():
            actual = group_counts_all.get(group, 0)
            if actual != expected:
                group_count_mismatches[group] = dict(expected=expected, actual=actual)
                violations.append(dict(kind='manual_group_count_mismatch',
                                       detail=f'{group}: expected {expected}, '
                                              f'actual {actual}'))
    # assignment identity audit against the true route table
    identity_mismatch = []
    for route_id, row in assignment_rows.items():
        true = true_routes.get(route_id)
        if true is None:
            continue
        row_source = (row.get('source_endpoint') or '').strip()
        row_target = (row.get('target_endpoint') or '').strip()
        if not row_source or not row_target:
            continue
        if (row_source, row_target) != (str(true['source_endpoint']),
                                        str(true['target_endpoint'])):
            identity_mismatch.append(route_id)
            if len(identity_mismatch) <= 50:
                violations.append(dict(kind='assignment_port_pair_mismatch',
                                       route_id=route_id))
        row_plane = (row.get('plane') or row.get('interface') or '').strip()
        if row_plane and row_plane != str(true['plane']):
            violations.append(dict(kind='assignment_plane_mismatch',
                                   route_id=route_id,
                                   detail=f'{row_plane!r} != {true["plane"]!r}'))
    details = dict(
        available=True,
        assignment_rows=len(assignment_rows),
        missing_assignment_rows=len(missing_rows),
        extra_assignment_rows=len(extra_rows),
        body_checked=body_checked,
        manual_group_counts_all=dict(sorted(group_counts_all.items())),
        manual_group_counts_routed=dict(sorted(group_counts_routed.items())),
        manual_group_expected_counts=(expected_group_counts if new_naming else None),
        manual_group_count_mismatches=group_count_mismatches,
        manual_routes_not_on_fixed_layer=len(manual_wrong_layer),
        manual_layer_rerouting_policy_applicable=bool(new_naming),
        nonmanual_rows_on_manual_layers=len(overwritten),
        manual_layer_overwrite_count=(len(overwritten) if new_naming else 0),
        assignment_port_pair_mismatches=len(identity_mismatch),
        routed_body_layer_counts={str(key): value
                                  for key, value in sorted(layer_counts_routed.items())},
    )
    return violations, details


# ===========================================================================
# layer stack / process contract audit
# ===========================================================================
def check_layer_stack(payload):
    """Validate the embedded layer stack and process blocks against ground truth."""
    violations = []
    expected_heights = {int(key): float(value)
                        for key, value in common.PHYSICAL_LAYERS.items()}
    details = dict(expected_routing_heights={str(key): value
                                             for key, value in sorted(expected_heights.items())},
                   expected_interface_rows={'z1': 0.0, 'z2': 0.5},
                   embedded=False, embedded_valid=None, plane_gaps_mm=[],
                   min_plane_gap_mm=None, at_exact_clearance=[])
    raw_stack = payload.get('layer_stack')
    if isinstance(raw_stack, dict):
        details['embedded'] = True
        raw_layers = raw_stack.get('layers') or {}
        found = {}
        errors = []
        for key, layer in raw_layers.items():
            try:
                layer_id = int(layer.get('layer_id', key))
            except (TypeError, ValueError):
                errors.append(f'invalid layer id {key!r}')
                continue
            if layer.get('layer_type') == 'interface':
                rows = layer.get('interface_rows') or {}
                if {str(name): _round(value, 9) for name, value in rows.items()} != \
                        {'z1': 0.0, 'z2': 0.5}:
                    errors.append(f'L{layer_id} interface rows {rows!r}')
            else:
                z = layer.get('physical_z_mm')
                if z is None:
                    errors.append(f'L{layer_id} missing physical_z_mm')
                else:
                    found[layer_id] = float(z)
        if found != {key: round(value, 9) for key, value in expected_heights.items()}:
            errors.append(f'routing heights {found!r} != expected')
        min_pitch = raw_stack.get('min_layer_pitch_mm')
        if min_pitch is not None and abs(float(min_pitch) - 0.05) > 1e-9:
            errors.append(f'min_layer_pitch_mm={min_pitch!r} != 0.05')
        details['embedded_valid'] = not errors
        details['embedded_errors'] = errors[:20]
        for error in errors[:20]:
            violations.append(dict(kind='embedded_layer_stack_invalid',
                                   detail=error))
    else:
        details['embedded_errors'] = []
        details['note'] = ('routes file has no layer_stack block; the validator '
                          'uses fanout1024.common.layer_stack() as ground truth')
    # physical plane gaps incl. both interface rows
    planes = sorted({0.0, 0.5, *expected_heights.values()})
    gaps = []
    for low, high in zip(planes, planes[1:]):
        gap = float(high - low)
        gaps.append(gap)
        if gap < 0.05 - TOL_PLANE_GAP_MM:
            violations.append(dict(kind='physical_plane_pitch_too_small',
                                   detail=f'z={low:g}..{high:g} gap={gap:.9g}'))
        if abs(gap - 0.05) <= TOL_PLANE_GAP_MM:
            details['at_exact_clearance'].append([low, high])
    details['plane_gaps_mm'] = gaps
    details['min_plane_gap_mm'] = min(gaps) if gaps else None
    # process block
    raw_process = payload.get('process')
    process = dict(embedded=isinstance(raw_process, dict))
    if isinstance(raw_process, dict):
        expected = dict(min_3d_clearance_mm=MIN_3D_CLEARANCE_MM,
                        min_bend_radius_mm=R15_MM,
                        min_layer_pitch_mm=0.05,
                        glass_thickness_mm=1.0)
        for field, value in expected.items():
            if field in raw_process and raw_process[field] is not None:
                try:
                    if abs(float(raw_process[field]) - value) > 1e-9:
                        violations.append(dict(
                            kind='process_rule_mismatch',
                            detail=f'{field}={raw_process[field]!r} expected={value!r}'))
                        process[f'{field}_ok'] = False
                except (TypeError, ValueError):
                    violations.append(dict(kind='process_rule_invalid',
                                           detail=f'{field}={raw_process[field]!r}'))
            else:
                process[f'{field}_present'] = False
        z_range = raw_process.get('glass_z_range_mm')
        if z_range is not None:
            try:
                if [float(z_range[0]), float(z_range[1])] != [GLASS_Z_MIN_MM,
                                                              GLASS_Z_MAX_MM]:
                    violations.append(dict(kind='process_glass_range_mismatch',
                                           detail=repr(z_range)))
            except (TypeError, ValueError, IndexError):
                violations.append(dict(kind='process_glass_range_invalid',
                                       detail=repr(z_range)))
        not_restored = raw_process.get('explicitly_not_restored')
        if isinstance(not_restored, dict):
            if not_restored.get('global_80um_clearance') is True:
                violations.append(dict(
                    kind='process_restored_80um_global_clearance',
                    detail='explicitly_not_restored.global_80um_clearance is True'))
            else:
                process['global_80um_clearance_restored'] = False
    details['process'] = process
    return violations, details


# ===========================================================================
# g) validator-vs-online-world consistency spot checks (50/49 um boundary)
# ===========================================================================
def _synthetic_flat_route(route_id, z_mm, layer_id, primitives):
    return dict(route_id=int(route_id), plane='z1',
                start_z_mm=float(z_mm), end_z_mm=float(z_mm),
                parts=[dict(kind='flat', layer_id=int(layer_id),
                            z_mm=float(z_mm),
                            length_mm=float(P.path_length(primitives)),
                            primitives=primitives)])


def _plane_pitch_verdict(payload_gaps, min_pitch=MIN_3D_CLEARANCE_MM):
    """Independent pitch audit used by the consistency tests."""
    bad = [gap for gap in payload_gaps if gap < min_pitch - TOL_PLANE_GAP_MM]
    return dict(legal=not bad, illegal_gaps=[round(gap, 12) for gap in bad])


def run_consistency_tests():
    """(g) prove the validator agrees with the online World on the 50/49 um edge."""
    tests = []

    def add_test(name, expected, actual, detail=None):
        tests.append(dict(name=name, expected=expected, actual=actual,
                          passed=bool(expected == actual),
                          detail=detail))

    stack = common.layer_stack()
    primitives = [dict(kind='line', p0=[10.0, 10.0], p1=[20.0, 10.0])]
    base = _synthetic_flat_route(900001, 0.0, INTERFACE_LAYER_ID, primitives)
    delta = 0.05
    second_50 = _synthetic_flat_route(900002, delta, 8, primitives)
    world_50 = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    world_50.add_route(base)
    violations_50 = world_50.check_route(second_50, check_self=True)
    add_test('world_accepts_50um_plane_separation', True, not violations_50,
             detail=f'world.check_route -> {violations_50[:3]}')
    # validator-side plane-pitch audit on the same synthetic planes
    pitch_50 = _plane_pitch_verdict([abs(delta - 0.0)])
    add_test('validator_accepts_50um_plane_separation', True, pitch_50['legal'],
             detail=str(pitch_50))
    delta_49 = 0.049
    second_49 = _synthetic_flat_route(900003, delta_49, 8, primitives)
    world_49 = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    world_49.add_route(base)
    violations_49 = world_49.check_route(second_49, check_self=True)
    kinds_49 = sorted({str(item.get('kind')) for item in violations_49})
    add_test('world_rejects_49um_plane_separation', True, bool(violations_49),
             detail=f'kinds={kinds_49} first={violations_49[:2]}')
    add_test('world_49um_is_flat_cross_plane_too_close', True,
             'flat_cross_plane_too_close' in kinds_49, detail=f'kinds={kinds_49}')
    pitch_49 = _plane_pitch_verdict([abs(delta_49 - 0.0)])
    add_test('validator_rejects_49um_plane_separation', True,
             not pitch_49['legal'], detail=str(pitch_49))
    # the accepted 18-layer stack itself must pass, a 49 um stack must fail
    heights = {int(key): float(value) for key, value in common.PHYSICAL_LAYERS.items()}
    real_planes = sorted({0.0, 0.5, *heights.values()})
    real_gaps = [abs(b - a) for a, b in zip(real_planes, real_planes[1:])]
    add_test('real_layer_stack_min_pitch_is_50um', 0.05,
             round(min(real_gaps), 12), detail=f'gaps={real_gaps}')
    bad_gaps = list(real_gaps)
    bad_gaps[0] = 0.049
    bad_verdict = _plane_pitch_verdict(bad_gaps)
    add_test('validator_rejects_49um_physical_stack', True,
             not bad_verdict['legal'], detail=str(bad_verdict))
    # same physical height but 50/49 um XY separation is the 2D D56 0.08 mm rule:
    # the pair audit must reject both (this is a different rule, checked for
    # completeness of the online/validator agreement).
    from ..fslw import validate_fslw as fslw_validate
    for xy_delta, label in ((0.05, '50um_xy'), (0.049, '49um_xy')):
        prepared = [fslw_validate.prepare_route(
                        [dict(kind='line', p0=[10.0, 10.0], p1=[20.0, 10.0])],
                        route_id='synthetic_a'),
                    fslw_validate.prepare_route(
                        [dict(kind='line', p0=[10.0, 10.0 + xy_delta],
                              p1=[20.0, 10.0 + xy_delta])],
                        route_id='synthetic_b')]
        audit = fslw_validate.audit_route_pairs(
            prepared, clearance=D56_CLEARANCE_MM, sagitta=SAGITTA_MM,
            policy='strict')
        add_test(f'd56_same_plane_{label}_is_illegal', True,
                 bool(audit['violations']),
                 detail=f'violations={audit["violations"][:2]}')
    # ports of the true data must resolve (endpoint pose audit)
    port_ok = True
    port_detail = None
    try:
        for endpoint_id in ('N01:1:1', 'S01:1:1', 'E01:2:1', 'W16:2:16'):
            xy, inward, z = common.endpoint_pose(endpoint_id)
            if plane_of := common.endpoints()[endpoint_id].get('plane'):
                expected_z = interface_z_of_plane(plane_of)
                if abs(z - expected_z) > TOL_Z_MM:
                    port_ok = False
                    port_detail = endpoint_id
    except Exception as error:  # noqa: BLE001
        port_ok = False
        port_detail = f'{type(error).__name__}: {error}'
    add_test('true_port_table_poses_consistent', True, port_ok,
             detail=port_detail)
    payload = dict(schema=CONSISTENCY_SCHEMA, generated_at=_now(),
                   clearance_mm=MIN_3D_CLEARANCE_MM,
                   layer_pitch_mm=0.05, tests=tests,
                   all_passed=all(test['passed'] for test in tests))
    return payload


# ===========================================================================
# h) same-physical-plane strict D56 pair audit + crossings
# ===========================================================================
def check_same_plane_crossings(routed):
    """(h) strict D56 pair audit per physical z plane; count legal crossings."""
    from ..fslw import validate_fslw as fslw_validate
    groups = OrderedDict()
    zero_length_primitive_routes = set()
    for record in routed:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            try:
                z = float(part.get('z_mm'))
            except (TypeError, ValueError):
                continue
            prims = []
            for prim in part.get('primitives') or []:
                if not isinstance(prim, dict):
                    continue
                if prim.get('kind') == 'line':
                    p0 = _finite_xy(prim.get('p0'))
                    p1 = _finite_xy(prim.get('p1'))
                    if p0 is None or p1 is None:
                        continue
                    if math.dist(p0, p1) <= 1e-12:
                        zero_length_primitive_routes.add(route_id)
                        continue
                prims.append(dict(prim))
            if prims:
                key = round(z, 9)
                groups.setdefault(key, {}).setdefault(route_id, []).extend(prims)
    planes = []
    violations = []
    total_crossings = 0
    total_crossing_pairs = 0
    total_violations = 0
    prepared_failures = []
    for z_mm, route_prims in sorted(groups.items()):
        prepared = []
        for route_id, prims in sorted(route_prims.items()):
            try:
                prepared.append(fslw_validate.prepare_route(prims, route_id=route_id))
            except (ValueError, KeyError, TypeError) as error:
                prepared_failures.append(dict(route_id=route_id, z_mm=z_mm,
                                              error=f'{type(error).__name__}: {error}'))
                violations.append(dict(check='crossings', kind='prepare_failed',
                                       route_id=route_id,
                                       detail=f'z={z_mm:g} {error}'))
        if not prepared:
            continue
        started = time.time()
        result = fslw_validate.audit_route_pairs(
            prepared, clearance=D56_CLEARANCE_MM, sagitta=SAGITTA_MM,
            policy='strict')
        plane_violations = result.get('violations') or []
        plane = dict(
            z_mm=_round(z_mm),
            routes=len(prepared),
            parts=sum(len(items) for items in route_prims.values()),
            crossings=int(result.get('crossing_count') or 0),
            crossing_pairs=int(result.get('crossing_pair_count') or 0),
            min_non_crossing_centerline_mm=_round(
                result.get('min_non_crossing_centerline_mm')),
            violations=len(plane_violations),
            runtime_seconds=round(time.time() - started, 3),
        )
        planes.append(plane)
        total_crossings += plane['crossings']
        total_crossing_pairs += plane['crossing_pairs']
        total_violations += len(plane_violations)
        for item in plane_violations[:100]:
            violations.append(dict(
                check='crossings', kind=str(item.get('kind')),
                route_id=item.get('route_a'), other_route=item.get('route_b'),
                detail=f'z={_round(z_mm)} distance={item.get("distance_mm")} '
                       f'at ({item.get("x")},{item.get("y")})'))
    details = dict(planes=planes, total_crossings=total_crossings,
                   total_crossing_pairs=total_crossing_pairs,
                   total_violations=total_violations,
                   min_non_crossing_centerline_mm=min(
                       (plane['min_non_crossing_centerline_mm'] for plane in planes
                        if plane['min_non_crossing_centerline_mm'] is not None),
                       default=None),
                   zero_length_line_routes=sorted(zero_length_primitive_routes)[:50],
                   prepare_failures=prepared_failures[:50])
    return violations, details


# ===========================================================================
# orchestration
# ===========================================================================
def _violation(check_name, kind, route_id=None, other_route=None, detail=None):
    entry = dict(check=check_name, kind=str(kind))
    if route_id is not None:
        try:
            entry['route_id'] = int(route_id)
        except (TypeError, ValueError):
            entry['route_id'] = route_id
    if other_route is not None:
        try:
            entry['other_route'] = int(other_route)
        except (TypeError, ValueError):
            entry['other_route'] = other_route
    if detail is not None:
        entry['detail'] = str(detail)
    return entry


def validate(routes_path, assignment_path=None, out_path=None,
             consistency_out=None, run_dir=None, skip_min_clearance=False,
             skip_crossings=False, verbose=True):
    """Full independent validation of one finished routes_l3d.json."""
    started = time.time()
    routes_path = Path(routes_path)
    if assignment_path is None:
        assignment_path = routes_path.parent / 'assignment_1024.csv'
    if out_path is None:
        out_path = routes_path.parent / 'validation.json'
    if consistency_out is None:
        consistency_out = routes_path.parent / 'validator_consistency_tests.json'
    if run_dir is not None:
        run_dir = Path(run_dir)

    payload, all_records = load_payload(routes_path)
    routed, failed = split_records(all_records)
    true_routes = build_true_routes()
    stack_layer_ids = set(common.PHYSICAL_LAYERS) | {INTERFACE_LAYER_ID}

    violations = []
    checks = OrderedDict()
    stats = Counter()
    stats['records'] = len(all_records)
    stats['routed'] = len(routed)
    stats['failed'] = len(failed)
    stats['route_count_declared'] = payload.get('route_count')

    # -- layer stack / process -------------------------------------------------
    stack_violations, stack_details = check_layer_stack(payload)
    process_details = stack_details.pop('process', dict(embedded=False))
    checks['layer_stack'] = stack_details
    checks['process'] = process_details
    for item in stack_violations:
        check_name = ('process' if str(item.get('kind', '')).startswith('process_')
                      else 'layer_stack')
        violations.append(_violation(check_name, item['kind'],
                                     detail=item.get('detail')))

    # -- (a) structure ---------------------------------------------------------
    structure_violations = []
    structure_details = dict(routes_checked=0, raw_world_structure_errors=[],
                             missing_declared_fields=Counter(), planes=Counter())
    for record in routed:
        route_violations, route_details = check_route_structure(
            record, stack_layer_ids)
        structure_details['routes_checked'] += 1
        for item in route_violations:
            structure_violations.append(_violation(
                'structure', item['kind'], item.get('route_id'),
                detail=item.get('detail')))
        if route_details.get('raw_structure_errors'):
            structure_details['raw_world_structure_errors'].append(
                dict(route_id=record.get('route_id'),
                     errors=route_details['raw_structure_errors']))
        for field in route_details.get('rebuilt', {}).get('missing_fields', []):
            structure_details['missing_declared_fields'][field] += 1
        plane = route_details.get('plane')
        if plane:
            structure_details['planes'][plane] += 1
    structure_details['routes_checked'] = len(routed)
    structure_details['raw_world_structure_error_routes'] = len(
        structure_details['raw_world_structure_errors'])
    structure_details['missing_declared_fields'] = dict(
        sorted(structure_details['missing_declared_fields'].items()))
    structure_details['planes'] = dict(sorted(structure_details['planes'].items()))
    structure_details['violations'] = len(structure_violations)
    structure_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in structure_violations
         if item.get('route_id') is not None})
    structure_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in structure_violations).items()))
    checks['structure'] = structure_details
    violations.extend(structure_violations)

    # -- (b) radius ------------------------------------------------------------
    radius_violations = []
    radius_details = dict(routes_checked=0, flat_arc_count=0,
                          flat_arc_radii=[], transition_count=0,
                          transition_declared_radii=[],
                          transition_min_sampled_radius=None,
                          transition_samples_total=0)
    for record in routed:
        route_violations, route_details = check_route_radius(record)
        radius_details['routes_checked'] += 1
        for item in route_violations:
            radius_violations.append(_violation(
                'radius', item['kind'], item.get('route_id'),
                detail=item.get('detail')))
        flat_arc_count = route_details.get('flat_arc_count') or 0
        radius_details['flat_arc_count'] += flat_arc_count
        radius_details['flat_arc_radii'].extend(
            route_details.get('flat_arc_radii') or [])
        radius_details['transition_count'] += route_details.get('transition_count') or 0
        radius_details['transition_declared_radii'].extend(
            route_details.get('transition_declared_radii') or [])
        radius_details['transition_samples_total'] += (
            route_details.get('transition_samples_total') or 0)
        minimum = route_details.get('transition_min_sampled_radius')
        if minimum is not None:
            if radius_details['transition_min_sampled_radius'] is None or \
                    minimum < radius_details['transition_min_sampled_radius']:
                radius_details['transition_min_sampled_radius'] = minimum
    radius_details['flat_arc_radii'] = sorted(
        {round(value, 9) for value in radius_details['flat_arc_radii']})
    radius_details['transition_declared_radii'] = sorted(
        {round(value, 9) for value in radius_details['transition_declared_radii']})
    radius_details['min_flat_arc_radius'] = (
        min(radius_details['flat_arc_radii'])
        if radius_details['flat_arc_radii'] else None)
    radius_details['r15_required_mm'] = R15_MM
    radius_details['transition_min_required_mm'] = MIN_R15_SAMPLED_MM
    radius_details['violations'] = len(radius_violations)
    radius_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in radius_violations
         if item.get('route_id') is not None})
    radius_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in radius_violations).items()))
    checks['radius'] = radius_details
    violations.extend(radius_violations)

    # -- (c) glass -------------------------------------------------------------
    glass_violations = []
    glass_details = dict(routes_checked=0, samples=0,
                         min_centerline_margin_mm=None,
                         min_edge_margin_mm=None,
                         edge_margin_negative_routes=[],
                         min_z_mm=None, max_z_mm=None)
    edge_negative = set()
    for record in routed:
        route_violations, route_details = check_route_glass(record)
        glass_details['routes_checked'] += 1
        for item in route_violations:
            glass_violations.append(_violation(
                'glass', item['kind'], item.get('route_id'),
                detail=item.get('detail')))
        if not route_details:
            continue
        glass_details['samples'] += route_details.get('samples') or 0
        margin = route_details.get('min_centerline_margin_mm')
        if margin is not None and (glass_details['min_centerline_margin_mm'] is None
                                   or margin < glass_details['min_centerline_margin_mm']):
            glass_details['min_centerline_margin_mm'] = margin
        edge_margin = route_details.get('min_edge_margin_mm')
        if edge_margin is not None and (glass_details['min_edge_margin_mm'] is None
                                        or edge_margin < glass_details['min_edge_margin_mm']):
            glass_details['min_edge_margin_mm'] = edge_margin
        if route_details.get('edge_margin_negative'):
            try:
                edge_negative.add(int(record.get('route_id')))
            except (TypeError, ValueError):
                pass
        for key, target in (('min_z_mm', 'min_z_mm'), ('max_z_mm', 'max_z_mm')):
            value = route_details.get(key)
            if value is None:
                continue
            if target == 'min_z_mm':
                if glass_details[target] is None or value < glass_details[target]:
                    glass_details[target] = value
            else:
                if glass_details[target] is None or value > glass_details[target]:
                    glass_details[target] = value
    glass_details['min_centerline_margin_mm'] = _round(
        glass_details['min_centerline_margin_mm'])
    glass_details['min_edge_margin_mm'] = _round(glass_details['min_edge_margin_mm'])
    glass_details['edge_margin_negative_route_count'] = len(edge_negative)
    glass_details['edge_margin_negative_route_ids'] = sorted(edge_negative)[:100]
    glass_details['bounds'] = dict(x=[0.0, GLASS_XY_MM], y=[0.0, GLASS_XY_MM],
                                   z=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM])
    glass_details['waveguide_half_width_mm'] = WAVEGUIDE_HALF_WIDTH_MM
    glass_details['violations'] = len(glass_violations)
    glass_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in glass_violations
         if item.get('route_id') is not None})
    glass_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in glass_violations).items()))
    checks['glass'] = glass_details
    violations.extend(glass_violations)

    # -- (d) true 3D clearance --------------------------------------------------
    clearance_details = check_true_3d_clearance(routed)
    clearance_block = dict(
        method='fresh four_side_1024.l3d.world.World(fanout1024.common.'
               'layer_stack(), clearance=0.05); check_route(route, '
               'check_self=True) in route-id order, then add_route',
        clearance_mm=MIN_3D_CLEARANCE_MM,
        routes_checked=clearance_details['checked'],
        routes_added=clearance_details['added'],
        violations=clearance_details['violation_count'],
        violation_kinds=clearance_details['by_kind'],
        offending_route_ids=clearance_details['offending_route_ids'],
        offending_route_count=len(clearance_details['offending_route_ids']),
        world=clearance_details['world'],
    )
    for item in clearance_details['violations']:
        violations.append(_violation(
            'clearance', item.get('kind'), item.get('route_id'),
            other_route=item.get('other_route'),
            detail=item.get('detail')))
    if skip_min_clearance:
        min_scan = dict(skipped=True, min_3d_clearance_mm=None)
    else:
        min_scan = measure_min_3d_clearance(routed)
    clearance_block['min_clearance_scan'] = min_scan
    clearance_block['min_3d_clearance_mm'] = min_scan.get('min_3d_clearance_mm')
    clearance_block['min_3d_clearance_lower_bound_mm'] = min_scan.get(
        'min_3d_clearance_lower_bound_mm')
    for group in ('transition_vs_flat', 'transition_vs_transition'):
        for item in (min_scan.get(group) or {}).get('pairs', []):
            if clearance_details['violation_count'] > 0:
                # already reported through the authoritative online world path;
                # the independent scan only adds the measured minimum values
                continue
            violations.append(_violation(
                'clearance', group, item.get('route_id'),
                other_route=item.get('other_route'),
                detail=f'independent_min_scan distance={item.get("distance_mm")} '
                       f'(online world did not flag this pair)'))
    checks['clearance'] = clearance_block

    # -- (e) ports --------------------------------------------------------------
    port_violations, port_details = check_ports(routed, failed, all_records,
                                                true_routes)
    port_details['violations'] = len(port_violations)
    port_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in port_violations
         if item.get('route_id') is not None})
    port_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in port_violations).items()))
    checks['ports'] = port_details
    violations.extend(_violation('ports', item.get('kind'), item.get('route_id'),
                                 detail=item.get('detail'))
                      for item in port_violations)

    # -- (f) assignment ---------------------------------------------------------
    assignment_rows, duplicate_columns = read_assignment(assignment_path)
    assignment_violations, assignment_details = check_assignment(
        routed, failed, assignment_rows, true_routes)
    assignment_details['assignment_file'] = str(assignment_path)
    assignment_details['duplicate_csv_columns'] = duplicate_columns
    assignment_details['violations'] = len(assignment_violations)
    assignment_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in assignment_violations
         if item.get('route_id') is not None})
    assignment_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in assignment_violations).items()))
    checks['assignment'] = assignment_details
    violations.extend(_violation('assignment', item.get('kind'),
                                 item.get('route_id'),
                                 detail=item.get('detail'))
                      for item in assignment_violations)

    # -- (g) consistency self tests --------------------------------------------
    consistency = run_consistency_tests()
    checks['consistency'] = dict(
        tests=consistency['tests'], all_passed=consistency['all_passed'],
        test_count=len(consistency['tests']),
        failed_tests=[test['name'] for test in consistency['tests']
                      if not test['passed']])
    _write_json(consistency_out, consistency)

    # -- (h) same-plane crossings ----------------------------------------------
    if skip_crossings:
        crossing_details = dict(skipped=True)
        crossing_violations = []
    else:
        crossing_violations, crossing_details = check_same_plane_crossings(routed)
    crossing_details['violations'] = len(crossing_violations)
    crossing_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in crossing_violations
         if item.get('route_id') is not None})
    crossing_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in crossing_violations).items()))
    checks['crossings'] = crossing_details
    violations.extend(crossing_violations)

    # -- failures ---------------------------------------------------------------
    failed_details = dict(
        count=len(failed),
        by_plane=dict(sorted(Counter(str(_route_plane(record))
                                     for record in failed).items())),
        by_reason=dict(sorted(Counter(failure_reason(record)
                                      for record in failed).items())),
        route_ids=sorted(int(record['route_id']) for record in failed
                         if record.get('route_id') is not None),
        records=[dict(route_id=record.get('route_id'),
                      plane=_route_plane(record),
                      source_endpoint=record.get('source_endpoint'),
                      target_endpoint=record.get('target_endpoint'),
                      status=record.get('status'),
                      reason=failure_reason(record)) for record in failed],
    )
    stats['failed_by_plane'] = failed_details['by_plane']
    stats['failed_by_reason'] = failed_details['by_reason']
    checks['failures'] = failed_details

    # -- aggregate counts -------------------------------------------------------
    for item in violations:
        item.setdefault('check', 'other')
    geometry_checks = ('structure', 'radius', 'glass', 'clearance', 'ports',
                       'crossings')
    contract_checks = ('layer_stack', 'process', 'assignment')
    check_names = ('structure', 'radius', 'glass', 'clearance', 'ports',
                   'assignment', 'crossings', 'layer_stack', 'process')
    total_transitions = sum(int(record.get('n_transitions') or 0)
                            for record in routed)
    if total_transitions == 0:
        total_transitions = radius_details['transition_count']
    total_length = None
    xy_length = None
    try:
        total_length = float(sum(float(record.get('length_mm') or 0.0)
                                 for record in routed))
        xy_length = float(sum(float(record.get('xy_length_mm') or 0.0)
                              for record in routed))
    except (TypeError, ValueError):
        pass
    if not total_length:
        total_length = None
    counts = dict(
        records=len(all_records),
        routed=len(routed),
        failed=len(failed),
        routed_by_plane=dict(sorted(Counter(
            str(_route_plane(record)) for record in routed).items())),
        failed_by_plane=failed_details['by_plane'],
        transitions=total_transitions,
        lifted_routes=sum(1 for record in routed
                          if int(record.get('n_transitions') or 0) > 0),
        flat_routes=sum(1 for record in routed
                        if int(record.get('n_transitions') or 0) == 0),
        flat_arc_count=radius_details['flat_arc_count'],
        transition_count=radius_details['transition_count'],
        total_length_mm=_round(total_length),
        xy_length_mm=_round(xy_length),
        same_plane_crossings=crossing_details.get('total_crossings'),
        same_plane_crossing_pairs=crossing_details.get('total_crossing_pairs'),
        same_plane_min_non_crossing_mm=crossing_details.get(
            'min_non_crossing_centerline_mm'),
        min_3d_clearance_mm=clearance_block.get('min_3d_clearance_mm'),
        min_flat_arc_radius_mm=radius_details.get('min_flat_arc_radius'),
        min_transition_sampled_radius_mm=radius_details.get(
            'transition_min_sampled_radius'),
        min_centerline_glass_margin_mm=glass_details.get('min_centerline_margin_mm'),
        min_edge_glass_margin_mm=glass_details.get('min_edge_margin_mm'),
        offending_routes_by_check={
            name: len(checks[name].get('offending_route_ids') or [])
            for name in check_names},
        violation_total=len(violations),
    )
    geometry_pass = not any(item['check'] in geometry_checks
                            for item in violations)
    contract_pass = not any(item['check'] in contract_checks
                            for item in violations)
    validator_consistency_passed = bool(consistency['all_passed'])
    validation_pass = bool(geometry_pass and contract_pass
                           and validator_consistency_passed)
    runtime = time.time() - started
    report = OrderedDict([
        ('schema', VALIDATOR_SCHEMA),
        ('validator', 'four_side_1024.fanout1024.validate_final'),
        ('validated_at', _now()),
        ('routes_file', str(routes_path)),
        ('routes_file_sha256', _sha256(routes_path)),
        ('assignment_file', str(assignment_path)),
        ('run_dir', str(run_dir) if run_dir is not None else
         str(routes_path.parent)),
        ('route_count', len(all_records)),
        ('route_count_declared', payload.get('route_count')),
        ('routed', len(routed)),
        ('failed', len(failed)),
        ('checks', checks),
        ('violations', violations[:2000]),
        ('violation_count', len(violations)),
        ('violations_truncated', len(violations) > 2000),
        ('violation_counts_by_check', dict(sorted(Counter(
            item['check'] for item in violations).items()))),
        ('geometry_pass', bool(geometry_pass)),
        ('contract_pass', bool(contract_pass)),
        ('validation_pass', bool(validation_pass)),
        ('validator_consistency_passed', validator_consistency_passed),
        ('min_3d_clearance_mm', clearance_block.get('min_3d_clearance_mm')),
        ('min_3d_clearance_lower_bound_mm', clearance_block.get(
            'min_3d_clearance_lower_bound_mm')),
        ('counts', counts),
        ('exit_code', 0 if validation_pass else
         (2 if not validator_consistency_passed else 1)),
        ('runtime_seconds', round(runtime, 2)),
    ])
    out_path = Path(out_path)
    _write_json(out_path, report)
    if verbose:
        print(_summary_text(report, out_path, consistency_out))
    return report, out_path, consistency


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _summary_text(report, out_path, consistency_out):
    lines = []
    lines.append(f"[validate_final] routes={report['route_count']} "
                 f"routed={report['routed']} failed={report['failed']}")
    for name in ('structure', 'radius', 'glass', 'clearance', 'ports',
                 'assignment', 'crossings', 'layer_stack', 'process'):
        block = report['checks'].get(name) or {}
        count = block.get('violations', 0)
        lines.append(f"  {name:<12} violations={count}")
    clearance = report['checks']['clearance']
    lines.append(f"  min_3d_clearance={clearance.get('min_3d_clearance_mm')} mm "
                 f"(lower_bound={clearance.get('min_3d_clearance_lower_bound_mm')})")
    consistency = report['checks']['consistency']
    lines.append(f"  consistency_tests={consistency['test_count']} "
                 f"passed={consistency['all_passed']} "
                 f"failed={consistency['failed_tests']}")
    lines.append(f"  geometry_pass={report['geometry_pass']} "
                 f"contract_pass={report['contract_pass']} "
                 f"validation_pass={report['validation_pass']} "
                 f"violation_count={report['violation_count']} "
                 f"runtime={report['runtime_seconds']}s")
    lines.append(f"  wrote {out_path}")
    lines.append(f"  wrote {consistency_out}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Independent final validator for the fanout-first 1024 run.')
    parser.add_argument('--routes', default=str(RUN_DIR / 'routes_l3d.json'))
    parser.add_argument('--assignment',
                        default=None,
                        help='assignment_1024.csv (default: next to routes file)')
    parser.add_argument('--out', default=None,
                        help='validation.json path (default: next to routes)')
    parser.add_argument('--consistency-out', default=None,
                        help='validator_consistency_tests.json path')
    parser.add_argument('--run-dir', default=None)
    parser.add_argument('--skip-min-clearance', action='store_true',
                        help='skip the exact minimum 3D distance scan (fast mode)')
    parser.add_argument('--skip-crossings', action='store_true',
                        help='skip the same-plane pair audit (fast mode)')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    report, out_path, _consistency = validate(
        args.routes, assignment_path=args.assignment, out_path=args.out,
        consistency_out=args.consistency_out, run_dir=args.run_dir,
        skip_min_clearance=args.skip_min_clearance,
        skip_crossings=args.skip_crossings, verbose=not args.quiet)
    return int(report['exit_code'])


if __name__ == '__main__':
    sys.exit(main())
