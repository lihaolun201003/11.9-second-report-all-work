# -*- coding: utf-8 -*-
"""Independent validator for the Native 3D multi-height 1024-route experiment.

The Native 3D experiment keeps the *same route record schema* as the frozen
E5 baseline (``NON_C4_CROSSING_OPT_1024/E5_joint_repair_final``) but allows a
route's ``parts`` list to be an arbitrary alternating sequence::

    flat(lead) -> transition(fanout) -> flat(body,z1) -> transition(mid)
    -> flat(body,z2) -> transition(mid) -> flat(body,z1)
    -> transition(fanout) -> flat(lead)

Every flat carries its own physical height (one of the 21 routing heights of
``four_side_1024.fanout1024.reheight21.model``) and every mid-body transition is
exactly the R=15 mm S-curve produced by
``four_side_1024.fsd25d.path3d.make_transition``.

This module is deliberately **independent** of the Lead's Native-3D builder
(``native3d.route_model`` / ``native3d.transition`` / ``native3d.common``):
it re-derives everything from the written ``parts``.  Only frozen leaf helpers
are reused:

* ``reheight21.validate21`` -- model loading/pitch audit, primitive/part leaf
  checks (``_check_primitive_list``, ``_check_flat_part``, ``_check_transition``),
  radius sampling (``check_radius``), glass (``check_glass``), ports
  (``check_ports``), strict same-plane D56/crossings (``check_crossings``),
  true-3D world clearance (``check_true_3d_clearance``) and the independent
  minimum-3D-clearance scan (``measure_min_3d_clearance``);
  ``validate21.check_radius`` was verified to iterate *every* transition of a
  route (it has no single-body assumption), including several mid transitions.
* ``l3d.world.World`` -- true-XYZ collision world (``check_structure``,
  ``check_route(check_self=True)``, ``add_route``).
* ``reheight21.model`` -- the frozen 21 routing heights (plane ids / z).
* ``fsd25d.path3d`` -- primitive geometry (points, tangents, path length).

Checks (each reported with counts + offending route ids)
--------------------------------------------------------
1. coverage / identity against the frozen E5 baseline (1024 routed records,
   identical route ids, endpoints, plane and rows; 512 z1 + 512 z2);
2. structure of the arbitrary alternating part chain (continuity position/z/
   tangent at every junction, fanout transitions at the interface heights,
   port poses, primitive/arc consistency, direct routes);
3. native metadata re-derived from ``parts`` (``native_3d``, ``body_heights``,
   ``n_mid_transitions``, ``mid_transitions``, ``excursions`` part indices,
   ``layer_sequence``, ``layer_z_sequence``, ``layers_used``, ``length_mm``,
   ``xy_length_mm``, primary ``target_layer``); every flat z must be one of the
   21 heights and distinct heights obey the 50 um pitch;
4. R15: every flat arc and every transition radius is exactly 15 mm with the
   sampled true-3D curvature radius >= 15 - 1e-6 mm;
5. glass bounds (reused ``validate21.check_glass`` over all parts);
6. true-3D clearance: fresh ``l3d.world.World(model stack, 0.05)``, all 1024
   routes added in route-id order with ``check_route(check_self=True)`` plus the
   independent minimum-3D-clearance scan (skippable);
7. ports (reused ``validate21.check_ports``);
8. strict same-plane D56/crossing audit grouped by *physical* z over **all**
   flat parts (interface leads included -- reused
   ``validate21.check_crossings``), with total events / pairs / per-plane and
   per-route distributions;
9. the 368 manual-group routes are frozen: ``parts`` / ``length_mm`` / z fields
   must be json-identical to the frozen E5 baseline;
10. E5 regression mode reproduces exactly 1024/1024 routes, 2606 crossings /
    2067 pairs, 0 violations; plus the synthetic consistency suite in
    ``tests_native3d`` (duck-out accepted, 49 um offset / R=14 / 1e-3
    discontinuity / flat overlap rejected).

Public API
----------
``validate_run(run_dir, baseline_dir=None, out_dir=None,
skip_min_clearance=False, log=print, ...) -> dict``
writes ``<out_dir>/validation.json`` and ``<out_dir>/validator_consistency_tests.json``.

CLI::

    python -m four_side_1024.fanout1024.native3d.validate_native3d \
        --run-dir <dir> [--baseline-dir <E5 dir>] [--out-dir <dir>] \
        [--skip-min-clearance] [--regression]

Exit codes: 0 = pass, 1 = violations, 2 = input/regression failure.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from .. import common as C
from ..reheight21 import model as M
from ..reheight21 import validate21 as V21
from ...fsd25d import path3d as P
from ...l3d.world import World

# ===========================================================================
# constants -- frozen experiment definition
# ===========================================================================
VALIDATOR_ID = 'four_side_1024.fanout1024.native3d.validate_native3d'
VALIDATION_SCHEMA = 'native3d_validation_v1'
CONSISTENCY_SCHEMA = 'native3d_consistency_v1'

OUTPUT_ROOT = C.OUTPUT_ROOT
RUN_ROOT = OUTPUT_ROOT / 'NATIVE_3D_CROSSING_OPT_1024'
DEFAULT_BASELINE = OUTPUT_ROOT / 'NON_C4_CROSSING_OPT_1024' / 'E5_joint_repair_final'

R15_MM = 15.0
MIN_3D_CLEARANCE_MM = 0.05
MIN_LAYER_PITCH_MM = 0.05
TOL_POS_MM = 1e-6
TOL_Z_MM = 1e-6
TOL_TANGENT = 1e-6
TOL_RADIUS_MM = 1e-6
TOL_LEN_MM = 1e-5
TOL_MODEL_Z_MM = 1e-9
LEGACY_INTERFACE_LAYER_ID = V21.INTERFACE_LEGACY_LAYER_ID  # 1
INTERFACE_PLANE_BY_NAME = {'z1': 1001, 'z2': 1002}
MAX_VIOLATIONS_JSON = 2000
MAX_OFFENDING_IDS = 500

#: frozen E5 regression expectations (task acceptance authority)
E5_EXPECT = dict(
    routed=1024,
    failed=0,
    direct_routes=98,
    non_direct_routes=926,
    transitions=1852,
    flat_arc_count=1596,
    same_plane_crossings=2606,
    same_plane_crossing_pairs=2067,
    same_plane_crossing_violations=0,
    audited_heights=21,
    manual_routes=368,
    manual_geometry_mismatch_count=0,
    min_3d_clearance_mm=0.068714895,
    min_3d_clearance_tol=1e-6,
    total_length_mm=157565.774342258,
    total_length_tol=1e-3,
    violation_total=0,
)

PAYLOAD_REQUIRED_KEYS = ('routes',)


# ===========================================================================
# small helpers
# ===========================================================================
def _now():
    return datetime.now().isoformat(timespec='seconds')


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(path, payload):
    return V21._write_json(path, payload)


def _sha256(path):
    try:
        return V21._sha256(path)
    except OSError:
        return None


def _round(value, digits=9):
    return V21._round(value, digits)


def _canon(value):
    """Canonical JSON text of a value (used for json-identical comparisons)."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, default=str)


def _resolve(path):
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path).absolute()


def _is_within(path, parent):
    path, parent = _resolve(path), _resolve(parent)
    try:
        return path == parent or parent in path.parents
    except (OSError, ValueError):
        return False


def _path_text(path):
    return None if path is None else str(Path(path))


def _xy(value):
    return V21._finite_xy(value)


def _parse_int(value):
    return V21._parse_int(value)


def _parse_float(value):
    return V21._parse_float(value)


def _kind(part):
    return part.get('kind') if isinstance(part, dict) else None


def _part_flat_z(part):
    return V21._part_flat_z(part)


def _prim_first(part):
    """``((x, y), (tx, ty))`` of the first primitive of a flat part."""
    primitives = part.get('primitives') if isinstance(part, dict) else None
    if not primitives:
        return None, None
    prim = primitives[0]
    if not isinstance(prim, dict):
        return None, None
    point = _xy(prim.get('p0'))
    tangent = None
    try:
        tangent = P.prim_tangent_at(prim, 0.0)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        tangent = None
    return point, tangent


def _prim_last(part):
    """``((x, y), (tx, ty))`` of the last primitive of a flat part."""
    primitives = part.get('primitives') if isinstance(part, dict) else None
    if not primitives:
        return None, None
    prim = primitives[-1]
    if not isinstance(prim, dict):
        return None, None
    point = _xy(prim.get('p1'))
    tangent = None
    try:
        tangent = P.prim_tangent_at(prim, 1.0)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        tangent = None
    return point, tangent


def _tangent_gap(first, second):
    """Euclidean gap of two 2-D direction vectors (``None`` when unknown)."""
    if first is None or second is None:
        return None
    return math.hypot(float(first[0]) - float(second[0]),
                      float(first[1]) - float(second[1]))


def _unit_direction(value):
    direction = _xy(value)
    if direction is None:
        return None
    norm = math.hypot(direction[0], direction[1])
    if norm <= 0.0:
        return None
    return (direction[0] / norm, direction[1] / norm)


def _violation(check, kind, route_id=None, other_route=None, detail=None):
    entry = dict(check=str(check), kind=str(kind))
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


def _adopt(check, items):
    """Adopt violations produced by a reused validate21 leaf helper."""
    adopted = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry['check'] = str(check)
        adopted.append(entry)
    return adopted


def _finalize_check(name, violations, details):
    kinds = Counter(str(item.get('kind')) for item in violations)
    offending = sorted({int(item['route_id']) for item in violations
                        if item.get('route_id') is not None
                        and isinstance(item['route_id'], int)})
    block = dict(check=name)
    block.update(details)
    block['violations'] = len(violations)
    block['violation_kinds'] = dict(sorted(kinds.items()))
    block['offending_route_ids'] = offending[:MAX_OFFENDING_IDS]
    block['offending_route_count'] = len(offending)
    return dict(name=name, violations=violations, details=block)


# ===========================================================================
# frozen 21-height model helpers
# ===========================================================================
def _model_planes():
    """The frozen 21 routing heights as validate21-compatible plane entries."""
    planes = OrderedDict()
    for plane_id, spec in M.planes().items():
        planes[int(plane_id)] = dict(
            plane_id=int(plane_id),
            label=str(spec['label']),
            z_mm=float(spec['z_mm']),
            kind=str(spec['kind']),
            interface=(str(spec['plane']) if spec.get('plane') else None),
        )
    return planes


def _build_model(planes):
    """Derived lookup helpers for the 21 routing heights."""
    z_map = {int(pid): float(plane['z_mm']) for pid, plane in planes.items()}
    z_to_plane = OrderedDict()
    for pid in sorted(z_map, key=lambda key: (z_map[key], key)):
        z_to_plane[round(z_map[pid], 9)] = int(pid)
    interface_ids = {int(pid) for pid, plane in planes.items()
                     if str(plane.get('kind')) == 'interface_body'}
    interface_z = {}
    for name, plane_id in INTERFACE_PLANE_BY_NAME.items():
        if plane_id in z_map:
            interface_z[name] = z_map[plane_id]
    if 'z1' not in interface_z:
        interface_z['z1'] = float(M.Z1_INTERFACE_MM)
    if 'z2' not in interface_z:
        interface_z['z2'] = float(M.Z2_INTERFACE_MM)
    model = dict(planes=planes, z_map=z_map, z_to_plane=z_to_plane,
                 interface_ids=interface_ids, interface_z=interface_z,
                 plane_ids=tuple(sorted(z_map, key=lambda key: (z_map[key], key))))
    model['pitch_rows'], model['min_pitch_mm'] = V21.plane_pitch_audit(planes)
    return model


def _plane_of_z(model, z_mm, tol=TOL_MODEL_Z_MM):
    """Plane id whose frozen physical height is ``z_mm`` (``None`` if none)."""
    try:
        z = float(z_mm)
    except (TypeError, ValueError):
        return None
    key = round(z, 9)
    plane_id = model['z_to_plane'].get(key)
    if plane_id is not None:
        return plane_id
    for pid, plane_z in model['z_map'].items():
        if abs(plane_z - z) <= tol:
            return pid
    return None


