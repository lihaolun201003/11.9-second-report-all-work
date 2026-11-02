# -*- coding: utf-8 -*-
"""ONE full 1024-channel comparison: manual grouping L1-L4 vs the old 15L baseline.

Rules of this round (as instructed)
-----------------------------------
* connection topology: the two ``section2.csv`` files (1024 records, z1 512 + z2 512);
* manual grouping metadata: ``人工分组/z1_z2_manual_u_assignment_v2_640.csv``;
* **L1-L4 execute the manual grouping** (explicitly marked records only, 64 per
  layer), **L5-L15 use the original crossing-lift strategy**;
* unified 150 um layer model: Z1 = 0.0, Z2 = 0.5, L2 = 0.65, L3 = 0.80,
  L4 = 0.95, L5 = 1.10, +0.15 mm per layer up to L15 = 2.60 mm;
* exactly one full run: no parameter sweep, no re-clustering, no new algorithm;
* R = 15 mm / clearance are checked with the existing frozen validator; legal
  design crossings are not violations.

FIXED version (this run)
------------------------
The 256 manual connections no longer reuse the frozen 2D primitives.  For every
manual connection a real, deeply nested R15 U is constructed from its TRUE port
poses (``manual_u_geometry.build_manual_u_geometry``); the old geometry of all
256 manual routes (including the 64 L1 flats) is removed from the world first.
L1 keeps the flat U on z=0; L2/L3/L4 receive real elevation S-curves on the new
U arms and are validated by the frozen 3D world.  Only if all 256 manual U's are
executed does the run continue with the unchanged old strategy on L5-L15.

The frozen campaign layout (``phase2_2d_selected/routes_1024.json``) still
supplies the connection topology and the non-manual routes, but the manual
geometry is NEW, so the comparison is made on the same topology / constraints and
on the common successful route set (the same 992 routed ids are expected).
"""
from __future__ import annotations

import json
import math
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4 import lift_cross as LIFT          # noqa: E402
from four_side_1024.v3c4 import lift_cross_run as LIFT_RUN  # noqa: E402
from four_side_1024.v3c4 import l3d as L3                   # noqa: E402
from four_side_1024.v3c4 import inputs as V3                # noqa: E402
from four_side_1024.manual_c4_adapt import manual_u_geometry as UGEOM  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
V4_ROOT = CAMPAIGN / 'phase2_2d_selected'
BASELINE_DIR = CAMPAIGN / '02_layer_sweep/L15/lift'
#: Fixed-version outputs (the b926212 artifacts under
#: ``MANUAL_GROUP_15L_COMPARISON`` must not be overwritten).
OUT_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_GROUP_15L_COMPARISON_FIXED')
METADATA_CSV = (ROOT / 'manual_z1_router/data/exports/人工分组'
                / 'z1_z2_manual_u_assignment_v2_640.csv')

MANUAL_LAYERS = (1, 2, 3, 4)
LAST_VIOLATION = []
OLD_ALGORITHM_LAYERS = tuple(range(5, 16))
TIME_LIMIT_S = 480.0
MAX_GROUPS = 300
HEIGHTS = [round(0.65 + 0.15 * index, 3) for index in range(14)]  # L2..L15


def log(message):
    print(message, flush=True)


def install_extended_stack_builder():
    """Allow the frozen lifter to build its L2..L15 stack.

    The current ``four_side_1024.l3d.layers.build_stack`` only knows the fixed
    L1-L5 model (``ROUTING_LAYER_IDS = (2, 3, 4, 5)``); the frozen
    ``CrossingLifter`` already passes an explicit heights dict, so this wrapper
    builds the same dataclass with an arbitrary number of routing layers without
    touching the existing module.
    """
    from four_side_1024.l3d import layers as LL

    original = LL.build_stack

    def build_stack(name=None, heights=None, provenance=LL.PROVENANCE_UNCONFIRMED,
                    note=None):
        if heights is None:
            return original(name=name, provenance=provenance, note=note)
        ids = sorted(int(key) for key in heights)
        all_ids = [LL.INTERFACE_LAYER_ID] + ids
        allowed = tuple(all_ids)
        layers = {
            LL.INTERFACE_LAYER_ID: LL.LayerGeometry(
                LL.INTERFACE_LAYER_ID, 'interface', None,
                dict(LL.INTERFACE_ROWS), allowed)}
        for layer_id in ids:
            layers[layer_id] = LL.LayerGeometry(
                layer_id, 'routing', float(heights[layer_id]), {}, allowed)
        stack = LL.LayerStack(
            layers=layers, provenance=provenance,
            note=note or 'exploratory multi-layer stack for the 15L comparison')
        stack.name = name or 'custom'
        max_layer = ids[-1] if ids else LL.INTERFACE_LAYER_ID

        def to_dict():
            return dict(
                schema='four_side_1024_v2_l3d_layer_stack_v1',
                provenance=stack.provenance,
                formal_acceptance_allowed=False,
                note=stack.note,
                interface_layer=LL.INTERFACE_LAYER_ID,
                max_layer=int(max_layer),
                layers={str(layer_id): stack.layers[layer_id].to_dict()
                        for layer_id in sorted(stack.layers)},
                routing_heights_mm={str(layer_id):
                                    float(stack.layers[layer_id].physical_z_mm)
                                    for layer_id in ids})
        stack.to_dict = to_dict
        return stack

    LL.build_stack = build_stack
    return LL


# ---------------------------------------------------------------------------
# manual grouping metadata -> z1 route_id -> layer
# ---------------------------------------------------------------------------
def load_manual_layers():
    import csv
    raw = Path(METADATA_CSV).read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(raw.splitlines()))
    manual = OrderedDict()
    for row in rows:
        if row['input_dataset'] != 'z1':
            continue
        if row['routing_method'] != 'manual_fixed_u':
            continue
        layer_text = (row.get('assigned_layer') or '').strip()
        layer = int(layer_text[1:]) if layer_text.upper().startswith('L') else None
        if layer is None or layer not in MANUAL_LAYERS:
            continue
        manual[int(row['route_id'])] = dict(
            layer=layer, group=(row.get('manual_group') or '').strip() or None,
            order=(row.get('manual_group_order') or '').strip() or None,
            u_pair=(row.get('u_pair') or '').strip() or None)
    return manual


