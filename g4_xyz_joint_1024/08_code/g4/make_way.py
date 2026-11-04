# -*- coding: utf-8 -*-
"""Make-way / ruin-and-recreate joint transactions for the G4c / G4d search.

The G3 single-route optimizer is stuck at 1322 crossings because a route that
wants to migrate to a good height is blocked by the true-3D geometry of other
routes (their flat bodies at intermediate heights or their S-curve transitions).
This module implements the G4 answer: **one all-or-nothing joint transaction**
that rips up the target route *and* the routes that block it, re-plans them in
a chosen order (later routes see the earlier new geometry), and lets the shared
:class:`joint_world.Transaction` accept the whole set only when the exact
strict-D56 crossing count of every affected physical height drops.

Everything here uses only the frozen public engine APIs
(``JointWorld.transaction`` / ``Transaction.rip_all/plan/place/finish/abort``)
plus the frozen candidate library (``local_reroute`` / ``route_builder``) for
the *probe* step, which is a read-only clean-mode 3-D check that additionally
returns the exact blocking route ids (``violation['other_route']``).

Failure reasons use the SPEC_G4 section-6 string keys.
"""
from __future__ import annotations

import time
from collections import Counter

from ....l3d.world import World
from .. import local_reroute as LR
from .. import route_builder as RB
from .. import world_adapter as WA
from . import joint_world as JW
from . import ledger as L
from . import neighborhood as NB

# ---------------------------------------------------------------------------
# SPEC section-6 failure reasons (single vocabulary for every G4 arm)
# ---------------------------------------------------------------------------
R_NO_XY = 'no_legal_xy_corridor'
R_TARGET_OCC = 'target_height_occupied'
R_R15 = 'r15_geometry_rejected'
R_T3D = 'transition_3d_conflict'
R_LEAD = 'lead_below_minimum'
R_JOINT = 'joint_rebuild_failed'
R_NOGAIN = 'legal_but_no_crossing_improvement'
R_BUDGET = 'budget_exhausted'
R_NO_CROSS = 'no_current_crossings'
R_STRUCT = 'structure_error'

# ---------------------------------------------------------------------------
# candidate-generation configurations (cheap on purpose: the exact 3-D check in
# the transaction is what decides legality; more candidates rarely help here)
# ---------------------------------------------------------------------------
#: clean-mode probe of one forced height (2 lead pairs, <= 2 bodies)
PROBE_CFG = dict(max_target_layers=0, max_lead_pairs=2,
                 prescreen_candidates=80, max_candidates=110, d56_top=8,
                 bodies_per_pair=1, max_return=1, allow_direct=True,
                 allow_xy_only=False)
#: target route inside a make-way transaction (forced height, 2 lead pairs)
TARGET_CFG = dict(PROBE_CFG)
#: blocker re-planned at its own original height (1 lead pair)
BLOCKER_CFG = dict(max_target_layers=0, max_lead_pairs=1,
                   prescreen_candidates=60, max_candidates=80, d56_top=6,
                   bodies_per_pair=1, max_return=1, allow_direct=True,
                   allow_xy_only=False)
#: blocker fallback: free height (small)
BLOCKER_FREE_CFG = dict(max_target_layers=2, max_lead_pairs=1,
                        prescreen_candidates=70, max_candidates=90, d56_top=6,
                        bodies_per_pair=1, max_return=1, allow_direct=True,
                        allow_xy_only=False)
#: blocker last-resort fallback: body-only XY rebuild at its own height
BLOCKER_KEEP_CFG = dict(max_target_layers=0, max_lead_pairs=1,
                        prescreen_candidates=50, max_candidates=60, d56_top=5,
                        bodies_per_pair=1, max_return=1, allow_direct=False,
                        allow_xy_only=True)
#: greedy sweep: one lead pair, clean-mode exact delta (cheapest exact probe)
SWEEP_CFG = dict(max_target_layers=0, max_lead_pairs=1,
                 prescreen_candidates=70, max_candidates=90, d56_top=8,
                 bodies_per_pair=1, max_return=2, allow_direct=True,
                 allow_xy_only=False)
#: greedy sweep quality pass: more lead pairs / bodies (G3-grade candidates)
SWEEP_QUALITY_CFG = dict(max_target_layers=0, max_lead_pairs=2,
                         prescreen_candidates=110, max_candidates=150,
                         d56_top=16, bodies_per_pair=2, max_return=3,
                         allow_direct=True, allow_xy_only=False)