def _interface_z(model, plane):
    plane = str(plane or '')
    return model['interface_z'].get(plane)


def _interface_plane_id(model, plane):
    plane = str(plane or '')
    if plane in INTERFACE_PLANE_BY_NAME:
        candidate = INTERFACE_PLANE_BY_NAME[plane]
        if candidate in model['z_map']:
            return candidate
    return None


def _transition_formula(part):
    """Geometry of a native S-curve recomputed with the frozen R=15 mm.

    Returns ``(length_mm, footprint_mm, theta_rad)`` or ``(None, None, None)``.
    The computation is independent of the writer: it only uses the frozen
    radius 15 mm and the declared ``z0``/``z1`` of the transition.
    """
    try:
        z0 = float(part.get('z0'))
        z1 = float(part.get('z1'))
    except (TypeError, ValueError):
        return None, None, None
    dz = abs(z1 - z0)
    if dz <= 0.0:
        return 0.0, 0.0, 0.0
    ratio = 1.0 - dz / (2.0 * R15_MM)
    if ratio <= -1.0:
        return None, None, None
    theta = math.acos(max(-1.0, min(1.0, ratio)))
    return (2.0 * R15_MM * theta, 2.0 * R15_MM * math.sin(theta), theta)


def _flat_chain_length(part):
    try:
        return float(P.path_length(part.get('primitives') or []))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


# ===========================================================================
# part-chain helpers (no builder imports)
# ===========================================================================
def flat_parts(route):
    return [(index, part) for index, part in enumerate(route.get('parts') or [])
            if _kind(part) == 'flat']


def transition_parts(route):
    return [(index, part) for index, part in enumerate(route.get('parts') or [])
            if _kind(part) == 'transition']


def body_flat_indices(route):
    """Indices of the body flats (interface ``lead`` flats excluded).

    Baseline/native convention: a non-direct route starts and ends with a lead
    flat; every flat between them belongs to the body (a native body may own
    several flats on different heights).  A direct route is one flat body.
    """
    flats = flat_parts(route)
    if not flats:
        return []
    if not transition_parts(route):
        return [index for index, _part in flats]
    if len(flats) <= 2:
        return []
    return [index for index, _part in flats[1:-1]]


def part_length(part):
    """Declared length of a part (flat chain length rebuilt from primitives)."""
    if _kind(part) == 'flat':
        rebuilt = _flat_chain_length(part)
        if rebuilt is not None:
            return rebuilt
    try:
        return float(part.get('length_mm') or 0.0)
    except (TypeError, ValueError):
        return None


def recompute_route(route, model):
    """Re-derive every native/derived field of a route from ``parts`` alone."""
    parts = route.get('parts') or []
    trans = transition_parts(route)
    flats = flat_parts(route)
    flat_heights_all = [_part_flat_z(part) for _index, part in flats]
    is_direct = not trans
    body_indices = body_flat_indices(route)
    body_heights = []
    body_planes = []
    for index in body_indices:
        z = _part_flat_z(parts[index])
        body_heights.append(z)
        body_planes.append(_plane_of_z(model, z) if z is not None else None)
    mid_indices = [index for ordinal, (index, _part) in enumerate(trans)
                   if 0 < ordinal < len(trans) - 1]
    mid_entries = []
    for index in mid_indices:
        part = parts[index]
        mid_entries.append(dict(part_index=int(index),
                                from_z=_parse_float(part.get('z0')),
                                to_z=_parse_float(part.get('z1'))))
    # -- excursions: inner transition / flat / inner transition with matching
    #    heights is one up/travel/down layer change (fully re-derived).
    #    Only *inner* (mid) transitions may pair; the fanout transitions that
    #    touch the interface heights are never part of an excursion.
    tagged_mid = [index for index, part in trans
                  if str(part.get('tag') or '') == 'mid']
    candidate_mid = tagged_mid if tagged_mid else list(mid_indices)
    candidate_mid_set = set(candidate_mid)
    excursions = []
    paired = set()
    for index in candidate_mid:
        if index in paired:
            continue
        if index + 1 >= len(parts) or index + 2 >= len(parts):
            continue
        if index + 2 not in candidate_mid_set or index + 2 in paired:
            continue
        up, middle, down = parts[index], parts[index + 1], parts[index + 2]
        if _kind(middle) != 'flat' or _kind(down) != 'transition':
            continue
        up_z0, up_z1 = _parse_float(up.get('z0')), _parse_float(up.get('z1'))
        middle_z = _part_flat_z(middle)
        down_z0, down_z1 = _parse_float(down.get('z0')), _parse_float(down.get('z1'))
        if None in (up_z0, up_z1, middle_z, down_z0, down_z1):
            continue
        if abs(up_z1 - middle_z) > TOL_Z_MM:
            continue
        if abs(down_z0 - middle_z) > TOL_Z_MM:
            continue
        if abs(down_z1 - up_z0) > TOL_Z_MM:
            continue
        if abs(up_z1 - up_z0) <= TOL_Z_MM:
            continue
        excursions.append(dict(up_part_index=int(index),
                               middle_part_index=int(index + 1),
                               down_part_index=int(index + 2),
                               from_z=float(up_z0), to_z=float(up_z1)))
        paired.add(index)
        paired.add(index + 2)
    # -- rebuilt lengths (native S-curves recomputed with the frozen R15)
    flat_lengths = []
    flat_lengths_ok = True
    for _index, part in flats:
        length = _flat_chain_length(part)
        flat_lengths.append(length)
        if length is None:
            flat_lengths_ok = False
    transition_lengths = []
    transition_footprints = []
    transitions_ok = True
    for _index, part in trans:
        length, footprint, _theta = _transition_formula(part)
        if length is None:
            transitions_ok = False
            continue
        transition_lengths.append(length)
        transition_footprints.append(footprint)
    length_mm = None
    xy_length_mm = None
    if flat_lengths_ok and transitions_ok:
        length_mm = float(sum(flat_lengths) + sum(transition_lengths))
        xy_length_mm = float(sum(flat_lengths) + sum(transition_footprints))
    # -- primary body flat = longest body flat (ties are tolerated by plane)
    primary_planes = []
    primary_plane = None
    primary_z = None
    if body_indices:
        lengths = []
        for index in body_indices:
            length = part_length(parts[index])
            lengths.append(float('-inf') if length is None else length)
        longest = max(lengths)
        candidate_indices = [index for index, length in zip(body_indices, lengths)
                             if length >= longest - TOL_LEN_MM]
        primary_set = set()
        for index in candidate_indices:
            plane = _plane_of_z(model, _part_flat_z(parts[index]))
            if plane is not None:
                primary_set.add(int(plane))
        primary_planes = sorted(primary_set)
        first_index = candidate_indices[0]
        primary_plane = _plane_of_z(model, _part_flat_z(parts[first_index]))
        primary_z = _part_flat_z(parts[first_index])
    plane_ids = [pid for pid in body_planes if pid is not None]
    if is_direct:
        expected_layer_sequence = [int(primary_plane)] if primary_plane is not None else None
        expected_layers_used = [int(primary_plane)] if primary_plane is not None else None
        expected_layer_z_sequence = [primary_z]
    else:
        iface_z = _interface_z(model, route.get('plane'))
        expected_layer_sequence = None
        expected_layer_z_sequence = None
        expected_layers_used = None
        if iface_z is not None and None not in plane_ids:
            expected_layer_sequence = ([LEGACY_INTERFACE_LAYER_ID]
                                       + [int(pid) for pid in plane_ids]
                                       + [LEGACY_INTERFACE_LAYER_ID])
            expected_layer_z_sequence = ([float(iface_z)]
                                         + [float(z) for z in body_heights]
                                         + [float(iface_z)])
            expected_layers_used = ([LEGACY_INTERFACE_LAYER_ID]
                                    + sorted({int(pid) for pid in plane_ids}))
    unique_heights = sorted({round(float(z), 9) for z in flat_heights_all
                             if z is not None})
    min_pitch = None
    if len(unique_heights) > 1:
        min_pitch = min(b - a for a, b in zip(unique_heights, unique_heights[1:]))
    return dict(
        parts=len(parts), flats=flats, transitions=trans, is_direct=is_direct,
        body_indices=body_indices, body_heights=body_heights,
        body_planes=[None if pid is None else int(pid) for pid in body_planes],
        plane_ids=[int(pid) for pid in plane_ids],
        mid_indices=mid_indices, mid_entries=mid_entries,
        unpaired_mid=[index for index in mid_indices if index not in paired],
        excursions=excursions,
        primary_planes=primary_planes,
        primary_plane=primary_plane, primary_z=primary_z,
        expected_layer_sequence=expected_layer_sequence,
        expected_layer_z_sequence=expected_layer_z_sequence,
        expected_layers_used=expected_layers_used,
        length_mm=length_mm, xy_length_mm=xy_length_mm,
        unique_heights=unique_heights, min_pitch_mm=min_pitch,
        body_heights_all_known=all(pid is not None for pid in body_planes),
    )


# ===========================================================================
# input loading
# ===========================================================================
def _load_model(run_dir, baseline_dir, log):
    warnings = []
    path = Path(run_dir) / 'layer_planes.json'
    if not path.exists():
        warnings.append(dict(kind='run_layer_planes_missing',
                             detail=str(path)))
        baseline_path = Path(baseline_dir) / 'layer_planes.json'
        if baseline_path.exists():
            path = baseline_path
            warnings.append(dict(kind='baseline_layer_planes_fallback',
                                 detail=str(path)))
        else:
            path = None
    planes, source = (None, 'missing')
    if path is not None:
        planes, source = V21.load_layer_planes(path)
    if planes is None:
        planes = _model_planes()
        source = 'reheight21.model fallback (no layer_planes.json)'
        warnings.append(dict(kind='model_table_fallback', detail=source))
    # the interface side must be present for the reused validate21 helpers
    for plane_id, spec in V21.SPEC_INTERFACE_PLANES.items():
        plane = planes.get(int(plane_id))
        if plane is not None and not plane.get('interface'):
            plane['interface'] = spec['interface']
    model = _build_model(planes)
    model['source'] = source
    model['path'] = _path_text(path)
    model['warnings'] = warnings
    log('[model] source=%s planes=%d body=%d interface=%d min_pitch=%.6f'
        % (source, len(planes),
           sum(1 for plane in planes.values() if plane.get('kind') == 'body'),
           len(model['interface_ids']),
           model['min_pitch_mm'] if model['min_pitch_mm'] is not None else -1.0))
    return model


def _load_assignment(run_dir, baseline_dir, log):
    path = Path(run_dir) / 'assignment_1024.csv'
    source = 'run'
    if not path.exists():
        source = 'baseline'
        path = Path(baseline_dir) / 'assignment_1024.csv'
        log('[assignment] run copy missing -> baseline %s' % path)
    rows = V21._read_csv(path)
    by_id = {}
    for row in rows:
        route_id = _parse_int(row.get('route_id'))
        if route_id is not None:
            by_id[int(route_id)] = row
    log('[assignment] %d rows from %s' % (len(rows), source))
    return rows, by_id, path, source


def _load_routes(path):
    payload, records = V21.load_payload(path)
    routed, failed = V21.split_records(records)
    return payload, records, routed, failed


# ===========================================================================
# check 1: coverage / identity against the frozen E5 baseline
# ===========================================================================
IDENTITY_FIELDS = ('source_endpoint', 'target_endpoint', 'plane',
                   'source_row', 'target_row')


def _identity(value):
    if value is None:
        return None
    return str(value) if isinstance(value, str) else _canon(value)