# ---------------------------------------------------------------------------
# manual U construction: TRUE endpoints -> NEW deep/nested R15 U geometry
# ---------------------------------------------------------------------------
def load_manual_connections():
    """The 256 manual z1 same-side U connections with their TRUE port poses."""
    import csv
    layout = json.loads((V4_ROOT / 'routes_1024.json')
                        .read_text(encoding='utf-8'))
    records = {int(record['route_id']): record for record in layout['routes']}
    raw = Path(METADATA_CSV).read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(raw.splitlines()))
    connections = OrderedDict()
    for row in rows:
        if row['input_dataset'] != 'z1':
            continue
        if row['routing_method'] != 'manual_fixed_u':
            continue
        layer_text = (row.get('assigned_layer') or '').strip().upper()
        if not layer_text.startswith('L'):
            continue
        layer = int(layer_text[1:])
        if layer not in MANUAL_LAYERS:
            continue
        route_id = int(row['route_id'])
        record = records.get(route_id)
        if record is None or record.get('status') != 'routed':
            continue
        connections[route_id] = dict(
            route_id=route_id, layer=layer,
            side=row['source_side'], other_side=row['target_side'],
            source=(float(row['source_x_mm']), float(row['source_y_mm'])),
            target=(float(row['target_x_mm']), float(row['target_y_mm'])),
            group=(row.get('manual_group') or '').strip() or None,
            order=(row.get('manual_group_order') or '').strip() or None,
            u_pair=(row.get('u_pair') or '').strip() or None,
            record=record)
    return connections


def _layer_z(lifter, layer_id):
    """Physical z of a manual layer (L1 = z1 interface row, z = 0.0)."""
    layer_id = int(layer_id)
    if layer_id == 1:
        return 0.0
    return float(lifter.stack.z_for_layer(layer_id))


def _arm_requirement(layer_id, layer_z):
    """Smallest straight arm that can host the layer's elevation S-curve."""
    if int(layer_id) == 1:
        return 0.25
    footprint = float(LIFT.transition_geometry(float(layer_z))['footprint_mm'])
    return float(footprint) + 2.0 * LIFT.PORT_MARGIN_MM + 2.0


def _arm_candidates(nesting, arm_requirement, *, step_mm=0.25,
                    board_limit_mm=UGEOM.MAX_DEPTH_MM - UGEOM.PROFILE_RADIUS_MM):
    """U arm lengths to try for one connection, nesting-ordered target first."""
    target = arm_requirement + (nesting['chain_k'] - nesting['contains']) * step_mm
    target = min(max(float(target), 0.25), board_limit_mm)
    values = [round(float(target), 3)]
    for offset in (2.0, 4.0, 8.0, 12.0, -2.0):
        value = round(float(target + offset), 3)
        if value < 0.25 or value > board_limit_mm:
            continue
        if all(abs(value - other) > 1e-6 for other in values):
            values.append(value)
    return values


def _window_candidates(primitives, layer_id, layer_z, lifter, *,
                       step_mm=0.5, plan_limit=40, margin_mm=0.10,
                       window_mode='arms'):
    """Candidate elevation transitions on the NEW manual-U chain.

    ``window_mode='arms'`` : rise on the first straight arm, fall on the last one
    (keeps the U shape: lead-in, climb, elevated arm/bottom/arm, descent, tail).
    ``window_mode='any'``  : also allows the bottom straight, a fallback for U's
    whose arms are blocked.

    Besides the frozen transition-vs-plane test, the low elevation band of each
    S-curve must not contain a crossing point with another route on the interface
    plane (a legal flat/flat crossing becomes an illegal transition/flat conflict
    as soon as the curve rises there).
    """
    paths = LIFT._paths()
    total = paths.path_length(primitives)
    dz = float(layer_z) - 0.0
    footprint = float(LIFT.transition_geometry(dz)['footprint_mm'])
    windows = LIFT._straight_start_windows(primitives, footprint, total)
    if len(windows) < 2:
        return []
    safe = float(lifter.safe_length)
    free_margin = float(LIFT.CROSSING_EXCLUSION_MARGIN_MM)
    # crossing positions on the interface plane z=0 of the new chain
    crossing_positions = []
    try:
        evaluation = lifter.world.planes.evaluate(primitives, 0.0)
        for item in getattr(evaluation, 'crossings', None) or []:
            point = (float(item['x']), float(item['y']))
            crossing_positions.append(
                float(LIFT.position_on_route(primitives, point)))
    except Exception:  # noqa: BLE001
        crossing_positions = []
    crossing_positions.sort()

    def _starts(window):
        low, high = window
        values = []
        value = low
        while value <= high + 1e-9:
            values.append(round(float(value), 6))
            value += step_mm
        values.append(round(float(high), 6))
        return values

    def _plane_clear(start):
        point, direction = paths.path_point_at(primitives, start)
        return lifter._transition_clearance_ok(point, direction, 0.0,
                                               float(layer_z), footprint,
                                               margin=margin_mm)

    def _rise_ok(start):
        if start < LIFT.PORT_MARGIN_MM - 1e-9:
            return False
        if not _plane_clear(start):
            return False
        return LIFT._free_zone(start, start + safe, crossing_positions,
                               free_margin)

    def _fall_ok(start):
        if start + footprint > total - LIFT.PORT_MARGIN_MM + 1e-9:
            return False
        if not _plane_clear(start):
            return False
        return LIFT._free_zone(start + footprint - safe, start + footprint,
                               crossing_positions, free_margin)

    if window_mode == 'arms':
        window_pairs = [(0, len(windows) - 1)]
    else:
        window_pairs = []
        for rise_index, _rise_window in enumerate(windows):
            for fall_index in range(rise_index, len(windows)):
                window_pairs.append((rise_index, fall_index))

    plans = []
    for rise_index, fall_index in window_pairs:
        rise_valid = [start for start in _starts(windows[rise_index])
                      if _rise_ok(start)]
        fall_valid = [start for start in _starts(windows[fall_index])
                      if _fall_ok(start)]
        rise_valid.sort()
        fall_valid.sort(reverse=True)
        for rise_start in rise_valid[:8]:
            for fall_start in fall_valid[:8]:
                if fall_start < rise_start + footprint + LIFT.MIN_TRAVEL_MM:
                    continue
                plans.append(dict(layer_id=int(layer_id),
                                  layer_z=float(layer_z), dz=dz,
                                  footprint=footprint,
                                  rise_start=float(rise_start),
                                  fall_start=float(fall_start),
                                  window_mode=window_mode))
                if len(plans) >= plan_limit:
                    return plans
    return plans[:plan_limit]


