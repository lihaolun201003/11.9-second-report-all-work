# -*- coding: utf-8 -*-
"""Targeted repair of routes 210 and its blocker 131."""
import json, sys
from pathlib import Path
ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import fixed_layer_3d as F3
from four_side_1024.manual_c4_adapt.run_full_campaign import CAMPAIGN_V4
from four_side_1024.r15 import profile_r15
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.fsd25d.world25d import self_clearance_violations

M.install_extended_stack_builder(); profile_r15.apply()
heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO'
proto = json.loads((out / 'manual_routes.json').read_text(encoding='utf-8'))
manual = {int(k): v for k, v in proto['routes'].items()}
manual_prims = {int(k): v for k, v in proto['primitives'].items()}
c5dir = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R'
c5 = json.loads((c5dir / 'z1_all_routes.json').read_text(encoding='utf-8'))
c5_routes = {int(k): v for k, v in c5.items()}
c5_prims = {int(k): v for k, v in json.loads((c5dir / 'primitives.json').read_text(encoding='utf-8')).items()}
payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
records = {int(r['route_id']): r for r in payload['routes']}
lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out, heights=heights, log=print)
lifter.world.rebuild({}); lifter.lifted = {}; lifter.primitives = {}; lifter.base_routes = {}

def add(rid, route, prims):
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in prims]
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', prims, row=1)

for rid, route in manual.items():
    add(rid, route, manual_prims[rid])
for rid, route in c5_routes.items():
    if rid in manual: continue
    add(rid, route, records[rid]['primitives'])

def rebuild_approx(exclude):
    approx = F3.ApproxClearance()
    for rid, route in lifter.lifted.items():
        if rid not in exclude:
            approx.add_route(route)
    return approx

# 1. remove 131
lifter.world.remove_route(131)
route131 = lifter.lifted.pop(131)
prims131 = lifter.primitives.pop(131)
lifter.base_routes.pop(131, None)
approx = rebuild_approx({131, 210})
print('removed 131; base routes', len(lifter.world.plan))

# 2. add frozen 210 as temporary flat obstacle
temp210 = LIFT.flat_route(210, 'z1', records[210]['primitives'], row=1)
lifter.world.add_route(temp210)
approx.add_route(temp210)
print('added temp 210 flat')

# 3. find a 131 route legal against temp210
target_z = 1.4
plans = F3.transition_plans(records[131]['primitives'], target_z, 0.0,
                            mode='all', window_positions=6, max_plans=200)
chosen = None
for plan in plans:
    r, reason = F3.build_one_plan(lifter, records[131], 1,
                                  records[131]['primitives'], 7, plan,
                                  check_plane=True)
    if r is None: continue
    conf = approx.route_conflicts(r)
    if conf: continue
    if self_clearance_violations(r, lifter.clearance): continue
    chosen = (r, plan); break
print('chosen 131', bool(chosen), chosen[1] if chosen else None)
if chosen is None:
    print('could not re-lift 131'); sys.exit(1)
# remove temp210, add new 131
lifter.world.remove_route(210)
# remove temp210 from approx by rebuild
approx = rebuild_approx({131, 210})
r131, plan131 = chosen
add(131, r131, records[131]['primitives'])
approx.add_route(r131)
print('re-added 131')

# 4. build 210 using candidates & frozen path
def try_route210(prims):
    for plan in F3.transition_plans(prims, 1.55, 0.0, mode='all',
                                    window_positions=6, max_plans=200):
        r, reason = F3.build_one_plan(lifter, records[210], 1, prims, 8,
                                      plan, check_plane=True)
        if r is None: continue
        if approx.route_conflicts(r): continue
        if self_clearance_violations(r, lifter.clearance): continue
        return r, plan
    return None, None

route210, plan210 = try_route210(records[210]['primitives'])
print('route 210 frozen success', bool(route210), plan210)
if route210 is None:
    # alternative 2D candidates
    from four_side_1024.manual_c4_adapt.run_full_campaign import CampaignState
    from four_side_1024.v2opt import search as SEARCH
    from four_side_1024.d56.index import prepare
    state = CampaignState(payload, 'z1', log=print)
    for rid, route in lifter.lifted.items():
        for index, part in enumerate(route.get('parts') or []):
            if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9: continue
            prepared = prepare([dict(p) for p in part['primitives']])
            oid = rid * 1000 + index
            state.index.add(oid, prepared); state.oracles.add(oid, prepared)
    frame = state.frames[210]; oracle = state.oracle_for(210)
    for count, cand in enumerate(SEARCH.candidates_for(frame, oracle)):
        if count >= 50: break
        world = frame.to_world(cand['primitives'])
        route210, plan210 = try_route210(world)
        if route210 is not None:
            print('alternative success at candidate', count, cand.get('family'))
            break
if route210 is not None:
    add(210, route210, records[210]['primitives'])
    approx.add_route(route210)
    print('repaired 210!')
else:
    print('210 still failed')

# save
out2 = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R2'
out2.mkdir(parents=True, exist_ok=True)
(out2 / 'z1_all_routes.json').write_text(json.dumps({str(k): v for k, v in lifter.lifted.items()},
    ensure_ascii=False, indent=1, default=str), encoding='utf-8')
(out2 / 'primitives.json').write_text(json.dumps({str(k): v for k, v in lifter.primitives.items()},
    ensure_ascii=False, indent=1, default=str), encoding='utf-8')
print('total', len(lifter.lifted))