def check_coverage(payload, records, routed, failed, baseline_records,
                   baseline_assignment_by_id, assignment_by_id):
    violations = []
    baseline_by_id = {}
    for record in baseline_records:
        route_id = _parse_int(record.get('route_id'))
        if route_id is not None:
            baseline_by_id[int(route_id)] = record
    expected_ids = set(baseline_by_id)
    ids = []
    for record in records:
        ids.append(_parse_int(record.get('route_id')))
    valid_ids = [route_id for route_id in ids if route_id is not None]
    counts = Counter(valid_ids)
    duplicates = sorted(route_id for route_id, count in counts.items() if count > 1)
    missing = sorted(expected_ids - set(valid_ids))
    extra = sorted(set(valid_ids) - expected_ids)
    for route_id in missing[:MAX_OFFENDING_IDS]:
        violations.append(_violation('coverage', 'route_id_missing',
                                     route_id=route_id))
    for route_id in extra[:MAX_OFFENDING_IDS]:
        violations.append(_violation('coverage', 'route_id_not_in_baseline',
                                     route_id=route_id))
    for route_id in duplicates[:MAX_OFFENDING_IDS]:
        violations.append(_violation('coverage', 'duplicate_route_id',
                                     route_id=route_id))
    declared_count = _parse_int(payload.get('route_count'))
    if declared_count is not None and declared_count != len(records):
        violations.append(_violation(
            'coverage', 'route_count_declared_mismatch',
            detail='route_count=%s records=%d' % (declared_count, len(records))))
    if len(routed) != len(expected_ids):
        violations.append(_violation(
            'coverage', 'routed_count_not_1024',
            detail='routed=%d expected=%d' % (len(routed), len(expected_ids))))
    if failed:
        for record in failed[:MAX_OFFENDING_IDS]:
            violations.append(_violation(
                'coverage', 'failed_route_present',
                route_id=_parse_int(record.get('route_id')),
                detail=str(V21.failure_reason(record))))
    plane_counts = Counter()
    row_mismatches = 0
    for record in routed:
        route_id = _parse_int(record.get('route_id'))
        if route_id is None:
            continue
        plane_counts[str(record.get('plane') or '')] += 1
        baseline = baseline_by_id.get(route_id)
        if baseline is None:
            continue
        for field in IDENTITY_FIELDS:
            if _identity(record.get(field)) != _identity(baseline.get(field)):
                row_mismatches += 1
                violations.append(_violation(
                    'coverage', 'identity_field_mismatch', route_id=route_id,
                    detail='field=%s run=%r baseline=%r'
                           % (field, record.get(field), baseline.get(field))))
    if plane_counts.get('z1', 0) != 512:
        violations.append(_violation('coverage', 'plane_z1_count_not_512',
                                     detail=str(plane_counts.get('z1', 0))))
    if plane_counts.get('z2', 0) != 512:
        violations.append(_violation('coverage', 'plane_z2_count_not_512',
                                     detail=str(plane_counts.get('z2', 0))))
    # assignment coverage: every route id must be described
    assignment_missing = sorted(expected_ids - set(assignment_by_id))
    for route_id in assignment_missing[:MAX_OFFENDING_IDS]:
        violations.append(_violation('coverage', 'assignment_row_missing',
                                     route_id=route_id))
    assignment_identity = 0
    for route_id, row in assignment_by_id.items():
        baseline_row = (baseline_assignment_by_id or {}).get(int(route_id))
        if baseline_row is None:
            continue
        for field in ('plane', 'source_endpoint', 'target_endpoint',
                      'source_row', 'target_row', 'manual_group'):
            if _identity(row.get(field)) != _identity(baseline_row.get(field)):
                assignment_identity += 1
                violations.append(_violation(
                    'coverage', 'assignment_identity_mismatch', route_id=route_id,
                    detail='field=%s run=%r baseline=%r'
                           % (field, row.get(field), baseline_row.get(field))))
    details = dict(
        records=len(records), routed=len(routed), failed=len(failed),
        baseline_records=len(baseline_records), expected_route_ids=len(expected_ids),
        unique_route_ids=len(set(valid_ids)),
        duplicate_route_ids=duplicates[:MAX_OFFENDING_IDS],
        missing_route_ids=missing[:MAX_OFFENDING_IDS],
        missing_route_id_count=len(missing),
        extra_route_ids=extra[:MAX_OFFENDING_IDS],
        extra_route_id_count=len(extra),
        planes=dict(sorted(plane_counts.items())),
        identity_field_mismatches=row_mismatches,
        assignment_rows=len(assignment_by_id),
        assignment_missing_rows=len(assignment_missing),
        assignment_identity_mismatches=assignment_identity,
    )
    return _finalize_check('coverage', violations, details)


# ===========================================================================
# check 2: structure of the arbitrary alternating flat/transition chain
# ===========================================================================
def _junction_report(route, model):
    """Recompute position / z / tangent continuity of every flat/transition junction."""
    parts = route.get('parts') or []
    junctions = []
    for index in range(len(parts) - 1):
        first, second = parts[index], parts[index + 1]
        if _kind(first) == 'flat' and _kind(second) == 'transition':
            flat_point, flat_tangent = _prim_last(first)
            start = _xy(second.get('start'))
            direction = _unit_direction(second.get('direction'))
            z_flat = _part_flat_z(first)
            z0 = _parse_float(second.get('z0'))
            junction = dict(index=index, kind='flat_to_transition',
                            position_gap_mm=(None if flat_point is None
                                             or start is None
                                             else math.dist(flat_point, start)),
                            z_gap_mm=(None if z_flat is None or z0 is None
                                      else abs(z_flat - z0)),
                            tangent_gap=(_tangent_gap(flat_tangent, direction)))
        elif _kind(first) == 'transition' and _kind(second) == 'flat':
            end = _xy(first.get('end'))
            flat_point, flat_tangent = _prim_first(second)
            direction = _unit_direction(first.get('direction'))
            z1 = _parse_float(first.get('z1'))
            z_flat = _part_flat_z(second)
            junction = dict(index=index, kind='transition_to_flat',
                            position_gap_mm=(None if end is None
                                             or flat_point is None
                                             else math.dist(end, flat_point)),
                            z_gap_mm=(None if z1 is None or z_flat is None
                                      else abs(z1 - z_flat)),
                            tangent_gap=(_tangent_gap(direction, flat_tangent)))
        else:
            junction = dict(index=index, kind='flat_to_flat'
                            if _kind(first) == 'flat' else 'transition_to_transition',
                            position_gap_mm=None, z_gap_mm=None, tangent_gap=None)
        junctions.append(junction)
    return junctions


def _check_port_poses(record, model, endpoints, violations):
    """First/last lead flat must reproduce the exact port pose of the route."""
    parts = record.get('parts') or []
    if not parts:
        return
    plane = str(record.get('plane') or '')
    iface_z = _interface_z(model, plane)
    route_id = _parse_int(record.get('route_id'))
    first, last = parts[0], parts[-1]
    source_id = record.get('source_endpoint')
    target_id = record.get('target_endpoint')
    if source_id in endpoints:
        source = endpoints[source_id]
        point, tangent = _prim_first(first) if _kind(first) == 'flat' else (None, None)
        if point is None:
            violations.append(_violation('structure', 'source_pose_missing',
                                         route_id=route_id))
        else:
            if math.dist(point, tuple(source['routing_xy'])) > TOL_POS_MM:
                violations.append(_violation(
                    'structure', 'source_start_not_at_port', route_id=route_id,
                    detail='start=%r port=%r' % (point, tuple(source['routing_xy']))))
            if tangent is not None:
                if math.hypot(tangent[0] - float(source['inward'][0]),
                              tangent[1] - float(source['inward'][1])) > TOL_TANGENT:
                    violations.append(_violation(
                        'structure', 'source_start_tangent_mismatch',
                        route_id=route_id,
                        detail='tangent=%r inward=%r' % (tangent, tuple(source['inward']))))
            if iface_z is not None:
                port_z = _parse_float(source.get('z_mm'))
                if port_z is not None and abs(port_z - iface_z) > TOL_Z_MM:
                    violations.append(_violation(
                        'structure', 'source_port_height_not_interface',
                        route_id=route_id,
                        detail='port_z=%r interface=%r' % (port_z, iface_z)))
    else:
        violations.append(_violation('structure', 'source_endpoint_not_a_port',
                                     route_id=route_id, detail=repr(source_id)))
    if target_id in endpoints:
        target = endpoints[target_id]
        point, tangent = _prim_last(last) if _kind(last) == 'flat' else (None, None)
        if point is None:
            violations.append(_violation('structure', 'target_pose_missing',
                                         route_id=route_id))
        else:
            if math.dist(point, tuple(target['routing_xy'])) > TOL_POS_MM:
                violations.append(_violation(
                    'structure', 'target_end_not_at_port', route_id=route_id,
                    detail='end=%r port=%r' % (point, tuple(target['routing_xy']))))
            if tangent is not None:
                inward = target['inward']
                if math.hypot(tangent[0] + float(inward[0]),
                              tangent[1] + float(inward[1])) > TOL_TANGENT:
                    violations.append(_violation(
                        'structure', 'target_end_tangent_mismatch',
                        route_id=route_id,
                        detail='tangent=%r -inward=%r'
                               % (tangent, (-float(inward[0]), -float(inward[1])))))
            if iface_z is not None:
                port_z = _parse_float(target.get('z_mm'))
                if port_z is not None and abs(port_z - iface_z) > TOL_Z_MM:
                    violations.append(_violation(
                        'structure', 'target_port_height_not_interface',
                        route_id=route_id,
                        detail='port_z=%r interface=%r' % (port_z, iface_z)))
    else:
        violations.append(_violation('structure', 'target_endpoint_not_a_port',
                                     route_id=route_id, detail=repr(target_id)))


def _check_part_tags(record, require_tags, violations, stats):
    """Tag convention: lead/body flats and fanout/mid transitions."""
    parts = record.get('parts') or []
    route_id = _parse_int(record.get('route_id'))
    n = len(parts)
    transitions = [index for index, part in enumerate(parts)
                   if _kind(part) == 'transition']
    missing = 0
    for index, part in enumerate(parts):
        if _kind(part) == 'flat':
            if n == 1:
                expected = 'body'
            else:
                expected = 'lead' if index in (0, n - 1) else 'body'
        elif _kind(part) == 'transition':
            if not transitions:
                continue
            if index in (min(transitions), max(transitions)):
                expected = 'fanout'
            else:
                expected = 'mid'
        else:
            continue
        tag = part.get('tag')
        if tag is None or tag == '':
            missing += 1
            if require_tags:
                violations.append(_violation(
                    'structure', 'native_part_missing_tag', route_id=route_id,
                    detail='part=%d kind=%s expected=%s'
                           % (index, _kind(part), expected)))
        elif str(tag) != expected:
            violations.append(_violation(
                'structure', 'part_tag_mismatch', route_id=route_id,
                detail='part=%d kind=%s tag=%r expected=%r'
                       % (index, _kind(part), tag, expected)))
    stats['missing_tags'] += missing
    stats['tagged_parts'] += len(parts) - missing


