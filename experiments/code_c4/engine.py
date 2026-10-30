# -*- coding: utf-8 -*-
"""C4 exact-increment crossing engine and 13-layer collision world.

The engine pre-computes every 2D intersection between the 1024 fixed 2D chains
(91,536 events for the frozen connection table).  A route's height profile is a
list ``(s0, s1, kind, z)`` along its chain, where transitions consume their XY
**footprint** (not their 3D arc length).  A crossing event counts only when both
sides are flat at the same physical z, which makes the global unique-crossing
count exactly

    sum over physical heights h of |{ unordered route pairs crossing at h }|

identical to the E1 ``core.audit`` convention (verified 0-difference on legal
layouts; illegal layouts are rejected by the legality checks before being
scored).
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.c4 import layers as LY
from four_side_1024.c4 import orbits as O


# ---------------------------------------------------------------------------
# height profile along the fixed 2D chain
# ---------------------------------------------------------------------------
def route_geom(record):
    out = []
    s = 0.0
    for part in record.get('parts') or []:
        if part['kind'] == 'flat':
            span = float(part['length_mm'])
            out.append((s, s + span, 'flat', round(float(part['z_mm']), 6)))
        else:
            span = float(part.get('footprint_mm') or 0.0)
            if span <= 0.0:
                dz = abs(float(part['z1']) - float(part['z0']))
                span = float(LY.transition_geometry(dz)['footprint_mm'])
            out.append((s, s + span, 'transition', None))
        s += span
    return out


def geom_length(geom):
    return geom[-1][1] if geom else 0.0


def geom_z_at(geom, s):
    for s0, s1, kind, z in geom:
        if s0 - 1e-9 <= s <= s1 + 1e-9:
            return z if kind == 'flat' else None
    return None


def orbit_geom(ctx, orbit, layer, a_in, a_out):
    """Height profile of every member of an orbit for one candidate window."""
    target_z = LY.layer_z(layer)
    base_z = float(ctx.base_z(orbit['rep']))
    footprint = float(LY.transition_geometry(target_z - base_z)['footprint_mm'])
    total = ctx.total(orbit['rep'])
    windows = O.member_windows(orbit, a_in, a_out)
    geoms = {}
    for rid in orbit['ids']:
        head, tail = windows[rid]
        fall_start = total - tail - footprint
        if head + footprint > fall_start - 5.0 or tail < 1.2:
            return None
        geom = [(0.0, head, 'flat', round(base_z, 6)),
                (head, head + footprint, 'transition', None),
                (head + footprint, fall_start, 'flat', round(target_z, 6)),
                (fall_start, fall_start + footprint, 'transition', None),
                (fall_start + footprint, total, 'flat', round(base_z, 6))]
        geoms[rid] = geom
    return geoms


def flat_geom(ctx, rid):
    record = ctx.flat(rid)
    return route_geom(record)


# ---------------------------------------------------------------------------
# collision world with the 13-layer stack
# ---------------------------------------------------------------------------
class StackC4:
    def __init__(self, max_layer):
        self.max_layer = int(max_layer)
        self.rows = {'z1': LY.Z1, 'z2': LY.Z2}

    def z_for_layer(self, layer_id, row=None):
        layer_id = int(layer_id)
        if layer_id == 1:
            if row is None:
                raise ValueError('interface layer needs row')
            return self.rows[row]
        return float(LY.HEIGHTS[layer_id])

    def physical_planes(self):
        planes = [(1, 'z1', LY.Z1), (1, 'z2', LY.Z2)]
        planes += [(i, None, LY.HEIGHTS[i])
                   for i in range(2, self.max_layer + 1)]
        return planes


def make_world(records, max_layer):
    from four_side_1024.l3d.world import World
    world = World(StackC4(max_layer), clearance=C.CLEARANCE)
    for record in records:
        world.add_route(record)
    return world


# ---------------------------------------------------------------------------
# event table
# ---------------------------------------------------------------------------
class C4Engine:
    """All-pairs crossing event table for the frozen 1024 chains."""

    def __init__(self, ctx, cache_dir=None, log=print):
        self.ctx = ctx
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.events = []
        self.by_rid = defaultdict(list)
        cache = (self.cache_dir / 'c4_events.pkl') if self.cache_dir else None
        if cache is not None and cache.exists():
            with cache.open('rb') as handle:
                payload = pickle.load(handle)
            self.events = payload['events']
            self.by_rid = payload['by_rid']
            log(f'[c4-engine] loaded {len(self.events)} cached events')
        else:
            self._build(log)
            if cache is not None:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with cache.open('wb') as handle:
                    pickle.dump(dict(events=self.events,
                                     by_rid=dict(self.by_rid)), handle)
                log(f'[c4-engine] cached {len(self.events)} events')

    def _build(self, log):
        import time
        from four_side_1024.fslw import validate_fslw as V
        started = time.perf_counter()
        rids = sorted(int(record['route_id']) for record in self.ctx.records_base)
        entries = [dict(kind='movable', rid=rid,
                        prep=V.prepare_route(self.ctx.chain(rid), rid))
                   for rid in rids]
        pairs = V._candidate_pairs([entry['prep'] for entry in entries],
                                   C.CLEARANCE + 2.0 * V.SAGITTA)
        log(f'[c4-engine] entries={len(entries)} broad_pairs={len(pairs)}')
        events = []
        for index_a, index_b in pairs:
            first, second = entries[index_a], entries[index_b]
            result = V.evaluate_pair(first['prep'], second['prep'],
                                     C.CLEARANCE, V.SAGITTA, 'strict')
            if result is None or not result['crossings'] or not result['valid']:
                continue
            for crossing in result['crossings']:
                index = len(events)
                events.append(dict(a=first['rid'], b=second['rid'],
                                   s_a=float(crossing['sa']),
                                   s_b=float(crossing['sb']),
                                   x=float(crossing['point'][0]),
                                   y=float(crossing['point'][1])))
                self.by_rid[first['rid']].append(index)
                self.by_rid[second['rid']].append(index)
        self.events = events
        log(f'[c4-engine] events={len(events)} build={time.perf_counter()-started:.1f}s')

    # -- scoring ---------------------------------------------------------
    def audit(self, geoms):
        """Exact unique-pair count (E1 convention) + per-height statistics."""
        pairs_at = defaultdict(set)
        events = 0
        for event in self.events:
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            events += 1
            pairs_at[round(za, 6)].add((min(event['a'], event['b']),
                                        max(event['a'], event['b'])))
        per_height = {z: len(pairs) for z, pairs in pairs_at.items()}
        return dict(unique_pairs=sum(per_height.values()),
                    events=events, per_height=per_height)

    def contribution(self, geoms, rid):
        """(pairs, events) of one route in a complete layout."""
        rid = int(rid)
        pairs = set()
        events = 0
        seen = set()
        for index in self.by_rid.get(rid, ()):
            if index in seen:
                continue
            seen.add(index)
            event = self.events[index]
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            other = event['b'] if event['a'] == rid else event['a']
            pairs.add((min(rid, other), max(rid, other)))
            events += 1
        return len(pairs), events

    def orbit_delta(self, geoms, orbit, new_geoms):
        """Exact change of the global unique-pair count for one orbit move."""
        affected = set()
        for rid in orbit['ids']:
            affected.update(self.by_rid.get(rid, ()))
        before = defaultdict(set)
        after = defaultdict(set)
        old_geoms = {rid: geoms[rid] for rid in orbit['ids']}
        for index in affected:
            event = self.events[index]
            a, b = event['a'], event['b']
            pair = (min(a, b), max(a, b))
            za = geom_z_at(old_geoms.get(a, geoms[a]), event['s_a'])
            zb = geom_z_at(old_geoms.get(b, geoms[b]), event['s_b'])
            if za is not None and zb is not None and za == zb:
                before[pair].add(round(za, 6))
            na = new_geoms.get(a) or old_geoms.get(a) or geoms[a]
            nb = new_geoms.get(b) or old_geoms.get(b) or geoms[b]
            za2 = geom_z_at(na, event['s_a'])
            zb2 = geom_z_at(nb, event['s_b'])
            if za2 is not None and zb2 is not None and za2 == zb2:
                after[pair].add(round(za2, 6))
        delta = 0
        for pair in set(before) | set(after):
            delta += len(after.get(pair, ())) - len(before.get(pair, ()))
        return delta


# ---------------------------------------------------------------------------
# legality
# ---------------------------------------------------------------------------
def orbit_legality(ctx, world, orbit, routes, check_mutual=True):
    """World legality of a candidate orbit (returns list of problems)."""
    from four_side_1024.l3d.world import World
    problems = []
    for route in routes:
        if World.check_structure(route):
            problems.append(dict(route_id=int(route['route_id']),
                                 kind='structure'))
            return problems
    for route in routes:
        violations = world.check_route(route)
        if violations:
            problems.append(dict(route_id=int(route['route_id']),
                                 kind='world',
                                 violations=violations[:2]))
            return problems
    if check_mutual and len(routes) > 1:
        for index in range(len(routes)):
            for other in range(index + 1, len(routes)):
                bad = C.pairwise_violations(world, routes[index], routes[other])
                if bad:
                    problems.append(dict(route_id=int(routes[index]['route_id']),
                                         other=int(routes[other]['route_id']),
                                         kind='mutual'))
                    return problems
    return problems
