# -*- coding: utf-8 -*-
"""Build the 444 high-layer Z2 routes as far as the fixed-layer geometry allows.

Interface-plane Z2 routes (68) are audited separately: every frozen z=0.5 path
is tested against the already-fixed Z1 transitions at the real 3D clearance.
"""
import csv, json, sys, time
from collections import Counter, OrderedDict
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


def main():
    M.install_extended_stack_builder(); profile_r15.apply()
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    z1dir = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R4'
    z1_routes = {int(k): v for k, v in json.loads(
        (z1dir / 'z1_all_routes.json').read_text(encoding='utf-8')).items()}
    z1_prims = {int(k): v for k, v in json.loads(
        (z1dir / 'primitives.json').read_text(encoding='utf-8')).items()}
    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    audit = list(csv.DictReader(open(
        ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_20L_FIXED_ASSIGNMENT_FULL/z2_assignment_audit.csv',
        encoding='utf-8-sig')))
    target = {int(row['route_id']): (None if row['target_layer'] == ''
                                     else int(row['target_layer']))
              for row in audit}
    out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_Z2H'
    out.mkdir(parents=True, exist_ok=True)
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out, heights=heights, log=log)
    lifter.world.rebuild({}); lifter.lifted = {}; lifter.primitives = {}; lifter.base_routes = {}
    approx = F3.ApproxClearance(margin=0.003)
    for rid, route in z1_routes.items():
        F3.add_existing_route(lifter, records[rid], 1, route, z1_prims[rid])
        approx.add_route(route)
    log(f'z1 fixed {len(lifter.world.plan)}')

    results = OrderedDict()
    failures = []

    def record_result(rid, ok, layer, reason=None):
        results[rid] = dict(ok=bool(ok), layer=layer, reason=reason)
        if not ok:
            failures.append(dict(route_id=rid, layer=layer, reason=reason))

    def add_high(rid, route, prims):
        F3.add_existing_route(lifter, records[rid], 2, route, prims, fast=None)
        approx.add_route(route)

    # ---- interface-plane audit: frozen 2D paths at z=0.5 -----------------
    interface = [rid for rid, layer in target.items() if layer is None]
    interface_failures = []
    interface_ok = 0
    for rid in sorted(interface):
        record = records[rid]
        prims = record.get('primitives') if record.get('status') == 'routed' else None
        if not prims:
            record_result(rid, False, None, 'no_2d_geometry')
            continue
        route = LIFT.flat_route(rid, 'z2', prims, row=2)
        violations = lifter.world.check_route(route, check_self=False)
        if violations:
            reason = 'z1_transition_conflict:' + str(violations[0].get('kind')) + \
                     ':route' + str(violations[0].get('other_route'))
            record_result(rid, False, None, reason)
            interface_failures.append(dict(route_id=rid, reason=reason,
                                           other=violations[0].get('other_route'),
                                           distance=violations[0].get('distance_mm')))
            continue
        F3.add_existing_route(lifter, record, 2, route, prims)
        approx.add_route(route)
        record_result(rid, True, None)
        interface_ok += 1
    log(f'interface: {interface_ok}/{len(interface)} legal at true 3D clearance')
    print('interface failure reasons',
          Counter(item['reason'].split(':')[0] for item in interface_failures))

    # ---- high layers -----------------------------------------------------
    high = [rid for rid, layer in target.items() if layer is not None]
    high.sort(key=lambda rid: (target[rid], rid))

    def try_prims(record, layer, prims, max_plans):
        target_z = float(lifter.stack.z_for_layer(layer))
        deadline = time.perf_counter() + 2.5
        for plan in F3.transition_plans(prims, target_z, 0.5, mode='all',
                                        window_positions=5,
                                        max_plans=max_plans,
                                        prefer='ends'):
            if time.perf_counter() > deadline:
                break
            route, reason = F3.build_one_plan(lifter, record, 2, prims, layer,
                                              plan, check_plane=True)
            if route is None:
                continue
            if approx.route_conflicts(route):
                continue
            if self_clearance_violations(route, lifter.clearance):
                continue
            return route, prims, plan
        return None, None, None

    def build_high(record, layer):
        rid = int(record['route_id'])
        prims = record.get('primitives') if record.get('status') == 'routed' else None
        if not prims:
            return None, None, 'no_2d_geometry'
        if record['relation'] == 'same':
            route, used, plan = try_prims(record, layer, prims, 30)
            if route is not None:
                return route, used, None
            source = LIFT._endpoint_xy(record['source_endpoint'])
            target_xy = LIFT._endpoint_xy(record['target_endpoint'])
            # fresh deeper R15 U, evaluated by the same fixed-layer search
            target_z = float(lifter.stack.z_for_layer(layer))
            footprint = F3.transition_footprint(abs(target_z - 0.5))
            arm_min = footprint + 2.0 * LIFT.PORT_MARGIN_MM + 2.0
            for offset in (0.0, 3.0, 6.0, 10.0, 15.0, 22.0, 30.0, 40.0):
                geom = F3.build_manual_u_for_layer(
                    source, target_xy, str(record['source_side']),
                    target_z, 0.5)
                if not geom or not geom.get('ok'):
                    continue
                u_prims = [dict(p) for p in geom['primitives']]
                route, used, plan = try_prims(record, layer, u_prims, 30)
                if route is not None:
                    return route, u_prims, None
                break
        route, used, plan = try_prims(record, layer, prims, 50)
        if route is not None:
            return route, used, None
        return None, None, 'no_legal_plan'

    layer_ok = Counter()
    started = time.perf_counter()
    for index, rid in enumerate(high, 1):
        layer = target[rid]
        route, prims, reason = build_high(records[rid], layer)
        if route is None:
            record_result(rid, False, layer, reason)
        else:
            record_result(rid, True, layer)
            add_high(rid, route, prims)
            layer_ok[layer] += 1
        if index % 8 == 0:
            log(f'[z2] {index}/{len(high)} ok={sum(layer_ok.values())} fail={len(failures)} '
                f'({time.perf_counter()-started:.1f}s) by_layer={dict(layer_ok)}')
    log(f'[z2] high done ok={sum(layer_ok.values())}/{len(high)} '
        f'({time.perf_counter()-started:.1f}s) by_layer={dict(layer_ok)}')
    print('failures', Counter(f['reason'].split(':')[0] for f in failures))
    (out / 'routes_20l_partial.json').write_text(json.dumps(
        {str(rid): lifter.lifted[rid] for rid in lifter.lifted}, ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    (out / 'primitives_20l_partial.json').write_text(json.dumps(
        {str(rid): lifter.primitives[rid] for rid in lifter.primitives},
        ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (out / 'z2_build_summary.json').write_text(json.dumps(
        dict(results={str(k): v for k, v in results.items()}, failures=failures,
             interface_failures=interface_failures,
             by_layer=dict(layer_ok),
             interface_ok=interface_ok,
             high_ok=sum(layer_ok.values()),
             elapsed=time.perf_counter()-started), ensure_ascii=False,
        indent=1, default=str), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
