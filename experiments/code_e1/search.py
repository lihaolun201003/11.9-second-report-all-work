# -*- coding: utf-8 -*-
"""E1 candidate search: S-bend windows for Z1/Z2 routes and blocker capture.

Windows are restricted to the *structurally valid* straight intervals of the
existing 2D chain (the frozen S-bend template can only start a transition inside
a straight run that is long enough for its XY footprint), and every candidate is
checked with ``World.check_structure`` before the clearance world is consulted.
"""
from __future__ import annotations

import time

from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from four_side_1024.v3c4.lift_cross import (
    transition_geometry, _straight_start_windows)
from four_side_1024.l3d.world import World
from . import core as C

MIN_TRAVEL = 5.0
PORT_MARGIN = 1.2
SEGMENT_MARGIN = 0.25

# fine symmetric grid (mm from port); dense where the Z2 corridor gaps are
A_GRID = [1.2, 1.6, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0, 4.5, 5.0, 5.5, 6.0, 6.6,
          7.2, 7.8, 8.4, 9.0, 9.6, 10.4, 11.2, 12.0, 13.0, 14.0, 15.0, 16.0,
          17.0, 18.5, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0, 34.0, 36.0,
          38.0, 40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0, 54.0, 55.0, 56.0,
          57.0, 58.0, 59.0, 60.0, 61.0, 62.0, 63.0, 64.0, 65.0, 66.0, 67.0,
          68.0, 70.0, 72.0, 74.0, 76.0, 80.0, 85.0, 90.0, 95.0]
A_COARSE = [1.2, 2.4, 4.0, 6.0, 9.0, 13.0, 18.5, 24.0, 30.0, 38.0, 48.0,
            58.0, 68.0, 80.0]


def footprint(ctx, rid, layer):
    """XY footprint of the S rise from the route's base z to ``layer``."""
    z = C.LAYER_Z[int(layer)]
    return float(transition_geometry(z - ctx.base_z(rid))['footprint_mm'])


def rise_windows(ctx, rid, layer):
    """Structurally valid rise-start intervals for this route/layer."""
    f = footprint(ctx, rid, layer)
    windows = _straight_start_windows(ctx.chain(rid), f, ctx.total(rid))
    return [(round(lo, 6), round(hi, 6)) for lo, hi in windows]


def max_a(ctx, rid, layer):
    total = ctx.total(rid)
    f = footprint(ctx, rid, layer)
    return max(PORT_MARGIN, min((total - 2.0 * f - MIN_TRAVEL) / 2.0, total))


def _positions(windows, values):
    out = set()
    for lo, hi in windows:
        out.add(round(lo, 4))
        out.add(round(hi, 4))
        for value in values:
            if lo - 1e-9 <= value <= hi + 1e-9:
                out.add(round(value, 4))
    return sorted(out)


def _inside(windows, value):
    return any(lo - 1e-9 <= value <= hi + 1e-9 for lo, hi in windows)


def window_grid(ctx, rid, layer, symmetric_only=False, fine=A_GRID,
                coarse=A_COARSE):
    """(a_in, a_out) candidates ordered by total base-stub length."""
    total = ctx.total(rid)
    f = footprint(ctx, rid, layer)
    windows = rise_windows(ctx, rid, layer)
    if not windows:
        return []
    rise_positions = _positions(windows, fine)
    fall_positions = _positions(windows, fine)
    combos = {}
    for position in rise_positions:
        fall_start = total - position - f
        if fall_start < position + f + MIN_TRAVEL - 1e-9:
            continue
        if not _inside(windows, fall_start):
            continue
        key = (round(position, 4), round(position, 4))
        combos[key] = position + position
    if not symmetric_only:
        rise_coarse = _positions(windows, coarse)
        fall_coarse = _positions(windows, coarse)
        for position in rise_coarse:
            for fall_start in fall_coarse:
                if fall_start < position + f + MIN_TRAVEL - 1e-9:
                    continue
                a_out = total - fall_start - f
                if a_out < PORT_MARGIN - 1e-9:
                    continue
                key = (round(position, 4), round(a_out, 4))
                if key in combos:
                    continue
                combos[key] = position + a_out + abs(position - a_out) * 0.1
    return sorted(combos, key=lambda item: combos[item])