def force_manual_route(lifter, rid, layer_id, construction,
                       plan_limit=40):
    """Build & commit ONE manual U from its NEW geometry; never commits illegally.

    Steps (mirrors the requested workflow):
    1. take the freshly built deep U chain (``build_manual_u_geometry``);
    2. search rise/fall S-curve placements on its arms (``_window_candidates``);
    3. build the real 3D route for the target layer (``LIFT.lift_route``);
    4. validate it against the frozen 3D world (``check_route``);
    5. commit only if it is legal; otherwise return the concrete failure reason.
    """
    layer_id = int(layer_id)
    layer_z = _layer_z(lifter, layer_id)
    primitives = [dict(primitive) for primitive in
                  construction['geometry']['primitives']]
    record = construction['connection']['record']
    plan = None
    if layer_id == 1:
        route = LIFT.flat_route(rid, 'z1', primitives, row=1)
    else:
        route = None
        reasons = []
        last_conflict = None
        for window_mode in ('arms', 'any'):
            plans = _window_candidates(primitives, layer_id, layer_z, lifter,
                                       plan_limit=plan_limit,
                                       window_mode=window_mode)
            if not plans:
                reasons.append(f'{window_mode}:no_transition_window')
                continue
            for candidate in plans:
                built = LIFT.lift_route(record, 1, layer_id, layer_z,
                                        candidate['rise_start'],
                                        candidate['fall_start'], primitives)
                if built is None:
                    continue
                if lifter.world.check_structure(built):
                    continue
                violations = lifter.world.check_route(built, check_self=True)
                if violations:
                    last_conflict = violations[0]
                    continue
                route = built
                plan = candidate
                break
            if route is not None:
                break
            reasons.append(f'{window_mode}:all_placements_conflict')
        if route is None:
            note = ''
            if last_conflict:
                note = (f'; blocker={last_conflict.get("kind")}:'
                        f'route{last_conflict.get("other_route")}')
            return None, '+'.join(reasons) + note
    lifter.world.add_route(route)
    lifter.primitives[rid] = primitives
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', primitives, row=1)
    if layer_id == 1:
        lifter.lifted.pop(int(rid), None)
    else:
        lifter.lifted[int(rid)] = route
    return dict(route=route, plan=plan, primitives=primitives,
                arm_mm=float(construction['geometry']['arm_mm']),
                depth_mm=float(construction['geometry']['depth_mm'])), None


def unique_pairs_from_crossings(crossings):
    return {tuple(sorted((int(item[1]), int(item[2])))) for item in crossings}


def breakdown(lifter, routed_planes, group_of, unique_pairs):
    """Split unique crossing pairs by data-source plane and by C4 bundle."""
    by_plane = Counter()
    by_bundle = Counter()
    for first, second in unique_pairs:
        planes = tuple(sorted((routed_planes[first], routed_planes[second])))
        by_plane['x'.join(planes)] += 1
        if group_of.get(first) is not None and \
                group_of.get(first) == group_of.get(second):
            by_bundle['intra_bundle'] += 1
        else:
            by_bundle['inter_bundle'] += 1
    return dict(by_plane=dict(by_plane), by_bundle=dict(by_bundle))


def per_plane_pair_counts(crossings):
    counts = Counter()
    for item in crossings:
        counts[round(float(item[0]), 6)] += 1
    return {str(key): value for key, value in sorted(counts.items())}


def per_plane_unique_pairs(crossings):
    sets = defaultdict(set)
    for item in crossings:
        sets[round(float(item[0]), 6)].add(tuple(sorted((int(item[1]),
                                                         int(item[2])))))
    return {str(key): len(value) for key, value in sorted(sets.items())}


# ---------------------------------------------------------------------------
# baseline breakdown (from the existing 15L artifacts)
# ---------------------------------------------------------------------------
def baseline_metrics():
    summary = json.loads((BASELINE_DIR / 'summary.json')
                         .read_text(encoding='utf-8'))
    after = json.loads((BASELINE_DIR / 'crossings_after.json')
                       .read_text(encoding='utf-8'))
    payload = json.loads((BASELINE_DIR / 'routes_l3d.json')
                         .read_text(encoding='utf-8'))
    records = {int(record['route_id']): record
               for record in payload['routes']}
    routed = {rid: record for rid, record in records.items()
              if record.get('status') == 'routed'}
    routed_planes = {rid: record['plane'] for rid, record in routed.items()}
    geometry = json.loads((V4_ROOT / 'routes_1024.json').read_text(encoding='utf-8'))
    group_of = {}
    for group in geometry['rotation_groups']:
        for rid in group['route_ids']:
            group_of[int(rid)] = int(group['group_id'])
    unique_pairs = {tuple(sorted(pair)) for pair in after['remaining_pairs']}
    return dict(
        routed_ids=sorted(routed),
        label='old 15L baseline (crossing-lift, all layers L2-L15)',
        routed=len(routed), failed=len(records) - len(routed),
        unique_pairs=len(unique_pairs),
        crossing_points=int(after.get('count') or 0),
        per_plane_pairs=after.get('pair_count_by_height'),
        per_plane_unique_pairs=per_plane_unique_pairs(
            [(item['z'], item['route_a'], item['route_b'])
             for item in after.get('crossings') or []]),
        lifted_groups=summary.get('lifted_groups'),
        lifted_routes=summary.get('lifted_routes'),
        transitions=summary.get('transitions'),
        violations=(summary.get('validation_counts') or {}).get('violations'),
        runtime_seconds=summary.get('runtime_seconds'),
        length_total_mm=summary.get('length_total_after_mm'),
        **breakdown(None, routed_planes, group_of, unique_pairs))


# ---------------------------------------------------------------------------
# the single full manual-grouping run
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# manual-U phase: build all 256 connections from the NEW geometry
# ---------------------------------------------------------------------------
def _min_pair_distance(array_a, array_b, chunk=256):
    """Minimum Euclidean distance between two sampled paths (numpy)."""
    import numpy as np
    best = math.inf
    for start in range(0, len(array_a), chunk):
        block = array_a[start:start + chunk]
        deltas = block[:, None, :] - array_b[None, :, :]
        best = min(best, float(np.min(np.hypot(deltas[..., 0],
                                               deltas[..., 1]))))
    return best