def _reason_from_builder(error):
    reason = str(getattr(error, 'reason', '') or '')
    if reason == 'lead_below_minimum':
        return R_LEAD
    if reason == 'structure':
        return R_R15
    if reason in ('no_transition_record', 'lifted_route_without_height_change'):
        return R_R15
    return R_NO_XY


def _bump_probe(ledger, cfg, n_bodies, n_checks, n_valid):
    """Mirror the shared engine's budget counters for our own probe pass."""
    if ledger is None:
        return
    ledger.bump('d56_candidate_evals', int(cfg.get('d56_top', 8)))
    ledger.bump('xy_candidates_generated', int(n_bodies))
    ledger.bump('route_3d_checks', int(n_checks))
    if n_valid:
        ledger.bump('valid_candidates', int(n_valid))


# ---------------------------------------------------------------------------
# read-only clean-mode probe: candidate at one forced height + exact delta
# ---------------------------------------------------------------------------
def probe_forced(jw, rid, layer, z_mm, cfg=None, ledger=None, max_eval=3):
    """Probe one route at one forced physical height (no state change).

    Returns::

        dict(rid, layer, z, ok=bool, candidates=[dict(route, delta, ...)],
             violations=[...], blockers=Counter({other_rid: count}),
             reasons=Counter(...), seconds=float)

    The candidate list is sorted by exact crossing delta (best first).  When
    every candidate is blocked the ``blockers`` counter names exactly which
    routes caused the true-3D violations, i.e. the make-way sets.
    """
    started = time.time()
    cfg = dict(PROBE_CFG, **(cfg or {}))
    state = jw.state
    rid = int(rid)
    layer = int(layer)
    z_mm = float(z_mm)
    row = state.row(rid)
    route0 = state.route(rid)
    outcome = dict(rid=rid, layer=layer, z=z_mm, ok=False, candidates=[],
                   violations=[], blockers=Counter(), reasons=Counter(),
                   seconds=0.0, n_bodies=0)
    if abs(z_mm - float(row['interface_z_mm'])) < 1e-12:
        option = dict(kind='direct', layer=layer, z=z_mm, load=0, priority=0)
    else:
        option = dict(kind='migrate', layer=layer, z=z_mm, load=0, priority=0)
    try:
        lead_pairs = LR._lead_pair_candidates(route0, option, cfg)
    except (RB.BuilderError, ValueError):
        outcome['reasons'][R_LEAD] += 1
        return outcome
    seen_blockers = Counter()
    candidates = []
    n_checks = 0
    n_valid = 0
    for lead_s, lead_t in lead_pairs:
        try:
            task, _source, _target = LR.make_task_for_option(
                state, rid, option, lead_s, lead_t)
        except (RB.BuilderError, ValueError) as error:
            outcome['reasons'][_reason_from_builder(error)] += 1
            continue
        bodies = LR.xy_candidates(state, rid, task, layer, z_mm, cfg)
        outcome['n_bodies'] += len(bodies)
        _bump_probe(ledger, cfg, len(bodies), 0, 0)
        if not bodies:
            outcome['reasons'][R_NO_XY] += 1
            continue
        for body_record in bodies[:int(cfg.get('max_return', 1))]:
            try:
                route = LR.build_route_candidate(state, rid, option, lead_s,
                                                 lead_t, body_record['body'])
            except (RB.BuilderError, ValueError) as error:
                outcome['reasons'][_reason_from_builder(error)] += 1
                continue
            structural = World.check_structure(route)
            n_checks += 1
            if ledger is not None:
                ledger.bump('route_3d_checks')
            if structural:
                if ledger is not None:
                    ledger.bump('rejected_3d')
                outcome['reasons'][R_STRUCT] += 1
                continue
            violations = _check_clean_mode(jw, rid, route)
            if violations:
                if ledger is not None:
                    ledger.bump('rejected_3d')
                outcome['violations'].extend(violations)
                for violation in violations:
                    other = violation.get('other_route')
                    if other is not None and int(other) != rid:
                        seen_blockers[int(other)] += 1
                outcome['reasons'][R_T3D] += 1
                continue
            n_valid += 1
            delta, per_plane = state.crossing_delta(rid, route)
            candidates.append(dict(
                route=route, delta=int(delta), per_plane=per_plane,
                layer=layer, z=z_mm, lead_s=float(lead_s),
                lead_t=float(lead_t), family=str(body_record.get('family') or ''),
                xy_crossings=int(body_record.get('crossings') or 0),
                length_mm=float(route.get('length_mm') or 0.0)))
    if n_valid and ledger is not None:
        ledger.bump('valid_candidates', n_valid)
    candidates.sort(key=lambda item: (item['delta'], item['length_mm']))
    outcome['candidates'] = candidates
    outcome['blockers'] = seen_blockers
    outcome['ok'] = bool(candidates)
    outcome['seconds'] = round(time.time() - started, 3)
    if not candidates and not outcome['reasons']:
        outcome['reasons'][R_NO_XY] += 1
    return outcome