def build_single(ctx, rid, layer, a_in, a_out):
    return ctx.lift(int(rid), int(layer), float(a_in), float(a_out))


def structure_errors(route):
    return World.check_structure(route)


def evaluate_single(ctx, world, rid, layer, a_in, a_out, collect=True):
    """Build + check one lifted route; returns a candidate record and the route."""
    record = dict(route_id=int(rid), pair_id='', mode='single',
                  layer=int(layer), a_in=float(a_in), a_out=float(a_out))
    entry = ctx.pairs_by_rid.get(int(rid))
    if entry is not None:
        record['pair_id'] = entry['pair_id']
    route = build_single(ctx, rid, layer, a_in, a_out)
    if route is None:
        record.update(built=False, legal=False, failure='curvature_or_space',
                      blockers=[], classes=set(), violations=[])
        return record, None
    errors = structure_errors(route)
    if errors:
        record.update(built=False, legal=False, failure='curvature_or_space',
                      blockers=[], classes=set(), violations=[],
                      structure_errors=errors[:4])
        return record, route
    violations = world.check_route(route)
    record['built'] = True
    record['violations'] = violations
    if not violations:
        record.update(legal=True, failure='ok', blockers=[], classes=set())
        return record, route
    if not collect:
        record.update(legal=False, failure='conflict', blockers=[], classes=set(),
                      violations=violations)
        return record, route
    full = C.collect_violations(world, route)
    classes = C.violation_classes(ctx, full)
    record.update(legal=False, classes=classes,
                  failure=C.failure_type(classes), blockers=C.blocker_rows(ctx, rid, full),
                  violations=full)
    return record, route


def evaluate_pair_together(ctx, world, entry, layer, a_in, a_out, collect=True):
    """Build both members of a C2 pair with the same window; joint legality."""
    record = dict(route_id=int(entry['rids'][0]), pair_id=entry['pair_id'],
                  mode='pair', layer=int(layer), a_in=float(a_in),
                  a_out=float(a_out), route_ids=list(entry['rids']))
    routes = ctx.lift_pair(entry, layer, a_in, a_out)
    if routes is None:
        record.update(built=False, legal=False, failure='curvature_or_space',
                      blockers=[], classes=set(), violations=[])
        return record, None
    for route in routes:
        errors = structure_errors(route)
        if errors:
            record.update(built=False, legal=False,
                          failure='curvature_or_space', blockers=[],
                          classes=set(), violations=[],
                          structure_errors=errors[:4])
            return record, routes
    record['built'] = True
    violations = []
    for index, route in enumerate(routes):
        violations.extend(world.check_route(route))
        if index == 1:
            violations.extend(C.pairwise_violations(world, routes[0], routes[1]))
    if not violations:
        record.update(legal=True, failure='ok', blockers=[], classes=set(),
                      violations=[])
        return record, routes
    if not collect:
        record.update(legal=False, failure='conflict', blockers=[], classes=set(),
                      violations=violations)
        return record, routes
    full = []
    for route in routes:
        full.extend(C.collect_violations(world, route))
    full.extend(C.pairwise_violations(world, routes[0], routes[1]))
    classes = C.violation_classes(ctx, full)
    record.update(legal=False, classes=classes, failure=C.failure_type(classes),
                  blockers=C.blocker_rows(ctx, record['route_id'], full),
                  violations=full)
    return record, routes


