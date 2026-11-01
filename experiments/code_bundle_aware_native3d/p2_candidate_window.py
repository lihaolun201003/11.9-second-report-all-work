# -*- coding: utf-8 -*-
"""P2: candidate-centred corridor rip-up (window around the candidate path).

For each unrouted Z2 orbit we enumerate the frozen-template candidate quads,
take the candidates with the fewest blocker orbits, and clear a spatial window
around the candidate geometry itself.  The window (plus the target orbit) is then
re-routed jointly: the target first, then the ripped orbits in several orders.
This is the targeted version of the spatial-window rip-up and avoids clearing the
whole board for corner connections whose port bbox covers half the board.
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
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
RIP_DIR = CAMPAIGN / '02_ripup'
CHECKPOINTS = RIP_DIR / 'checkpoints'
MARGINS = (12.0, 20.0)
TARGET_TIME = 150.0
BUDGET = 2000


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def primitive_points(primitives):
    points = []
    for primitive in primitives:
        if primitive.get('kind') == 'line':
            points.append(tuple(primitive['p0']))
            points.append(tuple(primitive['p1']))
        else:
            for key in ('p0', 'p1', 'center'):
                if primitive.get(key):
                    points.append(tuple(primitive[key])[:2])
            radius = float(primitive.get('radius') or 0.0)
            center = primitive.get('center')
            if radius and center:
                points.extend([(center[0] - radius, center[1] - radius),
                               (center[0] + radius, center[1] + radius)])
    return points


def group_points(router, group):
    xs, ys = [], []
    for rid in group['route_ids']:
        record = router.blocks[int(rid)]
        pts = primitive_points(record.get('primitives') or [])
        if not pts:
            for key in ('source_endpoint', 'target_endpoint'):
                endpoint = record.get(key)
                if endpoint:
                    ep = router.state.endpoints.get(endpoint)
                    if ep is not None:
                        pts.append(tuple(ep['routing_xy'])[:2])
        for x, y in pts:
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def window_around(router, groups, target, box, margin):
    lo_x, lo_y = box[0] - margin, box[1] - margin
    hi_x, hi_y = box[2] + margin, box[3] + margin
    selected = []
    for group in groups:
        if int(group['group_id']) == int(target['group_id']):
            continue
        if not all(int(rid) in router.state.accepted for rid in group['route_ids']):
            continue
        other = group_points(router, group)
        if other is None:
            continue
        if not (other[2] < lo_x or other[0] > hi_x
                or other[3] < lo_y or other[1] > hi_y):
            selected.append(group)
    return selected


def rip(state, router, groups):
    for group in groups:
        for rid in group['route_ids']:
            rid = int(rid)
            if rid in state.accepted:
                state.remove(rid)
        router.group_results.pop(int(group['group_id']), None)
        router.failed_groups.pop(int(group['group_id']), None)


def try_window(rr, state, router, target, window):
    snapshot = snapshot_state(state)
    rip_groups = [target] + window
    rip(state, router, rip_groups)
    target_results, failure, _stats = router.attempt_group(target, BUDGET)
    if target_results is None:
        restore_state(state, snapshot)
        return False, dict(stage='target_failed',
                           reason=failure['reason'],
                           blockers=list(failure.get('blockers') or {})[:10])
    router.commit_group(target, target_results)
    post_target = snapshot_state(state)
    orders = [('original', 0), ('reverse', 0), ('easy', 0), ('hard', 0),
              ('shuffle', 1), ('shuffle', 2), ('shuffle', 3)]
    rank = {'opposite': 0, 'adjacent': 1, 'same': 2}
    for order_mode, seed in orders:
        restore_state(state, post_target)
        pending = [group for group in window
                   if not all(int(rid) in state.accepted
                              for rid in group['route_ids'])]
        if order_mode == 'original':
            pending.sort(key=lambda group: int(group['group_id']))
        elif order_mode == 'reverse':
            pending.sort(key=lambda group: -int(group['group_id']))
        elif order_mode == 'easy':
            pending.sort(key=lambda group: (rank.get(group['kind'], 9),
                                            int(group['group_id'])))
        elif order_mode == 'hard':
            pending.sort(key=lambda group: (-rank.get(group['kind'], 9),
                                            int(group['group_id'])))
        else:
            random.Random(seed).shuffle(pending)
        failed = None
        for group in pending:
            results, failure, _stats = router.attempt_group(group, BUDGET)
            if results is None:
                failed = dict(group_id=int(group['group_id']),
                              reason=failure['reason'])
                break
            router.commit_group(group, results)
        if failed is None:
            return True, dict(stage='window_ok', order=order_mode,
                              window=len(window) + 1,
                              routed=len(state.accepted))
    restore_state(state, snapshot)
    return False, dict(stage='window_failed', window=len(window) + 1)


def main():
    patch_conn()
    RIP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
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
        print(f'[p2win] initial failed={failed}', flush=True)
        rounds = 0
        while failed and rounds < 3:
            rounds += 1
            progress = False
            for group_id in list(failed):
                if group_id not in failed:
                    continue
                target = by_gid[group_id]
                target_started = time.perf_counter()
                candidates = rr.candidate_quads(target, budget=900)
                accepted = None
                tried = 0
                for candidate in candidates[:40]:
                    if time.perf_counter() - target_started > TARGET_TIME:
                        break
                    if candidate['self_conflict']:
                        continue
                    box = primitive_points(candidate['oriented'][0])
                    if not box:
                        continue
                    xs = [point[0] for point in box]
                    ys = [point[1] for point in box]
                    candidate_box = (min(xs), min(ys), max(xs), max(ys))
                    for margin in MARGINS:
                        window = window_around(router, groups, target,
                                               candidate_box, margin)
                        if not window or len(window) > 26:
                            continue
                        tried += 1
                        ok, info = try_window(rr, state, router, target,
                                              window)
                        trials.append(dict(target=group_id, tried=tried,
                                           margin=margin,
                                           window=len(window), result=info,
                                           seconds=round(
                                               time.perf_counter()
                                               - started_overall, 1)))
                        print(f'[p2win] target {group_id} cand={tried} '
                              f'window={len(window)} margin={margin} -> {info}',
                              flush=True)
                        if ok:
                            payload_out = rr.build_payload()
                            report = validate_plane_payload(payload_out, 'z2')
                            print(f'[p2win]   validation={report["passed"]}',
                                  flush=True)
                            if report['passed']:
                                accepted = payload_out
                                improvements.append(dict(group_id=group_id,
                                                         window=len(window),
                                                         routed=len(
                                                             state.accepted)))
                                (CHECKPOINTS /
                                 f'z2_routed_{len(state.accepted)}.json'
                                 ).write_text(json.dumps(
                                     dict(payload=payload_out,
                                          extra=dict(target=group_id)),
                                     ensure_ascii=False, default=str),
                                     encoding='utf-8')
                                (RIP_DIR / 'z2_routes_best.json').write_text(
                                    json.dumps(payload_out,
                                               ensure_ascii=False,
                                               default=str),
                                    encoding='utf-8')
                                print(f'[p2win] ACCEPTED {group_id} ->'
                                      f' {len(state.accepted)}', flush=True)
                                break
                        if time.perf_counter() - target_started > TARGET_TIME:
                            break
                    if accepted is not None:
                        break
                if accepted is not None:
                    failed = [gid for gid in failed
                              if not all(int(rid) in state.accepted
                                         for rid in by_gid[gid]['route_ids'])]
                    progress = True
                    break
            if not progress:
                break
        failures = [gid for gid in sorted(by_gid)
                    if not all(int(rid) in state.accepted
                               for rid in by_gid[gid]['route_ids'])]
        summary = dict(final_routed=len(state.accepted),
                       failed_groups=failures,
                       improvements=improvements, trials=trials,
                       seconds=round(time.perf_counter() - started_overall, 1))
        (RIP_DIR / 'z2_window_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        print(json.dumps({key: summary[key] for key in
                          ('final_routed', 'failed_groups', 'seconds')},
                         ensure_ascii=False, indent=1), flush=True)
    finally:
        ROUTER.BULGE_LADDER = old_ladder


if __name__ == '__main__':
    main()