def _check_clean_mode(jw, rid, route):
    """True-3-D violations of ``route`` against the *current* world without rid."""
    world = jw.raw_world()
    rid = int(rid)
    world.ignore_route(rid)
    try:
        return world.check_route(route, check_self=True)
    finally:
        world.restore_route(rid)


def plan_clean_forced(jw, rid, layer, z_mm, cfg=None):
    """Cheapest exact candidate at a forced height (shared clean-mode planner).

    Uses ``JointWorld.plan_forced(mode='clean')``: every returned candidate is
    already true-3-D checked against the current world and carries its **exact**
    crossing delta (``candidate.delta``), so committing it only needs the
    one-route transaction below.  This is the workhorse of the greedy sweep.
    """
    cfg = dict(SWEEP_CFG, **(cfg or {}))
    return jw.plan_forced(int(rid), int(layer), float(z_mm), cfg=cfg,
                          mode='clean')


def commit_planned(jw, rid, candidate, min_gain=1, note='migrate_clean'):
    """Commit an exact-checked clean-mode candidate without re-planning it.

    The route is placed directly into a one-route transaction, so the exact
    acceptance recount only touches the affected physical heights instead of
    recounting all 21 planes (``RouteWorld.commit``).
    """
    started = time.time()
    rid = int(rid)
    if isinstance(candidate, JW.PlanCandidate):
        route = candidate.route
    elif isinstance(candidate, dict):
        route = candidate.get('route') or candidate.get('candidate') or candidate
    else:
        route = candidate
    if not isinstance(route, dict) or 'target_layer' not in route:
        return dict(accepted=False, gain=0, delta=0, reason=R_JOINT,
                    rids=[rid], strategy='clean_commit', order=[rid],
                    seconds=round(time.time() - started, 3))
    tx = jw.transaction([rid], note=note, min_gain=int(min_gain))
    tx.rip_all()
    tx.place(rid, route)
    result = tx.finish()
    result.update(rids=[rid], strategy='clean_commit', order=[rid],
                  seconds=round(time.time() - started, 3))
    if not result['accepted']:
        result['reason'] = R_NOGAIN
    return result


def rank_heights_for_probe(jw, rid, frozen=None, index=None, limit=3,
                           max_frozen=0, cfg=None):
    """Cheapest-first list of probe heights for one route (see neighborhood)."""
    ranked = NB.rank_target_heights(jw.state, rid, frozen=frozen, index=index)
    if max_frozen is not None:
        rows = [row for row in ranked if row['n_frozen'] <= int(max_frozen)]
        if rows:
            ranked = rows
    return ranked[:int(limit)]


# ---------------------------------------------------------------------------
# blocker selection
# ---------------------------------------------------------------------------
def choose_blockers(jw, target_rid, blocker_scores, frozen=None, cap=3,
                    graph=None, index=None, extra_blockers=None):
    """Pick the make-way set: true-3D blockers first, then same-height occupants.

    ``blocker_scores`` maps candidate rid -> evidence weight (violation count
    / proximity).  Routes are ranked by evidence, then by their own crossing
    count (we prefer moving a route that is itself a crossing hot spot).
    """
    frozen = set(int(r) for r in (frozen or ()))
    scores = Counter()
    for rid, weight in (blocker_scores or {}).items():
        rid = int(rid)
        if rid == int(target_rid) or rid in frozen:
            continue
        scores[rid] += int(weight) if not isinstance(weight, float) else 1
    extra = extra_blockers or {}
    body = [int(r) for r in extra.get('body') or ()]
    transition = [int(r) for r in extra.get('transition') or ()]
    for rid in transition:
        if rid != int(target_rid) and rid not in frozen:
            scores[rid] += 2
    for rid in body:
        if rid != int(target_rid) and rid not in frozen:
            scores[rid] += 1
    if not scores:
        return []
    graph = graph
    counts = graph.per_route if graph is not None else Counter()
    ordered = sorted(scores.items(),
                     key=lambda item: (-item[1], -int(counts.get(item[0], 0)),
                                       item[0]))
    return [rid for rid, _score in ordered[:max(1, int(cap))]]


