# -*- coding: utf-8 -*-
"""Integration check: optimized manual U + Z2 interface + L7/L8 opposite routes.

This is the final step requested by the U-depth experiment: take the better
legal A/B scheme, keep the 256 optimized manual U's, add the Z2 interface
routes that coexist, then try to restore the Z1 L7/L8 opposite-side routes
without changing their assigned layers.  Local S-transition/XY adjustments are
allowed; failures are recorded, never hidden.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import fixed_layer_3d as F3
from four_side_1024.manual_c4_adapt import manual_20l_assignment as A
from four_side_1024.manual_c4_adapt import u_depth_transition_optimizer as OPT
from four_side_1024.manual_c4_adapt.run_full_campaign import CAMPAIGN_V4
from four_side_1024.v3c4 import lift_cross as LIFT

OUT = OPT.OUT / 'integration_L7_L8'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')


def log(message):
    print(message, flush=True)


def make_interface_flat(record):
    return LIFT.flat_route(int(record['route_id']), 'z2',
                           record['primitives'], row=2)


def main(experiment='A', out_dir=OUT):
    M.install_extended_stack_builder()
    from four_side_1024.r15 import profile_r15
    profile_r15.apply()
    exp_name = ('experiment_A_fixed_depth' if experiment == 'A'
                else 'experiment_B_adaptive_depth')
    exp_dir = OPT.OUT / exp_name
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ck = OPT.CKPT
    u_routes = {int(k): v for k, v in read_json(exp_dir / 'u_routes.json').items()}
    u_prims = {int(k): v for k, v in read_json(exp_dir / 'u_primitives.json').items()}
    z2_results = read_json(exp_dir / 'z2_results.json')
    z2_ok = set(int(x) for x in z2_results.get('results', {})
                if z2_results['results'][str(x)].get('ok')) if False else set()
    # z2_results has results keyed by strings; get successful ids
    z2_ok = {int(rid) for rid, row in (z2_results.get('results') or {}).items()
             if row.get('ok')}
    records = read_json(CAMPAIGN_V4 / 'routes_1024.json')
    records = {int(r['route_id']): r for r in records['routes']}
    checklist = read_json(ck / 'z1/z1_all_routes.json')
    checklist = {int(k): v for k, v in checklist.items()}
    u_ids = set(u_routes)
    log(f'[{experiment}] optimized U={len(u_routes)} Z2 interface ok={len(z2_ok)}')
    lifter = OPT.build_lifter(out_dir)
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    for rid in sorted(u_routes):
        lifter.world.add_route(u_routes[rid])
        lifter.lifted[rid] = u_routes[rid]
        lifter.primitives[rid] = [dict(p) for p in u_prims[rid]]
        lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1',
                                                  u_prims[rid], row=1)
    for rid in sorted(z2_ok):
        prims = [dict(p) for p in records[rid]['primitives']]
        route = make_interface_flat(records[rid])
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = prims
        lifter.base_routes[rid] = route
    log(f'world before L7/L8: {len(lifter.world.plan)} routes')
    # ---- add L7/L8 one by one (existing validated routes; direct check) ---
    l7l8 = []
    for rid, route in checklist.items():
        if rid in u_ids:
            continue
        layer_seq = route.get('layer_sequence') or []
        if len(layer_seq) < 2 or int(layer_seq[1]) not in (7, 8):
            continue
        l7l8.append((int(layer_seq[1]), rid))
    l7l8.sort()
    log(f'L7/L8 candidates: {len(l7l8)}')
    results = OrderedDict()
    started = time.perf_counter()
    for index, (layer, rid) in enumerate(l7l8, 1):
        record = records[rid]
        prims = record.get('primitives') or []
        route = None
        reason = None
        if prims:
            existing = checklist.get(rid) or route
            violations = lifter.world.check_route(existing, check_self=False)
            if not violations:
                lifter.world.add_route(existing)
                lifter.lifted[rid] = existing
                lifter.primitives[rid] = [dict(p) for p in prims]
                lifter.base_routes[rid] = existing
                route = existing
                reason = None
            else:
                route = None
                reason = 'flat_or_transition:' + str(
                    violations[0].get('kind')) + ':route' + str(
                    violations[0].get('other_route'))
        else:
            reason = 'no_2d_geometry'
        results[rid] = dict(route_id=rid, layer=layer, ok=route is not None,
                            reason=None if route else reason)
        if index % 10 == 0:
            ok = sum(1 for row in results.values() if row['ok'])
            log(f'[{experiment}] L7/L8 progress {index}/{len(l7l8)} ok={ok} '
                f'({time.perf_counter()-started:.0f}s)')
    log(f'[{experiment}] L7/L8 success '
        f'{sum(1 for row in results.values() if row["ok"])}/{len(l7l8)}')
    # ---- retest all 48 interface routes against U + L7/L8 --------------
    from four_side_1024.l3d.world import World
    test = OPT.build_lifter(out_dir)
    test.world.rebuild({})
    for rid in sorted(u_routes):
        test.world.add_route(u_routes[rid])
    for rid, row in results.items():
        if not row['ok']:
            continue
        test.world.add_route(lifter.lifted[rid])
    interface_ids = OPT.load_records_and_interface()[1]
    z2_after = {}
    for rid in interface_ids:
        flat = make_interface_flat(records[rid])
        violations = test.world.check_route(flat, check_self=False)
        z2_after[rid] = dict(
            ok=not violations,
            reason=None if not violations else violations[0].get('kind'),
            other_route=None if not violations else violations[0].get('other_route'))
    log(f'[{experiment}] Z2 interface after L7/L8: '
        f'{sum(1 for row in z2_after.values() if row["ok"])}/{len(interface_ids)}')
    # ---- final validation payload -------------------------------------
    final_routes = dict(u_routes)
    final_prims = dict(u_prims)
    for rid in z2_ok:
        if z2_after[rid]['ok']:
            final_routes[rid] = make_interface_flat(records[rid])
            final_prims[rid] = [dict(p) for p in records[rid]['primitives']]
    for rid, row in results.items():
        if row['ok']:
            final_routes[rid] = lifter.lifted[rid]
            final_prims[rid] = [dict(p) for p in records[rid]['primitives']]
    report = OPT.validate_route_subset(final_routes, final_prims, records,
                                       out_dir / 'validation.json')
    write_json(out_dir / 'l7_l8_results.json', dict(
        total=len(l7l8),
        ok=sum(1 for row in results.values() if row['ok']),
        failed=sum(1 for row in results.values() if not row['ok']),
        results=results))
    write_json(out_dir / 'z2_results.json', dict(
        before=len(z2_ok), after=sum(1 for row in z2_after.values() if row['ok']),
        total=len(interface_ids), results={
            str(rid): dict(ok=row['ok'], reason=row['reason'],
                           other_route=row['other_route'])
            for rid, row in z2_after.items()}))
    write_json(out_dir / 'summary.json', dict(
        experiment=experiment, z2_before=len(z2_ok),
        z2_after=sum(1 for row in z2_after.values() if row['ok']),
        l7_l8_ok=sum(1 for row in results.values() if row['ok']),
        l7_l8_total=len(l7l8),
        validation_status=report.get('status'),
        validation_geometry_pass=report.get('geometry_pass'),
        validation_counts=report.get('counts')))
    write_json(out_dir / 'routes.json', {str(rid): final_routes[rid]
                                         for rid in final_routes})
    write_json(out_dir / 'primitives.json', {str(rid): final_prims[rid]
                                             for rid in final_prims})
    log(f'[{experiment}] integration DONE z2_after='
        f'{sum(1 for row in z2_after.values() if row["ok"])}/48, '
        f'L7/L8={sum(1 for row in results.values() if row["ok"])}/{len(l7l8)}, '
        f'validation={report.get("status")}')
    return out_dir


if __name__ == '__main__':
    exp = sys.argv[1] if len(sys.argv) > 1 else 'A'
    main(exp)