def _flat_clearance_on_plane(lifter, z_mm, manual_ids):
    """Exact minimum D56 spacing of every manual route on one physical plane.

    Uses the frozen D56 index directly (same primitives / sagitta / clearance
    rules as the validator) with the route's own parts excluded; the reported
    value is the exact centre-line spacing to the nearest other route.
    """
    from four_side_1024.d56.index import prepare
    entries = lifter.world.planes.parts.get(round(float(z_mm), 9)) or {}
    if not entries:
        return dict(min_clearance_mm=None, pair=None,
                    measure='D56Index min_spacing (exact primitives)')
    index = lifter.world.planes._index(z_mm)
    best = None
    best_pair = None
    for part_id, primitives in entries.items():
        rid = int(part_id) // 1000
        if rid not in manual_ids:
            continue
        exclude = tuple(pid for pid in entries if int(pid) // 1000 == rid)
        try:
            evaluation = index.evaluate(prepare(primitives), exclude=exclude,
                                       stop_on_invalid=False)
        except Exception:  # noqa: BLE001
            continue
        spacing = getattr(evaluation, 'min_spacing_mm', None)
        if spacing is not None and (best is None or spacing < best):
            best = float(spacing)
            best_pair = (rid, None)
    return dict(min_clearance_mm=None if best is None else round(best, 6),
                pair=best_pair,
                measure='D56Index min_spacing (exact primitives)')


def _transition_clearance_to_planes(lifter, results):
    """Minimum true-3D clearance between a manual S-curve and other routes' flats."""
    import numpy as np
    plane_entries = {}
    for z_key, parts in lifter.world.planes.parts.items():
        arrays = []
        ids = []
        for part_id, primitives in parts.items():
            array = UGEOM._sample_xy(primitives, sagitta=0.05)
            if array is not None and len(array) >= 1:
                arrays.append(array)
                ids.append(np.full(len(array), int(part_id) // 1000,
                                   dtype=int))
        if arrays:
            plane_entries[z_key] = (np.vstack(arrays), np.concatenate(ids))
    best = None
    best_info = None
    for outcome in results.values():
        if 'failed' in outcome or int(outcome['layer']) == 1:
            continue
        rid = int(outcome['route_id'])
        route = lifter.lifted.get(rid)
        if route is None:
            continue
        for part in route['parts']:
            if part.get('kind') != 'transition':
                continue
            samples = LIFT_RUN._part_samples(part)
            for sample in samples[::4]:
                x, y, z = float(sample[0]), float(sample[1]), float(sample[2])
                for z_key, (array, ids) in plane_entries.items():
                    if abs(z - z_key) > 2.0:
                        continue
                    keep = ids != rid
                    if not np.any(keep):
                        continue
                    points = array[keep]
                    distance_2d = float(np.min(np.hypot(points[:, 0] - x,
                                                        points[:, 1] - y)))
                    distance_3d = math.hypot(distance_2d, z - z_key)
                    if best is None or distance_3d < best:
                        best = distance_3d
                        best_info = dict(route_id=rid, z_plane=float(z_key),
                                         point=[round(x, 3), round(y, 3),
                                                round(z, 4)])
    return dict(min_clearance_mm=None if best is None else round(float(best), 6),
                info=best_info)


def _layer_stat_rows(phase1):
    rows = OrderedDict()
    for layer in MANUAL_LAYERS:
        layer_rows = phase1['layer_orders'][layer]
        placed = [row for row in layer_rows if 'failed' not in row]
        failed = [row for row in layer_rows if 'failed' in row]
        depths = sorted(row['depth_mm'] for row in placed)
        strict = [row for row in placed
                  if abs(row['arm_mm'] - row['strict_arm_mm']) <= 1e-6]
        rows[layer] = dict(
            layer=int(layer), expected=len(layer_rows), placed=len(placed),
            failed=len(failed),
            depth_min_mm=None if not depths else round(depths[0], 3),
            depth_max_mm=None if not depths else round(depths[-1], 3),
            strict_nesting=len(strict),
            constraint_adjusted=len(placed) - len(strict),
            transitions=sum(1 for row in placed if row['n_transitions'] == 2),
            failures=[dict(route_id=row['route_id'], side=row['side'],
                           reason=row['reason']) for row in failed])
    return rows


def _jsonable_phase1(phase1):
    def _clean(value):
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        if isinstance(value, float):
            return float(value)
        return value
    return _clean(phase1)


def _plot_manual_layers(lifter, connections, phase1):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
    except Exception as error:  # noqa: BLE001
        log(f'[u-fix] matplotlib unavailable: {error}')
        return []
    out = OUT_DIR / 'plots_manual'
    out.mkdir(parents=True, exist_ok=True)
    manual_ids = set(connections)
    context = []
    for rid, record in lifter.routed.items():
        if rid in manual_ids:
            continue
        array = UGEOM._sample_xy(record['primitives'], sagitta=0.05)
        if array is not None:
            context.append(array)
    side_colors = {'N': '#1f6fd6', 'S': '#e07b1a', 'E': '#2f9e44',
                   'W': '#7048e8'}
    produced = []
    paths = LIFT._paths()
    for layer in MANUAL_LAYERS:
        layer_rows = phase1['layer_orders'][layer]
        placed = [row for row in layer_rows if 'failed' not in row]
        failed = [row for row in layer_rows if 'failed' in row]
        fig, ax = plt.subplots(figsize=(8.4, 7.8))
        if context:
            ax.add_collection(LineCollection(
                context, colors='#adb5bd', linewidths=0.12, alpha=0.22,
                zorder=1))
        for row in placed:
            array = UGEOM._sample_xy(row['primitives'], sagitta=0.02)
            if array is None:
                continue
            ax.plot(array[:, 0], array[:, 1],
                    color=side_colors.get(row['side'], '#343a40'),
                    lw=1.15, zorder=3)
            plan = row.get('transition')
            if plan:
                for start in (plan['rise_start'], plan['fall_start']):
                    point, _direction = paths.path_point_at(row['primitives'],
                                                            start)
                    ax.plot(point[0], point[1], marker='v', ms=3.2,
                            color='#e03131', zorder=5)
        for row in failed:
            connection = connections[row['route_id']]
            ax.plot(sum(point[0] for point in (connection['source'],
                                               connection['target'])) / 2.0,
                    sum(point[1] for point in (connection['source'],
                                               connection['target'])) / 2.0,
                    'rx', ms=8, mew=1.8, zorder=6)
        ax.set_xlim(-2, 152)
        ax.set_ylim(-2, 152)
        ax.set_aspect('equal')
        ax.grid(alpha=0.12)
        ax.set_xlabel('x (mm)')
        ax.set_ylabel('y (mm)')
        layer_z = _layer_z(lifter, layer)
        ax.set_title(
            f'manual U layer L{layer}  z={layer_z:.2f} mm  |  '
            f'{len(placed)}/{len(layer_rows)} placed  |  '
            f'new R15 U geometry (not the frozen 2D path)\n'
            f'blue=N, orange=S, green=E, purple=W; grey = frozen other routes; '
            f'red triangles = elevation transition; red x = failed',
            fontsize=8.0)
        fig.tight_layout()
        target = out / f'manual_layer_L{layer}.png'
        fig.savefig(target, dpi=170)
        plt.close(fig)
        produced.append(str(target))
    return produced


def build_manual_us(lifter, connections):
    """Phase 1: remove ALL old manual geometries and build the 256 real U's."""
    started = time.perf_counter()
    manual_ids = set(connections)
    remaining = {rid: route for rid, route in lifter.world.plan.items()
                 if rid not in manual_ids}
    lifter.world.rebuild(remaining)
    lifter.lifted = {rid: route for rid, route in lifter.lifted.items()
                     if rid not in manual_ids}
    log(f'[u-fix] removed the old geometry of all {len(manual_ids)} manual '
        f'routes (including the 64 L1 flats); world now '
        f'{len(lifter.world.plan)} routes')
    results = OrderedDict()
    layer_orders = {layer: [] for layer in MANUAL_LAYERS}
    for layer in MANUAL_LAYERS:
        layer_z = _layer_z(lifter, layer)
        arm_requirement = _arm_requirement(layer, layer_z)
        lifter._refresh_plane_cache()
        for side in UGEOM.SIDE_ORDER:
            side_connections = [connection for connection in connections.values()
                                if connection['layer'] == layer
                                and connection['side'] == side]
            if not side_connections:
                continue
            items = [dict(route_id=connection['route_id'],
                          source=connection['source'],
                          target=connection['target'])
                     for connection in side_connections]
            nesting = UGEOM.nesting_plan(items, arm_min_mm=arm_requirement,
                                         depth_step_mm=0.25)
            ordered = sorted(
                side_connections,
                key=lambda connection: (nesting[connection['route_id']]
                                        ['contains'],
                                        connection['route_id']))
            for connection in ordered:
                rid = connection['route_id']
                row = nesting[rid]
                outcome = None
                last_reason = 'no_candidate_depth'
                for arm_index, arm in enumerate(
                        _arm_candidates(row, arm_requirement)):
                    geometry = UGEOM.build_manual_u_geometry(
                        connection['source'], connection['target'],
                        connection['side'], arm_mm=arm)
                    if not geometry['ok']:
                        last_reason = 'geometry:' + ','.join(geometry['errors'])
                        continue
                    committed, reason = force_manual_route(
                        lifter, rid, layer,
                        dict(connection=connection, geometry=geometry),
                        plan_limit=40 if arm_index == 0 else 20)
                    if committed is None:
                        last_reason = reason
                        continue
                    outcome = dict(
                        route_id=rid, layer=int(layer), side=side,
                        group=connection['group'], order=connection['order'],
                        u_pair=connection['u_pair'],
                        arm_mm=float(committed['arm_mm']),
                        depth_mm=float(committed['depth_mm']),
                        nesting_contains=int(row['contains']),
                        nesting_k=int(row['chain_k']),
                        strict_arm_mm=float(round(
                            arm_requirement
                            + (row['chain_k'] - row['contains']) * 0.25, 3)),
                        transition=committed['plan'],
                        length_mm=float(committed['route'].get('length_mm')
                                        or 0.0),
                        n_transitions=int(committed['route'].get(
                            'n_transitions') or 0),
                        primitives=committed['primitives'])
                    break
                if outcome is None:
                    outcome = dict(route_id=rid, layer=int(layer), side=side,
                                   group=connection['group'],
                                   order=connection['order'],
                                   u_pair=connection['u_pair'], failed=True,
                                   reason=last_reason,
                                   nesting_contains=int(row['contains']),
                                   nesting_k=int(row['chain_k']))
                    # keep the original route only as a diagnostic; it is never
                    # counted as an executed manual layer
                    lifter.world.add_route(lifter.base_routes[rid])
                results[rid] = outcome
                layer_orders[layer].append(outcome)
                if len(layer_orders[layer]) % 8 == 0:
                    placed_now = sum(1 for item in layer_orders[layer]
                                     if 'failed' not in item)
                    log(f'[u-fix] L{layer} progress: {placed_now}/'
                        f'{len(layer_orders[layer])} placed '
                        f'({time.perf_counter() - started:.1f}s)')
            placed = sum(1 for item in layer_orders[layer]
                         if 'failed' not in item)
            log(f'[u-fix] L{layer} {side}: {placed}/'
                f'{len(layer_orders[layer])} placed '
                f'({time.perf_counter() - started:.1f}s)')
    complete = all('failed' not in item for item in results.values())
    return dict(complete=complete, expected=len(connections),
                placed=sum(1 for item in results.values()
                           if 'failed' not in item),
                failed=sum(1 for item in results.values() if 'failed' in item),
                results=results, layer_orders=layer_orders,
                elapsed_seconds=round(time.perf_counter() - started, 1))


def run_manual(lifter, manual_layers, phase1_only=False):
    started = time.perf_counter()
    LIFT.LAYER_IDS = tuple(range(2, 16))
    lifter.analyze()
    log(f'[u-fix] frozen-layout analysis: pairs={len(lifter.pair_set)} '
        f'points={len(lifter.crossings)} '
        f'({time.perf_counter() - started:.1f}s)')
    connections = load_manual_connections()
    log(f'[u-fix] manual U connections loaded from the 640 CSV: '
        f'{len(connections)} (L1-L4)')

    phase1 = build_manual_us(lifter, connections)
    phase1['layer_stats'] = _layer_stat_rows(phase1)
    manual_ids = set(connections)
    phase1['clearances'] = {}
    for layer in MANUAL_LAYERS:
        layer_z = _layer_z(lifter, layer)
        phase1['clearances'][str(layer)] = _flat_clearance_on_plane(
            lifter, layer_z, manual_ids)
    phase1['transition_clearance'] = _transition_clearance_to_planes(
        lifter, phase1['results'])
    figures = _plot_manual_layers(lifter, connections, phase1)
    phase1['figures'] = figures
    LIFT._write_json(OUT_DIR / 'manual_phase1.json',
                     _jsonable_phase1(phase1), indent=1)
    log('')
    log('[u-fix] ===== manual U phase summary =====')
    for layer in MANUAL_LAYERS:
        row = phase1['layer_stats'][layer]
        clearance = phase1['clearances'][str(layer)]
        log(f'[u-fix] L{layer}: placed {row["placed"]}/{row["expected"]}, '
            f'depth {row["depth_min_mm"]}..{row["depth_max_mm"]} mm, '
            f'strict nesting {row["strict_nesting"]}/'
            f'{row["placed"]}, transitions {row["transitions"]}, '
            f'flat min clearance {clearance["min_clearance_mm"]} mm')
    log(f'[u-fix] transition 3D min clearance '
        f'{phase1["transition_clearance"]["min_clearance_mm"]} mm '
        f'({phase1["transition_clearance"]["info"]})')
    log(f'[u-fix] manual phase: {phase1["placed"]}/{phase1["expected"]} '
        f'placed, {phase1["failed"]} failed '
        f'({phase1["elapsed_seconds"]}s)')
    if not phase1['complete']:
        log('[u-fix] manual phase INCOMPLETE -> the full 1024-channel run is '
            'NOT started (per the requested acceptance order)')
        return dict(complete=False, phase1=phase1)
    if phase1_only:
        log('[u-fix] phase-1 only requested: stopping before the full run')
        return dict(complete=True, phase1=phase1, phase1_only=True)
    return _run_old_algorithm(lifter, connections, phase1, started)


def _run_old_algorithm(lifter, connections, phase1, started):
    """Phase 2: the original crossing-lift strategy on L5-L15 (unchanged)."""
    manual_groups = set()
    for rid in connections:
        entry = lifter.route_group.get(int(rid))
        if entry is not None:
            manual_groups.add(int(entry[0]))
    log(f'[u-fix] recomputing the crossing state from the NEW geometry')
    entries = lifter.final_flat_entries()
    crossings, reports, pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=True,
        primitives_by_id=lifter.primitives)
    lifter.crossings = crossings
    lifter.pair_set = set()
    for plane_pairs in pairs.values():
        lifter.pair_set |= plane_pairs
    lifter.high_pairs = lifter._added_pairs({})
    for gid in manual_groups:
        lifter.group_plans[gid] = dict(
            group_id=int(gid), status='manual_fixed_group',
            note='L1-L4 manual U connections (new R15 geometry)')
    log(f'[u-fix] after manual phase: pairs={len(lifter.pair_set)} '
        f'points={len(lifter.crossings)} '
        f'({time.perf_counter() - started:.1f}s)')

    LIFT.LAYER_IDS = tuple(range(5, 16))
    log(f'[u-fix] old algorithm continues on L5-L15 '
        f'(LAYER_IDS={LIFT.LAYER_IDS}, budget {TIME_LIMIT_S:.0f}s, '
        f'max {MAX_GROUPS} groups)')
    history = lifter.optimize(max_groups=MAX_GROUPS, time_limit=TIME_LIMIT_S,
                              log=log)
    log(f'[u-fix] optimizer lifted {len(history)} groups '
        f'({time.perf_counter() - started:.1f}s)')

    payload = lifter.build_payload()
    LIFT._write_json(OUT_DIR / 'routes_l3d.json', payload)
    LIFT._write_json(OUT_DIR / 'layer_stack.json', lifter.stack.to_dict())
    validation = LIFT.validate_payload_v4(payload, lifter.v4_root, log=log)
    repair_rounds = 0
    while not validation.get('exploratory_pass') and repair_rounds < 40:
        violations = validation.get('violations') or []
        offending = set()
        manual_offences = set()
        for item in violations:
            if item.get('category') != 'clearance_violations':
                continue
            for key in ('route_id', 'other_route'):
                value = item.get(key)
                if value is None:
                    continue
                entry = lifter.route_group.get(int(value))
                if entry is None:
                    continue
                gid = int(entry[0])
                if gid in manual_groups:
                    manual_offences.add(gid)
                else:
                    offending.add(gid)
        if not offending:
            log(f'[u-fix] validation violations only in manual groups: '
                f'{sorted(manual_offences)}')
            break
        lifter.revert_groups(offending, log=log)
        repair_rounds += 1
        payload = lifter.build_payload()
        LIFT._write_json(OUT_DIR / 'routes_l3d.json', payload)
        validation = LIFT.validate_payload_v4(payload, lifter.v4_root, log=log)
    if repair_rounds:
        log(f'[u-fix] repair reverted {repair_rounds} round(s) of non-manual '
            f'groups')

    entries = lifter.final_flat_entries()
    after_crossings, after_reports, after_pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=False)
    unique_pairs = set()
    for plane_pairs in after_pairs.values():
        unique_pairs |= plane_pairs
    after_records = [dict(z=float(value[0]), route_a=int(value[1]),
                          route_b=int(value[2]), x=float(value[3]),
                          y=float(value[4]), angle_deg=float(value[7]))
                     for value in after_crossings]
    LIFT._write_json(OUT_DIR / 'crossings_after.json', dict(
        count=len(after_records), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(key): value['crossing_pair_count']
                              for key, value in after_reports.items()},
        point_count_by_height={str(key): value['crossing_count']
                               for key, value in after_reports.items()},
        remaining_pairs=sorted(unique_pairs),
        crossings=after_records), indent=None)

    summary = lifter.summary(validation=validation, after_reports=after_reports,
                             after_pairs_by_plane=after_pairs)
    manual_lifted = sum(1 for row in phase1['results'].values()
                        if 'failed' not in row and int(row['layer']) > 1)
    manual_flat = sum(1 for row in phase1['results'].values()
                      if 'failed' not in row and int(row['layer']) == 1)
    failures = [dict(route_id=row['route_id'], layer=row['layer'],
                     side=row['side'], reason=row['reason'])
                for row in phase1['results'].values() if 'failed' in row]
    summary.update(
        schema='four_side_1024_manual_group_15L_fixed_summary_v1',
        layer_heights_mm={str(int(layer.layer_id)): float(layer.physical_z_mm)
                          for layer in lifter.stack.routing_layers},
        remaining_unique_crossing_pairs=len(unique_pairs),
        crossing_pairs_after_by_plane={str(key): value['crossing_pair_count']
                                       for key, value in after_reports.items()},
        crossing_points_after_by_plane={str(key): value['crossing_count']
                                        for key, value in after_reports.items()},
        manual_grouping=dict(
            manual_records=len(connections),
            manual_layers={str(layer): sum(1 for row in
                                           phase1['results'].values()
                                           if int(row['layer']) == layer)
                           for layer in MANUAL_LAYERS},
            manual_routes_lifted_to_layer=manual_lifted,
            manual_routes_flat_l1=manual_flat,
            manual_routes_failed=len(failures),
            manual_failures=failures,
            manual_groups=len(manual_groups),
            layer_stats=phase1['layer_stats'],
            clearance=phase1['clearances'],
            transition_clearance=phase1['transition_clearance'],
            geometry='new R15 U chains built from the true endpoints '
                     '(build_manual_u_geometry); the frozen 2D paths of the '
                     '256 manual connections were removed first',
            layer_assignment_rule='L1-L4 manual grouping; L5-L15 original '
                                  'strategy'),
        old_algorithm=dict(layer_ids=list(OLD_ALGORITHM_LAYERS),
                           lifted_groups=len(history),
                           time_limit_seconds=TIME_LIMIT_S,
                           max_groups=MAX_GROUPS),
        repair_rounds=repair_rounds,
        elapsed_seconds=round(time.perf_counter() - started, 1),
    )
    LIFT._write_json(OUT_DIR / 'summary.json', summary, indent=1)
    LIFT._write_json(OUT_DIR / 'validation.json', validation, indent=1)
    LIFT._write_json(OUT_DIR / 'lift_plans.json', dict(
        lifted=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'lifted'],
        rejected=[plan for plan in lifter.group_plans.values()
                  if plan.get('status') == 'rejected'],
        reverted=[plan for plan in lifter.group_plans.values()
                  if plan.get('status') == 'reverted'],
        manual=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'manual_fixed_group'],
        history=history), indent=1)
    try:
        figures = LIFT_RUN.plot_all(lifter, payload, summary,
                                    OUT_DIR / 'plots', log=log)
        summary['figures'] = figures
    except Exception as error:  # noqa: BLE001
        log(f'[u-fix] plotting skipped: {error}')
    LIFT._write_json(OUT_DIR / 'summary.json', summary, indent=1)
    return dict(complete=True, lifter=lifter, payload=payload,
                validation=validation, summary=summary,
                unique_pairs=unique_pairs, after_records=after_records,
                history=history, phase1=phase1)


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------
def compare(baseline, result):
    lifter = result['lifter']
    routed_planes = {rid: record['plane'] for rid, record in lifter.routed.items()}
    group_of = {rid: int(entry[0]) for rid, entry in lifter.route_group.items()}
    manual_breakdown = breakdown(lifter, routed_planes, group_of,
                                 result['unique_pairs'])
    summary = result['summary']
    manual = dict(
        label='manual grouping L1-L4 + old strategy L5-L15',
        routed=len(lifter.routed), failed=len(lifter.routes) - len(lifter.routed)
        if hasattr(lifter, 'routes') else sum(1 for rid in lifter.routed
                                              if False),
        unique_pairs=len(result['unique_pairs']),
        crossing_points=len(result['after_records']),
        per_plane_pairs=summary.get('crossing_pairs_after_by_plane'),
        per_plane_unique_pairs=per_plane_unique_pairs(
            [(item['z'], item['route_a'], item['route_b'])
             for item in result['after_records']]),
        lifted_groups=len(result['history']),
        lifted_routes=len(lifter.lifted),
        transitions=sum(int(route.get('n_transitions') or 0)
                        for route in lifter.lifted.values()),
        violations=(summary.get('validation_counts') or {}).get('violations'),
        runtime_seconds=summary.get('elapsed_seconds'),
        length_total_mm=summary.get('length_total_after_mm'),
        **manual_breakdown)
    # routed counts: 32 failed records are the same in both (same 2D layout)
    geometry = json.loads((V4_ROOT / 'routes_1024.json').read_text(encoding='utf-8'))
    all_records = len(geometry['routes'])
    manual['failed'] = all_records - manual['routed']
    delta = manual['unique_pairs'] - baseline['unique_pairs']
    percent = 100.0 * delta / max(1, baseline['unique_pairs'])
    # fairness: compare on the common successful route set
    baseline_ids = set(baseline.get('routed_ids') or [])
    manual_ids = set(lifter.routed)
    common_ids = baseline_ids & manual_ids
    baseline_pairs = {tuple(sorted(pair)) for pair in
                      json.loads((BASELINE_DIR / 'crossings_after.json')
                                 .read_text(encoding='utf-8'))['remaining_pairs']}
    base_common = sum(1 for first, second in baseline_pairs
                      if first in common_ids and second in common_ids)
    manual_common = sum(1 for first, second in result['unique_pairs']
                        if first in common_ids and second in common_ids)
    common_delta = manual_common - base_common
    comparison = dict(
        schema='four_side_1024_manual_group_15L_fixed_comparison_v1',
        baseline=baseline, manual=manual,
        delta_pairs=delta, delta_percent=round(percent, 4),
        routed_sets=dict(
            baseline=baseline['routed'], manual=manual['routed'],
            common=len(common_ids),
            same_routed_set=bool(baseline_ids == manual_ids),
            note=('the automatic routes are the same frozen layout; the 256 '
                  'manual connections use NEW U geometry, so the fair '
                  'comparison is the common successful route set below')),
        common_route_set=dict(
            size=len(common_ids), baseline_pairs=base_common,
            manual_pairs=manual_common, delta_pairs=common_delta,
            delta_percent=round(100.0 * common_delta
                                / max(1, base_common), 4)),
        rules=dict(manual_layers=list(MANUAL_LAYERS),
                   old_algorithm_layers=list(OLD_ALGORITHM_LAYERS),
                   layer_model='Z1=0.0, Z2=0.5, L2=0.65, +0.15 mm per layer, '
                               'L15=2.60 mm',
                   radius_mm=15.0,
                   note='legal design crossings are not violations'),
    )
    LIFT._write_json(OUT_DIR / 'comparison.json', comparison, indent=1)
    md = render_table(comparison)
    (OUT_DIR / 'comparison.md').write_text(md, encoding='utf-8')
    return comparison, md


