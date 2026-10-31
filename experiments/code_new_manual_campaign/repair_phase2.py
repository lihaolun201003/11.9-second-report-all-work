# -*- coding: utf-8 -*-
"""Repair the failed phase-2 C4 groups with an extended same-side U bulge family.

Loads the best per-plane routed layout, re-commits it into the frozen layout state,
then re-attempts only the failed C4 groups with:
  * a much denser same-side U bulge ladder (0.25 mm steps over the whole board),
  * a large candidate budget for the normal-frame groups.
Any group that becomes legal is committed; the resulting plane payload is saved.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import audit2d  # noqa: E402
from four_side_1024.v3c4 import validate2d  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402
from four_side_1024.fslw import config as C  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def extended_ladder():
    values = [round(0.25 * index, 3) for index in range(0, 561)]
    values += [120.5, 121.0, 122.5, 125.0, 130.0, 135.0, 140.0]
    return values


def repair_plane(plane, source_routes, out_dir, budget=20000, log=print):
    started = time.perf_counter()
    from four_side_1024.d56.index import prepare
    from four_side_1024.d56.search import RouteResult
    payload = json.loads(Path(source_routes).read_text(encoding='utf-8'))
    records = payload['routes']
    routed = [dict(r) for r in records if r.get('status') == 'routed']
    failed = [dict(r) for r in records if r.get('status') != 'routed']
    state = state_for(plane, log=lambda message: None)
    loaded = 0
    load_failed = []
    for record in routed:
        rid = int(record['route_id'])
        try:
            prims = [dict(primitive) for primitive in record['primitives']]
            prepared = prepare(prims)
        except Exception as exc:  # noqa: BLE001
            load_failed.append(dict(route_id=rid, error=repr(exc)))
            continue
        state.index.add(rid, prepared)
        state.accepted[rid] = RouteResult(
            rid, record.get('family') or 'HISTORY',
            dict(record.get('params') or {}), prims, prepared,
            float(record.get('length_mm') or 0.0), 0, 0,
            int(record.get('bend_count') or 0))
        loaded += 1
    groups = CONN.groups_for_plane(plane)
    router = ManualGroupRouter(state, groups, log=lambda message: None)
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = extended_ladder()
    recovered = []
    still_failed = []
    try:
        for record in failed:
            rid = int(record['route_id'])
            gid = None
            group = None
            for candidate in groups:
                if rid in [int(x) for x in candidate['route_ids']]:
                    group = candidate
                    gid = int(candidate['group_id'])
                    break
            if group is None:
                still_failed.append(dict(route_id=rid, reason='group_missing'))
                continue
            if any(int(other) in state.accepted
                   for other in group['route_ids'] if int(other) != rid):
                # another member was routed somehow; skip (should not happen)
                still_failed.append(dict(route_id=rid,
                                         reason='partial_group_state'))
                continue
            results, failure, stats = router.attempt_group(group, budget)
            if results is None:
                still_failed.append(dict(group_id=gid, route_ids=group['route_ids'],
                                         reason=failure.get('reason'),
                                         rejection_counts=failure.get(
                                             'rejection_counts'),
                                         evaluated=failure.get('evaluated')))
                continue
            router.commit_group(group, results)
            recovered.append(dict(group_id=gid, route_ids=group['route_ids'],
                                  evaluated=stats.get('evaluated'),
                                  families=stats.get('families')))
            log(f'[repair {plane}] recovered group {gid} '
                f'({stats.get("evaluated")} candidates)')
    finally:
        ROUTER.BULGE_LADDER = old_ladder
    # build the output payload in the same schema as run2d
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    algorithm_detail = dict(
        name='MANUAL_C4_2D_REPAIR', algorithm='C4_2D_REPAIR',
        process_profile='R15_min_radius_15mm', radius_mm=float(C.RADIUS_MM),
        geometry_mode='d56', crossing_policy='exact',
        strategy='best sequential layout + extended same-side U bulge family '
                 'retry for the failed groups',
        budget=int(budget), extended_bulge_values=len(extended_ladder()))
    result_payload = state.payload('C4_2D_REPAIR', algorithm_detail,
                                   'MANUAL_C4_2D_REPAIR')
    result_payload['manual_c4'] = dict(
        plane=plane, source=source_routes,
        loaded_routes=len(routed), load_failed=load_failed,
        recovered_groups=recovered, still_failed=still_failed,
        seconds=round(time.perf_counter() - started, 2))
    result_payload['rotation_groups'] = [
        dict(group_id=g['group_id'], plane=g['plane'], kind=g['kind'],
             route_ids=g['route_ids'],
             status='routed' if all(int(rid) in state.accepted
                                    for rid in g['route_ids']) else 'failed')
        for g in groups]
    result_payload['failed_groups'] = still_failed
    router.augment_route_records(result_payload)
    (out_dir / 'routes.json').write_text(
        json.dumps(result_payload, ensure_ascii=False, default=str), encoding='utf-8')
    saved = json.loads((out_dir / 'routes.json').read_text(encoding='utf-8'))
    report = audit2d.audit_plane(saved, plane,
                                 label=f'MANUAL_C4_2D_REPAIR_{plane}',
                                 log=lambda message: None)
    groups_all = CONN.combined_topology()['groups']
    route_group = CONN.route_group_map()
    c4_report = validate2d.audit_c4_groups(saved['routes'],
                                           [g for g in groups_all
                                            if g['plane'] == plane],
                                           route_group,
                                           log=lambda message: None)
    validation = dict(schema='manual_c4_2d_plane_validation_v1',
                      experiment='MANUAL_C4_2D_REPAIR', plane=plane,
                      passed=bool(report['passed'] and c4_report['passed']),
                      plane_audit=report, c4_symmetry=c4_report)
    (out_dir / 'validation.json').write_text(
        json.dumps(validation, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    summary = dict(plane=plane, routed=len(state.accepted),
                   failed=len(state.routes) - len(state.accepted),
                   recovered_groups=len(recovered),
                   still_failed=len(still_failed),
                   validation_passed=validation['passed'],
                   seconds=round(time.perf_counter() - started, 2))
    (out_dir / 'run_summary.json').write_text(
        json.dumps(summary, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    log(f'[repair {plane}] routed={summary["routed"]} failed={summary["failed"]} '
        f'recovered={len(recovered)} still_failed={len(still_failed)} '
        f'validation={summary["validation_passed"]} ({summary["seconds"]}s)')
    return summary


def main():
    from four_side_1024.v3c4.profile import apply as apply_profile
    apply_profile()
    patch_conn()
    specs = [
        ('z1', CAMPAIGN / 'phase2_2d_order_same_first/z1/routes.json',
         CAMPAIGN / 'phase2_2d_repaired/z1'),
        ('z2', CAMPAIGN / 'phase2_2d/z2/routes.json',
         CAMPAIGN / 'phase2_2d_repaired/z2'),
    ]
    rows = []
    for plane, source, out_dir in specs:
        if not Path(source).exists():
            print('missing source', source)
            continue
        rows.append(repair_plane(plane, source, out_dir, log=print))
    (CAMPAIGN / 'phase2_2d_repaired' / 'repair_summary.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
