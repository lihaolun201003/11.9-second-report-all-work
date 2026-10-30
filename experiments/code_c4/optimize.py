# -*- coding: utf-8 -*-
"""C4 orbit-level greedy optimizer (layer assignment + S-window + Z1/Z2 joint).

Optimisation unit = one C4 orbit (4 routes).  A move is a
``(layer, a_in, a_out)`` for the orbit representative; the other three members
are built with the rotation-mapped window, so the layout stays exactly C4.

A pass is a *sequential construction* in a chosen orbit order:

* the collision world is initialised with the complete **interface-flat**
  layout, so every not-yet-processed orbit is present in its guaranteed legal
  flat geometry.  An accepted lift is therefore checked against all unprocessed
  orbits and all previously accepted lifts, which makes the produced layout
  legal by construction (the frozen validator is still run on every scheme);
* candidate ranking uses the exact all-pairs crossing engine
  (``E.C4Engine.orbit_delta``) against the layout as it currently stands;
* a candidate is accepted only when it is legal and strictly reduces the exact
  global unique-pair count; otherwise the previous geometry is kept.

Repeating passes with different orbit orders and candidate sets implements
layer assignment, window refinement and Z1/Z2 coordination.
"""
from __future__ import annotations

import time
from collections import Counter

from four_side_1024.e1 import core as C
from four_side_1024.c4 import layers as LY
from four_side_1024.c4 import orbits as O
from four_side_1024.c4 import engine as E

ORDER_PRIORITY = {
    ('z2', 'adjacent'): 0,
    ('z2', 'same'): 1,
    ('z2', 'opposite'): 2,
    ('z1', 'opposite'): 3,
    ('z1', 'same'): 4,
    ('z1', 'adjacent'): 5,
}


def current_geoms(records):
    return {int(record['route_id']): E.route_geom(record) for record in records}


def _priority(orbit, reverse=False):
    base = ORDER_PRIORITY.get((orbit['plane'], orbit['kind']), 9)
    return (-base if reverse else base, orbit['group_id'])


# ---------------------------------------------------------------------------
# candidate generation
# ---------------------------------------------------------------------------
def candidates_for(ctx, orbit, current, layers, mode):
    """Candidate (layer, a_in, a_out) list for one orbit."""
    out = []
    seen = set()

    def push(layer, grid, limit):
        count = 0
        for a_in, a_out in grid:
            window = (int(layer), float(a_in), float(a_out))
            if window in seen:
                continue
            seen.add(window)
            out.append(window)
            count += 1
            if count >= limit:
                break

    if mode in ('layer', 'mixed'):
        for layer in layers:
            grid = O.window_grid(ctx, orbit, layer, symmetric_only=True)
            if grid:
                picks = grid[:2]
                for frac in (0.25, 0.5, 0.75, 1.0):
                    index = min(len(grid) - 1, int(frac * (len(grid) - 1)))
                    picks.append(grid[index])
                push(layer, picks, 6)
    if mode in ('window', 'mixed'):
        layers_try = [current[0]] if current else list(layers)
        for layer in layers_try:
            grid = O.window_grid(ctx, orbit, layer, symmetric_only=False)
            if grid:
                push(layer, grid[:4], 4)
            grid_sym = O.window_grid(ctx, orbit, layer, symmetric_only=True)
            if grid_sym:
                push(layer, grid_sym[:3], 3)
    if current is not None:
        out.append(tuple(current))
    return out


