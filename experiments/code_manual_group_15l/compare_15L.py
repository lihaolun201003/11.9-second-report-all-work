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

The 2D layout is the frozen campaign layout
(``phase2_2d_selected/routes_1024.json``, 992/1024 routed), i.e. both the baseline
and this run use the **same routed set and the same 2D geometry**; only the 3D
layer assignment differs.  That makes the comparison fair by construction.
"""
from __future__ import annotations

import json
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

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
V4_ROOT = CAMPAIGN / 'phase2_2d_selected'
BASELINE_DIR = CAMPAIGN / '02_layer_sweep/L15/lift'
OUT_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_GROUP_15L_COMPARISON')
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
# one manual route: choose the elevation transition placement for its layer
# ---------------------------------------------------------------------------
def _window_candidates(lifter, rid, layer_id, plan_limit=40, step_mm=0.5):
    """Ordered candidate transition placements for one manual route / one layer.

    Mirrors the frozen campaign rules: the rise/fall *safe zones* must not contain
    any same-plane crossing point of this route (``_free_zone``), the placement
    must be inside a straight window, and the transition must clear the planes it
    crosses.  Plans are ranked by the same-plane crossings they remove and by how
    short the interface-plane lead-ins stay.
    """
    primitives = lifter.primitives[rid]
    paths = LIFT._paths()
    total = paths.path_length(primitives)
    row = lifter.row[rid]
    base_z = LIFT.row_z(row)
    layer_z = float(lifter.stack.z_for_layer(layer_id))
    dz = layer_z - base_z
    footprint = float(LIFT.transition_geometry(dz)['footprint_mm'])
    windows = LIFT._straight_start_windows(primitives, footprint, total)
    if not windows:
        return []
    positions = sorted(LIFT._position_of(entry, rid)
                       for entry in lifter.crossings
                       if entry[1] == rid or entry[2] == rid)
    margin = LIFT.CROSSING_EXCLUSION_MARGIN_MM
    safe = lifter.safe_length
    prefilter_margin = 0.10

    starts = set()
    for low, high in windows:
        value = low
        while value <= high + 1e-9:
            starts.add(round(float(value), 6))
            value += step_mm
        starts.add(round(float(high), 6))
        for position in positions:
            for candidate in (position - footprint - margin,
                              position + margin,
                              position - safe - margin,
                              position - footprint + safe + margin):
                if low - 1e-9 <= candidate <= high + 1e-9:
                    starts.add(round(float(candidate), 6))
    ordered = sorted(starts)
    if len(ordered) > 240:
        stride = max(1, len(ordered) // 240)
        ordered = ordered[::stride][:240]

    def _plane_clear(start):
        point, direction = paths.path_point_at(primitives, start)
        return lifter._transition_clearance_ok(point, direction, base_z,
                                               layer_z, footprint,
                                               margin=prefilter_margin)

    rise_valid = []
    fall_valid = []
    for start in ordered:
        if not LIFT._inside_window(start, windows):
            continue
        if LIFT._free_zone(start, start + safe, positions, margin) and _plane_clear(start):
            rise_valid.append(start)
        if (start + footprint <= total - LIFT.PORT_MARGIN_MM + 1e-9
                and LIFT._free_zone(start + footprint - safe,
                                    start + footprint, positions, margin)
                and _plane_clear(start)):
            fall_valid.append(start)
    plans = []
    for rise_start in rise_valid:
        rise_end = rise_start + footprint
        for fall_start in fall_valid:
            if fall_start < rise_end + LIFT.MIN_TRAVEL_MM:
                continue
            low = rise_start + safe + margin
            high = fall_start + footprint - safe - margin
            if high <= low:
                continue
            removed = (bisect_left(positions, high)
                       - bisect_right(positions, low))
            interface_length = rise_start + (total - fall_start - footprint)
            plans.append(dict(layer_id=int(layer_id), layer_z=layer_z, dz=dz,
                              footprint=footprint, rise_start=float(rise_start),
                              fall_start=float(fall_start),
                              removed_crossings=int(removed),
                              interface_length_mm=float(interface_length)))
    plans.sort(key=lambda item: (-item['removed_crossings'],
                                 item['interface_length_mm'],
                                 item['rise_start']))
    return plans[:plan_limit]


def force_manual_route(lifter, rid, layer_id):
    """Lift ONE manually assigned route to its mandated layer (no group atomicity).

    The manual grouping splits every C4 quartet 2+2 across two layers, so the
    original group-atomic lift cannot express it; each record is lifted on its own
    2D chain while the C4 partners keep their own (possibly different) layer.
    """
    record = lifter.routed[rid]
    row = lifter.row[rid]
    # the transition-vs-plane clearance test reads the cached physical planes;
    # refresh it from the CURRENT world before searching placements
    lifter._refresh_plane_cache()
    plans = _window_candidates(lifter, rid, layer_id)
    if not plans:
        return None, 'no_transition_window'
    primitives = lifter.primitives[rid]
    safe = lifter.safe_length
    last_reject = 'no_plan'
    for plan in plans:
        route = LIFT.lift_route(record, row, plan['layer_id'], plan['layer_z'],
                                plan['rise_start'], plan['fall_start'],
                                primitives)
        if route is None:
            last_reject = 'lift_route_none'
            continue
        span = LIFT.route_elevated_span_stored(route, record, safe)
        if span is None:
            last_reject = 'no_high_span'
            continue
        # transition clearance against the CURRENT physical planes
        point_a, dir_a = LIFT._paths().path_point_at(primitives,
                                                     plan['rise_start'])
        point_b, dir_b = LIFT._paths().path_point_at(primitives,
                                                     plan['fall_start'])
        if not lifter._transition_clearance_ok(point_a, dir_a,
                                               LIFT.row_z(row), plan['layer_z'],
                                               plan['footprint'],
                                               margin=0.10):
            last_reject = 'transition_clearance_rise'
            continue
        if not lifter._transition_clearance_ok(point_b, dir_b,
                                               LIFT.row_z(row), plan['layer_z'],
                                               plan['footprint'],
                                               margin=0.10):
            last_reject = 'transition_clearance_fall'
            continue
        # true 3D world check against the current layout
        violations = lifter.world.check_route(route, check_self=True)
        if violations:
            last_reject = f'world:{violations[0].get("kind")}'
            LAST_VIOLATION.clear()
            LAST_VIOLATION.append(violations[:2])
            continue
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        return dict(rid=rid, layer_id=int(layer_id),
                    layer_z_mm=round(float(plan['layer_z']), 6),
                    rise_start_mm=round(float(plan['rise_start']), 4),
                    fall_start_mm=round(float(plan['fall_start']), 4),
                    footprint_mm=round(float(plan['footprint']), 4),
                    removed_crossings=int(plan['removed_crossings']),
                    high_span_mm=[round(float(value), 4) for value in span]), None
    return None, last_reject


# ---------------------------------------------------------------------------
# crossings helpers
# ---------------------------------------------------------------------------
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
def run_manual(lifter, manual_layers):
    started = time.perf_counter()
    LIFT.LAYER_IDS = tuple(range(2, 16))
    lifter.analyze()
    log(f'[manual] base analysis: pairs={len(lifter.pair_set)} '
        f'points={len(lifter.crossings)} ({time.perf_counter() - started:.1f}s)')

    # classify the manual records
    targets = OrderedDict()
    flat = OrderedDict()
    missing = []
    for rid, info in manual_layers.items():
        if rid not in lifter.routed:
            missing.append(rid)
            continue
        if info['layer'] == 1:
            flat[rid] = info
        else:
            targets[rid] = info
    log(f'[manual] manual records: {len(manual_layers)} '
        f'(lift {len(targets)}, flat L1 {len(flat)}, not routed {len(missing)})')

    manual_groups = set()
    for rid in list(targets) + list(flat):
        manual_groups.add(int(lifter.route_group[rid][0]))

    lifted = {}
    failures = []
    if targets:
        lifter._drop_base_routes(sorted(targets))
        for index, (rid, info) in enumerate(sorted(targets.items()), 1):
            outcome, reason = force_manual_route(lifter, rid, info['layer'])
            if outcome is None:
                failures.append(dict(rid=rid, layer=info['layer'], reason=reason))
                lifter.world.add_route(lifter.base_routes[rid])
                log(f'[manual] route {rid} -> L{info["layer"]} FAILED ({reason}), '
                    f'kept flat')
            else:
                outcome['uid'] = f'z1:{rid}'
                outcome['manual_group'] = info['group']
                outcome['manual_group_order'] = info['order']
                lifted[rid] = outcome
            if index % 32 == 0:
                inserted = len(lifted)
                log(f'[manual] {index}/{len(targets)} manual lifts processed '
                    f'({inserted} inserted, {len(failures)} failed, '
                    f'{time.perf_counter() - started:.1f}s)')

    # recompute the crossing bookkeeping from the real current geometry
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
            note='L1-L4 manual grouping (records lifted individually as C2 pairs)')
    log(f'[manual] after manual lifts: pairs={len(lifter.pair_set)} '
        f'points={len(lifter.crossings)} ({time.perf_counter() - started:.1f}s)')

    # L5-L15: unchanged original strategy
    LIFT.LAYER_IDS = tuple(range(5, 16))
    log(f'[manual] old algorithm continues on L5-L15 '
        f'(LAYER_IDS={LIFT.LAYER_IDS}, budget {TIME_LIMIT_S:.0f}s, '
        f'max {MAX_GROUPS} groups)')
    history = lifter.optimize(max_groups=MAX_GROUPS, time_limit=TIME_LIMIT_S,
                              log=log)
    log(f'[manual] optimizer lifted {len(history)} groups '
        f'({time.perf_counter() - started:.1f}s)')

    payload = lifter.build_payload()
    LIFT._write_json(OUT_DIR / 'routes_l3d.json', payload)
    LIFT._write_json(OUT_DIR / 'layer_stack.json', lifter.stack.to_dict())
    validation = LIFT.validate_payload_v4(payload, lifter.v4_root, log=log)

    # frozen repair loop: revert NON-manual groups only (manual ones are mandated)
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
            log(f'[manual] validation failed with only manual-group offences: '
                f'{sorted(manual_offences)}')
            break
        lifter.revert_groups(offending, log=log)
        repair_rounds += 1
        payload = lifter.build_payload()
        LIFT._write_json(OUT_DIR / 'routes_l3d.json', payload)
        validation = LIFT.validate_payload_v4(payload, lifter.v4_root, log=log)
    if repair_rounds:
        log(f'[manual] repair reverted {repair_rounds} round(s) of non-manual groups')

    # final exact crossing statistics (same code path as the baseline)
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
    summary.update(
        schema='four_side_1024_manual_group_15L_summary_v1',
        layer_heights_mm={str(int(layer.layer_id)): float(layer.physical_z_mm)
                          for layer in lifter.stack.routing_layers},
        remaining_unique_crossing_pairs=len(unique_pairs),
        crossing_pairs_after_by_plane={str(key): value['crossing_pair_count']
                                       for key, value in after_reports.items()},
        crossing_points_after_by_plane={str(key): value['crossing_count']
                                        for key, value in after_reports.items()},
        manual_grouping=dict(
            manual_records=len(manual_layers),
            manual_layers={str(layer): sum(1 for info in manual_layers.values()
                                           if info['layer'] == layer)
                           for layer in MANUAL_LAYERS},
            manual_routes_lifted=len(lifted),
            manual_routes_kept_flat_l1=len(flat),
            manual_routes_failed=len(failures),
            manual_failures=failures,
            manual_groups=len(manual_groups),
            layer_assignment_rule='L1-L4 manual grouping; L5-L15 original strategy'),
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
    LIFT._write_json(OUT_DIR / 'manual_records.json', dict(lifted=lifted,
                                                           failures=failures))
    try:
        figures = LIFT_RUN.plot_all(lifter, payload, summary,
                                    OUT_DIR / 'plots', log=log)
        summary['figures'] = figures
    except Exception as error:  # noqa: BLE001
        log(f'[manual] plotting skipped: {error}')
    LIFT._write_json(OUT_DIR / 'summary.json', summary, indent=1)
    return dict(lifter=lifter, payload=payload, validation=validation,
                summary=summary, unique_pairs=unique_pairs,
                after_records=after_records, history=history)


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
    comparison = dict(
        schema='four_side_1024_manual_group_15L_comparison_v1',
        baseline=baseline, manual=manual,
        delta_pairs=delta, delta_percent=round(percent, 4),
        routed_sets=dict(
            baseline=baseline['routed'], manual=manual['routed'],
            same_routed_set=True,
            note=('both runs use the identical frozen 2D layout '
                  '(phase2_2d_selected/routes_1024.json): same 992 routed '
                  'connections, same 2D geometry; only the 3D layer assignment '
                  'differs, so the comparison is already on the identical route '
                  'set')),
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
    planes = sorted({float(key) for key in list(b['per_plane_unique_pairs'])
                     | list(m['per_plane_unique_pairs'])})
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
def main():
    install_extended_stack_builder()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manual_layers = load_manual_layers()
    log(f'[manual] manual grouping records (L1-L4): {len(manual_layers)} '
        f'layers={Counter(info["layer"] for info in manual_layers.values())}')
    lifter = LIFT.CrossingLifter(v4_root=V4_ROOT, out_dir=OUT_DIR,
                                 heights=HEIGHTS, log=log)
    result = run_manual(lifter, manual_layers)
    baseline = baseline_metrics()
    comparison, md = compare(baseline, result)
    log('')
    log(md)
    log(f'[manual] artifacts: {OUT_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