# ---------------------------------------------------------------------------
# order helpers (order sensitivity is a SPEC requirement)
# ---------------------------------------------------------------------------
def plan_order(rids, target_rid, strategy='target_first', graph=None, rng=None):
    rids = [int(rid) for rid in rids]
    target_rid = int(target_rid)
    others = [rid for rid in rids if rid != target_rid]
    counts = graph.per_route if graph is not None else Counter()
    if strategy == 'target_first':
        rest = sorted(others, key=lambda rid: (-int(counts.get(rid, 0)), rid))
        return [target_rid] + rest
    if strategy == 'blockers_first':
        rest = sorted(others, key=lambda rid: (-int(counts.get(rid, 0)), rid))
        return rest + [target_rid]
    if strategy == 'by_crossings':
        return sorted(rids, key=lambda rid: (-int(counts.get(rid, 0)),
                                            rid != target_rid, rid))
    if strategy == 'by_height':
        return sorted(rids, key=lambda rid: (rid != target_rid, rid))
    return list(rids)


def recreate_order(rids, strategy='desc', graph=None, rng=None, state=None):
    rids = [int(rid) for rid in rids]
    counts = graph.per_route if graph is not None else Counter()
    if strategy == 'desc':
        return sorted(rids, key=lambda rid: (-int(counts.get(rid, 0)), rid))
    if strategy == 'asc':
        return sorted(rids, key=lambda rid: (int(counts.get(rid, 0)), rid))
    if strategy == 'rid_desc':
        return sorted(rids, reverse=True)
    if strategy == 'rid_asc':
        return sorted(rids)
    if strategy == 'endpoint' and state is not None:
        def key(rid):
            row = state.row(rid)
            sx = float(row.get('source_xy', (0.0, 0.0))[0])
            sy = float(row.get('source_xy', (0.0, 0.0))[1])
            return (round(sx, 3), round(sy, 3), int(rid))
        return sorted(rids, key=key)
    if strategy == 'random':
        rng = rng or __import__('random').Random(0)
        order = list(rids)
        rng.shuffle(order)
        return order
    return list(rids)


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------
def _safe_plan(tx, rid, forced, cfg):
    """Plan one ripped route with fallbacks; returns candidate list or []."""
    cands = tx.plan(rid, forced=forced, cfg=cfg)
    if cands:
        return cands
    if forced is not None:
        cands = tx.plan(rid, cfg=BLOCKER_FREE_CFG)
        if cands:
            return cands
    return tx.plan(rid, cfg=BLOCKER_KEEP_CFG)


def single_move(jw, rid, layer, z_mm, cfg=None, ledger=None, min_gain=1,
                note='migrate_single'):
    """One-route transaction: force ``rid`` to ``(layer, z)`` (exact accept)."""
    started = time.time()
    tx = jw.transaction([int(rid)], note=note, min_gain=int(min_gain))
    tx.rip_all()
    cands = tx.plan(int(rid), forced=(int(layer), float(z_mm)),
                    cfg=dict(TARGET_CFG, **(cfg or {})))
    if not cands:
        result = tx.abort('no_candidate')
        result.update(reason=R_NO_XY, rids=[int(rid)], strategy='single',
                      order=[int(rid)], placed=0,
                      seconds=round(time.time() - started, 3))
        return result
    tx.place(int(rid), cands[0])
    result = tx.finish()
    result.update(rids=[int(rid)], strategy='single', order=[int(rid)])
    if not result['accepted']:
        result['reason'] = R_NOGAIN
    result['seconds'] = round(time.time() - started, 3)
    return result


