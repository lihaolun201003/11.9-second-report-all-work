# -*- coding: utf-8 -*-
"""E1-D validated greedy S-bend window refiner (library, no disk writes).

This is the exact algorithm that produced the E1-D D2 result
(BASE 6,078 -> 4,670 unique crossing pairs, violations 0).  It is generic:
give it any complete 1024-route layout and it will

1. audit the layout exactly (``core.audit``),
2. search the structurally valid S-bend ``(a_in, a_out)`` windows of every
   *movable* route on its **current** target layer against the current world
   (the route itself is temporarily removed, every other route fixed),
3. greedily replace windows: a replacement is accepted only when it is
   world-legal (``World.check_route``) **and** its exact incremental change of
   the full-layout unique crossing count is <= 0, its adjacent-related events
   do not increase and its crossing events do not increase (at least one strict
   improvement), and
4. return the updated records.

The incremental crossing delta is computed by ``LiftingEngine``: every flat
part of a lifted record is a sub-chain of the route's fixed 2D chain, so each
physical crossing event is a fixed 2D chain intersection whose height on both
routes is the same flat plane.  That makes the greedy exact (and ~100x cheaper
than a full ``core.audit`` per candidate).  The engine is validated against
``core.audit`` inside ``refine`` (``stats['engine_check']``).

Entry point
-----------
    from four_side_1024.e1 import refine as R
    result = R.refine(ctx, records)          # records: full routed record list
    result['records']    # full 1024-route list, same order/format as input
    result['changed']    # [{route_id, old:(a_in,a_out,layer),
                         #                  new:(a_in,a_out,layer), ...}]
    result['pass_stats'] # [{pass_index, accepted, seconds}, ...]
    result['stats']      # summary incl. before/after crossings + engine check

``movable_rids=None`` means: every Z1 C2-opposite route that is lifted
(``route_target_layer > 1``) in the given layout.  Pass an explicit list to
refine other routes (e.g. the Z2 routes a previous stage moved) - any record
whose flat parts are sub-chains of its fixed 2D chain is supported.
"""
from __future__ import annotations

import math
import time
from collections import Counter, defaultdict

from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.fslw import validate_fslw as V

PORT_MARGIN = 1.2
AREA_EPS = 1e-6


# ---------------------------------------------------------------------------
# geometry: height profile of a record along its fixed 2D chain
# ---------------------------------------------------------------------------
def route_geom(record):
    """[(s_start, s_end, kind, z)] along the fixed 2D chain.

    Flat parts consume ``length_mm`` of chain arclength; a frozen S transition
    consumes its XY footprint (the transition has no lateral offset, so its
    projection onto the chain is exactly that straight interval).
    """
    out = []
    s = 0.0
    for part in record.get('parts') or []:
        if part['kind'] == 'flat':
            span = float(part['length_mm'])
            out.append((s, s + span, 'flat', round(float(part['z_mm']), 6)))
        else:
            span = float(part.get('footprint_mm')
                         or part.get('length_mm') or 0.0)
            out.append((s, s + span, 'transition', None))
        s += span
    return out


def geom_z_at(geom, s):
    for s0, s1, kind, z in geom:
        if s0 - 1e-9 <= s <= s1 + 1e-9:
            return z if kind == 'flat' else None
    return None


def geom_length(geom):
    return geom[-1][1] if geom else 0.0


def chain_position(ctx, rid, x, y):
    """Exact (distance, kind, arclength-from-source) of (x, y) on the chain."""
    best = None
    offset = 0.0
    for prim in ctx.chain(rid):
        cx, cy = C.prim_closest_point(prim, x, y)
        distance = math.hypot(cx - x, cy - y)
        length = C.prim_len(prim)
        if best is None or distance < best[0]:
            if prim['kind'] == 'line':
                p0, p1 = prim['p0'], prim['p1']
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                den = dx * dx + dy * dy
                t = (0.0 if den <= 1e-18 else
                     max(0.0, min(1.0, ((cx - p0[0]) * dx
                                        + (cy - p0[1]) * dy) / den)))
            else:
                center = prim['center']
                start = float(prim['start_angle'])
                sweep = float(prim['sweep'])
                angle = math.atan2(cy - center[1], cx - center[0])
                if sweep >= 0.0:
                    delta = (angle - start) % (2.0 * math.pi)
                    if delta > sweep + 1e-9:
                        delta = 0.0 if delta <= sweep + math.pi else sweep
                    t = delta / sweep if abs(sweep) > 1e-15 else 0.0
                else:
                    delta = (start - angle) % (2.0 * math.pi)
                    if delta > -sweep + 1e-9:
                        delta = 0.0 if delta <= -sweep + math.pi else -sweep
                    t = delta / (-sweep) if abs(sweep) > 1e-15 else 0.0
                t = max(0.0, min(1.0, t))
            best = (distance, prim['kind'], offset + t * length)
        offset += length
    return best