def _fmt(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.1f}'
    return str(value)


def render_table(comparison):
    b = comparison['baseline']
    m = comparison['manual']
    lines = []
    lines.append('# 人工分组前后（15L）对比表\n')
    lines.append('| 指标 | 原 15L 基线（旧算法，L2–L15） | 人工分组（L1–L4 人工 + L5–L15 旧算法） | 变化 |')
    lines.append('|---|---:|---:|---:|')
    rows = [
        ('布通条数（1024 通道）', f"{b['routed']} / 1024", f"{m['routed']} / 1024",
         f"{m['routed'] - b['routed']:+d}"),
        ('全局唯一交叉对数', f"{b['unique_pairs']}", f"{m['unique_pairs']}",
         f"{comparison['delta_pairs']:+d}（{comparison['delta_percent']:+.2f}%）"),
        ('交叉点总数', f"{b['crossing_points']}", f"{m['crossing_points']}",
         f"{m['crossing_points'] - b['crossing_points']:+d}"),
        ('Z1×Z1 唯一交叉对', f"{b['by_plane'].get('z1xz1', 0)}",
         f"{m['by_plane'].get('z1xz1', 0)}",
         f"{m['by_plane'].get('z1xz1', 0) - b['by_plane'].get('z1xz1', 0):+d}"),
        ('Z2×Z2 唯一交叉对', f"{b['by_plane'].get('z2xz2', 0)}",
         f"{m['by_plane'].get('z2xz2', 0)}",
         f"{m['by_plane'].get('z2xz2', 0) - b['by_plane'].get('z2xz2', 0):+d}"),
        ('Z1×Z2 混合唯一交叉对', f"{b['by_plane'].get('z1xz2', 0)}",
         f"{m['by_plane'].get('z1xz2', 0)}",
         f"{m['by_plane'].get('z1xz2', 0) - b['by_plane'].get('z1xz2', 0):+d}"),
        ('束内（同 C4 组）唯一交叉对', f"{b['by_bundle'].get('intra_bundle', 0)}",
         f"{m['by_bundle'].get('intra_bundle', 0)}",
         f"{m['by_bundle'].get('intra_bundle', 0) - b['by_bundle'].get('intra_bundle', 0):+d}"),
        ('束间唯一交叉对', f"{b['by_bundle'].get('inter_bundle', 0)}",
         f"{m['by_bundle'].get('inter_bundle', 0)}",
         f"{m['by_bundle'].get('inter_bundle', 0) - b['by_bundle'].get('inter_bundle', 0):+d}"),
        ('举升组数 / 抬升路线数', f"{_fmt(b['lifted_groups'])} / {_fmt(b['lifted_routes'])}",
         f"{_fmt(m['lifted_groups'])} / {_fmt(m['lifted_routes'])}", '—'),
        ('升降段数', f"{_fmt(b['transitions'])}", f"{_fmt(m['transitions'])}",
         f"{(m['transitions'] or 0) - (b['transitions'] or 0):+d}"),
        ('验证违规数（R15/净空/同层）', f"{_fmt(b['violations'])}",
         f"{_fmt(m['violations'])}", '—'),
        ('总长度（mm）', _fmt(b['length_total_mm']), _fmt(m['length_total_mm']),
         f"{(m['length_total_mm'] or 0) - (b['length_total_mm'] or 0):+.1f}"),
        ('运行时间（s）', _fmt(b['runtime_seconds']), _fmt(m['runtime_seconds']), '—'),
    ]
    for row in rows:
        lines.append('| ' + ' | '.join(row) + ' |')
    lines.append('')
    lines.append('## 分层逐层交叉对（唯一对 / 交叉点）\n')
    lines.append('| 物理 z (mm) | 层 | 基线 唯一对 / 点 | 人工分组 唯一对 / 点 | 唯一对变化 |')
    lines.append('|---|---|---:|---:|---:|')
    planes = sorted({float(key) for key in b['per_plane_unique_pairs']}
                    | {float(key) for key in m['per_plane_unique_pairs']})
    z_to_layer = {0.0: 'L1(z1)', 0.5: 'L1(z2)', 0.65: 'L2', 0.8: 'L3', 0.95: 'L4'}
    for z in planes:
        key = str(round(z, 6))
        base_pairs = b['per_plane_unique_pairs'].get(key)
        manual_pairs = m['per_plane_unique_pairs'].get(key)
        base_points = (b['per_plane_pairs'] or {}).get(key)
        manual_points = (m['per_plane_pairs'] or {}).get(key)
        layer = z_to_layer.get(round(z, 6), '')
        if not layer and z >= 1.1:
            layer = f'L{int(round((z - 0.55) / 0.15))}'
        delta = ((manual_pairs if manual_pairs is not None else 0)
                 - (base_pairs if base_pairs is not None else 0))
        lines.append(f'| {z:g} | {layer} | {_fmt(base_pairs)} / {_fmt(base_points)} '
                     f'| {_fmt(manual_pairs)} / {_fmt(manual_points)} | {delta:+d} |')
    lines.append('')
    lines.append('说明：全局唯一交叉对 = 同一对线路在所有物理高度上只计一次（与基线 '
                 '`remaining_unique_crossing_pairs` 同一定义）；逐层唯一对之和可能大于'
                 '全局唯一对（同一对可在多层交叉）。合法设计交叉不算违规。')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description='Manual-U fix: 256 real R15 U connections on L1-L4, then '
                    'the unchanged old strategy on L5-L15.')
    parser.add_argument('--phase1-only', action='store_true',
                        help='only build/validate the 256 manual U connections')
    args = parser.parse_args(argv)
    install_extended_stack_builder()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manual_layers = load_manual_layers()
    log(f'[u-fix] manual grouping records (L1-L4): {len(manual_layers)} '
        f'layers={Counter(info["layer"] for info in manual_layers.values())}')
    lifter = LIFT.CrossingLifter(v4_root=V4_ROOT, out_dir=OUT_DIR,
                                 heights=HEIGHTS, log=log)
    result = run_manual(lifter, manual_layers, phase1_only=args.phase1_only)
    if not result.get('complete'):
        log('[u-fix] stopped after the manual phase (not complete)')
        return 0
    if result.get('phase1_only'):
        log(f'[u-fix] phase-1 artifacts: {OUT_DIR}')
        return 0
    baseline = baseline_metrics()
    comparison, md = compare(baseline, result)
    log('')
    log(md)
    log(f'[u-fix] artifacts: {OUT_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