def make_way(jw, target_rid, target_layer, target_z, blockers,
             strategy='target_first', cfg=None, ledger=None, min_gain=1,
             note='make_way', graph=None):
    """Joint all-or-nothing make-way transaction.

    The target route is forced to ``(target_layer, target_z)``; every blocker
    is re-planned at its own original height first (fallback: free height,
    fallback: body-only XY rebuild).  The plan order is order-sensitive and is
    chosen by the caller (``strategy``).
    """
    started = time.time()
    target_rid = int(target_rid)
    rids = [target_rid]
    for blocker in blockers:
        blocker = int(blocker)
        if blocker != target_rid and blocker not in rids:
            rids.append(blocker)
    order = plan_order(rids, target_rid, strategy=strategy, graph=graph)
    cfg = dict(TARGET_CFG, **(cfg or {}))
    tx = jw.transaction(rids, note=note, min_gain=int(min_gain))
    tx.rip_all()
    for rid in order:
        if rid == target_rid:
            cands = tx.plan(rid, forced=(int(target_layer), float(target_z)),
                            cfg=cfg)
            if not cands:
                cands = tx.plan(rid, cfg=BLOCKER_FREE_CFG)
        else:
            row = tx.saved_rows[rid]
            cands = _safe_plan(tx, rid,
                               (int(row['target_layer']),
                                float(row['target_z_mm'])), BLOCKER_CFG)
        if not cands:
            result = tx.abort('no_candidate_%d' % rid)
            result.update(reason=R_JOINT if rid != target_rid else R_NO_XY,
                          rids=rids, strategy=strategy, order=order,
                          failed_rid=rid,
                          seconds=round(time.time() - started, 3))
            return result
        tx.place(rid, cands[0])
    result = tx.finish()
    result.update(rids=rids, strategy=strategy, order=order,
                  seconds=round(time.time() - started, 3))
    if not result['accepted']:
        result['reason'] = (R_NOGAIN if result['placed'] == len(rids)
                            else R_JOINT)
    return result


def recreate_group(jw, rids, strategy='desc', cfg=None, ledger=None,
                   min_gain=1, note='recreate', graph=None, forced_map=None,
                   forced_same=False, keep_fallback=True, rng=None):
    """Ruin-and-recreate transaction of a whole neighbourhood / component.

    ``forced_map`` may pin single routes ``{rid: (layer, z)}`` (used for the
    height-assignment variant); otherwise each route is re-planned freely
    (``forced_same`` pins it to its current height).  When a route has no
    candidate and ``keep_fallback`` is set, its **original geometry is kept**
    (a legal no-op placement) so the rest of the neighbourhood can still
    improve.
    """
    started = time.time()
    rids = sorted({int(rid) for rid in rids})
    order = recreate_order(rids, strategy=strategy, graph=graph, rng=rng,
                           state=jw.state)
    forced_map = dict(forced_map or {})
    cfg = dict(cfg or {})
    tx = jw.transaction(rids, note=note, min_gain=int(min_gain))
    tx.rip_all()
    unchanged = 0
    for rid in order:
        row = tx.saved_rows[rid]
        forced = forced_map.get(rid)
        if forced is None and forced_same:
            forced = (int(row['target_layer']), float(row['target_z_mm']))
        cands = tx.plan(rid, forced=forced, cfg=(cfg or None))
        if not cands:
            if keep_fallback:
                tx.place(rid, tx.saved_routes[rid])
                unchanged += 1
                continue
            result = tx.abort('no_candidate_%d' % rid)
            result.update(reason=R_JOINT, rids=rids, strategy=strategy,
                          order=order, failed_rid=rid, unchanged=unchanged,
                          seconds=round(time.time() - started, 3))
            return result
        tx.place(rid, cands[0])
    result = tx.finish()
    result.update(rids=rids, strategy=strategy, order=order,
                  unchanged=int(unchanged),
                  seconds=round(time.time() - started, 3))
    if not result['accepted']:
        result['reason'] = (R_NOGAIN if result['placed'] == len(rids)
                            else R_JOINT)
    return result


