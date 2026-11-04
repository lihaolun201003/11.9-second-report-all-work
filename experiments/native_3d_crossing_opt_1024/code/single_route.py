# -*- coding: utf-8 -*-
"""Experiment A: single-route mid-body layer change in the real 1024-route space."""
from __future__ import annotations

import copy
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from ...fsd25d import path3d as P
from ...l3d.world import World
from .. import common as C
from ..reheight21 import model as M
from . import common as N
from . import crossing_cache as CC
from . import route_model as RM
from . import transition as T


# ------------------------------------------------------------------ positions
def route_body_chain(route):
    """``(body_part_index, primitives)`` of the single baseline body flat."""
    flats = N.body_flats(route)
    if not flats:
        raise ValueError('route %s has no body flat' % route.get('route_id'))
    if len(flats) > 1 and route.get('native_3d'):
        # choose the longest body flat
        index, part = max(flats, key=lambda item: N.part_length(item[1]))
        return index, [dict(prim) for prim in part['primitives']]
    index, part = max(flats, key=lambda item: N.part_length(item[1]))
    return index, [dict(prim) for prim in part['primitives']]


def _project_s(prims, point, step=0.25):
    """Arc length of the nearest path point to ``point`` (approximate)."""
    total = P.path_length(prims)
    best_s = 0.0
    best = float('inf')
    s = 0.0
    while s <= total + 1e-9:
        p, _t = P.path_point_at(prims, s)
        distance = math.hypot(p[0] - point[0], p[1] - point[1])
        if distance < best:
            best = distance
            best_s = s
        s += step
    p, _t = P.path_point_at(prims, total)
    distance = math.hypot(p[0] - point[0], p[1] - point[1])
    if distance < best:
        best = distance
        best_s = total
    return best_s, best


def crossing_positions(route, events):
    """``[{s_mm, partner, x, y, z, angle}]`` along the route's body path."""
    index, prims = route_body_chain(route)
    rid = int(route['route_id'])
    positions = []
    for event in events:
        route_a = int(event['route_a'])
        route_b = int(event['route_b'])
        if rid not in (route_a, route_b):
            continue
        partner = route_b if route_a == rid else route_a
        point = (float(event['x_mm']), float(event['y_mm']))
        s, distance = _project_s(prims, point)
        positions.append(dict(s_mm=round(s, 4), partner=partner,
                              x_mm=point[0], y_mm=point[1],
                              z_mm=float(event['z_mm']),
                              angle_deg=float(event.get('angle_deg') or 0.0),
                              projection_error_mm=round(distance, 5)))
    positions.sort(key=lambda item: item['s_mm'])
    return positions


def cluster_positions(positions, gap_mm=10.0, min_count=1):
    """Group crossings into consecutive clusters along the path."""
    clusters = []
    for item in positions:
        if clusters and item['s_mm'] - clusters[-1]['s_end_mm'] <= gap_mm:
            cluster = clusters[-1]
            cluster['s_end_mm'] = item['s_mm']
            cluster['items'].append(item)
            cluster['count'] += 1
        else:
            clusters.append(dict(s_start_mm=item['s_mm'],
                                 s_end_mm=item['s_mm'],
                                 items=[item], count=1))
    return [cluster for cluster in clusters if cluster['count'] >= min_count]


# ------------------------------------------------------------------ candidates
def _shadow_chain(prims, s_start, s_end):
    """Line chain covering ``[s_start, s_end]`` (clipped to the body path)."""
    total = P.path_length(prims)
    s_start = max(0.0, min(total, float(s_start)))
    s_end = max(0.0, min(total, float(s_end)))
    if s_end - s_start <= 1e-9:
        return []
    _head, rest = P.path_split(prims, s_start)
    if not rest:
        return []
    segment, _tail = P.path_split(rest, s_end - s_start)
    return [dict(prim) for prim in segment]


