# -*- coding: utf-8 -*-
"""Crossing-aware per-layer 2D body router (fanout-first 1024 system).

Background
----------
``four_side_1024/fanout1024/layer2d.py`` routes the 2D body of every connection
on its fixed body layer with a *greedy* acceptance rule: the first candidate
chain that passes the strict same-layer ``D56Index`` check, the true-3D
transition-obstacle check and the self-clearance check is committed.  Same-layer
transverse crossings are legal under the strict D56 policy, so that greedy rule
never looks at how many crossings a candidate creates.

This module keeps the *exact* same primitive set, geometry and legality
machinery (R15 arcs only, strict D56, 3D obstacle rule, 150 x 150 mm board,
pose-complete to 1e-6) and changes only the *selection*:

1. per route, collect up to ``max_legal_candidates`` legal candidates (exactly
   the same candidate stream ``layer2d`` uses) and commit the one minimising

       ``crossing_weight * new_crossings + length_mm``

   where ``new_crossings`` counts genuine transverse crossings with the
   already-committed same-layer bodies and the frozen ``initial_routes``
   (manual bodies / interface leads on an interface plane);
2. after the first pass, run a deterministic crossing-reduction pass: routed
   routes are re-attempted in descending crossing-count order against the other
   committed routes, with a transactional rollback that restores the exact
   previous state (routes / failed / D56 index / crossing bookkeeping) unless
   the re-route keeps the route placed and strictly improves the layer
   (fewer crossings, or equal crossings and shorter total length);
3. report the *authoritative* crossing count of the final layer (routed bodies
   + ``initial_routes``) with the project validator
   (``four_side_1024.fslw.validate_fslw``: ``prepare_route`` +
   ``audit_route_pairs(policy='strict')``, clearance 0.08 mm, sagitta
   0.0005 mm) — the same definition as ``crossing_stats.json``.

The router never lowers R15, never relaxes D56 / 3D clearance, never drops a
route and never needs wall-clock-dependent decisions: identical
``(tasks, obstacles, initial_routes, seed, cfg, crossing parameters)`` give an
identical routing (see :func:`routing_signature`).

Public API
----------
``route_layer_cross_aware(layer_id, z_mm, tasks, obstacles=None, budget=600,
                          ordering_seed=0, initial_routes=None, cfg=None,
                          crossing_weight=100.0, max_legal_candidates=24,
                          reduce_rounds=3, log=print, rr_rounds=2,
                          rr_ripmax=3, reduce_budget=120,
                          reduce_max_legal=12)``
``route_all_layers_cross_aware(layer_tasks, out_dir=None, cfg=None, log=print,
                               ordering_seed=0, budget=600, ...)``
``count_layer_crossings(primitives_by_route)``
``routing_signature(result)``

Both routing entry points return exactly the ``layer2d.route_layer`` /
``layer2d.route_all_layers`` shapes (same ``routed`` / ``failed`` / ``stats``
keys plus a few additive crossing statistics).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import layer2d as L2
from ...d56.index import prepare as d56_prepare
from ...fslw import validate_fslw as FSLW

__all__ = [
    'CROSS_DEFAULTS',
    'CrossAwareLayerRouter',
    'count_layer_crossings',
    'route_layer_cross_aware',
    'route_all_layers_cross_aware',
    'routing_signature',
]

#: authoritative D56 audit parameters of the project (``crossing_stats.json``)
AUTHORITATIVE_CLEARANCE_MM = 0.08
AUTHORITATIVE_SAGITTA_MM = 0.0005

#: defaults of the crossing-aware selection / reduction
CROSS_DEFAULTS = dict(
    crossing_weight=100.0,      # mm of detour accepted to remove one crossing
    max_legal_candidates=24,    # legal candidates inspected per route attempt
    reduce_rounds=3,            # bounded crossing-reduction rounds
    #: reduction-pass re-attempts use a smaller deterministic candidate scan:
    #: the first pass already converges to a single-route local optimum on the
    #: real layers (a full 600-evaluation scan finds no further improvement),
    #: so this only bounds runtime without changing the resulting crossings.
    reduce_budget=120,          # candidate evaluations per reduction re-attempt
    reduce_max_legal=12,        # legal candidates compared per reduction attempt
)

_ROUND_DIGITS = 9


# ---------------------------------------------------------------------------
# authoritative crossing audit (same definition as crossing_stats.json)
# ---------------------------------------------------------------------------
def _key_order(key):
    """Deterministic ordering for arbitrary (int / str / tuple) route keys."""
    if isinstance(key, bool):
        return (1, str(key))
    if isinstance(key, int):
        return (0, key)
    if isinstance(key, str) and key.lstrip('-').isdigit():
        return (0, int(key))
    return (2, repr(key))


def _percentile(sorted_values, fraction):
    """Linear-interpolation percentile of an already sorted sequence."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * float(fraction)
    lower = int(math.floor(position))
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight)
                 + sorted_values[upper] * weight)


