# -*- coding: utf-8 -*-
"""Joint multi-route transaction engine for G4 (XY+Z large-neighbourhood search).

This module is the shared foundation of every G4 experiment:

* :class:`JointWorld` -- wraps the existing :class:`world_adapter.RouteWorld`
  and adds *(a)* candidate planning at a forced / free physical height reusing
  the frozen ``local_reroute`` candidate library, *(b)* incremental true-3D
  World maintenance for a *set* of routes (drop -> plan -> place -> accept or
  rollback) **without** rebuilding the whole World after every change,
  *(c)* exact crossing recount of the affected physical heights only.

* :class:`Transaction` -- all-or-nothing joint re-routing of ``k`` routes.
  While a transaction is open the true 3D World and the per-height D56 state
  always contain exactly the *current* geometry: ripped routes are absent,
  already re-planned routes are present, not-yet-planned ones are absent.
  A candidate for route ``i`` is therefore checked against the real world of
  the transaction state.  ``finish()`` recounts the affected heights with the
  frozen strict-D56 rule and either commits the whole set or rolls everything
  back.  A partially legal set can never be left behind.

* module helpers: crossing-conflict graph, plane occupancy, per-route height
  plans, exact subset recount.

Budget accounting goes through :class:`g4.ledger.Ledger` so every arm reports
comparable counters (task 7: identical candidate-evaluation budget).
"""
from __future__ import annotations

import copy
import time
from collections import Counter, defaultdict

from ....d56.index import prepare as d56_prepare
from ....l3d.world import World
from ....l3d.world import part_id as world_part_id
from ... import common as C
from .. import local_reroute as LR
from .. import route_builder as RB
from .. import world_adapter as WA
from ...native3d import route_model as RM
from ...reheight21 import model as M
from . import ledger as L

CLEARANCE_MM = float(C.MIN_3D_CLEARANCE_MM)
R15 = float(C.MIN_BEND_RADIUS_MM)

#: every this-many joint transactions the incremental World is rebuilt from
#: scratch to bound the memory of the clearance-world's append-only entry lists
WORLD_REBUILD_EVERY = 150

#: default candidate-generation configuration for one route (bounded, exact-D56
#: ranked).  Callers may override any key.
PLAN_CFG = dict(
    max_target_layers=3,      # free-height options besides the current height
    max_lead_pairs=2,
    prescreen_candidates=160,
    max_candidates=320,
    d56_top=16,
    bodies_per_pair=2,
    max_return=4,             # candidates returned per route (best first)
)


def log_noop(*_args, **_kwargs):
    return None


# ---------------------------------------------------------------------------
# exact crossing recount of a subset of physical heights
# ---------------------------------------------------------------------------
def recount_subset(state, z_keys):
    """Recount ``state.plane_counts`` for ``z_keys`` only and refresh totals.

    Uses the frozen strict-D56 audit (``nonc4.crossings.audit_flat_group``),
    identical to ``world_adapter._recount_planes`` but restricted to the
    affected heights.  Empty heights are recorded as ``(0, 0)`` so a stale
    count can never survive a plane becoming empty.
    """
    from ...nonc4 import crossings as X
    for z_key in sorted(set(WA.plane_key(z) for z in z_keys)):
        prims = state.plane_prims.get(z_key) or {}
        if not prims:
            state.plane_counts[z_key] = (0, 0)
            continue
        result = X.audit_flat_group(prims)
        state.plane_counts[z_key] = (int(result.get('crossing_count') or 0),
                                     int(result.get('crossing_pair_count') or 0))
    state.total = int(sum(value[0] for value in state.plane_counts.values()))
    state.pairs = int(sum(value[1] for value in state.plane_counts.values()))
    return int(state.total)


def crossing_events(state, cache=None):
    """Exact crossing events of the current state (frozen strict-D56 rule)."""
    if cache is None:
        cache = state.per_route_counts()[1]
    return [dict(route_a=int(event['route_a']), route_b=int(event['route_b']),
                 z_mm=float(event['z_mm']), x_mm=float(event['x_mm']),
                 y_mm=float(event['y_mm']),
                 angle_deg=float(event['angle_deg']))
            for event in cache.crossing_events()]


