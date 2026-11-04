# -*- coding: utf-8 -*-
"""Crossing statistics + fast candidate evaluation for Native 3D routes.

Exact counting follows the frozen definition used to accept E5: every flat part
is grouped by its **physical** ``z`` and each height is audited with the
independent ``fslw`` strict route-pair audit (see ``nonc4.crossings``).  This is
already multi-height aware: a route with several flats on different z planes
contributes each flat to its own plane.

The fast path uses the production ``D56Index`` (strict policy) per plane, which
counts the genuine transverse crossing points of a candidate flat chain against
the other routes of that plane and rejects spacing / overlap / tangency.
"""
from __future__ import annotations

import copy
import time
from collections import Counter, OrderedDict
from pathlib import Path

from ...d56.index import D56Index, prepare
from ...fslw import config as FS
from .. import common as C
from . import common as N


# ------------------------------------------------------------------ helpers
def route_flat_groups(route):
    """``{z: [[prims per flat part], ...]}`` of one route (flat parts only)."""
    groups = OrderedDict()
    for part in route.get('parts') or ():
        if part.get('kind') != 'flat':
            continue
        prims = [dict(prim) for prim in (part.get('primitives') or ())]
        if not prims:
            continue
        key = round(float(part['z_mm']), 9)
        groups.setdefault(key, []).append(prims)
    return groups


def _new_index():
    return D56Index(width=FS.WIDTH_MM, gap=FS.EDGE_GAP_MM,
                    sagitta=FS.SAGITTA_MM,
                    min_cross_angle_deg=FS.MIN_CROSS_ANGLE_DEG,
                    crossing_policy='strict')


# ------------------------------------------------------------------ exact cache
class CrossingCache:
    """Exact per-height crossing totals (fslw strict audit) with incremental update."""

    def __init__(self, routes, log=None):
        self.log = log or (lambda *_a, **_k: None)
        self.plane_routes = {}      # z -> {rid: [prims, ...] merged}
        self.route_planes = {}      # rid -> {z: [[prims], ...]}
        self.plane_counts = {}      # z -> (events, pairs)
        started = time.time()
        for route in routes:
            self.add_route(route, recount=False)
        for z_key in sorted(self.plane_routes):
            self._recount(z_key)
        if self.log:
            self.log('[cache] built %d routes, %d planes, total=%d (%.1fs)'
                     % (len(self.route_planes), len(self.plane_routes),
                        self.total(), time.time() - started))

    # -- structure ---------------------------------------------------------
    def add_route(self, route, recount=True):
        from ..nonc4 import crossings as X
        rid = int(route['route_id'])
        groups = route_flat_groups(route)
        self.route_planes[rid] = groups
        for z_key, chains in groups.items():
            merged = []
            for chain in chains:
                merged.extend(chain)
            self.plane_routes.setdefault(z_key, {})[rid] = merged
        if recount:
            for z_key in groups:
                self._recount(z_key)

    def remove_route(self, route_id):
        rid = int(route_id)
        groups = self.route_planes.pop(rid, {})
        for z_key in groups:
            self.plane_routes.get(z_key, {}).pop(rid, None)
            if not self.plane_routes.get(z_key):
                self.plane_routes.pop(z_key, None)
                self.plane_counts.pop(z_key, None)
        return groups

    def update_route(self, route, previous_groups=None):
        rid = int(route['route_id'])
        old_groups = previous_groups if previous_groups is not None \
            else self.route_planes.get(rid) or {}
        self.remove_route(rid)
        self.add_route(route, recount=False)
        new_groups = self.route_planes.get(rid) or {}
        affected = set(old_groups) | set(new_groups)
        for z_key in sorted(affected):
            self._recount(z_key)
        return affected

    # -- counting ----------------------------------------------------------
    def _recount(self, z_key):
        from ..nonc4 import crossings as X
        route_prims = self.plane_routes.get(z_key) or {}
        if not route_prims:
            self.plane_counts.pop(z_key, None)
            return (0, 0)
        result = X.audit_flat_group(route_prims)
        counts = (int(result.get('crossing_count') or 0),
                  int(result.get('crossing_pair_count') or 0))
        self.plane_counts[z_key] = counts
        return counts

    def total(self):
        return int(sum(value[0] for value in self.plane_counts.values()))

    def total_pairs(self):
        return int(sum(value[1] for value in self.plane_counts.values()))

    def summary(self):
        return dict(totals=dict(crossings=self.total(),
                                crossing_pairs=self.total_pairs()),
                    planes=[dict(z_mm=z, events=self.plane_counts[z][0],
                                 pairs=self.plane_counts[z][1],
                                 routes=len(self.plane_routes.get(z) or {}))
                            for z in sorted(self.plane_counts)])

    def per_route(self):
        from ..nonc4 import crossings as X
        counter = Counter()
        for z_key, route_prims in self.plane_routes.items():
            result = X.audit_flat_group(route_prims)
            for crossing in result.get('crossings') or ():
                counter[int(crossing['route_a'])] += 1
                counter[int(crossing['route_b'])] += 1
        return counter

    def crossing_events(self):
        from ..nonc4 import crossings as X
        events = []
        for z_key in sorted(self.plane_routes):
            result = X.audit_flat_group(self.plane_routes[z_key])
            for crossing in result.get('crossings') or ():
                events.append(dict(route_a=int(crossing['route_a']),
                                   route_b=int(crossing['route_b']),
                                   z_mm=float(z_key),
                                   x_mm=float(crossing['x']),
                                   y_mm=float(crossing['y']),
                                   angle_deg=float(crossing['angle_deg'])))
        return events


