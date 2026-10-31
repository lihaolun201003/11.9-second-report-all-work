# -*- coding: utf-8 -*-
"""F1/F2/F3 layer-strategy experiments: shared core.

Strategy experiments on the 7-layer 150 um stack, starting from the current best
E1 solution (3,594 unique crossings, 1024/1024, violations=0).

Build order (Z1 first, then Z2 as an independent subsystem):

1. place the fixed Z1 interface routes (adjacent arcs) flat;
2. place the prescribed Z1 opposite routes on their target layer with the
   smallest legal S-bend window, allowing per-route asymmetric windows and
   fallback layers (recorded);
3. optimise the 512 Z2 routes independently (interface / L2..L7, per-route or
   per-U-bundle moves) with the exact incremental crossing engine;
4. optional joint micro-tuning of windows / target layers.

Every layout is built sequentially into a collision world, so it is legal by
construction; the frozen validator is still run and a repair loop reverts any
route the stricter frozen check rejects.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.e1 import layering as L
from four_side_1024.c4 import engine as E

OUT = C.Z.CAMPAIGN / 'F1_F2_F3_layer_strategy'
WORK = OUT / '_work'
MAX_LAYER = 7
LAYERS = tuple(range(2, MAX_LAYER + 1))
A_SMALL = [1.2, 1.6, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0, 4.5, 5.0, 5.6, 6.2,
           7.0, 8.0, 9.0, 10.0, 11.5, 13.0, 15.0, 17.0, 20.0, 24.0, 28.0,
           32.0, 36.0, 40.0, 45.0, 50.0, 55.0, 58.0, 60.0, 62.0, 64.0]


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_baseline(ctx):
    payload = C.read_json(C.E1 / 'best_solution' / 'routes_1024.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    return {int(r['route_id']): r for r in records}


def flat_records(ctx):
    return {int(rid): ctx.flat(rid) for rid in ctx.manifest}


CLEARANCE_MARGIN = 0.12


def make_world(records):
    values = records.values() if isinstance(records, dict) else records
    values = list(values)
    world = C.Z.make_world(values, MAX_LAYER)
    # a safety margin above the 0.08 mm spec: the frozen validator samples the
    # transitions more densely than the fast world, so candidates that only just
    # pass 0.08 mm would be rejected there.  The accept thresholds are baked into
    # ClearanceWorld3D at construction time, so the world must be rebuilt.
    from four_side_1024.fsd25d.world25d import ClearanceWorld3D
    world.clearance = CLEARANCE_MARGIN
    clearance_world = ClearanceWorld3D(CLEARANCE_MARGIN)
    for route in values:
        clearance_world.add_route(route)
    world.clearance_world = clearance_world
    return world


def route_geom(record):
    return E.route_geom(record)


def geoms_of(records):
    return {rid: route_geom(record) for rid, record in records.items()}


def engine(ctx):
    return E.C4Engine(ctx, cache_dir=WORK, log=lambda *a: None)


def orbit_groups(ctx):
    """C2 pair-directions of the Z1 opposite routes (independent per member)."""
    return ctx.pair_dirs


def z1_u_groups(ctx):
    return [int(gid) for gid, info in ctx.groups.items()
            if info['kind'] == 'same' and info['plane'] == 'z1']


def z2_u_groups(ctx):
    return [int(gid) for gid, info in ctx.groups.items()
            if info['kind'] == 'same' and info['plane'] == 'z2']


def z2_opposite_groups(ctx):
    return [int(gid) for gid, info in ctx.groups.items()
            if info['kind'] == 'opposite' and info['plane'] == 'z2']


# ---------------------------------------------------------------------------
# exact per-route / per-group crossing delta
# ---------------------------------------------------------------------------
def _pair_height(geom_a, s_a, geom_b, s_b):
    za = E.geom_z_at(geom_a, s_a)
    if za is None:
        return None
    zb = E.geom_z_at(geom_b, s_b)
    if zb is None or za != zb:
        return None
    return round(za, 6)


def unit_delta(eng, geoms, rids, new_geoms):
    """Exact change of global unique-pair count when ``rids`` take new geoms."""
    affected = set()
    for rid in rids:
        affected.update(eng.by_rid.get(rid, ()))
    before = defaultdict(set)
    after = defaultdict(set)
    rids = set(rids)
    for index in affected:
        event = eng.events[index]
        a, b = event['a'], event['b']
        pair = (min(a, b), max(a, b))
        za = _pair_height(geoms[a], event['s_a'], geoms[b], event['s_b'])
        if za is not None:
            before[pair].add(za)
        na = new_geoms.get(a, geoms[a])
        nb = new_geoms.get(b, geoms[b])
        za2 = _pair_height(na, event['s_a'], nb, event['s_b'])
        if za2 is not None:
            after[pair].add(za2)
    delta = 0
    for pair in set(before) | set(after):
        delta += len(after.get(pair, ())) - len(before.get(pair, ()))
    return delta


# ---------------------------------------------------------------------------
# window candidates
# ---------------------------------------------------------------------------
def windows(ctx, rid, layer, count=6):
    grid = S.window_grid(ctx, rid, layer, symmetric_only=False)
    if not grid:
        return []
    picks = list(grid[:3])
    for frac in (0.25, 0.5, 0.75, 1.0):
        index = min(len(grid) - 1, int(frac * (len(grid) - 1)))
        picks.append(grid[index])
    out = []
    seen = set()
    for a_in, a_out in picks[:count]:
        key = (round(a_in, 4), round(a_out, 4))
        if key in seen:
            continue
        seen.add(key)
        out.append((float(a_in), float(a_out)))
    return out


def legal(world, routes):
    from four_side_1024.l3d.world import World
    for route in routes:
        if World.check_structure(route):
            return False
        if world.check_route(route):
            return False
    for index in range(len(routes)):
        for other in range(index + 1, len(routes)):
            if C.pairwise_violations(world, routes[index], routes[other]):
                return False
    return True


# ---------------------------------------------------------------------------
# phase A: prescribed Z1 layering
# ---------------------------------------------------------------------------
def build_z1_phase(ctx, plan, log=print, base_records=None):
    """Build the Z1 part starting from the complete interface-flat layout.

    The collision world starts as the full 1024-route flat layout, so every Z1
    lift is checked against the Z2 interface routes as well; otherwise a small
    Z1 S-bend window can conflict with a collinear Z2 arm and the final layout
    would fail the frozen validator.
    """
    if base_records is None:
        records = {int(rid): ctx.flat(rid) for rid in ctx.manifest}
    else:
        records = dict(base_records)
    world = make_world(records)
    rows = []
    order = sorted(plan, key=lambda rid: (
        0 if ctx.cat[rid].startswith('opposite_z1') else 1, rid))
    for index, rid in enumerate(order):
        if index and index % 32 == 0:
            world = make_world(records)
        expected = int(plan[rid])
        cat = ctx.cat[rid]
        own = {rid}
        candidates = []
        if expected > 1:
            for layer in [expected] + [lay for lay in (2, 3, 4, 5, 6, 7)
                                       if lay != expected]:
                for a_in, a_out in windows(ctx, rid, layer):
                    candidates.append((layer, a_in, a_out))
        placed = None
        if candidates:
            for layer, a_in, a_out in candidates:
                route = ctx.lift(rid, layer, a_in, a_out)
                if route is None:
                    continue
                if not legal_modulo_self(ctx, world, [route], own):
                    placed = (route, layer, a_in, a_out)
                    break
        if placed is None:
            route = records[rid]
            placed = (route, 1, None, None)
            reason = 'no_legal_window' if candidates else ''
        else:
            reason = ''
        route, layer, a_in, a_out = placed
        records[rid] = route
        world.add_route(route)
        rows.append(dict(route_id=rid, category=cat, expected_layer=expected,
                         actual_layer=layer, a_in=a_in, a_out=a_out,
                         fallback=(layer != expected), reason=reason))
    log(f'[z1] placed {len(rows)} routes: '
        f'{dict(Counter(row["actual_layer"] for row in rows))}')
    return records, rows


# ---------------------------------------------------------------------------
# Z2: strict C4 orbit units (Z1 stays asymmetric)
# ---------------------------------------------------------------------------
def z2_orbits(ctx):
    from four_side_1024.c4 import orbits as O
    return [orbit for orbit in O.load_orbits(ctx) if orbit['plane'] == 'z2']


def orbit_candidates(ctx, orbit, layer_pool, count=6):
    from four_side_1024.c4 import orbits as O
    out = []
    seen = set()
    for layer in layer_pool:
        grid = O.window_grid(ctx, orbit, layer, symmetric_only=False)
        if not grid:
            continue
        picks = list(grid[:3])
        for frac in (0.25, 0.5, 0.75, 1.0):
            picks.append(grid[min(len(grid) - 1, int(frac * (len(grid) - 1)))])
        taken = 0
        for a_in, a_out in picks:
            key = (layer, round(float(a_in), 4), round(float(a_out), 4))
            if key in seen:
                continue
            seen.add(key)
            out.append((int(layer), float(a_in), float(a_out)))
            taken += 1
            if taken >= count:
                break
    return out


def optimize_z2_orbits(ctx, eng, records, orbits, world, log=print,
                       layer_pool=(2, 3, 4, 5, 6, 7), max_legal_tries=6,
                       pass_name='z2-c4', world_mode='fresh',
                       rebuild_every=32):
    """Greedy joint optimisation of whole Z2 C4 orbits (4 routes together)."""
    from four_side_1024.c4 import orbits as O
    from four_side_1024.c4 import engine as E
    from four_side_1024.c4 import optimize as CO
    geoms = geoms_of(records)
    analysis = C.audit(list(records.values()), ctx)
    contribution = analysis['per_route']
    orbits = sorted(orbits, key=lambda orbit: (
        -sum(contribution.get(rid, 0) for rid in orbit['ids']),
        orbit['group_id']))
    log(f'[{pass_name}] start unique={analysis["n_unique_pairs"]} orbits='
        f'{len(orbits)}')
    moved = 0
    for index, orbit in enumerate(orbits):
        if index and index % rebuild_every == 0 and world_mode == 'existing':
            world = make_world(records)
        rids = [int(rid) for rid in orbit['ids']]
        own = set(rids)
        if world_mode == 'fresh':
            for rid in rids:
                world.add_route(records[rid])
        current_layer = C.Ctx.route_target_layer(records[rids[0]])
        hint = current_layer if current_layer > 1 else 4
        layers_try = [hint] + [lay for lay in layer_pool if lay != hint]
        cands = orbit_candidates(ctx, orbit, layers_try)
        scored = []
        for layer, a_in, a_out in cands:
            new_geoms = E.orbit_geom(ctx, orbit, layer, a_in, a_out)
            if new_geoms is None:
                continue
            routes = O.build_orbit(ctx, orbit, layer, a_in, a_out)
            if routes is None:
                continue
            delta = eng.orbit_delta(geoms, orbit, new_geoms)
            scored.append((delta, layer, a_in, a_out, routes, new_geoms))
        scored.sort(key=lambda item: item[0])
        best = None
        tries = 0
        for delta, layer, a_in, a_out, routes, new_geoms in scored:
            if delta >= 0:
                break
            if tries >= max_legal_tries:
                break
            tries += 1
            if not CO.orbit_legal(world, orbit, routes):
                continue
            best = (delta, layer, routes, new_geoms)
            break
        if best is None:
            continue
        delta, layer, routes, new_geoms = best
        for route in routes:
            rid = int(route['route_id'])
            records[rid] = route
            geoms[rid] = new_geoms[rid]
            world.add_route(route)
        moved += 1
    analysis = C.audit(list(records.values()), ctx)
    log(f'[{pass_name}] unique={analysis["n_unique_pairs"]} moved={moved}/'
        f'{len(orbits)}')
    return records, analysis


def z2_c4_validation(ctx, records):
    """Independent strict-C4 audit of the Z2 subsystem only (Z1 excluded)."""
    from four_side_1024.c4 import validate as V4
    z2_rids = {rid for rid in records
               if ctx.cat[rid].startswith(('adjacent_z2', 'same_u_z2',
                                           'opposite_z2'))}
    payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                   experiment='F123-z2-c4',
                   layer_stack=C.Z.stack_payload(MAX_LAYER),
                   routes=[records[rid] for rid in sorted(z2_rids)])
    report = V4.validate_layout(payload, max_layer=MAX_LAYER)
    z2_orbits = [orbit for orbit in report.get('per_orbit') or []
                 if orbit.get('plane') == 'z2']
    orbit_size_errors = sum(1 for orbit in z2_orbits
                            if int(orbit.get('n_present') or 0) != 4)
    endpoint_errors = sum(1 for orbit in z2_orbits
                          if not orbit.get('endpoint_ok', True))
    layer_errors = sum(1 for orbit in z2_orbits
                       if not orbit.get('layer_ok', True))
    transition_errors = sum(1 for orbit in z2_orbits
                            if not orbit.get('transition_ok', True))
    geometry_errors = sum(1 for orbit in z2_orbits
                          if not orbit.get('geometry_ok', True))
    max_dev = max((float(orbit.get('xyz_max_mm') or 0.0)
                   for orbit in z2_orbits), default=0.0)
    failed = [orbit['group_id'] for orbit in z2_orbits
              if orbit.get('failed')]
    symmetry_pass = (orbit_size_errors == 0 and endpoint_errors == 0
                     and layer_errors == 0 and transition_errors == 0
                     and geometry_errors == 0 and not failed)
    return dict(
        schema='four_side_1024_z2_strict_c4_validation_v1',
        scope='Z2 subsystem only (Z1 asymmetric by design)',
        total_routes=len(z2_rids),
        total_orbits=len(z2_orbits),
        orbit_size_errors=orbit_size_errors,
        endpoint_rotation_errors=endpoint_errors,
        layer_symmetry_errors=layer_errors,
        transition_symmetry_errors=transition_errors,
        geometry_symmetry_errors=geometry_errors,
        maximum_xyz_deviation_mm=float(max_dev),
        failed_orbits=failed,
        symmetry_pass=bool(symmetry_pass),
        validator=__file__,
    )


# ---------------------------------------------------------------------------
# phase B: independent Z2 optimisation
# ---------------------------------------------------------------------------
def _unit_candidates(ctx, rids, layer_hint):
    """Candidate (layer, [(a_in, a_out) per route]) for a route or U bundle."""
    out = []
    layers = [layer_hint] + [lay for lay in (4, 5, 6, 7, 3, 2)
                             if lay != layer_hint]
    for layer in layers:
        grids = [windows(ctx, rid, layer, count=4) for rid in rids]
        if any(not grid for grid in grids):
            continue
        for index in range(min(len(grid) for grid in grids)):
            out.append((layer, [grid[index] for grid in grids]))
    return out


def optimize_units(ctx, eng, records, units, world, log=print,
                   layer_pool=(2, 3, 4, 5, 6, 7), max_legal_tries=5,
                   pass_name='z2', world_mode='fresh', rebuild_every=96):
    """Greedy sequential optimisation of route/bundle units against a world.

    ``world_mode='fresh'``: the world does not yet contain the units' current
    geometry (they are added as we walk).  ``'existing'``: the world already
    contains the full current layout (used for later refinement passes).
    """
    geoms = geoms_of(records)
    analysis = C.audit(list(records.values()), ctx)
    log(f'[{pass_name}] start unique={analysis["n_unique_pairs"]}')
    contribution = analysis['per_route']
    units = sorted(units, key=lambda unit: (
        -sum(contribution.get(rid, 0) for rid in unit['rids']),
        unit['rids'][0]))
    moved = 0
    for index, unit in enumerate(units):
        if index and index % rebuild_every == 0 and world_mode == 'existing':
            world = make_world(records)
        rids = unit['rids']
        own = set(rids)
        if world_mode == 'fresh':
            for rid in rids:
                world.add_route(records[rid])
        current = [records[rid] for rid in rids]
        current_layer = C.Ctx.route_target_layer(current[0])
        hint = current_layer if current_layer > 1 else 4
        layers_try = [current_layer] + [lay for lay in layer_pool
                                        if lay != current_layer]
        cands = []
        for layer in layers_try:
            if layer == 1:
                continue
            grids = [windows(ctx, rid, layer, count=4) for rid in rids]
            if any(not grid for grid in grids):
                continue
            for idx in range(min(len(grid) for grid in grids)):
                cands.append((layer, [grid[idx] for grid in grids]))
        scored = []
        for layer, wind in cands:
            routes = []
            ok = True
            for rid, (a_in, a_out) in zip(rids, wind):
                route = ctx.lift(rid, layer, a_in, a_out)
                if route is None:
                    ok = False
                    break
                routes.append(route)
            if not ok:
                continue
            new_geoms = {int(route['route_id']): route_geom(route)
                         for route in routes}
            delta = unit_delta(eng, geoms, rids, new_geoms)
            scored.append((delta, layer, routes, new_geoms))
        scored.sort(key=lambda item: item[0])
        best = None
        tries = 0
        for delta, layer, routes, new_geoms in scored:
            if delta >= 0:
                break
            if tries >= max_legal_tries:
                break
            tries += 1
            if not legal_modulo_self(ctx, world, routes, own):
                continue
            best = (delta, layer, routes, new_geoms)
            break
        if best is None:
            continue
        delta, layer, routes, new_geoms = best
        for route in routes:
            rid = int(route['route_id'])
            records[rid] = route
            geoms[rid] = new_geoms[rid]
            world.add_route(route)
        moved += 1
    analysis = C.audit(list(records.values()), ctx)
    log(f'[{pass_name}] unique={analysis["n_unique_pairs"]} moved={moved}/'
        f'{len(units)}')
    return records, analysis


# ---------------------------------------------------------------------------
# frozen-validator repair
# ---------------------------------------------------------------------------
def _violation_rids(report):
    ids = set()
    for item in report.get('violations') or []:
        for field in ('route_id', 'other_route', 'route_a', 'route_b'):
            value = item.get(field)
            if isinstance(value, int):
                ids.add(int(value))
            elif isinstance(value, str) and value.split(':')[0].isdigit():
                ids.add(int(value.split(':')[0]))
        for key in ('blockers', 'routes'):
            for value in item.get(key) or []:
                if isinstance(value, int):
                    ids.add(int(value) // 1000 if value > 10000 else int(value))
                elif isinstance(value, str) and value.split(':')[0].isdigit():
                    ids.add(int(value.split(':')[0]))
    return ids


def validate(records):
    payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                   experiment='F123',
                   layer_stack=C.Z.stack_payload(MAX_LAYER),
                   routes=list(records.values()))
    return C.Z.validate_payload(payload, max_layer=MAX_LAYER,
                                log=lambda *a: None)


def repair(ctx, records, log=print, max_rounds=30):
    """Frozen-validator repair that only touches the asymmetric Z1 routes.

    The Z2 C4 layout is kept as optimised: the Z1 S-bends were constructed after
    the Z2 orbits had cleared the corridors, so reverting a Z2 orbit to the
    interface would create new transition-vs-flat conflicts with those very Z1
    lifts.  Reverting only Z1 routes converges to a layout where the remaining
    Z1 lifts are legal against the unchanged Z2 layout (a fully-flat Z1 is
    always compatible with it).
    """
    reverted = []
    report = None
    z2_rids = {int(rid) for orbit in z2_orbits(ctx) for rid in orbit['ids']}
    best_count = None
    stall = 0
    for round_index in range(max_rounds):
        report = validate(records)
        counts = dict(report.get('counts') or {})
        violation_count = int(counts.get('violations') or 0)
        if violation_count == 0:
            log(f'  [repair] clean (round {round_index})')
            return records, report, reverted
        if best_count is None or violation_count < best_count:
            best_count = violation_count
            stall = 0
        else:
            stall += 1
        if stall >= 6:
            reverted_all = []
            for rid in sorted(records):
                if rid not in z2_rids and C.Ctx.route_target_layer(
                        records[rid]) > 1:
                    records[rid] = ctx.flat(rid)
                    reverted_all.append(rid)
            reverted.extend(reverted_all)
            report = validate(records)
            counts = dict(report.get('counts') or {})
            log('  [repair] stalled -> reverted all lifted Z1 routes '
                f'(violations={counts.get("violations")})')
            return records, report, reverted
        revert_rids = set()
        for item in report.get('violations') or []:
            for field in ('route_id', 'other_route', 'route_a', 'route_b'):
                value = item.get(field)
                if isinstance(value, int):
                    rid = int(value)
                elif isinstance(value, str) and value.split(':')[0].isdigit():
                    rid = int(value.split(':')[0])
                else:
                    continue
                if rid in records and rid not in z2_rids:
                    revert_rids.add(rid)
        changed = []
        for rid in sorted(revert_rids):
            if C.Ctx.route_target_layer(records[rid]) > 1:
                records[rid] = ctx.flat(rid)
                changed.append(rid)
        log(f'  [repair] round {round_index}: violations={violation_count} '
            f'reverting {len(changed)} Z1 routes')
        reverted.extend(changed)
        if not changed:
            break
    return records, report, reverted


# ---------------------------------------------------------------------------
# legality against a world that still contains the unit's own old geometry
# ---------------------------------------------------------------------------
def _strip_self(violations, own):
    out = []
    for violation in violations:
        if violation.get('kind') == 'flat_same_plane_conflict':
            blockers = [int(b) // 1000 for b in (violation.get('blockers') or [])]
            if [b for b in blockers if b not in own]:
                out.append(violation)
            continue
        other = violation.get('other_route')
        if other is not None and int(other) in own:
            continue
        out.append(violation)
    return out


def legal_modulo_self(ctx, world, routes, own):
    from four_side_1024.l3d.world import World
    problems = []
    for route in routes:
        if World.check_structure(route):
            problems.append(('structure', int(route['route_id'])))
            return problems
        bad = _strip_self(C.collect_violations(world, route), own)
        if bad:
            return bad
    for index in range(len(routes)):
        for other in range(index + 1, len(routes)):
            if C.pairwise_violations(world, routes[index], routes[other]):
                return [('mutual', 0)]
    return problems

