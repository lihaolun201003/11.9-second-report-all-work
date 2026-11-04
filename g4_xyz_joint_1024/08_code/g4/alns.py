# -*- coding: utf-8 -*-
"""Adaptive large-neighbourhood search (ALNS) shell for G4c / G4d.

The search is a *monotone* ruin-and-recreate / migrate loop on top of the
shared joint transaction engine:

* every accepted transaction strictly lowers the exact strict-D56 crossing
  count (``min_gain >= 1``), so ``best_valid`` can never be invalid and the
  run can be checkpointed / resumed at any time;
* operators are weighted (adaptive weights, 0.8/0.2 update) and every stage
  enforces coverage of the required neighbourhood sizes 8/16/32/64(/96);
* the conflict graph + 3-D blocker index is rebuilt every 60-90 s (the exact
  graph costs ~4 s), per-route counts are always re-derived from it;
* every failed attempt is classified with the SPEC_G4 section-6 reason keys and
  kept in ``state.failed_attempts`` (written by ``save_final``);
* budgets are checked against the shared :class:`g4.ledger.Ledger` counters and
  the wall clock; checkpoints are written every 50 accepted transactions or
  10 minutes and ``--resume`` continues from the newest one.

Operators
---------
``migrate``     pick a high-crossing route, rank its 19 body heights by the
                exact XY conflict pre-rank + blocker graph, probe the best
                heights in clean mode and commit a single-route migration or a
                joint make-way transaction when 3-D blockers exist.
``lift_direct`` interface-direct routes (~100) are lifted to body heights,
                removing their whole-board interface-body crossings.
``recreate``    BFS neighbourhood of the stage size: ruin the set, force the two
                hottest members to their best ranked heights, re-create the rest
                (fallback: keep original geometry), exact accept.
``component``   height-pure conflict component (or merged components) as the
                ruin unit, multi-order re-create with height assignment.
"""
from __future__ import annotations

import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import artifacts as ART
from . import arm_base as AB
from . import joint_world as JW
from . import make_way as MW
from . import neighborhood as NB
from . import paths as GP
from .. import world_adapter as WA

#: canonical failure reason keys (SPEC_G4 section 6)
SPEC_REASONS = (
    MW.R_NO_XY, MW.R_TARGET_OCC, MW.R_R15, MW.R_T3D, MW.R_LEAD,
    MW.R_JOINT, MW.R_NOGAIN, MW.R_BUDGET, MW.R_NO_CROSS, MW.R_STRUCT,
)

DEFAULT_CFG = dict(
    graph_refresh_seconds=100.0,    # exact conflict graph rebuild period
    graph_refresh_accepts=45,       # ... or after this many accepts
    index_refresh_accepts=30,       # rebuild the cheap blocker index
    checkpoint_seconds=600.0,       # SPEC: every 10 min
    checkpoint_accepts=50,          # SPEC: or every 50 accepts
    min_seed_crossings=2,           # ignore routes below this crossing count
    probe_limit_small=3,            # heights probed per migrate (stage 8)
    probe_limit_large=2,
    beam_small=2,                   # order strategies per make-way
    beam_large=2,
    max_blockers=3,
    recreate_free_max_size=16,      # free height re-create up to this size
    recreate_seed_pins=2,           # hottest members pinned to a ranked height
    min_recreate_attempts=3,        # guaranteed recreate coverage per stage
    lift_direct_ratio=0.10,         # probability of the interface operator
    sweep_top_k=36,                 # greedy sweep: routes per batch/round
    sweep_max_routes=240,           # greedy sweep: full ranked queue per pass
    sweep_heights=7,                # greedy sweep: quiet plane candidates
    sweep_min_gain=2,               # greedy sweep: minimum accepted gain
    sweep_retry_min_gain=1,         # greedy sweep: later passes accept gain 1
    sweep_max_passes=3,             # greedy sweep: full passes over the queue
    sweep_quality_routes=60,        # greedy sweep: stronger cfg on top routes
    sweep_early_delta=-6,           # greedy sweep: stop probing at this gain
    enable_direct_plane=False,      # interface-direct-body plane operator (G4d)
    direct_orders=2,                # re-create orders per direct-plane attempt
    failed_attempts_cap=4000,
    verbose_every_seconds=60.0,
)


def log_default(message):
    print(message, flush=True)