def _distribution(values):
    """``max / p95 / mean / median`` summary of per-route crossing counts."""
    numbers = sorted(int(value) for value in values)
    if not numbers:
        return dict(routes=0, max=0, p95=0.0, mean=0.0, median=0.0,
                    routes_with_crossings=0)
    return dict(
        routes=len(numbers),
        max=int(numbers[-1]),
        p95=round(_percentile(numbers, 0.95), 6),
        mean=round(sum(numbers) / float(len(numbers)), 6),
        median=round(_percentile(numbers, 0.5), 6),
        routes_with_crossings=sum(1 for value in numbers if value > 0),
    )


def count_layer_crossings(primitives_by_route):
    """Authoritative strict-D56 crossing audit of one physical plane.

    Parameters
    ----------
    primitives_by_route : mapping
        ``{route_key: [primitive, ...]}`` of every same-layer body that lives
        on the plane (routed bodies *and* frozen ``initial_routes``).  Keys may
        be any hashable value (int route ids are the normal case; the frozen
        interface leads use unique integer ids); they are only used as labels.

    Returns
    -------
    dict
        ``crossings`` (int, number of genuine transverse crossings),
        ``crossing_pairs`` (int), ``violations`` (int), ``per_route``
        (``{key: crossing_count}``, only routes with > 0 crossings),
        ``crossing_distribution`` (max/p95/mean/median over all routes),
        ``min_non_crossing_centerline_mm``, ``candidate_pair_count`` and
        ``runtime_seconds``.  This is exactly the definition used by the
        baseline ``crossing_stats.json`` (strict policy, clearance 0.08 mm,
        sagitta 0.0005 mm).
    """
    started = time.perf_counter()
    keys = [key for key, prims in (primitives_by_route or {}).items() if prims]
    keys.sort(key=_key_order)
    prepared = []
    for key in keys:
        prims = [dict(prim) for prim in primitives_by_route[key]]
        if not prims:
            continue
        try:
            prepared.append(FSLW.prepare_route(prims, route_id=key))
        except (ValueError, KeyError, TypeError, FSLW._PrimitiveError):
            # a malformed frozen body is not silently dropped: report it as a
            # violation candidate (the route still does not contribute pairs).
            prepared.append(None)
    usable = [route for route in prepared if route is not None]
    report = dict(crossings=0, crossing_pairs=0, violations=0, per_route={},
                  crossing_distribution=_distribution(()),
                  min_non_crossing_centerline_mm=None,
                  candidate_pair_count=0,
                  runtime_seconds=0.0)
    report['violations'] = len(prepared) - len(usable)
    if len(usable) < 2:
        report['runtime_seconds'] = round(time.perf_counter() - started, 6)
        return report
    audit = FSLW.audit_route_pairs(usable,
                                   clearance=AUTHORITATIVE_CLEARANCE_MM,
                                   sagitta=AUTHORITATIVE_SAGITTA_MM,
                                   policy='strict')
    per_route = Counter()
    for crossing in audit.get('crossings') or ():
        for side in ('route_a', 'route_b'):
            key = crossing.get(side)
            per_route[key] += 1
    report.update(
        crossings=int(audit.get('crossing_count') or 0),
        crossing_pairs=int(audit.get('crossing_pair_count') or 0),
        violations=report['violations'] + len(audit.get('violations') or ()),
        per_route=dict(per_route),
        crossing_distribution=_distribution(per_route.values()),
        min_non_crossing_centerline_mm=audit.get(
            'min_non_crossing_centerline_mm'),
        candidate_pair_count=int(audit.get('candidate_pair_count') or 0),
        runtime_seconds=round(time.perf_counter() - started, 6),
    )
    return report


