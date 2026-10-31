# -*- coding: utf-8 -*-
"""Extra multi-pass repair for the remaining z2 C4 groups (finer bulge ladder)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile  # noqa: E402
apply_profile()

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import audit2d  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402
from four_side_1024.v3c4 import validate2d  # noqa: E402
from four_side_1024.d56.index import prepare  # noqa: E402
from four_side_1024.d56.search import RouteResult  # noqa: E402
from four_side_1024.fslw import config as C  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
PLANE = 'z2'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def main():
    patch_conn()
    CONN.combined_topology()
    source = CAMPAIGN / 'phase2_2d_repaired' / PLANE / 'routes.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    records = {int(r['route_id']): dict(r) for r in payload['routes']}
    routed = [r for r in records.values() if r.get('status') == 'routed']
    groups = CONN.groups_for_plane(PLANE)
    by_gid = {int(g['group_id']): g for g in groups}

    state = state_for(PLANE, log=lambda *a: None)
    for record in routed:
        rid = int(record['route_id'])
        prims = [dict(p) for p in record['primitives']]
        prepared = prepare(prims)
        state.index.add(rid, prepared)
        state.accepted[rid] = RouteResult(
            rid, record.get('family') or 'HISTORY',
            dict(record.get('params') or {}), prims, prepared,
            float(record.get('length_mm') or 0.0), 0, 0,
            int(record.get('bend_count') or 0))
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    ladder = [round(0.1 * i, 3) for i in range(0, 1301)] + [130.0, 135.0, 140.0]
    old = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = ladder
    started = time.perf_counter()
    recovered_history = []
    try:
        for pass_index in range(4):
            pending = [by_gid[gid] for gid in sorted(router.failed_groups)]
            if not pending:
                break
            recovered = 0
            for group in pending:
                if any(int(other) in state.accepted
                       for other in group['route_ids']):
                    continue
                results, failure, stats = router.attempt_group(group, 40000)
                if results is not None:
                    router.commit_group(group, results)
                    recovered += 1
                    recovered_history.append(dict(
                        pass_index=pass_index,
                        group_id=int(group['group_id']),
                        kind=group['kind'],
                        evaluated=stats.get('evaluated')))
            print(f'[repair-more] pass {pass_index}: pending={len(pending)} '
                  f'recovered={recovered} routed={len(state.accepted)}',
                  flush=True)
            if not recovered:
                break
    finally:
        ROUTER.BULGE_LADDER = old
    out_dir = CAMPAIGN / 'phase2_2d_repaired2' / PLANE
    out_dir.mkdir(parents=True, exist_ok=True)
    algorithm_detail = dict(name='MANUAL_C4_2D_REPAIR2',
                            algorithm='C4_2D_REPAIR2',
                            process_profile='R15_min_radius_15mm',
                            radius_mm=float(C.RADIUS_MM),
                            geometry_mode='d56', crossing_policy='exact',
                            strategy='multi-pass fine U bulge ladder repair')
    result_payload = state.payload('C4_2D_REPAIR2', algorithm_detail,
                                   'MANUAL_C4_2D_REPAIR2')
    result_payload['rotation_groups'] = [
        dict(group_id=g['group_id'], plane=g['plane'], kind=g['kind'],
             route_ids=g['route_ids'],
             status='routed' if all(int(rid) in state.accepted
                                    for rid in g['route_ids']) else 'failed')
        for g in groups]
    result_payload['failed_groups'] = []
    router.augment_route_records(result_payload)
    # patch failed reason
    for record in result_payload['routes']:
        if record.get('status') != 'routed':
            record['status'] = 'failed'
            record['reason'] = 'no_legal_quad_after_repair2'
    (out_dir / 'routes.json').write_text(
        json.dumps(result_payload, ensure_ascii=False, default=str),
        encoding='utf-8')
    saved = json.loads((out_dir / 'routes.json').read_text(encoding='utf-8'))
    report = audit2d.audit_plane(saved, PLANE, label=f'REPAIR2_{PLANE}',
                                 log=lambda *a: None)
    all_groups = CONN.combined_topology()['groups']
    route_group = CONN.route_group_map()
    c4 = validate2d.audit_c4_groups(saved['routes'],
                                    [g for g in all_groups
                                     if g['plane'] == PLANE],
                                    route_group, log=lambda *a: None)
    validation = dict(schema='manual_c4_2d_plane_validation_v1',
                      experiment='MANUAL_C4_2D_REPAIR2', plane=PLANE,
                      passed=bool(report['passed'] and c4['passed']),
                      plane_audit=report, c4_symmetry=c4)
    (out_dir / 'validation.json').write_text(
        json.dumps(validation, indent=1, ensure_ascii=False, default=str),
        encoding='utf-8')
    summary = dict(plane=PLANE, routed=len(state.accepted),
                   failed=len(state.routes) - len(state.accepted),
                   recovered_history=recovered_history,
                   validation_passed=validation['passed'],
                   seconds=round(time.perf_counter() - started, 1))
    (out_dir / 'run_summary.json').write_text(
        json.dumps(summary, indent=1, ensure_ascii=False, default=str),
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