class FileLog:
    """Timestamped logger that echoes to stdout and appends ``run.log``."""

    def __init__(self, path, echo=True, stamp=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = bool(echo)
        self.stamp = bool(stamp)
        self.handle = self.path.open('a', encoding='utf-8')

    def __call__(self, message):
        text = str(message)
        if self.stamp:
            text = '[%s] %s' % (time.strftime('%Y-%m-%dT%H:%M:%S'), text)
        self.handle.write(text + '\n')
        self.handle.flush()
        if self.echo:
            print(text, flush=True)

    def close(self):
        try:
            self.handle.close()
        except Exception:  # noqa: BLE001
            pass


def _count_jsonable(value):
    if isinstance(value, Counter):
        return {str(k): int(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, dict):
        return {str(k): _count_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_count_jsonable(v) for v in value]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


class G4Search:
    """One G4c / G4d arm: state + ledger + LNS loop + artifact writing."""

    def __init__(self, ctx, spec, cfg=None, log=None, start_stage=0):
        self.ctx = ctx
        self.spec = spec
        self.state = ctx.state
        self.ledger = ctx.ledger
        self.cfg = dict(DEFAULT_CFG, **(cfg or {}))
        self.log = log or ctx.log or log_default
        self.jw = JW.JointWorld(self.state, ledger=self.ledger,
                                log=self.log, seed=spec.seed)
        self.ctx.jw = self.jw
        self.best = ART.BestTracker(spec, ctx.baseline, log=self.log)
        self.best.best_total = self._existing_best_total()
        self.manual_ids = set(AB.manual_route_ids(self.state))
        self.frozen = set(self.manual_ids) if spec.manual_frozen else set()
        self.movable = set(int(rid) for rid in self.state.routes) - self.frozen
        self.rng = random.Random(int(spec.seed))
        self.graph = None
        self.index = None
        self._graph_time = 0.0
        self._graph_accepts = 0
        self._accepted = 0
        self.stage_stats = []
        self.operator_stats = defaultdict(lambda: dict(
            attempts=0, accepts=0, gain=0, seconds=0.0, failures=Counter()))
        self.weights = {'migrate': 3.0, 'lift_direct': 1.0,
                        'recreate': 1.0, 'component': 0.8,
                        'direct_plane': 0.0}
        if self.cfg.get('enable_direct_plane'):
            self.weights['direct_plane'] = 2.5
        self.direct_plane_stats = {}
        self.direct_order_cycle = 0
        self.reason_totals = Counter()
        self.history_records = []
        self.state.failed_attempts = list(
            getattr(self.state, 'failed_attempts', None) or [])
        self._last_checkpoint = 0.0
        self._last_checkpoint_accepts = 0
        self._last_verbose = 0.0
        self._stop = False
        self.started = spec.started
        self.start_stage = int(start_stage or 0)
        self.total_transactions = 0

    # ------------------------------------------------------------------ aux
    def _existing_best_total(self):
        path = Path(self.spec.out_dir) / 'best_valid' / 'summary.json'
        try:
            payload = GP.read_json(path)
            return int(payload['totals']['crossings'])
        except Exception:  # noqa: BLE001 - no previous best
            return None

    def elapsed(self):
        return time.time() - self.started

    def _budget_left(self, budget):
        for key in ('route_3d_checks', 'd56_candidate_evals'):
            limit = budget.get(key)
            if limit is not None and self.ledger.data.get(key, 0) >= int(limit):
                return False
        return True

    # ---------------------------------------------------------------- graph
    def refresh_graph(self, force=False):
        """Rebuild the exact conflict graph + cheap blocker index (~4.2 s)."""
        started = time.time()
        per_route, cache = self.state.per_route_counts()
        self.graph = NB.build_conflict_graph(self.state, cache=cache,
                                             per_route=per_route)
        self.index = NB.build_block_index(self.state)
        self._graph_time = time.time()
        self._graph_accepts = self._accepted
        summary = self.graph.summary()
        self.log('[graph] %.2fs events=%d edges=%d nodes=%d components=%d '
                 'max_degree=%d sizes=%s' % (
                     time.time() - started, summary['events'], summary['edges'],
                     summary['nodes'], summary['components'],
                     summary['max_degree'], summary['component_sizes'][:8]))
        return summary

    def maybe_refresh(self):
        if self.graph is None:
            self.refresh_graph(force=True)
            return
        age = time.time() - self._graph_time
        if age >= float(self.cfg['graph_refresh_seconds']) or \
                self._accepted - self._graph_accepts >= int(self.cfg['graph_refresh_accepts']):
            self.refresh_graph(force=True)
        elif not self.index or \
                self._accepted - self._graph_accepts >= int(self.cfg['index_refresh_accepts']):
            self.index = NB.build_block_index(self.state)

    # ------------------------------------------------------------- selection
    def _candidate_seeds(self, direct=None):
        seeds = [(int(rid), int(count)) for rid, count in self.graph.per_route.items()
                 if int(rid) in self.movable and
                 int(count) >= int(self.cfg['min_seed_crossings'])]
        if not seeds:
            return []
        if direct is None:
            return seeds
        rows = []
        for rid, count in seeds:
            is_direct = int(self.state.route(rid).get('n_transitions') or 0) == 0
            if bool(is_direct) == bool(direct):
                rows.append((rid, count))
        return rows

    def pick_seed(self, direct=None):
        rows = self._candidate_seeds(direct=direct)
        if not rows:
            return None
        total = float(sum(count for _rid, count in rows))
        pick = self.rng.random() * total
        acc = 0.0
        for rid, count in rows:
            acc += count
            if pick <= acc:
                return rid
        return rows[-1][0]

    def _pick_edge(self):
        rows = []
        for (a, b), weight in self.graph.edges.items():
            if a in self.movable and b in self.movable:
                rows.append((int(weight), a, b))
        if not rows:
            return None
        total = float(sum(row[0] for row in rows))
        pick = self.rng.random() * total
        acc = 0.0
        for weight, a, b in rows:
            acc += weight
            if pick <= acc:
                return (a, b)
        return (rows[-1][1], rows[-1][2])

    # ------------------------------------------------------------- operators
    def _sweep_seeds(self, limit=None):
        """High-crossing body routes (interface-direct routes are excluded)."""
        rows = []
        min_gain = int(self.cfg.get('min_seed_crossings', 2))
        for rid, count in self.graph.per_route.items():
            rid = int(rid)
            if rid not in self.movable or int(count) < min_gain:
                continue
            if int(self.state.route(rid).get('n_transitions') or 0) == 0:
                continue
            rows.append((rid, int(count)))
        rows.sort(key=lambda row: (-row[1], row[0]))
        limit = int(limit if limit is not None else self.cfg['sweep_max_routes'])
        return [rid for rid, _count in rows[:limit]]

    def _run_sweep(self, seconds, budget):
        """Greedy forced-height migration sweep (highest gain / lowest cost).

        Every route is probed at the quietest planes of the *current* state and
        the single best exact-delta candidate is committed; the graph is
        re-ranked after every round.  This is the verified fast path that
        breaks the G3 plateau before the neighbourhood ALNS starts.
        """
        stage = dict(stage=-1, kind='sweep', size=0,
                     started_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                     seconds_budget=round(float(seconds), 1), attempts=0,
                     accepts=0, gain=0, seconds_used=0.0,
                     attempts_by_op=Counter(), accepts_by_op=Counter(),
                     gain_by_op=Counter(), reasons=Counter())
        self.stage_stats.append(stage)
        self._current_stage = -1
        started = time.time()
        initial_total = int(self.state.total)
        passes = 0
        self.log('=' * 74)
        self.log('[sweep] greedy forced-height migration budget=%.0fs total=%d'
                 % (float(seconds), self.state.total))
        passes = 0
        max_passes = int(self.cfg['sweep_max_passes'])
        while not self._stop and passes < max_passes:
            if time.time() - started >= float(seconds):
                break
            if self.elapsed() >= float(budget['wall_seconds']):
                stage['stopped'] = 'wall_budget'
                break
            if not self._budget_left(budget):
                stage['stopped'] = 'counted_budget'
                self.reason_totals[MW.R_BUDGET] += 1
                break
            if passes > 0:
                self.refresh_graph(force=True)
            passes += 1
            min_gain = int(self.cfg['sweep_min_gain']) if passes == 1 \
                else int(self.cfg['sweep_retry_min_gain'])
            queue = self._sweep_seeds()
            if not queue:
                self.log('[sweep] no seed routes with crossings left')
                break
            pass_accepts = 0
            pass_gain = 0
            for rid in queue:
                if time.time() - started >= float(seconds):
                    break
                if not self._budget_left(budget):
                    break
                if self.elapsed() >= float(budget['wall_seconds']):
                    break
                result = self._safe_operator('sweep', lambda: MW.sweep_route(
                    self.jw, rid, n_heights=int(self.cfg['sweep_heights']),
                    min_gain=min_gain,
                    early_delta=int(self.cfg['sweep_early_delta'])), [rid])
                self._record(stage, result, 'sweep')
                if result.get('accepted'):
                    pass_accepts += 1
                    pass_gain += int(result.get('gain') or 0)
                if time.time() - self._last_verbose >= float(self.cfg['verbose_every_seconds']):
                    self._last_verbose = time.time()
                    self.log('[sweep pass %d] total=%d pass_accepts=%d '
                             'attempts=%d (%.0fs/%.0fs)' % (
                                 passes, self.state.total, pass_accepts,
                                 stage['attempts'], time.time() - started,
                                 float(seconds)))
            self.log('[sweep pass %d done] accepted=%d gain=%d total=%d '
                     '(%.0fs, queue=%d)' % (
                         passes, pass_accepts, pass_gain, self.state.total,
                         time.time() - started, len(queue)))
            self._last_verbose = time.time()
            self.jw.maybe_rebuild_world()
            if pass_accepts == 0:
                self.log('[sweep] converged after pass %d' % passes)
                break
        # optional stronger-candidate quality pass on the hottest remaining routes
        quality_routes = int(self.cfg.get('sweep_quality_routes', 0) or 0)
        if quality_routes and not self._stop and \
                time.time() - started < float(seconds) * 0.7:
            self.refresh_graph(force=True)
            queue = self._sweep_seeds(limit=quality_routes)
            self.log('[sweep] quality pass on %d routes' % len(queue))
            for rid in queue:
                if time.time() - started >= float(seconds):
                    break
                if not self._budget_left(budget):
                    break
                result = self._safe_operator('sweep', lambda: MW.sweep_route(
                    self.jw, rid, n_heights=10,
                    min_gain=int(self.cfg['sweep_retry_min_gain']),
                    cfg=MW.SWEEP_QUALITY_CFG,
                    early_delta=int(self.cfg['sweep_early_delta'])), [rid])
                self._record(stage, result, 'sweep')
        stage['seconds_used'] = round(time.time() - started, 1)
        stage['final_total'] = int(self.state.total)
        stage['stage_gain'] = int(initial_total - self.state.total)
        stage['passes'] = passes
        self.log('[sweep done] attempts=%d accepts=%d gain=%d total=%d (%.0fs)' % (
            stage['attempts'], stage['accepts'], stage['stage_gain'],
            self.state.total, time.time() - started))
        self.ledger.data['wall_seconds'] = round(self.elapsed(), 2)
        self.ctx.save_checkpoint(tag='step_%05d' % self._accepted,
                                 extra=dict(stage=0, accepts=self._accepted,
                                            total=int(self.state.total),
                                            kind='sweep_done'))
        self._last_checkpoint = time.time()
        self._last_checkpoint_accepts = self._accepted
        self._write_partial()
        return stage

    def _op_migrate(self, stage):
        rid = self.pick_seed(direct=False)
        if rid is None:
            return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                        operator='migrate', rids=[], seconds=0.0)
        probe_limit = int(self.cfg['probe_limit_small'] if stage['size'] <= 16
                          else self.cfg['probe_limit_large'])
        beam = int(self.cfg['beam_small'] if stage['size'] <= 16
                   else self.cfg['beam_large'])
        height_order = NB.rank_heights_by_events(self.state, rid)
        result = MW.try_migrate(
            self.jw, rid, frozen=self.frozen, graph=self.graph, index=self.index,
            probe_limit=probe_limit, beam=beam, ledger=self.ledger,
            min_gain=1, height_order=height_order)
        return result

    def _op_lift_direct(self, stage):
        rid = self.pick_seed(direct=True)
        if rid is None:
            return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                        operator='lift_direct', rids=[], seconds=0.0)
        result = MW.try_migrate(
            self.jw, rid, frozen=self.frozen, graph=self.graph, index=self.index,
            probe_limit=2, max_frozen=0, beam=2, ledger=self.ledger,
            min_gain=1)
        result['operator'] = 'lift_direct'
        return result

    # ------------------------------------------------- direct interface plane
    def _direct_route_sets(self):
        """``{interface_layer: [rid, ...]}`` of the interface-direct bodies."""
        sets = {}
        for rid in self.movable:
            row = self.state.row(rid)
            layer = int(row.get('target_layer') or 0)
            if layer not in (1001, 1002):
                continue
            if int(self.state.route(rid).get('n_transitions') or 0) != 0:
                continue
            sets.setdefault(layer, []).append(int(rid))
        return sets

    def _direct_cfg(self):
        return dict(max_target_layers=0, max_lead_pairs=1,
                    prescreen_candidates=90, max_candidates=120, d56_top=8,
                    bodies_per_pair=1, max_return=2, allow_direct=True,
                    allow_xy_only=False)

    def _direct_orders(self, layer):
        self.direct_order_cycle += 1
        all_orders = ['desc', 'asc', 'random', 'endpoint']
        count = max(1, int(self.cfg.get('direct_orders', 2)))
        start = self.direct_order_cycle % len(all_orders)
        return [all_orders[(start + i) % len(all_orders)]
                for i in range(count)]

    def _op_direct_plane(self, stage):
        """Rip + jointly re-create all interface-direct bodies of one plane.

        The 97 interface-direct bodies cause 212 of the 1322 start crossings
        (80 on z=0, 130 on z=0.5) by crossing each other on the full-board
        interface plane; the ~460 lifted leads at the same height are fixed
        constraints and are **not** ripped.  Every direct body is re-planned at
        its own interface height (``kind='direct'``) in several orders and the
        whole plane is accepted only when the exact strict-D56 recount improves.
        """
        started = time.time()
        sets = self._direct_route_sets()
        ranked = []
        for layer, rids in sets.items():
            if len(rids) < 4:
                continue
            z = float(self.state.row(rids[0])['target_z_mm'])
            z_key = WA.plane_key(z)
            events = int(self.state.plane_counts.get(z_key, (0, 0))[0])
            stats = self.direct_plane_stats.setdefault(
                layer, dict(attempts=0, accepts=0, gain=0, fails=0))
            priority = float(events) - 25.0 * stats['accepts'] \
                - 35.0 * stats['fails']
            ranked.append((priority, events, layer, z, rids))
        if not ranked:
            return dict(accepted=False, gain=0, reason=MW.R_NO_CROSS,
                        operator='direct_plane', rids=[], seconds=0.0)
        ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
        _priority, events, layer, z, rids = ranked[0]
        forced_map = {int(rid): (int(layer), float(z)) for rid in rids}
        cfg = self._direct_cfg()
        orders = self._direct_orders(layer)
        results = []
        stats = self.direct_plane_stats.setdefault(
            layer, dict(attempts=0, accepts=0, gain=0, fails=0))
        for strategy in orders:
            result = self._safe_operator(
                'direct_plane',
                lambda: MW.try_recreate(
                    self.jw, rids, strategy=strategy, cfg=cfg,
                    ledger=self.ledger, min_gain=1,
                    forced_map=forced_map, graph=self.graph,
                    note='direct_plane_%d_%s' % (layer, strategy)),
                rids)
            results.append(result)
            stats['attempts'] += 1
            if result.get('accepted'):
                stats['accepts'] += 1
                stats['gain'] += int(result.get('gain') or 0)
                result['operator'] = 'direct_plane'
                result['interface_layer'] = int(layer)
                result['plane_events_before'] = int(events)
                result['direct_routes'] = len(rids)
                result['orders_tried'] = len(results)
                return result
            stats['fails'] += 1
        result = results[-1] if results else dict(
            accepted=False, gain=0, reason=MW.R_JOINT,
            operator='direct_plane', rids=rids, seconds=0.0)
        result['operator'] = 'direct_plane'
        result['interface_layer'] = int(layer)
        result['plane_events_before'] = int(events)
        result['direct_routes'] = len(rids)
        result['orders_tried'] = len(results)
        result['seconds'] = round(time.time() - started, 3)
        return result

    def _op_recreate(self, stage):
        size = int(stage['size'])
        seed = self.pick_seed()
        if seed is None:
            edge = self._pick_edge()
            if edge is None:
                return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                            operator='recreate', rids=[], seconds=0.0)
            seed = max(edge, key=lambda rid: self.graph.crossing_count(rid))
        rids = NB.select_neighborhood(self.graph, [seed], size, rng=self.rng,
                                      allowed=self.movable)
        rids = [rid for rid in rids if rid in self.movable]
        if len(rids) < 4:
            return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                        operator='recreate', rids=rids, seconds=0.0)
        forced_map = self._pin_hot_routes(rids, pins=int(self.cfg['recreate_seed_pins']))
        free = len(rids) <= int(self.cfg['recreate_free_max_size'])
        cfg = self._recreate_cfg(size, free=free)
        strategies = ['desc', 'asc'] if stage['size'] <= 16 else ['desc', 'random']
        started = time.time()
        results = []
        for strategy in strategies:
            result = MW.try_recreate(
                self.jw, rids, strategy=strategy, cfg=cfg, ledger=self.ledger,
                min_gain=1, forced_map=forced_map, forced_same=not free,
                graph=self.graph, note='recreate_%d_%s' % (size, strategy))
            results.append(result)
            if result['accepted']:
                result['operator'] = 'recreate'
                result['stage_size'] = size
                result['strategies_tried'] = len(results)
                return result
        result = results[-1]
        result['operator'] = 'recreate'
        result['stage_size'] = size
        result['strategies_tried'] = len(results)
        result['seconds'] = round(time.time() - started, 3)
        return result

    def _op_component(self, stage):
        comps = NB.component_neighborhoods(self.graph, allowed=self.movable,
                                           min_size=4, max_size=int(stage['size']))
        if not comps:
            return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                        operator='component', rids=[], seconds=0.0)
        comp = comps[self.rng.randrange(min(len(comps), 8))]
        rids = [rid for rid in comp['routes'] if rid in self.movable]
        if len(rids) < 4:
            return dict(accepted=False, reason=MW.R_NO_CROSS, gain=0,
                        operator='component', rids=rids, seconds=0.0)
        forced_map = self._pin_hot_routes(rids, pins=int(self.cfg['recreate_seed_pins']))
        free = len(rids) <= int(self.cfg['recreate_free_max_size'])
        cfg = self._recreate_cfg(len(rids), free=free)
        result = MW.try_recreate(
            self.jw, rids, strategy='desc', cfg=cfg, ledger=self.ledger,
            min_gain=1, forced_map=forced_map, forced_same=not free,
            graph=self.graph, note='component_%d' % len(rids))
        result['operator'] = 'component'
        result['stage_size'] = int(stage['size'])
        result['component_events'] = int(comp['events'])
        return result

    def _pin_hot_routes(self, rids, pins=2):
        """Height assignment for the hottest neighbourhood members."""
        ranked = sorted(rids, key=lambda rid: (
            -self.graph.crossing_count(rid), rid))
        forced_map = {}
        for rid in ranked[:max(0, int(pins))]:
            if rid in self.frozen:
                continue
            rows = NB.rank_target_heights(self.state, rid, frozen=self.frozen,
                                          index=self.index)
            if not rows:
                continue
            best = rows[0]
            if best['n_frozen'] > 0:
                continue
            forced_map[int(rid)] = (int(best['layer']), float(best['z']))
        return forced_map

    def _recreate_cfg(self, size, free=True):
        if free:
            return dict(max_target_layers=(2 if size <= 8 else 1),
                        max_lead_pairs=1, prescreen_candidates=70,
                        max_candidates=90, d56_top=6, bodies_per_pair=1,
                        max_return=1, allow_direct=False, allow_xy_only=False)
        return dict(max_target_layers=0, max_lead_pairs=1,
                    prescreen_candidates=60, max_candidates=80, d56_top=5,
                    bodies_per_pair=1, max_return=1, allow_direct=True,
                    allow_xy_only=False)

    # ----------------------------------------------------------- bookkeeping
    def _safe_operator(self, name, thunk, rids):
        """Run one operator call; a bug must never kill a multi-hour arm."""
        started = time.time()
        try:
            return thunk()
        except Exception as error:  # noqa: BLE001 - keep the arm alive
            import traceback
            detail = traceback.format_exc().splitlines()[-1]
            self.log('[warn] operator %s raised %s: %s' % (
                name, type(error).__name__, detail))
            return dict(accepted=False, gain=0, delta=0,
                        reason=MW.R_JOINT, operator=name,
                        rids=list(rids or []),
                        seconds=round(time.time() - started, 3),
                        order=[], strategy='exception')

    def _record(self, stage, result, op_name):
        seconds = float(result.get('seconds') or 0.0)
        accepted = bool(result.get('accepted'))
        gain = int(result.get('gain') or 0)
        stats = self.operator_stats[op_name]
        stats['attempts'] += 1
        stats['seconds'] += seconds
        if accepted:
            stats['accepts'] += 1
            stats['gain'] += gain
            self._accepted += 1
            stage['accepts'] += 1
            stage['gain'] += gain
            stage['accepts_by_op'][op_name] += 1
            stage['gain_by_op'][op_name] += gain
        else:
            reason = result.get('reason') or 'unknown'
            stats['failures'][reason] += 1
            stage['reasons'][reason] += 1
            self.reason_totals[reason] += 1
            attempts = self.state.failed_attempts
            if len(attempts) < int(self.cfg['failed_attempts_cap']):
                attempts.append(dict(
                    stage=int(stage['stage']), operator=op_name,
                    rids=list(result.get('rids') or []),
                    reason=str(reason),
                    seconds=round(seconds, 3),
                    wall=round(self.elapsed(), 2)))
        stage['attempts'] += 1
        stage['attempts_by_op'][op_name] += 1
        stage['seconds_used'] += seconds
        self.total_transactions = len(self.jw.transaction_history)
        self.history_records.append(dict(
            stage=int(stage['stage']), operator=op_name, accepted=accepted,
            gain=gain, delta=int(result.get('delta') or 0),
            routes=list(result.get('rids') or []),
            order=list(result.get('order') or []),
            strategy=str(result.get('strategy') or ''),
            reason=str(result.get('reason') or ''),
            seconds=round(seconds, 3), wall=round(self.elapsed(), 2),
            total=int(self.state.total),
            best_total=int(self.best.best_total or self.state.total)))
        if accepted:
            self.best.consider(self.state, note='%s gain=%d' % (op_name, gain))
            self.jw.maybe_rebuild_world()
            if op_name in ('direct_plane', 'recreate', 'component'):
                # large structural change: re-rank the conflict graph soon
                self._graph_time = 0.0
                self.index = None
            self._maybe_checkpoint()
        self._update_weight(op_name, accepted, gain, seconds)

    def _update_weight(self, op_name, accepted, gain, seconds):
        reward = 0.0
        if accepted:
            reward = 1.0 + min(4.0, float(gain))
            if seconds > 1.0:
                reward = reward / max(1.0, seconds / 2.0)
        weight = float(self.weights.get(op_name, 1.0))
        self.weights[op_name] = max(0.05, 0.8 * weight + 0.2 * reward)

    def _choose_operator(self, stage):
        names = [name for name in self.weights
                 if name in ('migrate', 'lift_direct', 'recreate',
                             'component', 'direct_plane')
                 and (name != 'direct_plane'
                      or self.cfg.get('enable_direct_plane'))]
        if stage['size'] <= 8:
            names = ['migrate', 'migrate', 'recreate', 'component', 'lift_direct']
        total = sum(self.weights.get(name, 0.5) for name in names)
        pick = self.rng.random() * total
        acc = 0.0
        for name in names:
            acc += self.weights.get(name, 0.5)
            if pick <= acc:
                return name
        return names[-1]

    def _maybe_checkpoint(self):
        now = time.time()
        if now - self._last_checkpoint < float(self.cfg['checkpoint_seconds']) and \
                self._accepted - self._last_checkpoint_accepts < int(self.cfg['checkpoint_accepts']):
            return
        self._last_checkpoint = now
        self._last_checkpoint_accepts = self._accepted
        self.ledger.data['wall_seconds'] = round(self.elapsed(), 2)
        try:
            self.ctx.save_checkpoint(tag='step_%05d' % self._accepted,
                                     extra=dict(stage=self._current_stage,
                                                accepts=self._accepted,
                                                best_total=int(self.best.best_total
                                                               or self.state.total),
                                                total=int(self.state.total)))
        except Exception as error:  # noqa: BLE001 - a checkpoint must never kill the run
            self.log('[warn] checkpoint failed: %s' % error)

    # ------------------------------------------------------------------ run
    def run(self, wall_seconds, stage_sizes, stage_fractions, sweep_seconds=0.0,
            skip_sweep=False):
        self._current_stage = 0
        self.maybe_refresh()
        self.best.consider(self.state, note='start')
        self.log('[search] arm=%s manual_frozen=%s routes=%d crossings=%d '
                 'manual=%d movable=%d stages=%s sweep=%.0fs skip_sweep=%s' % (
                     self.spec.arm, self.spec.manual_frozen,
                     len(self.state.routes), self.state.total,
                     len(self.manual_ids), len(self.movable),
                     list(zip(stage_sizes, stage_fractions)),
                     float(sweep_seconds), skip_sweep))
        budget = dict(self.spec.budget)
        budget['wall_seconds'] = float(wall_seconds)
        sweep_seconds = max(0.0, min(float(sweep_seconds), float(wall_seconds) * 0.9))
        sweep_used = 0.0
        if sweep_seconds > 0 and self.start_stage == 0 and not skip_sweep:
            stage = self._run_sweep(sweep_seconds, budget)
            sweep_used = float((stage or {}).get('seconds_used') or 0.0)
        # unused sweep budget flows into the neighbourhood stages
        stage_pool = max(1.0, float(wall_seconds) - sweep_used)
        for stage_index, (size, fraction) in enumerate(
                zip(stage_sizes, stage_fractions)):
            if stage_index < self.start_stage:
                continue
            stage_seconds = stage_pool * float(fraction)
            if not self._budget_left(budget):
                self.log('[search] counted budget exhausted before stage %d' % stage_index)
                break
            if self.elapsed() >= float(wall_seconds):
                self.log('[search] wall budget exhausted before stage %d' % stage_index)
                break
            self._run_stage(stage_index, int(size), stage_seconds, budget)
            if not self._budget_left(budget):
                break
            if self.elapsed() >= float(wall_seconds):
                break
        self._write_partial()
        return self.finish()

    def _run_stage(self, stage_index, size, seconds, budget):
        self._current_stage = stage_index
        self.rng = random.Random(int(self.spec.seed) + int(stage_index) * 101)
        stage = dict(stage=int(stage_index), size=int(size),
                     started_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                     seconds_budget=round(seconds, 1), attempts=0,
                     accepts=0, gain=0, seconds_used=0.0,
                     attempts_by_op=Counter(), accepts_by_op=Counter(),
                     gain_by_op=Counter(), reasons=Counter())
        self.stage_stats.append(stage)
        started = time.time()
        initial_total = int(self.state.total)
        self.log('=' * 74)
        self.log('[stage %d] neighbourhood size=%d budget=%.0fs total=%d' % (
            stage_index, size, seconds, self.state.total))
        forced = self._forced_schedule(size)
        min_recreate = int(self.cfg.get('min_recreate_attempts', 3))
        recreate_attempts = 0
        while True:
            if self._stop:
                stage['stopped'] = 'interrupted'
                break
            if time.time() - started >= seconds:
                break
            if self.elapsed() >= float(budget['wall_seconds']):
                stage['stopped'] = 'wall_budget'
                break
            if not self._budget_left(budget):
                stage['stopped'] = 'counted_budget'
                self.reason_totals[MW.R_BUDGET] += 1
                break
            self.maybe_refresh()
            if forced:
                op_name = forced.pop(0)
            else:
                op_name = self._choose_operator(stage)
            if op_name == 'recreate' and recreate_attempts >= min_recreate and \
                    stage['attempts'] > 0 and self.rng.random() < 0.5:
                op_name = 'migrate'
            if op_name == 'migrate':
                result = self._safe_operator(op_name, lambda: self._op_migrate(stage), [])
            elif op_name == 'lift_direct':
                result = self._safe_operator(op_name, lambda: self._op_lift_direct(stage), [])
            elif op_name == 'recreate':
                recreate_attempts += 1
                result = self._safe_operator(op_name, lambda: self._op_recreate(stage), [])
            else:
                result = self._safe_operator(op_name, lambda: self._op_component(stage), [])
            self._record(stage, result, op_name)
            if time.time() - self._last_verbose >= float(self.cfg['verbose_every_seconds']):
                self._last_verbose = time.time()
                self._log_progress(stage, started, initial_total, seconds)
        stage['seconds_used'] = round(time.time() - started, 1)
        stage['final_total'] = int(self.state.total)
        stage['stage_gain'] = int(initial_total - self.state.total)
        self.log('[stage %d done] size=%d attempts=%d accepts=%d gain=%d '
                 'total=%d (%.0fs) ops=%s reasons=%s' % (
                     stage_index, size, stage['attempts'], stage['accepts'],
                     stage['stage_gain'], self.state.total,
                     round(time.time() - started, 1),
                     dict(stage['accepts_by_op']),
                     dict(list(stage['reasons'].most_common(6)))))
        self.ledger.data['wall_seconds'] = round(self.elapsed(), 2)
        self.ctx.save_checkpoint(tag='step_%05d' % self._accepted,
                                 extra=dict(stage=stage_index + 1,
                                            accepts=self._accepted,
                                            total=int(self.state.total)))
        self._last_checkpoint = time.time()
        self._last_checkpoint_accepts = self._accepted
        self._write_partial()

    def _forced_schedule(self, size):
        """Guarantee SPEC coverage: every stage tests its neighbourhood size."""
        schedule = []
        if self.cfg.get('enable_direct_plane'):
            schedule.append('direct_plane')
        schedule.extend(['recreate', 'component', 'migrate', 'migrate',
                         'lift_direct', 'migrate', 'recreate'])
        return schedule

    def _log_progress(self, stage, started, initial_total, seconds):
        elapsed = time.time() - started
        attempts = max(1, stage['attempts'])
        self.log('[stage %d %.0f/%.0fs] total=%d gain=%d attempts=%d accepts=%d '
                 'rate=%.1f%% ops=%s topfail=%s' % (
                     stage['stage'], elapsed, seconds, self.state.total,
                     int(initial_total - self.state.total), stage['attempts'],
                     stage['accepts'], 100.0 * stage['accepts'] / attempts,
                     dict(stage['accepts_by_op']),
                     dict(stage['reasons'].most_common(4))))

    # --------------------------------------------------------------- saving
    def _write_partial(self):
        payload = dict(arm=self.spec.arm, stage_stats=[
            _count_jsonable(stage) for stage in self.stage_stats],
            operator_stats={name: _count_jsonable(stats)
                            for name, stats in self.operator_stats.items()},
            reason_totals=dict(self.reason_totals),
            weights=dict(self.weights),
            accepts=int(self._accepted), total=int(self.state.total),
            seconds=round(self.elapsed(), 2),
            ledger=self.ledger.summary())
        try:
            GP.write_json(Path(self.spec.out_dir) / 'strategy_stats_partial.json',
                          payload)
        except Exception as error:  # noqa: BLE001
            self.log('[warn] partial stats write failed: %s' % error)

    def finish(self):
        """Final exact save + independent validator + strategy stats."""
        self.log('[search] finishing: total=%d accepts=%d transactions=%d (%.1fs)' % (
            self.state.total, self._accepted, len(self.jw.transaction_history),
            self.elapsed()))
        self.refresh_graph(force=True)
        self.best.force_save(self.state, note='final best total=%d' % self.state.total)
        validation = ART.run_validation(
            Path(self.spec.out_dir) / 'best_valid',
            Path(self.spec.out_dir) / 'validation',
            baseline_dir=str(GP.AUTHORITY_DIR),
            manual_policy='fully_optimizable',
            python=__import__('sys').executable, log=self.log)
        self.ledger.bump('validator_runs')
        extra = self.extra_payload(validation=validation)
        self.ledger.data['wall_seconds'] = round(self.elapsed(), 2)
        self.ctx.save_final(note='G4 LNS final total=%d' % self.state.total,
                            extra=extra)
        self._write_partial()
        self._write_summary(extra, validation)
        return dict(total=int(self.state.total), accepts=int(self._accepted),
                    validation=validation, out_dir=str(self.spec.out_dir))

    def extra_payload(self, validation=None):
        graph_summary = self.graph.summary() if self.graph is not None else {}
        return dict(
            schema='g4_strategy_stats_v1',
            arm=self.spec.arm,
            manual_frozen=bool(self.spec.manual_frozen),
            start_crossings=int(GP.START_CROSSINGS),
            final_crossings=int(self.state.total),
            delta_vs_start=int(self.state.total) - int(GP.START_CROSSINGS),
            accepts=int(self._accepted),
            transactions=len(self.jw.transaction_history),
            transaction_history=self.jw.transaction_history[-400:],
            stage_stats=[_count_jsonable(stage) for stage in self.stage_stats],
            operator_stats={name: _count_jsonable(stats)
                            for name, stats in self.operator_stats.items()},
            reason_totals=dict(self.reason_totals),
            weights=dict(self.weights),
            graph_summary=graph_summary,
            cfg=dict(self.cfg),
            ledger=self.ledger.summary(),
            validation=validation,
            history_records=self.history_records[-800:],
        )

    def _write_summary(self, extra, validation):
        stats = None
        try:
            stats = GP.read_json(Path(self.spec.out_dir) / 'summary.json')
        except Exception:  # noqa: BLE001
            stats = {}
        geometry = None
        try:
            geometry = GP.read_json(Path(self.spec.out_dir) / 'geometry_changes.json')
        except Exception:  # noqa: BLE001
            geometry = {}
        changed = len((geometry or {}).get('changes') or [])
        pass_flag = None
        if isinstance(validation, dict):
            try:
                payload = GP.read_json(Path(self.spec.out_dir) / 'validation' /
                                       'validation.json')
                pass_flag = payload.get('validation_pass')
            except Exception:  # noqa: BLE001
                pass_flag = None
        payload = dict(
            arm=self.spec.arm,
            final_crossings=int(self.state.total),
            crossing_pairs=int(self.state.pairs),
            start_crossings=int(GP.START_CROSSINGS),
            delta_vs_start=int(self.state.total) - int(GP.START_CROSSINGS),
            routes_changed=int(changed),
            routes=len(self.state.routes),
            accepts=int(self._accepted),
            transactions=len(self.jw.transaction_history),
            seconds=round(self.elapsed(), 2),
            best_valid_dir=str(Path(self.spec.out_dir) / 'best_valid'),
            validation_pass=pass_flag,
            validation_exit=int((validation or {}).get('exit_code', -1)),
            ledger=self.ledger.summary(),
            stages=[dict(stage=stage['stage'], size=stage['size'],
                         attempts=stage['attempts'], accepts=stage['accepts'],
                         gain=stage['stage_gain'],
                         seconds=stage['seconds_used'],
                         reasons=dict(stage['reasons']))
                    for stage in self.stage_stats],
            summary=(stats or {}).get('totals'),
        )
        GP.write_json(Path(self.spec.out_dir) / 'summary_g4.json', payload)
        self.log('[search] summary: %s' % json.dumps(payload, ensure_ascii=False)[:1200])
        return payload