def _check_route_structure(record, model, endpoints, violations, stats):
    route_id = _parse_int(record.get('route_id'))
    parts = record.get('parts')
    stats['routes_checked'] += 1
    if not isinstance(parts, list) or not parts:
        violations.append(_violation('structure', 'route_missing_parts',
                                     route_id=route_id,
                                     detail=repr(parts)[:120]))
        return
    parts = [part if isinstance(part, dict) else {} for part in parts]
    n = len(parts)
    kinds = [_kind(part) for part in parts]
    stats['parts_total'] += n
    # -- alternation / first-last flat -----------------------------------
    expected = ['flat' if index % 2 == 0 else 'transition'
                for index in range(n)]
    if n % 2 == 0 or kinds != expected:
        violations.append(_violation(
            'structure', 'parts_not_alternating_flat_transition',
            route_id=route_id, detail='kinds=%r' % (kinds,)))
    for index, kind in enumerate(kinds):
        if kind not in ('flat', 'transition'):
            violations.append(_violation(
                'structure', 'unknown_part_kind', route_id=route_id,
                detail='part=%d kind=%r' % (index, kind)))
    stats['flats_total'] += sum(1 for kind in kinds if kind == 'flat')
    stats['transitions_total'] += sum(1 for kind in kinds if kind == 'transition')
    # -- leaf flat checks (z / layer_id / primitives / declared length) ---
    for index, part in enumerate(parts):
        if _kind(part) == 'flat':
            leaf = []
            V21._check_flat_part(route_id, index, part, model['z_map'],
                                 model['interface_ids'], leaf)
            violations.extend(_adopt('structure', leaf))
        elif _kind(part) == 'transition':
            if index == 0 or index == n - 1:
                violations.append(_violation(
                    'structure', 'transition_at_route_end', route_id=route_id,
                    detail='part=%d' % index))
            elif index - 1 >= 0 and index + 1 < n \
                    and _kind(parts[index - 1]) == 'flat' \
                    and _kind(parts[index + 1]) == 'flat':
                leaf = []
                V21._check_transition(route_id, index, parts, leaf)
                violations.extend(_adopt('structure', leaf))
    # -- explicit junction continuity (position / z / tangent) ------------
    junctions = _junction_report(record, model)
    for junction in junctions:
        if junction['kind'] not in ('flat_to_transition', 'transition_to_flat'):
            continue
        stats['junctions_checked'] += 1
        for key, tolerance, kind_name in (
                ('position_gap_mm', TOL_POS_MM, 'junction_position_discontinuity'),
                ('z_gap_mm', TOL_Z_MM, 'junction_height_discontinuity'),
                ('tangent_gap', TOL_TANGENT, 'junction_tangent_discontinuity')):
            gap = junction.get(key)
            if gap is not None and gap > tolerance:
                violations.append(_violation(
                    'structure', kind_name, route_id=route_id,
                    detail='junction=%d %s=%r > %r'
                           % (junction['index'], key, gap, tolerance)))
        stats['max_position_gap_mm'] = max(
            stats['max_position_gap_mm'],
            junction.get('position_gap_mm') or 0.0)
        stats['max_z_gap_mm'] = max(stats['max_z_gap_mm'],
                                    junction.get('z_gap_mm') or 0.0)
        stats['max_tangent_gap'] = max(stats['max_tangent_gap'],
                                       junction.get('tangent_gap') or 0.0)
    # -- route plane / interface heights ---------------------------------
    plane = str(record.get('plane') or '')
    iface_z = _interface_z(model, plane)
    iface_plane = _interface_plane_id(model, plane)
    if iface_z is None:
        violations.append(_violation('structure', 'route_unknown_plane',
                                     route_id=route_id, detail=repr(plane)))
    else:
        flats = flat_parts(record)
        if not flats:
            violations.append(_violation('structure', 'route_has_no_flat',
                                         route_id=route_id))
        else:
            first_index, first = flats[0]
            last_index, last = flats[-1]
            first_z, last_z = _part_flat_z(first), _part_flat_z(last)
            if first_z is None or abs(first_z - iface_z) > TOL_Z_MM:
                violations.append(_violation(
                    'structure', 'lead_source_wrong_interface_z',
                    route_id=route_id,
                    detail='z=%r expected=%r' % (first_z, iface_z)))
            if last_z is None or abs(last_z - iface_z) > TOL_Z_MM:
                violations.append(_violation(
                    'structure', 'lead_target_wrong_interface_z',
                    route_id=route_id,
                    detail='z=%r expected=%r' % (last_z, iface_z)))
            accepted_layers = {LEGACY_INTERFACE_LAYER_ID}
            if iface_plane is not None:
                accepted_layers.add(int(iface_plane))
            first_layer = _parse_int(first.get('layer_id'))
            last_layer = _parse_int(last.get('layer_id'))
            if first_layer not in accepted_layers:
                violations.append(_violation(
                    'structure', 'lead_source_not_interface_plane',
                    route_id=route_id, detail='layer_id=%r' % (first_layer,)))
            if last_layer not in accepted_layers:
                violations.append(_violation(
                    'structure', 'lead_target_not_interface_plane',
                    route_id=route_id, detail='layer_id=%r' % (last_layer,)))
            # the fanout transitions must touch the interface heights
            transitions = transition_parts(record)
            if transitions:
                first_transition = transitions[0][1]
                last_transition = transitions[-1][1]
                first_z0 = _parse_float(first_transition.get('z0'))
                last_z1 = _parse_float(last_transition.get('z1'))
                if first_z0 is None or abs(first_z0 - iface_z) > TOL_Z_MM:
                    violations.append(_violation(
                        'structure', 'fanout_start_not_interface_height',
                        route_id=route_id,
                        detail='z0=%r expected=%r'
                               % (first_transition.get('z0'), iface_z)))
                if last_z1 is None or abs(last_z1 - iface_z) > TOL_Z_MM:
                    violations.append(_violation(
                        'structure', 'fanout_end_not_interface_height',
                        route_id=route_id,
                        detail='z1=%r expected=%r'
                               % (last_transition.get('z1'), iface_z)))
            if n == 1 and transitions:
                violations.append(_violation(
                    'structure', 'direct_route_has_transition',
                    route_id=route_id))
            if n > 1 and len(flats) < 2:
                violations.append(_violation(
                    'structure', 'route_missing_body_flat', route_id=route_id))
    # -- port pose --------------------------------------------------------
    _check_port_poses(record, model, endpoints, violations)
    # -- tag convention ---------------------------------------------------
    _check_part_tags(record, require_tags=bool(record.get('native_3d')),
                     violations=violations, stats=stats)
    # -- cheap independent world structure check --------------------------
    try:
        raw = World.check_structure(record)
    except Exception as error:  # noqa: BLE001 - malformed record is reported
        raw = ['structure_check_exception:%s: %s' % (type(error).__name__, error)]
    if raw:
        stats['world_structure_flagged'] += 1
        violations.append(_violation(
            'structure', 'world_check_structure_flagged', route_id=route_id,
            detail=repr(raw[:6])))


def check_structure(routed, model, endpoints):
    violations = []
    stats = dict(routes_checked=0, parts_total=0, flats_total=0,
                 transitions_total=0, junctions_checked=0,
                 max_position_gap_mm=0.0, max_z_gap_mm=0.0,
                 max_tangent_gap=0.0, world_structure_flagged=0,
                 tagged_parts=0, missing_tags=0, direct_routes=0,
                 non_direct_routes=0, native_routes=0)
    for record in routed:
        _check_route_structure(record, model, endpoints, violations, stats)
        if transition_parts(record):
            stats['non_direct_routes'] += 1
        else:
            stats['direct_routes'] += 1
        if record.get('native_3d'):
            stats['native_routes'] += 1
    return _finalize_check('structure', violations, stats)


# ===========================================================================
# check 3: native metadata re-derived from the parts
# ===========================================================================
def _compare_sequence(route_id, violations, field, declared, expected,
                      kind='native_metadata'):
    if not isinstance(declared, list):
        violations.append(_violation(kind, '%s_missing_or_not_list' % field,
                                     route_id=route_id,
                                     detail=repr(declared)[:160]))
        return
    if expected is None:
        return
    if _canon(declared) != _canon(expected):
        violations.append(_violation(kind, '%s_mismatch' % field,
                                     route_id=route_id,
                                     detail='declared=%r rebuilt=%r'
                                            % (declared, expected)))


def _compare_float_list(route_id, violations, field, declared, expected,
                        tol=TOL_MODEL_Z_MM, kind='native_metadata'):
    if not isinstance(declared, list):
        violations.append(_violation(kind, '%s_missing_or_not_list' % field,
                                     route_id=route_id,
                                     detail=repr(declared)[:160]))
        return
    if expected is None:
        return
    if len(declared) != len(expected):
        violations.append(_violation(kind, '%s_length_mismatch' % field,
                                     route_id=route_id,
                                     detail='declared=%d rebuilt=%d'
                                            % (len(declared), len(expected))))
        return
    for index, (left, right) in enumerate(zip(declared, expected)):
        try:
            gap = abs(float(left) - float(right))
        except (TypeError, ValueError):
            gap = None
        if gap is None or gap > tol:
            violations.append(_violation(
                kind, '%s_value_mismatch' % field, route_id=route_id,
                detail='index=%d declared=%r rebuilt=%r'
                       % (index, left, right)))
            return


