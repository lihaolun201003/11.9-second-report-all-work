# -*- coding: utf-8 -*-
"""Independent validator for the 21-routing-height rebalanced 1024 experiment.

This is a *new independent experiment*; the 18-layer baseline RUN_DIR
(``FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024``) is strictly read-only.

The model is read from ``RUN_DIR/layer_planes.json`` (the 21 routing heights:
19 body planes ids 2..20 + interface-body planes 1001/1002) and is verified
against the frozen SPEC.md table; ``assignment_1024.csv`` and
``routes_l3d.json`` are validated against that model with a fresh
``l3d.world.World`` rebuilt from the model heights (clearance = 0.05 mm).

Checks
------
(a) routed / failed counts, real failed route ids + reasons;
(b) direct (interface-body, needs_transition=False) routes: exactly one flat
    part at its interface plane (layer_id 1001/1002, z = 0.0/0.5), no
    transition, exact port poses + headings, n_transitions=0, z_span=0,
    lifted=False; exact count (100 for the 21-height model);
(c) non-direct routes: exactly 2 transitions, interface start/end z, body flat
    layer_id == assigned target plane and z == model z, lead continuity;
(d) structure / continuity / declared-field contract checks;
(e) R15: every flat arc exactly 15 mm, every transition's true 3D curvature
    radius sampled densely >= 15 - 1e-6 mm;
(f) glass bounds (x, y in [0, 150], z in [-0.35, 0.65]) + edge margin report;
(g) true 3D clearance: fresh World(model stack, clearance=0.05), every route in
    route-id order, violation kinds + offending route ids; independent exact-ish
    minimum true 3D centreline distance scan;
(h) same-physical-plane strict D56 audit for EACH of the 21 planes (interface
    planes include the frozen leads *and* the direct bodies in the same audit),
    crossings / crossing pairs / min non-crossing distance / violations;
(i) port identity / coverage vs ``common.routes()``;
(j) assignment match: 21 distinct heights, min pitch >= 0.05, C4 orbit
    single-plane, manual groups on their fixed planes, per-plane counts;
(k) 50/49 um consistency tests (online World code path vs validator);
(l) totals: transitions (expect 1848), transition length, total/max length,
    crossing distribution (max / p95 / mean), per-route + per-plane stats.

Outputs into RUN_DIR: ``validation.json``, ``validator_consistency_tests.json``,
``crossing_stats.json``.

Baseline regression (never writes the baseline RUN_DIR)::

    python -m four_side_1024.fanout1024.reheight21.validate21 \
        --baseline-model --run-dir <baseline RUN_DIR> \
        --out-dir scratch/fanout1024_report/reheight21_baseline \
        --regression-expect-baseline

Exit codes: 0 = geometry + contract + consistency pass, 1 = violations,
2 = validator consistency / baseline regression failure.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import common
from ...fsd25d import path3d as P
from ...l3d.world import World
from ...l3d.layers import build_stack
from ...fslw import validate_fslw

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = common.OUTPUT_ROOT
BASELINE_RUN_DIR = common.RUN_DIR          # 18-layer baseline: READ-ONLY
RUN_DIR_21H = OUTPUT_ROOT / 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'

VALIDATOR_SCHEMA = 'fanout_first_21_height_validation_v1'
CONSISTENCY_SCHEMA = 'fanout_first_21_height_consistency_v1'
CROSSING_SCHEMA = 'fanout_first_21_height_crossing_stats_v1'

# -- SPEC.md section 1: frozen 21-routing-height model -----------------------
SPEC_BODY_HEIGHTS = OrderedDict([
    (2, -0.35), (3, -0.30), (4, -0.25), (5, -0.20), (6, -0.15), (7, -0.10),
    (20, -0.05), (8, 0.05), (9, 0.10), (10, 0.15), (11, 0.20), (12, 0.25),
    (13, 0.30), (14, 0.35), (15, 0.40), (16, 0.45), (17, 0.55), (18, 0.60),
    (19, 0.65),
])
SPEC_INTERFACE_PLANES = OrderedDict([
    (1001, dict(label='Z1_INTERFACE', z_mm=0.0, interface='z1',
                level=common.Z1_INTERFACE_MM)),
    (1002, dict(label='Z2_INTERFACE', z_mm=0.5, interface='z2',
                level=common.Z2_INTERFACE_MM)),
])
SPEC_INTERFACE_IDS = set(SPEC_INTERFACE_PLANES)
SPEC_MANUAL_FIXED = OrderedDict([
    ('Z1-U1', 2), ('Z1-U2', 3), ('Z1-U3', 4), ('Z1-U4', 5),
    ('Z2-U1', 10), ('Z2-U2', 11), ('Z2-U3', 12), ('Z2-U4', 13),
])
#: SPEC.md section 2: exact per-plane assigned route counts
SPEC_EXPECTED_ASSIGNED = OrderedDict([
    (2, 64), (3, 64), (4, 64), (5, 64),
    (6, 52), (7, 52), (20, 52), (1001, 52), (8, 48),
    (10, 16), (11, 16), (12, 40), (13, 40),
    (9, 48), (14, 48), (15, 48), (16, 52), (17, 52), (18, 52),
    (19, 52), (1002, 48),
])
SPEC_DIRECT_TOTAL = 100
SPEC_DIRECT_BY_PLANE = {1001: 52, 1002: 48}
#: baseline regression expectations (18-layer experiment, read-only)
BASELINE_REGRESSION = dict(
    routed=1024, failed=0, direct_routes=0, transitions=2048,
    crossings_total=18108,
    crossings_by_z={-0.11: 5610, -0.05: 5284},
    min_3d_clearance_mm=0.149965866,
    total_length_mm=156893.005,
    total_length_tol=1e-3,
    clearance_tol=1e-6,
)

# -- tolerances (same spirit as the 18-layer validator) ----------------------
TOL_POS_MM = 1e-6
TOL_Z_MM = 1e-6
TOL_RADIUS_MM = 1e-6
TOL_LEN_FIELD_MM = 1e-4
TOL_TANGENT = 1e-6
TOL_GLASS_MM = 1e-6
TOL_PLANE_GAP_MM = 1e-9
R15_MM = 15.0
MIN_R15_SAMPLED_MM = R15_MM - 1e-6
GLASS_XY_MM = 150.0
GLASS_Z_MIN_MM = -0.35
GLASS_Z_MAX_MM = 0.65
WAVEGUIDE_HALF_WIDTH_MM = common.WIDTH_MM / 2.0
MIN_3D_CLEARANCE_MM = 0.05
MIN_LAYER_PITCH_MM = 0.05
D56_CLEARANCE_MM = common.CLEARANCE_2D_MM
SAGITTA_MM = 0.0005
INTERFACE_LEGACY_LAYER_ID = 1
TRANSITION_SAMPLE_STEP_MM = 0.01
TRANSITION_SCAN_STEP_MM = 0.02
ARC_SAMPLE_STEP_MM = 0.05
GLASS_TRANSITION_STEP_MM = 0.02
CURVATURE_JOIN_MIN_LENGTH_MM = 1e-9

ROUTED_STATUSES = {'routed', 'ok', 'success', 'valid', 'accepted', 'done'}
FAILED_STATUSES = {'failed', 'fail', 'error', 'unrouted', 'invalid', 'rejected'}
FAILURE_REASON_KEYS = ('reason', 'failure_reason', 'error', 'fail_reason',
                       'detail', 'message')


# ===========================================================================
# basic helpers
# ===========================================================================
def _now():
    return datetime.now().isoformat(timespec='seconds')


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + '\n', encoding='utf-8')
    return path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _round(value, digits=9):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), digits)


def _fmt(value, digits=6):
    if value is None:
        return 'n/a'
    if isinstance(value, float):
        return f'{value:.{digits}g}'
    return str(value)


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def normalize_status(record):
    status = record.get('status')
    if status is None:
        return 'routed'
    text = str(status).strip().lower()
    if text in ROUTED_STATUSES:
        return 'routed'
    if text in FAILED_STATUSES:
        return 'failed'
    return 'failed'   # unknown status is never silently promoted to success


def failure_reason(record):
    for key in FAILURE_REASON_KEYS:
        value = record.get(key)
        if value not in (None, ''):
            return str(value)
    return str(record.get('status') or 'unknown')


def load_payload(path):
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise FileNotFoundError(f'routes file not found / not a JSON object: {path}')
    records = payload.get('routes')
    if not isinstance(records, list):
        raise ValueError(f'routes file has no "routes" list: {path}')
    return payload, records


def split_records(records):
    routed, failed = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        (routed if normalize_status(record) == 'routed' else failed).append(record)
    routed.sort(key=lambda item: int(item.get('route_id', 0)))
    failed.sort(key=lambda item: int(item.get('route_id', 0)))
    return routed, failed


def build_true_routes():
    return {int(route['route_id']): route for route in common.routes()}


def interface_z(plane):
    return float(common.INTERFACE_Z[str(plane)])


def interface_plane_id(plane):
    return 1001 if str(plane) == 'z1' else 1002


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


def _prim_point(prim, t):
    return P.prim_point_at(prim, t)


def _prim_tangent(prim, t):
    return P.prim_tangent_at(prim, t)


def _violation(check, kind, route_id=None, other_route=None, detail=None):
    entry = dict(check=check, kind=str(kind))
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


# ===========================================================================
# layer-plane model
# ===========================================================================
def _spec_model():
    """The frozen SPEC.md section 1 model (ground truth, id -> plane dict)."""
    planes = OrderedDict()
    for plane_id, z in SPEC_BODY_HEIGHTS.items():
        planes[int(plane_id)] = dict(
            plane_id=int(plane_id), label=f'L{int(plane_id)}',
            z_mm=float(z), kind='body', interface=None)
    for plane_id, spec in SPEC_INTERFACE_PLANES.items():
        planes[int(plane_id)] = dict(
            plane_id=int(plane_id), label=spec['label'],
            z_mm=float(spec['z_mm']), kind='interface_body',
            interface=spec['interface'])
    return planes


def _looks_like_planes(value):
    return isinstance(value, (list, dict))


def load_layer_planes(path):
    """Load RUN_DIR/layer_planes.json (tolerant to the small schema variants)."""
    payload = _read_json(path)
    if payload is None:
        return None, 'missing'
    block = payload
    if isinstance(payload, dict):
        for key in ('planes', 'layer_planes', 'routing_planes', 'heights'):
            if key in payload:
                block = payload[key]
                break
    entries = []
    if isinstance(block, list):
        entries = [dict(item) for item in block if isinstance(item, dict)]
    elif isinstance(block, dict):
        for key, value in block.items():
            if not isinstance(value, dict):
                continue
            entry = dict(value)
            if entry.get('plane_id') is None and entry.get('id') is None \
                    and entry.get('layer_id') is None:
                entry['plane_id'] = key
            entries.append(entry)
    if not entries:
        return None, 'empty'
    planes = OrderedDict()
    for entry in entries:
        plane_id = _parse_int(entry.get('plane_id', entry.get('id',
                            entry.get('layer_id', entry.get('plane')))))
        if plane_id is None:
            continue
        z = _parse_float(entry.get('z_mm', entry.get('z',
                        entry.get('physical_z_mm', entry.get('target_z_mm')))))
        if z is None:
            continue
        kind = str(entry.get('kind') or entry.get('type') or '').lower()
        label = str(entry.get('label') or entry.get('name') or f'P{plane_id}')
        interface = entry.get('interface') or entry.get('plane_name')
        if not kind:
            kind = 'body' if plane_id not in SPEC_INTERFACE_IDS else 'interface_body'
        if 'interface' in kind:
            kind = 'interface_body'
        planes[plane_id] = dict(plane_id=plane_id, label=label, z_mm=float(z),
                                kind=kind, interface=interface)
    # infer the interface side for the frozen interface-plane ids
    for plane_id, spec in SPEC_INTERFACE_PLANES.items():
        plane = planes.get(int(plane_id))
        if plane is not None and plane.get('interface') is None:
            plane['interface'] = spec['interface']
    return (planes if planes else None), 'layer_planes.json'


def derive_baseline_model():
    """18-layer model derived from the frozen baseline (regression mode only)."""
    planes = OrderedDict()
    for plane_id, z in common.PHYSICAL_LAYERS.items():
        planes[int(plane_id)] = dict(plane_id=int(plane_id), label=f'L{int(plane_id)}',
                                     z_mm=float(z), kind='body', interface=None)
    return planes


def body_heights_of(planes):
    return OrderedDict((int(plane['plane_id']), float(plane['z_mm']))
                       for plane in planes.values() if plane['kind'] == 'body')


def interface_plane_map(planes):
    return {int(plane['plane_id']): plane for plane in planes.values()
            if plane['kind'] == 'interface_body'}


def plane_z_map(planes):
    return {int(plane['plane_id']): float(plane['z_mm'])
            for plane in planes.values()}


def plane_pitch_audit(planes):
    ordered = sorted(planes.values(), key=lambda item: item['z_mm'])
    rows = []
    minimum = None
    for low, high in zip(ordered, ordered[1:]):
        gap = float(high['z_mm']) - float(low['z_mm'])
        rows.append(dict(low=low['plane_id'], high=high['plane_id'],
                         low_z_mm=low['z_mm'], high_z_mm=high['z_mm'],
                         gap_mm=gap))
        minimum = gap if minimum is None else min(minimum, gap)
    return rows, minimum


def build_model_stack(planes):
    heights = body_heights_of(planes)
    if not heights:
        raise ValueError('model has no body planes')
    stack = build_stack('reheight21_body_stack', heights=heights,
                        note='21-routing-height experiment body planes')
    return stack


def check_model(planes, model_source, baseline_mode=False):
    """(j part 1) validate the layer-plane model against frozen SPEC.md."""
    violations = []
    details = dict(source=model_source, baseline_mode=bool(baseline_mode),
                   plane_count=len(planes),
                   expected_plane_count=(18 if baseline_mode else 21),
                   body_plane_count=sum(1 for p in planes.values()
                                        if p['kind'] == 'body'),
                   interface_plane_count=sum(1 for p in planes.values()
                                             if p['kind'] == 'interface_body'))
    if baseline_mode:
        expected_ids = set(int(key) for key in common.PHYSICAL_LAYERS)
        for plane_id, plane in planes.items():
            if plane_id not in expected_ids:
                violations.append(dict(kind='baseline_plane_unknown',
                                       detail=f'plane {plane_id}'))
            elif abs(plane['z_mm'] - float(common.PHYSICAL_LAYERS[plane_id])) > 1e-9:
                violations.append(dict(kind='baseline_plane_z_mismatch',
                                       detail=f'plane {plane_id}'))
    else:
        if details['plane_count'] != 21:
            violations.append(dict(kind='plane_count_not_21',
                                   detail=f'{details["plane_count"]}'))
        if details['body_plane_count'] != 19:
            violations.append(dict(kind='body_plane_count_not_19',
                                   detail=f'{details["body_plane_count"]}'))
        if details['interface_plane_count'] != 2:
            violations.append(dict(kind='interface_plane_count_not_2',
                                   detail=f'{details["interface_plane_count"]}'))
        for plane_id, z in SPEC_BODY_HEIGHTS.items():
            plane = planes.get(int(plane_id))
            if plane is None:
                violations.append(dict(kind='model_body_plane_missing',
                                       detail=f'plane {plane_id}'))
            elif plane['kind'] != 'body':
                violations.append(dict(kind='model_plane_kind_mismatch',
                                       detail=f'plane {plane_id} kind={plane["kind"]}'))
            elif abs(plane['z_mm'] - float(z)) > 1e-9:
                violations.append(dict(kind='model_plane_z_mismatch',
                                       detail=f'plane {plane_id} z={plane["z_mm"]} '
                                              f'expected={z}'))
        for plane_id, spec in SPEC_INTERFACE_PLANES.items():
            plane = planes.get(int(plane_id))
            if plane is None:
                violations.append(dict(kind='model_interface_plane_missing',
                                       detail=f'plane {plane_id}'))
                continue
            if plane['kind'] != 'interface_body':
                violations.append(dict(kind='model_plane_kind_mismatch',
                                       detail=f'plane {plane_id} kind={plane["kind"]}'))
            if abs(plane['z_mm'] - float(spec['z_mm'])) > 1e-9:
                violations.append(dict(kind='model_plane_z_mismatch',
                                       detail=f'plane {plane_id}'))
            if str(plane.get('interface') or '') != spec['interface']:
                violations.append(dict(kind='model_plane_interface_mismatch',
                                       detail=f'plane {plane_id} '
                                              f'interface={plane.get("interface")}'))
        for plane_id in planes:
            if plane_id not in SPEC_BODY_HEIGHTS and plane_id not in SPEC_INTERFACE_IDS:
                violations.append(dict(kind='model_unknown_plane_id',
                                       detail=f'plane {plane_id}'))
    pitch_rows, minimum = plane_pitch_audit(planes)
    details['plane_pitch'] = pitch_rows
    details['min_pitch_mm'] = minimum
    if minimum is None or minimum < MIN_LAYER_PITCH_MM - TOL_PLANE_GAP_MM:
        violations.append(dict(kind='min_plane_pitch_below_50um',
                               detail=f'min_pitch={minimum}'))
    details['distinct_heights'] = len({round(p['z_mm'], 9)
                                       for p in planes.values()})
    if details['distinct_heights'] != details['plane_count']:
        violations.append(dict(kind='plane_heights_not_distinct',
                               detail=f'{details["distinct_heights"]} distinct '
                                      f'of {details["plane_count"]}'))
    details['sorted_planes'] = [
        dict(plane_id=plane['plane_id'], label=plane['label'],
             z_mm=_round(plane['z_mm']), kind=plane['kind'],
             interface=plane.get('interface'))
        for plane in sorted(planes.values(), key=lambda item: item['z_mm'])]
    details['violations'] = len(violations)
    return violations, details


# ===========================================================================
# primitive / part structure checks
# ===========================================================================
def _check_primitive_list(route_id, part_index, primitives, violations):
    if not isinstance(primitives, list) or not primitives:
        violations.append(dict(kind='empty_flat_part', route_id=route_id,
                               detail=f'part={part_index} has no primitives'))
        return
    previous = None
    for index, prim in enumerate(primitives):
        if not isinstance(prim, dict):
            violations.append(dict(kind='primitive_not_mapping', route_id=route_id,
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
                violations.append(dict(kind='zero_length_line', route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
        elif kind == 'arc':
            try:
                center = _finite_xy(prim.get('center'))
                radius = float(prim.get('radius'))
                start = float(prim.get('start_angle'))
                sweep = float(prim.get('sweep'))
            except (TypeError, ValueError):
                violations.append(dict(kind='arc_missing_parameters',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
                previous = None
                continue
            if center is None:
                violations.append(dict(kind='arc_invalid_parameters',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
                previous = None
                continue
            if radius <= 0.0:
                violations.append(dict(kind='arc_nonpositive_radius',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
            if not (0.0 < abs(sweep) <= 2.0 * math.pi + 1e-12):
                violations.append(dict(kind='arc_invalid_sweep',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
            expected_p0 = (center[0] + radius * math.cos(start),
                           center[1] + radius * math.sin(start))
            expected_p1 = (center[0] + radius * math.cos(start + sweep),
                           center[1] + radius * math.sin(start + sweep))
            if math.dist(expected_p0, p0) > TOL_POS_MM:
                violations.append(dict(kind='arc_start_inconsistent',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
            if math.dist(expected_p1, p1) > TOL_POS_MM:
                violations.append(dict(kind='arc_end_inconsistent',
                                       route_id=route_id,
                                       detail=f'part={part_index} prim={index}'))
        else:
            violations.append(dict(kind='unknown_primitive_kind', route_id=route_id,
                                   detail=f'part={part_index} prim={index} '
                                          f'kind={kind!r}'))
            previous = None
            continue
        if previous is not None:
            prev_p1 = _finite_xy(previous.get('p1'))
            if prev_p1 is not None and math.dist(prev_p1, p0) > TOL_POS_MM:
                violations.append(dict(
                    kind='flat_primitive_discontinuity', route_id=route_id,
                    detail=f'part={part_index} prim={index}'))
                previous = None
                continue
            try:
                tangent_gap = math.hypot(
                    _prim_tangent(previous, 1.0)[0] - _prim_tangent(prim, 0.0)[0],
                    _prim_tangent(previous, 1.0)[1] - _prim_tangent(prim, 0.0)[1])
            except (KeyError, TypeError, ValueError):
                tangent_gap = 0.0
            if tangent_gap > TOL_TANGENT:
                violations.append(dict(
                    kind='flat_tangent_discontinuity', route_id=route_id,
                    detail=f'part={part_index} prim={index} '
                           f'tangent_gap={tangent_gap:.3g}'))
        previous = prim


def _part_flat_z(part):
    try:
        return float(part.get('z_mm'))
    except (TypeError, ValueError):
        return None


def _check_flat_part(route_id, part_index, part, z_map, interface_ids, violations,
                     plane_label=None):
    z = _part_flat_z(part)
    if z is None:
        violations.append(dict(kind='flat_missing_z', route_id=route_id,
                               detail=f'part={part_index}'))
        return
    layer_id = _parse_int(part.get('layer_id'))
    if layer_id is None:
        violations.append(dict(kind='flat_missing_layer_id', route_id=route_id,
                               detail=f'part={part_index}'))
        return
    if layer_id == INTERFACE_LEGACY_LAYER_ID:
        # legacy interface lead layer id is accepted only for measured z=0/0.5
        if min(abs(z - 0.0), abs(z - 0.5)) > TOL_Z_MM:
            violations.append(dict(kind='legacy_interface_flat_wrong_z',
                                   route_id=route_id,
                                   detail=f'part={part_index} z={z!r}'))
    elif layer_id in interface_ids:
        expected = z_map.get(layer_id)
        if expected is None or abs(z - expected) > TOL_Z_MM:
            violations.append(dict(kind='interface_flat_wrong_z', route_id=route_id,
                                   detail=f'part={part_index} layer={layer_id} '
                                          f'z={z!r} expected={expected!r}'))
    elif layer_id in z_map:
        if abs(z - z_map[layer_id]) > TOL_Z_MM:
            violations.append(dict(kind='body_flat_wrong_z', route_id=route_id,
                                   detail=f'part={part_index} layer={layer_id} '
                                          f'z={z!r} expected={z_map[layer_id]!r}'))
    else:
        violations.append(dict(kind='flat_unknown_layer_id', route_id=route_id,
                               detail=f'part={part_index} layer_id={layer_id} '
                                      f'(plane {plane_label})'))
    primitives = part.get('primitives')
    _check_primitive_list(route_id, part_index, primitives, violations)
    if isinstance(primitives, list) and primitives:
        try:
            length = P.path_length(primitives)
        except (KeyError, TypeError, ValueError):
            length = None
        declared = part.get('length_mm')
        if length is not None and declared is not None:
            try:
                if abs(float(declared) - length) > TOL_LEN_FIELD_MM:
                    violations.append(dict(kind='flat_part_length_mismatch',
                                           route_id=route_id,
                                           detail=f'part={part_index} '
                                                  f'declared={declared!r} '
                                                  f'rebuilt={length:.9g}'))
            except (TypeError, ValueError):
                violations.append(dict(kind='flat_part_length_invalid',
                                       route_id=route_id,
                                       detail=f'part={part_index}'))


def _check_transition(route_id, index, parts, violations):
    part = parts[index]
    if not isinstance(part, dict):
        violations.append(dict(kind='transition_not_mapping', route_id=route_id,
                               detail=f'part={index}'))
        return
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
        return
    if start is None or end is None or direction is None:
        return
    norm = math.hypot(direction[0], direction[1])
    if abs(norm - 1.0) > TOL_TANGENT:
        violations.append(dict(kind='transition_direction_not_unit',
                               route_id=route_id,
                               detail=f'part={index} norm={norm:.9g}'))
        if norm > 0.0:
            direction = (direction[0] / norm, direction[1] / norm)
    prev_z = _part_flat_z(parts[index - 1]) if index > 0 else None
    next_z = _part_flat_z(parts[index + 1]) if index + 1 < len(parts) else None
    if prev_z is not None and abs(z0 - prev_z) > TOL_Z_MM:
        violations.append(dict(kind='transition_prev_height_mismatch',
                               route_id=route_id,
                               detail=f'part={index} z0={z0!r} '
                                      f'prev_z={prev_z!r}'))
    if next_z is not None and abs(z1 - next_z) > TOL_Z_MM:
        violations.append(dict(kind='transition_next_height_mismatch',
                               route_id=route_id,
                               detail=f'part={index} z1={z1!r} '
                                      f'next_z={next_z!r}'))
    if prev_z is not None and next_z is not None and abs(z0 - prev_z) <= TOL_Z_MM \
            and abs(z1 - next_z) <= TOL_Z_MM:
        pass
    try:
        prev_prim = parts[index - 1]['primitives'][-1]
        next_prim = parts[index + 1]['primitives'][0]
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
                               detail=f'part={index} '
                                      f'd={math.dist(prev_end, start):.3g}'))
    if next_start is not None and math.dist(end, next_start) > TOL_POS_MM:
        violations.append(dict(kind='transition_end_position_mismatch',
                               route_id=route_id,
                               detail=f'part={index} '
                                      f'd={math.dist(end, next_start):.3g}'))
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
    if radius is not None and radius > 0.0:
        dz = abs(z1 - z0)
        if dz <= 0.0:
            violations.append(dict(kind='zero_height_transition',
                                   route_id=route_id, detail=f'part={index}'))
        elif dz > 2.0 * radius + 1e-9:
            violations.append(dict(kind='transition_height_exceeds_diameter',
                                   route_id=route_id,
                                   detail=f'part={index} dz={dz!r} r={radius!r}'))
        else:
            expected_theta = math.acos(max(-1.0, min(1.0,
                                                     1.0 - dz / (2.0 * radius))))
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
                                       detail=f'part={index}'))
            if length is not None and abs(length - expected_length) > TOL_POS_MM:
                violations.append(dict(kind='transition_length_mismatch',
                                       route_id=route_id,
                                       detail=f'part={index}'))
            if footprint is not None:
                expected_end = (start[0] + direction[0] * footprint,
                                start[1] + direction[1] * footprint)
                if math.dist(expected_end, end) > TOL_POS_MM:
                    violations.append(dict(kind='transition_end_mismatch',
                                           route_id=route_id,
                                           detail=f'part={index}'))


def _flat_part(part):
    return isinstance(part, dict) and part.get('kind') == 'flat'


def _interface_layer_ids(model_interface_ids):
    return set(model_interface_ids) | {INTERFACE_LEGACY_LAYER_ID}


# ===========================================================================
# (b) direct interface-body routes
# ===========================================================================
def check_direct_route(record, row, model, endpoints, violations):
    route_id = int(record.get('route_id'))
    plane = str(record.get('plane') or row.get('plane') or '')
    if plane not in ('z1', 'z2'):
        violations.append(dict(kind='direct_route_unknown_plane', route_id=route_id,
                               detail=repr(record.get('plane'))))
        return
    expected_plane_id = interface_plane_id(plane)
    expected_z = interface_z(plane)
    parts = record.get('parts')
    if not isinstance(parts, list) or len(parts) != 1:
        violations.append(dict(kind='direct_route_parts_not_single_flat',
                               route_id=route_id,
                               detail=f'parts={len(parts) if isinstance(parts, list) else parts!r}'))
        return
    part = parts[0]
    if not _flat_part(part):
        violations.append(dict(kind='direct_route_part_not_flat', route_id=route_id,
                               detail=repr(part.get('kind') if isinstance(part, dict)
                                           else part)))
        return
    if _parse_int(part.get('layer_id')) != expected_plane_id:
        violations.append(dict(kind='direct_route_wrong_interface_plane',
                               route_id=route_id,
                               detail=f'layer_id={part.get("layer_id")!r} '
                                      f'expected={expected_plane_id}'))
    if _part_flat_z(part) is None or abs(_part_flat_z(part) - expected_z) > TOL_Z_MM:
        violations.append(dict(kind='direct_route_wrong_interface_z',
                               route_id=route_id,
                               detail=f'z={part.get("z_mm")!r} expected={expected_z!r}'))
    _check_primitive_list(route_id, 0, part.get('primitives'), violations)
    primitives = part.get('primitives') or []
    if not primitives:
        return
    source_id = record.get('source_endpoint') or (row or {}).get('source_endpoint')
    target_id = record.get('target_endpoint') or (row or {}).get('target_endpoint')
    if source_id not in endpoints or target_id not in endpoints:
        violations.append(dict(kind='direct_route_endpoint_missing',
                               route_id=route_id,
                               detail=f'{source_id!r} -> {target_id!r}'))
        return
    source = endpoints[source_id]
    target = endpoints[target_id]
    start_xy = tuple(float(v) for v in source['routing_xy'])
    start_inward = tuple(float(v) for v in source['inward'])
    end_xy = tuple(float(v) for v in target['routing_xy'])
    end_inward = tuple(float(v) for v in target['inward'])
    first_p0 = _finite_xy(primitives[0].get('p0'))
    last_p1 = _finite_xy(primitives[-1].get('p1'))
    if first_p0 is None or math.dist(first_p0, start_xy) > TOL_POS_MM:
        violations.append(dict(kind='direct_route_start_not_at_source_port',
                               route_id=route_id,
                               detail=f'start={first_p0} port={start_xy}'))
    if last_p1 is None or math.dist(last_p1, end_xy) > TOL_POS_MM:
        violations.append(dict(kind='direct_route_end_not_at_target_port',
                               route_id=route_id,
                               detail=f'end={last_p1} port={end_xy}'))
    try:
        tangent_start = _prim_tangent(primitives[0], 0.0)
        if math.hypot(tangent_start[0] - start_inward[0],
                      tangent_start[1] - start_inward[1]) > TOL_TANGENT:
            violations.append(dict(kind='direct_route_start_heading_mismatch',
                                   route_id=route_id,
                                   detail=f'tangent={tangent_start} '
                                          f'inward={start_inward}'))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    try:
        tangent_end = _prim_tangent(primitives[-1], 1.0)
        if math.hypot(tangent_end[0] + end_inward[0],
                      tangent_end[1] + end_inward[1]) > TOL_TANGENT:
            violations.append(dict(kind='direct_route_end_heading_mismatch',
                                   route_id=route_id,
                                   detail=f'tangent={tangent_end} '
                                          f'-inward={(-end_inward[0], -end_inward[1])}'))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    # declared contract fields
    if _parse_int(record.get('n_transitions')) not in (0,):
        violations.append(dict(kind='direct_route_n_transitions_not_zero',
                               route_id=route_id,
                               detail=repr(record.get('n_transitions'))))
    if record.get('lifted') is not None and bool(record.get('lifted')):
        violations.append(dict(kind='direct_route_lifted_true', route_id=route_id))
    z_span = record.get('z_span_mm')
    if z_span is None:
        pass
    elif abs(float(z_span)) > TOL_Z_MM:
        violations.append(dict(kind='direct_route_z_span_not_zero',
                               route_id=route_id, detail=repr(z_span)))
    for field in ('start_z_mm', 'end_z_mm'):
        value = record.get(field)
        if value is not None:
            try:
                if abs(float(value) - expected_z) > TOL_Z_MM:
                    violations.append(dict(kind=f'direct_route_{field}_mismatch',
                                           route_id=route_id,
                                           detail=f'{value!r} != {expected_z!r}'))
            except (TypeError, ValueError):
                violations.append(dict(kind=f'direct_route_{field}_invalid',
                                       route_id=route_id, detail=repr(value)))
    target_plane = _parse_int(record.get('target_plane'))
    if target_plane is not None and target_plane != expected_plane_id:
        violations.append(dict(kind='direct_route_target_plane_mismatch',
                               route_id=route_id,
                               detail=f'{target_plane} != {expected_plane_id}'))
    if record.get('needs_transition') is not None and bool(record.get('needs_transition')):
        violations.append(dict(kind='direct_route_needs_transition_true',
                               route_id=route_id))
    if record.get('target_layer') is not None \
            and _parse_int(record.get('target_layer')) != expected_plane_id:
        violations.append(dict(kind='direct_route_target_layer_mismatch',
                               route_id=route_id,
                               detail=f'{record.get("target_layer")!r} != '
                                      f'{expected_plane_id}'))
    declared_sequence = record.get('layer_sequence')
    if isinstance(declared_sequence, list) and declared_sequence:
        try:
            declared = [int(value) for value in declared_sequence]
            accepted = ([expected_plane_id], [INTERFACE_LEGACY_LAYER_ID])
            if declared not in accepted:
                violations.append(dict(
                    kind='direct_route_layer_sequence_mismatch',
                    route_id=route_id,
                    detail=f'{declared} not in {accepted}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='direct_route_layer_sequence_invalid',
                                   route_id=route_id))
    declared_length = record.get('length_mm')
    rebuilt = P.path_length(primitives) if primitives else None
    if declared_length is not None and rebuilt is not None:
        try:
            if abs(float(declared_length) - rebuilt) > TOL_LEN_FIELD_MM:
                violations.append(dict(kind='direct_route_length_mismatch',
                                       route_id=route_id,
                                       detail=f'declared={declared_length!r} '
                                              f'rebuilt={rebuilt:.9g}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='direct_route_length_invalid',
                                   route_id=route_id))


# ===========================================================================
# (c)(d) non-direct routes: structure / continuity / contract
# ===========================================================================
def check_non_direct_route(record, row, model, z_map, interface_ids, endpoints,
                           violations):
    route_id = int(record.get('route_id'))
    plane = str(record.get('plane') or (row or {}).get('plane') or '')
    if plane not in ('z1', 'z2'):
        violations.append(dict(kind='non_direct_unknown_plane', route_id=route_id,
                               detail=repr(record.get('plane'))))
        return
    iface_z = interface_z(plane)
    target_layer = _parse_int((row or {}).get('target_layer')) \
        if row is not None else _parse_int(record.get('target_layer'))
    if target_layer is None:
        target_layer = _parse_int(record.get('target_layer'))
    if target_layer not in z_map:
        violations.append(dict(kind='non_direct_assigned_plane_missing',
                               route_id=route_id, detail=repr(target_layer)))
        return
    body_z = float(z_map[target_layer])
    parts = record.get('parts')
    if not isinstance(parts, list) or not parts:
        violations.append(dict(kind='route_missing_parts', route_id=route_id))
        return
    kinds = [part.get('kind') if isinstance(part, dict) else None for part in parts]
    if len(parts) != 5 or kinds != ['flat', 'transition', 'flat', 'transition',
                                    'flat']:
        violations.append(dict(kind='non_direct_parts_not_lead_trans_body_trans_lead',
                               route_id=route_id, detail=repr(kinds)))
        if kinds.count('transition') != 2:
            violations.append(dict(kind='non_direct_transition_count_mismatch',
                                   route_id=route_id,
                                   detail=f'{kinds.count("transition")} != 2'))
            return
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            _check_flat_part(route_id, index, part, z_map, interface_ids,
                             violations, plane_label=target_layer)
        elif part.get('kind') == 'transition':
            if index == 0 or index == len(parts) - 1:
                violations.append(dict(kind='transition_not_between_flats',
                                       route_id=route_id, detail=f'part={index}'))
            else:
                _check_transition(route_id, index, parts, violations)
    # first/last flat must be the interface leads of its own interface height
    if kinds and kinds[0] == 'flat':
        first_z = _part_flat_z(parts[0])
        if first_z is None or abs(first_z - iface_z) > TOL_Z_MM:
            violations.append(dict(kind='lead_source_wrong_interface_z',
                                   route_id=route_id,
                                   detail=f'z={first_z!r} expected={iface_z!r}'))
        first_layer = _parse_int(parts[0].get('layer_id'))
        if first_layer not in interface_ids:
            violations.append(dict(kind='lead_source_not_interface_plane',
                                   route_id=route_id,
                                   detail=f'layer_id={first_layer!r}'))
    if kinds and kinds[-1] == 'flat':
        last_z = _part_flat_z(parts[-1])
        if last_z is None or abs(last_z - iface_z) > TOL_Z_MM:
            violations.append(dict(kind='lead_target_wrong_interface_z',
                                   route_id=route_id,
                                   detail=f'z={last_z!r} expected={iface_z!r}'))
        last_layer = _parse_int(parts[-1].get('layer_id'))
        if last_layer not in interface_ids:
            violations.append(dict(kind='lead_target_not_interface_plane',
                                   route_id=route_id,
                                   detail=f'layer_id={last_layer!r}'))
    # body flat: exactly the assigned plane / z
    if len(parts) == 5 and kinds[2] == 'flat':
        body_part = parts[2]
        body_layer = _parse_int(body_part.get('layer_id'))
        body_part_z = _part_flat_z(body_part)
        if body_layer != target_layer:
            violations.append(dict(kind='body_layer_mismatch_assignment',
                                   route_id=route_id,
                                   detail=f'body={body_layer!r} '
                                          f'assigned={target_layer}'))
        if body_part_z is None or abs(body_part_z - body_z) > TOL_Z_MM:
            violations.append(dict(kind='body_z_mismatch_model',
                                   route_id=route_id,
                                   detail=f'body_z={body_part_z!r} '
                                          f'model_z={body_z!r}'))
    # port poses (source/target) and declared contract fields
    source_id = record.get('source_endpoint') or (row or {}).get('source_endpoint')
    target_id = record.get('target_endpoint') or (row or {}).get('target_endpoint')
    if source_id in endpoints and kinds and kinds[0] == 'flat':
        source = endpoints[source_id]
        start_xy = tuple(float(v) for v in source['routing_xy'])
        start_inward = tuple(float(v) for v in source['inward'])
        primitives = parts[0].get('primitives') or []
        start = _finite_xy(primitives[0].get('p0')) if primitives else None
        if start is None or math.dist(start, start_xy) > TOL_POS_MM:
            violations.append(dict(kind='route_start_not_at_source_port',
                                   route_id=route_id,
                                   detail=f'start={start} port={start_xy}'))
        if abs(float(source['z_mm']) - iface_z) > TOL_Z_MM:
            violations.append(dict(kind='source_port_height_not_interface',
                                   route_id=route_id,
                                   detail=f'port_z={source["z_mm"]!r} '
                                          f'interface={iface_z!r}'))
        try:
            tangent = _prim_tangent(primitives[0], 0.0)
            if math.hypot(tangent[0] - start_inward[0],
                          tangent[1] - start_inward[1]) > TOL_TANGENT:
                violations.append(dict(kind='route_start_tangent_mismatch',
                                       route_id=route_id,
                                       detail=f'tangent={tangent} '
                                              f'inward={start_inward}'))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    if target_id in endpoints and kinds and kinds[-1] == 'flat':
        target = endpoints[target_id]
        end_xy = tuple(float(v) for v in target['routing_xy'])
        end_inward = tuple(float(v) for v in target['inward'])
        primitives = parts[-1].get('primitives') or []
        end = _finite_xy(primitives[-1].get('p1')) if primitives else None
        if end is None or math.dist(end, end_xy) > TOL_POS_MM:
            violations.append(dict(kind='route_end_not_at_target_port',
                                   route_id=route_id,
                                   detail=f'end={end} port={end_xy}'))
        try:
            tangent = _prim_tangent(primitives[-1], 1.0)
            if math.hypot(tangent[0] + end_inward[0],
                          tangent[1] + end_inward[1]) > TOL_TANGENT:
                violations.append(dict(kind='route_end_tangent_mismatch',
                                       route_id=route_id,
                                       detail=f'tangent={tangent} '
                                              f'-inward={(-end_inward[0], -end_inward[1])}'))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    # declared contract fields
    n_transitions = _parse_int(record.get('n_transitions'))
    if n_transitions is not None and n_transitions != 2:
        violations.append(dict(kind='non_direct_n_transitions_not_2',
                               route_id=route_id, detail=repr(n_transitions)))
    if record.get('lifted') is not None and not bool(record.get('lifted')):
        violations.append(dict(kind='non_direct_lifted_false', route_id=route_id))
    for field in ('start_z_mm', 'end_z_mm'):
        value = record.get(field)
        if value is not None:
            try:
                if abs(float(value) - iface_z) > TOL_Z_MM:
                    violations.append(dict(kind=f'{field}_mismatch',
                                           route_id=route_id,
                                           detail=f'{value!r} != {iface_z!r}'))
            except (TypeError, ValueError):
                violations.append(dict(kind=f'{field}_invalid', route_id=route_id))
    z_span = record.get('z_span_mm')
    expected_span = abs(body_z - iface_z)
    if z_span is not None:
        try:
            if abs(float(z_span) - expected_span) > TOL_Z_MM:
                violations.append(dict(kind='z_span_mismatch', route_id=route_id,
                                       detail=f'{z_span!r} != {expected_span!r}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='z_span_invalid', route_id=route_id))
    target_plane = _parse_int(record.get('target_plane'))
    if target_plane is not None and target_plane != target_layer:
        violations.append(dict(kind='target_plane_mismatch', route_id=route_id,
                               detail=f'{target_plane} != {target_layer}'))
    if record.get('target_layer') is not None \
            and _parse_int(record.get('target_layer')) != target_layer:
        violations.append(dict(kind='target_layer_mismatch', route_id=route_id))
    if record.get('target_z_mm') is not None:
        try:
            if abs(float(record.get('target_z_mm')) - body_z) > TOL_Z_MM:
                violations.append(dict(kind='target_z_mismatch_model',
                                       route_id=route_id))
        except (TypeError, ValueError):
            violations.append(dict(kind='target_z_invalid', route_id=route_id))
    if record.get('needs_transition') is not None \
            and not bool(record.get('needs_transition')):
        violations.append(dict(kind='non_direct_needs_transition_false',
                               route_id=route_id))
    declared_sequence = record.get('layer_sequence')
    if isinstance(declared_sequence, list) and len(declared_sequence) == 3:
        try:
            declared = [int(value) for value in declared_sequence]

            def _norm(layer_id):
                if layer_id in interface_ids or layer_id in SPEC_INTERFACE_IDS:
                    return 'I'
                return layer_id

            if [_norm(value) for value in declared] != ['I', target_layer, 'I']:
                violations.append(dict(kind='layer_sequence_mismatch',
                                       route_id=route_id,
                                       detail=f'{declared} != [I,{target_layer},I]'))
        except (TypeError, ValueError):
            violations.append(dict(kind='layer_sequence_invalid', route_id=route_id))
    # length / xy_length / layers_used contract
    flat_lengths = []
    transition_lengths = []
    xy_total = 0.0
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            try:
                length = P.path_length(part.get('primitives') or [])
            except (KeyError, TypeError, ValueError):
                length = None
            flat_lengths.append(length)
            if length is not None:
                xy_total += length
        else:
            transition_lengths.append(_parse_float(part.get('length_mm')) or 0.0)
            xy_total += _parse_float(part.get('footprint_mm')) or 0.0
    rebuilt_length = None
    if all(value is not None for value in flat_lengths):
        rebuilt_length = float(sum(flat_lengths) + sum(transition_lengths))
    if record.get('length_mm') is not None and rebuilt_length is not None:
        try:
            if abs(float(record.get('length_mm')) - rebuilt_length) > TOL_LEN_FIELD_MM:
                violations.append(dict(kind='length_mm_mismatch', route_id=route_id,
                                       detail=f'declared={record.get("length_mm")!r} '
                                              f'rebuilt={rebuilt_length:.9g}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='length_mm_invalid', route_id=route_id))
    if record.get('xy_length_mm') is not None:
        try:
            if abs(float(record.get('xy_length_mm')) - xy_total) > TOL_LEN_FIELD_MM:
                violations.append(dict(kind='xy_length_mm_mismatch',
                                       route_id=route_id,
                                       detail=f'declared='
                                              f'{record.get("xy_length_mm")!r} '
                                              f'rebuilt={xy_total:.9g}'))
        except (TypeError, ValueError):
            violations.append(dict(kind='xy_length_mm_invalid', route_id=route_id))
    layers_used = record.get('layers_used')
    if isinstance(layers_used, list):
        try:
            declared_raw = [int(value) for value in layers_used]
        except (TypeError, ValueError):
            declared_raw = None
        rebuilt_raw = [_parse_int(part.get('layer_id')) for part in parts
                       if isinstance(part, dict) and part.get('kind') == 'flat'
                       and _parse_int(part.get('layer_id')) is not None]
        if declared_raw is not None:
            def _norm_layer_set(values):
                normalized = set()
                for value in values:
                    if value in interface_ids or value in SPEC_INTERFACE_IDS:
                        normalized.add('I')
                    else:
                        normalized.add(value)
                return normalized

            declared_set = _norm_layer_set(declared_raw)
            rebuilt_set = _norm_layer_set(rebuilt_raw)
            if declared_set != rebuilt_set:
                violations.append(dict(kind='layers_used_mismatch',
                                       route_id=route_id,
                                       detail=f'{sorted(map(str, declared_set))} != '
                                              f'{sorted(map(str, rebuilt_set))}'))


# ===========================================================================
# (e) R15 radius
# ===========================================================================
def _min_circumradius(points):
    if len(points) < 3:
        return None
    array = np.asarray(points, dtype=float)
    a, b, c = array[:-2], array[1:-1], array[2:]
    ab, ac = b - a, c - a
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


def check_radius(record, violations):
    route_id = int(record.get('route_id'))
    arcs = []
    transitions = []
    details = dict(flat_arc_count=0, flat_arc_radii=[],
                   transition_count=0, transition_declared_radii=[],
                   transition_min_sampled_radius=None,
                   transition_samples_total=0)
    for index, part in enumerate(record.get('parts') or []):
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
                    violations.append(dict(kind='flat_arc_radius_not_r15',
                                           route_id=route_id,
                                           detail=f'part={index} prim={prim_index} '
                                                  f'radius={radius!r}'))
        elif part.get('kind') == 'transition':
            try:
                declared_radius = float(part.get('radius_mm'))
            except (TypeError, ValueError):
                declared_radius = None
                violations.append(dict(kind='transition_radius_missing',
                                       route_id=route_id, detail=f'part={index}'))
            if declared_radius is not None \
                    and abs(declared_radius - R15_MM) > TOL_RADIUS_MM:
                violations.append(dict(kind='transition_declared_radius_not_r15',
                                       route_id=route_id,
                                       detail=f'part={index} '
                                              f'radius_mm={declared_radius!r}'))
            try:
                samples = P.transition_samples(part,
                                               step=TRANSITION_SAMPLE_STEP_MM)
            except (KeyError, TypeError, ValueError) as error:
                violations.append(dict(kind='transition_sampling_failed',
                                       route_id=route_id,
                                       detail=f'part={index} {error!r}'))
                continue
            minimum = _min_circumradius(samples)
            if minimum is not None and minimum < MIN_R15_SAMPLED_MM:
                violations.append(dict(
                    kind='transition_true_3d_radius_below_r15',
                    route_id=route_id,
                    detail=f'part={index} min_sampled_radius={minimum:.9g}'))
            transitions.append(dict(index=index, declared_radius=declared_radius,
                                    min_sampled_radius=minimum,
                                    samples=len(samples)))
    details.update(
        flat_arc_count=len(arcs),
        flat_arc_radii=sorted({round(value, 9) for value in arcs}),
        transition_count=len(transitions),
        transition_declared_radii=sorted(
            {round(item['declared_radius'], 9) for item in transitions
             if item.get('declared_radius') is not None}),
        transition_samples_total=sum(item.get('samples', 0) for item in transitions),
    )
    sampled = [item['min_sampled_radius'] for item in transitions
               if item.get('min_sampled_radius') is not None]
    details['transition_min_sampled_radius'] = min(sampled) if sampled else None
    return details


# ===========================================================================
# (f) glass bounds
# ===========================================================================
def _flat_sample_points(part):
    points = []
    for prim in part.get('primitives') or []:
        if not isinstance(prim, dict):
            continue
        p0 = _finite_xy(prim.get('p0'))
        p1 = _finite_xy(prim.get('p1'))
        if prim.get('kind') == 'line':
            if p0 is not None:
                points.append(p0)
            if p1 is not None:
                points.append(p1)
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
            count = max(2, int(math.ceil(abs(sweep) * radius
                                        / ARC_SAMPLE_STEP_MM)) + 1)
            for angle in np.linspace(start, start + sweep, count).tolist():
                points.append((center[0] + radius * math.cos(angle),
                               center[1] + radius * math.sin(angle)))
    return points


def check_glass(record, violations):
    route_id = int(record.get('route_id'))
    samples = []
    for part in record.get('parts') or []:
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
                for sample in P.transition_samples(part,
                                                  step=GLASS_TRANSITION_STEP_MM):
                    samples.append((float(sample[0]), float(sample[1]),
                                    float(sample[2])))
            except (KeyError, TypeError, ValueError):
                continue
    if not samples:
        return {}
    array = np.asarray(samples, dtype=float)
    xs, ys, zs = array[:, 0], array[:, 1], array[:, 2]
    center_margin = np.minimum(np.minimum(xs, GLASS_XY_MM - xs),
                               np.minimum(ys, GLASS_XY_MM - ys))
    min_center_margin = float(np.min(center_margin))
    min_edge_margin = min_center_margin - WAVEGUIDE_HALF_WIDTH_MM
    if min_center_margin < -TOL_GLASS_MM:
        violations.append(dict(kind='outside_glass_xy', route_id=route_id,
                               detail=f'min_centerline_margin='
                                      f'{min_center_margin:.9g} mm'))
    min_z = float(np.min(zs))
    max_z = float(np.max(zs))
    if min_z < GLASS_Z_MIN_MM - TOL_GLASS_MM or max_z > GLASS_Z_MAX_MM + TOL_GLASS_MM:
        violations.append(dict(kind='outside_glass_z', route_id=route_id,
                               detail=f'z_range=[{min_z:.9g},{max_z:.9g}]'))
    return dict(min_centerline_margin_mm=min_center_margin,
                min_edge_margin_mm=min_edge_margin,
                min_z_mm=min_z, max_z_mm=max_z, samples=len(samples),
                edge_margin_negative=bool(min_edge_margin < 0.0))


# ===========================================================================
# (g) true 3D clearance
# ===========================================================================
def check_true_3d_clearance(routed, stack):
    world = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    violations = []
    by_kind = Counter()
    offending = set()
    checked = added = 0
    for record in routed:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        checked += 1
        try:
            found = world.check_route(record, check_self=True)
        except Exception as error:  # noqa: BLE001 - malformed record is reported
            violations.append(dict(kind='clearance_check_exception',
                                   route_id=route_id,
                                   detail=f'{type(error).__name__}: {error}'))
            by_kind['clearance_check_exception'] += 1
            offending.add(route_id)
            continue
        for item in found:
            kind = str(item.get('kind'))
            by_kind[kind] += 1
            offending.add(route_id)
            other = item.get('other_route')
            entry = dict(kind=kind, route_id=route_id,
                         other_route=int(other) if other is not None else None)
            if item.get('distance_mm') is not None:
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
            world.add_route(record)
            added += 1
        except Exception as error:  # noqa: BLE001
            violations.append(dict(kind='world_add_route_exception',
                                   route_id=route_id,
                                   detail=f'{type(error).__name__}: {error}'))
            by_kind['world_add_route_exception'] += 1
            offending.add(route_id)
    return dict(violations=violations, by_kind=dict(sorted(by_kind.items())),
                offending_route_ids=sorted(offending), checked=checked,
                added=added, world=dict(clearance_mm=MIN_3D_CLEARANCE_MM,
                                        body_plane_count=len(stack.routing_layer_ids)))


def _segments_from_polyline(points):
    if len(points) < 2:
        empty = np.zeros((0, 3))
        return empty, empty
    array = np.asarray(points, dtype=float)
    return array[:-1], array[1:]


def _segment_segment_closest(p1, q1, p2, q2):
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
    return np.sqrt(np.einsum('ij,ij->i', diff, diff)), point_a


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
    flat_a, flat_b, flat_route = [], [], []
    trans_a, trans_b, trans_route = [], [], []
    for record in routed:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        for part in record.get('parts') or []:
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
                        if p0 is not None and p1 is not None \
                                and math.dist(p0, p1) > 1e-12:
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
                        count = max(2, int(math.ceil(abs(sweep) * radius
                                                    / 0.02)) + 1)
                        z = float(part['z_mm'])
                        for angle in np.linspace(start, start + sweep,
                                                 count).tolist():
                            points.append((center[0] + radius * math.cos(angle),
                                           center[1] + radius * math.sin(angle), z))
                if len(points) >= 2:
                    a, b = _segments_from_polyline(points)
                    flat_a.append(a)
                    flat_b.append(b)
                    flat_route.append(np.full(len(a), route_id, dtype=np.int64))
            elif part.get('kind') == 'transition':
                try:
                    samples = P.transition_samples(part, step=TRANSITION_SCAN_STEP_MM)
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


def measure_min_3d_clearance(routed, query_radius_mm=0.20,
                             limit_mm=MIN_3D_CLEARANCE_MM):
    import scipy.spatial as spatial
    started = time.time()
    store = _build_3d_segment_stores(routed)
    flat_a, flat_b, flat_route = store['flat']
    trans_a, trans_b, trans_route = store['transition']
    result = dict(flat_segments=int(len(flat_a)),
                  transition_segments=int(len(trans_a)),
                  query_radius_mm=float(query_radius_mm),
                  transition_vs_flat=dict(violations=0, min_mm=None, pairs=[]),
                  transition_vs_transition=dict(violations=0, min_mm=None,
                                                pairs=[]))
    if len(trans_a) == 0:
        result['min_3d_clearance_mm'] = None
        result['runtime_seconds'] = round(time.time() - started, 2)
        return result
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
            distance, point_a = _segment_segment_closest(
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
            bad = np.flatnonzero(distance < limit_mm - 1e-9)
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
                             distance_mm=_round(distance[index])))
        result['transition_vs_flat']['min_mm'] = (
            _round(minimum) if math.isfinite(minimum) else None)
        result['transition_vs_flat']['min_pair'] = min_pair
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
            distance, point_a = _segment_segment_closest(
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
            bad = np.flatnonzero(distance < limit_mm - 1e-9)
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
                             distance_mm=_round(distance[index])))
        result['transition_vs_transition']['min_mm'] = (
            _round(minimum) if math.isfinite(minimum) else None)
        result['transition_vs_transition']['min_pair'] = min_pair
    measured = [value for value in (result['transition_vs_flat']['min_mm'],
                                    result['transition_vs_transition']['min_mm'])
                if value is not None]
    result['min_3d_clearance_mm'] = min(measured) if measured else None
    result['violation_count'] = (result['transition_vs_flat']['violations']
                                 + result['transition_vs_transition']['violations'])
    plane_gap = MIN_LAYER_PITCH_MM
    result['min_plane_gap_mm'] = plane_gap
    result['min_3d_clearance_lower_bound_mm'] = (
        min(measured + [plane_gap]) if measured else plane_gap)
    result['runtime_seconds'] = round(time.time() - started, 2)
    return result


# ===========================================================================
# (h) per-plane strict D56 audit + crossing statistics
# ===========================================================================
def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * float(fraction)
    lower = int(math.floor(position))
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight)
                 + sorted_values[upper] * weight)


def _crossing_distribution(counter):
    values = sorted(int(value) for value in counter.values())
    if not values:
        return dict(routes=0, max=0, p95=0.0, mean=0.0, median=0.0,
                    routes_with_crossings=0)
    return dict(routes=len(values), max=int(values[-1]),
                p95=round(_percentile(values, 0.95), 6),
                mean=round(sum(values) / float(len(values)), 6),
                median=round(_percentile(values, 0.5), 6),
                routes_with_crossings=sum(1 for value in values if value > 0))


def check_crossings(routed, planes, assignment_by_id, baseline_mode=False):
    """Strict D56 audit per physical routing height (all 21 planes).

    All flat parts are grouped by *physical z*: interface planes therefore
    automatically merge the frozen interface leads, the interface-direct bodies
    and any other flat at z=0.0/0.5 into one audit.  Nothing is skipped.
    """
    started = time.time()
    groups = OrderedDict()
    for record in routed:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            z = _part_flat_z(part)
            if z is None:
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
                        continue
                prims.append(dict(prim))
            if prims:
                key = round(z, 9)
                groups.setdefault(key, {}).setdefault(route_id, []).extend(prims)
    planes_by_z = {}
    for plane in planes.values():
        planes_by_z[round(float(plane['z_mm']), 9)] = plane
    plane_rows = []
    violations = []
    all_route_crossings = Counter()
    totals = dict(crossings=0, crossing_pairs=0, violations=0)
    audited_z = set()
    for z_key in sorted(groups):
        if z_key not in planes_by_z:
            if baseline_mode:
                # baseline has interface lead heights without body planes
                plane = dict(plane_id=None, label=f'interface_lead_z{z_key:+.3f}',
                             z_mm=z_key, kind='interface_lead', interface=None)
            else:
                # a flat at a height that is not one of the 21 model planes
                violations.append(_violation(
                    'crossings', 'flat_at_unknown_height', route_id=None,
                    detail=f'z={z_key:g} not in the 21-height model'))
                plane = dict(plane_id=None, label=f'unknown_z{z_key:+.3f}',
                             z_mm=z_key, kind='unknown', interface=None)
        else:
            plane = planes_by_z[z_key]
        route_prims = groups[z_key]
        prepared = []
        for route_id, prims in sorted(route_prims.items()):
            try:
                prepared.append(validate_fslw.prepare_route(prims,
                                                            route_id=route_id))
            except (ValueError, KeyError, TypeError) as error:
                violations.append(_violation(
                    'crossings', 'prepare_failed', route_id=route_id,
                    detail=f'z={z_key:g} {error}'))
        plane_started = time.time()
        if prepared:
            result = validate_fslw.audit_route_pairs(
                prepared, clearance=D56_CLEARANCE_MM, sagitta=SAGITTA_MM,
                policy='strict')
        else:
            result = dict(crossing_count=0, crossing_pair_count=0,
                          violations=[], crossings=[],
                          min_non_crossing_centerline_mm=None)
        crossing_list = result.get('crossings') or []
        route_crossings = Counter()
        direct_direct = direct_lead = lead_non_direct = 0
        for crossing in crossing_list:
            route_a = crossing.get('route_a')
            route_b = crossing.get('route_b')
            for route_id in (route_a, route_b):
                try:
                    rid = int(route_id)
                except (TypeError, ValueError):
                    continue
                route_crossings[rid] += 1
                all_route_crossings[rid] += 1
            if plane['kind'] == 'interface_body':
                row_a = assignment_by_id.get(int(route_a)
                                             if str(route_a).lstrip('-').isdigit()
                                             else -1) or {}
                row_b = assignment_by_id.get(int(route_b)
                                             if str(route_b).lstrip('-').isdigit()
                                             else -1) or {}
                direct_a = _is_direct_row(row_a)
                direct_b = _is_direct_row(row_b)
                if direct_a and direct_b:
                    direct_direct += 1
                elif direct_a or direct_b:
                    direct_lead += 1
                else:
                    lead_non_direct += 1
        route_ids = sorted(route_prims)
        assigned_count = 0
        direct_routes = 0
        if plane.get('plane_id') is not None:
            for route_id in route_ids:
                row = assignment_by_id.get(route_id) or {}
                if _parse_int(row.get('target_layer')) == int(plane['plane_id']):
                    assigned_count += 1
                if _is_direct_row(row):
                    direct_routes += 1
        plane_row = dict(
            plane_id=plane.get('plane_id'), label=plane.get('label'),
            z_mm=_round(z_key), kind=plane.get('kind'),
            interface=plane.get('interface'),
            routes=len(route_ids), parts=sum(len(items)
                                             for items in route_prims.values()),
            assigned_routes=assigned_count, direct_routes=direct_routes,
            crossings=int(result.get('crossing_count') or 0),
            crossing_pairs=int(result.get('crossing_pair_count') or 0),
            min_non_crossing_centerline_mm=_round(
                result.get('min_non_crossing_centerline_mm')),
            violations=len(result.get('violations') or []),
            route_crossing_distribution=_crossing_distribution(route_crossings),
            crossing_kinds=(dict(sorted(Counter(
                str(item.get('kind')) for item in (result.get('violations') or [])
            ).items())) if result.get('violations') else {}),
            interface_direct_crossings=(dict(
                direct_direct=direct_direct, direct_lead=direct_lead,
                lead_non_direct=lead_non_direct)
                if plane['kind'] == 'interface_body' else None),
            runtime_seconds=round(time.time() - plane_started, 3),
        )
        plane_rows.append(plane_row)
        audited_z.add(z_key)
        totals['crossings'] += plane_row['crossings']
        totals['crossing_pairs'] += plane_row['crossing_pairs']
        totals['violations'] += plane_row['violations']
        for item in (result.get('violations') or [])[:100]:
            violations.append(_violation(
                'crossings', str(item.get('kind')), route_id=item.get('route_a'),
                other_route=item.get('route_b'),
                detail=f'z={z_key:g} distance={item.get("distance_mm")} '
                       f'at ({item.get("x")},{item.get("y")})'))
    # model planes that carry assigned routes but show no flat geometry
    missing_planes = []
    for plane in planes.values():
        if plane['kind'] != 'body':
            continue
        z_key = round(float(plane['z_mm']), 9)
        if z_key in groups:
            continue
        missing_planes.append(plane['plane_id'])
    details = dict(
        planes=plane_rows, totals=totals,
        min_non_crossing_centerline_mm=min(
            (row['min_non_crossing_centerline_mm'] for row in plane_rows
             if row['min_non_crossing_centerline_mm'] is not None),
            default=None),
        per_route_distribution=_crossing_distribution(all_route_crossings),
        audited_heights=len(plane_rows),
        missing_model_planes=missing_planes,
        runtime_seconds=round(time.time() - started, 2),
    )
    return violations, details


# ===========================================================================
# assignment
# ===========================================================================
def _is_direct_row(row):
    if not row:
        return False
    value = row.get('needs_transition')
    if value is not None:
        return str(value).strip().lower() in ('false', '0', 'no', 'direct')
    target_z = _parse_float(row.get('target_z_mm'))
    interface_z_mm = _parse_float(row.get('interface_z_mm'))
    if target_z is not None and interface_z_mm is not None:
        return abs(target_z - interface_z_mm) <= 1e-9
    direction = str(row.get('direction') or '').strip().lower()
    return direction == 'direct'


def check_assignment(assignment_rows, routes, true_routes, planes,
                     baseline_mode=False):
    violations = []
    by_id = {}
    duplicates = []
    invalid_ids = []
    for row in assignment_rows:
        route_id = _parse_int(row.get('route_id'))
        if route_id is None:
            invalid_ids.append(row.get('route_id'))
            continue
        if route_id in by_id:
            duplicates.append(route_id)
        by_id[route_id] = row
    if len(assignment_rows) != 1024:
        violations.append(dict(kind='assignment_row_count_not_1024',
                               detail=f'{len(assignment_rows)}'))
    for route_id in duplicates[:100]:
        violations.append(dict(kind='duplicate_assignment_route_id',
                               route_id=route_id))
    for value in invalid_ids[:20]:
        violations.append(dict(kind='invalid_assignment_route_id',
                               detail=repr(value)))
    missing = sorted(set(true_routes) - set(by_id))
    extra = sorted(set(by_id) - set(true_routes))
    for route_id in missing[:100]:
        violations.append(dict(kind='assignment_row_missing',
                               route_id=route_id))
    for route_id in extra[:100]:
        violations.append(dict(kind='assignment_row_unknown_route_id',
                               route_id=route_id))
    z_map = plane_z_map(planes)
    body_ids = set(body_heights_of(planes))
    interface_map = interface_plane_map(planes)
    plane_counts = Counter()
    plane_counts_direct = Counter()
    manual_counts = Counter()
    direction_counts = Counter()
    needs_transition_counts = Counter()
    for route_id, row in by_id.items():
        true = true_routes.get(route_id)
        plane = str(row.get('plane') or (true or {}).get('plane') or '')
        if true is not None and plane != str(true['plane']):
            violations.append(dict(kind='assignment_plane_mismatch',
                                   route_id=route_id,
                                   detail=f'{plane!r} != {true["plane"]!r}'))
        row_source = str(row.get('source_endpoint') or '').strip()
        row_target = str(row.get('target_endpoint') or '').strip()
        if true is not None and row_source and row_target:
            if (row_source, row_target) != (str(true['source_endpoint']),
                                            str(true['target_endpoint'])):
                violations.append(dict(kind='assignment_port_pair_mismatch',
                                       route_id=route_id))
        target_layer = _parse_int(row.get('target_layer'))
        if target_layer is None:
            target_layer = _parse_int(row.get('physical_layer'))
        if target_layer is None:
            violations.append(dict(kind='assignment_target_layer_missing',
                                   route_id=route_id))
            continue
        if target_layer not in z_map:
            violations.append(dict(kind='assignment_target_plane_unknown',
                                   route_id=route_id,
                                   detail=f'plane={target_layer}'))
            continue
        plane_counts[target_layer] += 1
        target_z = _parse_float(row.get('target_z_mm'))
        if target_z is not None and abs(target_z - z_map[target_layer]) > 1e-9:
            violations.append(dict(kind='assignment_target_z_mismatch',
                                   route_id=route_id,
                                   detail=f'z={target_z!r} '
                                          f'model_z={z_map[target_layer]!r}'))
        interface_z_mm = _parse_float(row.get('interface_z_mm'))
        if interface_z_mm is None:
            interface_z_mm = interface_z(plane) if plane in common.INTERFACE_Z else None
        direct = _is_direct_row(row)
        needs_transition_counts['direct' if direct else 'transition'] += 1
        if direct:
            plane_counts_direct[target_layer] += 1
            if target_layer not in interface_map:
                violations.append(dict(kind='direct_row_target_not_interface_plane',
                                       route_id=route_id,
                                       detail=f'plane={target_layer}'))
            elif interface_z_mm is not None \
                    and abs(z_map[target_layer] - interface_z_mm) > 1e-9:
                violations.append(dict(kind='direct_row_interface_z_mismatch',
                                       route_id=route_id))
        else:
            if target_layer in interface_map:
                violations.append(dict(kind='transition_row_target_interface_plane',
                                       route_id=route_id,
                                       detail=f'plane={target_layer}'))
            if plane in common.INTERFACE_Z and interface_z_mm is not None \
                    and abs(interface_z_mm - interface_z(plane)) > 1e-6:
                violations.append(dict(kind='transition_row_interface_z_mismatch',
                                       route_id=route_id,
                                       detail=f'{interface_z_mm!r} != '
                                              f'{interface_z(plane)!r}'))
        direction = str(row.get('direction') or '').strip().lower()
        if direction:
            direction_counts[direction] += 1
            expected = ('direct' if direct else
                        ('down' if z_map[target_layer] < (interface_z_mm
                                                         if interface_z_mm is not None
                                                         else 0.0) else 'up'))
            if expected == 'direct' and direction != 'direct':
                violations.append(dict(kind='assignment_direction_mismatch',
                                       route_id=route_id,
                                       detail=f'direction={direction!r} expected=direct'))
            elif expected in ('down', 'up') and direction not in (expected,):
                violations.append(dict(kind='assignment_direction_mismatch',
                                       route_id=route_id,
                                       detail=f'direction={direction!r} '
                                              f'expected={expected!r}'))
        manual_group = str(row.get('manual_group') or '').strip()
        if manual_group:
            manual_counts[manual_group] += 1
            expected_plane = SPEC_MANUAL_FIXED.get(manual_group)
            if expected_plane is not None and target_layer != expected_plane:
                violations.append(dict(kind='manual_group_wrong_target_plane',
                                       route_id=route_id,
                                       detail=f'{manual_group} assignment='
                                              f'{target_layer} expected='
                                              f'{expected_plane}'))
        # C4 orbit single target plane
        row_c4 = _parse_int(row.get('c4_group_id'))
        if row_c4 is not None:
            pass
    # C4 orbit integrity: whole *non-manual* orbits are assigned to one plane
    # (manual groups intentionally split an orbit across their fixed planes, as
    # specified; the manual rows are checked separately against SPEC_MANUAL_FIXED)
    row_plane = {}
    row_manual = {}
    for route_id, row in by_id.items():
        row_plane[route_id] = _parse_int(row.get('target_layer',
                                                 row.get('physical_layer')))
        row_manual[route_id] = bool(str(row.get('manual_group') or '').strip())
    orbit_problems = []
    manual_split_orbits = 0
    for group in common.rotation_groups():
        nonmanual_planes = set()
        manual_planes = set()
        for route_id in group['route_ids']:
            route_id = int(route_id)
            if row_manual.get(route_id):
                target = row_plane.get(route_id)
                if target is not None:
                    manual_planes.add(target)
            else:
                target = row_plane.get(route_id)
                if target is not None:
                    nonmanual_planes.add(target)
        if len(manual_planes) > 1:
            manual_split_orbits += 1
        if len(nonmanual_planes) > 1:
            orbit_problems.append(dict(
                group_id=int(group['group_id']),
                plane=group.get('plane'),
                nonmanual_target_planes=sorted(nonmanual_planes)))
            violations.append(dict(kind='c4_orbit_not_single_plane',
                                   detail=f'orbit {group["group_id"]}: '
                                          f'{sorted(nonmanual_planes)}'))
    if not baseline_mode:
        if len(plane_counts) != 21:
            violations.append(dict(kind='assignment_used_planes_not_21',
                                   detail=f'{len(plane_counts)}'))
        for plane_id, expected in SPEC_EXPECTED_ASSIGNED.items():
            actual = plane_counts.get(plane_id, 0)
            if actual != expected:
                violations.append(dict(
                    kind='assigned_plane_count_mismatch',
                    detail=f'plane {plane_id}: expected {expected} '
                           f'actual {actual}'))
        direct_total = sum(plane_counts_direct.values())
        if direct_total != SPEC_DIRECT_TOTAL:
            violations.append(dict(kind='direct_route_count_mismatch',
                                   detail=f'{direct_total} != {SPEC_DIRECT_TOTAL}'))
        for plane_id, expected in SPEC_DIRECT_BY_PLANE.items():
            actual = plane_counts_direct.get(plane_id, 0)
            if actual != expected:
                violations.append(dict(kind='direct_plane_count_mismatch',
                                       detail=f'plane {plane_id}: expected '
                                              f'{expected} actual {actual}'))
        for group, expected in (('Z1-U1', 64), ('Z1-U2', 64), ('Z1-U3', 64),
                                ('Z1-U4', 64), ('Z2-U1', 16), ('Z2-U2', 16),
                                ('Z2-U3', 40), ('Z2-U4', 40)):
            if manual_counts.get(group, 0) != expected:
                violations.append(dict(kind='manual_group_count_mismatch',
                                       detail=f'{group}: expected {expected} '
                                              f'actual {manual_counts.get(group, 0)}'))
        # route records vs assignment
        route_by_id = {}
        for record in routes:
            route_id = _parse_int(record.get('route_id'))
            if route_id is not None:
                route_by_id[route_id] = record
        for route_id, row in by_id.items():
            record = route_by_id.get(route_id)
            if record is None or normalize_status(record) != 'routed':
                continue
            target_layer = _parse_int(row.get('target_layer'))
            if target_layer not in z_map:
                continue
            direct = _is_direct_row(row)
            if direct:
                if int(record.get('n_transitions') or 0) != 0:
                    violations.append(dict(kind='direct_route_has_transitions',
                                           route_id=route_id))
                parts = record.get('parts') or []
                layer = _parse_int(parts[0].get('layer_id')) if parts else None
                if layer != target_layer:
                    violations.append(dict(kind='direct_route_body_layer_mismatch',
                                           route_id=route_id,
                                           detail=f'{layer} != {target_layer}'))
            else:
                counts = Counter(part.get('kind') for part in
                                 (record.get('parts') or [])
                                 if isinstance(part, dict))
                if counts.get('transition', 0) != 2:
                    violations.append(dict(kind='non_direct_transition_count_not_2',
                                           route_id=route_id,
                                           detail=f'{counts.get("transition", 0)}'))
                body = [part for part in (record.get('parts') or [])
                        if isinstance(part, dict) and part.get('kind') == 'flat'
                        and _parse_int(part.get('layer_id')) == target_layer]
                if not body:
                    violations.append(dict(kind='non_direct_body_not_on_assigned_plane',
                                           route_id=route_id))
    else:
        for plane_id in plane_counts:
            if plane_id not in z_map:
                violations.append(dict(kind='baseline_assignment_unknown_plane',
                                       detail=f'plane={plane_id}'))
        for group, expected in (('Z1-U1', 64), ('Z1-U2', 64), ('Z1-U3', 64),
                                ('Z1-U4', 64), ('Z2-U1', 16), ('Z2-U2', 16),
                                ('Z2-U3', 40), ('Z2-U4', 40)):
            if manual_counts.get(group, 0) != expected:
                violations.append(dict(kind='baseline_manual_group_count_mismatch',
                                       detail=f'{group}: '
                                              f'{manual_counts.get(group, 0)}'))
    details = dict(
        flag=('baseline_18_layer' if baseline_mode else '21_height'),
        rows=len(assignment_rows), unique_route_ids=len(by_id),
        assigned_plane_counts={str(key): value
                               for key, value in sorted(plane_counts.items())},
        assigned_direct_counts={str(key): value
                                for key, value in sorted(plane_counts_direct.items())},
        manual_group_counts=dict(sorted(manual_counts.items())),
        direction_counts=dict(sorted(direction_counts.items())),
        needs_transition_counts=dict(sorted(needs_transition_counts.items())),
        c4_orbit_count=len(common.rotation_groups()),
        c4_orbit_nonmanual_violations=len(orbit_problems),
        c4_orbit_manual_split_orbits=manual_split_orbits,
        c4_orbit_problems=orbit_problems[:20],
        min_pitch_mm=plane_pitch_audit(planes)[1],
        distinct_heights=len(z_map),
    )
    return violations, details, by_id


# ===========================================================================
# ports
# ===========================================================================
def check_ports(routed, failed, all_records, true_routes):
    violations = []
    endpoints = common.endpoints()
    ids = []
    for record in all_records:
        ids.append(_parse_int(record.get('route_id')))
    expected_ids = set(true_routes)
    valid_ids = [value for value in ids if value is not None]
    counts = Counter(valid_ids)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    missing = sorted(expected_ids - set(valid_ids))
    extra = sorted(set(valid_ids) - expected_ids)
    for route_id in missing[:100]:
        violations.append(dict(kind='route_id_missing', route_id=route_id))
    for route_id in extra[:100]:
        violations.append(dict(kind='route_id_not_in_true_data',
                               route_id=route_id))
    for route_id in duplicates[:100]:
        violations.append(dict(kind='duplicate_route_id', route_id=route_id))
    plane_counts = Counter()
    port_pairs = {}
    routed_missing_endpoints = []
    for record in all_records:
        route_id = _parse_int(record.get('route_id'))
        if route_id is None:
            continue
        true = true_routes.get(route_id)
        plane = str(record.get('plane') or '')
        if true is not None and plane != str(true['plane']):
            violations.append(dict(kind='route_plane_mismatch', route_id=route_id,
                                   detail=f'{plane!r} != {true["plane"]!r}'))
        plane_counts[plane] += 1
        source = record.get('source_endpoint')
        target = record.get('target_endpoint')
        if source is None or target is None:
            if normalize_status(record) == 'routed':
                routed_missing_endpoints.append(route_id)
            continue
        if normalize_status(record) != 'routed':
            continue
        if true is not None:
            expected = (str(true['source_endpoint']), str(true['target_endpoint']))
            if (str(source), str(target)) != expected:
                violations.append(dict(kind='port_pair_not_true_data',
                                       route_id=route_id,
                                       detail=f'{(source, target)} != {expected}'))
        port_pairs[route_id] = (str(source), str(target))
        for name, endpoint_id in (('source', source), ('target', target)):
            if endpoint_id not in endpoints:
                violations.append(dict(kind=f'{name}_endpoint_not_a_port',
                                       route_id=route_id,
                                       detail=repr(endpoint_id)))
                continue
            endpoint_plane = str(endpoints[endpoint_id].get('plane'))
            if endpoint_plane != plane:
                violations.append(dict(kind=f'{name}_endpoint_plane_mismatch',
                                       route_id=route_id,
                                       detail=f'{endpoint_id} '
                                              f'plane={endpoint_plane!r} '
                                              f'record={plane!r}'))
    for route_id in routed_missing_endpoints[:100]:
        violations.append(dict(kind='routed_record_missing_endpoints',
                               route_id=route_id))
    true_pairs = {int(route['route_id']): (str(route['source_endpoint']),
                                           str(route['target_endpoint']))
                  for route in common.routes()}
    pair_matches = all(true_pairs.get(route_id) == pair
                       for route_id, pair in port_pairs.items())
    details = dict(
        records=len(all_records), routed=len(routed), failed=len(failed),
        unique_route_ids=len(set(valid_ids)),
        duplicate_route_ids=duplicates[:50],
        missing_route_ids=missing[:50], missing_route_id_count=len(missing),
        extra_route_ids=extra[:50],
        planes=dict(sorted(plane_counts.items())),
        port_pairs_checked=len(port_pairs),
        port_pair_set_matches=bool(pair_matches)
        and len(port_pairs) == len(true_pairs),
        routed_missing_endpoints=len(routed_missing_endpoints),
        endpoint_table_size=len(endpoints),
    )
    return violations, details


# ===========================================================================
# (k) consistency tests
# ===========================================================================
def _plane_pitch_verdict(gaps, min_pitch=MIN_LAYER_PITCH_MM):
    bad = [gap for gap in gaps if gap < min_pitch - TOL_PLANE_GAP_MM]
    return dict(legal=not bad, illegal_gaps=[round(gap, 12) for gap in bad])


def run_consistency_tests(planes, stack):
    tests = []

    def add_test(name, expected, actual, detail=None):
        tests.append(dict(name=name, expected=expected, actual=actual,
                          passed=bool(expected == actual), detail=detail))

    body_z = sorted(round(float(plane['z_mm']), 9) for plane in planes.values()
                    if plane['kind'] == 'body')
    low = body_z[0]
    first_gap = body_z[1] - body_z[0]
    primitives = [dict(kind='line', p0=[10.0, 10.0], p1=[20.0, 10.0])]

    def _synthetic_flat(route_id, z_mm, layer_id):
        return dict(route_id=int(route_id), plane='z1',
                    start_z_mm=float(z_mm), end_z_mm=float(z_mm),
                    n_transitions=0, lifted=False,
                    layer_sequence=[int(layer_id)],
                    layer_z_sequence=[float(z_mm)],
                    layers_used=[int(layer_id)],
                    parts=[dict(kind='flat', layer_id=int(layer_id),
                                z_mm=float(z_mm),
                                length_mm=float(P.path_length(primitives)),
                                primitives=primitives)])

    world_50 = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    world_50.add_route(_synthetic_flat(900001, low, 2))
    violations_50 = world_50.check_route(_synthetic_flat(900002,
                                                         low + 0.05,
                                                         body_z[1] and 3),
                                         check_self=True)
    add_test('world_accepts_50um_plane_separation', True, not violations_50,
             detail=f'world.check_route -> {violations_50[:3]}')
    add_test('validator_accepts_50um_plane_separation', True,
             _plane_pitch_verdict([0.05])['legal'])
    world_49 = World(stack, clearance=MIN_3D_CLEARANCE_MM)
    world_49.add_route(_synthetic_flat(900003, low, 2))
    violations_49 = world_49.check_route(_synthetic_flat(900004, low + 0.049, 3),
                                         check_self=True)
    kinds_49 = sorted({str(item.get('kind')) for item in violations_49})
    add_test('world_rejects_49um_plane_separation', True, bool(violations_49),
             detail=f'kinds={kinds_49}')
    add_test('world_49um_is_flat_cross_plane_too_close', True,
             'flat_cross_plane_too_close' in kinds_49)
    add_test('validator_rejects_49um_plane_separation', True,
             not _plane_pitch_verdict([0.049])['legal'])
    real_gaps = [high - low_z for low_z, high in zip(body_z, body_z[1:])]
    add_test('model_min_pitch_is_50um', True,
             all(gap >= MIN_LAYER_PITCH_MM - TOL_PLANE_GAP_MM
                 for gap in real_gaps),
             detail=f'min={min(real_gaps):.12g}')
    # the 21-height stack must build and validate; a 49 um pair must be rejected
    stack_ok = True
    stack_detail = None
    try:
        build_stack('consistency_21h', heights=body_heights_of(planes),
                    note='consistency test')
    except Exception as error:  # noqa: BLE001
        stack_ok = False
        stack_detail = f'{type(error).__name__}: {error}'
    add_test('model_stack_builds_and_validates', True, stack_ok,
             detail=stack_detail)
    bad_heights = dict(body_heights_of(planes))
    if len(bad_heights) >= 2:
        keys = sorted(bad_heights, key=lambda key: bad_heights[key])
        bad_heights[keys[1]] = bad_heights[keys[0]] + 0.049
    bad_ok = True
    bad_detail = None
    try:
        build_stack('consistency_21h_bad', heights=bad_heights,
                    note='consistency test (49 um)')
    except Exception:  # noqa: BLE001 - expected rejection
        bad_ok = False
    add_test('invalid_49um_stack_rejected', True, not bad_ok, detail=bad_detail)
    # same-height D56 separation is still the 0.08 mm 2D rule
    for xy_delta, label in ((0.05, '50um_xy'), (0.049, '49um_xy')):
        prepared = [
            validate_fslw.prepare_route(
                [dict(kind='line', p0=[10.0, 10.0], p1=[20.0, 10.0])],
                route_id='synthetic_a'),
            validate_fslw.prepare_route(
                [dict(kind='line', p0=[10.0, 10.0 + xy_delta],
                      p1=[20.0, 10.0 + xy_delta])], route_id='synthetic_b')]
        audit = validate_fslw.audit_route_pairs(
            prepared, clearance=D56_CLEARANCE_MM, sagitta=SAGITTA_MM,
            policy='strict')
        add_test(f'd56_same_plane_{label}_is_illegal', True,
                 bool(audit['violations']),
                 detail=f'violations={audit["violations"][:2]}')
    # true port table poses
    port_ok = True
    port_detail = None
    try:
        for endpoint_id in ('N01:1:1', 'S01:1:1', 'E01:2:1', 'W16:2:16'):
            _xy, _inward, z = common.endpoint_pose(endpoint_id)
            plane = common.endpoints()[endpoint_id].get('plane')
            if abs(z - interface_z(plane)) > TOL_Z_MM:
                port_ok = False
                port_detail = endpoint_id
    except Exception as error:  # noqa: BLE001
        port_ok = False
        port_detail = f'{type(error).__name__}: {error}'
    add_test('true_port_table_poses_consistent', True, port_ok,
             detail=port_detail)
    payload = dict(schema=CONSISTENCY_SCHEMA, generated_at=_now(),
                   clearance_mm=MIN_3D_CLEARANCE_MM,
                   layer_pitch_mm=MIN_LAYER_PITCH_MM,
                   plane_count=len(planes),
                   tests=tests,
                   all_passed=all(test['passed'] for test in tests))
    return payload


# ===========================================================================
# baseline regression comparison
# ===========================================================================
def regression_check(report):
    expected = BASELINE_REGRESSION
    checks = []

    def add(name, expected_value, actual, ok, detail=None):
        checks.append(dict(name=name, expected=expected_value, actual=actual,
                           passed=bool(ok), detail=detail))

    counts = report['counts']
    add('routed', expected['routed'], counts.get('routed'),
        counts.get('routed') == expected['routed'])
    add('failed', expected['failed'], report.get('failed'),
        report.get('failed') == expected['failed'])
    add('direct_routes', expected['direct_routes'], counts.get('direct_routes'),
        counts.get('direct_routes') == expected['direct_routes'])
    add('transitions', expected['transitions'], counts.get('transitions'),
        counts.get('transitions') == expected['transitions'])
    crossings = counts.get('same_plane_crossings')
    add('same_plane_crossings', expected['crossings_total'], crossings,
        crossings == expected['crossings_total'])
    planes = {_round(row['z_mm'], 6): row
              for row in ((report.get('checks') or {}).get('crossings') or {}
                          ).get('planes') or []}
    for z, expected_count in expected['crossings_by_z'].items():
        row = planes.get(round(float(z), 6)) or {}
        actual = row.get('crossings')
        add(f'crossings_z{z:+.2f}', expected_count, actual,
            actual == expected_count)
    clearance = report.get('min_3d_clearance_mm')
    add('min_3d_clearance_mm', expected['min_3d_clearance_mm'], clearance,
        clearance is not None
        and abs(float(clearance) - expected['min_3d_clearance_mm'])
        <= expected['clearance_tol'])
    length = counts.get('total_length_mm')
    add('total_length_mm', expected['total_length_mm'], length,
        length is not None
        and abs(float(length) - expected['total_length_mm'])
        <= expected['total_length_tol'])
    return dict(expected=expected, checks=checks,
                ok=all(check['passed'] for check in checks))


# ===========================================================================
# orchestration
# ===========================================================================
def _guard_output_path(path, baseline_mode):
    path = Path(path).resolve()
    if baseline_mode:
        base = BASELINE_RUN_DIR.resolve()
        try:
            path.relative_to(base)
        except ValueError:
            return path
        raise RuntimeError(f'refusing to write into the read-only baseline '
                           f'RUN_DIR: {path}')
    return path


def validate(run_dir=None, baseline_model=False, layer_planes_path=None,
             assignment_path=None, out_dir=None, validation_out=None,
             consistency_out=None, crossing_out=None,
             skip_min_clearance=False, skip_crossings=False,
             expect_direct=None, expect_transitions=None,
             regression=False, verbose=True):
    started = time.time()
    run_dir = Path(run_dir) if run_dir is not None else (
        BASELINE_RUN_DIR if baseline_model else RUN_DIR_21H)
    out_dir = Path(out_dir) if out_dir is not None else run_dir
    validation_out = Path(validation_out) if validation_out is not None else \
        out_dir / 'validation.json'
    consistency_out = Path(consistency_out) if consistency_out is not None else \
        out_dir / 'validator_consistency_tests.json'
    crossing_out = Path(crossing_out) if crossing_out is not None else \
        out_dir / 'crossing_stats.json'
    for path in (validation_out, consistency_out, crossing_out):
        _guard_output_path(path, baseline_model)
    if baseline_model and out_dir.resolve() == run_dir.resolve():
        raise RuntimeError('baseline regression must write to a separate '
                           '--out-dir (never into the baseline RUN_DIR)')
    assignment_path = Path(assignment_path) if assignment_path is not None else \
        run_dir / 'assignment_1024.csv'
    if layer_planes_path is not None:
        layer_planes_path = Path(layer_planes_path)
    elif run_dir / 'layer_planes.json' is not None and \
            (run_dir / 'layer_planes.json').exists():
        layer_planes_path = run_dir / 'layer_planes.json'
    routes_path = run_dir / 'routes_l3d.json'

    # -- model ---------------------------------------------------------------
    model_violations = []
    if baseline_model:
        planes = derive_baseline_model()
        model_source = 'derived_from_baseline_18_layer_common.PHYSICAL_LAYERS'
    else:
        planes, model_source = load_layer_planes(layer_planes_path) \
            if layer_planes_path is not None else (None, 'missing')
        if planes is None:
            planes = _spec_model()
            warnings = [dict(kind='layer_planes_file_missing',
                             detail=f'{layer_planes_path} -> SPEC.md model used')]
            model_source = 'SPEC.md fallback (layer_planes.json missing)'
        else:
            warnings = []
    model_check_violations, model_details = check_model(
        planes, model_source, baseline_mode=baseline_model)
    model_violations.extend(model_check_violations)
    if not baseline_model and planes is not None and model_source != 'SPEC.md fallback (layer_planes.json missing)':
        spec_planes = _spec_model()
        if set(planes) != set(spec_planes):
            model_violations.append(dict(kind='layer_planes_id_set_mismatch',
                                         detail=f'{sorted(planes)}'))
    model_details['warnings'] = warnings if not baseline_model else []
    model_details['violations'] = len(model_violations)
    stack = build_model_stack(planes)
    z_map = plane_z_map(planes)
    interface_ids = set(interface_plane_map(planes))

    # -- routes --------------------------------------------------------------
    payload, records = load_payload(routes_path)
    routed, failed = split_records(records)
    true_routes = build_true_routes()
    endpoints = common.endpoints()
    assignment_rows = _read_csv(assignment_path)

    root_violations = list(model_violations)
    assignment_violations, assignment_details, assignment_by_id = check_assignment(
        assignment_rows, records, true_routes, planes,
        baseline_mode=baseline_model)

    # -- structure / direct / non-direct ------------------------------------
    structure_violations = []
    direct_count = 0
    direct_by_plane = Counter()
    direct_ids = []
    transition_count = 0
    transition_length = 0.0
    total_length = 0.0
    max_route_length = 0.0
    all_interface_ids = _interface_layer_ids(interface_ids)
    for record in routed:
        route_id = _parse_int(record.get('route_id'))
        if route_id is None:
            continue
        row = assignment_by_id.get(route_id) or {}
        direct = _is_direct_row(row) if row else int(record.get('n_transitions') or 0) == 0
        if direct:
            direct_count += 1
            direct_ids.append(route_id)
            route_plane = str(record.get('plane') or row.get('plane') or '')
            if route_plane in ('z1', 'z2'):
                direct_by_plane[interface_plane_id(route_plane)] += 1
            check_direct_route(record, row, planes, endpoints, structure_violations)
        else:
            check_non_direct_route(record, row, planes, z_map, all_interface_ids,
                                   endpoints, structure_violations)
        try:
            raw = World.check_structure(record)
        except Exception as error:  # noqa: BLE001
            raw = [f'structure_check_exception:{type(error).__name__}:{error}']
        if raw:
            structure_violations.append(dict(
                kind='world_check_structure_flagged', route_id=route_id,
                detail=repr(raw[:4])))
        for part in record.get('parts') or []:
            if not isinstance(part, dict):
                continue
            if part.get('kind') == 'transition':
                transition_count += 1
                try:
                    transition_length += float(part.get('length_mm') or 0.0)
                except (TypeError, ValueError):
                    pass
        try:
            route_length = float(record.get('length_mm') or 0.0)
        except (TypeError, ValueError):
            route_length = 0.0
        total_length += route_length
        max_route_length = max(max_route_length, route_length)
    structure_details = dict(
        routed_checked=len(routed),
        direct_routes=direct_count,
        direct_by_interface_plane={str(key): value
                                   for key, value in sorted(direct_by_plane.items())},
        direct_route_ids=direct_ids[:200],
        non_direct_routes=len(routed) - direct_count,
        violations=len(structure_violations),
        offending_route_ids=sorted({item['route_id'] for item in structure_violations
                                    if item.get('route_id') is not None}),
        violation_kinds=dict(sorted(Counter(
            item['kind'] for item in structure_violations).items())),
    )

    # -- radius --------------------------------------------------------------
    radius_violations = []
    radius_details = dict(routes_checked=0, flat_arc_count=0,
                          flat_arc_radii=[], transition_count=0,
                          transition_declared_radii=[],
                          transition_min_sampled_radius=None,
                          transition_samples_total=0)
    for record in routed:
        details = check_radius(record, radius_violations)
        radius_details['routes_checked'] += 1
        radius_details['flat_arc_count'] += details['flat_arc_count']
        radius_details['flat_arc_radii'].extend(details['flat_arc_radii'])
        radius_details['transition_count'] += details['transition_count']
        radius_details['transition_declared_radii'].extend(
            details['transition_declared_radii'])
        radius_details['transition_samples_total'] += details['transition_samples_total']
        minimum = details['transition_min_sampled_radius']
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

    # -- glass ---------------------------------------------------------------
    glass_violations = []
    glass_details = dict(routes_checked=0, samples=0,
                         min_centerline_margin_mm=None,
                         min_edge_margin_mm=None,
                         edge_margin_negative_route_count=0,
                         min_z_mm=None, max_z_mm=None)
    edge_negative = set()
    for record in routed:
        details = check_glass(record, glass_violations)
        glass_details['routes_checked'] += 1
        if not details:
            continue
        glass_details['samples'] += details.get('samples') or 0
        margin = details.get('min_centerline_margin_mm')
        if margin is not None and (glass_details['min_centerline_margin_mm'] is None
                                   or margin < glass_details['min_centerline_margin_mm']):
            glass_details['min_centerline_margin_mm'] = margin
        edge_margin = details.get('min_edge_margin_mm')
        if edge_margin is not None and (glass_details['min_edge_margin_mm'] is None
                                        or edge_margin < glass_details['min_edge_margin_mm']):
            glass_details['min_edge_margin_mm'] = edge_margin
        if details.get('edge_margin_negative'):
            route_id = _parse_int(record.get('route_id'))
            if route_id is not None:
                edge_negative.add(route_id)
        for key in ('min_z_mm', 'max_z_mm'):
            value = details.get(key)
            if value is None:
                continue
            if glass_details[key] is None:
                glass_details[key] = value
            elif key == 'min_z_mm':
                glass_details[key] = min(glass_details[key], value)
            else:
                glass_details[key] = max(glass_details[key], value)
    glass_details['min_centerline_margin_mm'] = _round(
        glass_details['min_centerline_margin_mm'])
    glass_details['min_edge_margin_mm'] = _round(glass_details['min_edge_margin_mm'])
    glass_details['edge_margin_negative_route_count'] = len(edge_negative)
    glass_details['bounds'] = dict(x=[0.0, GLASS_XY_MM], y=[0.0, GLASS_XY_MM],
                                   z=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM])
    glass_details['waveguide_half_width_mm'] = WAVEGUIDE_HALF_WIDTH_MM
    glass_details['violations'] = len(glass_violations)
    glass_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in glass_violations
         if item.get('route_id') is not None})
    glass_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in glass_violations).items()))

    # -- true 3D clearance ---------------------------------------------------
    clearance_details = check_true_3d_clearance(routed, stack)
    if skip_min_clearance:
        min_scan = dict(skipped=True, min_3d_clearance_mm=None)
    else:
        min_scan = measure_min_3d_clearance(routed)
    clearance_block = dict(
        method='fresh four_side_1024.l3d.world.World(model stack from '
               'layer_planes body heights, clearance=0.05); check_route(route, '
               'check_self=True) in route-id order, then add_route',
        clearance_mm=MIN_3D_CLEARANCE_MM,
        body_plane_count=len(stack.routing_layer_ids),
        routes_checked=clearance_details['checked'],
        routes_added=clearance_details['added'],
        violations=len(clearance_details['violations']),
        violation_kinds=clearance_details['by_kind'],
        offending_route_ids=clearance_details['offending_route_ids'],
        offending_route_count=len(clearance_details['offending_route_ids']),
        world=clearance_details['world'],
        min_clearance_scan=min_scan,
        min_3d_clearance_mm=min_scan.get('min_3d_clearance_mm'),
        min_3d_clearance_lower_bound_mm=min_scan.get(
            'min_3d_clearance_lower_bound_mm'),
    )

    # -- ports ---------------------------------------------------------------
    port_violations, port_details = check_ports(routed, failed, records,
                                                true_routes)
    port_details['violations'] = len(port_violations)
    port_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in port_violations).items()))
    port_details['offending_route_ids'] = sorted(
        {item['route_id'] for item in port_violations
         if item.get('route_id') is not None})

    # -- crossings (h) -------------------------------------------------------
    if skip_crossings:
        crossing_violations = []
        crossing_details = dict(skipped=True)
    else:
        crossing_violations, crossing_details = check_crossings(
            routed, planes, assignment_by_id, baseline_mode=baseline_model)
    crossing_details['violations'] = len(crossing_violations)
    crossing_details['violation_kinds'] = dict(sorted(Counter(
        item['kind'] for item in crossing_violations).items()))

    # -- consistency ---------------------------------------------------------
    consistency = run_consistency_tests(planes, stack)
    _write_json(consistency_out, consistency)

    # -- contract checks -----------------------------------------------------
    contract_violations = []
    for item in assignment_violations:
        contract_violations.append(_violation('assignment', item.get('kind'),
                                              item.get('route_id'),
                                              detail=item.get('detail')))
    for item in model_violations:
        contract_violations.append(_violation('model', item.get('kind'),
                                              detail=item.get('detail')))
    non_direct_routed = len(routed) - direct_count
    if transition_count != 2 * non_direct_routed:
        contract_violations.append(_violation(
            'totals', 'transition_count_not_2_per_non_direct_route',
            detail=f'{transition_count} != 2*{non_direct_routed}'))
    expected_direct_value = (SPEC_DIRECT_TOTAL if not baseline_model else 0) \
        if expect_direct is None else int(expect_direct)
    if len(failed) > 0 and expect_direct is None:
        # partial results are reported honestly: the direct count contract only
        # requires every routed direct-assigned route to actually be direct
        expected_direct_value = sum(
            1 for record in routed
            if _is_direct_row(assignment_by_id.get(
                _parse_int(record.get('route_id')), {})))
    if direct_count != expected_direct_value:
        contract_violations.append(_violation(
            'totals', 'direct_route_count_mismatch',
            detail=f'{direct_count} != {expected_direct_value}'))
    expected_transition_value = (None if expect_transitions is None else
                                 int(expect_transitions))
    if expected_transition_value is None and len(failed) == 0:
        expected_transition_value = 2 * (1024 - expected_direct_value)
    if expected_transition_value is not None \
            and transition_count != expected_transition_value:
        contract_violations.append(_violation(
            'totals', 'transition_count_mismatch',
            detail=f'{transition_count} != {expected_transition_value}'))
    if not baseline_model:
        # direct routes must exist on both interface planes (52 + 48)
        if len(failed) == 0:
            for plane_id, expected in SPEC_DIRECT_BY_PLANE.items():
                actual = direct_by_plane.get(plane_id, 0)
                if actual != expected:
                    contract_violations.append(_violation(
                        'totals', 'direct_plane_count_mismatch',
                        detail=f'plane {plane_id}: {actual} != {expected}'))
        # crossings must be audited on every one of the 21 planes, interface
        # planes included with their leads + direct bodies merged (never skipped)
        if not skip_crossings:
            audited = crossing_details.get('audited_heights')
            if audited != 21:
                contract_violations.append(_violation(
                    'crossings', 'planes_audited_count_not_21',
                    detail=f'audited={audited}'))
            if crossing_details.get('missing_model_planes'):
                contract_violations.append(_violation(
                    'crossings', 'model_planes_without_flat_geometry',
                    detail=f'{crossing_details.get("missing_model_planes")}'))
            interface_rows = [row for row
                              in (crossing_details.get('planes') or [])
                              if row.get('kind') == 'interface_body']
            if len(interface_rows) != 2:
                contract_violations.append(_violation(
                    'crossings', 'interface_planes_not_audited',
                    detail=f'{len(interface_rows)} interface plane audits'))
            else:
                direct_in_audits = sum(int(row.get('direct_routes') or 0)
                                       for row in interface_rows)
                if direct_in_audits != direct_count:
                    contract_violations.append(_violation(
                        'crossings', 'interface_direct_bodies_not_merged_in_audit',
                        detail=f'audit direct={direct_in_audits} '
                               f'routed direct={direct_count}'))
        if model_details.get('plane_count') != 21:
            contract_violations.append(_violation(
                'model', 'model_plane_count_not_21',
                detail=f'{model_details.get("plane_count")}'))

    # -- failures ------------------------------------------------------------
    failure_records = [dict(route_id=_parse_int(record.get('route_id')),
                            plane=str(record.get('plane') or ''),
                            reason=failure_reason(record),
                            status=record.get('status'))
                       for record in failed]
    failed_details = dict(count=len(failed), records=failure_records[:400],
                          route_ids=[record['route_id'] for record in failure_records
                                     if record.get('route_id') is not None],
                          by_reason=dict(sorted(Counter(
                              record['reason'] for record in failure_records).items())),
                          by_plane=dict(sorted(Counter(
                              record['plane'] for record in failure_records).items())))

    # -- assemble report -----------------------------------------------------
    cross_totals = (crossing_details.get('totals') or {})
    counts = dict(
        records=len(records), routed=len(routed), failed=len(failed),
        routed_by_plane=dict(sorted(Counter(str(record.get('plane'))
                                            for record in routed).items())),
        direct_routes=direct_count,
        direct_by_interface_plane={str(key): value
                                   for key, value in sorted(direct_by_plane.items())},
        non_direct_routes=non_direct_routed,
        transitions=transition_count,
        transition_total_length_mm=_round(transition_length),
        total_length_mm=_round(total_length),
        max_route_length_mm=_round(max_route_length),
        flat_arc_count=radius_details['flat_arc_count'],
        min_flat_arc_radius_mm=radius_details['min_flat_arc_radius'],
        min_transition_sampled_radius_mm=radius_details[
            'transition_min_sampled_radius'],
        min_3d_clearance_mm=clearance_block.get('min_3d_clearance_mm'),
        min_3d_clearance_lower_bound_mm=clearance_block.get(
            'min_3d_clearance_lower_bound_mm'),
        same_plane_crossings=cross_totals.get('crossings'),
        same_plane_crossing_pairs=cross_totals.get('crossing_pairs'),
        same_plane_crossing_violations=cross_totals.get('violations'),
        min_non_crossing_centerline_mm=crossing_details.get(
            'min_non_crossing_centerline_mm'),
        per_route_crossing_distribution=crossing_details.get(
            'per_route_distribution'),
        planes_audited=crossing_details.get('audited_heights'),
        min_centerline_glass_margin_mm=glass_details.get('min_centerline_margin_mm'),
        min_edge_glass_margin_mm=glass_details.get('min_edge_margin_mm'),
        violation_total=0,
    )
    geometry_checks = ('structure', 'radius', 'glass', 'clearance', 'ports',
                       'crossings')
    contract_checks = ('model', 'assignment', 'totals')
    check_names = ('model', 'structure', 'radius', 'glass', 'clearance',
                   'ports', 'assignment', 'crossings', 'totals', 'consistency')
    violations = []
    for item in structure_violations:
        violations.append(_violation('structure', item.get('kind'),
                                     item.get('route_id'),
                                     detail=item.get('detail')))
    for item in radius_violations:
        violations.append(_violation('radius', item.get('kind'),
                                     item.get('route_id'),
                                     detail=item.get('detail')))
    for item in glass_violations:
        violations.append(_violation('glass', item.get('kind'),
                                     item.get('route_id'),
                                     detail=item.get('detail')))
    for item in clearance_details['violations']:
        violations.append(_violation('clearance', item.get('kind'),
                                     item.get('route_id'),
                                     other_route=item.get('other_route'),
                                     detail=item.get('detail')))
    for item in (min_scan.get('transition_vs_flat') or {}).get('pairs', []):
        if clearance_details['violations']:
            continue
        violations.append(_violation('clearance', 'transition_vs_flat',
                                     item.get('route_id'),
                                     other_route=item.get('other_route'),
                                     detail=f'independent_min_scan '
                                            f'distance={item.get("distance_mm")}'))
    for item in port_violations:
        violations.append(_violation('ports', item.get('kind'),
                                     item.get('route_id'),
                                     detail=item.get('detail')))
    for item in crossing_violations:
        violations.append(_violation('crossings', item.get('kind'),
                                     item.get('route_id'),
                                     other_route=item.get('other_route'),
                                     detail=item.get('detail')))
    violations.extend(contract_violations)
    for item in violations:
        item.setdefault('check', 'other')
    counts['violation_total'] = len(violations)
    geometry_pass = not any(item['check'] in geometry_checks
                            for item in violations)
    contract_pass = not any(item['check'] in contract_checks
                            for item in violations)
    validator_consistency_passed = bool(consistency['all_passed'])
    validation_pass = bool(geometry_pass and contract_pass
                           and validator_consistency_passed)
    report = OrderedDict([
        ('schema', VALIDATOR_SCHEMA),
        ('validator', 'four_side_1024.fanout1024.reheight21.validate21'),
        ('validated_at', _now()),
        ('run_dir', str(run_dir)),
        ('routes_file', str(routes_path)),
        ('routes_file_sha256', _sha256(routes_path)),
        ('assignment_file', str(assignment_path)),
        ('layer_planes_file', str(layer_planes_path)
         if layer_planes_path is not None else None),
        ('baseline_model', bool(baseline_model)),
        ('model', model_details),
        ('route_count', len(records)),
        ('route_count_declared', payload.get('route_count')),
        ('routed', len(routed)),
        ('failed', len(failed)),
        ('checks', OrderedDict([
            ('structure', structure_details),
            ('radius', radius_details),
            ('glass', glass_details),
            ('clearance', clearance_block),
            ('ports', port_details),
            ('assignment', assignment_details),
            ('crossings', crossing_details),
            ('failures', failed_details),
            ('consistency', dict(
                tests=consistency['tests'],
                all_passed=consistency['all_passed'],
                test_count=len(consistency['tests']),
                failed_tests=[test['name'] for test in consistency['tests']
                              if not test['passed']])),
            ('totals', dict(
                transitions=transition_count,
                transition_total_length_mm=_round(transition_length),
                total_length_mm=_round(total_length),
                max_route_length_mm=_round(max_route_length),
                direct_routes=direct_count,
                non_direct_routes=non_direct_routed,
                expected_transitions=(2 * (1024 - expected_direct_value)
                                      if not baseline_model else 2048),
            )),
        ])),
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
        ('runtime_seconds', 0.0),
    ])
    regression_result = None
    if regression:
        regression_result = regression_check(report)
        report['baseline_regression'] = regression_result
        if not regression_result['ok']:
            report['exit_code'] = 2
    report['runtime_seconds'] = round(time.time() - started, 2)

    # -- crossing_stats.json -------------------------------------------------
    crossing_stats = OrderedDict([
        ('schema', CROSSING_SCHEMA),
        ('generated_at', _now()),
        ('run_dir', str(run_dir)),
        ('routes_file', str(routes_path)),
        ('routes_file_sha256', report['routes_file_sha256']),
        ('model', dict(
            source=model_details.get('source'),
            baseline_model=bool(baseline_model),
            plane_count=model_details.get('plane_count'),
            min_pitch_mm=model_details.get('min_pitch_mm'),
            planes=model_details.get('sorted_planes'))),
        ('rule', dict(d56_centreline_mm=D56_CLEARANCE_MM,
                      width_mm=common.WIDTH_MM,
                      edge_gap_mm=common.EDGE_GAP_MM,
                      policy='strict D56 with legal transverse crossings',
                      note='crossing counts are geometric proxies only; '
                           'no optical loss is claimed')),
        ('totals', dict(
            crossings=cross_totals.get('crossings'),
            crossing_pairs=cross_totals.get('crossing_pairs'),
            violations=cross_totals.get('violations'),
            audited_heights=crossing_details.get('audited_heights'),
            planes_with_crossings=sum(
                1 for row in (crossing_details.get('planes') or [])
                if (row.get('crossings') or 0) > 0),
            per_route_distribution=crossing_details.get(
                'per_route_distribution'),
            min_non_crossing_centerline_mm=crossing_details.get(
                'min_non_crossing_centerline_mm'))),
        ('planes', crossing_details.get('planes') or []),
        ('interface_direct', dict(
            planes=[row for row in (crossing_details.get('planes') or [])
                    if row.get('kind') == 'interface_body'],
            note='interface planes merge frozen leads + interface-direct bodies '
                 'in one strict D56 audit; direct/direct, direct/lead and '
                 'lead/non-direct crossing counts are reported per plane')),
        ('violations', crossing_violations[:200]),
        ('geometry', dict(
            min_3d_clearance_mm=clearance_block.get('min_3d_clearance_mm'),
            min_flat_arc_radius_mm=radius_details['min_flat_arc_radius'],
            min_transition_sampled_radius_mm=radius_details[
                'transition_min_sampled_radius'],
            total_length_mm=counts.get('total_length_mm'),
            max_route_length_mm=counts.get('max_route_length_mm'),
            transition_total_length_mm=counts.get('transition_total_length_mm'),
            transitions=counts.get('transitions'))),
    ])
    _write_json(validation_out, report)
    _write_json(crossing_out, crossing_stats)
    if verbose:
        print(_summary_text(report, validation_out, consistency_out, crossing_out))
    return report, validation_out, crossing_stats, consistency


def _summary_text(report, validation_out, consistency_out, crossing_out):
    lines = []
    model = report.get('model') or {}
    lines.append(f"[validate21] run_dir={report['run_dir']} "
                 f"model={'baseline18' if report.get('baseline_model') else '21h'} "
                 f"planes={model.get('plane_count')} "
                 f"min_pitch={model.get('min_pitch_mm')}")
    lines.append(f"  records={report['route_count']} routed={report['routed']} "
                 f"failed={report['failed']} "
                 f"direct={report['counts'].get('direct_routes')} "
                 f"transitions={report['counts'].get('transitions')}")
    for name in ('structure', 'radius', 'glass', 'clearance', 'ports',
                 'assignment', 'crossings'):
        block = report['checks'].get(name) or {}
        lines.append(f"  {name:<11} violations={block.get('violations', 0)}")
    # model/contract violations are folded into the totals/assignment blocks
    lines.append(f"  model_violations={report['model'].get('violations', 0)} "
                 f"contract_violations="
                 f"{len([v for v in report['violations'] if v['check'] in ('model', 'assignment', 'totals')])}")
    crossings = report['checks']['crossings']
    lines.append(f"  crossings_total={crossings.get('totals', {}).get('crossings')} "
                 f"pairs={crossings.get('totals', {}).get('crossing_pairs')} "
                 f"audited_heights={crossings.get('audited_heights')}")
    lines.append(f"  min_3d_clearance={report.get('min_3d_clearance_mm')} mm "
                 f"min_radius={report['checks']['radius'].get('min_flat_arc_radius')} mm")
    consistency = report['checks']['consistency']
    lines.append(f"  consistency_tests={consistency['test_count']} "
                 f"passed={consistency['all_passed']} "
                 f"failed={consistency['failed_tests']}")
    if report.get('baseline_regression') is not None:
        regression = report['baseline_regression']
        lines.append(f"  baseline_regression_ok={regression['ok']} "
                     f"failed={[c['name'] for c in regression['checks'] if not c['passed']]}")
    lines.append(f"  geometry_pass={report['geometry_pass']} "
                 f"contract_pass={report['contract_pass']} "
                 f"validation_pass={report['validation_pass']} "
                 f"violations={report['violation_count']} "
                 f"runtime={report['runtime_seconds']}s")
    lines.append(f"  wrote {validation_out}")
    lines.append(f"  wrote {consistency_out}")
    lines.append(f"  wrote {crossing_out}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Independent validator for the 21-height experiment.')
    parser.add_argument('--run-dir', default=None,
                        help=f'default: {RUN_DIR_21H} (or baseline with '
                             f'--baseline-model)')
    parser.add_argument('--layer-planes', default=None)
    parser.add_argument('--assignment', default=None)
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--validation-out', default=None)
    parser.add_argument('--consistency-out', default=None)
    parser.add_argument('--crossing-out', default=None)
    parser.add_argument('--baseline-model', action='store_true',
                        help='run the 18-layer baseline regression model '
                             '(use --out-dir, never writes the baseline RUN_DIR)')
    parser.add_argument('--regression-expect-baseline', action='store_true',
                        help='compare the computed numbers with the frozen '
                             'baseline regression expectations')
    parser.add_argument('--skip-min-clearance', action='store_true')
    parser.add_argument('--skip-crossings', action='store_true')
    parser.add_argument('--expect-direct', type=int, default=None)
    parser.add_argument('--expect-transitions', type=int, default=None)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    run_dir = args.run_dir
    if run_dir is None:
        run_dir = BASELINE_RUN_DIR if args.baseline_model else RUN_DIR_21H
    out_dir = args.out_dir
    if args.baseline_model and out_dir is None:
        raise SystemExit('--baseline-model requires --out-dir (never write the '
                         'baseline RUN_DIR)')
    report, _v, _c, _consistency = validate(
        run_dir=run_dir, baseline_model=args.baseline_model,
        layer_planes_path=args.layer_planes, assignment_path=args.assignment,
        out_dir=out_dir, validation_out=args.validation_out,
        consistency_out=args.consistency_out, crossing_out=args.crossing_out,
        skip_min_clearance=args.skip_min_clearance,
        skip_crossings=args.skip_crossings, expect_direct=args.expect_direct,
        expect_transitions=args.expect_transitions,
        regression=bool(args.regression_expect_baseline),
        verbose=not args.quiet)
    return int(report['exit_code'])


if __name__ == '__main__':
    sys.exit(main())