def evaluate_independent_pair(ctx, world, entry, window0, window1, collect=True):
    """Each member of the pair gets its own (layer, a_in, a_out)."""
    (layer0, a_in0, a_out0) = window0
    (layer1, a_in1, a_out1) = window1
    record = dict(route_id=int(entry['rids'][0]), pair_id=entry['pair_id'],
                  mode='pair_independent', layer=int(layer0),
                  a_in=float(a_in0), a_out=float(a_out0),
                  route_ids=list(entry['rids']),
                  member_windows=[window0, window1])
    routes = [build_single(ctx, entry['rids'][0], layer0, a_in0, a_out0),
              build_single(ctx, entry['rids'][1], layer1, a_in1, a_out1)]
    if any(route is None for route in routes):
        record.update(built=False, legal=False, failure='curvature_or_space',
                      blockers=[], classes=set(), violations=[])
        return record, None
    for route in routes:
        errors = structure_errors(route)
        if errors:
            record.update(built=False, legal=False,
                          failure='curvature_or_space', blockers=[],
                          classes=set(), violations=[])
            return record, routes
    record['built'] = True
    violations = []
    for index, route in enumerate(routes):
        violations.extend(world.check_route(route))
        if index == 1:
            violations.extend(C.pairwise_violations(world, routes[0], routes[1]))
    if not violations:
        record.update(legal=True, failure='ok', blockers=[], classes=set(),
                      violations=[])
        return record, routes
    full = list(violations)
    if collect:
        full = []
        for route in routes:
            full.extend(C.collect_violations(world, route))
        full.extend(C.pairwise_violations(world, routes[0], routes[1]))
    classes = C.violation_classes(ctx, full)
    record.update(legal=False, classes=classes,
                  failure=C.failure_type(classes),
                  blockers=C.blocker_rows(ctx, entry['rids'][0], full),
                  violations=full)
    return record, routes


def search_route(ctx, world, rid, layers=C.LAYERS, symmetric_only=False,
                 collect_failures=True, collect_limit=2, max_candidates=None):
    """Window search for one route against ``world``."""
    records = []
    legal = []
    for layer in layers:
        for a_in, a_out in window_grid(ctx, rid, layer,
                                       symmetric_only=symmetric_only):
            record, route = evaluate_single(
                ctx, world, rid, layer, a_in, a_out,
                collect=collect_failures and len(legal) < collect_limit)
            records.append(record)
            if record['legal']:
                legal.append((record, route))
                if len(legal) >= collect_limit:
                    break
            if max_candidates and len(records) >= max_candidates:
                break
        if len(legal) >= collect_limit:
            break
    return dict(records=records, legal=legal)


def search_pair_together(ctx, world, entry, layers=C.LAYERS,
                         symmetric_only=False, collect_limit=2):
    records = []
    legal = []
    for layer in layers:
        for a_in, a_out in window_grid(ctx, entry['rids'][0], layer,
                                       symmetric_only=symmetric_only):
            record, routes = evaluate_pair_together(
                ctx, world, entry, layer, a_in, a_out, collect=True)
            records.append(record)
            if record['legal']:
                legal.append((record, routes))
                if len(legal) >= collect_limit:
                    break
        if len(legal) >= collect_limit:
            break
    return dict(records=records, legal=legal)