def _check_native_metadata(record, model, assignment_row, violations, stats):
    route_id = _parse_int(record.get('route_id'))
    parts = record.get('parts') or []
    stats['routes_checked'] += 1
    if not isinstance(record.get('parts'), list) or not record.get('parts'):
        return
    info = recompute_route(record, model)
    native = bool(record.get('native_3d'))
    stats['native_routes' if native else 'baseline_routes'] += 1
    # -- every flat z must be one of the 21 routing heights ----------------
    flat_heights = []
    for index, part in info['flats']:
        z = _part_flat_z(part)
        flat_heights.append(z)
        if z is None or _plane_of_z(model, z) is None:
            violations.append(_violation(
                'native_metadata', 'flat_z_not_model_height', route_id=route_id,
                detail='part=%d z=%r' % (index, z)))
    stats['flat_parts'] += len(info['flats'])
    # -- 50 um minimum pitch between the distinct heights of one route -----
    if info['min_pitch_mm'] is not None:
        stats['min_route_pitch_mm'] = min(
            stats['min_route_pitch_mm'], info['min_pitch_mm'])
        if info['min_pitch_mm'] < MIN_LAYER_PITCH_MM - TOL_MODEL_Z_MM:
            violations.append(_violation(
                'native_metadata', 'route_min_layer_pitch_below_50um',
                route_id=route_id,
                detail='min_pitch=%r heights=%r'
                       % (info['min_pitch_mm'], info['unique_heights'])))
    stats['distinct_heights'] += len(info['unique_heights'])
    # -- n_transitions is a real derived field for every route -------------
    declared_n = _parse_int(record.get('n_transitions'))
    if declared_n is None:
        violations.append(_violation('native_metadata',
                                     'n_transitions_missing', route_id=route_id))
    elif declared_n != len(info['transitions']):
        violations.append(_violation(
            'native_metadata', 'n_transitions_mismatch', route_id=route_id,
            detail='declared=%d actual=%d'
                   % (declared_n, len(info['transitions']))))
    # -- layer_sequence / layer_z_sequence / layers_used -------------------
    _compare_sequence(route_id, violations, 'layer_sequence',
                      record.get('layer_sequence'),
                      info['expected_layer_sequence'])
    _compare_float_list(route_id, violations, 'layer_z_sequence',
                        record.get('layer_z_sequence'),
                        info['expected_layer_z_sequence'], tol=TOL_Z_MM)
    _compare_sequence(route_id, violations, 'layers_used',
                      record.get('layers_used'), info['expected_layers_used'])
    # -- rebuilt length / xy length ----------------------------------------
    declared_length = _parse_float(record.get('length_mm'))
    if declared_length is None:
        violations.append(_violation('native_metadata', 'length_mm_missing',
                                     route_id=route_id))
    elif info['length_mm'] is None:
        violations.append(_violation('native_metadata', 'length_mm_unrebuildable',
                                     route_id=route_id))
    elif abs(declared_length - info['length_mm']) > TOL_LEN_MM:
        violations.append(_violation(
            'native_metadata', 'length_mm_mismatch', route_id=route_id,
            detail='declared=%.12g rebuilt=%.12g'
                   % (declared_length, info['length_mm'])))
    declared_xy = _parse_float(record.get('xy_length_mm'))
    if declared_xy is not None and info['xy_length_mm'] is not None:
        if abs(declared_xy - info['xy_length_mm']) > TOL_LEN_MM:
            violations.append(_violation(
                'native_metadata', 'xy_length_mm_mismatch', route_id=route_id,
                detail='declared=%.12g rebuilt=%.12g'
                       % (declared_xy, info['xy_length_mm'])))
    stats['total_length_mm'] += declared_length or 0.0
    stats['max_route_length_mm'] = max(stats['max_route_length_mm'],
                                       declared_length or 0.0)
    # -- primary (longest) body flat -> target_layer -----------------------
    declared_target = _parse_int(record.get('target_layer'))
    if not info['body_indices']:
        violations.append(_violation('native_metadata',
                                     'route_has_no_body_flat', route_id=route_id))
    elif declared_target is None:
        violations.append(_violation('native_metadata', 'target_layer_missing',
                                     route_id=route_id))
    elif info['primary_planes'] and declared_target not in info['primary_planes']:
        violations.append(_violation(
            'native_metadata', 'target_layer_not_primary_body_flat',
            route_id=route_id,
            detail='declared=%r primary=%r body_planes=%r'
                   % (declared_target, info['primary_planes'],
                      info['body_planes'])))
    declared_target_plane = _parse_int(record.get('target_plane'))
    if declared_target_plane is not None and declared_target is not None \
            and declared_target_plane != declared_target:
        violations.append(_violation(
            'native_metadata', 'target_plane_mismatch', route_id=route_id,
            detail='target_plane=%r target_layer=%r'
                   % (declared_target_plane, declared_target)))
    declared_target_z = _parse_float(record.get('target_z_mm'))
    if declared_target_z is not None and info['primary_z'] is not None:
        if abs(declared_target_z - info['primary_z']) > TOL_Z_MM:
            violations.append(_violation(
                'native_metadata', 'target_z_mm_mismatch', route_id=route_id,
                detail='declared=%r rebuilt=%r'
                       % (declared_target_z, info['primary_z'])))
    # -- body_heights (native routes must declare it) ----------------------
    declared_body = record.get('body_heights')
    if native:
        if not isinstance(declared_body, list):
            violations.append(_violation(
                'native_metadata', 'native_missing_body_heights',
                route_id=route_id, detail=repr(declared_body)[:120]))
        else:
            _compare_float_list(route_id, violations, 'body_heights',
                                declared_body, info['body_heights'])
    elif declared_body is not None:
        _compare_float_list(route_id, violations, 'body_heights',
                            declared_body, info['body_heights'])
    # -- interface lead heights declared in start/end z --------------------
    plane = str(record.get('plane') or '')
    iface_z = _interface_z(model, plane)
    for field, expected in (('start_z_mm', iface_z), ('end_z_mm', iface_z)):
        value = _parse_float(record.get(field))
        if value is not None and expected is not None \
                and abs(value - expected) > TOL_Z_MM:
            violations.append(_violation(
                'native_metadata', '%s_mismatch' % field, route_id=route_id,
                detail='declared=%r interface=%r' % (value, expected)))
    lifted = record.get('lifted')
    if lifted is not None:
        if native and not bool(lifted):
            violations.append(_violation('native_metadata', 'native_lifted_false',
                                         route_id=route_id))
        if not native and bool(lifted) and not info['transitions']:
            violations.append(_violation('native_metadata',
                                         'direct_route_lifted_true',
                                         route_id=route_id))
    # -- native-only metadata ---------------------------------------------
    if native:
        stats['native_routes'] += 0  # already counted above
        if not info['transitions']:
            violations.append(_violation('native_metadata',
                                         'native_route_without_transition',
                                         route_id=route_id))
        if not info['mid_indices']:
            violations.append(_violation(
                'native_metadata', 'native_route_without_mid_transition',
                route_id=route_id))
        if info['unpaired_mid']:
            violations.append(_violation(
                'native_metadata', 'mid_transition_not_in_excursion',
                route_id=route_id, detail=repr(info['unpaired_mid'])))
        declared_mid_count = _parse_int(record.get('n_mid_transitions'))
        if declared_mid_count is None:
            violations.append(_violation(
                'native_metadata', 'native_missing_n_mid_transitions',
                route_id=route_id))
        elif declared_mid_count != len(info['mid_indices']):
            violations.append(_violation(
                'native_metadata', 'n_mid_transitions_mismatch',
                route_id=route_id,
                detail='declared=%d rebuilt=%d'
                       % (declared_mid_count, len(info['mid_indices']))))
        declared_mid = record.get('mid_transitions')
        declared_mid_entries = []
        if not isinstance(declared_mid, list):
            violations.append(_violation(
                'native_metadata', 'native_missing_mid_transitions',
                route_id=route_id, detail=repr(declared_mid)[:120]))
        else:
            for item in declared_mid:
                if not isinstance(item, dict):
                    violations.append(_violation(
                        'native_metadata', 'mid_transitions_entry_not_mapping',
                        route_id=route_id, detail=repr(item)[:80]))
                    continue
                declared_mid_entries.append(dict(
                    part_index=_parse_int(item.get('part_index')),
                    from_z=_parse_float(item.get('from_z')),
                    to_z=_parse_float(item.get('to_z'))))
            if len(declared_mid_entries) != len(info['mid_entries']):
                violations.append(_violation(
                    'native_metadata', 'mid_transitions_count_mismatch',
                    route_id=route_id,
                    detail='declared=%d rebuilt=%d'
                           % (len(declared_mid_entries),
                              len(info['mid_entries']))))
            else:
                for declared_entry, rebuilt_entry in zip(declared_mid_entries,
                                                         info['mid_entries']):
                    if declared_entry['part_index'] != rebuilt_entry['part_index']:
                        violations.append(_violation(
                            'native_metadata', 'mid_transition_part_index_mismatch',
                            route_id=route_id,
                            detail='declared=%r rebuilt=%r'
                                   % (declared_entry['part_index'],
                                      rebuilt_entry['part_index'])))
                    for field in ('from_z', 'to_z'):
                        left = declared_entry[field]
                        right = rebuilt_entry[field]
                        if left is None or right is None \
                                or abs(left - right) > TOL_Z_MM:
                            violations.append(_violation(
                                'native_metadata',
                                'mid_transition_%s_mismatch' % field,
                                route_id=route_id,
                                detail='part=%r declared=%r rebuilt=%r'
                                       % (declared_entry['part_index'],
                                          left, right)))
        declared_excursions = record.get('excursions')
        if not isinstance(declared_excursions, list) or not declared_excursions:
            violations.append(_violation(
                'native_metadata', 'native_missing_excursions',
                route_id=route_id, detail=repr(declared_excursions)[:120]))
        else:
            if len(declared_excursions) != len(info['excursions']):
                violations.append(_violation(
                    'native_metadata', 'excursions_count_mismatch',
                    route_id=route_id,
                    detail='declared=%d rebuilt=%d'
                           % (len(declared_excursions), len(info['excursions']))))
            matched = set()
            rebuilt_keys = {}
            for position, rebuilt in enumerate(info['excursions']):
                rebuilt_keys[(rebuilt['up_part_index'],
                              rebuilt['middle_part_index'],
                              rebuilt['down_part_index'])] = (position, rebuilt)
            for item in declared_excursions:
                if not isinstance(item, dict):
                    violations.append(_violation(
                        'native_metadata', 'excursion_entry_not_mapping',
                        route_id=route_id, detail=repr(item)[:80]))
                    continue
                up = _parse_int(item.get('up_part_index'))
                middle = _parse_int(item.get('middle_part_index'))
                down = _parse_int(item.get('down_part_index'))
                key = (up, middle, down)
                found = rebuilt_keys.get(key)
                if found is None:
                    violations.append(_violation(
                        'native_metadata', 'excursion_part_indices_mismatch',
                        route_id=route_id,
                        detail='declared=(%r,%r,%r) rebuilt=%r'
                               % (up, middle, down,
                                  sorted(rebuilt_keys))))
                    continue
                matched.add(found[0])
                rebuilt = found[1]
                for field in ('from_z', 'to_z'):
                    left = _parse_float(item.get(field))
                    right = rebuilt[field]
                    if left is None or abs(left - right) > TOL_Z_MM:
                        violations.append(_violation(
                            'native_metadata', 'excursion_%s_mismatch' % field,
                            route_id=route_id,
                            detail='%(u)r declared=%(l)r rebuilt=%(r)r'
                                   % dict(u=up, l=left, r=right)))
                # optional cross-check of the extra writer fields when present
                declared_from_plane = _parse_int(item.get('from_plane'))
                if declared_from_plane is not None:
                    expected_plane = _plane_of_z(model, rebuilt['from_z'])
                    if expected_plane is not None \
                            and declared_from_plane != expected_plane:
                        violations.append(_violation(
                            'native_metadata', 'excursion_from_plane_mismatch',
                            route_id=route_id,
                            detail='declared=%r rebuilt=%r'
                                   % (declared_from_plane, expected_plane)))
                declared_to_plane = _parse_int(item.get('to_plane'))
                if declared_to_plane is not None:
                    expected_plane = _plane_of_z(model, rebuilt['to_z'])
                    if expected_plane is not None \
                            and declared_to_plane != expected_plane:
                        violations.append(_violation(
                            'native_metadata', 'excursion_to_plane_mismatch',
                            route_id=route_id,
                            detail='declared=%r rebuilt=%r'
                                   % (declared_to_plane, expected_plane)))
            if len(matched) != len(info['excursions']):
                violations.append(_violation(
                    'native_metadata', 'excursion_not_declared',
                    route_id=route_id,
                    detail='rebuilt_indices=%r' % (
                        sorted(rebuilt_keys),)))
        if len(info['transitions']) != 2 + 2 * len(info['excursions']):
            violations.append(_violation(
                'native_metadata', 'native_transition_count_not_two_fanout_plus_excursion',
                route_id=route_id,
                detail='transitions=%d excursions=%d'
                       % (len(info['transitions']), len(info['excursions']))))
        if info['parts'] != 2 * len(info['transitions']) + 1:
            violations.append(_violation(
                'native_metadata', 'native_part_count_not_alternating',
                route_id=route_id,
                detail='parts=%d transitions=%d'
                       % (info['parts'], len(info['transitions']))));
        stats['native_routes'] = stats.get('native_routes', 0)
        stats['mid_transitions'] += len(info['mid_indices'])
        stats['excursions'] += len(info['excursions'])
        stats['native_body_flats'] += len(info['body_indices'])
        stats['max_body_flats_per_route'] = max(
            stats['max_body_flats_per_route'], len(info['body_indices']))
    else:
        # unchanged routes must keep the frozen baseline schema / shape
        for field in ('n_mid_transitions', 'mid_transitions', 'excursions'):
            value = record.get(field)
            if value not in (None, 0, [], ()):
                violations.append(_violation(
                    'native_metadata', 'non_native_route_has_native_metadata',
                    route_id=route_id, detail='field=%s value=%r'
                           % (field, value)[:160]))
        if info['mid_indices']:
            violations.append(_violation(
                'native_metadata', 'non_native_route_has_mid_transitions',
                route_id=route_id, detail=repr(info['mid_indices'])))
        if info['is_direct']:
            if info['parts'] != 1:
                violations.append(_violation(
                    'native_metadata', 'non_native_direct_route_not_single_flat',
                    route_id=route_id, detail='parts=%d' % info['parts']))
        else:
            shape = [_kind(part) for part in record.get('parts') or []]
            expected_shape = ['flat', 'transition', 'flat', 'transition', 'flat']
            if shape != expected_shape:
                violations.append(_violation(
                    'native_metadata', 'non_native_route_not_baseline_shape',
                    route_id=route_id, detail='parts=%r' % (shape,)))
    # -- informational: assignment still describes the primary plane ------
    if assignment_row is not None:
        assignment_plane = _parse_int(assignment_row.get('target_layer'))
        if assignment_plane is not None and declared_target is not None \
                and assignment_plane != declared_target:
            stats['assignment_primary_mismatch'] += 1
            stats['assignment_primary_mismatch_ids'].append(route_id)
    stats['body_flats'] += len(info['body_indices'])


def check_native_metadata(routed, model, assignment_by_id):
    violations = []
    stats = dict(routes_checked=0, native_routes=0, baseline_routes=0,
                 flat_parts=0, body_flats=0, native_body_flats=0,
                 mid_transitions=0, excursions=0,
                 assignment_primary_mismatch=0,
                 assignment_primary_mismatch_ids=[],
                 min_route_pitch_mm=float('inf'), distinct_heights=0,
                 total_length_mm=0.0, max_route_length_mm=0.0,
                 max_body_flats_per_route=0)
    for record in routed:
        route_id = _parse_int(record.get('route_id'))
        row = assignment_by_id.get(int(route_id)) if route_id is not None else None
        _check_native_metadata(record, model, row, violations, stats)
    if stats['min_route_pitch_mm'] == float('inf'):
        stats['min_route_pitch_mm'] = None
    stats['assignment_primary_mismatch_ids'] = \
        sorted(stats['assignment_primary_mismatch_ids'])[:MAX_OFFENDING_IDS]
    stats['total_length_mm'] = _round(stats['total_length_mm'], 6)
    stats['max_route_length_mm'] = _round(stats['max_route_length_mm'], 6)
    return _finalize_check('native_metadata', violations, stats)


