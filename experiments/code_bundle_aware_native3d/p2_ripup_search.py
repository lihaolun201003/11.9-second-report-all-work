# -*- coding: utf-8 -*-
"""P2: efficient local rip-up & reroute search for the eight unrouted Z2 orbits.

For each target orbit the search enumerates candidate quads of the frozen
template families, collects their blocker orbits, then for several *local
neighbourhoods* (target + 1-3 blockers) it rips the neighbourhood and re-routes
it jointly in several orders (target first / reverse / seeded shuffles).  The
candidate is committed only through the frozen 2D index and accepted only after
the frozen plane audit + strict C4 audit pass; every improvement is checkpointed.
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
    RipUpRerouter, load_plane_payload, restore_state, snapshot_state)
from four_side_1024.bundle3d.validate_local import validate_plane_payload  # noqa: E402
from four_side_1024.d56.search import RouteResult  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
RIP_DIR = CAMPAIGN / '02_ripup'
CHECKPOINTS = RIP_DIR / 'checkpoints'
BLOCKER_BUDGET = 600
PER_TARGET_TIME = 150.0
MAX_ATTEMPTS_PER_TARGET = 60


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def remove_groups(state, router, groups_by_id, group_ids):
    removed = {}
    for group_id in group_ids:
        group = groups_by_id[group_id]
        for rid in group['route_ids']:
            rid = int(rid)
            if rid in state.accepted:
                removed[rid] = state.accepted[rid]
                state.remove(rid)
        router.group_results.pop(int(group_id), None)
        router.failed_groups.pop(int(group_id), None)
    return removed


def commit_target(router, target, candidate):
    ids = [int(route_id) for route_id in target['route_ids']]
    results = []
    for index, rid in enumerate(ids):
        prepared = candidate['prepared'][index]
        results.append(RouteResult(
            rid, candidate['family'], dict(candidate['params']),
            candidate['oriented'][index], prepared, prepared.length, 0, 0,
            prepared.bend_count))
    router.commit_group(target, results)


def try_rip_set(rr, state, router, groups_by_id, target, candidate,
                rip_ids, orders):
    """Rip the neighbourhood, commit the target candidate, re-route the rest."""
    snapshot = snapshot_state(state)
    remove_groups(state, router, groups_by_id, rip_ids)
    commit_target(router, target, candidate)
    post_target = snapshot_state(state)
    pending_ids = [group_id for group_id in rip_ids
                   if int(group_id) != int(target['group_id'])]
    for order_mode, seed in orders:
        restore_state(state, post_target)
        if order_mode == 'target_first':
            pending = sorted(pending_ids)
        elif order_mode == 'reverse':
            pending = sorted(pending_ids, reverse=True)
        else:
            pending = list(pending_ids)
            random.Random(seed).shuffle(pending)
        failed = None
        for group_id in pending:
            group = groups_by_id[int(group_id)]
            group_results, failure, _stats = router.attempt_group(
                group, BLOCKER_BUDGET)
            if group_results is None:
                failed = dict(group_id=int(group_id),
                              reason=failure['reason'],
                              evaluated=failure['evaluated'])
                break
            router.commit_group(group, group_results)
        if failed is None:
            return True, dict(order=order_mode, seed=seed, failed=None,
                              routed=len(state.accepted))
    restore_state(state, snapshot)
    return False, dict(order=None, failed='all_orders_failed')


def main():
    patch_conn()
    RIP_DIR.mkdir(parents=True, exist_ok=True)
    groups = CONN.groups_for_plane('z2')
    by_gid = {int(group['group_id']): group for group in groups}
    combined = json.loads((OLD / 'phase2_2d_selected/routes_1024.json')
                          .read_text(encoding='utf-8'))
    payload = dict(schema='x', plane='z2',
                   routes=[copy.deepcopy(record) for record in
                           combined['routes'] if record.get('plane') == 'z2'])
    state = state_for('z2', log=lambda *a: None)
    load_plane_payload(state, payload)
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = ([round(0.1 * index, 3) for index in range(0, 1301)]
                           + [130.0, 135.0, 140.0])
    rr = RipUpRerouter(router, state, groups, log=lambda *a: None)
    rr.plane = 'z2'
    trials = []
    improvements = []
    started_overall = time.perf_counter()
    try:
        failed = [gid for gid in sorted(by_gid)
                  if not all(int(rid) in state.accepted
                             for rid in by_gid[gid]['route_ids'])]
        print(f'[p2] initial failed={failed}', flush=True)
        progress_round = 0
        while failed and progress_round < 6:
            progress_round += 1
            progress = False
            for group_id in list(failed):
                if group_id not in failed:
                    continue
                target = by_gid[group_id]
                target_started = time.perf_counter()
                candidates = rr.candidate_quads(target, budget=600)
                by_set = {}
                for candidate in candidates:
                    if candidate['self_conflict'] and not candidate['blocker_groups']:
                        continue
                    key = tuple(candidate['blocker_groups'])
                    if len(key) > 3:
                        continue
                    if key not in by_set:
                        by_set[key] = candidate
                ranked = sorted(by_set.items(),
                                key=lambda item: (len(item[0]),
                                                  item[1]['length_mm'] or 0.0))
                print(f'[p2] target {group_id} ({target["kind"]}): '
                      f'{len(candidates)} candidates, {len(ranked)} blocker sets',
                      flush=True)
                accepted = None
                attempts = 0
                for key, candidate in ranked[:12]:
                    if attempts >= MAX_ATTEMPTS_PER_TARGET:
                        break
                    if time.perf_counter() - target_started > PER_TARGET_TIME:
                        print(f'[p2] target {group_id}: time limit', flush=True)
                        break
                    neighbourhoods = [list(key)]
                    if len(key) >= 2:
                        neighbourhoods.append(list(key)[:2])
                    if len(key) >= 3:
                        neighbourhoods.append(list(key)[:3])
                        # expanded: combine this set with the next blocker sets
                        extra = [other for other in ranked[:8]
                                 if other[0] != key]
                        for other_key, _other in extra[:3]:
                            merged = list(dict.fromkeys(list(key)
                                                        + list(other_key)))[:5]
                            if merged not in neighbourhoods:
                                neighbourhoods.append(merged)
                    orders = (('target_first', 0), ('reverse', 0),
                              ('shuffle', 1), ('shuffle', 2), ('shuffle', 3))
                    for rip_ids in neighbourhoods:
                        attempts += 1
                        ok, info = try_rip_set(rr, state, router, by_gid,
                                               target, candidate,
                                               [int(group_id)] + rip_ids,
                                               orders)
                        trials.append(dict(
                            target=group_id, kind=target['kind'],
                            candidate=key, rip_ids=[int(group_id)] + rip_ids,
                            result=info, routed=len(state.accepted),
                            seconds=round(time.perf_counter()
                                          - started_overall, 1)))
                        print(f'[p2]   target {group_id} attempt {attempts} '
                              f'rip={rip_ids} -> {info} routed='
                              f'{len(state.accepted)}', flush=True)
                        if ok:
                            accepted = info
                            payload_out = rr.build_payload()
                            report = validate_plane_payload(payload_out, 'z2')
                            if report['passed']:
                                accepted = dict(info, validation_pass=True)
                                improvements.append(dict(
                                    group_id=group_id,
                                    blockers=rip_ids,
                                    routed=len(state.accepted)))
                                (CHECKPOINTS).mkdir(parents=True, exist_ok=True)
                                (CHECKPOINTS /
                                 f'z2_routed_{len(state.accepted)}.json'
                                 ).write_text(json.dumps(
                                     dict(payload=payload_out,
                                          extra=dict(group_id=group_id,
                                                     blockers=rip_ids)),
                                     ensure_ascii=False, default=str),
                                     encoding='utf-8')
                                (RIP_DIR / 'z2_routes_best.json').write_text(
                                    json.dumps(payload_out, ensure_ascii=False,
                                               default=str),
                                    encoding='utf-8')
                                print(f'[p2] ACCEPTED orbit {group_id} '
                                      f'(rip={rip_ids}) routed='
                                      f'{len(state.accepted)}', flush=True)
                            else:
                                print(f'[p2]   committed but validation '
                                      f'failed: {report.get("plane_audit", {}).get("passed")} '
                                      f'{report.get("c4_symmetry", {}).get("passed")}',
                                      flush=True)
                                accepted = None
                            break
                        if (time.perf_counter() - target_started
                                > PER_TARGET_TIME):
                            break
                    if accepted is not None:
                        break
                if accepted is not None:
                    failed = [gid for gid in failed
                              if not all(int(rid) in state.accepted
                                         for rid in by_gid[gid]['route_ids'])]
                    progress = True
                    break
                print(f'[p2] target {group_id}: no legal neighbourhood '
                      f'(attempts={attempts})', flush=True)
            if not progress:
                break
        final_payload = rr.build_payload()
        report = validate_plane_payload(final_payload, 'z2')
        summary = dict(final_routed=len(state.accepted),
                       failed_groups=[gid for gid in sorted(by_gid)
                                      if not all(int(rid) in state.accepted
                                                 for rid in
                                                 by_gid[gid]['route_ids'])],
                       validation_passed=report['passed'],
                       improvements=improvements,
                       trials=trials,
                       seconds=round(time.perf_counter() - started_overall, 1))
        (RIP_DIR / 'z2_ripup_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        (RIP_DIR / 'z2_routes_final.json').write_text(
            json.dumps(final_payload, ensure_ascii=False, default=str),
            encoding='utf-8')
        (RIP_DIR / 'z2_ripup_validation.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        print(json.dumps({key: summary[key] for key in
                          ('final_routed', 'failed_groups',
                           'validation_passed', 'seconds')},
                         ensure_ascii=False, indent=1), flush=True)
    finally:
        ROUTER.BULGE_LADDER = old_ladder


if __name__ == '__main__':
    main()
