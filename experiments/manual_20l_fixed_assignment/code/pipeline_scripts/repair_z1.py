# -*- coding: utf-8 -*-
"""Repair the Z1 opposite routes that have no legal lift on the frozen path."""
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


def log(m): print(m, flush=True)


def add_world_route(lifter, approx, records, rid, route, primitives, row=1):
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in primitives]
    lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1', primitives, row=row)
    approx.add_route(route)


def add_state_obstacles(state, route):
    for index, part in enumerate(route.get('parts') or []):
        if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
            continue
        obstacle_id = int(route['route_id']) * 1000 + index
        prepared = prepare([dict(p) for p in part['primitives']])
        state.index.add(obstacle_id, prepared)
        state.oracles.add(obstacle_id, prepared)


def try_candidate(state, lifter, approx, record, layer, primitives,
                  max_candidates=12, max_plans=80):
    rid = int(record['route_id'])
    if state.index.evaluate(prepare(primitives)).valid is False:
        return None, None, 'candidate_2d_conflict'
    target_z = float(lifter.stack.z_for_layer(layer))
    plans = F3.transition_plans(primitives, target_z,
                                0.0 if record['plane'] == 'z1' else 0.5,
                                mode='all', window_positions=6,
                                max_plans=max_plans)
    for plan in plans:
        route, reason = F3.build_one_plan(lifter, record, 1, primitives,
                                          layer, plan, check_plane=False)
        if route is None:
            continue
        conflict = approx.route_conflicts(route)
        if conflict:
            continue
        if self_clearance_violations(route, lifter.clearance):
            continue
        return route, primitives, None
    return None, None, 'no_lift_plan'


def main():
    M.install_extended_stack_builder(); profile_r15.apply()
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO'
    proto = json.loads((out / 'manual_routes.json').read_text(encoding='utf-8'))
    manual = {int(k): v for k, v in proto['routes'].items()}
    manual_prims = {int(k): v for k, v in proto['primitives'].items()}
    c5dir = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5'
    c5 = json.loads((c5dir / 'z1_all_routes.json').read_text(encoding='utf-8'))
    c5_routes = {int(k): v for k, v in c5.items()}
    c5_prims = {int(k): v for k, v in json.loads(
        (c5dir / 'primitives.json').read_text(encoding='utf-8')).items()}
    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out,
                                 heights=heights, log=log)
    lifter.world.rebuild({}); lifter.lifted = {}; lifter.primitives = {}; lifter.base_routes = {}
    approx = F3.ApproxClearance()
    for rid, route in manual.items():
        add_world_route(lifter, approx, records, rid, route, manual_prims[rid])
    for rid, route in c5_routes.items():
        if rid in manual:
            continue
        add_world_route(lifter, approx, records, rid, route,
                        c5_prims.get(rid) or records[rid]['primitives'])
    log(f'loaded world={len(lifter.world.plan)} accepted={len(c5_routes)}')
    accepted_ids = set(c5_routes) | set(manual)
    failed = []
    for record in payload['routes']:
        if record.get('plane') != 'z1' or record.get('relation') != 'opposite':
            continue
        rid = int(record['route_id'])
        if rid not in accepted_ids:
            failed.append(rid)
    log(f'failed opposite routes: {len(failed)}')
    # build a 2D state with every accepted route's z=0 flats as obstacles
    state = CampaignState(payload, 'z1', log=log)
    for rid in accepted_ids:
        route = lifter.lifted[rid]
        add_state_obstacles(state, route)
    log(f'state obstacles added; index={len(state.accepted)} oracles')
    repaired = []
    still = []
    t0 = time.perf_counter()
    for rid in failed:
        record = records[rid]
        sides = {record['source_side'], record['target_side']}
        layer = 7 if sides == {'N', 'S'} else 8
        frame = state.frames.get(rid)
        if frame is None:
            still.append((rid, 'no_frame')); continue
        oracle = state.oracle_for(rid)
        route = None; prims = None; reason = 'no_candidate'
        for count, candidate in enumerate(SEARCH.candidates_for(frame, oracle)):
            if count >= 40:
                break
            try:
                world_prims = frame.to_world(candidate['primitives'])
            except Exception:
                continue
            route, prims, reason = try_candidate(
                state, lifter, approx, record, layer, world_prims,
                max_plans=80)
            if route is not None:
                break
        if route is None:
            still.append((rid, reason))
            log(f'FAIL repair route {rid}: {reason}')
            continue
        add_world_route(lifter, approx, records, rid, route, prims)
        add_state_obstacles(state, route)
        repaired.append(rid)
        log(f'repaired {rid} -> L{layer} ({time.perf_counter()-t0:.1f}s)')
    log(f'repaired {len(repaired)}; still {len(still)} ({time.perf_counter()-t0:.1f}s)')
    print('still', still)
    out2 = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R'
    out2.mkdir(parents=True, exist_ok=True)
    (out2 / 'z1_all_routes.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.lifted.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out2 / 'primitives.json').write_text(json.dumps(
        {str(k): v for k, v in lifter.primitives.items()}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out2 / 'summary.json').write_text(json.dumps(
        dict(repaired=repaired, still=still), indent=1, default=str))


if __name__ == '__main__':
    main()