# ===========================================================================
# check 4: R15 (reused validate21.check_radius -- verified multi-transition)
# ===========================================================================
def check_radius(routed):
    violations = []
    stats = dict(routes_checked=0, flat_arc_count=0, flat_arc_radii=[],
                 transition_count=0, transition_declared_radii=[],
                 transition_samples_total=0, transition_min_sampled_radius=None)
    arc_radii = set()
    declared_radii = set()
    sampled_min = None
    for record in routed:
        stats['routes_checked'] += 1
        route_violations = []
        details = V21.check_radius(record, route_violations)
        violations.extend(_adopt('radius', route_violations))
        stats['flat_arc_count'] += int(details.get('flat_arc_count') or 0)
        stats['transition_count'] += int(details.get('transition_count') or 0)
        stats['transition_samples_total'] += int(
            details.get('transition_samples_total') or 0)
        arc_radii.update(details.get('flat_arc_radii') or [])
        declared_radii.update(details.get('transition_declared_radii') or [])
        value = details.get('transition_min_sampled_radius')
        if value is not None:
            sampled_min = value if sampled_min is None else min(sampled_min, value)
    stats['flat_arc_radii'] = sorted(arc_radii)
    stats['transition_declared_radii'] = sorted(declared_radii)
    stats['transition_min_sampled_radius'] = _round(sampled_min, 9)
    stats['r15_required_mm'] = R15_MM
    stats['transition_min_required_mm'] = R15_MM - TOL_RADIUS_MM
    stats['multi_transition_route_support'] = True
    stats['min_flat_arc_radius_mm'] = (min(arc_radii) if arc_radii else None)
    return _finalize_check('radius', violations, stats)


# ===========================================================================
# check 5: glass bounds (reused validate21.check_glass)
# ===========================================================================
def check_glass(routed):
    violations = []
    stats = dict(routes_checked=0, samples=0, min_centerline_margin_mm=None,
                 min_edge_margin_mm=None, min_z_mm=None, max_z_mm=None,
                 edge_margin_negative_route_count=0,
                 waveguide_half_width_mm=V21.WAVEGUIDE_HALF_WIDTH_MM,
                 bounds=dict(x=[0.0, V21.GLASS_XY_MM], y=[0.0, V21.GLASS_XY_MM],
                             z=[V21.GLASS_Z_MIN_MM, V21.GLASS_Z_MAX_MM]))
    center = None
    edge = None
    z_min = None
    z_max = None
    for record in routed:
        stats['routes_checked'] += 1
        route_violations = []
        details = V21.check_glass(record, route_violations)
        violations.extend(_adopt('glass', route_violations))
        stats['samples'] += int(details.get('samples') or 0)
        value = details.get('min_centerline_margin_mm')
        if value is not None:
            center = value if center is None else min(center, value)
        value = details.get('min_edge_margin_mm')
        if value is not None:
            edge = value if edge is None else min(edge, value)
        value = details.get('min_z_mm')
        if value is not None:
            z_min = value if z_min is None else min(z_min, value)
        value = details.get('max_z_mm')
        if value is not None:
            z_max = value if z_max is None else max(z_max, value)
        if details.get('edge_margin_negative'):
            stats['edge_margin_negative_route_count'] += 1
    stats['min_centerline_margin_mm'] = _round(center)
    stats['min_edge_margin_mm'] = _round(edge)
    stats['min_z_mm'] = _round(z_min)
    stats['max_z_mm'] = _round(z_max)
    return _finalize_check('glass', violations, stats)


# ===========================================================================
# check 6: true 3D clearance (fresh World from the run's layer model)
# ===========================================================================
def check_clearance(routed, planes, skip_min_clearance=False, log=print):
    started = time.time()
    violations = []
    stack = V21.build_model_stack(planes)
    result = V21.check_true_3d_clearance(routed, stack)
    for item in result.get('violations') or []:
        entry = dict(item)
        entry['check'] = 'clearance'
        violations.append(entry)
    scan = None
    if not skip_min_clearance:
        log('[clearance] running independent minimum 3D clearance scan ...')
        try:
            scan = V21.measure_min_3d_clearance(routed)
        except Exception as error:  # noqa: BLE001 - reported as a violation
            violations.append(_violation(
                'clearance', 'min_clearance_scan_exception', detail=repr(error)))
    min_clearance = None
    lower_bound = None
    if scan is not None:
        min_clearance = scan.get('min_3d_clearance_mm')
        lower_bound = scan.get('min_3d_clearance_lower_bound_mm')
        if scan.get('violation_count'):
            violations.append(_violation(
                'clearance', 'min_clearance_scan_violations',
                detail='violation_count=%s' % scan.get('violation_count')))
    details = dict(
        method=('fresh four_side_1024.l3d.world.World(model stack from the run '
                'layer_planes body heights, clearance=0.05); '
                'check_route(route, check_self=True) in route-id order, '
                'then add_route'),
        clearance_mm=MIN_3D_CLEARANCE_MM,
        body_plane_count=len(stack.routing_layer_ids),
        routes_checked=result.get('checked'),
        routes_added=result.get('added'),
        world=result.get('world'),
        violation_kinds=result.get('by_kind'),
        min_clearance_scan=scan,
        min_3d_clearance_mm=min_clearance,
        min_3d_clearance_lower_bound_mm=lower_bound,
        runtime_seconds=round(time.time() - started, 2),
    )
    return _finalize_check('clearance', violations, details)


# ===========================================================================
# check 7: ports (reused validate21.check_ports)
# ===========================================================================
def check_ports(routed, failed, records):
    violations, details = V21.check_ports(routed, failed, records,
                                          V21.build_true_routes())
    details = dict(details)
    details['validation_route_ids_vs_true_data'] = 'reused validate21.check_ports'
    return _finalize_check('ports', violations, details)


# ===========================================================================
# check 8: strict same-plane D56 / crossings grouped by physical height
# ===========================================================================
def check_crossings(routed, planes, assignment_by_id):
    started = time.time()
    violations, details = V21.check_crossings(routed, planes, assignment_by_id)
    details = dict(details)
    details['crossing_rule'] = (
        'every flat part grouped by physical z (all heights, interface leads '
        'merged); fslw strict D56 audit per height; reused '
        'validate21.check_crossings')
    details['runtime_seconds'] = round(time.time() - started, 2)
    return _finalize_check('crossings', violations, details)


# ===========================================================================
# check 9: the 368 manual-group routes are frozen to the E5 baseline
# ===========================================================================
MANUAL_FROZEN_FIELDS = ('parts', 'length_mm', 'start_z_mm', 'end_z_mm',
                        'target_z_mm', 'z_span_mm', 'layer_z_sequence')
MANUAL_NATIVE_FIELDS = ('native_3d', 'n_mid_transitions', 'mid_transitions',
                        'excursions', 'body_heights')


def check_manual_frozen(routed, assignment_by_id, baseline_by_id):
    violations = []
    details = dict(
        rule=('routes whose assignment row has a non-empty manual_group must '
              'keep the frozen E5 parts / length_mm / z fields byte-for-byte'),
        frozen_fields=list(MANUAL_FROZEN_FIELDS),
        manual_route_count=0, checked=0, matched=0, mismatch_count=0,
        mismatch_route_ids=[], missing_in_baseline=[], missing_in_run=[],
        changed_manual_route_ids=[])
    manual_ids = sorted(route_id for route_id, row in assignment_by_id.items()
                        if str(row.get('manual_group') or '').strip())
    details['manual_route_count'] = len(manual_ids)
    run_by_id = {}
    for record in routed:
        route_id = _parse_int(record.get('route_id'))
        if route_id is not None:
            run_by_id[int(route_id)] = record
    for route_id in manual_ids:
        record = run_by_id.get(route_id)
        if record is None:
            details['missing_in_run'].append(route_id)
            violations.append(_violation('manual_frozen', 'manual_route_missing',
                                         route_id=route_id))
            continue
        baseline = baseline_by_id.get(route_id)
        if baseline is None:
            details['missing_in_baseline'].append(route_id)
            violations.append(_violation('manual_frozen',
                                         'manual_route_missing_in_baseline',
                                         route_id=route_id))
            continue
        details['checked'] += 1
        mismatched = []
        for field in MANUAL_FROZEN_FIELDS:
            if _canon(record.get(field)) != _canon(baseline.get(field)):
                mismatched.append(field)
        for field in MANUAL_NATIVE_FIELDS:
            value = record.get(field)
            if value not in (None, False, 0, [], ()):
                mismatched.append(field)
        if mismatched:
            details['mismatch_count'] += 1
            details['mismatch_route_ids'].append(route_id)
            violations.append(_violation(
                'manual_frozen', 'manual_route_geometry_changed',
                route_id=route_id, detail='fields=%r' % (mismatched,)))
        else:
            details['matched'] += 1
    details['mismatch_route_ids'] = details['mismatch_route_ids'][:MAX_OFFENDING_IDS]
    details['manual_geometry_mismatch_count'] = details['mismatch_count']
    return _finalize_check('manual_frozen', violations, details)


# ===========================================================================
# model check (layer_planes integrity against the frozen SPEC table)
# ===========================================================================
def check_model(planes, model_source):
    violations, details = V21.check_model(planes, model_source)
    details = dict(details)
    details['violation_kinds'] = dict(sorted(
        Counter(str(item.get('kind')) for item in violations).items()))
    return _finalize_check('model', violations, details)


# ===========================================================================
# E5 regression expectations
# ===========================================================================
def _regression_block(counts, min_clearance, skip_min_clearance):
    checks = []

    def add(name, expected, actual, passed, detail=None):
        checks.append(dict(name=name, expected=expected, actual=actual,
                           passed=bool(passed), detail=detail))

    add('routed', E5_EXPECT['routed'], counts.get('routed'),
        counts.get('routed') == E5_EXPECT['routed'])
    add('failed', E5_EXPECT['failed'], counts.get('failed'),
        counts.get('failed') == E5_EXPECT['failed'])
    add('routed_records', E5_EXPECT['routed'], counts.get('records'),
        counts.get('records') == E5_EXPECT['routed'])
    add('direct_routes', E5_EXPECT['direct_routes'],
        counts.get('direct_routes'),
        counts.get('direct_routes') == E5_EXPECT['direct_routes'])
    add('non_direct_routes', E5_EXPECT['non_direct_routes'],
        counts.get('non_direct_routes'),
        counts.get('non_direct_routes') == E5_EXPECT['non_direct_routes'])
    add('transitions', E5_EXPECT['transitions'], counts.get('transitions'),
        counts.get('transitions') == E5_EXPECT['transitions'])
    add('flat_arc_count', E5_EXPECT['flat_arc_count'],
        counts.get('flat_arc_count'),
        counts.get('flat_arc_count') == E5_EXPECT['flat_arc_count'])
    add('same_plane_crossings', E5_EXPECT['same_plane_crossings'],
        counts.get('same_plane_crossings'),
        counts.get('same_plane_crossings') == E5_EXPECT['same_plane_crossings'])
    add('same_plane_crossing_pairs', E5_EXPECT['same_plane_crossing_pairs'],
        counts.get('same_plane_crossing_pairs'),
        counts.get('same_plane_crossing_pairs')
        == E5_EXPECT['same_plane_crossing_pairs'])
    add('same_plane_crossing_violations',
        E5_EXPECT['same_plane_crossing_violations'],
        counts.get('same_plane_crossing_violations'),
        counts.get('same_plane_crossing_violations')
        == E5_EXPECT['same_plane_crossing_violations'])
    add('audited_heights', E5_EXPECT['audited_heights'],
        counts.get('audited_heights'),
        counts.get('audited_heights') == E5_EXPECT['audited_heights'])
    add('manual_routes', E5_EXPECT['manual_routes'],
        counts.get('manual_route_count'),
        counts.get('manual_route_count') == E5_EXPECT['manual_routes'])
    add('manual_geometry_mismatch_count',
        E5_EXPECT['manual_geometry_mismatch_count'],
        counts.get('manual_geometry_mismatch_count'),
        counts.get('manual_geometry_mismatch_count')
        == E5_EXPECT['manual_geometry_mismatch_count'])
    add('violation_total', E5_EXPECT['violation_total'],
        counts.get('violation_total'),
        counts.get('violation_total') == E5_EXPECT['violation_total'])
    if skip_min_clearance:
        checks.append(dict(name='min_3d_clearance_mm', expected='measured',
                           actual='skipped', passed=True,
                           detail='--skip-min-clearance'))
    else:
        expected = E5_EXPECT['min_3d_clearance_mm']
        actual = min_clearance
        passed = (actual is not None
                  and abs(float(actual) - expected)
                  <= E5_EXPECT['min_3d_clearance_tol'])
        add('min_3d_clearance_mm', expected, actual, passed)
    expected_length = E5_EXPECT['total_length_mm']
    actual_length = counts.get('total_length_mm')
    passed = (actual_length is not None
              and abs(float(actual_length) - expected_length)
              <= E5_EXPECT['total_length_tol'])
    add('total_length_mm', expected_length, actual_length, passed)
    return dict(expected=dict(E5_EXPECT), crossing_rule='per physical z',
                checks=checks, passed=all(item['passed'] for item in checks))


