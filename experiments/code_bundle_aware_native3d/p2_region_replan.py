# -*- coding: utf-8 -*-
"""P2: spatial-window rip-up & reroute (bundle-level local replanning).

For each unrouted Z2 C4 orbit a board window (e.g. 30-60 mm around the orbit) is
cleared: all routed orbits whose geometry touches that window are ripped up
together with the target orbit.  The window is then re-routed jointly in several
orders (target first, original order, reverse, seeded shuffles).  This is much
stronger than single-blocker rip-up because the whole local corridor layout can
change, which is exactly what the corner/U bundle bottlenecks require.

Every completely re-routed + frozen-audit-passing window becomes a checkpoint.
"""
from __future__ import annotations

import copy
import json
import math
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
WINDOWS = [22.0, 35.0, 50.0]
REGION_TIME = 260.0
BUDGET = 1800


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
            if radius and primitive.get('center'):
                center = primitive['center']
                points.append((center[0] - radius, center[1] - radius))
                points.append((center[0] + radius, center[1] + radius))
    return points


def group_bbox(router, group):
    xs, ys = [], []
    for rid in group['route_ids']:
        record = router.blocks[int(rid)]
        points = primitive_points(record.get('primitives') or [])
        if not points:
            for key in ('source_endpoint', 'target_endpoint'):
                endpoint = record.get(key)
                if endpoint:
                    ep = router.state.endpoints.get(endpoint)
                    if ep is not None:
                        points.append(tuple(ep['routing_xy'])[:2])
        for x, y in points:
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def window_groups(router, groups, target_group, margin):
    target_box = group_bbox(router, target_group)
    if target_box is None:
        return []
    min_x, min_y, max_x, max_y = target_box
    lo_x, lo_y = max(0.0, min_x - margin), max(0.0, min_y - margin)
    hi_x, hi_y = min(150.0, max_x + margin), min(150.0, max_y + margin)
    selected = []
    for group in groups:
        if int(group['group_id']) == int(target_group['group_id']):
            continue
        if not all(int(rid) in router.state.accepted for rid in group['route_ids']):
            continue
        box = group_bbox(router, group)
        if box is None:
            continue
        intersects = not (box[2] < lo_x or box[0] > hi_x
                          or box[3] < lo_y or box[1] > hi_y)
        if intersects:
            selected.append(group)
    return selected


def rip_groups(state, router, groups):
    for group in groups:
        for rid in group['route_ids']:
            rid = int(rid)
            if rid in state.accepted:
                state.remove(rid)
        router.group_results.pop(int(group['group_id']), None)
        router.failed_groups.pop(int(group['group_id']), None)