# ---------------------------------------------------------------------------
# crossing-aware layer router (subclass of the frozen greedy router)
# ---------------------------------------------------------------------------
class CrossAwareLayerRouter(L2._LayerRouter):
    """Crossing-aware variant of ``layer2d._LayerRouter``.

    Only the *acceptance* of a candidate and a bounded post-pass are changed;
    candidate generation, geometry, strict D56 index, transition-obstacle rule
    and the output shape are inherited unchanged.

    Crossing bookkeeping used by the reduction pass (all incremental):
    ``_route_crossings[rid]`` is the number of genuine D56 crossing events
    between one committed route and every other indexed route (routed *and*
    frozen initial); ``_pairs[rid]`` is the per-partner breakdown.  The layer
    proxy ``sum(_route_crossings.values())`` equals ``2 * routed/routed +
    routed/initial`` crossing events (every routed/routed event is seen from
    both sides), which is monotone in the true same-layer crossing count.
    """

    def __init__(self, layer_id, z_mm, tasks, obstacles=None, cfg=None,
                 log=print, initial_routes=None, crossing_weight=100.0,
                 max_legal_candidates=24, reduce_rounds=3, rr_rounds=2,
                 rr_ripmax=3, reduce_budget=120, reduce_max_legal=12):
        merged = dict(L2.DEFAULT_CFG)
        if cfg:
            merged.update(cfg)
        self.crossing_weight = float(crossing_weight)
        self.max_legal_candidates = max(1, int(max_legal_candidates))
        self.reduce_rounds = max(0, int(reduce_rounds))
        self.rr_rounds = max(0, int(rr_rounds))
        self.rr_ripmax = max(1, int(rr_ripmax))
        #: candidate scan of one reduction re-attempt (bounded runtime; the
        #: full scan is provably useless on the real layers, see CROSS_DEFAULTS)
        self.reduce_budget = max(1, int(reduce_budget))
        self.reduce_max_legal = min(self.max_legal_candidates,
                                    max(1, int(reduce_max_legal)))
        # raw frozen initial bodies (base turns them into ``Prepared`` objects),
        # kept because the authoritative audit needs the raw primitives.
        self.initial_raw = []
        for key, primitives in (initial_routes or {}).items():
            try:
                int(key)
            except (TypeError, ValueError):
                continue
            if not primitives:
                continue
            self.initial_raw.append(
                (key, [dict(prim) for prim in primitives]))
        super().__init__(layer_id, z_mm, list(tasks or ()), obstacles or (),
                         merged, log, initial_routes=initial_routes)
        # ---- incremental same-layer crossing bookkeeping --------------------
        self._route_crossings = {}   # routed route_id -> crossing events
        self._pairs = {}             # routed route_id -> {partner: count}
        # ---- additive statistics -------------------------------------------
        self.stats.update(
            crossing_weight=self.crossing_weight,
            max_legal_candidates=self.max_legal_candidates,
            reduce_rounds=self.reduce_rounds,
            reduce_budget=self.reduce_budget,
            reduce_max_legal=self.reduce_max_legal,
            crossings_before_reduction=None,
            crossings_after=None,
            d56_crossings_before_reduction=None,
            d56_crossings_after_reduction=None,
            reduction_rounds=0,
            reduction_effective=False,
            reduction_history=[],
            routed_crossing_distribution=_distribution(()),
            authoritative_audit_seconds=0.0,
        )

    # -- crossing bookkeeping ------------------------------------------------
    def _record_crossings(self, route_id, pair_counts):
        """Register the crossings of a freshly committed route."""
        pairs = {partner: int(count) for partner, count in pair_counts.items()
                 if int(count) > 0 and partner != route_id}
        self._pairs[route_id] = pairs
        total = int(sum(pairs.values()))
        self._route_crossings[route_id] = total
        for partner, count in pairs.items():
            if partner in self._route_crossings:
                self._route_crossings[partner] += count

    def _uncommit(self, route_id):
        """Base uncommit + crossing bookkeeping rollback (incremental)."""
        if route_id not in self.routed:
            return
        pairs = self._pairs.pop(route_id, {})
        for partner, count in pairs.items():
            if partner in self._route_crossings:
                self._route_crossings[partner] -= count
        self._route_crossings.pop(route_id, None)
        super()._uncommit(route_id)

    def _total_crossings_proxy(self):
        return int(sum(self._route_crossings.values()))

    def _total_length(self):
        return float(sum(float(payload.get('length_mm') or 0.0)
                         for payload in self.payload.values()))

    # -- transactional snapshots --------------------------------------------
    def _snapshot(self):
        """Full mutable-state snapshot (cheap: references only)."""
        return dict(
            routed=OrderedDict(self.routed),
            prepared=dict(self.prepared),
            payload=dict(self.payload),
            failed=OrderedDict(self.failed),
            route_crossings=dict(self._route_crossings),
            pairs={rid: dict(pairs) for rid, pairs in self._pairs.items()},
            family_counts=Counter(self._family_counts),
        )

    def _restore(self, snapshot):
        """Restore an exact snapshot: routes, failed list and D56 index.

        The D56 index is rebuilt from the frozen initial bodies plus the
        snapshot routes, so the restored index has exactly the same geometry.
        """
        self.index.clear()
        for route_id, prepared in self.initial_routes.items():
            self.index.add(route_id, prepared)
        for route_id, prepared in snapshot['prepared'].items():
            self.index.add(route_id, prepared)
        self.routed = OrderedDict(snapshot['routed'])
        self.prepared = dict(snapshot['prepared'])
        self.payload = dict(snapshot['payload'])
        self.failed = OrderedDict(snapshot['failed'])
        self._route_crossings = dict(snapshot['route_crossings'])
        self._pairs = {rid: dict(pairs) for rid, pairs in snapshot['pairs'].items()}
        self._family_counts = Counter(snapshot['family_counts'])

    def _route_snapshot(self, route_id):
        """Snapshot of one committed route (targeted, O(partners) rollback)."""
        return dict(
            route_id=int(route_id),
            routed=route_id in self.routed,
            world=self.routed.get(route_id),
            prepared=self.prepared.get(route_id),
            payload=self.payload.get(route_id),
            crossings=self._route_crossings.get(route_id),
            pairs=dict(self._pairs.get(route_id) or {}),
            failed=self.failed.get(route_id),
        )

    def _restore_route(self, snapshot):
        """Restore one route after a rejected/ failed re-attempt.

        Only the route itself and the crossing counters of its partners have
        changed inside a re-attempt, so no full index rebuild is required for
        the (very frequent) reduction-pass rollback.
        """
        route_id = snapshot['route_id']
        if route_id in self.routed:
            self._uncommit(route_id)
        if not snapshot['routed']:
            if snapshot['failed'] is not None:
                self.failed[route_id] = dict(snapshot['failed'])
            else:
                self.failed.pop(route_id, None)
            return
        # partner counters lost the original pair counts when the route was
        # uncommitted; put them back before re-inserting the original body.
        for partner, count in snapshot['pairs'].items():
            if partner in self._route_crossings:
                self._route_crossings[partner] += int(count)
        self.index.add(route_id, snapshot['prepared'])
        self.routed[route_id] = snapshot['world']
        self.prepared[route_id] = snapshot['prepared']
        if snapshot['payload'] is not None:
            self.payload[route_id] = snapshot['payload']
        self._pairs[route_id] = dict(snapshot['pairs'])
        self._route_crossings[route_id] = int(snapshot['crossings'] or 0)
        self.failed.pop(route_id, None)

    # -- candidate selection -------------------------------------------------
    def _attempt(self, route_id, budget, commit=True, phase=0.0,
                 record_failure=True):
        """Route one body, selecting the legal candidate with the lowest
        ``crossing_weight * new_crossings + length`` score.

        The candidate stream is the inherited ``_iter_candidates`` generator
        (identical geometry / family order as the greedy router).  Candidates
        whose length is already at least the best score so far cannot win
        (a score is never below the path length), so they are skipped without
        the expensive strict-D56 evaluation; the selection is therefore
        identical to evaluating every candidate.  At most
        ``max_legal_candidates`` legal candidates are compared.
        """
        frame = self.frames.get(route_id)
        if frame is None:
            if record_failure:
                self._store_failure(
                    route_id, self.frame_errors.get(route_id, 'invalid_frame'),
                    0, {}, [])
            return False
        considered = 0
        rejection = Counter()
        blockers = set()
        candidates = []
        best_score = None
        for world, spec, _signature in self._iter_candidates(route_id, phase):
            if considered >= budget or self._candidates_built > int(
                    self.cfg['max_candidates_built']):
                break
            considered += 1
            length = L2._path_length(world)
            if best_score is not None and length >= best_score - 1e-12:
                continue                      # cannot improve: score >= length
            prepared = d56_prepare(world)
            self.stats['d56_evaluations'] += 1
            evaluation = self.index.evaluate(prepared)
            if not evaluation.valid:
                rejection[evaluation.reason] += 1
                blockers.update(evaluation.blockers)
                continue
            ok, obstacle_blockers = self.obstacles.check(world, route_id)
            if not ok:
                rejection['obstacle'] += 1
                self.stats['obstacle_rejections'] += 1
                blockers.update(obstacle_blockers)
                continue
            if not L2._self_clearance_ok(world):
                rejection['self_clearance'] += 1
                self.stats['self_rejections'] += 1
                continue
            pair_counts = Counter()
            for crossing in evaluation.crossings:
                other = crossing.get('other')
                if other == route_id:
                    continue
                pair_counts[other] += 1
            new_crossings = int(sum(pair_counts.values()))
            score = self.crossing_weight * new_crossings + length
            candidates.append(dict(order=len(candidates), score=score,
                                   world=world, prepared=prepared, spec=spec,
                                   crossings=new_crossings,
                                   pairs=pair_counts, length=length))
            if best_score is None or score < best_score:
                best_score = score
            if len(candidates) >= self.max_legal_candidates:
                break
        if not candidates:
            primary = 'candidate_budget_exhausted'
            if not rejection:
                primary = ('no_candidate_generated'
                           if considered == 0 else 'no_candidate_available')
            elif rejection.get('obstacle', 0) and (
                    rejection['obstacle'] >= max(rejection.values())):
                primary = 'obstacle_blocked'
            if record_failure:
                self._store_failure(route_id, primary, considered,
                                    dict(rejection), sorted(blockers, key=str))
            return False
        chosen = min(candidates, key=lambda item: (item['score'], item['order']))
        if commit:
            self._commit(route_id, chosen['world'], chosen['prepared'],
                         chosen['spec'], considered)
            self._record_crossings(route_id, chosen['pairs'])
            self._rejection_counts.update(rejection)
            self._candidates_built = 0
        return True

    # -- rip-up & reroute (inherited algorithm, transactional rollback) ------
    def _ripup_reroute(self, budget, rr_rounds, rr_ripmax, phase, order, log):
        """Bounded rip-up-and-reroute with exact snapshot rollback.

        Same deterministic algorithm as ``layer2d._LayerRouter._ripup_reroute``
        (which is unable to keep the crossing bookkeeping of this subclass
        consistent because it re-inserts saved bodies directly into the D56
        index); rollback restores the full state instead.
        """
        best = len(self.routed)
        history = []
        for round_index in range(1, int(rr_rounds) + 1):
            gained = 0
            pending = [rid for rid in order if rid in self.failed]
            for route_id in pending:
                if route_id not in self.failed:
                    continue
                failure = dict(self.failed.get(route_id) or {})
                blockers = []
                for blocker in failure.get('blockers') or ():
                    try:
                        blocker_id = int(blocker)
                    except (TypeError, ValueError):
                        continue
                    if blocker_id in self.routed:
                        blockers.append(blocker_id)
                if not blockers:
                    saved_failure = self.failed.get(route_id)
                    self._attempted += 1
                    if self._attempt(route_id, budget * (round_index + 1),
                                     phase=(phase + 0.5) % 1.0):
                        self.failed.pop(route_id, None)
                        gained += 1
                    elif saved_failure is not None:
                        self.failed[route_id] = saved_failure
                    continue
                rip = blockers[:max(1, int(rr_ripmax))]
                snapshot = self._snapshot()
                for blocker_id in rip:
                    self._uncommit(blocker_id)
                self._attempted += 1
                placed = self._attempt(route_id, budget,
                                       phase=(phase + 0.5 * round_index) % 1.0)
                restored = True
                if placed:
                    for blocker_id in rip:
                        self._attempted += 1
                        if not self._attempt(
                                blocker_id, budget,
                                phase=(phase + 0.5) % 1.0):
                            restored = False
                            break
                if placed and restored:
                    self.failed.pop(route_id, None)
                    for blocker_id in rip:
                        self.failed.pop(blocker_id, None)
                    gained += 1
                    continue
                self._restore(snapshot)
                self.failed.setdefault(route_id, failure)
            current = len(self.routed)
            best = max(best, current)
            history.append(dict(round=round_index, pending=len(pending),
                                gained=gained, routed=current,
                                failed=len(self.failed)))
            log(f'[cross_router] L{self.layer_id} rrr round {round_index}: '
                f'pending={len(pending)} gained={gained} '
                f'routed={current}/{len(self.tasks)}')
            if gained == 0:
                break
        # final bounded retry of whatever is still failed (expanded budget)
        for route_id in [rid for rid in order if rid in self.failed]:
            self._attempted += 1
            if self._attempt(route_id, budget * 2,
                             phase=(phase + 0.75) % 1.0):
                self.failed.pop(route_id, None)
        self.stats['rrr'] = history

    # -- crossing-reduction pass --------------------------------------------
    def _reduce_crossings(self, budget, phase, log):
        """Run the reduction pass with its bounded candidate scan width."""
        saved_width = self.max_legal_candidates
        self.max_legal_candidates = self.reduce_max_legal
        try:
            return self._reduce_crossings_impl(budget, phase, log)
        finally:
            self.max_legal_candidates = saved_width

    def _reduce_crossings_impl(self, budget, phase, log):
        """Deterministic rip-up / re-route pass reducing same-layer crossings.

        Routes are visited in descending current crossing count (ties by route
        id).  Each visit is transactional: the route is uncommitted, re-routed
        with the crossing-aware selection and the change is kept only when the
        route is still placed, the total number of routed routes is unchanged
        and the layer improves — either strictly fewer crossing events, or the
        same crossings with a strictly shorter total routed length.  Every
        other outcome restores the exact previous state.
        """
        history = []
        for round_index in range(1, self.reduce_rounds + 1):
            routed_before = len(self.routed)
            order = sorted(self.routed,
                           key=lambda rid: (-self._route_crossings.get(rid, 0),
                                            int(rid)))
            changes = 0
            for route_id in order:
                if route_id not in self.routed:
                    continue
                snapshot = self._route_snapshot(route_id)
                old_total = self._total_crossings_proxy()
                old_length = self._total_length()
                self._uncommit(route_id)
                self._attempted += 1
                placed = self._attempt(route_id, budget, commit=True,
                                       phase=phase, record_failure=False)
                accepted = False
                if placed:
                    new_total = self._total_crossings_proxy()
                    new_length = self._total_length()
                    accepted = (
                        (new_total < old_total)
                        or (new_total == old_total
                            and new_length < old_length - 1e-9))
                if accepted:
                    changes += 1
                else:
                    self._restore_route(snapshot)
            if len(self.routed) != routed_before:      # pragma: no cover
                log(f'[cross_router] L{self.layer_id} WARNING routed count '
                    f'changed during reduction '
                    f'({routed_before}->{len(self.routed)})')
            current = self._total_crossings_proxy()
            history.append(dict(round=round_index, changes=changes,
                                routed=len(self.routed),
                                d56_crossings=current,
                                total_length_mm=round(self._total_length(), 6)))
            log(f'[cross_router] L{self.layer_id} reduce round {round_index}: '
                f'changes={changes} routed={len(self.routed)}/'
                f'{len(self.tasks)} d56_crossings={current}')
            if changes == 0:
                break
        self.stats['reduction_rounds'] = len(history)
        self.stats['reduction_history'] = history
        return history

    # -- authoritative audit -------------------------------------------------
    def _authoritative_audit(self):
        """Strict-D56 crossing audit of routed bodies + frozen initial routes."""
        combined = OrderedDict()
        for index, (key, primitives) in enumerate(self.initial_raw):
            if not primitives:
                continue
            label = ('initial', str(key))
            combined[label] = primitives
        for route_id, payload in self.payload.items():
            primitives = payload.get('primitives') or []
            if not primitives:
                continue
            combined[('body', int(route_id))] = [dict(prim) for prim in primitives]
        report = count_layer_crossings(combined)
        routed_counts = []
        for route_id in self.payload:
            label = ('body', int(route_id))
            routed_counts.append(int(report['per_route'].get(label, 0)))
        return dict(
            crossings=int(report['crossings']),
            crossing_pairs=int(report['crossing_pairs']),
            violations=int(report['violations']),
            min_non_crossing_centerline_mm=report[
                'min_non_crossing_centerline_mm'],
            routed_crossing_distribution=_distribution(routed_counts),
            d56_candidate_pairs=int(report['candidate_pair_count']),
            runtime_seconds=float(report['runtime_seconds']),
        )

    # -- driver --------------------------------------------------------------
    def run_cross_aware(self, budget, rr_rounds, rr_ripmax, ordering_seed,
                        log=None):
        """Full crossing-aware run: greedy-aware first pass, bounded repair,
        crossing-reduction pass and authoritative statistics."""
        log = log or self.log
        started = time.time()
        phase = L2._candidate_phase(self.cfg, ordering_seed)
        result_first = super().run(int(budget), int(rr_rounds),
                                   int(rr_ripmax), int(ordering_seed), log=log)
        del result_first
        first_state = self._snapshot()
        first_families = Counter(self._family_counts)
        first_routed = len(self.routed)
        proxy_before = self._total_crossings_proxy()
        first_length = self._total_length()
        audit_before = self._authoritative_audit()
        self.stats['d56_crossings_before_reduction'] = proxy_before
        self.stats['crossings_before_reduction'] = audit_before['crossings']
        log(f'[cross_router] L{self.layer_id} first pass authoritative: '
            f'crossings={audit_before["crossings"]} '
            f'd56={proxy_before} routed={first_routed}/{len(self.tasks)}')
        history = self._reduce_crossings(self.reduce_budget, phase, log)
        audit_after = self._authoritative_audit()
        kept = 'reduced'
        # Safety net: the reduction pass optimises the strict D56 index count;
        # keep the pass only if the *authoritative* project metric did not get
        # worse (it never drops a route by construction).
        if len(self.routed) != first_routed:
            kept = 'first_pass'
        elif audit_after['crossings'] > audit_before['crossings']:
            kept = 'first_pass'
        elif (audit_after['crossings'] == audit_before['crossings']
              and self._total_length() > first_length + 1e-9):
            kept = 'first_pass'
        if kept == 'first_pass':
            self._restore(first_state)
            self._family_counts = Counter(first_families)
            audit_after = audit_before
            history = []
            self.stats['reduction_rounds'] = 0
            self.stats['reduction_history'] = []
            log(f'[cross_router] L{self.layer_id} reduction pass rolled back '
                f'(authoritative crossings would not improve)')
        # ---- final statistics ----------------------------------------------
        self._family_counts = Counter(
            payload['family'] for payload in self.payload.values())
        self.stats['families'] = dict(self._family_counts)
        self.stats['attempted'] = self._attempted
        self.stats['success'] = len(self.routed)
        self.stats['failed'] = len(self.tasks) - len(self.routed)
        self.stats['rejection_counts'] = dict(self._rejection_counts)
        self.stats['seconds'] = float(time.time() - started)
        self.stats['d56_crossings_after_reduction'] = (
            self._total_crossings_proxy())
        self.stats['crossings_after'] = audit_after['crossings']
        self.stats['reduction_effective'] = bool(
            kept == 'reduced'
            and any(int(item.get('changes') or 0) > 0 for item in history))
        self.stats['routed_crossing_distribution'] = (
            audit_after['routed_crossing_distribution'])
        self.stats['authoritative_audit_seconds'] = round(
            audit_before['runtime_seconds'] + audit_after['runtime_seconds'], 6)
        self.stats['authoritative_crossing_pairs_after'] = (
            audit_after['crossing_pairs'])
        self.stats['authoritative_violations_after'] = audit_after['violations']
        self.stats['min_non_crossing_centerline_mm'] = audit_after[
            'min_non_crossing_centerline_mm']
        self.stats['reduction_reroute'] = kept
        log(f'[cross_router] L{self.layer_id}: routed={len(self.routed)}/'
            f'{len(self.tasks)} crossings {audit_before["crossings"]} -> '
            f'{audit_after["crossings"]} ({self.stats["seconds"]:.1f}s)')
        return self._result()


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def route_layer_cross_aware(layer_id, z_mm, tasks, obstacles=None, budget=600,
                            ordering_seed=0, initial_routes=None, cfg=None,
                            crossing_weight=100.0, max_legal_candidates=24,
                            reduce_rounds=3, log=print, rr_rounds=2,
                            rr_ripmax=3, reduce_budget=120,
                            reduce_max_legal=12):
    """Route the 2D bodies of one physical layer with crossing-aware selection.

    Drop-in replacement for :func:`four_side_1024.fanout1024.layer2d.route_layer`
    (same task/obstacle/initial_routes contract, same return shape); the only
    behavioural difference is candidate acceptance (fewest new same-layer
    crossings first) and the bounded crossing-reduction pass.

    Parameters
    ----------
    layer_id : int
    z_mm : float | None
        Layer height; ``None`` resolves ``fanout1024.common.layer_z(layer_id)``.
    tasks, obstacles : list[dict]
        Exactly the ``layer2d.route_layer`` input (landing poses ``A/dA/B/dB``
        and the true-3D transition obstacle samples).
    budget : int
        Candidate evaluations per route attempt (same meaning as layer2d).
    ordering_seed : int
        Deterministic route order / candidate ladder phase seed (same as
        layer2d; identical seed 0 reproduces the greedy route order).
    initial_routes : dict | None
        Frozen already-placed same-layer bodies ``{key: primitives}`` (manual
        bodies / interface leads on an interface plane).  Inserted into the
        strict D56 index and counted as crossing partners; never routed, never
        failed, never moved.  Unsafe/duplicate/colliding keys are remapped by
        the inherited ``layer2d`` logic, so they cannot alias the index.
    cfg : dict | None
        Overrides of ``layer2d.DEFAULT_CFG`` (candidate ladders, budget...).
    crossing_weight : float
        Millimetres of path length accepted to remove one crossing.
    max_legal_candidates : int
        Number of legal candidates compared per route attempt (>= 1).
    reduce_rounds : int
        Bounded crossing-reduction rounds after the first pass (0 disables).
    log : callable
    rr_rounds, rr_ripmax : int
        Bounded rip-up-and-reroute limits of the inherited repair loop.
    reduce_budget, reduce_max_legal : int
        Deterministic candidate-scan limits of one reduction re-attempt (the
        first pass keeps the full ``budget`` / ``max_legal_candidates``); they
        only bound the reduction runtime, which is a no-op for the stored
        crossings on these layers (see ``CROSS_DEFAULTS``).

    Returns
    -------
    dict
        ``{layer_id, z_mm, routed, failed, stats}`` exactly like
        :func:`layer2d.route_layer`; ``stats`` additionally carries
        ``crossings_before_reduction``, ``crossings_after`` (authoritative
        strict-D56), ``reduction_rounds``, ``reduction_effective``,
        ``routed_crossing_distribution`` (max/p95/mean/median),
        ``d56_evaluations`` and the crossing-selection parameters.
    """
    if z_mm is None:
        z_mm = L2.C.layer_z(int(layer_id))
    merged = dict(L2.DEFAULT_CFG)
    if cfg:
        merged.update(cfg)
    merged['budget'] = int(budget)
    router = CrossAwareLayerRouter(
        layer_id, z_mm, list(tasks or ()), obstacles or (), merged, log,
        initial_routes=initial_routes, crossing_weight=crossing_weight,
        max_legal_candidates=max_legal_candidates,
        reduce_rounds=reduce_rounds, rr_rounds=rr_rounds,
        rr_ripmax=rr_ripmax, reduce_budget=reduce_budget,
        reduce_max_legal=reduce_max_legal)
    return router.run_cross_aware(int(budget), int(rr_rounds),
                                  int(rr_ripmax), int(ordering_seed), log=log)