def crossing_graph(state, cache=None):
    """``Counter{(a, b): events}`` of the real same-layer crossing conflict graph."""
    graph = Counter()
    for event in crossing_events(state, cache=cache):
        key = tuple(sorted((int(event['route_a']), int(event['route_b']))))
        graph[key] += 1
    return graph


def per_route_crossings(state):
    values = Counter()
    for event in crossing_events(state):
        values[int(event['route_a'])] += 1
        values[int(event['route_b'])] += 1
    return values


def plane_occupancy(state):
    """``{z_key: {rid: [prims]}}`` of the current per-height flat occupancy."""
    return {z_key: dict(table) for z_key, table in state.plane_prims.items()}


def route_height_plan(route):
    """``[(z_mm, n_flat_parts), ...]`` of one route in traversal order."""
    plan = []
    for part in route.get('parts') or ():
        if part.get('kind') != 'flat':
            continue
        plan.append((round(float(part['z_mm']), 9), 1))
    return plan


def primary_height(route):
    """Physical height of the route's body (largest flat chain; interface height
    for direct routes).  Used for grouping / migration statistics only."""
    groups = WA.route_flat_groups(route)
    if not groups:
        return None
    best = max(groups.items(), key=lambda item: sum(len(chain) for chain in item[1]))
    return float(best[0])


class PlanCandidate:
    """One exact, building-valid route candidate for a single route."""

    __slots__ = ('route', 'layer', 'z_mm', 'kind', 'family', 'lead_s',
                 'lead_t', 'xy_crossings', 'delta', 'length_mm', 'score')

    def __init__(self, route, layer, z_mm, kind, family, lead_s, lead_t,
                 xy_crossings, delta, length_mm):
        self.route = route
        self.layer = int(layer)
        self.z_mm = float(z_mm)
        self.kind = str(kind)
        self.family = str(family)
        self.lead_s = float(lead_s)
        self.lead_t = float(lead_t)
        self.xy_crossings = int(xy_crossings)
        self.delta = None if delta is None else int(delta)
        self.length_mm = float(length_mm)
        self.score = ((self.delta if self.delta is not None
                       else self.xy_crossings), self.length_mm)

    def as_dict(self):
        return dict(layer=self.layer, z_mm=self.z_mm, kind=self.kind,
                    family=self.family, lead_s_mm=self.lead_s,
                    lead_t_mm=self.lead_t, xy_crossings=self.xy_crossings,
                    delta=self.delta, length_mm=self.length_mm,
                    route_id=int(self.route.get('route_id', 0)))


