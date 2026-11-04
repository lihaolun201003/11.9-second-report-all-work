# -*- coding: utf-8 -*-
"""G4b -- dynamic regrouping of the 368 manual-U routes.

Contract (``SPEC_G4.md`` §4, task G4-3): the 368 real connections are fixed but
the eight original ``manual_group`` member sets are **not** a hard constraint.
The arm searches over

* single-route migration to another legal body height,
* 2-3 route height swaps,
* cluster migration (3-8 routes),
* splitting one original group onto several body heights,
* different original groups sharing one body height again (new grouping),
* full XY / R15-arc / 3D-transition re-planning of every moved route and
  automatic reconstruction-order changes;

all moves are joint transactions over **manual-U routes only** (the non-manual
lines never participate in this arm; that is G4c/G4d territory).  Grouping is
measured from the *real* body heights (+ original group labels) -- the
``manual_group`` field itself is never rewritten.

Run (project root)::

    python -m four_side_1024.fanout1024.xyzrouter.g4.run_g4b \
        --budget-seconds 1200 --seed 20261104
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.xyzrouter import manual_reheight as MR  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import route_builder as RB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import arm_base as AB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import artifacts as ART  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import group_replan as GR  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import joint_world as JW  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

ARM = 'G4b'

SCAN_CFG = dict(max_target_layers=19, max_lead_pairs=1,
                prescreen_candidates=48, max_candidates=100, d56_top=6,
                bodies_per_pair=1, max_return=2, allow_direct=False,
                allow_xy_only=False)


def build_parser():
    parser = argparse.ArgumentParser(
        description='G4b: dynamic manual-U regrouping + full XY+Z re-planning.')
    parser.add_argument('--budget-seconds', type=float, default=1200.0)
    parser.add_argument('--reserve-seconds', type=float, default=90.0)
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--out-dir', type=str, default=None)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--no-validate', action='store_true')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--scan-routes', type=int, default=20)
    parser.add_argument('--scan-fraction', type=float, default=0.30)
    parser.add_argument('--singles', type=int, default=14)
    parser.add_argument('--single-targets', type=int, default=3)
    parser.add_argument('--xy-tune', type=int, default=14)
    parser.add_argument('--swaps', type=int, default=10)
    parser.add_argument('--clusters', type=int, default=6)
    parser.add_argument('--cluster-size', type=int, default=6)
    parser.add_argument('--splits', type=int, default=4)
    parser.add_argument('--split-size', type=int, default=8)
    parser.add_argument('--reorg', type=int, default=4)
    parser.add_argument('--reorg-size', type=int, default=8)
    parser.add_argument('--tune', type=int, default=12)
    parser.add_argument('--tune-size', type=int, default=3)
    parser.add_argument('--search-fraction', type=float, default=0.97)
    parser.add_argument('--max-rounds', type=int, default=12)
    parser.add_argument('--tag', type=str, default='')
    return parser


def _attempt_stats(attempts):
    by_reason = Counter()
    by_kind = OrderedDict()
    accepted = 0
    for attempt in attempts:
        if attempt.get('accepted'):
            reason = 'accepted'
            accepted += 1
        else:
            reason = str(attempt.get('failure_reason') or 'unknown')
        by_reason[reason] += 1
        kind = str(attempt.get('kind') or '?')
        entry = by_kind.setdefault(kind, Counter())
        entry['attempts'] += 1
        entry[reason] += 1
    return dict(count=len(attempts), accepted=int(accepted),
                by_reason={str(k): int(v) for k, v in by_reason.items()},
                by_kind={str(k): {str(kk): int(vv) for kk, vv in v.items()}
                         for k, v in by_kind.items()},
                spec_failure_classification_covered=sorted(
                    str(k) for k in by_reason
                    if str(k) in GR.FAILURE_REASONS))


def _plane_events(state):
    return {round(float(z), 9): int(counts[0])
            for z, counts in state.plane_counts.items()}


def _current_height(state, rid):
    return GR.height_label_of_z(GR.primary_height(state.routes[int(rid)]))


def feasible_labels(state, rid):
    """Body height labels reachable for this route (lead-length necessary cond.)."""
    try:
        values = MR.feasible_heights(state, int(rid))
    except Exception:  # noqa: BLE001 - defensive
        return None
    return {GR.height_label_of_z(z) for _pid, z, _lead in values}


def heuristic_targets(state, rids, loads, plane_events, feasible=None,
                      max_n=3, max_target_routes=GR.MAX_TARGET_ROUTES):
    """Cheap ranked body-height targets for a move of ``rids`` (old groups free)."""
    rids = [int(rid) for rid in rids]
    current = {_current_height(state, rid) for rid in rids}
    heights = [GR.primary_height(state.routes[rid]) for rid in rids]
    heights = [float(z) for z in heights if z is not None]
    centroid = sum(heights) / len(heights) if heights else 0.0
    rows = []
    for pid, z, label in GR.BODY_PLANES:
        if label in current:
            continue
        if feasible is not None and label not in feasible:
            continue
        load = loads[z]
        if int(load['routes']) + len(rids) > int(max_target_routes):
            continue
        rows.append(dict(layer=int(pid), z=float(z), label=str(label),
                         plane_events=int(plane_events.get(round(float(z), 9),
                                                           0)),
                         other=int(load['other']),
                         distance=round(abs(float(z) - centroid), 4)))
    rows.sort(key=lambda row: (row['plane_events'], row['other'],
                               row['distance'], row['label']))
    return rows[:int(max_n)]


def _target_from_label(label):
    layer, z = GR.label_plane(label)
    return dict(layer=int(layer), z=float(z), label=str(label))


# ---------------------------------------------------------------------------
# swap transaction (2-3 routes exchange body heights)
# ---------------------------------------------------------------------------
def swap_transaction(jw, rids, cfg, note='', min_gain=1):
    """Joint transaction where ``rids[i]`` takes ``rids[i-1]``'s body height."""
    state = jw.state
    rids = [int(rid) for rid in rids]
    plan = []
    for index, rid in enumerate(rids):
        source = rids[(index - 1) % len(rids)]
        plan.append((rid, _current_height(state, source),
                     _current_height(state, rid)))
    started = time.time()
    tx = jw.transaction(rids, note=note, min_gain=int(min_gain))
    tx.rip_all()
    placed = 0
    failed_rid = None
    try:
        for rid, target_label, old_label in plan:
            layer, z = GR.label_plane(target_label)
            cands = tx.plan(rid, forced=(int(layer), float(z)), cfg=cfg)
            if not cands:
                failed_rid = int(rid)
                break
            tx.place(rid, cands[0])
            placed += 1
        result = tx.finish()
    except Exception as error:  # noqa: BLE001
        try:
            if tx._open:
                tx.abort('exception:%s' % type(error).__name__)
        except Exception:  # noqa: BLE001
            pass
        GR.repair_after_rollback(state, rids)
        return dict(accepted=False, placed=placed, failed_rid=failed_rid,
                    failure_reason='structure_error',
                    delta=0, gain=0, total=int(state.total), reasons={},
                    repaired=True, seconds=round(time.time() - started, 2),
                    note=str(note), members=len(rids))
    repaired = False
    if not bool(result.get('accepted')):
        GR.repair_after_rollback(state, rids)
        repaired = True
    record = dict(accepted=bool(result.get('accepted')), placed=int(placed),
                  members=len(rids), failed_rid=failed_rid,
                  delta=int(result.get('delta') or 0),
                  gain=int(result.get('gain') or 0),
                  old_total=int(result.get('old_total') or state.total),
                  total=int(state.total),
                  reasons={str(k): int(v) for k, v in
                           (result.get('reasons') or {}).items()},
                  repaired=bool(repaired),
                  seconds=round(time.time() - started, 2), note=str(note))
    if record['accepted']:
        record['failure_reason'] = 'accepted'
    elif failed_rid is not None:
        record['failure_reason'] = 'no_legal_xy_corridor'
    else:
        record['failure_reason'] = GR.classify_transaction_failure(record)
    return record


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def search_g4b(ctx, jw, tracker, budget, args, log):
    state = ctx.state
    out_dir = Path(ctx.out_dir)
    groups = GR.manual_group_members(state)
    manual_set = GR.manual_ids(state)
    start_routes = {int(route['route_id']): route
                    for route in ctx.baseline['routes']}
    log('[g4b] loading start facts ...')
    start_events = GR.manual_crossing_events(state)
    start_crossings = start_events['per_route']
    loads = GR.plane_loads(state, manual_set)
    plane_events = _plane_events(state)
    start_grouping = GR.grouping_report(state, groups)
    start_floor = int(state.total) - int(start_events['manual_manual']
                                         + start_events['manual_non'])
    log('[g4b] start total=%d MM=%d MN=%d NN=%d manual_floor=%d clusters=%d'
        % (state.total, start_events['manual_manual'],
           start_events['manual_non'], start_events['non_manual'],
           start_floor, start_grouping['cluster_count']))
    GP.write_json(out_dir / 'start_snapshot.json', dict(
        arm=ARM, start_total=int(state.total), manual_routes=len(manual_set),
        start_grouping=start_grouping,
        start_group_heights={g: {str(k): int(v) for k, v in counter.items()}
                             for g, counter in
                             GR.group_height_map(state, groups).items()},
        plane_loads={str(z): value for z, value in loads.items()},
        plane_events={str(z): int(v) for z, v in plane_events.items()},
        crossing_decomposition={k: v for k, v in start_events.items()
                                if k != 'per_route'},
        theoretical_floor=int(start_floor),
        ceiling_note='manual-U-only arm: the non-manual-only crossings are '
                     'immutable here (G4c/G4d territory)'))

    attempts = []
    accepted = []
    rounds = []
    scanned = {}
    fail_count = Counter()
    last_checkpoint = time.time()
    rng = __import__('random').Random(int(args.seed))

    def refresh():
        nonlocal loads, plane_events
        loads = GR.plane_loads(state, manual_set)
        plane_events = _plane_events(state)

    def record_attempt(kind, rids, target, records, crossings):
        group_tag = '|'.join(sorted({str(state.routes[int(rid)].get(
            'manual_group') or '') for rid in rids}))
        old_labels = {int(rid): _current_height(state, rid) for rid in rids}
        out = []
        for record in records:
            record.update(kind=str(kind), group=group_tag,
                          target_label=str(target.get('label')),
                          target_layer=int(target.get('layer')),
                          target_z=float(target.get('z')),
                          route_ids=[int(rid) for rid in rids],
                          old_height_labels={str(k): v
                                             for k, v in old_labels.items()})
            out.append(record)
        return out

    def attempt_rids(kind, rids, target, crossings, cfg_variants=None,
                     order_variants=None, max_retries=1):
        rids = [int(rid) for rid in rids]
        group_tag = '|'.join(sorted({str(state.routes[int(rid)].get(
            'manual_group') or '') for rid in rids}))
        records = GR.attempt_group_target(
            jw, group_tag, rids, target, crossings, budget, log,
            cfg_variants=cfg_variants or [GR.PLAN_FAST, GR.PLAN_STD],
            order_variants=order_variants or ['crossing_desc', 'risk_desc'],
            max_retries=max_retries)
        records = record_attempt(kind, rids, target, records, crossings)
        attempts.extend(records)
        hit = [record for record in records if record.get('accepted')]
        if hit:
            accepted.extend(hit)
            tracker.consider(state, note='g4b %s %s->%s' % (
                kind, group_tag, target.get('label')))
            refresh()
            log('[g4b] accepted %s %s -> %s gain=%d total=%d'
                % (kind, group_tag, target.get('label'), hit[0].get('gain'),
                   state.total))
        else:
            for record in records:
                fail_count[(kind, group_tag, str(target.get('label')))] += 1
        return bool(hit)

    # ------------------------------------------------------------------ p1
    log('[g4b] P1: per-route clean scan of the highest-crossing routes')
    crossings = GR.manual_route_crossings(state, manual_set)
    crossing_routes = sorted([rid for rid, count in crossings.items()
                              if count > 0], key=lambda rid: (-crossings[rid],
                                                              rid))
    scan_limit = args.scan_routes if not args.quick else min(6, args.scan_routes)
    for rid in crossing_routes[:scan_limit]:
        if budget.search_over() or budget.fraction() > args.scan_fraction:
            break
        started = time.time()
        try:
            candidates = jw.plan_candidates(rid, cfg=SCAN_CFG, mode='clean')
        except Exception as error:  # noqa: BLE001
            log('[g4b] scan exception route %d: %s' % (rid, error))
            continue
        best = {}
        for candidate in candidates:
            if candidate.delta is None:
                continue
            key = round(float(candidate.z_mm), 9)
            record = dict(layer=int(candidate.layer),
                          z=float(candidate.z_mm),
                          label=GR.height_label_of_z(candidate.z_mm),
                          delta=int(candidate.delta),
                          kind=str(candidate.kind),
                          xy_crossings=int(candidate.xy_crossings),
                          lead_s=float(candidate.lead_s),
                          lead_t=float(candidate.lead_t))
            old = best.get(key)
            if old is None or record['delta'] < old['delta']:
                best[key] = record
        scanned[rid] = dict(total=int(state.total),
                            targets=sorted(best.values(),
                                           key=lambda r: r['delta']),
                            seconds=round(time.time() - started, 2))
    log('[g4b] P1 done: scanned=%d (%.0fs)' % (len(scanned), budget.elapsed()))
    GP.write_json(out_dir / 'route_scan.json', dict(
        route_count=len(scanned), routes={str(rid): value
                                          for rid, value in scanned.items()}))

    # ------------------------------------------------------------- operators
    def op_singles(crossing_routes, crossings):
        progressed = 0
        used = 0
        for rid in crossing_routes:
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.singles:
                break
            scan = scanned.get(rid)
            targets = []
            if scan:
                for record in scan['targets']:
                    if record['delta'] > -1:
                        break
                    targets.append(dict(layer=record['layer'], z=record['z'],
                                        label=record['label']))
                    if len(targets) >= args.single_targets:
                        break
            if not targets:
                feasible = feasible_labels(state, rid)
                targets = heuristic_targets(state, [rid], loads, plane_events,
                                            feasible=feasible,
                                            max_n=args.single_targets)
            if not targets:
                continue
            for target in targets:
                if budget.search_over():
                    break
                group_tag = str(state.routes[rid].get('manual_group') or '')
                if fail_count[('single_migrate', group_tag,
                               str(target['label']))] >= 3:
                    continue
                used += 1
                if attempt_rids('single_migrate', [rid], target, crossings,
                                cfg_variants=[GR.PLAN_FAST],
                                order_variants=['crossing_desc'],
                                max_retries=0):
                    progressed += 1
                    crossings = GR.manual_route_crossings(state, manual_set)
                    break
        return progressed, crossings

    def op_xy_tune(crossing_routes, crossings):
        progressed = 0
        used = 0
        for rid in crossing_routes:
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.xy_tune:
                break
            label = _current_height(state, rid)
            if label is None:
                continue
            target = _target_from_label(label)
            used += 1
            if attempt_rids('single_xy_replan', [rid], target, crossings,
                            cfg_variants=[GR.PLAN_FAST],
                            order_variants=['crossing_desc'],
                            max_retries=0):
                progressed += 1
                crossings = GR.manual_route_crossings(state, manual_set)
        return progressed, crossings

    def op_swaps(crossing_routes, crossings):
        progressed = 0
        used = 0
        manual_by_height = OrderedDict()
        for rid in manual_set:
            manual_by_height.setdefault(_current_height(state, rid),
                                        []).append(rid)
        for rid in crossing_routes:
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.swaps:
                break
            targets = []
            scan = scanned.get(rid)
            if scan:
                for record in scan['targets'][:2]:
                    if record['delta'] > -1:
                        break
                    targets.append(record['label'])
            if not targets:
                feasible = feasible_labels(state, rid)
                targets = [row['label'] for row in heuristic_targets(
                    state, [rid], loads, plane_events, feasible=feasible,
                    max_n=2)]
            for label in targets:
                partners = [partner for partner in
                            manual_by_height.get(label, [])
                            if partner != rid
                            and _current_height(state, partner) !=
                            _current_height(state, rid)]
                partners.sort(key=lambda partner: (
                    int(state.routes[partner].get('manual_group') ==
                        state.routes[rid].get('manual_group')),
                    crossings.get(partner, 0)))
                if not partners:
                    continue
                partner = partners[0]
                used += 1
                record = swap_transaction(
                    jw, [rid, partner], dict(GR.PLAN_FAST),
                    note='swap %d<->%d' % (rid, partner))
                record.update(kind='pair_swap', group='|'.join(sorted({
                    str(state.routes[rid].get('manual_group')),
                    str(state.routes[partner].get('manual_group'))})),
                    target_label='%s<->%s' % (_current_height(state, partner),
                                              _current_height(state, rid)),
                    target_layer=-1, target_z=0.0,
                    route_ids=[rid, partner])
                attempts.append(record)
                if record.get('accepted'):
                    accepted.append(record)
                    progressed += 1
                    tracker.consider(state, note='g4b swap %d<->%d' % (
                        rid, partner))
                    refresh()
                    crossings = GR.manual_route_crossings(state, manual_set)
                    log('[g4b] accepted pair_swap %d<->%d gain=%d total=%d'
                        % (rid, partner, record.get('gain'), state.total))
                    break
                fail_count[('pair_swap', '-', record.get('target_label',
                                                        '-'))] += 1
        return progressed, crossings

    def op_clusters(crossing_routes, crossings):
        progressed = 0
        used = 0
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        for gname in sorted(groups_now, key=lambda name: -group_cross[name]):
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.clusters:
                break
            members = [rid for rid in sorted(groups_now[gname],
                                             key=lambda rid: -crossings.get(
                                                 rid, 0))
                       if crossings.get(rid, 0) > 0]
            if len(members) < 3:
                continue
            for start in range(0, min(len(members), 2 * args.cluster_size),
                               args.cluster_size):
                if used >= args.clusters or budget.search_over():
                    break
                cluster = members[start:start + args.cluster_size]
                if len(cluster) < 3:
                    continue
                feasible = feasible_labels(state, cluster[0])
                for rid in cluster[1:]:
                    other = feasible_labels(state, rid)
                    feasible = (feasible & other) if feasible is not None \
                        and other is not None else None
                targets = heuristic_targets(state, cluster, loads,
                                            plane_events, feasible=feasible,
                                            max_n=2)
                if not targets:
                    continue
                for target in targets:
                    if budget.search_over():
                        break
                    used += 1
                    if attempt_rids('cluster_migrate', cluster, target,
                                    crossings):
                        progressed += 1
                        crossings = GR.manual_route_crossings(state, manual_set)
                        break
                if used >= args.clusters:
                    break
        return progressed, crossings

    def op_splits(crossing_routes, crossings):
        progressed = 0
        used = 0
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        for gname in sorted(groups_now, key=lambda name: -group_cross[name]):
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.splits:
                break
            members = groups_now[gname]
            counter = GR.group_height_counter(state, members)
            if len(counter) < 1:
                continue
            # split the members of the height with the most crossing routes
            by_height = OrderedDict()
            for rid in members:
                by_height.setdefault(_current_height(state, rid), []).append(
                    int(rid))
            ranked = sorted(
                by_height,
                key=lambda label: -sum(crossings.get(rid, 0)
                                       for rid in by_height[label]))
            for source_label in ranked[:2]:
                subset = sorted(by_height[source_label],
                                key=lambda rid: -crossings.get(rid, 0))
                subset = subset[:max(2, min(args.split_size,
                                            len(subset) // 2 or 2))]
                if len(subset) < 2:
                    continue
                feasible = feasible_labels(state, subset[0])
                for rid in subset[1:]:
                    other = feasible_labels(state, rid)
                    feasible = (feasible & other) if feasible is not None \
                        and other is not None else None
                targets = heuristic_targets(state, subset, loads, plane_events,
                                            feasible=feasible, max_n=2)
                for target in targets:
                    if budget.search_over() or used >= args.splits:
                        break
                    used += 1
                    if attempt_rids('split_group', subset, target, crossings):
                        progressed += 1
                        crossings = GR.manual_route_crossings(state, manual_set)
                        break
        return progressed, crossings

    def op_reorg(crossing_routes, crossings):
        """Move a cluster onto another original group's majority body height."""
        progressed = 0
        used = 0
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        order = sorted(groups_now, key=lambda name: -group_cross[name])
        for source in order:
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.reorg:
                break
            members = [rid for rid in sorted(groups_now[source],
                                             key=lambda rid: -crossings.get(
                                                 rid, 0))
                       if crossings.get(rid, 0) > 0]
            if len(members) < 3:
                continue
            cluster = members[:args.reorg_size]
            for destination in order:
                if destination == source:
                    continue
                dest_label = GR.majority_height_label(
                    GR.group_height_counter(state, groups_now[destination]))
                if dest_label is None:
                    continue
                if all(_current_height(state, rid) == dest_label
                       for rid in cluster):
                    continue
                target = _target_from_label(dest_label)
                if int(loads[target['z']]['routes']) + len(cluster) > \
                        GR.MAX_TARGET_ROUTES:
                    continue
                used += 1
                if attempt_rids('cross_group_reorg', cluster, target,
                                crossings):
                    progressed += 1
                    crossings = GR.manual_route_crossings(state, manual_set)
                    break
                if used >= args.reorg:
                    break
        return progressed, crossings

    def op_tune(crossing_routes, crossings):
        progressed = 0
        used = 0
        for rid in crossing_routes:
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            if used >= args.tune:
                break
            label = _current_height(state, rid)
            feasible = feasible_labels(state, rid)
            targets = heuristic_targets(state, [rid], loads, plane_events,
                                        feasible=feasible, max_n=1)
            if not targets:
                continue
            used += 1
            if attempt_rids('height_tune', [rid], targets[0], crossings,
                            cfg_variants=[GR.PLAN_FAST],
                            order_variants=['crossing_desc'],
                            max_retries=0):
                progressed += 1
                crossings = GR.manual_route_crossings(state, manual_set)
        return progressed, crossings

    round_index = 0
    while not budget.search_over():
        round_index += 1
        if round_index > args.max_rounds:
            break
        if budget.fraction() > args.search_fraction:
            break
        crossings = GR.manual_route_crossings(state, manual_set)
        crossing_routes = sorted([rid for rid, count in crossings.items()
                                  if count > 0],
                                 key=lambda rid: (-crossings[rid], rid))
        log('[g4b] round %d: total=%d crossing_routes=%d elapsed=%.0fs '
            'fraction=%.2f' % (round_index, state.total, len(crossing_routes),
                               budget.elapsed(), budget.fraction()))
        progressed = 0
        round_start_attempts = len(attempts)
        for operator in (op_singles, op_xy_tune, op_swaps, op_clusters,
                         op_splits, op_reorg, op_tune):
            if budget.search_over() or budget.fraction() > args.search_fraction:
                break
            try:
                hit, crossings = operator(crossing_routes, crossings)
            except Exception as error:  # noqa: BLE001 - keep the arm alive
                log('[g4b] operator %s exception %s: %s'
                    % (operator.__name__, type(error).__name__, error))
                import traceback
                log(traceback.format_exc()[-2000:])
                hit = 0
            progressed += hit
            if hit:
                refreshed = GR.manual_route_crossings(state, manual_set)
                crossing_routes = sorted(
                    [rid for rid, count in refreshed.items() if count > 0],
                    key=lambda rid: (-refreshed.get(rid, 0), rid))
        rounds.append(dict(round=round_index, accepted=int(progressed),
                           attempts=int(len(attempts) - round_start_attempts),
                           total=int(state.total),
                           seconds=round(budget.elapsed(), 1)))
        log('[g4b] round %d done accepted=%d total=%d (%.0fs)'
            % (round_index, progressed, state.total, budget.elapsed()))
        if progressed == 0:
            break
        if time.time() - last_checkpoint >= GR.CHECKPOINT_SECONDS:
            GR.checkpoint(ctx, jw, log, extra=dict(phase='G4b',
                                                   accepted=len(accepted)))
            last_checkpoint = time.time()

    # re-scan after the search to record the final per-route picture
    final_scan = {}
    crossings = GR.manual_route_crossings(state, manual_set)
    for rid in sorted(crossings, key=lambda value: -crossings[value])[:10]:
        if budget.search_over():
            break
        try:
            candidates = jw.plan_candidates(rid, cfg=SCAN_CFG, mode='clean')
        except Exception:  # noqa: BLE001
            continue
        final_scan[rid] = [dict(layer=int(candidate.layer),
                                z=float(candidate.z_mm),
                                label=GR.height_label_of_z(candidate.z_mm),
                                delta=None if candidate.delta is None
                                else int(candidate.delta))
                           for candidate in candidates[:6]]
    return dict(attempts=attempts, accepted=accepted, rounds=rounds,
                scanned=scanned, final_scan=final_scan,
                start_events=start_events, start_grouping=start_grouping,
                start_floor=start_floor, start_routes=start_routes,
                groups=groups, manual_set=manual_set,
                start_crossings=start_crossings)


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir) if args.out_dir else GP.ARM_DIRS[ARM]
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.quick:
        args.scan_routes = min(args.scan_routes, 4)
        args.singles = min(args.singles, 3)
        args.xy_tune = min(args.xy_tune, 3)
        args.swaps = min(args.swaps, 2)
        args.clusters = min(args.clusters, 2)
        args.splits = min(args.splits, 1)
        args.reorg = min(args.reorg, 1)
        args.tune = min(args.tune, 3)
        args.max_rounds = min(args.max_rounds, 2)
        args.scan_fraction = min(args.scan_fraction, 0.35)
    if args.quick and args.reserve_seconds >= 60:
        args.reserve_seconds = 20.0
    log = GR.Logger(out_dir / 'run.log')
    log('=' * 78)
    log('[g4b] start: budget=%.0fs seed=%d quick=%s' % (
        args.budget_seconds, args.seed, args.quick))
    cfg = dict(arm=ARM, quick=bool(args.quick), scan_cfg=SCAN_CFG,
               scan_routes=args.scan_routes, singles=args.singles,
               single_targets=args.single_targets, xy_tune=args.xy_tune,
               swaps=args.swaps, clusters=args.clusters,
               cluster_size=args.cluster_size, splits=args.splits,
               split_size=args.split_size, reorg=args.reorg,
               reorg_size=args.reorg_size, tune=args.tune,
               tune_size=args.tune_size, tag=args.tag,
               spec='experiments/xyz_joint_g4_1024/SPEC_G4.md')
    budget_cfg = dict(GP.ARM_BUDGETS[ARM])
    budget_cfg['wall_seconds'] = float(args.budget_seconds)
    spec = AB.ArmSpec(ARM, out_dir=out_dir, cfg=cfg, seed=args.seed,
                      budget=budget_cfg, log=log)
    ctx = AB.ArmContext(spec)
    ctx.load(resume=bool(args.resume))
    state = ctx.state
    jw = JW.JointWorld(state, ledger=ctx.ledger, log=log, seed=args.seed)
    ctx.jw = jw
    tracker = ART.BestTracker(spec, ctx.baseline, log=log)
    tracker.best_total = int(state.total)
    budget = GR.Budget(ctx, args.budget_seconds, reserve=args.reserve_seconds)
    result = dict(attempts=[], accepted=[], rounds=[], scanned={},
                  final_scan={}, start_events=dict(per_route={}),
                  start_grouping=dict(cluster_count=0, clusters={}),
                  start_floor=int(state.total),
                  start_routes={}, groups=GR.manual_group_members(state),
                  manual_set=GR.manual_ids(state), start_crossings={})
    try:
        result = search_g4b(ctx, jw, tracker, budget, args, log)
    except Exception as error:  # noqa: BLE001
        log('[g4b] SEARCH EXCEPTION %s: %s' % (type(error).__name__, error))
        import traceback
        log(traceback.format_exc()[-4000:])

    state = ctx.state
    manual_set = result.get('manual_set') or GR.manual_ids(state)
    groups = result.get('groups') or GR.manual_group_members(state)
    start_routes = result.get('start_routes') or {
        int(route['route_id']): route for route in ctx.baseline['routes']}
    attempts = list(result.get('attempts') or [])
    accepted = list(result.get('accepted') or [])
    start_grouping = result.get('start_grouping') or GR.grouping_report(
        type('S', (), {'routes': start_routes, 'plane_prims': {}})(), groups) \
        if False else (result.get('start_grouping') or {})
    log('[g4b] search finished total=%d accepted_events=%d elapsed=%.0fs'
        % (state.total, len(accepted), budget.elapsed()))
    geometry = state.validate_all(log=None)
    log('[g4b] state.validate_all: valid=%d violations=%d kinds=%s'
        % (geometry['valid'], len(geometry['violations']),
           geometry['violation_kinds']))
    xy_evidence = GR.xy_change_evidence(start_routes, state, manual_set)
    matrix = GR.migration_matrix(state, groups)
    matrix_rows = GR.migration_matrix_rows(matrix)
    final_grouping = GR.grouping_report(state, groups)
    split_evidence = GR.split_group_evidence(state, groups)
    final_events = GR.manual_crossing_events(state)
    attempt_stats = _attempt_stats(attempts)
    # start clustering by (height, old group) for the dynamic-regrouping claim
    class _StartState(object):
        pass
    start_state = _StartState()
    start_state.routes = start_routes
    start_clusters = GR.grouping_report(start_state, groups)
    moved = sum(1 for rid in manual_set
                if GR.height_label_of_z(GR.primary_height(
                    state.routes[int(rid)])) !=
                GR.height_label_of_z(GR.primary_height(
                    start_routes[int(rid)])))
    merged = final_grouping['merged_clusters']
    reorg_evidence = dict(
        start_cluster_count=int(start_clusters['cluster_count']),
        final_cluster_count=int(final_grouping['cluster_count']),
        start_heights_used=int(len(start_clusters['heights'])),
        final_heights_used=int(len(final_grouping['heights'])),
        routes_changed_primary_height=int(moved),
        routes_pct=round(100.0 * moved / float(max(1, len(manual_set))), 2),
        merged_height_clusters=merged,
        split_original_groups=final_grouping['split_groups'],
        start_split_original_groups=start_clusters['split_groups'],
        clusters=final_grouping['clusters'])
    summary_payload = dict(
        arm=ARM, start_crossings=int(GP.START_CROSSINGS),
        final_crossings=int(state.total),
        crossing_delta=int(state.total) - int(GP.START_CROSSINGS),
        crossing_pairs=int(state.pairs),
        accepted_transactions=int(len(accepted)),
        manual_routes=int(len(manual_set)),
        original_groups=len(groups),
        regrouping=reorg_evidence,
        migration_matrix=matrix,
        split_group_evidence=split_evidence,
        xy_evidence=xy_evidence,
        attempt_stats=attempt_stats,
        rounds=result.get('rounds') or [],
        crossing_decomposition_start=dict(
            manual_manual=int(result.get('start_events', {}).get(
                'manual_manual', 0)),
            manual_non=int(result.get('start_events', {}).get(
                'manual_non', 0)),
            non_manual=int(result.get('start_events', {}).get(
                'non_manual', 0))),
        crossing_decomposition_final=dict(
            manual_manual=int(final_events['manual_manual']),
            manual_non=int(final_events['manual_non']),
            non_manual=int(final_events['non_manual'])),
        theoretical_floor_manual_only=int(result.get('start_floor')
                                          or (GP.START_CROSSINGS - 109)),
        ceiling_note='G4b only re-plans the 368 manual-U routes; the %d '
                     'non-manual-only crossings are immutable in this arm.'
                     % int(result.get('start_events', {}).get('non_manual',
                                                              1213)),
        state_validate_all=dict(
            valid=int(geometry['valid']),
            violations=int(len(geometry['violations'])),
            kinds={str(k): int(v) for k, v in
                   (geometry['violation_kinds'] or {}).items()}),
        ledger=ctx.ledger.summary(),
        search_wall_seconds=round(budget.elapsed(), 2),
        config=spec.as_dict())
    writes = {
        'group_attempts.json': dict(arm=ARM, stats=attempt_stats,
                                    attempts=attempts[:2000]),
        'group_migration.json': summary_payload,
        'migration_matrix.csv': matrix_rows,
        'new_grouping.json': dict(arm=ARM, start=start_clusters,
                                  final=final_grouping,
                                  reorg_evidence=reorg_evidence,
                                  split_group_evidence=split_evidence),
        'xy_evidence.json': xy_evidence,
        'final_route_scan.json': {str(rid): value for rid, value in
                                  (result.get('final_scan') or {}).items()},
        'failure_taxonomy.json': GR.failure_taxonomy(
            attempts, budget_exhausted=bool(budget.search_over()),
            extra=dict(arm=ARM,
                       search_wall_seconds=round(budget.elapsed(), 2),
                       budget_cap_seconds=float(args.budget_seconds))),
    }
    state.failed_attempts = [
        dict(route_id=record.get('failed_rid'),
             reason=str(record.get('failure_reason')),
             kind=str(record.get('kind')),
             group=str(record.get('group')),
             target=str(record.get('target_label')),
             note=str(record.get('note')))
        for record in attempts if not record.get('accepted')][:2000]
    extra = dict(
        arm=ARM, attempt_stats=attempt_stats,
        accepted_moves=[
            dict(kind=record.get('kind'), group=record.get('group'),
                 target=record.get('target_label'),
                 target_z=record.get('target_z'),
                 route_ids=record.get('route_ids'),
                 gain=int(record.get('gain') or 0),
                 members=int(record.get('members') or 0),
                 order=record.get('order'),
                 seconds=record.get('seconds'))
            for record in accepted],
        regrouping=reorg_evidence,
        rounds=result.get('rounds') or [],
        final_crossings=int(state.total),
        scanned_routes=int(len(result.get('scanned') or {})),
        search_wall_seconds=round(budget.elapsed(), 2),
        spec_failure_coverage=attempt_stats[
            'spec_failure_classification_covered'],
        tag=args.tag)
    validation = GR.finalize_arm(ctx, jw, tracker, extra=extra,
                                 writes=writes, log=log,
                                 validate=not args.no_validate)
    arm_summary = dict(summary_payload)
    arm_summary['validation'] = validation.get('validation_summary') or {}
    arm_summary['total_search_and_validation_seconds'] = round(
        spec.elapsed(), 2)
    GP.write_json(out_dir / 'arm_summary.json', arm_summary)
    log('[g4b] DONE final_crossings=%d start=%d delta=%d validation=%s' % (
        state.total, GP.START_CROSSINGS,
        int(state.total) - int(GP.START_CROSSINGS),
        json.dumps(validation.get('validation_summary') or {},
                   ensure_ascii=False)))
    log('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
