# -*- coding: utf-8 -*-
"""Conflict graph, 3-D height-blocker graph and neighbourhood selection for G4.

This module is the *search-space* layer of G4c / G4d.  It builds, from the real
``world_adapter.RouteWorld`` state only:

* :class:`ConflictGraph` -- the exact same-height crossing conflict graph
  (built from the real ``joint_world.crossing_events`` of the frozen strict-D56
  audit), with per-route crossing counts, adjacency and connected components.
  Every crossing pair has at most one event in the G3 start solution, so the
  graph is simple and 1253 edges / 588 nodes / 38 height-pure components.

* the **3-D height-blocker graph**: for a route and a target physical height,
  which routes *block* it there.  Two classes are distinguished exactly like
  the SPEC requires:
    - *body occupants*     -- routes whose flat body sits on the target height
                              and whose body bbox overlaps the route corridor;
    - *transition blockers* -- routes whose spherical/parabolic S-curve passes
                              within the ``obstacles_for_z`` 3-D window of the
                              target height inside the route corridor.

* :func:`rank_target_heights` -- cheap ranking of the 19 body heights for one
  route, combining the O(1) XY crossing pre-rank with the blocker counts and a
  large penalty for blockers that may not be moved (frozen manual-U routes).

* :func:`select_neighborhood` / :func:`component_neighborhoods` -- BFS
  neighbourhood expansion over the conflict graph (8/16/32/64/96) and the
  height-pure component decomposition.

Nothing here mutates the state or the shared engine.
"""
from __future__ import annotations

import collections
import math
import time

from .. import route_builder as RB
from .. import world_adapter as WA
from . import joint_world as JW

#: body plane ids (19 physical body heights, Z1/Z2 interfaces excluded)
BODY_LAYER_IDS = tuple(int(pid) for pid in RB.BODY_PLANE_IDS)
BODY_Z = {int(pid): float(RB.PLANE_Z[int(pid)]) for pid in BODY_LAYER_IDS}
_Z_TO_LAYER = {round(float(z), 9): int(pid) for pid, z in BODY_Z.items()}

#: 3-D obstacle window used by ``RouteWorld.obstacles_for_z`` (mm)
OBSTACLE_WINDOW_MM = float(WA.OBSTACLE_WINDOW_MM)


def log_noop(*_args, **_kwargs):
    return None


# ---------------------------------------------------------------------------
# small geometry helpers
# ---------------------------------------------------------------------------
def route_body_primitives(route):
    """Flat primitives of the route *body* (leads excluded, traversal order)."""
    prims = []
    for index in RB.body_part_indices(route):
        part = route['parts'][index]
        for prim in part.get('primitives') or ():
            prims.append(prim)
    return prims


def prim_points(prim):
    """Extreme XY points of one planar primitive (line/arc)."""
    points = []
    for key in ('p0', 'p1', 'center'):
        value = prim.get(key)
        if value is not None:
            points.append((float(value[0]), float(value[1])))
    return points


def bbox_of_prims(prims):
    points = []
    for prim in prims:
        points.extend(prim_points(prim))
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def expand_bbox(box, margin):
    if box is None:
        return None
    margin = float(margin)
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def bbox_overlap(a, b, margin=0.0):
    if a is None or b is None:
        return False
    margin = float(margin)
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or
                a[3] + margin < b[1] or b[3] + margin < a[1])


def point_in_bbox(x, y, box):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


