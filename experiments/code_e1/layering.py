# -*- coding: utf-8 -*-
"""E1-C layering engine: Z1 priority + Z2 relocation to the free upper layers."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from . import core as C
from . import search as S

# default Z2 destination order per category (upper layers first)
Z2_DEST = {
    'adjacent_z2': (6, 7, 5, 4),
    'same_u_z2': (7, 6, 5, 4),
    'opposite_z2_EW': (5, 6, 7),
    'opposite_z2_NS': (5, 6, 7),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def records_by_id(records):
    return {int(record['route_id']): record for record in records}


def replace(records, new_routes):
    """Return a new record list with ``new_routes`` substituted by route id."""
    by_id = records_by_id(records)
    for route in new_routes:
        by_id[int(route['route_id'])] = route
    return [by_id[int(record['route_id'])] for record in records]


def line_key(ctx, rid):
    prims = ctx.chain(rid)
    if len(prims) != 1 or prims[0]['kind'] != 'line':
        return None
    p0, p1 = prims[0]['p0'], prims[0]['p1']
    if abs(p0[0] - p1[0]) < 1e-6 and abs(p0[1] - p1[1]) > 1e-6:
        return ('V', round(p0[0], 6))
    if abs(p0[1] - p1[1]) < 1e-6 and abs(p0[0] - p1[0]) > 1e-6:
        return ('H', round(p0[1], 6))
    return None


def collinear_z2_movers(ctx, min_arm=5.0):
    """Z2 routes that own a straight arm collinear with a Z1 opposite line."""
    lines = {}
    for rid in ctx.z1_opposite:
        key = line_key(ctx, rid)
        if key is not None:
            lines[rid] = key
    line_set = set(lines.values())
    movers = {}
    for rid in ctx.z2_all:
        armed = []
        for prim in ctx.chain(rid):
            if prim['kind'] != 'line' or C.prim_len(prim) < min_arm:
                continue
            p0, p1 = prim['p0'], prim['p1']
            if abs(p0[0] - p1[0]) < 1e-6 and abs(p0[1] - p1[1]) < 1e-6:
                continue
            if abs(p0[0] - p1[0]) < 1e-6:
                key = ('V', round(p0[0], 6))
            elif abs(p0[1] - p1[1]) < 1e-6:
                key = ('H', round(p0[1], 6))
            else:
                continue
            if key in line_set:
                armed.append(dict(key=key, length=round(C.prim_len(prim), 3)))
        if armed:
            movers[rid] = armed
    return movers


def bundle_layer_shift(ctx, movers, shift=2):
    """Preserve the relative layer order of the moved Z2 routes."""
    by_id = records_by_id(ctx.records_base)
    dest = {}
    for rid in movers:
        layer = ctx.route_target_layer(by_id[rid])
        dest[rid] = tuple(min(7, max(4, layer + shift)) for _ in (0,))
    return dest


def relocate_z2(ctx, records, movers, dest=None, dest_fn=None, log=print,
                time_limit=300.0, max_candidates=40):
    """Move the given Z2 routes to the free upper layers (Z1 priority)."""
    mover_ids = set(int(rid) for rid in movers)
    fixed = [record for record in records
             if int(record['route_id']) not in mover_ids]
    world = ctx.world(fixed)
    moved = {}
    failed = {}
    started = time.perf_counter()
    order = sorted(mover_ids, key=lambda rid: (
        0 if ctx.cat[rid] == 'adjacent_z2' else
        1 if ctx.cat[rid] == 'same_u_z2' else 2, rid))
    for rid in order:
        if time.perf_counter() - started > time_limit:
            failed[rid] = 'time_limit'
            continue
        if dest_fn is not None:
            layers = dest_fn(rid)
        else:
            layers = dest.get(ctx.cat[rid], (6, 7))
        placed = None
        tried = 0
        for layer in layers:
            for a_in, a_out in S.window_grid(ctx, rid, int(layer),
                                             symmetric_only=True):
                tried += 1
                if tried > max_candidates:
                    break
                route = ctx.lift(rid, int(layer), a_in, a_out)
                if route is None or S.structure_errors(route):
                    continue
                if world.check_route(route):
                    continue
                placed = route
                break
            if placed is not None:
                break
            if tried > max_candidates:
                break
        if placed is None:
            failed[rid] = 'no_legal_layer'
            continue
        world.add_route(placed)
        moved[rid] = placed
    log(f'[relocate_z2] moved {len(moved)}/{len(mover_ids)} '
        f'failed={len(failed)} in {time.perf_counter()-started:.1f}s')
    out = list(fixed) + list(moved.values())
    covered = {int(record['route_id']) for record in out}
    for rid, record in records_by_id(records).items():
        if rid not in covered:
            out.append(record)
    return out, moved, failed


def lift_z1_pairs(ctx, records, ew_layer=2, ns_layer=3, strict=True,
                  log=print, time_limit=600.0, order=None,
                  max_candidates_per_layer=60):
    """Lift every Z1 C2 pair-direction with the smallest legal window."""
    records = list(records)
    pair_rids = set(ctx.z1_opposite)
    fixed = [record for record in records
             if int(record['route_id']) not in pair_rids]
    world = ctx.world(fixed)
    current = records_by_id(records)
    stats = dict(lifted=[], flat=[], windows={}, fails={})
    started = time.perf_counter()
    entries = list(ctx.pair_dirs) if order is None else list(order)
    for entry in entries:
        preferred = int(ew_layer) if entry['key'] == 'EW' else int(ns_layer)
        layers = [preferred]
        if not strict:
            layers += [layer for layer in (2, 3, 4, 5, 6, 7)
                       if layer != preferred]
        chosen = None
        for layer in layers:
            tried = 0
            for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer,
                                              symmetric_only=True):
                tried += 1
                if tried > max_candidates_per_layer:
                    break
                routes = ctx.lift_pair(entry, layer, a_in, a_out)
                if routes is None:
                    continue
                if any(S.structure_errors(route) for route in routes):
                    continue
                if any(world.check_route(route) for route in routes):
                    continue
                if C.pairwise_violations(world, routes[0], routes[1]):
                    continue
                chosen = (layer, a_in, a_out, routes)
                break
            if chosen:
                break
            if time.perf_counter() - started > time_limit:
                break
        if chosen is None:
            stats['flat'].append(entry['pair_id'])
            stats['fails'][entry['pair_id']] = 'no_window'
            for rid in entry['rids']:
                flat = ctx.flat(rid)
                world.add_route(flat)
                current[rid] = flat
            continue
        layer, a_in, a_out, routes = chosen
        for route in routes:
            world.add_route(route)
            current[int(route['route_id'])] = route
        stats['lifted'].append(entry['pair_id'])
        stats['windows'][entry['pair_id']] = dict(
            layer=int(layer), a_in=float(a_in), a_out=float(a_out))
    log(f'[lift_z1_pairs] EW-L{ew_layer} NS-L{ns_layer} strict={strict}: '
        f'lifted {len(stats["lifted"])}/{len(entries)} '
        f'flat={len(stats["flat"])} in {time.perf_counter()-started:.1f}s')
    return list(current.values()), stats


def summarise(ctx, records, label, log=print):
    analysis = C.audit(records, ctx)
    stats = C.bar(records)
    usage = C.layer_usage(records, ctx)
    log(f'[{label}] unique={analysis["n_unique_pairs"]} '
        f'z1={analysis["z1_pairs"]} z2={analysis["z2_pairs"]} '
        f'high={analysis["high_pairs"]} adj={analysis["adjacent_related_events"]} '
        f'line={analysis["adjacent_line_events"]} '
        f'arc={analysis["adjacent_arc_events"]} '
        f'trans={stats["transitions"]} h={stats["fabrication_hours"]:.4f} '
        f'L5={usage[5]["routes"]} L6={usage[6]["routes"]} '
        f'L7={usage[7]["routes"]}')
    return analysis, stats, usage


def layer_by_height(analysis):
    return {z: info['pairs'] for z, info in sorted(analysis['per_height'].items())}