def interval_candidates(prims, cluster, target_z, z_from, env=None,
                        exclude_route=None, margin_mm=0.5, min_middle=None,
                        max_shift_mm=25.0):
    """Generate feasible ``(s0, s1)`` candidates for one cluster / target height.

    Returns a list of dicts with ``s0/s1/footprint/middle/shadow_ok/reasons``.
    """
    min_middle = float(N.MIN_MIDDLE_MM if min_middle is None else min_middle)
    footprint = T.transition_footprint(float(target_z) - float(z_from))
    total = P.path_length(prims)
    shadow = float(N.SHADOW_MM)
    first = cluster['s_start_mm']
    last = cluster['s_end_mm']
    needed = 2.0 * footprint + min_middle
    candidates = []
    base_extra = footprint + shadow + margin_mm
    for extra_before in (base_extra, base_extra + 1.5, base_extra + 3.0,
                         base_extra + 6.0):
        for extra_after in (base_extra, base_extra + 1.5, base_extra + 3.0,
                            base_extra + 6.0):
            s0 = first - extra_before
            s1 = last + extra_after
            # extend symmetrically when the cluster is too short for the S-curves
            if s1 - s0 < needed:
                grow = 0.5 * (needed - (s1 - s0)) + 0.5
                s0 -= grow
                s1 += grow
            if s0 < 0.5 or s1 > total - 0.5:
                continue
            span = T.same_straight_run(prims, s0, s1)
            if span is None:
                continue
            entry = dict(s0=float(s0), s1=float(s1),
                         footprint=float(footprint),
                         middle=float((s1 - s0) - 2.0 * footprint),
                         extra_before=float(extra_before),
                         extra_after=float(extra_after),
                         reasons=[])
            if entry['middle'] < min_middle - 1e-9:
                entry['reasons'].append('middle_too_short')
            if env is not None:
                entry['shadow'] = shadow_report(env, prims, entry, z_from,
                                                float(target_z), footprint,
                                                exclude_route)
                if not entry['shadow']['ok']:
                    entry['reasons'].append('shadow_crossing')
            entry['feasible'] = not entry['reasons']
            candidates.append(entry)
    # de-duplicate
    unique = {}
    for entry in candidates:
        key = (round(entry['s0'], 3), round(entry['s1'], 3))
        unique[key] = entry
    return list(unique.values())


def shadow_report(env, prims, interval, z_from, z_to, footprint,
                  exclude_route=None, margin_mm=0.0):
    """Check the S-curve footprints against every physical plane they touch.

    A two-arc R15 S-curve stays within ``dz`` of the plane it leaves and within
    ``dz`` of the plane it lands on, so with the 50 um routing pitch the whole
    transition footprint must be free of other routes' flats at *both* planes
    (the true 3D distance under the footprint is at most ``dz``).  For
    ``dz >= 0.10`` the curve also passes exactly through every intermediate
    routing height, so those planes must be crossing-free under the footprint
    as well.
    """
    s0 = interval['s0']
    s1 = interval['s1']
    footprint = float(footprint)
    checks = []
    planes = [(z_from, s0, s0 + footprint, 'up_source'),
              (z_to, s0, s0 + footprint, 'up_target'),
              (z_from, s1 - footprint, s1, 'down_source'),
              (z_to, s1 - footprint, s1, 'down_target')]
    low, high = sorted((float(z_from), float(z_to)))
    for plane_id in N.MOVABLE_PLANES:
        z_value = N.z_of_plane(plane_id)
        if low + 1e-9 < z_value < high - 1e-9:
            planes.append((z_value, s0, s0 + footprint, 'up_intermediate'))
            planes.append((z_value, s1 - footprint, s1, 'down_intermediate'))
    # the transition stays within dz of both end planes, so the routing planes
    # one 50 um pitch beyond each end are also inside the conservative 3D margin
    heights = sorted(N.all_heights())
    for end_z in (float(z_from), float(z_to)):
        for z_value in heights:
            if abs(z_value - end_z) < 1e-9:
                continue
            if abs(abs(z_value - end_z) - 0.05) > 1e-6:
                continue
            planes.append((z_value, s0, s0 + footprint, 'up_beyond'))
            planes.append((z_value, s1 - footprint, s1, 'down_beyond'))
    for z_key, start, end, label in planes:
        chain = _shadow_chain(prims, start, end)
        if not chain:
            continue
        events, _pairs, ok, reasons = env.plane_cache.crossings_of(
            round(float(z_key), 9), [chain], exclude_route=exclude_route)
        checks.append(dict(zone=label, z_mm=float(z_key),
                           crossings=int(events), d56_ok=bool(ok),
                           reasons=reasons[:2]))
    # A crossing under the footprint is a guaranteed 3D clearance violation
    # (the S-curve is within dz <= 50 um of the plane there); near misses that
    # do not cross are left to the exact local 3D world guard.
    bad = [item for item in checks if item['crossings'] > 0]
    return dict(ok=not bad, checks=checks, bad=bad)


# ------------------------------------------------------------------ world help
def world_without(env, route_id, clearance=float(N.MIN_3D_CLEARANCE)):
    """Fresh 3D world holding every route except ``route_id``."""
    world = World(M.layer_stack(), clearance=clearance)
    rid = int(route_id)
    for other_id in sorted(env.routes):
        if other_id == rid:
            continue
        world.add_route(env.routes[other_id])
    return world