# ---------------------------------------------------------------------------
# exact crossing conflict graph
# ---------------------------------------------------------------------------
class ConflictGraph:
    """Exact same-height crossing conflict graph of one ``RouteWorld``."""

    __slots__ = ('edges', 'per_route', 'adj', 'built_at', 'refreshed',
                 'build_seconds')

    def __init__(self, edges, per_route, built_at=None):
        self.edges = collections.Counter(
            {tuple(sorted((int(a), int(b)))): int(w) for (a, b), w in edges.items()})
        self.per_route = collections.Counter(
            {int(rid): int(w) for rid, w in per_route.items()})
        self.adj = collections.defaultdict(dict)
        for (a, b), weight in self.edges.items():
            self.adj[a][b] = weight
            self.adj[b][a] = weight
        self.built_at = float(built_at if built_at is not None else time.time())
        self.refreshed = 0
        self.build_seconds = 0.0

    # -- summary -----------------------------------------------------------
    @property
    def total_events(self):
        return int(sum(self.edges.values()))

    @property
    def node_count(self):
        return len(self.per_route)

    @property
    def edge_count(self):
        return len(self.edges)

    def neighbors(self, rid):
        return self.adj.get(int(rid), {})

    def crossing_count(self, rid):
        return int(self.per_route.get(int(rid), 0))

    def top_routes(self, limit=64, allowed=None, min_crossings=1):
        allowed = None if allowed is None else {int(r) for r in allowed}
        rows = [(int(rid), int(count)) for rid, count in self.per_route.items()
                if count >= int(min_crossings)]
        if allowed is not None:
            rows = [row for row in rows if row[0] in allowed]
        rows.sort(key=lambda row: (-row[1], row[0]))
        return rows[:int(limit)]

    def edges_in(self, allowed=None):
        allowed = None if allowed is None else {int(r) for r in allowed}
        out = []
        for (a, b), weight in self.edges.items():
            if allowed is not None and (a not in allowed or b not in allowed):
                continue
            out.append((a, b, int(weight)))
        out.sort(key=lambda row: (-row[2], row[0], row[1]))
        return out

    # -- connectivity ------------------------------------------------------
    def components(self, allowed=None, min_size=2):
        """Connected components ``[[rid, ...], ...]`` largest crossing volume first."""
        allowed = None if allowed is None else {int(r) for r in allowed}
        nodes = [int(r) for r in self.per_route] if allowed is None \
            else [int(r) for r in self.per_route if int(r) in allowed]
        seen = set()
        out = []
        for node in nodes:
            if node in seen:
                continue
            stack = [node]
            seen.add(node)
            comp = []
            while stack:
                current = stack.pop()
                comp.append(current)
                for other in self.adj.get(current, ()):
                    if other in seen:
                        continue
                    if allowed is not None and other not in allowed:
                        continue
                    seen.add(other)
                    stack.append(other)
            if len(comp) >= int(min_size):
                out.append(sorted(comp))
        out.sort(key=lambda comp: (-self._comp_events(comp), len(comp), comp[0]))
        return out

    def _comp_events(self, comp):
        members = set(int(rid) for rid in comp)
        return sum(int(w) for (a, b), w in self.edges.items()
                   if a in members and b in members)

    def component_events(self, comp):
        return self._comp_events(comp)

    def component_of(self, rid):
        target = int(rid)
        seen = {target}
        stack = [target]
        while stack:
            current = stack.pop()
            for other in self.adj.get(current, ()):
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        return sorted(seen)

    def summary(self):
        comps = self.components(min_size=1)
        return dict(edges=self.edge_count, nodes=self.node_count,
                    events=self.total_events, components=len(comps),
                    component_sizes=[len(c) for c in comps[:40]],
                    max_degree=max((len(v) for v in self.adj.values()), default=0))


def build_conflict_graph(state, cache=None, per_route=None):
    """Build the exact conflict graph (and optionally the per-route counts)."""
    started = time.time()
    events = JW.crossing_events(state, cache=cache)
    edges = collections.Counter()
    counts = collections.Counter()
    for event in events:
        a = int(event['route_a'])
        b = int(event['route_b'])
        if a == b:
            continue
        edges[(min(a, b), max(a, b))] += 1
        counts[a] += 1
        counts[b] += 1
    if per_route is not None:
        counts = collections.Counter(
            {int(rid): int(value) for rid, value in per_route.items()})
    graph = ConflictGraph(edges, counts)
    graph.build_seconds = round(time.time() - started, 3)
    return graph


# ---------------------------------------------------------------------------
# 3-D height blocker graph
# ---------------------------------------------------------------------------
class BlockIndex:
    """Cheap per-state index used by the blocker queries.

    * ``body_bbox``  : ``{rid: (x0, y0, x1, y1)}`` of the route *body*
    * ``plane_bbox`` : ``{z_key: {rid: bbox}}`` of the body occupants per height
    """

    __slots__ = ('body_bbox', 'plane_bbox', 'built_at')

    def __init__(self, state):
        self.body_bbox = {}
        self.plane_bbox = {}
        for rid, route in state.routes.items():
            box = bbox_of_prims(route_body_primitives(route))
            if box is None:
                continue
            self.body_bbox[int(rid)] = box
        for z_key, table in state.plane_prims.items():
            boxes = {}
            for rid in table:
                box = self.body_bbox.get(int(rid))
                if box is not None:
                    boxes[int(rid)] = box
            self.plane_bbox[z_key] = boxes
        self.built_at = time.time()

    def stale(self, state, max_age=120.0):
        """Cheap staleness test: route bodies changed vs index (count check)."""
        if time.time() - self.built_at > float(max_age):
            return True
        return len(self.body_bbox) != len(state.routes)


