# -*- coding: utf-8 -*-
"""Final Z1 repair pass: rebuild marginal/incomplete routes with a safety margin."""
import json, sys, time
from pathlib import Path
ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import fixed_layer_3d as F3
from four_side_1024.manual_c4_adapt.run_full_campaign import CampaignState, CAMPAIGN_V4
from four_side_1024.r15 import profile_r15
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.v2opt import search as SEARCH
from four_side_1024.d56.index import prepare
from four_side_1024.fsd25d.world25d import self_clearance_violations

M.install_extended_stack_builder(); profile_r15.apply()
heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
src = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R3'
all_routes = {int(k): v for k, v in json.loads((src / 'z1_all_routes.json').read_text(encoding='utf-8')).items()}
all_prims = {int(k): v for k, v in json.loads((src / 'primitives.json').read_text(encoding='utf-8')).items()}
payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
records = {int(r['route_id']): r for r in payload['routes']}
repair_ids = {27, 32, 169, 143, 210, 218}
keep = {rid: all_routes[rid] for rid in all_routes if rid not in repair_ids}
print('keep', len(keep), 'repair', sorted(repair_ids))
lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=src, heights=heights, log=print)
lifter.world.rebuild({rid: keep[rid] for rid in keep})
lifter.lifted = {}; lifter.primitives = {}; lifter.base_routes = {}
for rid in keep:
    lifter.lifted[rid] = keep[rid]
    lifter.primitives[rid] = [dict(p) for p in all_prims[rid]]
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', all_prims[rid], row=1)
approx = F3.ApproxClearance(margin=0.015)
for rid in keep:
    approx.add_route(keep[rid])
print('approx ready')
state = CampaignState(payload, 'z1', log=print)
for rid in keep:
    for index, part in enumerate(keep[rid].get('parts') or []):
        if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
            continue
        prepared = prepare([dict(p) for p in part['primitives']])
        state.index.add(rid * 1000 + index, prepared)
        state.oracles.add(rid * 1000 + index, prepared)
print('state ready')


def add(rid, route, prims):
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in prims]
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', prims, row=1)
    approx.add_route(route)
    for index, part in enumerate(route.get('parts') or []):
        if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
            continue
        prepared = prepare([dict(p) for p in part['primitives']])
        state.index.add(rid * 1000 + index, prepared)
        state.oracles.add(rid * 1000 + index, prepared)


def build(record, layer, prims, max_plans=200):
    target_z = float(lifter.stack.z_for_layer(layer))
    for plan in F3.transition_plans(prims, target_z, 0.0, mode='all',
                                    window_positions=7, max_plans=max_plans):
        route, reason = F3.build_one_plan(lifter, record, 1, prims, layer,
                                          plan, check_plane=True)
        if route is None:
            continue
        if approx.route_conflicts(route):
            continue
        if self_clearance_violations(route, lifter.clearance):
            continue
        return route, prims, plan
    return None, None, None


def rebuild(rid, max_candidates=200):
    record = records[rid]
    sides = {record['source_side'], record['target_side']}
    layer = 7 if sides == {'N', 'S'} else 8
    route, prims, plan = build(record, layer, record['primitives'])
    if route is not None:
        return route, prims, 'frozen', plan
    frame = state.frames.get(rid)
    if frame is None:
        return None, None, 'no_frame', None
    oracle = state.oracle_for(rid)
    for count, candidate in enumerate(SEARCH.candidates_for(frame, oracle)):
        if count >= max_candidates:
            break
        try:
            world = frame.to_world(candidate['primitives'])
        except Exception:
            continue
        if not state.index.evaluate(prepare(world)).valid:
            continue
        route, prims, plan = build(record, layer, world, max_plans=120)
        if route is not None:
            return route, prims, f'alternative:{candidate.get("family")}', plan
    return None, None, 'no_legal', None


rebuilt = []
still = []
t0 = time.perf_counter()
for rid in sorted(repair_ids):
    route, prims, how, plan = rebuild(rid)
    if route is None:
        still.append(rid)
        print('FAIL', rid)
        continue
    add(rid, route, prims)
    rebuilt.append(rid)
    print('rebuilt', rid, how, plan['rise_start'], plan['fall_start'],
          f'{time.perf_counter()-t0:.1f}s')
print('rebuilt', rebuilt, 'still', still)
out2 = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R4'
out2.mkdir(parents=True, exist_ok=True)
(out2 / 'z1_all_routes.json').write_text(json.dumps(
    {str(k): v for k, v in lifter.lifted.items()}, ensure_ascii=False,
    indent=1, default=str), encoding='utf-8')
(out2 / 'primitives.json').write_text(json.dumps(
    {str(k): v for k, v in lifter.primitives.items()}, ensure_ascii=False,
    indent=1, default=str), encoding='utf-8')
print('total', len(lifter.lifted))