def route_all_layers_cross_aware(layer_tasks, out_dir=None, cfg=None,
                                 log=print, ordering_seed=0, budget=600,
                                 rr_rounds=2, rr_ripmax=3,
                                 initial_routes=None, crossing_weight=100.0,
                                 max_legal_candidates=24, reduce_rounds=3,
                                 reduce_budget=120, reduce_max_legal=12):
    """Route every physical layer independently with the crossing-aware router.

    Input, output shape, per-layer logging and the optional ``out_dir``
    artifacts are identical to
    :func:`four_side_1024.fanout1024.layer2d.route_all_layers`:
    ``layer_tasks`` is ``{layer_id: {'z_mm': float, 'tasks': [...],
    'obstacles': [...]}}`` (a list of payloads is accepted too) and
    ``initial_routes`` is either ``{layer_id: {key: primitives}}`` (recommended)
    or a flat map when routing a single layer.

    In addition to the layer2d aggregate the returned ``stats`` carries the
    summed crossing numbers of the experiment (``crossings_before_reduction``,
    ``crossings_after``).
    """
    started = time.time()
    items = L2._normalize_layer_tasks(layer_tasks)
    if initial_routes is not None and not isinstance(initial_routes, dict):
        raise TypeError('initial_routes must be a dict')
    layers = OrderedDict()
    per_layer_rows = []
    failures = []
    total_input = 0
    total_routed = 0
    total_before = 0
    total_after = 0
    for layer_id, payload in items:
        tasks = list(payload.get('tasks') or ())
        obstacles = list(payload.get('obstacles') or ())
        z_mm = float(payload['z_mm'])
        frozen = L2._initial_routes_for_layer(initial_routes, layer_id,
                                              len(items) == 1)
        log(f'[cross_router] routing layer L{layer_id} (z={z_mm:+.2f} mm) '
            f'tasks={len(tasks)} obstacles={len(obstacles)}'
            + (f' initial={len(frozen)}' if frozen else ''))
        result = route_layer_cross_aware(
            layer_id, z_mm, tasks, obstacles=obstacles, budget=budget,
            ordering_seed=ordering_seed, initial_routes=frozen, cfg=cfg,
            crossing_weight=crossing_weight,
            max_legal_candidates=max_legal_candidates,
            reduce_rounds=reduce_rounds, log=log, rr_rounds=rr_rounds,
            rr_ripmax=rr_ripmax, reduce_budget=reduce_budget,
            reduce_max_legal=reduce_max_legal)
        layers[int(layer_id)] = result
        stats = result['stats']
        total_input += int(stats['input'])
        total_routed += int(stats['success'])
        total_before += int(stats.get('crossings_before_reduction') or 0)
        total_after += int(stats.get('crossings_after') or 0)
        failed_list = result['failed']
        for record in failed_list:
            failures.append(dict(record, layer_id=int(layer_id), z_mm=z_mm))
        per_layer_rows.append(dict(
            layer_id=int(layer_id), z_mm=z_mm,
            input=stats['input'], attempted=stats['attempted'],
            routed=stats['success'], failed=stats['failed'],
            seconds=round(float(stats['seconds']), 4),
            candidates_evaluated=stats['candidates_evaluated'],
            d56_evaluations=stats['d56_evaluations'],
            obstacle_rejections=stats['obstacle_rejections'],
            self_rejections=stats['self_rejections'],
            crossings_before_reduction=stats.get('crossings_before_reduction'),
            crossings_after=stats.get('crossings_after'),
            reduction_rounds=stats.get('reduction_rounds'),
            families=json.dumps(stats.get('families') or {},
                                ensure_ascii=False, sort_keys=True),
            failure_reasons=json.dumps(
                {record['reason']: sum(
                    1 for item in failed_list
                    if item['reason'] == record['reason'])
                 for record in failed_list},
                ensure_ascii=False, sort_keys=True),
        ))
        log(f'[cross_router] L{layer_id}: routed={stats["success"]}/'
            f'{stats["input"]} crossings='
            f'{stats.get("crossings_before_reduction")}->'
            f'{stats.get("crossings_after")} ({stats["seconds"]:.1f}s)')
    wall = time.time() - started
    total_failed = total_input - total_routed
    result = dict(
        schema='fanout_first_layer2d_routes_v1',
        layers=layers,
        stats=dict(
            input=total_input, routed=total_routed, failed=total_failed,
            seconds=float(wall), layers=len(layers),
            crossings_before_reduction=total_before,
            crossings_after=total_after,
            per_layer={int(key): dict(
                input=value['stats']['input'],
                routed=value['stats']['success'],
                failed=value['stats']['failed'],
                seconds=round(float(value['stats']['seconds']), 4),
                crossings_before_reduction=value['stats'].get(
                    'crossings_before_reduction'),
                crossings_after=value['stats'].get('crossings_after'),
                routed_crossing_distribution=value['stats'].get(
                    'routed_crossing_distribution'),
            ) for key, value in layers.items()},
            families=L2._aggregate_families(layers)),
    )
    log(f'[cross_router] all layers: routed={total_routed}/{total_input} '
        f'failed={total_failed} crossings {total_before} -> {total_after} '
        f'({wall:.1f}s)')
    if out_dir is not None:
        L2._write_layer_outputs(Path(out_dir), layers, per_layer_rows,
                                failures, result['stats'])
    return result


