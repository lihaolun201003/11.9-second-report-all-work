# -*- coding: utf-8 -*-
"""Apply the extended-ladder repair to the bundle-order 2D layouts."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile
apply_profile()

from four_side_1024.bundle3d.reroute import (  # noqa: E402
    load_plane_payload)
from four_side_1024.bundle3d.validate_local import validate_plane_payload  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
PLAN_DIR = CAMPAIGN / '02_bundle_planning'
OUT = PLAN_DIR / 'phase2_bundle_order_repaired'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def repair_plane(plane):
    groups = CONN.groups_for_plane(plane)
    by_gid = {int(group['group_id']): group for group in groups}
    payload = json.loads((PLAN_DIR / 'phase2_bundle_order' / plane
                          / 'routes.json').read_text(encoding='utf-8'))
    state = state_for(plane, log=lambda *a: None)
    load_plane_payload(state, payload)
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = ([round(0.1 * index, 3) for index in range(0, 1301)]
                           + [130.0, 135.0, 140.0])
    started = time.perf_counter()
    recovered = []
    try:
        for pass_index in range(4):
            failed = [gid for gid in sorted(by_gid)
                      if not all(int(rid) in state.accepted
                                 for rid in by_gid[gid]['route_ids'])]
            if not failed:
                break
            pass_recovered = 0
            for gid in failed:
                group = by_gid[gid]
                results, failure, stats = router.attempt_group(group, 30000)
                if results is not None:
                    router.commit_group(group, results)
                    pass_recovered += 1
                    recovered.append(dict(pass_index=pass_index,
                                          group_id=gid,
                                          kind=group['kind'],
                                          evaluated=stats.get('evaluated')))
            print(f'[repair-bundle] {plane} pass {pass_index}: failed={len(failed)} '
                  f'recovered={pass_recovered} routed={len(state.accepted)}',
                  flush=True)
            if not pass_recovered:
                break
        payload_out = router.state.payload('C4_2D_BUNDLE_REPAIRED', dict(
            name='C4_2D_BUNDLE_REPAIRED', algorithm='C4_2D_BUNDLE_REPAIRED',
            process_profile='R15_min_radius_15mm', radius_mm=15.0,
            geometry_mode='d56', crossing_policy='exact',
            strategy='bundle-first 2D order + extended U bulge repair',
            forced_symmetry=True, group_count=len(groups)), 'C4_2D_BUNDLE_REPAIRED')
        payload_out['rotation_groups'] = [
            dict(group_id=int(group['group_id']), plane=group['plane'],
                 kind=group['kind'], route_ids=[int(rid) for rid in group['route_ids']],
                 status='routed' if int(group['group_id']) in router.group_results
                 else 'failed') for group in groups]
        payload_out['failed_groups'] = [
            dict(group_id=gid, kind=by_gid[gid]['kind'],
                 reason='no_legal_quad_after_extended_ladder')
            for gid in sorted(by_gid)
            if int(gid) not in router.group_results]
        router.augment_route_records(payload_out)
        for record in payload_out['routes']:
            if record.get('status') != 'routed':
                record['status'] = 'failed'
                record['reason'] = 'no_legal_quad_after_extended_ladder'
        report = validate_plane_payload(payload_out, plane)
        route_count = len(state.accepted)
        return payload_out, dict(plane=plane, routed=route_count,
                                 recovered=recovered,
                                 validation_passed=report['passed'],
                                 seconds=round(time.perf_counter() - started, 1))
    finally:
        ROUTER.BULGE_LADDER = old_ladder


def main():
    patch_conn()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for plane in ('z1', 'z2'):
        payload_out, summary = repair_plane(plane)
        (OUT / plane).mkdir(parents=True, exist_ok=True)
        (OUT / plane / 'routes.json').write_text(
            json.dumps(payload_out, ensure_ascii=False, default=str),
            encoding='utf-8')
        results[plane] = summary
        print(f'[repair-bundle] {plane}: {summary["routed"]}/512 '
              f'validation={summary["validation_passed"]}', flush=True)
    (OUT / 'repair_summary.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print(json.dumps({plane: results[plane]['routed'] for plane in results}))


if __name__ == '__main__':
    main()