def build_block_index(state):
    return BlockIndex(state)


def height_blockers(state, rid, z_mm, margin=0.6, index=None, frozen=None,
                    cap=24):
    """Routes blocking ``rid`` at physical height ``z_mm``.

    Returns ``dict(body=[...], transition=[...], frozen=[...], cap_hit=bool)``
    where ``body`` are same-height body occupants whose bbox overlaps the
    route corridor and ``transition`` are routes whose S-curve passes inside
    the 3-D obstacle window at that height within the corridor.
    """
    rid = int(rid)
    z_key = WA.plane_key(z_mm)
    index = index if index is not None else build_block_index(state)
    box = index.body_bbox.get(rid)
    if box is None:
        box = bbox_of_prims(route_body_primitives(state.route(rid)))
    if box is None:
        return dict(body=[], transition=[], frozen=[], cap_hit=False)
    box = expand_bbox(box, float(margin))
    body = []
    for other, other_box in (index.plane_bbox.get(z_key) or {}).items():
        if int(other) == rid:
            continue
        if bbox_overlap(box, other_box):
            body.append(int(other))
    transition = []
    for sample in state.obstacles_for_z(z_mm):
        other = int(sample['route_id'])
        if other == rid:
            continue
        if point_in_bbox(float(sample['x']), float(sample['y']), box):
            if other not in transition:
                transition.append(other)
    frozen = set(int(r) for r in (frozen or ())) & (set(body) | set(transition))
    cap_hit = len(body) + len(transition) > int(cap)
    return dict(body=body[:int(cap)], transition=transition[:int(cap)],
                frozen=sorted(frozen), cap_hit=cap_hit)


def rank_heights_by_events(state, rid=None, exclude_current=True, body_heights=None):
    """Rank the 19 body heights by the **current crossing events** of the plane.

    This is the ordering that matters for forced height migration: the quiet
    planes of the current state (e.g. L12 with 9 events, L13 with 12) are the
    gold mines, whatever the route's current XY path looks like.  ``events`` is
    the exact ``state.plane_counts`` value, i.e. always up to date after every
    accepted transaction.
    """
    heights = body_heights if body_heights is not None else BODY_LAYER_IDS
    cur_z = None
    if rid is not None:
        cur_z = float(state.row(int(rid))['target_z_mm'])
    rows = []
    for layer_id in heights:
        layer_id = int(layer_id)
        z = float(BODY_Z[layer_id])
        if exclude_current and cur_z is not None and abs(z - cur_z) < 1e-9:
            continue
        z_key = WA.plane_key(z)
        events, pairs = state.plane_counts.get(z_key, (0, 0))
        load = len(state.plane_prims.get(z_key) or {})
        rows.append(dict(layer=layer_id, z=z, z_key=z_key,
                         events=int(events), pairs=int(pairs), load=int(load)))
    rows.sort(key=lambda row: (row['events'], row['load'],
                               abs(row['z'])))
    return rows