def candidate_world_errors(world, route, clearance=float(N.MIN_3D_CLEARANCE)):
    errors = []
    for part in route.get('parts') or ():
        if part['kind'] != 'flat':
            continue
        evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
        if evaluation is not None and not evaluation.valid:
            errors.append(dict(kind='flat_same_plane_conflict',
                               z_mm=float(part['z_mm']),
                               blockers=list(getattr(evaluation, 'blockers',
                                                     []) or [])[:8],
                               reason=str(getattr(evaluation, 'reason', ''))))
            return errors
    violations = world.check_route(route)
    for item in violations:
        errors.append(dict(item))
    return errors


# ------------------------------------------------------------------ evaluate
def evaluate_candidate(env, route_id, candidate_route, world=None):
    """Fast crossing delta + full 3D validity of one candidate route."""
    structural = RM.structure_errors(candidate_route)
    metadata = RM.route_metadata_errors(candidate_route)
    detail = dict(route_id=int(route_id),
                  structural=structural[:6], metadata=metadata[:6],
                  d56_ok=True, delta=None, world_errors=[], feasible=False,
                  reasons=[])
    if structural:
        detail['reasons'].append('structure')
        return detail
    if metadata:
        detail['reasons'].append('metadata')
        return detail
    fast = env.evaluate_candidate(route_id, candidate_route)
    detail['delta'] = int(fast['delta'])
    detail['per_plane'] = fast['per_plane']
    detail['d56_ok'] = bool(fast['d56_ok'])
    if not fast['d56_ok']:
        detail['reasons'].append('d56')
        detail['d56_problems'] = fast['problems']
        return detail
    if world is None:
        world = world_without(env, route_id)
    errors = candidate_world_errors(world, candidate_route)
    if errors:
        detail['reasons'].append('world')
        detail['world_errors'] = errors[:4]
        return detail
    detail['feasible'] = True
    return detail


# ------------------------------------------------------------------ search
def scan_route(env, route_id, events, world=None, max_clusters=4,
               max_target_heights=4, gap_mm=10.0, log=None, deadline=None):
    """Enumerate excursions for one route (fast screening, no acceptance)."""
    route = env.routes[int(route_id)]
    body_index, prims = route_body_chain(route)
    z_from = float(route['parts'][body_index]['z_mm'])
    positions = crossing_positions(route, events)
    clusters = cluster_positions(positions, gap_mm=gap_mm)
    clusters.sort(key=lambda item: -item['count'])
    clusters = clusters[:max_clusters]
    target_planes = [pid for pid in N.sorted_by_abs_dz(z_from)
                     if abs(N.z_of_plane(pid) - z_from) > 1e-9][:max_target_heights]
    results = []
    if world is None:
        world = world_without(env, route_id)
    for cluster in clusters:
        for plane_id in target_planes:
            target_z = N.z_of_plane(plane_id)
            for interval in interval_candidates(prims, cluster, target_z, z_from,
                                                env=env,
                                                exclude_route=route_id):
                if not interval['feasible']:
                    continue
                try:
                    built = RM.duck_out(route, body_index,
                                        interval['s0'], interval['s1'],
                                        target_z)
                except ValueError as error:
                    results.append(dict(route_id=int(route_id),
                                        target_plane=plane_id,
                                        target_z=target_z,
                                        s0=interval['s0'], s1=interval['s1'],
                                        feasible=False,
                                        reasons=['build:%s' % error]))
                    continue
                detail = evaluate_candidate(env, route_id, built['route'],
                                            world=world)
                detail.update(cluster_count=int(cluster['count']),
                              cluster_start=float(cluster['s_start_mm']),
                              cluster_end=float(cluster['s_end_mm']),
                              target_plane=int(plane_id),
                              target_z=float(target_z),
                              from_z=float(z_from),
                              s0=interval['s0'], s1=interval['s1'],
                              footprint_mm=built['footprint_mm'],
                              middle_mm=built['middle_mm'],
                              excursion=built['excursion'])
                detail['route'] = built['route']
                results.append(detail)
                if deadline is not None and time.time() > deadline:
                    return results
    return results


def crossing_improvement(results):
    return [item for item in results
            if item.get('feasible') and item.get('delta') is not None
            and int(item['delta']) < 0]


# ------------------------------------------------------------------ reporting
def summary_line(item):
    return ('route %d: %s -> %s (z %.3f -> %.3f) delta=%s feasible=%s'
            % (item.get('route_id'), item.get('from_z'), item.get('target_z'),
               float(item.get('from_z') or 0.0), float(item.get('target_z') or 0.0),
               item.get('delta'), item.get('feasible')))