class JointWorld:
    """Route state + true-3D world + budget ledger for the G4 search."""

    def __init__(self, state, ledger=None, log=None, seed=None):
        self.state = state
        self.ledger = ledger if ledger is not None else L.Ledger()
        self.log = log or log_noop
        self.rng = __import__('random').Random(int(seed if seed is not None
                                                   else 20261104))
        self._transactions_since_rebuild = 0
        self.transaction_history = []
        self.accepted = 0
        self.rollbacks = 0

    # ------------------------------------------------------------------ world
    def raw_world(self):
        """The incremental true-3D ``l3d.world.World`` (built on first use)."""
        world = self.state.world_cache.get('all')
        if world is None:
            started = time.time()
            world = self.state._world_all()
            self.ledger.bump('world_builds')
            self.log('[world] rebuilt true-3D world (%.2fs)' % (time.time() - started))
            self._transactions_since_rebuild = 0
        return world

    def _invalidate_height_caches(self, z_keys):
        for z_key in z_keys:
            self.state.prim_grids.pop(WA.plane_key(z_key), None)
        self.state.obstacle_samples = self.state._build_obstacle_samples()
        self.state.obstacle_cache = {}

    def plane_key_count(self):
        return len(self.state.plane_prims)

    # -------------------------------------------------------- light placement
    def _light_rip(self, rid):
        """Remove one route from the per-height D56 bookkeeping (not World).

        Scans **all** height tables (21 entries) instead of trusting
        ``_route_groups`` so that an orphaned entry can never survive.
        """
        state = self.state
        rid = int(rid)
        for z_key in list(state.plane_prims.keys()):
            table = state.plane_prims.get(z_key) or {}
            if rid not in table:
                continue
            index = state.planes.get(z_key)
            if index is not None and rid in state.plane_chains.get(z_key, {}):
                index.remove(rid)
            state.plane_chains.get(z_key, {}).pop(rid, None)
            table.pop(rid, None)
        state._route_groups[rid] = {}

    def _light_place(self, rid, route, row=None):
        """Insert one route into the per-height D56 bookkeeping (not World)."""
        state = self.state
        rid = int(rid)
        self._light_rip(rid)
        groups = WA.route_flat_groups(route)
        for z_key, chains in groups.items():
            merged = []
            for chain in chains:
                merged.extend(dict(prim) for prim in chain)
            prepared = d56_prepare(merged)
            state.plane_prims.setdefault(z_key, {})[rid] = merged
            state.plane_chains.setdefault(z_key, {})[rid] = prepared
            index = state.planes.get(z_key)
            if index is None:
                index = WA.new_index()
                state.planes[z_key] = index
            index.add(rid, prepared)
        state.routes[rid] = copy.deepcopy(route)
        if row is not None:
            state.rows[rid] = dict(row)
        state._route_groups[rid] = groups

    def _world_drop(self, rid):
        """Remove one route from the incremental true-3D world entirely."""
        world = self.raw_world()
        rid = int(rid)
        route = world.plan.get(rid)
        if route is not None:
            for index, part in enumerate(route['parts']):
                if part['kind'] == 'flat':
                    world.planes.remove(world_part_id(rid, index), part['z_mm'])
        world.clearance_world.drop_route(rid)
        world.plan.pop(rid, None)

    def _world_add(self, rid, route):
        self.raw_world().add_route(route)

    # --------------------------------------------------------- candidate plans
    def _height_options(self, rid, cfg):
        """Ranked target-height options of one route (mirrors G3's policy)."""
        row = self.state.row(rid)
        route = self.state.route(rid)
        cur_layer = int(row['target_layer'])
        cur_z = float(row['target_z_mm'])
        interface = float(row['interface_z_mm'])
        counts = self.state.route_counts_by_plane()
        options = []
        ranked = []
        for plane_id in RB.BODY_PLANE_IDS:
            z = float(RB.PLANE_Z[int(plane_id)])
            if abs(z - cur_z) < 1e-9 and int(plane_id) == cur_layer:
                continue
            load = int(counts.get(WA.plane_key(z), 0))
            ranked.append((load, abs(z - cur_z), int(plane_id), z))
        ranked.sort()
        allowed = cfg.get('allowed_layers')
        choose_new_height = cfg.get('choose_new_height', True)
        if choose_new_height:
            for load, _dz, plane_id, z in ranked:
                if allowed is not None and plane_id not in allowed:
                    continue
                options.append(dict(kind='migrate', layer=plane_id, z=z,
                                    load=load, priority=0))
                if len(options) >= int(cfg.get('max_target_layers', 3)):
                    break
        direct = int(route.get('n_transitions') or 0) == 0
        if cfg.get('allow_direct', True) and not direct:
            plane_id = int(RB.INTERFACE_PLANE[row['plane']])
            options.append(dict(kind='direct', layer=plane_id,
                                z=interface, load=0, priority=1))
        if cfg.get('allow_xy_only', True) and cur_layer not in (1001, 1002):
            options.append(dict(kind='xy_only', layer=cur_layer, z=cur_z,
                                load=0, priority=2))
        elif cfg.get('allow_xy_only', True):
            options.append(dict(kind='direct_xy', layer=cur_layer, z=cur_z,
                                load=0, priority=2))
        return options

    def _lead_pairs(self, rid, option, cfg):
        route = self.state.route(rid)
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
        return pairs[:max(1, int(cfg.get('max_lead_pairs', 2)))]

    def plan_candidates(self, rid, cfg=None, mode='clean', row_override=None):
        """Exact route candidates of one route, best first.

        ``mode='clean'``       : the route is currently in the state; the true 3D
                                 world is complete.  Candidates additionally get
                                 the exact crossing delta.
        ``mode='transaction'`` : the route has been ripped out of the state and
                                 the world; candidates are only checked against
                                 the *current* transaction world (which contains
                                 exactly the non-ripped + already re-planned
                                 routes).  ``delta`` is ``None`` and the score is
                                 the on-target-height D56 crossing count.
        """
        cfg = dict(PLAN_CFG, **(cfg or {}))
        state = self.state
        rid = int(rid)
        row = dict(row_override) if row_override is not None else state.row(rid)
        old_route = state.route(rid) if mode == 'clean' else None
        candidates = []
        for option in self._height_options(rid, cfg):
            for lead_s, lead_t in self._lead_pairs(rid, option, cfg):
                try:
                    task, _source, _target = LR.make_task_for_option(
                        state, rid, option, lead_s, lead_t)
                except (RB.BuilderError, ValueError) as error:
                    self.ledger.bump('no_candidate')
                    continue
                bodies = LR.xy_candidates(
                    state, rid, task, int(option['layer']),
                    float(option['z']), cfg)
                self.ledger.bump('d56_candidate_evals',
                                 int(cfg.get('d56_top', 16)))
                self.ledger.bump('xy_candidates_generated', len(bodies))
                if not bodies:
                    self.ledger.bump('no_candidate')
                    continue
                for body_record in bodies[:int(cfg.get('max_return', 4))]:
                    try:
                        route = LR.build_route_candidate(
                            state, rid, option, lead_s, lead_t,
                            body_record['body'])
                    except (RB.BuilderError, ValueError) as error:
                        self.ledger.bump('rejected_3d')
                        continue
                    candidate = self._check_candidate(
                        rid, route, option, body_record, lead_s, lead_t,
                        mode=mode, old_route=old_route)
                    if candidate is not None:
                        candidates.append(candidate)
                if candidates and len(candidates) >= int(cfg.get('max_return', 4)) * 2:
                    break
            if cfg.get('max_combos') is not None and \
                    len(candidates) >= int(cfg['max_combos']):
                break
        candidates.sort(key=lambda item: item.score)
        return candidates

    def _check_candidate(self, rid, route, option, body_record, lead_s, lead_t,
                         mode='clean', old_route=None):
        state = self.state
        if mode == 'clean':
            structural = World.check_structure(route)
            self.ledger.bump('route_3d_checks')
            if structural:
                self.ledger.bump('rejected_3d')
                return None
            evaluation = state.evaluate_candidate(rid, route)
            if not evaluation['ok']:
                self.ledger.bump('rejected_3d')
                return None
            self.ledger.bump('valid_candidates')
            delta = int(evaluation['delta'])
        else:
            structural = World.check_structure(route)
            self.ledger.bump('route_3d_checks')
            if structural:
                self.ledger.bump('rejected_3d')
                return None
            violations = self.raw_world().check_route(route, check_self=True)
            if violations:
                self.ledger.bump('rejected_3d')
                return None
            self.ledger.bump('valid_candidates')
            delta = None
        return PlanCandidate(
            route=route, layer=int(route['target_layer']),
            z_mm=float(route['target_z_mm']), kind=option['kind'],
            family=str(body_record.get('family') or ''),
            lead_s=lead_s, lead_t=lead_t,
            xy_crossings=int(body_record.get('crossings') or 0),
            delta=delta,
            length_mm=float(route.get('length_mm') or 0.0))

    def plan_best(self, rid, cfg=None, mode='clean', row_override=None):
        """Best exact candidate of one route, or ``None``."""
        candidates = self.plan_candidates(rid, cfg=cfg, mode=mode,
                                          row_override=row_override)
        return candidates[0] if candidates else None

    def plan_forced(self, rid, layer, z_mm, cfg=None, row_override=None,
                    mode='transaction'):
        """Exact candidates of one route at a *forced* physical height."""
        base = dict(PLAN_CFG, **(cfg or {}))
        option = dict(kind='migrate', layer=int(layer), z=float(z_mm), load=0,
                      priority=0)
        row = dict(row_override) if row_override is not None else self.state.row(rid)
        if abs(float(z_mm) - float(row['interface_z_mm'])) < 1e-12:
            option = dict(kind='direct', layer=int(layer), z=float(z_mm),
                          load=0, priority=0)
        candidates = []
        for lead_s, lead_t in self._lead_pairs(rid, option, base):
            try:
                task, _source, _target = LR.make_task_for_option(
                    self.state, rid, option, lead_s, lead_t)
            except (RB.BuilderError, ValueError):
                self.ledger.bump('no_candidate')
                continue
            bodies = LR.xy_candidates(self.state, rid, task, int(layer),
                                      float(z_mm), base)
            self.ledger.bump('d56_candidate_evals', int(base.get('d56_top', 16)))
            self.ledger.bump('xy_candidates_generated', len(bodies))
            for body_record in bodies[:int(base.get('max_return', 4))]:
                try:
                    route = LR.build_route_candidate(
                        self.state, rid, option, lead_s, lead_t,
                        body_record['body'])
                except (RB.BuilderError, ValueError):
                    self.ledger.bump('rejected_3d')
                    continue
                candidate = self._check_candidate(
                    rid, route, option, body_record, lead_s, lead_t,
                    mode=mode)
                if candidate is not None:
                    candidates.append(candidate)
        candidates.sort(key=lambda item: item.score)
        return candidates

    # -------------------------------------------------------- single replace
    def replace_one(self, rid, route, row=None, note=''):
        """Commit one route with the existing (exact) RouteWorld transaction."""
        self.ledger.bump('transactions')
        record = self.state.commit(int(rid), route, new_row=row, note=note)
        self.ledger.bump('route_3d_checks')
        self.ledger.bump('accepted_transactions')
        self.ledger.bump('accepted_changes')
        self.ledger.bump('gain', max(0, -int(record['delta'])))
        self.accepted += 1
        return record

    # ------------------------------------------------------------ transaction
    def transaction(self, rids, note='', min_gain=1, verify=True):
        return Transaction(self, rids, note=note, min_gain=min_gain,
                           verify=verify)

    def maybe_rebuild_world(self, force=False):
        """Rebuild the incremental world periodically to free stale entries."""
        self._transactions_since_rebuild += 1
        if force or self._transactions_since_rebuild >= WORLD_REBUILD_EVERY:
            self.state.world_cache = {}
            self.raw_world()
            self._transactions_since_rebuild = 0
            return True
        return False

    def validate_geometry(self):
        """Full true-3D rebuild + per-route check of the current state."""
        return self.state.validate_all()