# ------------------------------------------------------------------ fast index
class PlaneIndexCache:
    """Per-plane strict D56 indices, optionally rebuilt without one route."""

    def __init__(self, plane_routes):
        # plane_routes: {z: {rid: [prims]}}
        self.plane_routes = plane_routes
        self.indices = {}
        self.excluded = {}

    def index_for(self, z_key, exclude_route=None):
        exclude_route = None if exclude_route is None else int(exclude_route)
        key = (round(float(z_key), 9), exclude_route)
        index = self.indices.get(key)
        if index is not None:
            return index
        index = _new_index()
        route_prims = self.plane_routes.get(round(float(z_key), 9)) or {}
        for rid, prims in route_prims.items():
            if exclude_route is not None and int(rid) == exclude_route:
                continue
            index.add(int(rid), prepare([dict(prim) for prim in prims]))
        self.indices[key] = index
        self.excluded[key] = exclude_route
        return index

    def crossings_of(self, z_key, chains, exclude_route=None):
        """``(events, pairs, ok, reasons)`` of flat chains against one plane."""
        if not chains:
            return 0, 0, True, []
        index = self.index_for(z_key, exclude_route)
        events = 0
        pairs = 0
        ok = True
        reasons = []
        for chain in chains:
            evaluation = index.evaluate(prepare([dict(prim) for prim in chain]))
            events += len(getattr(evaluation, 'crossings', ()) or ())
            if evaluation.valid:
                pairs += 1 if getattr(evaluation, 'crossings', None) else 0
            else:
                ok = False
                reasons.append(str(getattr(evaluation, 'reason', 'invalid')))
        return events, pairs, ok, reasons

    def invalidate(self, z_key=None):
        if z_key is None:
            self.indices.clear()
        else:
            key_z = round(float(z_key), 9)
            for key in [item for item in self.indices if item[0] == key_z]:
                self.indices.pop(key, None)


# ------------------------------------------------------------------ route set
class NativeRouteSet:
    """The 1024 routes with exact crossing cache + fast plane indices."""

    def __init__(self, routes, log=None):
        self.log = log or (lambda *_a, **_k: None)
        self.routes = {int(route['route_id']): copy.deepcopy(route)
                       for route in routes}
        self.cache = CrossingCache(list(self.routes.values()), log=self.log)
        self.plane_cache = PlaneIndexCache(self.cache.plane_routes)
        self.accepted_crossings = self.cache.total()

    # -- access ------------------------------------------------------------
    def route(self, route_id):
        return self.routes[int(route_id)]

    def total(self):
        return self.cache.total()

    def replace_route(self, route):
        rid = int(route['route_id'])
        previous = self.cache.route_planes.get(rid) or {}
        self.routes[rid] = copy.deepcopy(route)
        affected = self.cache.update_route(route, previous_groups=previous)
        for z_key in affected:
            self.plane_cache.invalidate(z_key)
        self.accepted_crossings = self.cache.total()
        return affected

    # -- fast candidate evaluation ----------------------------------------
    def evaluate_candidate(self, route_id, new_route):
        """Fast crossing delta / D56 validity of replacing one route."""
        rid = int(route_id)
        old_route = self.routes[rid]
        old_groups = route_flat_groups(old_route)
        new_groups = route_flat_groups(new_route)
        affected = sorted(set(old_groups) | set(new_groups))
        events_delta = 0
        problems = []
        per_plane = {}
        for z_key in affected:
            old_events, _old_pairs, _ok, _r = self.plane_cache.crossings_of(
                z_key, old_groups.get(z_key) or [], exclude_route=rid)
            new_events, _new_pairs, ok, reasons = self.plane_cache.crossings_of(
                z_key, new_groups.get(z_key) or [], exclude_route=rid)
            events_delta += new_events - old_events
            per_plane[round(z_key, 9)] = dict(old=old_events, new=new_events)
            if not ok:
                problems.append(dict(plane=round(z_key, 9), reasons=reasons[:4]))
        return dict(delta=events_delta, per_plane=per_plane,
                    d56_ok=not problems, problems=problems,
                    affected_z=sorted(affected))
