# -*- coding: utf-8 -*-
"""G4a / G4b manual-U group re-planning utilities (owner: g4-group).

Shared building blocks of the two group-replanning arms of ``SPEC_G4.md``:

* exact failure classification (SPEC §6 keys) for forced-height candidate plans
  and for whole joint transactions;
* an explicit **rollback repair** (the shared engine's ``Transaction._rollback``
  leaves stale per-height D56 entries for placed routes whose restored geometry
  lives on other heights -- see ``repair_after_rollback``);
* per-group / per-route height feasibility scans built on the frozen
  ``JointWorld.plan_forced`` candidate library (no new geometry code);
* whole-group joint transactions (rip group -> re-plan every member at one
  forced body height -> exact recount -> all-or-nothing accept);
* migration-matrix / real-grouping / XY-projection-change evidence builders;
* arm finalisation (best_valid snapshot, standard artifact set, independent
  validator in a frozen subprocess).

No shared engine file is modified; every geometric decision still comes from
``local_reroute`` / ``route_builder`` / ``RouteWorld`` / ``JointWorld``.
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from ....d56.index import prepare as d56_prepare
from ...reheight21 import model as M
from .. import local_reroute as LR
from .. import route_builder as RB
from .. import world_adapter as WA
from . import artifacts as ART
from . import joint_world as JW
from . import paths as GP

# ---------------------------------------------------------------------------
# physical heights
# ---------------------------------------------------------------------------
BODY_PLANES = tuple((int(pid), float(RB.PLANE_Z[int(pid)]),
                     str(RB.PLANE_LABEL[int(pid)]))
                    for pid in RB.BODY_PLANE_IDS)
BODY_PLANE_Z = {pid: z for pid, z, _label in BODY_PLANES}
Z_TO_BODY = {round(z, 9): (pid, label) for pid, z, label in BODY_PLANES}

#: the eight start bands of the G3 manual-U solution (L2-L5, L10-L13)
START_BANDS = frozenset(('L2', 'L3', 'L4', 'L5', 'L10', 'L11', 'L12', 'L13'))
OUTSIDE_BANDS = tuple(label for _pid, _z, label in BODY_PLANES
                      if label not in START_BANDS)

#: SPEC §6 unified failure keys (+ documented extras)
FAILURE_REASONS = ('no_legal_xy_corridor', 'target_height_occupied',
                   'r15_geometry_rejected', 'transition_3d_conflict',
                   'lead_below_minimum', 'joint_rebuild_failed',
                   'legal_but_no_crossing_improvement', 'budget_exhausted',
                   'no_current_crossings', 'structure_error')
EXTRA_REASONS = ('already_at_height', 'prefilter_skipped')

#: candidate-generation presets (only keys of ``JointWorld.PLAN_CFG``)
PLAN_FAST = dict(max_lead_pairs=1, prescreen_candidates=80,
                 max_candidates=140, d56_top=8, bodies_per_pair=1,
                 max_return=2)
PLAN_STD = dict(max_lead_pairs=2, prescreen_candidates=120,
                max_candidates=200, d56_top=10, bodies_per_pair=2,
                max_return=3)
PLAN_WIDE = dict(max_lead_pairs=3, prescreen_candidates=180,
                 max_candidates=280, d56_top=14, bodies_per_pair=2,
                 max_return=4)

#: transaction gives up a target height when a single member has no candidate
MAX_TARGET_ROUTES = 140       # heuristic pre-filter for very crowded targets
CHECKPOINT_SECONDS = 300.0


# ---------------------------------------------------------------------------
# logging / budget
# ---------------------------------------------------------------------------
class Logger:
    """Timestamped tee logger writing ``<out_dir>/run.log``."""

    def __init__(self, path, echo=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = bool(echo)
        self.started = time.time()

    def __call__(self, message):
        line = '[%s %8.2fs] %s' % (time.strftime('%H:%M:%S'),
                                   time.time() - self.started, message)
        if self.echo:
            print(line, flush=True)
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')


class Budget:
    """Wall-clock + counted-budget guard (SPEC §3.2)."""

    def __init__(self, ctx, seconds, reserve=90.0):
        self.ctx = ctx
        self.seconds = float(seconds)
        self.reserve = float(reserve)
        self.started = time.time()

    def elapsed(self):
        return time.time() - self.started

    def remaining(self):
        return max(0.0, self.seconds - self.reserve - self.elapsed())

    def search_over(self):
        ctx = self.ctx
        ctx.ledger.data['wall_seconds'] = round(self.elapsed(), 2)
        if self.elapsed() >= self.seconds - self.reserve:
            return True
        budget = ctx.spec.budget or {}
        for key in ('route_3d_checks', 'd56_candidate_evals'):
            limit = budget.get(key)
            if limit is not None and \
                    int(ctx.ledger.data.get(key, 0)) >= int(limit):
                return True
        return False

    def fraction(self):
        return min(1.0, self.elapsed() / max(1e-9, self.seconds - self.reserve))


# ---------------------------------------------------------------------------
# state helpers
# ---------------------------------------------------------------------------
def manual_ids(state):
    return {int(rid) for rid in state.routes
            if str((state.routes[rid] or {}).get('manual_group') or '').strip()}


def manual_group_members(state):
    """``OrderedDict(group -> sorted [route_id])`` -- membership is immutable."""
    groups = OrderedDict()
    for rid in sorted(state.routes):
        group = str((state.routes[rid] or {}).get('manual_group') or '').strip()
        if group:
            groups.setdefault(group, []).append(int(rid))
    return OrderedDict(sorted(groups.items(), key=lambda item: item[0]))


def plane_loads(state, manual_set):
    """``{z: dict(layer, label, routes, manual, other)}`` of every body height."""
    out = {}
    for pid, z, label in BODY_PLANES:
        table = state.plane_prims.get(WA.plane_key(z)) or {}
        n_manual = sum(1 for rid in table if int(rid) in manual_set)
        out[z] = dict(layer=int(pid), z=float(z), label=str(label),
                      routes=len(table), manual=int(n_manual),
                      other=int(len(table) - n_manual))
    return out


def primary_height(route):
    return JW.primary_height(route)


def height_label_of_z(z_mm):
    if z_mm is None:
        return 'none'
    body = Z_TO_BODY.get(round(float(z_mm), 9))
    if body is not None:
        return body[1]
    return AB_height_label(z_mm)


def AB_height_label(z_mm):
    from . import arm_base as AB
    return AB.height_label(z_mm)


def current_route_heights(state):
    return {int(rid): primary_height(route) for rid, route in state.routes.items()}


def group_centroid(state, members):
    values = [primary_height(state.routes[int(rid)]) for rid in members]
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0


def group_height_counter(state, members):
    counter = Counter()
    for rid in members:
        z = primary_height(state.routes[int(rid)])
        counter[height_label_of_z(z)] += 1
    return counter


def majority_height_label(counter):
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def group_height_map(state, groups=None):
    groups = groups if groups is not None else manual_group_members(state)
    return OrderedDict((name, group_height_counter(state, members))
                       for name, members in groups.items())


def label_plane(label):
    """``(layer_id, z_mm)`` of a body height label."""
    for pid, z, name in BODY_PLANES:
        if name == str(label):
            return int(pid), float(z)
    raise KeyError('unknown body height label %r' % (label,))


# ---------------------------------------------------------------------------
# crossing bookkeeping (manual routes only -- cheap exact recount)
# ---------------------------------------------------------------------------
def manual_route_crossings(state, manual_set=None):
    """Exact crossing-event count of every manual route (endpoint counts)."""
    if manual_set is None:
        manual_set = manual_ids(state)
    out = {}
    for rid in sorted(manual_set):
        total = 0
        for z_key in (state._route_groups.get(int(rid)) or {}):
            total += int(state.route_plane_events(int(rid), z_key))
        out[int(rid)] = total
    return out


def group_crossing_sums(crossings, groups):
    return {name: int(sum(crossings.get(int(rid), 0) for rid in members))
            for name, members in groups.items()}


def manual_crossing_events(state):
    """(manual, non_manual, manual_non) crossing-event counts of the state."""
    per, cache = state.per_route_counts()
    manual_set = manual_ids(state)
    counts = Counter()
    for event in JW.crossing_events(state, cache=cache):
        a, b = int(event['route_a']), int(event['route_b'])
        a_man, b_man = a in manual_set, b in manual_set
        kinds = (a_man, b_man)
        counts[kinds] += 1
    return dict(manual_manual=int(counts[(True, True)]),
                manual_non=int(counts[(True, False)] + counts[(False, True)]),
                non_manual=int(counts[(False, False)]),
                crossing_events=int(cache.total()),
                crossing_pairs=int(cache.total_pairs()),
                per_route={int(rid): int(value) for rid, value in per.items()})


# ---------------------------------------------------------------------------
# failure classification (SPEC §6)
# ---------------------------------------------------------------------------
def classify_builder_reason(reason):
    reason = str(reason or '').lower()
    if 'lead' in reason:
        return 'lead_below_minimum'
    if 'r15' in reason or 'radius' in reason or 'transition' in reason:
        return 'r15_geometry_rejected'
    if 'structure' in reason or 'gap' in reason or 'tangent' in reason:
        return 'structure_error'
    return 'no_legal_xy_corridor'


def classify_violation_kind(kind):
    kind = str(kind or '').lower()
    if 'lead' in kind:
        return 'lead_below_minimum'
    if 'r15' in kind or 'radius' in kind:
        return 'r15_geometry_rejected'
    if 'structure' in kind or 'gap' in kind or 'junction' in kind \
            or 'tangent' in kind:
        return 'structure_error'
    if 'transition' in kind or 'clear' in kind or '3d' in kind or 'd56' in kind:
        return 'transition_3d_conflict'
    return 'transition_3d_conflict'


def dominant_reason(reason_counter):
    if not reason_counter:
        return None
    return str(Counter(reason_counter).most_common(1)[0][0])


# ---------------------------------------------------------------------------
# rollback repair (shared engine bug workaround)
# ---------------------------------------------------------------------------
def repair_after_rollback(state, rids):
    """Rebuild the per-height D56 bookkeeping of ``rids`` from ``state.routes``.

    ``JointWorld.Transaction._rollback`` restores ``state.routes``/``world`` but
    does not drop the placed routes' entries on heights that are absent from
    their restored geometry; those stale ``plane_prims`` rows inflate the next
    exact recount.  This routine removes every per-height entry of the routes,
    re-inserts the authoritative restored geometry and recounts only the touched
    heights.  It is idempotent and cheap (<= 22 body heights x len(rids)).
    """
    rids = sorted({int(rid) for rid in rids})
    if not rids:
        return 0
    rid_set = set(rids)
    affected = set()
    for z_key, table in list(state.plane_prims.items()):
        for rid in rids:
            if rid in table:
                affected.add(z_key)
                break
    for rid in rids:
        affected.update(WA.route_flat_groups(state.routes[rid]))
    # remove every entry of the routes on the touched heights
    for z_key in sorted(affected):
        index = state.planes.get(z_key)
        prims = state.plane_prims.setdefault(z_key, {})
        chains = state.plane_chains.setdefault(z_key, {})
        for rid in rids:
            if rid in chains:
                if index is not None:
                    index.remove(rid)
                chains.pop(rid, None)
            prims.pop(rid, None)
    # re-insert the authoritative restored geometry
    for rid in rids:
        groups = WA.route_flat_groups(state.routes[rid])
        state._route_groups[rid] = groups
        for z_key, chains_list in groups.items():
            merged = []
            for chain in chains_list:
                merged.extend(dict(prim) for prim in chain)
            prepared = d56_prepare(merged)
            prims = state.plane_prims.setdefault(z_key, {})
            chains = state.plane_chains.setdefault(z_key, {})
            prims[rid] = merged
            chains[rid] = prepared
            index = state.planes.get(z_key)
            if index is None:
                index = WA.new_index()
                state.planes[z_key] = index
            index.add(rid, prepared)
            affected.add(z_key)
    JW.recount_subset(state, affected)
    state.obstacle_samples = state._build_obstacle_samples()
    state.obstacle_cache = {}
    state.prim_grids = {}
    return len(affected)


# ---------------------------------------------------------------------------
# individual forced-height diagnosis (clean state only)
# ---------------------------------------------------------------------------
def lead_pairs_for(state, rid, option, cfg):
    base = dict(JW.PLAN_CFG, **(cfg or {}))
    route = state.route(int(rid))
    lead_s, lead_t = RB.lead_lengths(route)
    if option['kind'] in ('xy_only', 'direct_xy'):
        return [(lead_s, lead_t)]
    pairs = []
    if lead_s > 0.0 and lead_t > 0.0:
        pairs.append((lead_s, lead_t))
    for lead in RB.LEAD_CANDIDATES:
        pair = (float(lead), float(lead))
        if any(abs(pair[0] - q[0]) < 1e-9 and abs(pair[1] - q[1]) < 1e-9
               for q in pairs):
            continue
        pairs.append(pair)
    return pairs[:max(1, int(base.get('max_lead_pairs', 2)))]


def forced_option(state, rid, layer, z_mm):
    row = state.row(int(rid))
    option = dict(kind='migrate', layer=int(layer), z=float(z_mm), load=0,
                  priority=0)
    if abs(float(z_mm) - float(row['interface_z_mm'])) < 1e-12:
        option = dict(kind='direct', layer=int(layer), z=float(z_mm), load=0,
                      priority=0)
    return option


def diagnose_forced(jw, rid, layer, z_mm, cfg, ledger=None):
    """Why does ``plan_forced`` return nothing for route ``rid`` at this height?

    Only valid while ``rid`` is present in the state (clean mode).  Replays the
    same candidate library and reports the dominant SPEC §6 reason.
    """
    state = jw.state
    ledger = ledger if ledger is not None else jw.ledger
    rid = int(rid)
    base = dict(JW.PLAN_CFG, **(cfg or {}))
    option = forced_option(state, rid, layer, z_mm)
    reasons = Counter()
    for lead_s, lead_t in lead_pairs_for(state, rid, option, base):
        try:
            task, _source, _target = LR.make_task_for_option(
                state, rid, option, lead_s, lead_t)
        except (RB.BuilderError, ValueError) as error:
            reasons[classify_builder_reason(getattr(error, 'reason', ''))] += 1
            continue
        bodies = LR.xy_candidates(state, rid, task, int(layer), float(z_mm),
                                  base)
        ledger.bump('d56_candidate_evals', int(base.get('d56_top', 16)))
        ledger.bump('xy_candidates_generated', len(bodies))
        if not bodies:
            reasons['no_legal_xy_corridor'] += 1
            continue
        built = 0
        for body_record in bodies[:int(base.get('max_return', 4))]:
            try:
                route = LR.build_route_candidate(state, rid, option, lead_s,
                                                 lead_t, body_record['body'])
            except (RB.BuilderError, ValueError) as error:
                reasons[classify_builder_reason(getattr(error, 'reason', ''))] += 1
                continue
            violations = state.check_3d(rid, route)
            ledger.bump('route_3d_checks')
            if violations:
                ledger.bump('rejected_3d')
                reasons[classify_violation_kind(
                    (violations[0] or {}).get('kind'))] += 1
                continue
            built += 1
            ledger.bump('valid_candidates')
        if built:
            return dict(reason='ok', detail='candidate_exists')
    return dict(reason=dominant_reason(reasons) or 'no_legal_xy_corridor',
                detail={str(k): int(v) for k, v in reasons.items()})


# ---------------------------------------------------------------------------
# height feasibility scan (all 19 body heights per group)
# ---------------------------------------------------------------------------
def _group_representatives(state, members, max_reps=3):
    """One representative route per distinct current body height (bounded)."""
    by_height = OrderedDict()
    for rid in members:
        label = height_label_of_z(primary_height(state.routes[int(rid)]))
        by_height.setdefault(label, []).append(int(rid))
    reps = []
    for label, rids in by_height.items():
        reps.append(rids[len(rids) // 2])
    if len(reps) > max_reps:
        step = len(reps) / float(max_reps)
        reps = [reps[min(len(reps) - 1, int(i * step))]
                for i in range(max_reps)]
    return reps


def feasibility_scan(jw, groups, budget, log, cfg=None, max_reps=3,
                     max_seconds=None):
    """Per-group forced-height feasibility over **all 19 body heights**.

    Reports, for each (group, height): representative route feasibility, the
    estimated crossing delta of the representative candidate, and the dominant
    rejection reason for the failures.  This is the G4a "explore every body
    height" evidence and the ranking signal of the group-level transactions.
    """
    state = jw.state
    cfg = dict(PLAN_STD, **(cfg or {}))
    out = OrderedDict()
    scan_started = time.time()
    for gname, members in groups.items():
        reps = _group_representatives(state, members, max_reps=max_reps)
        group_out = OrderedDict()
        for pid, z, label in BODY_PLANES:
            if budget.search_over():
                return out
            if max_seconds is not None and \
                    time.time() - scan_started >= float(max_seconds):
                log('[feas] scan stopped after %.1fs (partial scan)' % (
                    time.time() - scan_started))
                return out
            ok = 0
            tried = 0
            deltas = []
            reasons = Counter()
            for rid in reps:
                tried += 1
                cands = jw.plan_forced(rid, pid, z, cfg=cfg, mode='clean')
                if cands:
                    ok += 1
                    candidate = cands[0]
                    if candidate.delta is not None:
                        deltas.append(int(candidate.delta))
                else:
                    diagnosis = diagnose_forced(jw, rid, pid, z, cfg)
                    reasons[diagnosis['reason']] += 1
            mean_delta = (sum(deltas) / len(deltas)) if deltas else None
            group_out[label] = dict(
                layer=int(pid), z=float(z), label=str(label),
                reps=[int(r) for r in reps], tried=int(tried), ok=int(ok),
                ok_fraction=round(ok / float(max(1, tried)), 3),
                mean_clean_delta=None if mean_delta is None
                else round(float(mean_delta), 3),
                failures={str(k): int(v) for k, v in reasons.items()},
                outside_start_bands=bool(label not in START_BANDS))
            log('[feas] %-6s -> %-4s ok=%d/%d mean_delta=%s fail=%s' % (
                gname, label, ok, tried,
                None if mean_delta is None else round(mean_delta, 3),
                dict(reasons)))
        out[gname] = group_out
    return out


# ---------------------------------------------------------------------------
# orderings
# ---------------------------------------------------------------------------
def order_members(state, members, kind, crossings=None, target_z=None):
    """Reconstruction order of one transaction (SPEC §5 order sensitivity)."""
    members = [int(rid) for rid in members]
    crossings = crossings or {}
    if kind == 'crossing_desc':
        return sorted(members, key=lambda rid: (-int(crossings.get(rid, 0)),
                                                rid))
    if kind == 'crossing_asc':
        return sorted(members, key=lambda rid: (int(crossings.get(rid, 0)),
                                                rid))
    if kind == 'risk_desc':
        if target_z is None:
            return sorted(members)
        return sorted(members,
                      key=lambda rid: (-abs(float(primary_height(
                          state.routes[rid]) or 0.0) - float(target_z)), rid))
    if kind == 'risk_asc':
        if target_z is None:
            return sorted(members)
        return sorted(members,
                      key=lambda rid: (abs(float(primary_height(
                          state.routes[rid]) or 0.0) - float(target_z)), rid))
    if kind == 'shuffle':
        values = list(members)
        random.Random(20261104 + len(values)).shuffle(values)
        return values
    return sorted(members)


# ---------------------------------------------------------------------------
# whole-group joint transaction
# ---------------------------------------------------------------------------
def group_transaction(jw, members, layer, z_mm, order, cfg, min_gain=1,
                      note=''):
    """Rip the whole group, re-plan every member at the forced height, verify.

    All-or-nothing: any member without a candidate (or a final 3D violation)
    rolls the whole target height back.  The exact recount decides acceptance
    (``gain >= min_gain``).  Returns a structured record with the classified
    failure reason.
    """
    state = jw.state
    members = [int(rid) for rid in members]
    order = [int(rid) for rid in order if int(rid) in set(members)]
    started = time.time()
    tx = jw.transaction(members, note=note, min_gain=int(min_gain))
    tx.rip_all()
    placed = 0
    failed_rid = None
    failed_at = None
    try:
        for rid in order:
            candidate_started = time.time()
            cands = tx.plan(rid, forced=(int(layer), float(z_mm)), cfg=cfg)
            if not cands:
                failed_rid = int(rid)
                failed_at = placed
                break
            tx.place(rid, cands[0])
            placed += 1
        result = tx.finish()
    except Exception as error:  # noqa: BLE001 - keep the arm alive
        try:
            if tx._open:
                tx.abort('exception:%s' % type(error).__name__)
        except Exception:  # noqa: BLE001
            pass
        repair_after_rollback(state, members)
        return dict(accepted=False, placed=placed, failed_rid=failed_rid,
                    failure_reason='structure_error',
                    failure_detail='%s: %s' % (type(error).__name__, error),
                    delta=0, gain=0, total=int(state.total),
                    reasons={}, repaired=True,
                    seconds=round(time.time() - started, 2), note=str(note))
    repaired = False
    if not bool(result.get('accepted')):
        repair_after_rollback(state, members)
        repaired = True
    accepted = bool(result.get('accepted'))
    record = dict(
        accepted=accepted, placed=int(placed), members=len(members),
        failed_rid=failed_rid, failed_at=failed_at,
        delta=int(result.get('delta') or 0),
        gain=int(result.get('gain') or 0),
        old_total=int(result.get('old_total') or state.total),
        total=int(state.total),
        reasons={str(k): int(v) for k, v in (result.get('reasons') or {}).items()},
        per_plane={str(k): v for k, v in (result.get('per_plane') or {}).items()},
        repaired=bool(repaired), seconds=round(time.time() - started, 2),
        note=str(note))
    record['failure_reason'] = classify_transaction_failure(record)
    return record


def classify_transaction_failure(record):
    if record.get('accepted'):
        return 'accepted'
    if record.get('failed_rid') is not None:
        # the concrete reason is filled in by the caller (diagnose_forced)
        return 'no_legal_xy_corridor'
    reasons = record.get('reasons') or {}
    if reasons.get('final_3d_violation'):
        return 'transition_3d_conflict'
    if reasons.get('incomplete_set'):
        return 'joint_rebuild_failed'
    if int(record.get('delta') or 0) >= 0:
        return 'legal_but_no_crossing_improvement'
    return 'joint_rebuild_failed'


def attempt_group_target(jw, group, members, target, crossings, budget, log,
                         cfg_variants=None, order_variants=None,
                         max_retries=2, min_gain=1):
    """Try one (group -> forced height) migration with 2-3 order/lead strategies."""
    state = jw.state
    cfg_variants = list(cfg_variants or [PLAN_STD, PLAN_WIDE])
    order_variants = list(order_variants or ['risk_desc', 'crossing_desc',
                                             'crossing_asc'])
    layer, z_mm = int(target['layer']), float(target['z'])
    label = str(target.get('label') or height_label_of_z(z_mm))
    attempts = []
    failure_reason = None
    for attempt_index in range(min(int(max_retries) + 1, len(cfg_variants),
                                   len(order_variants))):
        if budget.search_over():
            failure_reason = 'budget_exhausted'
            break
        cfg = dict(PLAN_STD, **cfg_variants[attempt_index])
        order = order_members(state, members, order_variants[attempt_index],
                              crossings=crossings, target_z=z_mm)
        record = group_transaction(
            jw, members, layer, z_mm, order, cfg, min_gain=min_gain,
            note='%s->%s[%s]' % (group, label, order_variants[attempt_index]))
        record.update(group=str(group), target_label=label,
                      target_layer=int(layer), target_z=float(z_mm),
                      order=order_variants[attempt_index],
                      cfg={str(k): v for k, v in cfg.items()},
                      attempt_index=int(attempt_index))
        diagnosis = None
        if not record['accepted'] and record.get('failed_rid') is not None:
            diagnosis = diagnose_forced(jw, record['failed_rid'], layer, z_mm,
                                        cfg)
            if diagnosis['reason'] == 'ok':
                # the route has a candidate on its own but not together with
                # the already re-planned members -> joint rebuild conflict
                record['failure_reason'] = 'joint_rebuild_failed'
            else:
                record['failure_reason'] = diagnosis['reason']
            record['failure_diagnosis'] = diagnosis['detail']
        else:
            record['failure_reason'] = classify_transaction_failure(record)
        attempts.append(record)
        log('[grp] %s -> %-4s try%d order=%-13s accepted=%s placed=%d/%d '
            'delta=%d gain=%d reason=%s %.1fs' % (
                group, label, attempt_index, record['order'],
                record['accepted'], record['placed'], record['members'],
                record['delta'], record['gain'], record['failure_reason'],
                record['seconds']))
        if record['accepted']:
            return attempts
        failure_reason = record['failure_reason']
    if not attempts:
        attempts.append(dict(group=str(group), target_label=label,
                             accepted=False, failure_reason=failure_reason
                             or 'budget_exhausted'))
    return attempts


# ---------------------------------------------------------------------------
# partial group transaction (SPEC §4: some members may stay on their height)
# ---------------------------------------------------------------------------
def partial_group_transaction(jw, members, layer, z_mm, order, cfg,
                              min_gain=1, note='', min_migrated_fraction=0.75):
    """Whole-group migration where geometrically infeasible members stay put.

    ``SPEC_G4.md`` §4 allows a few members of a group to remain on their
    current height when the new height is geometrically infeasible for them
    (each such member is reported with its classified reason).  The target
    height is still accepted only when the *whole* group transaction is legal
    and the exact recount improves.
    """
    state = jw.state
    members = [int(rid) for rid in members]
    order = [int(rid) for rid in order if int(rid) in set(members)]
    started = time.time()
    tx = jw.transaction(members, note=note, min_gain=int(min_gain))
    tx.rip_all()
    placed = 0
    stayed = []
    failed_rid = None
    try:
        for rid in order:
            cands = tx.plan(rid, forced=(int(layer), float(z_mm)), cfg=cfg)
            if not cands:
                current_z = primary_height(state.routes[rid])
                fallback = None
                if current_z is not None:
                    body = Z_TO_BODY.get(round(float(current_z), 9))
                    if body is not None:
                        fallback = tx.plan(rid, forced=(int(body[0]),
                                                        float(current_z)),
                                           cfg=cfg)
                if not fallback:
                    failed_rid = int(rid)
                    break
                tx.place(rid, fallback[0])
                stayed.append(int(rid))
            else:
                tx.place(rid, cands[0])
            placed += 1
        result = tx.finish()
    except Exception as error:  # noqa: BLE001
        try:
            if tx._open:
                tx.abort('exception:%s' % type(error).__name__)
        except Exception:  # noqa: BLE001
            pass
        repair_after_rollback(state, members)
        return dict(accepted=False, placed=placed, failed_rid=failed_rid,
                    failure_reason='structure_error',
                    failure_detail='%s: %s' % (type(error).__name__, error),
                    delta=0, gain=0, total=int(state.total), reasons={},
                    stayed=[], partial=True, repaired=True,
                    seconds=round(time.time() - started, 2), note=str(note))
    repaired = False
    if not bool(result.get('accepted')):
        repair_after_rollback(state, members)
        repaired = True
    migrated = max(0, int(placed) - len(stayed))
    record = dict(
        accepted=bool(result.get('accepted')),
        placed=int(placed), members=len(members),
        migrated=int(migrated), stayed_at_original_height=len(stayed),
        min_migrated_fraction=float(min_migrated_fraction),
        failed_rid=failed_rid,
        delta=int(result.get('delta') or 0),
        gain=int(result.get('gain') or 0),
        old_total=int(result.get('old_total') or state.total),
        total=int(state.total),
        reasons={str(k): int(v) for k, v in (result.get('reasons') or {}).items()},
        per_plane={str(k): v for k, v in (result.get('per_plane') or {}).items()},
        stayed_route_ids=[int(rid) for rid in stayed],
        partial=True, repaired=bool(repaired),
        seconds=round(time.time() - started, 2), note=str(note))
    if record['accepted']:
        record['failure_reason'] = 'accepted'
        record['whole_group_migration'] = bool(
            migrated >= int(round(min_migrated_fraction * len(members))))
    else:
        record['failure_reason'] = classify_transaction_failure(record)
    return record


# ---------------------------------------------------------------------------
# G4a target-height ranking
# ---------------------------------------------------------------------------
def rank_group_targets(state, group, members, feasibility, loads, crossings,
                       current_labels=None, plane_events=None):
    """Ordered forced-height targets of one group.

    Order = (representative feasibility tier) -> current crossing events on the
    target height (fewer is better) -> predicted clean crossing gain of the
    representative replacement -> non-manual route load -> height distance.
    """
    centroid = group_centroid(state, members)
    majority = majority_height_label(group_height_counter(state, members))
    plane_events = plane_events or {}
    rows = []
    for pid, z, label in BODY_PLANES:
        info = (feasibility.get(group) or {}).get(label) or {}
        ok_fraction = float(info.get('ok_fraction') or 0.0)
        load = loads[z]
        estimate = info.get('mean_clean_delta')
        estimate = None if estimate is None else float(estimate)
        rows.append(dict(
            layer=int(pid), z=float(z), label=str(label),
            load=int(load['routes']), other=int(load['other']),
            manual=int(load['manual']),
            plane_events=int(plane_events.get(z) or plane_events.get(
                round(float(z), 9)) or 0),
            outside_start_bands=bool(label not in START_BANDS),
            ok_fraction=round(ok_fraction, 3),
            estimate_clean_delta=estimate,
            distance=round(abs(float(z) - centroid), 4),
            is_majority=bool(label == majority),
            is_current=bool(current_labels and label in current_labels)))
    # targets whose whole group is clearly infeasible go last, but stay in the
    # plan so that every body height gets an explicit attempt record.
    def _gain(row):
        estimate = row['estimate_clean_delta']
        return 0.0 if estimate is None else max(0.0, -float(estimate))

    rows.sort(key=lambda row: (
        0 if row['ok_fraction'] >= 0.999 else (1 if row['ok_fraction'] > 0 else 2),
        row['plane_events'],
        -_gain(row),
        row['other'], row['distance'], row['label']))
    # interleave outside-band heights early so the outside-band exploration
    # (SPEC / task requirement) is guaranteed within the first few attempts
    inside = [row for row in rows if not row['outside_start_bands']]
    outside = [row for row in rows if row['outside_start_bands']]
    order = []
    outside_left = list(outside)
    inside_left = list(inside)
    while inside_left or outside_left:
        if inside_left:
            order.append(inside_left.pop(0))
        if outside_left:
            order.append(outside_left.pop(0))
    return order


# ---------------------------------------------------------------------------
# G4b target ranking for individual / cluster moves
# ---------------------------------------------------------------------------
def rank_route_targets(state, rid, loads, feasibility=None, group=None,
                       exclude_z=None, max_load=MAX_TARGET_ROUTES):
    """Ordered body-height targets of a single manual route."""
    current = primary_height(state.routes[int(rid)])
    rows = []
    for pid, z, label in BODY_PLANES:
        if exclude_z is not None and abs(float(z) - float(exclude_z)) < 1e-9:
            continue
        load = loads[z]
        if load['routes'] >= int(max_load):
            continue
        info = ((feasibility or {}).get(group) or {}).get(label) or {}
        rows.append(dict(layer=int(pid), z=float(z), label=str(label),
                         load=int(load['routes']), other=int(load['other']),
                         ok_fraction=float(info.get('ok_fraction') or 0.0),
                         distance=round(abs(float(z) - float(current)), 4)
                         if current is not None else 0.0,
                         outside_start_bands=bool(label not in START_BANDS)))
    rows.sort(key=lambda row: (0 if row['ok_fraction'] >= 0.999 else 1,
                               row['other'], row['distance'], row['label']))
    return rows


# ---------------------------------------------------------------------------
# group / geometry evidence
# ---------------------------------------------------------------------------
def migration_matrix(state, groups, start_labels=None):
    """Original group -> physical body height distribution (final state)."""
    out = OrderedDict()
    for gname, members in groups.items():
        counter = Counter()
        zsum = defaultdict(float)
        for rid in members:
            label = height_label_of_z(primary_height(state.routes[int(rid)]))
            counter[label] += 1
            z = primary_height(state.routes[int(rid)])
            zsum[label] = float(z) if z is not None else 0.0
        out[gname] = OrderedDict(
            (label, dict(count=int(count), z_mm=round(zsum[label], 6),
                         outside_start_bands=bool(label not in START_BANDS)))
            for label, count in sorted(counter.items()))
    return out


def migration_matrix_rows(matrix):
    rows = []
    for gname, dist in matrix.items():
        for label, info in dist.items():
            rows.append(dict(old_group=gname, new_height_label=label,
                             new_z_mm=info['z_mm'], count=info['count'],
                             outside_start_bands=info['outside_start_bands']))
    return rows


def _prim_points(prim):
    kind = prim.get('kind')
    out = []
    if kind == 'line':
        out.append((float(prim['p0'][0]), float(prim['p0'][1])))
        out.append((float(prim['p1'][0]), float(prim['p1'][1])))
    else:
        center = prim.get('center') or (0.0, 0.0)
        radius = float(prim.get('radius') or 0.0)
        start = float(prim.get('start_angle') or 0.0)
        sweep = float(prim.get('sweep') or 0.0)
        out.append((float(prim['p0'][0]), float(prim['p0'][1])))
        out.append((float(prim['p1'][0]), float(prim['p1'][1])))
        angle = start + 0.5 * sweep
        out.append((float(center[0]) + radius * math.cos(angle),
                    float(center[1]) + radius * math.sin(angle)))
    return out


def body_points(route):
    points = []
    for index in RB.body_part_indices(route):
        part = route['parts'][index]
        for prim in part.get('primitives') or ():
            points.extend(_prim_points(prim))
    return points


def _mean_nearest(points_a, points_b):
    def one_way(points, others):
        if not points or not others:
            return 0.0
        total = 0.0
        for x, y in points:
            best = min((x - ox) * (x - ox) + (y - oy) * (y - oy)
                       for ox, oy in others)
            total += math.sqrt(best)
        return total / len(points)
    return 0.5 * (one_way(points_a, points_b) + one_way(points_b, points_a))


def _arc_params(route):
    arcs = []
    for index in RB.body_part_indices(route):
        part = route['parts'][index]
        for prim in part.get('primitives') or ():
            if prim.get('kind') == 'arc':
                arcs.append((tuple(round(float(v), 6) for v in prim['center']),
                             round(float(prim['radius']), 6),
                             round(float(prim['start_angle']), 9),
                             round(float(prim['sweep']), 9)))
    return arcs


def xy_change_evidence(start_routes, state, manual_set=None, detail_limit=60):
    """Real XY-projection change evidence (signature / displacement / R15 arcs)."""
    manual_set = manual_set if manual_set is not None else manual_ids(state)
    changed_routes = []
    arc_changed = 0
    arc_count_changed = 0
    full_changed = 0
    heights_changed = 0
    displacements = []
    for rid in sorted(manual_set):
        old = start_routes.get(int(rid))
        new = state.routes[int(rid)]
        old_sig = RB.body_xy_signature(old)
        new_sig = RB.body_xy_signature(new)
        old_arcs = _arc_params(old)
        new_arcs = _arc_params(new)
        if old_arcs != new_arcs:
            arc_changed += 1
            if len(old_arcs) != len(new_arcs):
                arc_count_changed += 1
        if RB.route_signature(old) != RB.route_signature(new):
            full_changed += 1
        old_height = primary_height(old)
        new_height = primary_height(new)
        if old_height is None or new_height is None or \
                abs(float(old_height) - float(new_height)) > 1e-9:
            heights_changed += 1
        if old_sig == new_sig:
            continue
        displacement = _mean_nearest(body_points(old), body_points(new))
        displacements.append(displacement)
        changed_routes.append(dict(route_id=int(rid), displacement_mm=round(
            displacement, 4), old_group=str(old.get('manual_group') or ''),
            old_height_label=height_label_of_z(old_height),
            new_height_label=height_label_of_z(new_height)))
    count = len(displacements)
    return dict(
        manual_route_count=int(len(manual_set)),
        body_xy_signature_changed_count=int(count),
        body_xy_signature_changed_fraction=round(
            count / float(max(1, len(manual_set))), 4),
        r15_arc_parameter_changed_count=int(arc_changed),
        r15_arc_count_changed_routes=int(arc_count_changed),
        full_route_signature_changed_count=int(full_changed),
        primary_height_changed_routes=int(heights_changed),
        mean_body_xy_displacement_mm=round(
            sum(displacements) / count, 4) if count else 0.0,
        median_body_xy_displacement_mm=round(
            sorted(displacements)[count // 2], 4) if count else 0.0,
        max_body_xy_displacement_mm=round(max(displacements), 4)
        if displacements else 0.0,
        changed_routes=changed_routes[:int(detail_limit)],
        changed_routes_truncated=bool(count > int(detail_limit)))


def grouping_report(state, groups):
    """Real grouping of the manual U routes (body height x original group)."""
    clusters = OrderedDict()
    for gname, members in groups.items():
        for rid in members:
            label = height_label_of_z(primary_height(state.routes[int(rid)]))
            clusters.setdefault((label, gname), []).append(int(rid))
    out = OrderedDict()
    for (label, gname), rids in sorted(clusters.items()):
        out['%s|%s' % (label, gname)] = dict(height_label=label,
                                            old_group=gname,
                                            members=len(rids),
                                            route_ids=sorted(rids))
    by_height = OrderedDict()
    for (label, gname), rids in sorted(clusters.items()):
        by_height.setdefault(label, []).append(gname)
    return dict(cluster_count=len(out), clusters=out,
                heights=by_height,
                merged_clusters=[dict(height_label=label, old_groups=names)
                                 for label, names in by_height.items()
                                 if len(names) > 1],
                split_groups=sorted(
                    {gname for gname in groups
                     if len({label for label, name in clusters
                             if name == gname}) > 1}))


def split_group_evidence(state, groups):
    """Which original groups occupy more than one body height (split groups)."""
    out = OrderedDict()
    for gname, members in groups.items():
        counter = group_height_counter(state, members)
        out[gname] = dict(distribution={str(label): int(count)
                                        for label, count in counter.items()},
                          height_count=int(len(counter)),
                          split=bool(len(counter) > 1))
    return out


# ---------------------------------------------------------------------------
# failure taxonomy (SPEC §6: all eight classes are always enumerated)
# ---------------------------------------------------------------------------
def _normalize_failure_key(reason):
    reason = str(reason or '').strip()
    if reason in FAILURE_REASONS:
        return reason
    if reason in EXTRA_REASONS:
        return None
    if reason in ('ok', 'accepted', ''):
        return 'joint_rebuild_failed'
    if reason.startswith('exception') or reason == 'structure_error':
        return 'structure_error'
    if 'lead' in reason:
        return 'lead_below_minimum'
    if 'r15' in reason or 'radius' in reason:
        return 'r15_geometry_rejected'
    if 'transition' in reason or '3d' in reason:
        return 'transition_3d_conflict'
    if 'candidate' in reason or 'corridor' in reason:
        return 'no_legal_xy_corridor'
    return 'joint_rebuild_failed'


def failure_taxonomy(attempts, budget_exhausted=False, extra=None):
    """Count the SPEC §6 failure classes (all eight always enumerated).

    Every failure record is mapped onto the unified eight class keys; the
    non-SPEC bookkeeping keys (``already_at_height`` / ``prefilter_skipped``)
    are reported separately.  Nested candidate-level diagnoses are aggregated
    as well (they explain which class the concrete geometry failure had).
    """
    counts = Counter()
    extras = Counter()
    nested = Counter()
    kinds = Counter()
    for record in attempts:
        if record.get('accepted'):
            continue
        reason = str(record.get('failure_reason') or 'unknown')
        key = _normalize_failure_key(reason)
        if key is None:
            extras[reason] += 1
        else:
            counts[key] += 1
        kinds[str(record.get('kind') or '')] += 1
        diagnosis = record.get('failure_diagnosis')
        if isinstance(diagnosis, dict):
            for sub_key, sub_value in diagnosis.items():
                nested[str(sub_key)] += int(sub_value or 0)
    if budget_exhausted:
        counts['budget_exhausted'] += 1
    keys = OrderedDict()
    for reason in FAILURE_REASONS:
        keys[reason] = dict(count=int(counts.get(reason, 0)),
                            observed=bool(counts.get(reason, 0)),
                            note='')
    if counts.get('budget_exhausted'):
        keys['budget_exhausted']['note'] = (
            'search stopped because the wall-clock / counted budget cap was '
            'reached; the remaining planned attempts were not executed')
    if counts.get('joint_rebuild_failed'):
        keys['joint_rebuild_failed']['note'] = (
            'member candidate exists on its own but the joint transaction '
            'could not place the whole set (3D conflict with the already '
            're-planned members) -- legacy records may carry the old "ok" tag')
    payload = dict(
        schema='g4_failure_taxonomy_v1',
        spec_section='SPEC_G4.md §6',
        failure_classes=keys,
        observed_class_count=int(sum(1 for value in keys.values()
                                     if value['observed'])),
        total_failed_attempts=int(sum(counts.values()) + sum(extras.values())),
        extra_bookkeeping_keys={str(k): int(v) for k, v in extras.items()},
        nested_candidate_diagnoses={str(k): int(v) for k, v in
                                    nested.items()},
        failed_attempts_by_kind={str(k): int(v) for k, v in kinds.items()},
        note='every arm failure record is mapped onto exactly one of the eight '
             'SPEC §6 classes; classes with count=0 were not triggered by the '
             'accepted-search stream (the corresponding moves were either '
             'pre-filtered by the geometric necessity conditions or absent '
             'for this start point)')
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# finalisation
# ---------------------------------------------------------------------------
def extract_validation_summary(path):
    payload = {}
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    counts = payload.get('counts') or {}
    return dict(
        validation_pass=bool(payload.get('validation_pass')),
        violations=int(payload.get('violation_count') or 0),
        routed=counts.get('routed'),
        failed=counts.get('failed'),
        crossings=counts.get('same_plane_crossings'),
        crossing_pairs=counts.get('same_plane_crossing_pairs'),
        mid_transitions=counts.get('mid_transitions'),
        min_3d_clearance_mm=counts.get('min_3d_clearance_mm'),
        total_length_mm=counts.get('total_length_mm'),
        manual_policy=payload.get('manual_policy'),
        policy_violations=int((payload.get('policy_report') or {}).get(
            'violation_count') or 0))


def finalize_arm(ctx, jw, tracker, extra, writes, log, validate=True,
                 validator_out='validation'):
    """Save best_valid + standard artifacts + custom files + validator run."""
    state = ctx.state
    out_dir = Path(ctx.out_dir)
    ctx.jw = jw
    tracker.force_save(state, note='final')
    ctx.save_final(note='%s final' % ctx.spec.arm, extra=extra)
    for name, payload in writes.items():
        path = out_dir / name
        if str(name).endswith('.csv'):
            GP.write_csv_records(path, payload)
        else:
            GP.write_json(path, payload)
        log('[final] wrote %s' % path)
    validation_run = None
    validation_summary = {}
    if validate:
        log('[final] running independent validator (fully_optimizable) ...')
        validation_run = ART.run_validation(
            tracker.best_dir, out_dir / validator_out,
            baseline_dir=GP.AUTHORITY_DIR, manual_policy='fully_optimizable',
            python=sys.executable, log=log)
        validation_summary = extract_validation_summary(
            out_dir / validator_out / 'validation.json')
        GP.write_json(out_dir / 'validation_run.json', validation_run)
        GP.write_json(out_dir / 'validation_summary.json',
                      dict(validation_summary, **dict(
                          exit_code=validation_run.get('exit_code'),
                          seconds=validation_run.get('seconds'),
                          run_dir=str(tracker.best_dir))))
        log('[final] validation: %s' % json.dumps(validation_summary,
                                                  ensure_ascii=False))
    return dict(validation_run=validation_run,
                validation_summary=validation_summary)


def checkpoint(ctx, jw, log, extra=None):
    ctx.jw = jw
    ctx.save_checkpoint(extra=extra)
    log('[checkpoint] total=%d ledger=%s' % (ctx.state.total,
                                             ctx.ledger.summary()))