# ---------------------------------------------------------------------------
# legality helpers (self-orbit conflicts are ignored because the world may
# still contain the orbit's own previous/flat geometry)
# ---------------------------------------------------------------------------
def _strip_self(violations, orbit):
    own = set(int(rid) for rid in orbit['ids'])
    out = []
    for violation in violations:
        if violation.get('kind') == 'flat_same_plane_conflict':
            blockers = [int(b) // 1000 for b in (violation.get('blockers') or [])]
            others = [b for b in blockers if b not in own]
            if others:
                out.append(dict(violation, other_routes=others))
            continue
        other = violation.get('other_route')
        if other is not None and int(other) in own:
            continue
        out.append(violation)
    return out


def _pair_conflicts(route_a, route_b):
    """Self-contained pairwise legality check (does not touch the world)."""
    from four_side_1024.d56.index import D56Index, prepare
    from four_side_1024.fslw import config as CFG
    from four_side_1024.fsd25d.world25d import ClearanceWorld3D
    index = D56Index(width=CFG.WIDTH_MM, gap=CFG.EDGE_GAP_MM,
                     sagitta=CFG.SAGITTA_MM,
                     min_cross_angle_deg=CFG.MIN_CROSS_ANGLE_DEG,
                     crossing_policy='strict')
    out = []
    for part in route_a['parts']:
        if part['kind'] != 'flat':
            continue
        index.add(int(route_a['route_id']) * 1000 + 7,
                  prepare(part['primitives']))
    for part in route_b['parts']:
        if part['kind'] != 'flat':
            continue
        evaluation = index.evaluate(prepare(part['primitives']))
        if evaluation is not None and not evaluation.valid:
            out.append(dict(kind='flat_same_plane_conflict',
                            blockers=list(getattr(evaluation, 'blockers', [])
                                          or [])))
    clearance = ClearanceWorld3D(C.CLEARANCE)
    clearance.add_route(route_a)
    out.extend(clearance.check_route(route_b, check_self=True))
    return out


def _route_legal(world, orbit, route):
    from four_side_1024.l3d.world import World
    if World.check_structure(route):
        return False
    # collect ALL violations: world.check_route returns only the first one, which
    # could be a self-orbit conflict that would mask a real one
    return not _strip_self(C.collect_violations(world, route), orbit)


def orbit_legal(world, orbit, routes):
    for route in routes:
        if not _route_legal(world, orbit, route):
            return False
    for index in range(len(routes)):
        for other in range(index + 1, len(routes)):
            if _strip_self(_pair_conflicts(routes[index], routes[other]),
                           orbit):
                return False
    return True


# ---------------------------------------------------------------------------
# one pass
# ---------------------------------------------------------------------------
def run_pass(ctx, orbits, params, max_layer, engine, log=print,
             mode='mixed', allowed_layers=None, only_kinds=None,
             order='priority', max_legal_tries=30, verbose=True,
             rebuild_every=32, utility_gids=None):
    started = time.perf_counter()
    layers = [int(layer) for layer in (allowed_layers or
                                       range(2, int(max_layer) + 1))]
    all_orbits = O.load_orbits(ctx)
    orbit_by_gid = {orbit['group_id']: orbit for orbit in all_orbits}
    flat_records = O.flat_records(ctx, all_orbits)
    flat_by_id = {int(record['route_id']): record for record in flat_records}
    by_id = {int(record['route_id']): record
             for record in O.assemble(ctx, params, all_orbits)}
    geoms = {rid: E.route_geom(record) for rid, record in by_id.items()}
    total = engine.audit(geoms)['unique_pairs']

    focus = [orbit for orbit in all_orbits
             if only_kinds is None
             or (orbit['plane'], orbit['kind']) in only_kinds]
    if order == 'priority':
        focus.sort(key=lambda orbit: _priority(orbit))
    elif order == 'reverse':
        focus.sort(key=lambda orbit: _priority(orbit, reverse=True))
    elif order == 'contribution':
        contrib = {}
        for orbit in focus:
            value = 0
            for rid in orbit['ids']:
                value += engine.contribution(geoms, rid)[0]
            contrib[orbit['group_id']] = value
        focus.sort(key=lambda orbit: (-contrib[orbit['group_id']],
                                      orbit['group_id']))

    def fresh_world(processed):
        """World = all-flat layout + accepted lifts of processed orbits."""
        world = E.make_world(flat_records, max_layer)
        for gid in processed:
            window = params.get(gid)
            if window is None:
                continue
            orbit = orbit_by_gid[gid]
            routes = O.build_orbit(ctx, orbit, *window)
            if routes is None:
                continue
            for route in routes:
                world.add_route(route)
        return world

    world = E.make_world(flat_records, max_layer)
    processed = []
    accepted = 0
    kept = 0
    changed = 0
    failed = Counter()
    for index, orbit in enumerate(focus):
        if index and index % rebuild_every == 0:
            world = fresh_world(processed)
        current = params.get(orbit['group_id'])
        cands = candidates_for(ctx, orbit, current, layers, mode)
        scored = []
        for window in cands:
            new_geoms = E.orbit_geom(ctx, orbit, *window)
            if new_geoms is None:
                continue
            delta = engine.orbit_delta(geoms, orbit, new_geoms)
            scored.append((delta, tuple(window), new_geoms))
        scored.sort(key=lambda item: item[0])
        if current is not None:
            current_routes = O.build_orbit(ctx, orbit, *current)
            current_legal = bool(current_routes) and orbit_legal(
                world, orbit, current_routes)
        else:
            current_routes = [flat_by_id[rid] for rid in orbit['ids']]
            current_legal = orbit_legal(world, orbit, current_routes)
        best = None
        tries = 0
        utility = utility_gids is not None and orbit['group_id'] in utility_gids
        for delta, window, new_geoms in scored:
            if current_legal and delta >= 0 and not utility:
                break
            if tries >= max_legal_tries:
                break
            tries += 1
            routes = O.build_orbit(ctx, orbit, *window)
            if routes is None:
                failed['build'] += 1
                continue
            if not orbit_legal(world, orbit, routes):
                failed['world'] += 1
                continue
            best = (delta, window, new_geoms, routes)
            break
        if best is None:
            # No layered candidate is legal.  Try the interface-flat fallback:
            # every accepted lift was checked against this orbit's flat geometry
            # when it was accepted, so flat is legal against the current world.
            flat_routes = [flat_by_id[rid] for rid in orbit['ids']]
            if current is not None and orbit_legal(world, orbit, flat_routes):
                flat_geoms = {rid: E.flat_geom(ctx, rid) for rid in orbit['ids']}
                delta = engine.orbit_delta(geoms, orbit, flat_geoms)
                for rid in orbit['ids']:
                    by_id[rid] = flat_by_id[rid]
                    geoms[rid] = E.route_geom(flat_by_id[rid])
                for route in flat_routes:
                    world.add_route(route)
                params.pop(orbit['group_id'], None)
                accepted += 1
                total += delta
                processed.append(orbit['group_id'])
                if verbose and (index + 1) % 64 == 0:
                    log(f'    [{mode}/{order}] {index+1}/{len(focus)} '
                        f'engine_total={total} accepted={accepted} '
                        f'({time.perf_counter()-started:.1f}s)')
                continue
            if current is not None and current_legal:
                for route in current_routes:
                    world.add_route(route)
            elif current is None:
                for route in flat_routes:
                    world.add_route(route)
            else:
                # keep the previous (possibly stale) geometry: record it
                failed['kept_illegal'] += 1
                for route in current_routes:
                    world.add_route(route)
            kept += 1
            processed.append(orbit['group_id'])
            continue
        delta, window, new_geoms, routes = best
        for route in routes:
            rid = int(route['route_id'])
            by_id[rid] = route
            geoms[rid] = new_geoms[rid]
            world.add_route(route)
        if current is None or tuple(window) != tuple(current):
            accepted += 1
        else:
            changed += 1
        params[orbit['group_id']] = window
        total += delta
        processed.append(orbit['group_id'])
        if verbose and (index + 1) % 64 == 0:
            log(f'    [{mode}/{order}] {index+1}/{len(focus)} '
                f'engine_total={total} accepted={accepted} '
                f'({time.perf_counter()-started:.1f}s)')
    records = [by_id[int(record['route_id'])] for record in ctx.records_base]
    analysis = C.audit(records, ctx)
    final = engine.audit(current_geoms(records))['unique_pairs']
    log(f'[pass {mode}/{order}] unique={analysis["n_unique_pairs"]} '
        f'engine={final} accepted={accepted} kept={kept} '
        f'replaced={changed} failed={dict(failed)} '
        f'{time.perf_counter()-started:.1f}s')
    log(f'[pass {mode}/{order}] heights: '
        f'{ {z: info["pairs"] for z, info in sorted(analysis["per_height"].items())} }')
    return dict(records=records, params=params, unique=analysis['n_unique_pairs'],
                engine_unique=final,
                per_height={z: info['pairs'] for z, info in
                            sorted(analysis['per_height'].items())},
                accepted=accepted, kept=kept, failed=dict(failed),
                seconds=round(time.perf_counter() - started, 1))


def summarise(ctx, records, name):
    analysis = C.audit(records, ctx)
    stats = C.bar(records)
    usage = C.layer_usage(records, ctx)
    return dict(experiment=name, routed=len(records),
                unique_crossing_pairs=analysis['n_unique_pairs'],
                z1_crossing_pairs=analysis['z1_pairs'],
                z2_crossing_pairs=analysis['z2_pairs'],
                high_layer_crossing_pairs=analysis['high_pairs'],
                z1_hv_pairs=analysis['z1_hv_pairs'],
                adjacent_related_events=analysis['adjacent_related_events'],
                adjacent_line_events=analysis['adjacent_line_events'],
                adjacent_arc_events=analysis['adjacent_arc_events'],
                opposite_opposite_events=analysis['opposite_opposite_events'],
                transitions=stats['transitions'],
                total_length_mm=stats['total_length_mm'],
                fabrication_hours=stats['fabrication_hours'],
                max_z_mm=max((LY.HEIGHTS.get(int(k), 0.0)
                              for k in stats['layer_counts']), default=0.0),
                layer_usage={str(k): dict(z=info['z'], routes=info['routes'],
                                          segments=info['segments'])
                             for k, info in usage.items()},
                per_height={str(z): info['pairs'] for z, info in
                            sorted(analysis['per_height'].items())})