# ===========================================================================
# synthetic consistency tests (tests_native3d)
# ===========================================================================
def _run_synthetic_tests(model, log=print):
    try:
        from .tests_native3d import synthetic_native3d as SYN
    except Exception as error:  # noqa: BLE001 - reported, never fatal
        return dict(schema=CONSISTENCY_SCHEMA, tests=[], all_passed=False,
                    error='%s: %s' % (type(error).__name__, error))
    try:
        return SYN.run_synthetic_tests(model=model, log=log)
    except Exception as error:  # noqa: BLE001
        return dict(schema=CONSISTENCY_SCHEMA, tests=[], all_passed=False,
                    error='%s: %s' % (type(error).__name__, error))


# ===========================================================================
# orchestration
# ===========================================================================
def _default_out_dir(run_dir, regression):
    if regression:
        return RUN_ROOT / 'scratch' / 'native_validator' / 'e5_regression'
    if _is_within(run_dir, RUN_ROOT / 'scratch'):
        return RUN_ROOT / 'scratch' / 'native_validator' / \
            ('%s_check' % Path(run_dir).name)
    if _is_within(run_dir, RUN_ROOT):
        if _resolve(run_dir) == _resolve(RUN_ROOT):
            return RUN_ROOT / 'validation'
        return RUN_ROOT / 'validation' / str(Path(run_dir).name)
    if _is_within(run_dir, DEFAULT_BASELINE) \
            or _resolve(run_dir) == _resolve(DEFAULT_BASELINE):
        return RUN_ROOT / 'scratch' / 'native_validator' / \
            ('%s_check' % Path(run_dir).name)
    return Path(run_dir) / 'validation'


def _guard_out_dir(out_dir, baseline_dir):
    if _is_within(out_dir, baseline_dir):
        raise RuntimeError(
            'refusing to write validation output inside the frozen baseline '
            'directory: out_dir=%s baseline=%s' % (out_dir, baseline_dir))


def _counts_from_checks(records, routed, failed, checks):
    structure = checks.get('structure') or {}
    metadata = checks.get('native_metadata') or {}
    radius = checks.get('radius') or {}
    clearance = checks.get('clearance') or {}
    crossings = checks.get('crossings') or {}
    ports = checks.get('ports') or {}
    manual = checks.get('manual_frozen') or {}
    crossing_totals = (crossings.get('totals') or {})
    counts = dict(
        records=len(records), routed=len(routed), failed=len(failed),
        routed_by_plane=dict(sorted(ports.get('planes', {}).items()))
        if ports else {},
        direct_routes=structure.get('direct_routes'),
        non_direct_routes=structure.get('non_direct_routes'),
        native_routes=metadata.get('native_routes'),
        baseline_routes=metadata.get('baseline_routes'),
        transitions=radius.get('transition_count'),
        flat_arc_count=radius.get('flat_arc_count'),
        flat_arcs=radius.get('flat_arc_count'),
        mid_transitions=metadata.get('mid_transitions'),
        excursions=metadata.get('excursions'),
        body_flats=metadata.get('body_flats'),
        total_length_mm=metadata.get('total_length_mm'),
        max_route_length_mm=metadata.get('max_route_length_mm'),
        same_plane_crossings=crossing_totals.get('crossings'),
        same_plane_crossing_pairs=crossing_totals.get('crossing_pairs'),
        same_plane_crossing_violations=crossing_totals.get('violations'),
        audited_heights=crossings.get('audited_heights'),
        min_non_crossing_centerline_mm=crossings.get('min_non_crossing_centerline_mm'),
        per_route_crossing_distribution=crossings.get('per_route_distribution'),
        manual_route_count=manual.get('manual_route_count'),
        manual_geometry_mismatch_count=manual.get('manual_geometry_mismatch_count'),
        min_flat_arc_radius_mm=radius.get('min_flat_arc_radius_mm'),
        min_transition_sampled_radius_mm=radius.get(
            'transition_min_sampled_radius'),
        min_3d_clearance_mm=clearance.get('min_3d_clearance_mm'),
        min_3d_clearance_lower_bound_mm=clearance.get(
            'min_3d_clearance_lower_bound_mm'),
        min_centerline_glass_margin_mm=(checks.get('glass') or {}).get(
            'min_centerline_margin_mm'),
        min_edge_glass_margin_mm=(checks.get('glass') or {}).get(
            'min_edge_margin_mm'),
        assignment_primary_mismatch_count=metadata.get(
            'assignment_primary_mismatch'),
        min_route_layer_pitch_mm=metadata.get('min_route_pitch_mm'),
    )
    return counts


GEOMETRY_CHECKS = ('structure', 'native_metadata', 'radius', 'glass',
                   'clearance', 'crossings')
CONTRACT_CHECKS = ('coverage', 'ports', 'manual_frozen', 'model',
                   'synthetic')


def _summary_text(report):
    counts = report.get('counts') or {}
    checks = report.get('checks') or {}
    lines = []
    lines.append('Native 3D validation: %s'
                 % ('PASS' if report.get('validation_pass') else 'FAIL'))
    lines.append('  run_dir      : %s' % report.get('run_dir'))
    lines.append('  baseline_dir : %s' % report.get('baseline_dir'))
    lines.append('  routes       : records=%s routed=%s failed=%s '
                 '(native=%s, baseline=%s)'
                 % (counts.get('records'), counts.get('routed'),
                    counts.get('failed'), counts.get('native_routes'),
                    counts.get('baseline_routes')))
    lines.append('  parts        : transitions=%s mid=%s excursions=%s '
                 'flat_arcs=%s'
                 % (counts.get('transitions'), counts.get('mid_transitions'),
                    counts.get('excursions'), counts.get('flat_arc_count')))
    lines.append('  crossings    : events=%s pairs=%s violations=%s '
                 'heights=%s min_non_crossing=%s'
                 % (counts.get('same_plane_crossings'),
                    counts.get('same_plane_crossing_pairs'),
                    counts.get('same_plane_crossing_violations'),
                    counts.get('audited_heights'),
                    counts.get('min_non_crossing_centerline_mm')))
    lines.append('  clearance    : min_3d=%s (lower bound %s)'
                 % (counts.get('min_3d_clearance_mm'),
                    counts.get('min_3d_clearance_lower_bound_mm')))
    lines.append('  manual frozen: %s routes, %s mismatches'
                 % (counts.get('manual_route_count'),
                    counts.get('manual_geometry_mismatch_count')))
    for name in ('coverage', 'structure', 'native_metadata', 'radius', 'glass',
                 'clearance', 'ports', 'crossings', 'manual_frozen', 'model',
                 'synthetic'):
        block = checks.get(name) or {}
        lines.append('  [%-15s] violations=%s offending_routes=%s'
                     % (name, block.get('violations', 0),
                        block.get('offending_route_count', 0)))
    regression = report.get('regression')
    if regression is not None:
        lines.append('  E5 regression: %s'
                     % ('PASS' if regression.get('passed') else 'FAIL'))
        for item in regression.get('checks') or []:
            if not item.get('passed'):
                lines.append('    FAIL %s expected=%r actual=%r'
                             % (item.get('name'), item.get('expected'),
                                item.get('actual')))
    lines.append('  violation_total=%s runtime=%.1fs exit_code=%s'
                 % (report.get('violation_count'),
                    report.get('runtime_seconds', 0.0),
                    report.get('exit_code')))
    return '\n'.join(lines)


