# -*- coding: utf-8 -*-
"""Fast Phase C using ApproxClearance (first 32 routes test)."""
import json, sys, time, collections
from pathlib import Path
ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import fixed_layer_3d as F3
from four_side_1024.manual_c4_adapt.run_full_campaign import CAMPAIGN_V4
from four_side_1024.r15 import profile_r15
from four_side_1024.v3c4 import lift_cross as LIFT


def log(m): print(m, flush=True)


def try_plan(lifter, approx, record, layer, plan):
    route, reason = F3.build_one_plan(lifter, record, 1, record['primitives'],
                                      layer, plan)
    if route is None:
        return None, reason
    conflict = approx.route_conflicts(route)
    if conflict:
        return None, 'approx:' + str(conflict[0]['kind'])
    from four_side_1024.fsd25d.world25d import self_clearance_violations
    if self_clearance_violations(route, lifter.clearance):
        return None, 'self'
    # commit (world is only for compatibility; approx is authoritative here)
    rid = int(record['route_id'])
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in record['primitives']]
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', record['primitives'], row=1)
    approx.add_route(route)
    return route, None


def main():
    M.install_extended_stack_builder(); profile_r15.apply()
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO'
    proto = json.loads((out / 'manual_routes.json').read_text(encoding='utf-8'))
    manual_routes = {int(k): v for k, v in proto['routes'].items()}
    manual_prims = {int(k): v for k, v in proto['primitives'].items()}
    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out, heights=heights, log=log)
    lifter.world.rebuild({}); lifter.lifted = {}; lifter.primitives = {}; lifter.base_routes = {}
    approx = F3.ApproxClearance()
    for rid, route in manual_routes.items():
        F3.add_existing_route(lifter, records[rid], 1, route, manual_prims[rid], fast=None)
        approx.add_route(route)
    log(f'manual added; polylines {len(approx.transition_polylines)}')
    rows = []
    for record in payload['routes']:
        if record.get('plane') != 'z1' or record.get('relation') != 'opposite':
            continue
        sides = {record['source_side'], record['target_side']}
        rows.append((7 if sides == {'N', 'S'} else 8, int(record['route_id'])))
    rows.sort()
    slacks = [(20, 20), (15, 20), (20, 15), (25, 20), (20, 25), (12, 18),
              (18, 12), (30, 20), (20, 30), (10, 20), (20, 10), (40, 20),
              (20, 40), (14, 14), (8, 18), (18, 8)]
    stats = collections.Counter(); fails = []
    t0 = time.perf_counter()
    for layer, rid in rows:
        record = records[rid]
        total = F3.path_length(record['primitives'])
        fp = F3.transition_footprint(1.4 if layer == 7 else 1.55)
        plans = F3.transition_plans(record['primitives'],
                                    1.4 if layer == 7 else 1.55, 0.0,
                                    mode='all', window_positions=6,
                                    max_plans=200)
        route = None; reason = None
        for plan in plans:
            route, reason = try_plan(lifter, approx, record, layer, plan)
            if route is not None:
                break
        if route is not None:
            stats[layer] += 1
        else:
            fails.append((rid, layer, reason))
        if sum(stats.values()) + len(fails) in (8, 16, 24, 32):
            log(f'{sum(stats.values())+len(fails)} attempted ok={sum(stats.values())} '
                f'fail={len(fails)} {time.perf_counter()-t0:.1f}s')
    log(f'done {dict(stats)} fails={len(fails)} {time.perf_counter()-t0:.1f}s')
    print('fails', fails)
    out2 = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5'
    out2.mkdir(parents=True, exist_ok=True)
    (out2 / 'z1_all_routes.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.lifted.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out2 / 'primitives.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.primitives.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out2 / 'summary.json').write_text(json.dumps(
        dict(stats=dict(stats), failures=fails,
             elapsed=time.perf_counter()-t0), indent=1, default=str))


if __name__ == '__main__':
    main()