# ---------------------------------------------------------------------------
# high level operators (used by alns.py)
# ---------------------------------------------------------------------------
def sweep_route(jw, rid, n_heights=7, min_gain=2, cfg=None, same_height=True,
                early_delta=-6):
    """Greedy forced-height probe of one route: try the quietest planes.

    Target heights are ranked by the **current crossing events of the plane**
    (``state.plane_counts``, always exact), exactly like the verified lead
    sweep: the quiet planes of the current state are the profitable targets,
    regardless of the route's current XY path.

    Returns ``dict(accepted, gain, reason, best, probes, seconds, ...)``.  When
    ``same_height`` a same-height XY re-plan is probed as the last alternative.
    """
    started = time.time()
    rid = int(rid)
    cfg = dict(SWEEP_CFG, **(cfg or {}))
    state = jw.state
    heights = NB.rank_heights_by_events(state, rid)
    probes = 0
    best = None
    for height in heights[:max(1, int(n_heights))]:
        cands = plan_clean_forced(jw, rid, height['layer'], height['z'], cfg=cfg)
        probes += 1
        if not cands:
            continue
        candidate = cands[0]
        if candidate.delta > -int(min_gain):
            continue
        if best is None or candidate.delta < best['candidate'].delta:
            best = dict(height=height, candidate=candidate, probes=probes)
        if best is not None and best['candidate'].delta <= int(early_delta):
            break
    if same_height:
        row = state.row(rid)
        cands = plan_clean_forced(jw, rid, int(row['target_layer']),
                                  float(row['target_z_mm']), cfg=cfg)
        probes += 1
        if cands and cands[0].delta <= -int(min_gain) and \
                (best is None or cands[0].delta < best['candidate'].delta):
            best = dict(height=dict(layer=int(row['target_layer']),
                                    z=float(row['target_z_mm']),
                                    z_key=WA.plane_key(row['target_z_mm'])),
                        candidate=cands[0], probes=probes)
    if best is None:
        return dict(accepted=False, gain=0, delta=0, reason=R_NOGAIN,
                    operator='sweep', rids=[rid], probes=probes,
                    seconds=round(time.time() - started, 3), order=[],
                    strategy='sweep')
    result = commit_planned(jw, rid, best['candidate'], min_gain=min_gain,
                            note='sweep_migrate')
    result.update(operator='sweep', probes=probes,
                  probe_delta=int(best['candidate'].delta),
                  target_height=dict(best['height']),
                  seconds=round(time.time() - started, 3))
    return result


def try_migrate(jw, rid, frozen=None, graph=None, index=None, probe_limit=2,
                max_frozen=0, beam=1, ledger=None, min_gain=1,
                height_order=None, cfg=None, early_delta=-8):
    """Try to migrate one route to a better height (clean commit or make-way).

    Heights are probed in the verified order: **current plane crossing events
    ascending** (quiet planes first).  A clean, exact-delta candidate is
    committed without re-planning; only when the probe reports true-3-D
    blockers does a joint make-way transaction run.
    """
    started = time.time()
    rid = int(rid)
    if height_order is None:
        height_order = NB.rank_heights_by_events(jw.state, rid)
    tried = 0
    last_reason = R_NO_CROSS
    cfg = dict(SWEEP_CFG, **(cfg or {}))
    for height in height_order[:max(1, int(probe_limit))]:
        tried += 1
        probe = probe_forced(jw, rid, height['layer'], height['z'],
                             cfg=cfg, ledger=ledger)
        best = probe['candidates'][0] if probe['candidates'] else None
        if best is not None and best['delta'] <= -int(min_gain):
            result = commit_planned(jw, rid, best['route'], min_gain=min_gain,
                                    note='migrate_clean')
            result['operator'] = 'migrate'
            result['probe_delta'] = int(best['delta'])
            result['tried_heights'] = tried
            result['height'] = height
            if result['accepted']:
                return result
            last_reason = result.get('reason') or R_NOGAIN
            continue
        blockers = choose_blockers(
            jw, rid, probe['blockers'], frozen=frozen, cap=3, graph=graph,
            index=index, extra_blockers=height.get('blockers'))
        if blockers:
            last_reason = R_T3D if probe['blockers'] else R_TARGET_OCC
            strategies = ['target_first', 'blockers_first']
            for strategy in strategies[:max(1, int(beam))]:
                result = make_way(jw, rid, height['layer'], height['z'],
                                  blockers, strategy=strategy,
                                  ledger=ledger, min_gain=min_gain,
                                  graph=graph)
                result['operator'] = 'migrate'
                result['tried_heights'] = tried
                result['height'] = height
                result['blockers'] = list(blockers)
                if result['accepted']:
                    return result
                last_reason = result.get('reason') or last_reason
        else:
            if not probe['candidates']:
                last_reason = R_TARGET_OCC
    result = dict(accepted=False, gain=0, delta=0, reason=last_reason,
                  operator='migrate', rids=[rid], tried_heights=tried,
                  seconds=round(time.time() - started, 3), order=[], strategy='')
    if tried == 0:
        result['reason'] = R_NO_CROSS
    return result


def try_recreate(jw, rids, strategy='desc', cfg=None, ledger=None,
                 min_gain=1, forced_map=None, forced_same=False, graph=None,
                 note='recreate'):
    result = recreate_group(jw, rids, strategy=strategy, cfg=cfg,
                            ledger=ledger, min_gain=min_gain, note=note,
                            graph=graph, forced_map=forced_map,
                            forced_same=forced_same)
    result['operator'] = 'recreate'
    return result