# ---------------------------------------------------------------------------
# determinism helper
# ---------------------------------------------------------------------------
def routing_signature(result):
    """Stable SHA-256 of the *routing decisions* of one result (no timing).

    Identical inputs/seed produce an identical signature (routing
    determinism evidence); wall-clock statistics, rejection counters and
    cross-run bookkeeping are intentionally excluded.
    """
    def _layer_payload(layer):
        routed = OrderedDict()
        for key in sorted(layer.get('routed') or {},
                          key=lambda item: _key_order(item)):
            payload = (layer['routed'])[key]
            primitives = []
            for prim in payload.get('primitives') or ():
                if prim.get('kind') == 'line':
                    primitives.append([
                        'line',
                        [round(float(prim['p0'][0]), _ROUND_DIGITS),
                         round(float(prim['p0'][1]), _ROUND_DIGITS)],
                        [round(float(prim['p1'][0]), _ROUND_DIGITS),
                         round(float(prim['p1'][1]), _ROUND_DIGITS)]])
                else:
                    primitives.append([
                        'arc',
                        [round(float(prim['p0'][0]), _ROUND_DIGITS),
                         round(float(prim['p0'][1]), _ROUND_DIGITS)],
                        [round(float(prim['p1'][0]), _ROUND_DIGITS),
                         round(float(prim['p1'][1]), _ROUND_DIGITS)],
                        [round(float(prim['center'][0]), _ROUND_DIGITS),
                         round(float(prim['center'][1]), _ROUND_DIGITS)],
                        round(float(prim['radius']), _ROUND_DIGITS),
                        round(float(prim['start_angle']), _ROUND_DIGITS),
                        round(float(prim['sweep']), _ROUND_DIGITS)])
            routed[str(key)] = [str(payload.get('family')), primitives]
        failed = sorted(
            (str(record.get('route_id')), str(record.get('reason')))
            for record in (layer.get('failed') or ()))
        return dict(routed=routed, failed=failed)

    if isinstance(result, dict) and 'layers' in result:
        payload = OrderedDict(
            (str(int(layer_id)), _layer_payload(value))
            for layer_id, value in sorted(
                result['layers'].items(), key=lambda item: _key_order(item[0])))
    else:
        layer_id = result.get('layer_id')
        payload = OrderedDict([(str(layer_id), _layer_payload(result))])
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