# ---------------------------------------------------------------------------
# exact-increment crossing engine (movable routes only)
# ---------------------------------------------------------------------------
class LiftingEngine:
    """Exact crossing bookkeeping for routes whose S-bend windows may change.

    A movable route is modelled by its fixed 2D chain: its height at arclength
    ``s`` is read from its current record (base stub -> base row z, target
    layer travel -> layer z, transition -> None).  Every fixed route
    contributes its real flat parts with their real z.  Crossing events are the
    fixed 2D intersections; a crossing exists when both sides are flat at the
    same z, so all deltas of a candidate replacement are exactly computable.
    """

    def __init__(self, ctx, movable, fixed_records, policy='strict',
                 verbose=True):
        started = time.perf_counter()
        self.ctx = ctx
        self.movable = {int(rid) for rid in movable}
        entries = []
        for rid in sorted(self.movable):
            entries.append(dict(kind='movable', rid=rid,
                                prep=V.prepare_route(ctx.chain(rid), rid)))
        for record in fixed_records:
            rid = int(record['route_id'])
            if rid in self.movable:
                continue
            for index, part in enumerate(record.get('parts') or []):
                if part['kind'] != 'flat':
                    continue
                entries.append(dict(kind='fixed', rid=rid, index=index,
                                    z=round(float(part['z_mm']), 6),
                                    prep=V.prepare_route(part['primitives'],
                                                         rid)))
        pairs = V._candidate_pairs([entry['prep'] for entry in entries],
                                   C.CLEARANCE + 2.0 * V.SAGITTA)
        if verbose:
            print(f'  [lift-engine] entries={len(entries)} '
                  f'broad_pairs={len(pairs)} {time.perf_counter() - started:.2f}s',
                  flush=True)
        self.mm_events = []
        self.mf_events = []
        self.by_m = defaultdict(list)
        for index_a, index_b in pairs:
            first, second = entries[index_a], entries[index_b]
            if first['kind'] == 'fixed' and second['kind'] == 'fixed':
                continue
            result = V.evaluate_pair(first['prep'], second['prep'],
                                     C.CLEARANCE, V.SAGITTA, policy)
            if result is None or not result['crossings'] or not result['valid']:
                continue
            if first['kind'] == 'movable' and second['kind'] == 'movable':
                for crossing in result['crossings']:
                    index = len(self.mm_events)
                    self.mm_events.append(dict(
                        a=first['rid'], b=second['rid'],
                        s_a=float(crossing['sa']), s_b=float(crossing['sb']),
                        x=float(crossing['point'][0]),
                        y=float(crossing['point'][1])))
                    self.by_m[first['rid']].append(('mm', index, True))
                    self.by_m[second['rid']].append(('mm', index, False))
            else:
                if first['kind'] == 'movable':
                    mover, fixed, s_m, s_f = first, second, 'sa', 'sb'
                else:
                    mover, fixed, s_m, s_f = second, first, 'sb', 'sa'
                cat = ctx.cat.get(fixed['rid'], '?')
                for crossing in result['crossings']:
                    point = crossing['point']
                    adj_kind = ''
                    if cat == 'adjacent_z1' and fixed['z'] == C.Z1:
                        located = C.locate_on_chain(ctx.chain(fixed['rid']),
                                                    point[0], point[1])
                        adj_kind = ('arc' if (located is not None
                                              and located[1] == 'arc')
                                    else 'line')
                    index = len(self.mf_events)
                    self.mf_events.append(dict(
                        m=mover['rid'], s_m=float(crossing[s_m]),
                        f=fixed['rid'], z=fixed['z'],
                        s_f=float(crossing[s_f]),
                        x=float(point[0]), y=float(point[1]),
                        cat=cat, adj_kind=adj_kind))
                    self.by_m[mover['rid']].append(('mf', index, True))
        self.build_seconds = time.perf_counter() - started
        if verbose:
            print(f'  [lift-engine] mm_events={len(self.mm_events)} '
                  f'mf_events={len(self.mf_events)} '
                  f'build={self.build_seconds:.2f}s', flush=True)

    def route_stats(self, rid, geom, geoms):
        """(pairs, events, per_height, adjacent_line, adjacent_arc) of a route."""
        rid = int(rid)
        partners = {}
        events = 0
        per_height = Counter()
        adjacent_line = adjacent_arc = adjacent_related = 0
        for kind, index, is_m in self.by_m.get(rid, ()):
            if kind == 'mm':
                event = self.mm_events[index]
                s_self = event['s_a'] if is_m else event['s_b']
                z_self = geom_z_at(geom, s_self)
                if z_self is None:
                    continue
                other = event['b'] if is_m else event['a']
                other_geom = geoms.get(other)
                if other_geom is None:
                    continue
                s_other = event['s_b'] if is_m else event['s_a']
                if geom_z_at(other_geom, s_other) != z_self:
                    continue
            else:
                event = self.mf_events[index]
                z_self = geom_z_at(geom, event['s_m'])
                if z_self is None or z_self != event['z']:
                    continue
                other = event['f']
                if z_self == C.Z1 and event['cat'] == 'adjacent_z1':
                    adjacent_related += 1
                    if event['adj_kind'] == 'arc':
                        adjacent_arc += 1
                    else:
                        adjacent_line += 1
            events += 1
            per_height[z_self] += 1
            partners[other] = partners.get(other, 0) + 1
        return dict(pairs=len(partners), events=events,
                    per_height=dict(per_height),
                    adjacent_related=adjacent_related,
                    adjacent_line=adjacent_line, adjacent_arc=adjacent_arc)

    def full_audit(self, records):
        """Crossing audit of one complete layout (movable-involved events)."""
        geoms = {int(record['route_id']): route_geom(record)
                 for record in records
                 if int(record['route_id']) in self.movable}
        per_route = Counter()
        unique_pairs = set()
        events = 0
        adjacent_related = adjacent_line = adjacent_arc = 0
        for rid, geom in geoms.items():
            stats = self.route_stats(rid, geom, geoms)
            per_route[rid] = stats['events']
            adjacent_related += stats['adjacent_related']
            adjacent_line += stats['adjacent_line']
            adjacent_arc += stats['adjacent_arc']
        for event in self.mm_events:
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            events += 1
            unique_pairs.add((min(event['a'], event['b']),
                              max(event['a'], event['b'])))
        for event in self.mf_events:
            z_self = geom_z_at(geoms[event['m']], event['s_m'])
            if z_self is None or z_self != event['z']:
                continue
            events += 1
            unique_pairs.add((min(event['m'], event['f']),
                              max(event['m'], event['f'])))
        return dict(events=events, unique_pairs=len(unique_pairs),
                    per_route=per_route,
                    adjacent_related=adjacent_related,
                    adjacent_line=adjacent_line, adjacent_arc=adjacent_arc)


