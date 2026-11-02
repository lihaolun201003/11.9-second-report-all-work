# -*- coding: utf-8 -*-
"""Rebuild the Z1 routes implicated in the validator's 100 violations.

The first approximate pass accepted 512 routes but the independent validator
found 67 transition-vs-flat clearance and 33 same-height flat conflicts.  This
script removes every route involved, rebuilds it with the same-height D56 check
enabled and a tighter approximate 3D certificate, and re-runs the real
validator.  It never changes endpoints or target layers.
"""
import json, sys, time
from pathlib import Path
ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import fixed_layer_3d as F3
from four_side_1024.manual_c4_adapt.manual_20l_assignment import layer_stack_payload
from four_side_1024.manual_c4_adapt.run_full_campaign import CampaignState, CAMPAIGN_V4
from four_side_1024.r15 import profile_r15
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.v2opt import search as SEARCH
from four_side_1024.d56.index import prepare
from four_side_1024.fsd25d.world25d import self_clearance_violations
from four_side_1024.l3d import validate_l3d as V


def log(m): print(m, flush=True)


def add_route(lifter, approx, state, records, rid, route, prims, row=1):
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in prims]
    lifter.base_routes[rid] = LIFT.flat_route(rid, records[rid]['plane'], prims, row=row)
    approx.add_route(route)
    # z=0 flat obstacles for 2D candidate generation
    for index, part in enumerate(route.get('parts') or []):
        if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
            continue
        prepared = prepare([dict(p) for p in part['primitives']])
        oid = int(rid) * 1000 + index
        state.index.add(oid, prepared)
        state.oracles.add(oid, prepared)


def build_route(lifter, approx, state, record, layer, prims,
                max_plans=120, check_plane=True):
    rid = int(record['route_id'])
    target_z = float(lifter.stack.z_for_layer(layer))
    plans = F3.transition_plans(prims, target_z, 0.0, mode='all',
                                window_positions=6, max_plans=max_plans)
    for plan in plans:
        route, reason = F3.build_one_plan(lifter, record, 1, prims, layer,
                                          plan, check_plane=check_plane)
        if route is None:
            continue
        if approx.route_conflicts(route):
            continue
        if self_clearance_violations(route, lifter.clearance):
            continue
        return route, prims, plan, None
    return None, None, None, 'no_legal_plan'


def rebuild_one(lifter, approx, state, records, rid, max_candidates=50):
    record = records[rid]
    sides = {record['source_side'], record['target_side']}
    layer = 7 if sides == {'N', 'S'} else 8
    route, prims, plan, reason = build_route(
        lifter, approx, state, record, layer, record['primitives'])
    if route is not None:
        return route, prims, 'frozen', None
    frame = state.frames.get(rid)
    if frame is None:
        return None, None, None, 'no_frame'
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
        route, prims, plan, reason = build_route(
            lifter, approx, state, record, layer, world, max_plans=80)
        if route is not None:
            return route, prims, f'alternative:{candidate.get("family")}', None
    return None, None, None, reason or 'no_candidate'