def validate_run(run_dir=None, baseline_dir=None, out_dir=None,
                 skip_min_clearance=False, log=print, regression=False,
                 skip_synthetic=False):
    """Validate one Native-3D run directory (or the frozen E5 baseline).

    Parameters
    ----------
    run_dir : path-like, optional
        Directory holding ``routes_l3d.json`` (required),
        ``assignment_1024.csv`` and ``layer_planes.json`` (fall back to the
        frozen baseline copy when missing).  Defaults to the E5 baseline in
        regression mode and to ``NATIVE_3D_CROSSING_OPT_1024`` otherwise.
    baseline_dir : path-like, optional
        Frozen E5 baseline directory (defaults to
        ``NON_C4_CROSSING_OPT_1024/E5_joint_repair_final``).
    out_dir : path-like, optional
        Output directory for ``validation.json`` /
        ``validator_consistency_tests.json`` (never inside the baseline).
    skip_min_clearance : bool
        Skip the independent minimum-3D-clearance scan (the fresh-World
        ``check_route`` clearance audit always runs).
    regression : bool
        Also compare the report against the frozen E5 acceptance numbers.
    skip_synthetic : bool
        Skip the in-memory synthetic consistency suite.

    Returns
    -------
    dict : the full validation report (also written to ``out_dir``).
    """
    started = time.time()
    run_dir = Path(run_dir) if run_dir is not None else (
        DEFAULT_BASELINE if regression else RUN_ROOT)
    baseline_dir = Path(baseline_dir) if baseline_dir is not None else \
        DEFAULT_BASELINE
    out_dir = Path(out_dir) if out_dir is not None else \
        _default_out_dir(run_dir, regression)
    _guard_out_dir(out_dir, baseline_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    routes_path = run_dir / 'routes_l3d.json'
    if not routes_path.exists():
        raise FileNotFoundError('routes_l3d.json not found in run dir: %s'
                                % routes_path)
    baseline_routes_path = baseline_dir / 'routes_l3d.json'
    if not baseline_routes_path.exists():
        raise FileNotFoundError('frozen E5 baseline routes_l3d.json not found: %s'
                                % baseline_routes_path)
    log('=' * 78)
    log('[native3d] validating run_dir=%s' % run_dir)
    log('[native3d] baseline_dir=%s' % baseline_dir)
    log('[native3d] out_dir=%s' % out_dir)

    # -- model -------------------------------------------------------------
    model = _load_model(run_dir, baseline_dir, log)
    planes = model['planes']
    assignment_rows, assignment_by_id, assignment_path, assignment_source = \
        _load_assignment(run_dir, baseline_dir, log)
    baseline_rows = V21._read_csv(baseline_dir / 'assignment_1024.csv')
    baseline_assignment_by_id = {}
    for row in baseline_rows:
        route_id = _parse_int(row.get('route_id'))
        if route_id is not None:
            baseline_assignment_by_id[int(route_id)] = row

    # -- routes ------------------------------------------------------------
    payload, records, routed, failed = _load_routes(routes_path)
    baseline_payload, baseline_records = V21.load_payload(baseline_routes_path)
    log('[routes] %d records (%d routed, %d failed); baseline %d records'
        % (len(records), len(routed), len(failed), len(baseline_records)))
    baseline_by_id = {}
    for record in baseline_records:
        route_id = _parse_int(record.get('route_id'))
        if route_id is not None:
            baseline_by_id[int(route_id)] = record
    endpoints = C.endpoints()
    checks = OrderedDict()

    # -- 0. model ----------------------------------------------------------
    checks['model'] = check_model(planes, model['source'])
    log('[model] violations=%d' % checks['model']['details']['violations'])

    # -- 1. coverage / identity -------------------------------------------
    checks['coverage'] = check_coverage(
        payload, records, routed, failed, baseline_records,
        baseline_assignment_by_id, assignment_by_id)
    log('[coverage] routed=%d identity_mismatches=%d violations=%d'
        % (len(routed), checks['coverage']['details']['identity_field_mismatches'],
           checks['coverage']['details']['violations']))

    # -- 2. structure ------------------------------------------------------
    checks['structure'] = check_structure(routed, model, endpoints)
    log('[structure] routes=%d junctions=%d max_pos_gap=%.3g '
        'max_z_gap=%.3g max_tangent_gap=%.3g violations=%d'
        % (checks['structure']['details']['routes_checked'],
           checks['structure']['details']['junctions_checked'],
           checks['structure']['details']['max_position_gap_mm'],
           checks['structure']['details']['max_z_gap_mm'],
           checks['structure']['details']['max_tangent_gap'],
           checks['structure']['details']['violations']))

    # -- 3. native metadata -----------------------------------------------
    checks['native_metadata'] = check_native_metadata(
        routed, model, assignment_by_id)
    log('[metadata] native=%d mid=%d excursions=%d violations=%d'
        % (checks['native_metadata']['details']['native_routes'],
           checks['native_metadata']['details']['mid_transitions'],
           checks['native_metadata']['details']['excursions'],
           checks['native_metadata']['details']['violations']))

    # -- 4. R15 ------------------------------------------------------------
    checks['radius'] = check_radius(routed)
    log('[radius] flat_arcs=%d transitions=%d min_sampled=%s violations=%d'
        % (checks['radius']['details']['flat_arc_count'],
           checks['radius']['details']['transition_count'],
           checks['radius']['details']['transition_min_sampled_radius'],
           checks['radius']['details']['violations']))

    # -- 5. glass ----------------------------------------------------------
    checks['glass'] = check_glass(routed)
    log('[glass] samples=%d min_margin=%s violations=%d'
        % (checks['glass']['details']['samples'],
           checks['glass']['details']['min_centerline_margin_mm'],
           checks['glass']['details']['violations']))

    # -- 6. true 3D clearance ---------------------------------------------
    checks['clearance'] = check_clearance(
        routed, planes, skip_min_clearance=skip_min_clearance, log=log)
    log('[clearance] min_3d=%s violations=%d'
        % (checks['clearance']['details']['min_3d_clearance_mm'],
           checks['clearance']['details']['violations']))

    # -- 7. ports ----------------------------------------------------------
    checks['ports'] = check_ports(routed, failed, records)
    log('[ports] port_pairs=%d violations=%d'
        % (checks['ports']['details'].get('port_pairs_checked'),
           checks['ports']['details']['violations']))

    # -- 8. crossings ------------------------------------------------------
    checks['crossings'] = check_crossings(routed, planes, assignment_by_id)
    log('[crossings] events=%s pairs=%s violations=%d'
        % (checks['crossings']['details']['totals'].get('crossings'),
           checks['crossings']['details']['totals'].get('crossing_pairs'),
           checks['crossings']['details']['violations']))

    # -- 9. manual frozen routes ------------------------------------------
    checks['manual_frozen'] = check_manual_frozen(
        routed, assignment_by_id, baseline_by_id)
    log('[manual_frozen] %d manual routes, mismatches=%d violations=%d'
        % (checks['manual_frozen']['details']['manual_route_count'],
           checks['manual_frozen']['details']['manual_geometry_mismatch_count'],
           checks['manual_frozen']['details']['violations']))

    # -- 10. synthetic consistency suite ----------------------------------
    synthetic = dict(schema=CONSISTENCY_SCHEMA, tests=[], all_passed=True)
    if not skip_synthetic:
        log('[synthetic] running in-memory consistency tests ...')
        synthetic = _run_synthetic_tests(model, log=log)
        synthetic['schema'] = CONSISTENCY_SCHEMA
    synthetic_violations = []
    for test in synthetic.get('tests') or []:
        if not test.get('passed'):
            synthetic_violations.append(_violation(
                'synthetic', 'synthetic_test_failed',
                detail='%s: %s' % (test.get('name'), test.get('detail'))))
    if synthetic.get('error'):
        synthetic_violations.append(_violation(
            'synthetic', 'synthetic_suite_error',
            detail=str(synthetic.get('error'))))
    synthetic_details = dict(
        tests=len(synthetic.get('tests') or []),
        passed=sum(1 for test in synthetic.get('tests') or []
                   if test.get('passed')),
        failed=sum(1 for test in synthetic.get('tests') or []
                   if not test.get('passed')),
        all_passed=bool(synthetic.get('all_passed')) and not synthetic_violations,
        cases=[dict(name=test.get('name'), passed=test.get('passed'),
                    detail=test.get('detail'))
               for test in (synthetic.get('tests') or [])],
        error=synthetic.get('error'),
    )
    checks['synthetic'] = _finalize_check(
        'synthetic', synthetic_violations, synthetic_details)
    log('[synthetic] %d tests, %d failed'
        % (synthetic_details['tests'], synthetic_details['failed']))

    # -- flatten violations ------------------------------------------------
    all_violations = []
    for name, block in checks.items():
        all_violations.extend(block['violations'])
    violation_kinds = dict(sorted(
        Counter(str(item.get('kind')) for item in all_violations).items()))
    offending = sorted({int(item['route_id']) for item in all_violations
                        if item.get('route_id') is not None
                        and isinstance(item['route_id'], int)})
    counts = _counts_from_checks(records, routed, failed, {
        name: block['details'] for name, block in checks.items()})
    counts['violation_total'] = len(all_violations)
    geometry_violations = sum(
        checks[name]['details']['violations']
        for name in GEOMETRY_CHECKS if name in checks)
    contract_violations = sum(
        checks[name]['details']['violations']
        for name in CONTRACT_CHECKS if name in checks)
    geometry_pass = geometry_violations == 0
    contract_pass = contract_violations == 0
    validation_pass = geometry_pass and contract_pass

    # -- E5 regression -----------------------------------------------------
    regression_block = None
    if regression:
        regression_block = _regression_block(
            counts, checks['clearance']['details'].get('min_3d_clearance_mm'),
            skip_min_clearance)
        regression_violations = []
        for item in regression_block['checks']:
            if item['passed']:
                continue
            regression_violations.append(_violation(
                'regression', 'regression_expectation_failed',
                detail='%s expected=%r actual=%r'
                       % (item.get('name'), item.get('expected'),
                          item.get('actual'))))
        checks['regression'] = _finalize_check(
            'regression', regression_violations,
            dict(expected=dict(E5_EXPECT),
                 checks=regression_block['checks'],
                 passed=bool(regression_block['passed'])))
        if not regression_block['passed']:
            validation_pass = False
            all_violations.extend(regression_violations)
        violation_kinds = dict(sorted(
            Counter(str(item.get('kind')) for item in all_violations).items()))
        offending = sorted({int(item['route_id']) for item in all_violations
                            if item.get('route_id') is not None
                            and isinstance(item['route_id'], int)})

    # -- exit code ---------------------------------------------------------
    counts['violation_total'] = len(all_violations)
    if regression_block is not None and not regression_block['passed']:
        exit_code = 2
    elif not validation_pass:
        exit_code = 1
    else:
        exit_code = 0
    runtime = time.time() - started
    report = dict(
        schema=VALIDATION_SCHEMA,
        validator=VALIDATOR_ID,
        validated_at=_now(),
        mode='e5_regression' if regression else 'native3d',
        run_dir=str(run_dir),
        baseline_dir=str(baseline_dir),
        out_dir=str(out_dir),
        routes_file=str(routes_path),
        routes_file_sha256=_sha256(routes_path),
        baseline_routes_file=str(baseline_routes_path),
        baseline_routes_file_sha256=_sha256(baseline_routes_path),
        assignment_file=str(assignment_path),
        assignment_source=assignment_source,
        layer_planes_file=model.get('path'),
        layer_planes_source=model['source'],
        model=dict(
            source=model['source'],
            path=model.get('path'),
            plane_count=len(planes),
            plane_ids=[int(pid) for pid in model['plane_ids']],
            z_map={str(pid): _round(z) for pid, z in model['z_map'].items()},
            interface_plane_ids=sorted(model['interface_ids']),
            interface_z=model['interface_z'],
            min_pitch_mm=_round(model['min_pitch_mm']),
            pitch_rows=[dict(row) for row in model['pitch_rows']],
            warnings=model.get('warnings', []),
            checks=checks['model']['details'],
        ),
        counts=counts,
        checks=OrderedDict((name, block['details'])
                           for name, block in checks.items()),
        violations=all_violations[:MAX_VIOLATIONS_JSON],
        violation_count=len(all_violations),
        violations_truncated=len(all_violations) > MAX_VIOLATIONS_JSON,
        violation_counts_by_check=dict(sorted(Counter(
            str(item.get('check')) for item in all_violations).items())),
        violation_kinds=violation_kinds,
        offending_route_ids=offending[:MAX_OFFENDING_IDS],
        offending_route_count=len(offending),
        synthetic_consistency=dict(
            schema=CONSISTENCY_SCHEMA,
            generated_at=_now(),
            all_passed=bool(synthetic.get('all_passed')) and not synthetic_violations,
            tests=synthetic.get('tests') or [],
            error=synthetic.get('error'),
        ),
        regression=regression_block,
        geometry_pass=geometry_pass,
        contract_pass=contract_pass,
        validation_pass=validation_pass,
        exit_code=exit_code,
        runtime_seconds=round(runtime, 2),
    )
    validation_out = out_dir / 'validation.json'
    consistency_out = out_dir / 'validator_consistency_tests.json'
    _write_json(validation_out, report)
    _write_json(consistency_out, report['synthetic_consistency'])
    log('')
    log(_summary_text(report))
    log('[native3d] wrote %s' % validation_out)
    log('[native3d] wrote %s' % consistency_out)
    report['validation_file'] = str(validation_out)
    report['consistency_file'] = str(consistency_out)
    return report


# ===========================================================================
# CLI
# ===========================================================================
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Independent validator for the Native-3D (multi-height) '
                    '1024-route experiment.')
    parser.add_argument('--run-dir', default=None,
                        help='run directory with routes_l3d.json '
                             '(default: the E5 baseline in --regression mode, '
                             'else NATIVE_3D_CROSSING_OPT_1024)')
    parser.add_argument('--baseline-dir', default=None,
                        help='frozen E5 baseline directory (read-only)')
    parser.add_argument('--out-dir', default=None,
                        help='output directory for validation.json')
    parser.add_argument('--skip-min-clearance', action='store_true',
                        help='skip the independent minimum-3D-clearance scan')
    parser.add_argument('--regression', action='store_true',
                        help='validate the frozen E5 baseline and require the '
                             'exact acceptance numbers (1024 routed, 2606 '
                             'crossings / 2067 pairs, 0 violations)')
    parser.add_argument('--skip-synthetic', action='store_true',
                        help='skip the in-memory synthetic consistency suite')
    args = parser.parse_args(argv)
    run_dir = args.run_dir
    if args.regression and run_dir is None:
        run_dir = DEFAULT_BASELINE
    try:
        report = validate_run(
            run_dir=run_dir,
            baseline_dir=args.baseline_dir,
            out_dir=args.out_dir,
            skip_min_clearance=args.skip_min_clearance,
            regression=args.regression,
            skip_synthetic=args.skip_synthetic,
            log=lambda message: print(message, flush=True),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print('[native3d] INPUT ERROR: %s: %s'
              % (type(error).__name__, error), file=sys.stderr)
        return 2
    return int(report.get('exit_code', 1))


if __name__ == '__main__':
    sys.exit(main())

