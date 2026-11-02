# -*- coding: utf-8 -*-
"""Finalize the manual-first full run from the saved 2D stage:
manual 256 fixed + 540 auto routes; full frozen validation, global crossing
statistics (2D-plane solution, no further lifting), comparison with the
campaign baseline and the common-route-set fair comparison.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import run_full_campaign as R
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.v3c4 import lift_cross_run as LIFT_RUN

NEW_DIR = R.NEW_DIR
BUDGET = 480.0


def log(message):
    print(message, flush=True)


def main():
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    M.install_extended_stack_builder()
    from four_side_1024.r15 import profile_r15
    profile_r15.apply()
    reroute = json.loads((NEW_DIR / 'reroute_2d.json').read_text(encoding='utf-8'))
    payload = json.loads((R.CAMPAIGN_V4 / 'routes_1024.json')
                         .read_text(encoding='utf-8'))
    records = {int(record['route_id']): record for record in payload['routes']}
    manual_routes, manual_prims = R.load_manual_routes()
    manual_ids = set(manual_routes)
    final_2d = {}
    failures_2d = []
    for plane in ('z1', 'z2'):
        final_2d.update({int(rid): prims
                         for rid, prims in reroute[plane]['routed'].items()})
        failures_2d.extend(reroute[plane]['failures'])
    for rid in manual_ids:
        final_2d.pop(rid, None)
    log(f'[final] manual={len(manual_ids)}, auto={len(final_2d)}, '
        f'failed={len(failures_2d)}')

    lifter = LIFT.CrossingLifter(v4_root=R.CAMPAIGN_V4, out_dir=NEW_DIR,
                                 heights=M.HEIGHTS, log=log)
    failed_ids = {item['route_id'] for item in failures_2d}
    for rid in list(lifter.routed):
        rid = int(rid)
        if rid in failed_ids or (rid not in manual_ids
                                 and rid not in final_2d):
            lifter.routed.pop(rid, None)
    groups = []
    for group in lifter.groups:
        ids = [int(rid) for rid in group['route_ids']]
        if any(rid not in lifter.routed for rid in ids):
            continue
        groups.append(group)
    lifter.groups = groups
    lifter.group_by_id = {int(g['group_id']): g for g in groups}
    lifter.route_group = {}
    for group in groups:
        for phase, rid in enumerate(group['route_ids']):
            lifter.route_group[int(rid)] = (int(group['group_id']), phase)
    manual_groups = set()
    for rid in manual_ids:
        entry = lifter.route_group.get(int(rid))
        if entry is not None:
            manual_groups.add(int(entry[0]))
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    for rid, route in manual_routes.items():
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = [dict(primitive)
                                  for primitive in manual_prims[rid]]
        lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1',
                                                  lifter.primitives[rid], row=1)
    for rid, prims in final_2d.items():
        record = records[rid]
        plane = record['plane']
        flat = LIFT.flat_route(rid, plane, prims,
                               row=1 if plane == 'z1' else 2)
        lifter.world.add_route(flat)
        lifter.primitives[rid] = [dict(primitive) for primitive in prims]
        lifter.base_routes[rid] = flat
    for gid in manual_groups:
        lifter.group_plans[gid] = dict(group_id=int(gid),
                                       status='manual_fixed_group',
                                       note='manual U L1-L4 fixed')
    # pop any routed id without base geometry (defensive)
    for rid in list(lifter.routed):
        if int(rid) not in lifter.base_routes:
            lifter.routed.pop(int(rid), None)
    log(f'[final] 3D world: total={len(lifter.world.plan)}, '
        f'routed={len(lifter.routed)}, manual groups={len(manual_groups)}')

    # make the routed/lifted bookkeeping consistent for all built routes
    for rid in lifter.base_routes:
        record = records[int(rid)]
        lifter.routed.setdefault(int(rid), record)
        lifter.row.setdefault(int(rid),
                              1 if record['plane'] == 'z1' else 2)
    # mark records consistently with the manual-first routed set
    for rid in lifter.base_routes:
        if int(rid) in lifter.records:
            lifter.records[int(rid)]['status'] = 'routed'
    for rid in failed_ids:
        if int(rid) in lifter.records:
            lifter.records[int(rid)]['status'] = 'failed'
            lifter.records[int(rid)]['reason'] = 'manual_first_unrouted'
    # try the L5-L15 crossing lift with a short bounded budget
    entries = lifter.final_flat_entries()
    crossings, reports, pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=True,
        primitives_by_id=lifter.primitives)
    lifter.crossings = crossings
    lifter.pair_set = set()
    for plane_pairs in pairs.values():
        lifter.pair_set |= plane_pairs
    lifter.high_pairs = lifter._added_pairs({})
    lifter._finalize_analysis()
    log(f'[final] 2D-plane pairs={len(lifter.pair_set)}')
    LIFT.LAYER_IDS = tuple(range(5, 16))
    history = lifter.optimize(max_groups=300, time_limit=BUDGET, log=log)
    log(f'[final] optimizer lifted {len(history)} groups')
    payload_out = lifter.build_payload()
    LIFT._write_json(NEW_DIR / 'routes_l3d.json', payload_out)
    LIFT._write_json(NEW_DIR / 'layer_stack.json', lifter.stack.to_dict())
    validation = LIFT.validate_payload_v4(payload_out, lifter.v4_root, log=log)
    log(f'[final] validation={validation.get("status")} '
        f'counts={validation.get("counts")}')
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
    LIFT._write_json(NEW_DIR / 'crossings_after.json', dict(
        count=len(after_records), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(key): value['crossing_pair_count']
                              for key, value in after_reports.items()},
        point_count_by_height={str(key): value['crossing_count']
                               for key, value in after_reports.items()},
        remaining_pairs=sorted(unique_pairs), crossings=after_records),
        indent=None)
    routed_by_plane = Counter()
    for rid in lifter.routed:
        routed_by_plane[lifter.routed[rid]['plane']] += 1
    summary = lifter.summary(validation=validation,
                             after_reports=after_reports,
                             after_pairs_by_plane=after_pairs)
    summary.update(
        schema='manual_first_full_final_v1',
        layer_heights_mm={str(int(layer.layer_id)):
                          float(layer.physical_z_mm)
                          for layer in lifter.stack.routing_layers},
        remaining_unique_crossing_pairs=len(unique_pairs),
        crossing_pairs_after_by_plane={
            str(key): value['crossing_pair_count']
            for key, value in after_reports.items()},
        crossing_points_after_by_plane={
            str(key): value['crossing_count']
            for key, value in after_reports.items()},
        manual_fixed=dict(routes=len(manual_ids),
                          all_kept=all(rid in lifter.lifted
                                       or rid in lifter.base_routes
                                       for rid in manual_ids)),
        reroute=dict(z1_routed=len(reroute['z1']['routed']),
                     z1_failed=len(reroute['z1']['failures']),
                     z2_routed=len(reroute['z2']['routed']),
                     z2_failed=len(reroute['z2']['failures'])),
        failed_connections=failures_2d,
        routed_by_plane=dict(routed_by_plane),
        lifted_groups=len(history),
        elapsed_seconds=summary.get('runtime_seconds'))
    LIFT._write_json(NEW_DIR / 'summary.json', summary, indent=1)
    LIFT._write_json(NEW_DIR / 'validation.json', validation, indent=1)
    LIFT._write_json(NEW_DIR / 'lift_plans.json', dict(
        lifted=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'lifted'],
        manual=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'manual_fixed_group'],
        history=history), indent=1)
    try:
        LIFT_RUN.plot_all(lifter, payload_out, summary, NEW_DIR / 'plots',
                          log=log)
    except Exception as error:  # noqa: BLE001
        log(f'[final] plot_all skipped: {error}')

    baseline = M.baseline_metrics()
    result = dict(lifter=lifter, unique_pairs=unique_pairs,
                  after_records=after_records, history=history,
                  summary=summary)
    comparison, md = M.compare(baseline, result)
    (NEW_DIR / 'comparison.md').write_text(md, encoding='utf-8')
    log('')
    log(md)
    log(f'[final] artifacts: {NEW_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
