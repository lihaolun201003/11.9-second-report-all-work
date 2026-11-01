# -*- coding: utf-8 -*-
"""P2 experiment: bundle-level corridor re-planning of the same-side U bundle.

Removes all routed same-side U orbits of Z2 from the 480/512 layout, then
re-routes the whole U bundle (28 C4 orbits = 112 routes) in a coordinated order
(by separation, so nesting is consistent) while the 96 routed adjacent orbits
stay fixed.  If the whole U bundle commits legally, Z2 reaches 512/512.
"""
from __future__ import annotations

import copy
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile
apply_profile()

from four_side_1024.bundle3d.reroute import (  # noqa: E402
    load_plane_payload, restore_state, snapshot_state)
from four_side_1024.bundle3d.validate_local import validate_plane_payload  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter, order_groups  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
RIP_DIR = CAMPAIGN / '02_ripup'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def main():
    patch_conn()
    plane = 'z2'
    groups = CONN.groups_for_plane(plane)
    by_gid = {int(g['group_id']): g for g in groups}
    combined = json.loads((OLD / 'phase2_2d_selected/routes_1024.json')
                          .read_text(encoding='utf-8'))
    payload = dict(schema='x', plane=plane,
                   routes=[copy.deepcopy(r) for r in combined['routes']
                           if r.get('plane') == plane])
    state = state_for(plane, log=lambda *a: None)
    load_plane_payload(state, payload)
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    router.reconcile()
    same_groups = [by_gid[gid] for gid in sorted(by_gid)
                   if by_gid[gid]['kind'] == 'same']

    def separation_of(group):
        record = router.blocks[int(group['route_ids'][0])]
        eps = state.endpoints
        p0 = eps[record['source_endpoint']]['routing_xy']
        p1 = eps[record['target_endpoint']]['routing_xy']
        if record['source_side'] in 'NS':
            return abs(float(p1[0]) - float(p0[0]))
        return abs(float(p1[1]) - float(p0[1]))

    separations = {int(group['group_id']): separation_of(group)
                   for group in same_groups}
    print(f'[p2b] same orbits: {len(same_groups)}', flush=True)
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = ([round(0.1 * index, 3) for index in range(0, 1301)]
                           + [130.0, 135.0, 140.0])
    results = []
    best = None
    try:
        for attempt, (order_mode, seed) in enumerate((
                ('sep_desc', 0), ('sep_asc', 0), ('easy', 0),
                ('shuffle', 1), ('shuffle', 2), ('shuffle', 3))):
            snapshot = snapshot_state(state)
            # remove every routed same-side U orbit
            for group in same_groups:
                for rid in group['route_ids']:
                    rid = int(rid)
                    if rid in state.accepted:
                        state.remove(rid)
                router.group_results.pop(int(group['group_id']), None)
            if order_mode == 'sep_desc':
                order = sorted(same_groups,
                               key=lambda g: -separations[int(g['group_id'])])
            elif order_mode == 'sep_asc':
                order = sorted(same_groups,
                               key=lambda g: separations[int(g['group_id'])])
            elif order_mode == 'easy':
                order = order_groups(same_groups, router, mode='same_first')
            else:
                order = list(same_groups)
                random.Random(seed).shuffle(order)
            started = time.perf_counter()
            cache = router.prime_same_candidates()
            applied = 0
            for group in order:
                results_group, failure, _stats = router.attempt_group(
                    group, 2000, same_candidates=cache.get(
                        int(group['group_id'])))
                if results_group is None:
                    break
                router.commit_group(group, results_group)
                applied += 1
            seconds = round(time.perf_counter() - started, 1)
            routed = len(state.accepted)
            print(f'[p2b] attempt {attempt} order={order_mode} '
                  f'applied={applied}/{len(same_groups)} routed={routed} '
                  f'({seconds}s)', flush=True)
            results.append(dict(attempt=attempt, order=order_mode,
                                applied=applied, routed=routed,
                                seconds=seconds))
            if applied == len(same_groups):
                final_payload = router.build_payload() if hasattr(
                    router, 'build_payload') else None
                from four_side_1024.bundle3d.reroute import RipUpRerouter
                rr = RipUpRerouter(router, state, groups, log=lambda *a: None)
                rr.plane = plane
                final_payload = rr.build_payload()
                report = validate_plane_payload(final_payload, plane)
                print(f'[p2b] FULL U bundle committed: validation={report["passed"]}',
                      flush=True)
                if report['passed']:
                    best = dict(payload=final_payload, report=report,
                                attempt=attempt, order=order_mode)
                    break
            restore_state(state, snapshot)
        if best is not None:
            RIP_DIR.mkdir(parents=True, exist_ok=True)
            (RIP_DIR / 'z2_same_bundle_replan.json').write_text(
                json.dumps(dict(schema='p2b_same_bundle_replan',
                                order=best['order'],
                                routed=512,
                                validation=best['report']),
                           ensure_ascii=False, default=str),
                encoding='utf-8')
            (RIP_DIR / 'z2_routes_512.json').write_text(
                json.dumps(best['payload'], ensure_ascii=False, default=str),
                encoding='utf-8')
            print('[p2b] saved 512/512 z2 layout', flush=True)
        else:
            # keep the best partial state (most same groups applied)
            print('[p2b] no complete same-bundle re-plan; see attempts',
                  flush=True)
        (RIP_DIR / 'z2_same_bundle_attempts.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=1),
            encoding='utf-8')
    finally:
        ROUTER.BULGE_LADDER = old_ladder


if __name__ == '__main__':
    main()