def try_window(rr, state, router, target, window, orders):
    """Rip the window + target, then re-route the window in the given orders."""
    snapshot = snapshot_state(state)
    rip = [target] + window
    rip_groups(state, router, rip)
    # target first via its own full search
    group_results, failure, _stats = router.attempt_group(target, BUDGET)
    if group_results is None:
        restore_state(state, snapshot)
        return False, dict(stage='target_failed', reason=failure['reason'],
                           blockers=failure.get('blockers'))
    router.commit_group(target, group_results)
    pending = [group for group in window]
    for order_mode, seed in orders:
        if order_mode == 'original':
            remaining = sorted(pending, key=lambda group: int(group['group_id']))
        elif order_mode == 'reverse':
            remaining = sorted(pending,
                               key=lambda group: -int(group['group_id']))
        elif order_mode == 'easy':
            rank = {'opposite': 0, 'adjacent': 1, 'same': 2}
            remaining = sorted(pending, key=lambda group: (
                rank.get(group['kind'], 9), int(group['group_id'])))
        elif order_mode == 'hard':
            rank = {'adjacent': 0, 'same': 1, 'opposite': 2}
            remaining = sorted(pending, key=lambda group: (
                rank.get(group['kind'], 9), int(group['group_id'])))
        else:
            remaining = list(pending)
            random.Random(seed).shuffle(remaining)
        # reset to state containing only the target
        restore_state(state, snapshot)
        rip_groups(state, router, rip)
        target_results, _failure, _stats = router.attempt_group(target, BUDGET)
        if target_results is None:
            break
        router.commit_group(target, target_results)
        failed = None
        for group in remaining:
            if all(int(rid) in state.accepted for rid in group['route_ids']):
                continue
            results, failure, _stats = router.attempt_group(group, BUDGET)
            if results is None:
                failed = dict(group_id=int(group['group_id']),
                              reason=failure['reason'])
                break
            router.commit_group(group, results)
        if failed is None:
            return True, dict(order=order_mode, seed=seed,
                              routed=len(state.accepted),
                              window=len(window))
        last_failure = failed
    restore_state(state, snapshot)
    return False, dict(stage='window_failed', last=last_failure,
                       window=len(window))


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
        print(f'[p2reg] initial failed={failed}', flush=True)
        rounds = 0
        while failed and rounds < 4:
            rounds += 1
            progress = False
            for group_id in list(failed):
                if group_id not in failed:
                    continue
                target = by_gid[group_id]
                target_started = time.perf_counter()
                accepted = None
                for margin in WINDOWS:
                    if time.perf_counter() - target_started > REGION_TIME:
                        break
                    window = window_groups(router, groups, target, margin)
                    if not window:
                        continue
                    orders = (('target_then_original', 0),
                              ('target_then_reverse', 0),
                              ('target_then_easy', 0),
                              ('target_then_hard', 0),
                              ('shuffle', 1), ('shuffle', 2), ('shuffle', 3))
                    ok, info = try_window(rr, state, router, target, window,
                                          orders)
                    trials.append(dict(target=group_id, margin=margin,
                                       window_size=len(window),
                                       result=info,
                                       seconds=round(time.perf_counter()
                                                     - started_overall, 1)))
                    print(f'[p2reg] target {group_id} margin={margin} '
                          f'window={len(window)} -> {info}', flush=True)
                    if ok:
                        payload_out = rr.build_payload()
                        report = validate_plane_payload(payload_out, 'z2')
                        print(f'[p2reg]   validation passed={report["passed"]}',
                              flush=True)
                        if report['passed']:
                            accepted = payload_out
                            improvements.append(dict(
                                group_id=group_id, margin=margin,
                                window_size=len(window),
                                routed=len(state.accepted)))
                            (CHECKPOINTS).mkdir(parents=True, exist_ok=True)
                            (CHECKPOINTS /
                             f'z2_routed_{len(state.accepted)}.json'
                             ).write_text(json.dumps(
                                 dict(payload=payload_out,
                                      extra=dict(group_id=group_id,
                                                 margin=margin,
                                                 window_size=len(window))),
                                 ensure_ascii=False, default=str),
                                 encoding='utf-8')
                            (RIP_DIR / 'z2_routes_best.json').write_text(
                                json.dumps(payload_out, ensure_ascii=False,
                                           default=str), encoding='utf-8')
                            print(f'[p2reg] ACCEPTED target {group_id} '
                                  f'-> routed={len(state.accepted)}', flush=True)
                            break
                if accepted is not None:
                    failed = [gid for gid in failed
                              if not all(int(rid) in state.accepted
                                         for rid in
                                         by_gid[gid]['route_ids'])]
                    progress = True
                    break
            if not progress:
                print('[p2reg] no window replan found in this round', flush=True)
                break
        final_payload = rr.build_payload()
        report = validate_plane_payload(final_payload, 'z2')
        summary = dict(final_routed=len(state.accepted),
                       failed_groups=[gid for gid in sorted(by_gid)
                                      if not all(int(rid) in state.accepted
                                                 for rid in
                                                 by_gid[gid]['route_ids'])],
                       validation_passed=report['passed'],
                       improvements=improvements, trials=trials,
                       seconds=round(time.perf_counter() - started_overall, 1))
        (RIP_DIR / 'z2_region_summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        (RIP_DIR / 'z2_routes_final.json').write_text(
            json.dumps(final_payload, ensure_ascii=False, default=str),
            encoding='utf-8')
        (RIP_DIR / 'z2_region_validation.json').write_text(
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