def run_validator(routes, prims, records, src):
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=src,
                                 heights=heights, log=lambda *a, **k: None)
    for record in lifter.records.values():
        if record['plane'] == 'z2':
            record['status'] = 'failed'
            record['reason'] = 'not_built_yet'
    lifter.lifted = {rid: routes[rid] for rid in routes}
    lifter.primitives = {rid: [dict(p) for p in prims[rid]] for rid in routes}
    lifter.world.rebuild({})
    lifter.base_routes = {rid: LIFT.flat_route(rid, 'z1', prims[rid], row=1)
                          for rid in routes}
    payload = lifter.build_payload()
    payload['layer_stack'] = layer_stack_payload()
    identity = {'available': True, 'error': None, 'planes': {}}
    raw = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    from four_side_1024.v3c4.inputs import ENDPOINTS
    for plane in ('z1', 'z2'):
        rr = {}
        for record in raw['routes']:
            if record.get('plane') != plane:
                continue
            rid = int(record['route_id'])
            rr[rid] = dict(route_id=rid,
                           source_endpoint=record['source_endpoint'],
                           target_endpoint=record['target_endpoint'],
                           source_side=record['source_side'],
                           target_side=record['target_side'],
                           source_row=int(record['source_row']),
                           target_row=int(record['target_row']),
                           relation=record['relation'], pair=record['pair'])
        identity['planes'][plane] = {'routes': rr, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity
    return V.validate_payload(payload, allow_exploratory=True)


def main():
    M.install_extended_stack_builder(); profile_r15.apply()
    V.set_routing_layer_ids(range(2, 21))
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO'
    proto = json.loads((out / 'manual_routes.json').read_text(encoding='utf-8'))
    manual = {int(k): v for k, v in proto['routes'].items()}
    manual_prims = {int(k): v for k, v in proto['primitives'].items()}
    c5dir = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5'
    c5 = json.loads((c5dir / 'z1_all_routes.json').read_text(encoding='utf-8'))
    c5_ids = set(int(k) for k in c5)
    src = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R2'
    all_routes = {int(k): v for k, v in json.loads(
        (src / 'z1_all_routes.json').read_text(encoding='utf-8')).items()}
    all_prims = {int(k): v for k, v in json.loads(
        (src / 'primitives.json').read_text(encoding='utf-8')).items()}
    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    # routes to rebuild: all repaired ones + all validator clearance routes
    repair_ids = (set(all_routes) - c5_ids) | {131, 210}
    repair_ids |= {16, 143, 168, 217, 452, 477, 479}
    # also all same-plane participants where one side is a repaired route
    repair_ids &= set(all_routes)
    log(f'rebuild set: {len(repair_ids)}')
    # build reduced world
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=src,
                                 heights=heights, log=log)
    keep = {rid: all_routes[rid] for rid in all_routes if rid not in repair_ids}
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    lifter.world.rebuild({})
    for rid in keep:
        add_route(lifter, F3.ApproxClearance(), None, records, rid,
                  keep[rid], all_prims[rid]) if False else None
    # rebuild world once with kept routes
    lifter.world.rebuild({rid: keep[rid] for rid in keep})
    for rid in keep:
        lifter.lifted[rid] = keep[rid]
        lifter.primitives[rid] = [dict(p) for p in all_prims[rid]]
        lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', all_prims[rid], row=1)
    approx = F3.ApproxClearance()
    for rid in keep:
        approx.add_route(keep[rid])
    log(f'kept {len(keep)} routes; approx points={len(approx.transition_points)}')
    # state with z=0 obstacles of kept routes
    state = CampaignState(payload, 'z1', log=log)
    for rid in keep:
        for index, part in enumerate(keep[rid].get('parts') or []):
            if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
                continue
            prepared = prepare([dict(p) for p in part['primitives']])
            state.index.add(int(rid) * 1000 + index, prepared)
            state.oracles.add(int(rid) * 1000 + index, prepared)
    log('state ready')
    rebuilt = []
    still = []
    t0 = time.perf_counter()
    for rid in sorted(repair_ids):
        route, prims, how, reason = rebuild_one(
            lifter, approx, state, records, rid, max_candidates=60)
        if route is None:
            still.append((rid, reason))
            log(f'FAIL {rid}: {reason}')
            continue
        add_route(lifter, approx, state, records, rid, route, prims)
        rebuilt.append((rid, how))
        log(f'rebuilt {rid} ({how}) ({time.perf_counter()-t0:.1f}s)')
    log(f'rebuilt {len(rebuilt)} still {len(still)} ({time.perf_counter()-t0:.1f}s)')
    print('still', still)
    out2 = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R3'
    out2.mkdir(parents=True, exist_ok=True)
    (out2 / 'z1_all_routes.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.lifted.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out2 / 'primitives.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.primitives.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    log('running validator')
    report = run_validator(lifter.lifted, lifter.primitives, records, out2)
    (out2 / 'validation_z1.json').write_text(json.dumps(report, ensure_ascii=False,
                                                        indent=1, default=str),
                                             encoding='utf-8')
    log(f'validator status={report.get("status")} counts={report.get("counts")}')


if __name__ == '__main__':
    main()