# ---------------------------------------------------------------------------
# window search on the current layout
# ---------------------------------------------------------------------------
def search_legal_windows(ctx, records, rids, log=print, tag='windows'):
    """All world-legal windows of ``rids`` on their current layer/layout.

    Returns {rid: {'target_layer': int, 'current': (a_in, a_out),
                   'legal': [(a_in, a_out), ...]}}.
    """
    by_id = {int(record['route_id']): record for record in records}
    world = ctx.world(records)
    legal_map = {}
    started = time.perf_counter()
    for index, rid in enumerate(rids):
        record = by_id[rid]
        layer = C.Ctx.route_target_layer(record)
        a_in, a_out = C.Ctx.stubs(record)
        grid = S.window_grid(ctx, rid, layer)
        world.remove_route(rid)
        legal = []
        for a_rise, a_fall in grid:
            candidate, route = S.evaluate_single(ctx, world, rid, layer,
                                                 a_rise, a_fall, collect=False)
            if candidate['legal']:
                legal.append((float(a_rise), float(a_fall)))
        world.add_route(record)
        legal_map[rid] = dict(target_layer=layer,
                              current=(float(a_in), float(a_out)),
                              legal=legal)
        if (index + 1) % 20 == 0 or index + 1 == len(rids):
            elapsed = time.perf_counter() - started
            log(f'[{tag}] searched {index + 1}/{len(rids)} ({elapsed:.1f}s, '
                f'eta {elapsed / (index + 1) * (len(rids) - index - 1):.0f}s)')
    return legal_map