class Transaction:
    """All-or-nothing joint re-routing of a set of routes.

    Usage::

        with JointWorld(...).transaction(rids) as tx:
            tx.rip_all()
            for rid in order:
                cands = tx.plan(rid, mode='transaction')
                if not cands:
                    tx.abort('no_candidate_for_%d' % rid)   # rollback
                    break
                tx.place(rid, cands[0])
            result = tx.finish(min_gain=1)
            if not result['accepted']:
                ...  # state unchanged

    ``rip_all`` / ``plan`` / ``place`` / ``finish`` / ``abort`` may also be
    called directly; ``finish``/``abort`` always leave a consistent state.
    """

    def __init__(self, joint, rids, note='', min_gain=1, verify=True):
        self.jw = joint
        self.state = joint.state
        self.rids = sorted({int(rid) for rid in rids})
        self.note = str(note)
        self.min_gain = int(min_gain)
        self.verify = bool(verify)
        self.saved_routes = {rid: copy.deepcopy(self.state.routes[rid])
                             for rid in self.rids}
        self.saved_rows = {rid: dict(self.state.rows[rid]) for rid in self.rids}
        self.old_groups = {rid: dict(self.state._route_groups.get(rid) or {})
                           for rid in self.rids}
        self.old_total = int(self.state.total)
        self.old_pairs = int(self.state.pairs)
        self.old_history_length = len(self.state.history)
        self.placed = {}
        self.new_rows = {}
        self.reasons = Counter()
        self.started = time.time()
        self._open = True
        self._ripped = False
        self.transaction_id = len(joint.transaction_history)
        joint.ledger.bump('transactions')

    # -- open / close ------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None and self._open:
            self.abort('exception:%s' % exc_type.__name__)
        return False

    # -- steps -------------------------------------------------------------
    def rip_all(self):
        if self._ripped:
            return
        for rid in self.rids:
            self.jw._world_drop(rid)
            self.jw._light_rip(rid)
        affected = set()
        for rid in self.rids:
            affected.update(self.old_groups[rid])
        self.jw._invalidate_height_caches(affected)
        self._ripped = True

    def rip(self, rid):
        rid = int(rid)
        if rid not in self.rids:
            raise RuntimeError('route %d not in transaction' % rid)
        if not self._ripped:
            self.rip_all()
        else:
            self.jw._world_drop(rid)
            self.jw._light_rip(rid)
            self.jw._invalidate_height_caches(self.old_groups.get(rid, {}))

    # -- planning ----------------------------------------------------------
    def plan(self, rid, cfg=None, forced=None):
        """Plan one (ripped) route inside this transaction.

        ``forced`` may be ``None`` (free target-height choice) or
        ``(layer_id, z_mm)`` to force the physical height.
        Returns the candidate list (best first).  They are **not** placed.
        """
        rid = int(rid)
        if forced is not None:
            return self.jw.plan_forced(rid, forced[0], forced[1], cfg=cfg,
                                       mode='transaction')
        return self.jw.plan_candidates(rid, cfg=cfg, mode='transaction')

    def place(self, rid, candidate):
        """Place one planned candidate into the open transaction state."""
        rid = int(rid)
        route = candidate.route if isinstance(candidate, PlanCandidate) else candidate
        row = self.state.row(rid)
        new_row = RB.row_for_target(row, int(route['target_layer']),
                                    float(route['target_z_mm']))
        self.jw._light_place(rid, route, new_row)
        self.jw._world_add(rid, self.state.routes[rid])
        self.placed[rid] = self.state.routes[rid]
        self.new_rows[rid] = new_row
        self.jw._invalidate_height_caches(list(WA.route_flat_groups(route)))
        return self.placed[rid]

    # -- exact crossing delta ----------------------------------------------
    def affected_heights(self):
        affected = set()
        for rid in self.rids:
            affected.update(self.old_groups.get(rid, {}))
            affected.update(WA.route_flat_groups(self.state.routes[rid]))
        return sorted(affected)

    def crossing_delta(self):
        affected = self.affected_heights()
        before = {z: tuple(self.state.plane_counts.get(z, (0, 0)))
                  for z in affected}
        # also include heights that may have been emptied by the rip
        for rid in self.rids:
            for z in self.old_groups.get(rid, {}):
                before.setdefault(z, tuple(self.state.plane_counts.get(z, (0, 0))))
        old_total = self.old_total
        new_total = recount_subset(self.state, affected)
        per_plane = {}
        for z in sorted(set(before) | set(affected)):
            per_plane[z] = dict(old=int(before.get(z, (0, 0))[0]),
                                new=int(self.state.plane_counts.get(z, (0, 0))[0]))
        return int(new_total - old_total), old_total, int(new_total), per_plane

    # -- finish ------------------------------------------------------------
    def _verify_placed(self):
        """Verify every placed route against the transaction world (self excluded)."""
        world = self.jw.raw_world()
        violations = []
        for rid, route in sorted(self.placed.items()):
            world.ignore_route(rid)
            try:
                found = World.check_structure(route)
                if not found:
                    found = world.check_route(route, check_self=True)
            finally:
                world.restore_route(rid)
            self.jw.ledger.bump('route_3d_checks')
            if found:
                violations.append(dict(route_id=int(rid),
                                       kinds=[v.get('kind') for v in found[:4]]))
        return violations

    def finish(self):
        """Exact crossing recount + all-or-nothing acceptance."""
        if not self._open:
            raise RuntimeError('transaction already closed')
        delta, old_total, new_total, per_plane = self.crossing_delta()
        accepted = (len(self.placed) == len(self.rids) and
                    (-int(delta)) >= self.min_gain)
        if accepted and self.verify:
            violations = self._verify_placed()
            if violations:
                accepted = False
                self.reasons['final_3d_violation'] += len(violations)
                self.jw.ledger.bump('rejected_3d', len(violations))
        if accepted:
            self._commit(delta, old_total, new_total, per_plane)
        else:
            if len(self.placed) != len(self.rids):
                self.reasons['incomplete_set'] += 1
            self._rollback(per_plane)
        self._open = False
        return dict(accepted=bool(accepted),
                    transaction_id=int(self.transaction_id),
                    routes=list(self.rids),
                    placed=len(self.placed),
                    old_total=int(old_total),
                    total=int(self.state.total),
                    delta=int(self.state.total - old_total),
                    gain=int(old_total - self.state.total),
                    per_plane={str(z): value for z, value in per_plane.items()},
                    reasons=dict(self.reasons),
                    note=self.note,
                    seconds=round(time.time() - self.started, 3))

    def abort(self, reason='aborted'):
        if not self._open:
            return None
        self.reasons[str(reason)] += 1
        per_plane = {z: dict(old=0, new=0) for z in self.affected_heights()}
        self._rollback(per_plane)
        self._open = False
        return dict(accepted=False, routes=list(self.rids),
                    placed=len(self.placed), reason=str(reason),
                    total=int(self.state.total), seconds=round(
                        time.time() - self.started, 3))

    # -- internals ---------------------------------------------------------
    def _commit(self, delta, old_total, new_total, per_plane):
        self.jw.ledger.bump('accepted_transactions')
        self.jw.ledger.bump('accepted_changes', len(self.placed))
        self.jw.ledger.bump('gain', max(0, -int(delta)))
        self.jw.accepted += 1
        self.jw.maybe_rebuild_world()
        record = dict(kind='g4_transaction', routes=sorted(self.placed),
                      old_total=int(old_total), total=int(new_total),
                      delta=int(delta), note=self.note,
                      new_rows={str(k): v for k, v in self.new_rows.items()},
                      seconds=round(time.time() - self.started, 3))
        self.state.history.append(record)
        self.jw.transaction_history.append(dict(
            record, accepted=True, placed=len(self.placed),
            reasons=dict(self.reasons),
            per_plane={str(z): v for z, v in per_plane.items()}))

    def _rollback(self, per_plane):
        # collect every height that currently references one of the routes
        # (the transaction geometry may sit on heights absent from old_groups)
        affected = set(per_plane)
        for rid in self.rids:
            affected.update(self.old_groups.get(rid, {}))
            for z_key, table in self.state.plane_prims.items():
                if rid in table:
                    affected.add(z_key)
            affected.update(WA.route_flat_groups(self.saved_routes[rid]))
        for rid in self.rids:
            self.jw._world_drop(rid)
            self.jw._light_rip(rid)
            self.jw._light_place(rid, self.saved_routes[rid],
                                 self.saved_rows[rid])
            self.jw._world_add(rid, self.saved_routes[rid])
        recount_subset(self.state, affected)
        # belt-and-braces: any orphan table entry must be gone now
        for rid in self.rids:
            for z_key, table in self.state.plane_prims.items():
                assert rid not in table or z_key in \
                    self.state._route_groups.get(rid, {}), \
                    'orphan plane entry %s for route %s' % (z_key, rid)
        self.jw.ledger.bump('rolled_back')
        self.jw.rollbacks += 1
        self.jw._invalidate_height_caches(affected)
        del self.state.history[self.old_history_length:]
        self.jw.transaction_history.append(dict(
            transaction_id=int(self.transaction_id), routes=list(self.rids),
            accepted=False, placed=len(self.placed), reasons=dict(self.reasons),
            note=self.note, seconds=round(time.time() - self.started, 3)))