def search_pair_independent(ctx, world, entry, layers=C.LAYERS,
                            collect_limit=2, per_route_limit=3):
    """Search each member independently, then combine legal combinations."""
    per_route = {}
    for rid in entry['rids']:
        found = []
        for layer in layers:
            for a_in, a_out in window_grid(ctx, rid, layer):
                route = build_single(ctx, rid, layer, a_in, a_out)
                if route is None or structure_errors(route):
                    continue
                if world.check_route(route):
                    continue
                found.append(((layer, a_in, a_out), route))
                if len(found) >= per_route_limit:
                    break
            if len(found) >= per_route_limit:
                break
        per_route[rid] = found
    records = []
    legal = []
    for window0, route0 in per_route[entry['rids'][0]]:
        for window1, route1 in per_route[entry['rids'][1]]:
            violations = C.pairwise_violations(world, route0, route1)
            if violations:
                continue
            records.append(dict(route_id=int(entry['rids'][0]),
                                pair_id=entry['pair_id'],
                                mode='pair_independent',
                                member_windows=[window0, window1],
                                legal=True, built=True, failure='ok',
                                blockers=[], classes=set(),
                                layer=int(window0[0]), a_in=window0[1],
                                a_out=window0[2],
                                route_ids=list(entry['rids'])))
            legal.append((records[-1], [route0, route1]))
    if not records:
        records.append(dict(route_id=int(entry['rids'][0]),
                            pair_id=entry['pair_id'], mode='pair_independent',
                            legal=False, built=False,
                            failure='curvature_or_space', layer=0,
                            a_in=0.0, a_out=0.0,
                            blockers=[], classes=set()))
    return dict(records=records, legal=legal, per_route=per_route)


# ---------------------------------------------------------------------------
# Z2 reroute candidates (E1-C)
# ---------------------------------------------------------------------------
def z2_layer_options(ctx, rid, layers=(2, 3, 4, 5, 6, 7), max_options=8,
                     symmetric_first=True):
    """Geometrically constructible lifted alternatives for one Z2 route."""
    options = []
    seen = set()
    for layer in layers:
        count = 0
        for a_in, a_out in window_grid(ctx, rid, layer,
                                       symmetric_only=symmetric_first):
            route = build_single(ctx, rid, layer, a_in, a_out)
            if route is None or structure_errors(route):
                continue
            key = (int(layer), round(a_in, 3), round(a_out, 3))
            if key in seen:
                continue
            seen.add(key)
            options.append(dict(route_id=int(rid), layer=int(layer),
                                a_in=float(a_in), a_out=float(a_out),
                                route=route))
            count += 1
            if len(options) >= max_options:
                return options
            if count >= 3:
                break
    return options


def candidate_csv_row(ctx, record, contribution):
    blockers = record.get('blockers') or []
    blocker_ids = ';'.join(str(item['route_id']) for item in blockers)
    planes = ';'.join(sorted({item['plane'] for item in blockers}))
    cats = ';'.join(sorted({item['category'] for item in blockers}))
    labels = ';'.join(sorted({item['label'] for item in blockers}))
    points = ';'.join(
        (f"{item['route_id']}@{item['point'][0]:.3f},{item['point'][1]:.3f},"
         f"{item['point'][2]:.3f}") if item.get('point')
        else f"{item['route_id']}@same_plane"
        for item in blockers[:12])
    entry = ctx.pairs_by_rid.get(int(record['route_id']))
    window = record.get('member_windows')
    if window:
        window_text = '|'.join(
            f'L{w[0]}:a_in={w[1]:.2f},a_out={w[2]:.2f}' for w in window)
    else:
        window_text = (f"L{record.get('layer')}:a_in={record.get('a_in', 0):.2f},"
                       f"a_out={record.get('a_out', 0):.2f}")
    route_ids = record.get('route_ids') or [record['route_id']]
    return dict(
        route_id=record['route_id'],
        route_ids=';'.join(str(r) for r in route_ids),
        pair_id=entry['pair_id'] if entry else '',
        original_relation=ctx.manifest[int(route_ids[0])]['relation'],
        original_direction=ctx.manifest[int(route_ids[0])].get('pair', ''),
        lift_mode=record.get('mode', ''),
        target_layer=record.get('layer'),
        rise_fall_window=window_text,
        build_ok=bool(record.get('built')),
        geometry_legal=bool(record.get('legal')),
        failure_type=C.FAIL_LABEL.get(record.get('failure', ''),
                                      record.get('failure', '')),
        n_blockers=len(blockers),
        blocker_route_ids=blocker_ids,
        blocker_planes=planes,
        blocker_categories=cats,
        blocker_labels=labels,
        conflict_positions=points,
        original_crossing_contribution=int(contribution),
    )