# ---------------------------------------------------------------------------
# the refiner
# ---------------------------------------------------------------------------
def refine(ctx, records, movable_rids=None, max_passes=2, log=print):
    """E1-D validated greedy S-bend window refiner (no disk writes).

    Parameters
    ----------
    ctx : core.Ctx
    records : list[dict]
        complete routed layout (all 1024 records).
    movable_rids : list[int] | None
        routes whose ``(a_in, a_out)`` may change.  ``None`` = every Z1
        C2-opposite route that is lifted (``route_target_layer > 1``) in the
        given layout.
    max_passes : int
        greedy passes over the movable routes (stops early when a pass accepts
        nothing).
    log : callable
        progress sink (default ``print``).

    Returns
    -------
    dict with
        records     : updated full record list (input order, status routed)
        changed     : [{'route_id', 'old': (a_in, a_out, layer),
                        'new': (a_in, a_out, layer), 'delta_pairs',
                        'delta_events', 'delta_adjacent', ...}]
        pass_stats  : [{'pass_index', 'accepted', 'seconds'}]
        stats       : {'base_unique_crossing_pairs', 'after_unique_crossing_pairs',
                       'base_adjacent_related_events', 'after_adjacent_related_events',
                       'engine_check': {...}, 'search_seconds', 'refine_seconds',
                       'movable_routes', 'searched_routes', 'routes_changed'}
    """
    started = time.perf_counter()
    records = [dict(record) for record in records]
    by_id = {int(record['route_id']): record for record in records}
    order_ids = [int(record['route_id']) for record in records]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError('duplicate route ids in records')

    if movable_rids is None:
        movable = [rid for rid in ctx.z1_opposite
                   if int(rid) in by_id
                   and C.Ctx.route_target_layer(by_id[rid]) > 1]
    else:
        movable = [int(rid) for rid in movable_rids if int(rid) in by_id]
    # a movable route must be a chain-based lift (flat parts are sub-chains of
    # its fixed 2D chain), otherwise the exact engine cannot model it.
    supported = []
    for rid in movable:
        geom = route_geom(by_id[rid])
        if abs(geom_length(geom) - ctx.total(rid)) > 1e-6:
            log(f'  [refine] WARNING: route {rid} is not chain-based '
                f'(span {geom_length(geom):.4f} != chain {ctx.total(rid):.4f}); '
                f'kept fixed')
            continue
        supported.append(rid)
    movable = supported
    log(f'[refine] records={len(records)} movable={len(movable)}')

    base_analysis = C.audit(records, ctx)
    log(f'[refine] base audit unique={base_analysis["n_unique_pairs"]} '
        f'adjacent={base_analysis["adjacent_related_events"]}')

    # -- which routes can actually be improved --------------------------------
    search_rids = []
    for rid in movable:
        a_in, a_out = C.Ctx.stubs(by_id[rid])
        if base_analysis['per_route'].get(rid, 0) <= 0:
            continue
        if (a_in <= PORT_MARGIN + AREA_EPS
                and a_out <= PORT_MARGIN + AREA_EPS):
            continue
        search_rids.append(rid)
    log(f'[refine] searching windows for {len(search_rids)} routes')
    t_search = time.perf_counter()
    legal_map = search_legal_windows(ctx, records, search_rids, log=log,
                                     tag='refine')
    search_seconds = time.perf_counter() - t_search

    # -- ordering: predicted removable z=0 events, then current stub length ---
    total_by_rid = {rid: ctx.total(rid) for rid in movable}
    events_by_rid = defaultdict(list)
    movable_set = set(movable)
    for event in base_analysis['events']:
        a, b = int(event['route_a']), int(event['route_b'])
        if a not in movable_set and b not in movable_set:
            continue
        loc_a = chain_position(ctx, a, event['x'], event['y'])
        loc_b = chain_position(ctx, b, event['x'], event['y'])
        if a in movable_set:
            events_by_rid[a].append((a, b, round(float(event['z']), 6), loc_a[2]))
        if b in movable_set:
            events_by_rid[b].append((b, a, round(float(event['z']), 6), loc_b[2]))

    def _predicted_removed(rid):
        info = legal_map.get(rid)
        if not info:
            return 0, None
        total = total_by_rid[rid]
        a_in, a_out = C.Ctx.stubs(by_id[rid])
        z0 = [(s, partner) for (self_id, partner, z, s) in events_by_rid.get(rid, ())
              if z == C.Z1]
        head = [s for s, _ in z0 if s <= a_in + 1e-9]
        tail = [total - s for s, _ in z0 if s >= total - a_out - 1e-9]
        earlier = [(i, o) for i, o in info['legal']
                   if i < a_in - 0.05 or o < a_out - 0.05]
        if not earlier:
            return 0, None
        best = min(earlier, key=lambda window: (window[0] + window[1], window[0]))
        removed = (sum(1 for s in head if s > best[0] + 1e-9)
                   + sum(1 for d in tail if d > best[1] + 1e-9))
        return removed, best

    order_score = {}
    for rid in movable:
        removed, _best = _predicted_removed(rid)
        order_score[rid] = removed
    order = sorted(movable,
                   key=lambda rid: (-order_score.get(rid, 0),
                                    -(C.Ctx.stubs(by_id[rid])[0]
                                      + C.Ctx.stubs(by_id[rid])[1])))

    # -- greedy replacement ---------------------------------------------------
    engine = LiftingEngine(ctx, movable, records, verbose=True)
    geoms = {rid: route_geom(by_id[rid]) for rid in movable}
    world = ctx.world(records)
    changed = []
    pass_stats = []
    for pass_index in range(1, int(max_passes) + 1):
        accepted = 0
        t_pass = time.perf_counter()
        for position, rid in enumerate(order):
            info = legal_map.get(rid)
            if not info:
                continue
            layer = info['target_layer']
            current = C.Ctx.stubs(by_id[rid])
            candidates = [window for window in info['legal']
                          if window[0] < current[0] - 1e-6
                          or window[1] < current[1] - 1e-6]
            if not candidates:
                continue
            world.remove_route(rid)
            old_geom = geoms[rid]
            old_stats = engine.route_stats(rid, old_geom, geoms)
            best = None
            for a_rise, a_fall in candidates:
                record = S.build_single(ctx, rid, layer, a_rise, a_fall)
                if record is None or S.structure_errors(record):
                    continue
                if world.check_route(record):
                    continue
                new_geom = route_geom(record)
                new_stats = engine.route_stats(rid, new_geom, geoms)
                delta_pairs = new_stats['pairs'] - old_stats['pairs']
                delta_events = new_stats['events'] - old_stats['events']
                delta_adj = (new_stats['adjacent_related']
                             - old_stats['adjacent_related'])
                # full-layout unique crossings cannot increase (fixed-fixed
                # pairs are constant, so the route-local pair delta is exact)
                if delta_pairs > 0 or delta_adj > 0 or delta_events > 0:
                    continue
                if delta_pairs == 0 and delta_adj == 0 and delta_events == 0:
                    continue
                score = (delta_pairs, delta_adj, delta_events,
                         a_rise + a_fall, a_rise)
                if best is None or score < best[0]:
                    best = (score, record, new_geom, dict(
                        delta_pairs=delta_pairs,
                        delta_events=delta_events,
                        delta_adjacent=delta_adj,
                        delta_line=(new_stats['adjacent_line']
                                    - old_stats['adjacent_line']),
                        delta_arc=(new_stats['adjacent_arc']
                                   - old_stats['adjacent_arc'])))
            if best is None:
                world.add_route(by_id[rid])
                continue
            _, record, new_geom, delta = best
            world.add_route(record)
            by_id[rid] = record
            geoms[rid] = new_geom
            changed.append(dict(
                route_id=rid,
                old=(round(current[0], 6), round(current[1], 6), int(layer)),
                new=(round(float(C.Ctx.stubs(record)[0]), 6),
                     round(float(C.Ctx.stubs(record)[1]), 6), int(layer)),
                pair_id=(ctx.pairs_by_rid[rid]['pair_id']
                         if rid in ctx.pairs_by_rid else ''),
                base_stub_total=round(current[0] + current[1], 6),
                new_stub_total=round(sum(C.Ctx.stubs(record)), 6),
                **delta))
            accepted += 1
            if accepted % 20 == 0:
                log(f'[refine] pass{pass_index} {position + 1}/{len(order)} '
                    f'accepted={accepted} {time.perf_counter() - t_pass:.1f}s')
        pass_stats.append(dict(pass_index=pass_index, accepted=accepted,
                               seconds=round(time.perf_counter() - t_pass, 2)))
        log(f'[refine] pass{pass_index}: accepted {accepted} changes in '
            f'{pass_stats[-1]["seconds"]}s')
        if accepted == 0:
            break

    final_records = [by_id[rid] for rid in order_ids]
    after_analysis = C.audit(final_records, ctx)
    engine_check = engine.full_audit(final_records)
    core_movable_events = [event for event in after_analysis['events']
                           if int(event['route_a']) in engine.movable
                           or int(event['route_b']) in engine.movable]
    stats = dict(
        movable_routes=len(movable),
        searched_routes=len(search_rids),
        routes_changed=len(changed),
        base_unique_crossing_pairs=base_analysis['n_unique_pairs'],
        after_unique_crossing_pairs=after_analysis['n_unique_pairs'],
        base_adjacent_related_events=base_analysis['adjacent_related_events'],
        after_adjacent_related_events=after_analysis[
            'adjacent_related_events'],
        base_adjacent_line_events=base_analysis['adjacent_line_events'],
        after_adjacent_line_events=after_analysis['adjacent_line_events'],
        base_adjacent_arc_events=base_analysis['adjacent_arc_events'],
        after_adjacent_arc_events=after_analysis['adjacent_arc_events'],
        base_z1_crossing_pairs=base_analysis['z1_pairs'],
        after_z1_crossing_pairs=after_analysis['z1_pairs'],
        base_high_layer_crossing_pairs=base_analysis['high_pairs'],
        after_high_layer_crossing_pairs=after_analysis['high_pairs'],
        engine_check=dict(
            engine_events=engine_check['events'],
            core_movable_events=len(core_movable_events),
            engine_pairs=engine_check['unique_pairs'],
            core_pairs=len({(min(int(e['route_a']), int(e['route_b'])),
                             max(int(e['route_a']), int(e['route_b'])))
                            for e in core_movable_events}),
            engine_adjacent=engine_check['adjacent_related'],
            core_adjacent=sum(
                1 for event in after_analysis['events']
                if 'adjacent_z1' in (ctx.cat.get(int(event['route_a']), '?'),
                                     ctx.cat.get(int(event['route_b']), '?'))
                and event['z'] == C.Z1)),
        search_seconds=round(search_seconds, 2),
        engine_build_seconds=round(engine.build_seconds, 2),
        refine_seconds=round(time.perf_counter() - started, 2),
    )
    log(f'[refine] done: {len(changed)} routes changed; unique '
        f'{stats["base_unique_crossing_pairs"]} -> '
        f'{stats["after_unique_crossing_pairs"]}; adjacent '
        f'{stats["base_adjacent_related_events"]} -> '
        f'{stats["after_adjacent_related_events"]}')
    return dict(records=final_records, changed=changed, pass_stats=pass_stats,
                stats=stats)


if __name__ == '__main__':
    # self-check: run on the published BASE and print the exact result
    # (no disk writes)
    _ctx = C.load_ctx()
    _result = refine(_ctx, _ctx.records_base)
    print('changed routes:', len(_result['changed']))
    print('pass stats   :', _result['pass_stats'])
    print('stats        :', {key: _result['stats'][key] for key in
                             ('base_unique_crossing_pairs',
                              'after_unique_crossing_pairs',
                              'base_adjacent_related_events',
                              'after_adjacent_related_events')})
    from four_side_1024.manual_c4 import z1_multilayer_150um as Z
    _payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                    experiment='refine_base_selfcheck',
                    layer_stack=Z.stack_payload(7), routes=_result['records'])
    _validation = Z.validate_payload(_payload, max_layer=7, log=lambda *a: None)
    print('validation   :', _validation.get('status'),
          _validation.get('counts'))