def rank_target_heights(state, rid, frozen=None, index=None, cfg=None,
                        body_heights=None, exclude_current=True):
    """Rank the body heights for one route (cheap: O(1) per height).

    Score = exact-ish XY crossing pre-rank of the *current* body primitives on
    the target plane + blocker costs (movable blockers are cheap, frozen ones
    expensive) + a small load term.  The score is only a heuristic; the exact
    acceptance test is always the joint transaction recount.
    """
    cfg = cfg or {}
    rid = int(rid)
    row = state.row(rid)
    cur_z = float(row['target_z_mm'])
    prims = route_body_primitives(state.route(rid))
    frozen = set(int(r) for r in (frozen or ()))
    index = index if index is not None else build_block_index(state)
    heights = body_heights if body_heights is not None else BODY_LAYER_IDS
    out = []
    for layer_id in heights:
        layer_id = int(layer_id)
        z = float(BODY_Z[layer_id])
        if exclude_current and abs(z - cur_z) < 1e-9:
            continue
        z_key = WA.plane_key(z)
        table = state.plane_prims.get(z_key) or {}
        load = len(table)
        if table and prims:
            est_xy = int(state.fast_crossings(z_key, prims, exclude_route=rid))
        else:
            est_xy = 0
        blockers = height_blockers(state, rid, z, index=index, frozen=frozen)
        n_movable = len(blockers['body']) + len(blockers['transition']) \
            - len(blockers['frozen'])
        score = (est_xy
                 + 0.25 * max(0, n_movable)
                 + 6.0 * len(blockers['frozen'])
                 + 0.02 * load)
        out.append(dict(layer=layer_id, z=z, z_key=z_key,
                        est_xy=int(est_xy), load=int(load),
                        n_body=len(blockers['body']),
                        n_transition=len(blockers['transition']),
                        n_movable=max(0, n_movable),
                        n_frozen=len(blockers['frozen']),
                        blockers=blockers, score=round(float(score), 4)))
    out.sort(key=lambda row: (row['score'], abs(row['z'] - cur_z), row['layer']))
    return out


# ---------------------------------------------------------------------------
# neighbourhood selection
# ---------------------------------------------------------------------------
def select_neighborhood(graph, seed_rids, size, rng=None, allowed=None,
                        min_crossings=1):
    """BFS expansion of ``seed_rids`` over the conflict graph up to ``size``.

    Neighbours are visited highest crossing weight first so the assembled
    neighbourhood contains the most conflicting routes first.
    """
    size = max(1, int(size))
    allowed = None if allowed is None else {int(r) for r in allowed}
    rng = rng or __import__('random').Random(0)
    picked = []
    seen = set()
    frontier = collections.deque()
    for seed in seed_rids:
        seed = int(seed)
        if allowed is not None and seed not in allowed:
            continue
        frontier.append(seed)
    while frontier and len(picked) < size:
        rid = frontier.popleft()
        if rid in seen:
            continue
        seen.add(rid)
        if allowed is not None and rid not in allowed:
            continue
        picked.append(rid)
        if len(picked) >= size:
            break
        neighbours = [(int(other), int(weight))
                      for other, weight in graph.adj.get(rid, {}).items()
                      if int(other) not in seen and
                      (allowed is None or int(other) in allowed)]
        neighbours.sort(key=lambda row: (-row[1], row[0]))
        for other, _weight in neighbours:
            frontier.append(other)
    if len(picked) < size:
        # fill up with the highest-crossing allowed routes that are not yet in
        for rid, _count in graph.top_routes(limit=size * 8, allowed=allowed,
                                            min_crossings=min_crossings):
            if rid in seen:
                continue
            seen.add(rid)
            picked.append(int(rid))
            if len(picked) >= size:
                break
    return picked


def component_neighborhoods(graph, allowed=None, min_size=4, max_size=96):
    """Height-pure conflict components usable as ruin-and-recreate units."""
    out = []
    for comp in graph.components(allowed=allowed, min_size=int(min_size)):
        if len(comp) > int(max_size):
            continue
        out.append(dict(routes=comp, size=len(comp),
                        events=int(graph.component_events(comp))))
    out.sort(key=lambda row: (-row['events'], row['size'], row['routes'][0]))
    return out


def merged_component_neighborhood(graph, comps, count, allowed=None, size=96):
    """Merge ``count`` components (largest crossing volume first) into one unit."""
    members = []
    for comp in comps[:int(count)]:
        for rid in comp['routes']:
            if allowed is not None and int(rid) not in allowed:
                continue
            if int(rid) not in members:
                members.append(int(rid))
        if len(members) >= int(size):
            break
    return members[:int(size)]


def neighbourhood_summary(graph, block_index=None, state=None, frozen=None,
                          limit=8):
    """Diagnostic summary used by the arm runners / strategy stats."""
    summary = graph.summary()
    comps = graph.components(min_size=2)
    summary['components_detail'] = [
        dict(size=len(comp), events=int(graph.component_events(comp)),
             routes=comp[:8]) for comp in comps[:int(limit)]]
    if state is not None:
        frozen = set(int(r) for r in (frozen or ()))
        planes = {}
        for z_key, table in state.plane_prims.items():
            planes[str(z_key)] = dict(routes=len(table),
                                      frozen=sum(1 for r in table if int(r) in frozen))
        summary['planes'] = planes
    return summary
