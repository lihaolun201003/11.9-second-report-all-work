# -*- coding: utf-8 -*-
"""G4a -- fixed eight manual-U groups, whole-group XY+Z re-design.

Contract (``SPEC_G4.md`` §4, task G4-3):

* the 368 manual-U routes keep their **route identity / connection / original
  ``manual_group`` membership**; the eight groups are *fixed member sets*;
* every group may migrate, as a whole, to another legal body height (one body
  height per group) and every member gets a brand-new XY corridor (R15 arc
  placement / turns / leads / 3D transitions are all free, leads >= process
  minimum enforced by the frozen builder);
* a group-level joint transaction rips the whole group, re-plans every member at
  the forced target height (2-3 reconstruction orders / lead strategies), and
  only commits when the whole group is legal and the exact crossing recount
  improves; any member without a candidate fails that target height
  (``SPEC_G4.md`` §4 allows a documented partial fallback);
* the 19 body heights are explored: the target ranking covers L2-L5 and L10-L13
  **and** the outside-band heights (L6, L7, L20, L8, L9, L14-L19);
* after the group phase the accepted groups get intra-group micro-tuning rounds
  (still inside G4a freedom: same group, same body height, new XY corridors).

Run (from the project root)::

    python -m four_side_1024.fanout1024.xyzrouter.g4.run_g4a \
        --budget-seconds 1200 --seed 20261104

Quick smoke::

    python -m four_side_1024.fanout1024.xyzrouter.g4.run_g4a \
        --quick --budget-seconds 90 --no-validate
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

from four_side_1024.fanout1024.xyzrouter import route_builder as RB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import arm_base as AB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import artifacts as ART  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import group_replan as GR  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import joint_world as JW  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

ARM = 'G4a'


def build_parser():
    parser = argparse.ArgumentParser(
        description='G4a: fixed eight manual-U groups, whole-group XY+Z '
                    're-design (SPEC_G4.md).')
    parser.add_argument('--budget-seconds', type=float, default=1200.0,
                        help='search wall-clock budget (default 1200 s)')
    parser.add_argument('--reserve-seconds', type=float, default=90.0,
                        help='reserved for finalisation inside the budget')
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--out-dir', type=str, default=None)
    parser.add_argument('--resume', action='store_true',
                        help='resume from the latest arm checkpoint')
    parser.add_argument('--no-validate', action='store_true',
                        help='skip the independent validator (smoke runs only)')
    parser.add_argument('--quick', action='store_true',
                        help='small configuration for a smoke test')
    parser.add_argument('--max-rounds', type=int, default=6)
    parser.add_argument('--attempts-per-group-round', type=int, default=4)
    parser.add_argument('--max-group-attempts', type=int, default=12)
    parser.add_argument('--max-retries', type=int, default=1)
    parser.add_argument('--max-reps', type=int, default=3)
    parser.add_argument('--max-target-routes', type=int,
                        default=GR.MAX_TARGET_ROUTES)
    parser.add_argument('--group-phase-fraction', type=float, default=0.72)
    parser.add_argument('--tune-fraction', type=float, default=0.97)
    parser.add_argument('--tune-rounds', type=int, default=2)
    parser.add_argument('--tune-size', type=int, default=10)
    parser.add_argument('--tune-min', type=int, default=4)
    parser.add_argument('--feasibility-cap-seconds', type=float, default=170.0)
    parser.add_argument('--no-partial-fallback', action='store_true')
    parser.add_argument('--tag', type=str, default='')
    return parser


def _attempt_stats(attempts):
    by_reason = Counter()
    by_group = OrderedDict()
    accepted = 0
    for attempt in attempts:
        reason = str(attempt.get('failure_reason') or 'unknown')
        by_reason[reason] += 1
        group = str(attempt.get('group') or '?')
        entry = by_group.setdefault(group, Counter())
        entry['attempts'] += 1
        entry[reason] += 1
        if attempt.get('accepted'):
            accepted += 1
            entry['accepted'] += 1
    return dict(count=len(attempts), accepted=int(accepted),
                by_reason={str(k): int(v) for k, v in by_reason.items()},
                by_group={str(k): {str(kk): int(vv) for kk, vv in v.items()}
                          for k, v in by_group.items()})


def search_g4a(ctx, jw, tracker, budget, args, log):
    state = ctx.state
    out_dir = Path(ctx.out_dir)
    groups = GR.manual_group_members(state)
    manual_set = GR.manual_ids(state)
    start_routes = {int(r['route_id']): r for r in ctx.baseline['routes']}
    start_group_heights = GR.group_height_map(state, groups)

    log('[g4a] loading start facts (manual crossings / grouping) ...')
    start_events = GR.manual_crossing_events(state)
    start_crossings = start_events['per_route']
    loads = GR.plane_loads(state, manual_set)
    plane_events = {round(float(z), 9): int(counts[0])
                    for z, counts in state.plane_counts.items()}
    start_floor = int(state.total) - int(start_events['manual_manual']
                                         + start_events['manual_non'])
    log('[g4a] start total=%d manual_events: MM=%d MN=%d NN=%d '
        'theoretical_floor=%d' % (
            state.total, start_events['manual_manual'],
            start_events['manual_non'], start_events['non_manual'],
            start_floor))
    GP.write_json(out_dir / 'start_snapshot.json', dict(
        arm=ARM, start_total=int(state.total),
        routes=len(state.routes), manual_routes=len(manual_set),
        start_group_heights={g: {str(k): int(v) for k, v in counter.items()}
                             for g, counter in start_group_heights.items()},
        plane_loads={str(z): value for z, value in loads.items()},
        crossing_decomposition={k: v for k, v in start_events.items()
                                if k != 'per_route'},
        theoretical_floor=int(start_floor),
        ceiling_note='manual-U-only arms can only change crossings that '
                     'involve at least one manual route; the non-manual-only '
                     'crossings belong to G4c/G4d'))

    # ------------------------------------------------------------------ p1
    feas = OrderedDict()
    if not args.quick:
        log('[g4a] P1: forced-height feasibility scan over all 19 body heights')
        cap = args.feasibility_cap_seconds
        if cap and cap > 0:
            cap = min(cap, max(30.0, 0.25 * budget.seconds))
        feas = GR.feasibility_scan(jw, groups, budget, log,
                                   cfg=GR.PLAN_STD,
                                   max_reps=args.max_reps,
                                   max_seconds=cap)
        GP.write_json(out_dir / 'height_feasibility.json', feas)
        covered = sum(1 for g in feas for label in feas[g])
        outside = sum(1 for g in feas for label in feas[g]
                      if label not in GR.START_BANDS)
        log('[g4a] P1 done: %d (group, height) cells, %d outside start bands'
            % (covered, outside))
    else:
        log('[g4a] P1 skipped (quick mode)')

    # ------------------------------------------------------------------ p2
    attempts = []
    accepted = []
    rounds = []
    fail_count = Counter()
    attempts_by_group = Counter()
    accepted_groups = set()
    last_checkpoint = time.time()
    selected = sorted(groups)[:args.max_groups] if getattr(
        args, 'max_groups', 0) else sorted(groups)

    def refresh():
        nonlocal loads, plane_events
        loads = GR.plane_loads(state, manual_set)
        plane_events = {round(float(z), 9): int(counts[0])
                        for z, counts in state.plane_counts.items()}

    while not budget.search_over():
        round_index = len(rounds) + 1
        if round_index > args.max_rounds:
            break
        if budget.fraction() > args.group_phase_fraction:
            break
        log('[g4a] P2 round %d: total=%d elapsed=%.0fs fraction=%.2f'
            % (round_index, state.total, budget.elapsed(), budget.fraction()))
        crossings = GR.manual_route_crossings(state, manual_set)
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        order_groups = sorted(groups_now,
                              key=lambda g: (-group_cross[g], g))
        progressed = 0
        round_attempts = 0
        for gname in order_groups:
            if gname not in selected:
                continue
            if budget.search_over() or \
                    budget.fraction() > args.group_phase_fraction:
                break
            if attempts_by_group[gname] >= args.max_group_attempts:
                continue
            members = groups_now[gname]
            counter = GR.group_height_counter(state, members)
            majority = GR.majority_height_label(counter)
            targets = GR.rank_group_targets(state, gname, members, feas, loads,
                                            crossings,
                                            current_labels=set(counter),
                                            plane_events=plane_events)
            tries = 0
            for target in targets:
                if budget.search_over() or \
                        budget.fraction() > args.group_phase_fraction:
                    break
                if tries >= args.attempts_per_group_round:
                    break
                if attempts_by_group[gname] >= args.max_group_attempts:
                    break
                label = str(target['label'])
                if fail_count[(gname, label)] >= 2:
                    continue
                if label == majority and len(counter) == 1:
                    attempts.append(dict(
                        group=gname, target_label=label,
                        target_layer=target['layer'], target_z=target['z'],
                        members=len(members), accepted=False,
                        failure_reason='already_at_height', order='-',
                        attempt_index=-1, seconds=0.0, delta=0, gain=0))
                    attempts_by_group[gname] += 1
                    tries += 1
                    continue
                if int(target['load']) + len(members) > args.max_target_routes:
                    attempts.append(dict(
                        group=gname, target_label=label,
                        target_layer=target['layer'], target_z=target['z'],
                        members=len(members), accepted=False,
                        failure_reason='target_height_occupied', order='-',
                        attempt_index=-1, seconds=0.0, delta=0, gain=0,
                        target_load=int(target['load'])))
                    attempts_by_group[gname] += 1
                    tries += 1
                    continue
                before_counter = dict(counter)
                records = GR.attempt_group_target(
                    jw, gname, members, target, crossings, budget, log,
                    cfg_variants=[GR.PLAN_FAST, GR.PLAN_STD],
                    order_variants=['risk_desc', 'crossing_desc'],
                    max_retries=args.max_retries)
                for record in records:
                    record['old_heights'] = {str(k): int(v)
                                             for k, v in before_counter.items()}
                # documented SPEC §4 fallback: members that are geometrically
                # infeasible on the new height stay on their current height
                if (not any(record.get('accepted') for record in records)
                        and not args.no_partial_fallback
                        and int(target['load']) + len(members)
                        <= args.max_target_routes + 40):
                    order = GR.order_members(state, members, 'risk_desc',
                                             crossings=crossings,
                                             target_z=float(target['z']))
                    partial = GR.partial_group_transaction(
                        jw, members, target['layer'], target['z'], order,
                        dict(GR.PLAN_FAST), min_gain=1,
                        note='%s->%s partial' % (gname, label))
                    partial.update(group=gname, target_label=label,
                                   target_layer=int(target['layer']),
                                   target_z=float(target['z']),
                                   order='risk_desc', attempt_index=-1,
                                   old_heights={str(k): int(v) for k, v in
                                                before_counter.items()})
                    if partial.get('accepted'):
                        partial['new_heights'] = {
                            str(k): int(v) for k, v in
                            GR.group_height_counter(state, members).items()}
                        records.append(partial)
                    else:
                        records.append(partial)
                attempts.extend(records)
                attempts_by_group[gname] += 1
                tries += 1
                round_attempts += len(records)
                hit = [record for record in records if record.get('accepted')]
                if hit:
                    for record in hit:
                        record['new_heights'] = {
                            str(k): int(v) for k, v in
                            GR.group_height_counter(state, members).items()}
                        if record.get('migrated', len(members)) == len(members):
                            record['whole_group_migration'] = True
                    accepted.extend(hit)
                    accepted_groups.add(gname)
                    progressed += 1
                    tracker.consider(state, note='g4a %s -> %s' % (
                        gname, label))
                    refresh()
                    crossings = GR.manual_route_crossings(state, manual_set)
                    break
                fail_count[(gname, label)] += 1
        rounds.append(dict(round=round_index, accepted=int(progressed),
                           attempts=int(round_attempts),
                           total=int(state.total),
                           seconds=round(budget.elapsed(), 1)))
        log('[g4a] P2 round %d done: accepted=%d total=%d (%.0fs)'
            % (round_index, progressed, state.total, budget.elapsed()))
        if progressed == 0:
            break
        if time.time() - last_checkpoint >= GR.CHECKPOINT_SECONDS:
            GR.checkpoint(ctx, jw, log, extra=dict(phase='G4a_group',
                                                   accepted=len(accepted)))
            last_checkpoint = time.time()

    # ---------------------------------------------------------- p2b partial
    partial_attempts = []
    if not args.no_partial_fallback and budget.fraction() < 0.80:
        log('[g4a] P2b: partial group migration fallback (SPEC §4 allowed)')
        crossings = GR.manual_route_crossings(state, manual_set)
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        for gname in sorted(groups_now, key=lambda g: -group_cross[g]):
            if budget.search_over() or budget.fraction() > 0.82:
                break
            if gname in accepted_groups:
                continue
            members = groups_now[gname]
            counter = GR.group_height_counter(state, members)
            majority = GR.majority_height_label(counter)
            targets = GR.rank_group_targets(state, gname, members, feas, loads,
                                            crossings,
                                            current_labels=set(counter),
                                            plane_events=plane_events)
            for target in targets[:2]:
                if budget.search_over():
                    break
                label = str(target['label'])
                if fail_count[(gname, label)] >= 2:
                    continue
                order = GR.order_members(state, members, 'risk_desc',
                                         crossings=crossings,
                                         target_z=float(target['z']))
                record = GR.partial_group_transaction(
                    jw, members, target['layer'], target['z'], order,
                    dict(GR.PLAN_STD, **GR.PLAN_STD), min_gain=1,
                    note='%s->%s partial' % (gname, label))
                record.update(group=gname, target_label=label,
                              target_layer=int(target['layer']),
                              target_z=float(target['z']), order='risk_desc',
                              attempt_index=-1,
                              old_heights={str(k): int(v)
                                           for k, v in counter.items()})
                if record.get('accepted'):
                    record['new_heights'] = {
                        str(k): int(v) for k, v in
                        GR.group_height_counter(state, members).items()}
                    accepted.append(record)
                    accepted_groups.add(gname)
                    tracker.consider(state, note='g4a partial %s -> %s' % (
                        gname, label))
                    refresh()
                    crossings = GR.manual_route_crossings(state, manual_set)
                    log('[g4a] P2b accepted partial %s -> %s migrated=%d/%d '
                        'gain=%d' % (gname, label, record.get('migrated'),
                                     len(members), record.get('gain')))
                    break
                partial_attempts.append(record)
                fail_count[(gname, label)] += 1
            if time.time() - last_checkpoint >= GR.CHECKPOINT_SECONDS:
                GR.checkpoint(ctx, jw, log, extra=dict(phase='G4a_partial'))
                last_checkpoint = time.time()
        GP.write_json(out_dir / 'partial_attempts.json',
                      dict(count=len(partial_attempts),
                           attempts=partial_attempts))

    # ------------------------------------------------------------------ p3
    tune_rounds = 1 if args.quick else args.tune_rounds
    tune_attempts = []
    for tune_round in range(1, int(tune_rounds) + 1):
        if budget.search_over() or budget.fraction() > args.tune_fraction:
            break
        log('[g4a] P3 micro-tune round %d' % tune_round)
        crossings = GR.manual_route_crossings(state, manual_set)
        groups_now = GR.manual_group_members(state)
        group_cross = GR.group_crossing_sums(crossings, groups_now)
        progressed = 0
        for gname in sorted(groups_now, key=lambda g: -group_cross[g]):
            if budget.search_over() or \
                    budget.fraction() > args.tune_fraction:
                break
            members = groups_now[gname]
            crossing_members = sorted(
                [rid for rid in members if crossings.get(rid, 0) > 0],
                key=lambda rid: (-crossings.get(rid, 0), rid))
            subset = crossing_members[:max(args.tune_min, args.tune_size)]
            if len(subset) < args.tune_min:
                continue
            counter = GR.group_height_counter(state, members)
            majority = GR.majority_height_label(counter)
            layer, z_mm = GR.label_plane(majority)
            target = dict(layer=int(layer), z=float(z_mm), label=majority)
            before = dict(counter)
            records = GR.attempt_group_target(
                jw, gname, subset, target, crossings, budget, log,
                cfg_variants=[GR.PLAN_STD, GR.PLAN_WIDE],
                order_variants=['crossing_desc', 'risk_desc'],
                max_retries=1)
            for record in records:
                record['kind'] = 'micro_tune'
                record['tune_round'] = tune_round
                record['old_heights'] = {str(k): int(v)
                                         for k, v in before.items()}
            tune_attempts.extend(records)
            hit = [record for record in records if record.get('accepted')]
            if hit:
                for record in hit:
                    record['new_heights'] = {
                        str(k): int(v) for k, v in
                        GR.group_height_counter(state, members).items()}
                accepted.extend(hit)
                progressed += 1
                tracker.consider(state, note='g4a tune %s' % gname)
                crossings = GR.manual_route_crossings(state, manual_set)
                log('[g4a] P3 accepted tune %s routes=%d gain=%d total=%d'
                    % (gname, len(subset), hit[0].get('gain'), state.total))
        if progressed == 0:
            break

    return dict(attempts=attempts, partial_attempts=partial_attempts,
                tune_attempts=tune_attempts, accepted=accepted,
                rounds=rounds, feasibility=feas,
                start_events=start_events, start_group_heights=start_group_heights,
                start_floor=start_floor, start_routes=start_routes,
                groups=groups, manual_set=manual_set,
                accepted_groups=accepted_groups)


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir) if args.out_dir else GP.ARM_DIRS[ARM]
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.quick:
        args.max_rounds = min(args.max_rounds, 1)
        args.max_reps = 1
        args.attempts_per_group_round = min(args.attempts_per_group_round, 2)
        args.max_group_attempts = min(args.max_group_attempts, 3)
        args.tune_rounds = 1
        args.tune_size = 6
        args.feasibility_cap_seconds = 20.0
    log = GR.Logger(out_dir / 'run.log')
    log('=' * 78)
    log('[g4a] start: budget=%.0fs seed=%d partial_fallback=%s quick=%s' % (
        args.budget_seconds, args.seed, not args.no_partial_fallback,
        args.quick))
    cfg = dict(arm=ARM, quick=bool(args.quick),
               plan_std=GR.PLAN_STD, plan_wide=GR.PLAN_WIDE,
               max_rounds=args.max_rounds,
               attempts_per_group_round=args.attempts_per_group_round,
               max_group_attempts=args.max_group_attempts,
               max_retries=args.max_retries,
               partial_fallback=not args.no_partial_fallback,
               tune_rounds=args.tune_rounds, tune_size=args.tune_size,
               tag=args.tag, spec='experiments/xyz_joint_g4_1024/SPEC_G4.md')
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
    result = dict(attempts=[], accepted=[], rounds=[], tune_attempts=[],
                  partial_attempts=[], feasibility=OrderedDict(),
                  start_events=dict(manual_manual=0, manual_non=0,
                                    non_manual=0, per_route={}),
                  start_group_heights=OrderedDict(),
                  start_floor=int(state.total), start_routes={},
                  groups=GR.manual_group_members(state),
                  manual_set=GR.manual_ids(state), accepted_groups=set())
    try:
        result = search_g4a(ctx, jw, tracker, budget, args, log)
    except Exception as error:  # noqa: BLE001 - always finalise a legal state
        log('[g4a] SEARCH EXCEPTION %s: %s' % (type(error).__name__, error))
        import traceback
        log(traceback.format_exc()[-4000:])
    # ------------------------------------------------------------ finalise
    state = ctx.state
    manual_set = result.get('manual_set') or GR.manual_ids(state)
    groups = result.get('groups') or GR.manual_group_members(state)
    start_routes = result.get('start_routes') or {
        int(r['route_id']): r for r in ctx.baseline['routes']}
    attempts = list(result.get('attempts') or [])
    partial_attempts = list(result.get('partial_attempts') or [])
    tune_attempts = list(result.get('tune_attempts') or [])
    accepted = list(result.get('accepted') or [])
    log('[g4a] search finished total=%d accepted_events=%d elapsed=%.0fs'
        % (state.total, len(accepted), budget.elapsed()))

    # global validation of the whole manual-U geometry
    geometry = state.validate_all(log=None)
    log('[g4a] state.validate_all: valid=%d violations=%d kinds=%s'
        % (geometry['valid'], len(geometry['violations']),
           geometry['violation_kinds']))
    start_crossings = result.get('start_events', {}).get('per_route') or {}
    crossings_now = GR.manual_route_crossings(state, manual_set)
    xy_evidence = GR.xy_change_evidence(start_routes, state, manual_set)
    matrix = GR.migration_matrix(state, groups)
    matrix_rows = GR.migration_matrix_rows(matrix)
    split_evidence = GR.split_group_evidence(state, groups)
    final_events = GR.manual_crossing_events(state)
    attempt_stats = _attempt_stats(attempts + partial_attempts + tune_attempts)
    accepted_full = [record for record in accepted
                     if record.get('whole_group_migration')]
    migration_summary = OrderedDict()
    for gname, members in groups.items():
        changed = sum(1 for rid in members
                      if GR.height_label_of_z(GR.primary_height(
                          state.routes[int(rid)])) !=
                      GR.height_label_of_z(GR.primary_height(
                          start_routes[int(rid)])))
        migration_summary[gname] = dict(
            members=len(members),
            start_heights={},
            final_heights={str(k): int(v) for k, v in
                           GR.group_height_counter(state, members).items()},
            routes_changed_height=int(changed),
            migrated=bool(changed > 0),
            accepted_transactions=int(sum(1 for record in accepted
                                          if record.get('group') == gname)))
    # start heights per group (from the G3 baseline geometry)
    class _StartState(object):
        pass
    start_state = _StartState()
    start_state.routes = start_routes
    for gname, members in groups.items():
        migration_summary[gname]['start_heights'] = {
            str(k): int(v) for k, v in
            GR.group_height_counter(start_state, members).items()}
    cross_delta = int(state.total) - int(GP.START_CROSSINGS)
    summary_payload = dict(
        arm=ARM,
        start_crossings=int(GP.START_CROSSINGS),
        final_crossings=int(state.total),
        crossing_delta=int(cross_delta),
        crossing_pairs=int(state.pairs),
        accepted_transactions=int(len(accepted)),
        accepted_whole_group_migrations=int(len(accepted_full)),
        accepted_partial_migrations=int(len([r for r in accepted
                                             if r.get('partial')])),
        groups=len(groups),
        manual_routes=int(len(manual_set)),
        routes_changed_height=int(xy_evidence['primary_height_changed_routes']),
        xy_evidence=xy_evidence,
        start_group_heights={g: {str(k): int(v) for k, v in counter.items()}
                             for g, counter in
                             (result.get('start_group_heights') or {}).items()},
        final_group_heights={g: {str(k): int(v) for k, v in counter.items()}
                             for g, counter in
                             GR.group_height_map(state, groups).items()},
        migration_matrix=matrix,
        migration_summary=migration_summary,
        split_group_evidence=split_evidence,
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
        ceiling_note='G4a only moves the 368 manual-U routes; the %d '
                     'non-manual-only crossings are immutable in this arm '
                     '(they belong to G4c/G4d).' % int(
                         result.get('start_events', {}).get('non_manual', 1213)),
        state_validate_all=dict(valid=int(geometry['valid']),
                                violations=int(len(
                                    geometry['violations'])),
                                kinds={str(k): int(v) for k, v in
                                       (geometry['violation_kinds'] or {}).items()}),
        ledger=ctx.ledger.summary(),
        search_wall_seconds=round(budget.elapsed(), 2),
        config=spec.as_dict())
    writes = {
        'group_attempts.json': dict(
            arm=ARM, stats=attempt_stats,
            attempts=attempts[:2000], partial_attempts=partial_attempts[:500],
            tune_attempts=tune_attempts[:500]),
        'group_migration.json': summary_payload,
        'migration_matrix.csv': matrix_rows,
        'micro_tune.json': dict(
            arm=ARM, rounds=args.tune_rounds,
            attempts=tune_attempts, accepted=int(len(
                [r for r in tune_attempts if r.get('accepted')]))),
        'xy_evidence.json': xy_evidence,
        'failure_taxonomy.json': GR.failure_taxonomy(
            attempts + partial_attempts + tune_attempts,
            budget_exhausted=bool(budget.search_over()),
            extra=dict(arm=ARM,
                       search_wall_seconds=round(budget.elapsed(), 2),
                       budget_cap_seconds=float(args.budget_seconds))),
    }
    state.failed_attempts = [
        dict(route_id=record.get('failed_rid'),
             reason=str(record.get('failure_reason')),
             group=str(record.get('group')),
             target=str(record.get('target_label')),
             note=str(record.get('note')))
        for record in (attempts + partial_attempts + tune_attempts)
        if not record.get('accepted')][:2000]
    extra = dict(
        arm=ARM,
        phase_results=dict(
            group_phase=dict(rounds=result.get('rounds') or [],
                             attempts=len(attempts),
                             accepted=int(len(accepted))),
            partial_phase=dict(attempts=len(partial_attempts),
                               accepted=int(len([r for r in
                                                 partial_attempts
                                                 if r.get('accepted')]))),
            tune_phase=dict(attempts=len(tune_attempts),
                            accepted=int(len([r for r in tune_attempts
                                              if r.get('accepted')])))),
        attempt_stats=attempt_stats,
        accepted_migrations=[
            dict(group=record.get('group'),
                 target_label=record.get('target_label'),
                 target_z=record.get('target_z'),
                 old_heights=record.get('old_heights'),
                 new_heights=record.get('new_heights'),
                 gain=int(record.get('gain') or 0),
                 members=int(record.get('members') or 0),
                 migrated=int(record.get('migrated') or
                              record.get('members') or 0),
                 partial=bool(record.get('partial')),
                 order=record.get('order'),
                 seconds=record.get('seconds'))
            for record in accepted],
        feasibility_cells=int(sum(len(v) for v in
                                  (result.get('feasibility') or {}).values())),
        outside_band_attempts=int(sum(
            1 for record in attempts + partial_attempts
            if str(record.get('target_label')) not in GR.START_BANDS)),
        final_crossings=int(state.total),
        search_wall_seconds=round(budget.elapsed(), 2),
        tag=args.tag)
    validation = GR.finalize_arm(
        ctx, jw, tracker, extra=extra, writes=writes, log=log,
        validate=not args.no_validate)
    arm_summary = dict(summary_payload)
    arm_summary['validation'] = validation.get('validation_summary') or {}
    arm_summary['total_search_and_validation_seconds'] = round(
        spec.elapsed(), 2)
    GP.write_json(out_dir / 'arm_summary.json', arm_summary)
    log('[g4a] DONE final_crossings=%d start=%d delta=%d validation=%s' % (
        state.total, GP.START_CROSSINGS, cross_delta,
        json.dumps(validation.get('validation_summary') or {},
                   ensure_ascii=False)))
    log('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
