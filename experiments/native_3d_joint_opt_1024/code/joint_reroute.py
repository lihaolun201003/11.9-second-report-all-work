# -*- coding: utf-8 -*-
"""Experiment D: multi-route joint reroute / make-way for high-gain excursions.

Mechanism
---------
1. Build the target route's candidate mid-body excursion.
2. Find the **true-3D blockers** iteratively: check the candidate against the
   routes that can possibly matter (a local world built from every route whose
   2D bounding box overlaps the candidate), collect the blocking route ids,
   exclude them, re-check until clean (the clearance world reports only a few
   violations per pass, so the loop is needed).
3. If any blocker is a frozen manual U route -> reject (recorded reason).
4. Otherwise re-insert every blocker after giving it a **make-way excursion**:
   the blocker ducks away from the conflict point through its own exact R15
   S-curves (straight or arc-spanning excursion) at another height.  A blocker
   that cannot be re-inserted legally causes a clean rollback.
5. The changed routes are re-checked in a fresh world that holds all other 1020
   routes, and the whole layout gets an **exact** global crossing recount; the
   change is accepted only if the exact total strictly improves.

Everything is transactional: the caller's route dict is never mutated.
"""
from __future__ import annotations

import copy
import math
import time
from collections import Counter, OrderedDict

from ...fsd25d import path3d as P
from ...l3d.world import World
from ..reheight21 import model as M
from . import common as N
from . import crossing_cache as CC
from . import excursion2 as E2
from . import guard as G
from . import route_model as RM
from . import single_route as S
from . import transition as T

MAX_JOINT_ROUTES = 5
MAX_BLOCKER_ROUNDS = 8


# ------------------------------------------------------------------ helpers
def _bbox_of(route):
    return G.route_bbox(route)


def _overlap(first, second, margin=0.0):
    if first is None or second is None:
        return False
    return not (first[2] + margin < second[0] or second[2] + margin < first[0]
                or first[3] + margin < second[1] or second[3] + margin < first[1])


def _expand(bbox, margin):
    return (bbox[0] - margin, bbox[1] - margin,
            bbox[2] + margin, bbox[3] + margin)


def local_check(routes, bbox_cache, candidate, exclude_ids=(), margin=0.30,
                clearance=float(N.MIN_3D_CLEARANCE)):
    """Exact 3D + same-plane D56 check against every route that can matter."""
    rid = int(candidate['route_id'])
    bbox = _bbox_of(candidate)
    probe = _expand(bbox, margin)
    exclude = set(int(item) for item in exclude_ids) | {rid}
    boxes = getattr(bbox_cache, 'boxes', bbox_cache)
    selected = [other for other, box in boxes.items()
                if other not in exclude and _overlap(box, probe, 0.0)]
    world = World(M.layer_stack(), clearance=clearance)
    for other in sorted(selected):
        world.add_route(routes[other])
    return world.check_route(candidate), len(selected)


def collect_blockers(routes, bbox_cache, target_route_id, candidate_route,
                     manual, max_rounds=MAX_BLOCKER_ROUNDS):
    """Iteratively find every true-3D blocker of ``candidate_route``."""
    manual = manual or set()
    excluded = {int(target_route_id)}
    blockers = []
    for _round in range(int(max_rounds)):
        violations, _near = local_check(routes, bbox_cache, candidate_route,
                                        exclude_ids=excluded)
        if not violations:
            return dict(blockers=blockers, clean=True, reason='clean')
        found = []
        for violation in violations:
            for key in ('other_route',):
                other = violation.get(key)
                if other is not None:
                    found.append(int(other))
            for blocker in violation.get('blockers') or ():
                try:
                    value = int(blocker)
                except (TypeError, ValueError):
                    continue
                # the plane world encodes primitives as route_id*1000 + index
                if value >= 1000:
                    value = value // 1000
                found.append(value)
        found = [rid for rid in OrderedDict.fromkeys(found)
                 if rid not in excluded]
        if not found:
            own_kinds = ('flat_cross_plane_too_close', 'self_clearance',
                         'structure', 'layer_pitch')
            kinds = {item.get('kind') for item in violations}
            reason = ('own_geometry' if kinds <= set(own_kinds)
                      else 'unattributed_violation')
            return dict(blockers=blockers, clean=False, reason=reason,
                        violations=violations[:4])
        manual_found = [rid for rid in found if rid in manual]
        excluded.update(found)
        for rid in found:
            if rid not in {item['route_id'] for item in blockers}:
                blockers.append(dict(route_id=rid))
        if manual_found:
            return dict(blockers=blockers, clean=False,
                        reason='manual_blocker', manual_blockers=manual_found)
        if len(blockers) > MAX_JOINT_ROUTES:
            return dict(blockers=blockers, clean=False,
                        reason='too_many_blockers', blocker_count=len(blockers))
    return dict(blockers=blockers, clean=False, reason='blocker_round_limit')


def _conflict_centre(route, violations):
    """Arc-length position on the route body chain nearest to a conflict point."""
    body_index, prims = S.route_body_chain(route)
    total = float(P.path_length(prims))
    points = []
    for violation in violations or ():
        point = violation.get('point')
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    if not points:
        return body_index, total * 0.5
    best_s = total * 0.5
    best = float('inf')
    for point in points:
        s, distance = S._project_s(prims, point, step=0.5)
        if distance < best:
            best = distance
            best_s = s
    return body_index, best_s


# ------------------------------------------------------------------ make-way
def make_way_candidates(route, body_index, centre_s, z_from, target_planes):
    """Candidate make-way geometries (exact R15 excursions) for one blocker."""
    prims = [dict(prim) for prim in route['parts'][body_index]['primitives']]
    total = float(P.path_length(prims))
    options = []
    for target_plane in target_planes:
        target_z = N.z_of_plane(target_plane)
        footprint = T.transition_footprint(target_z - z_from)
        for half in (footprint + 3.0, footprint + 12.0):
            s0 = centre_s - half
            s1 = centre_s + half
            if s0 < 0.5 or s1 > total - 0.5:
                continue
            try:
                built = E2.insert_excursion_general(route, body_index, s0, s1,
                                                    target_z)
            except ValueError:
                continue
            options.append(dict(route=built['route'], target_z=target_z,
                                s0=s0, s1=s1,
                                footprint_mm=built['footprint_mm'],
                                contains_arc=built['contains_arc']))
    return options


def make_way_one(routes, bbox_cache, blocker_id, conflict_points, manual,
                 current_changes, target_planes_per_blocker=3):
    """Give one blocker a legal alternative geometry (or fail)."""
    blocker_id = int(blocker_id)
    base_route = routes[blocker_id]
    body_index, centre_s = _conflict_centre(base_route, conflict_points)
    z_from = float(base_route['parts'][body_index]['z_mm'])
    planes = [pid for pid in N.sorted_by_abs_dz(z_from)
              if abs(N.z_of_plane(pid) - z_from) > 1e-9][:int(
                  target_planes_per_blocker)]
    options = make_way_candidates(base_route, body_index, centre_s, z_from,
                                  planes)
    tried = 0
    for option in options:
        candidate = option['route']
        structural = RM.structure_errors(candidate)
        if structural:
            continue
        tried += 1
        violations, _near = local_check(routes, bbox_cache, candidate,
                                        exclude_ids=set(current_changes)
                                        | {blocker_id})
        if violations:
            continue
        return dict(route=candidate, target_z=option['target_z'],
                    s0=option['s0'], s1=option['s1'], tried=tried,
                    footprint_mm=option['footprint_mm'],
                    contains_arc=option['contains_arc'])
    return dict(route=None, reason='no_legal_make_way', tried=tried)


# ------------------------------------------------------------------ joint
def joint_try(env, bbox_cache, target_route_id, candidate_route, manual,
              max_joint=3, log=None, validation_mode='changed', collection=None):
    """Realise ``candidate_route`` by making way for up to ``max_joint`` blockers.

    Parameters
    ----------
    env : crossing_cache.NativeRouteSet of the current layout
    bbox_cache : guard.BboxCache of the current layout
    target_route_id : route that should receive the excursion
    candidate_route : the already-built target route (with the excursion)
    manual : set of frozen manual route ids
    max_joint : maximum number of movable blockers to reroute (1..5)

    Returns a report dict; when accepted it also carries ``routes`` (the full
    new route dict) and ``exact_total``.
    """
    started = time.time()
    target_route_id = int(target_route_id)
    original_total = int(env.total())
    routes = {rid: route for rid, route in env.routes.items()}
    report = dict(target_route_id=target_route_id, accepted=False,
                  blockers=[], movable_blockers=[], manual_blockers=[],
                  joint_routes=[], reason='', before_total=original_total,
                  after_total=None, net=0, seconds=0.0)
    if collection is None:
        collection = collect_blockers(routes, bbox_cache, target_route_id,
                                      candidate_route, manual)
    report['blockers'] = collection['blockers']
    if not collection['clean']:
        report['reason'] = collection['reason']
        report['manual_blockers'] = collection.get('manual_blockers') or []
        report['seconds'] = round(time.time() - started, 2)
        return report
    movable = [item['route_id'] for item in collection['blockers']]
    report['movable_blockers'] = list(movable)
    if len(movable) > int(max_joint):
        report['reason'] = 'too_many_movable_blockers:%d' % len(movable)
        report['seconds'] = round(time.time() - started, 2)
        return report
    # ---- gather the per-blocker conflict points (from the target candidate)
    target_violations = []
    excluded = {target_route_id}
    for _round in range(8):
        violations, _near = local_check(routes, bbox_cache, candidate_route,
                                        exclude_ids=excluded)
        if not violations:
            break
        target_violations.extend(violations)
        for violation in violations:
            other = violation.get('other_route')
            if other is not None:
                excluded.add(int(other))
    # ---- plan make-way geometries on a working copy
    work = {rid: copy.deepcopy(route) for rid, route in routes.items()}
    work[target_route_id] = copy.deepcopy(candidate_route)
    changed = {target_route_id}
    for blocker_id in movable:
        conflict_points = [item for item in target_violations
                           if item.get('other_route') == blocker_id]
        outcome = make_way_one(work, bbox_cache, blocker_id, conflict_points,
                               manual, changed)
        if outcome.get('route') is None:
            report['reason'] = 'blocker_%d:%s' % (blocker_id,
                                                  outcome.get('reason'))
            report['seconds'] = round(time.time() - started, 2)
            return report
        work[blocker_id] = outcome['route']
        changed.add(blocker_id)
        report['joint_routes'].append(dict(
            route_id=blocker_id, target_z=outcome['target_z'],
            s0=round(outcome['s0'], 3), s1=round(outcome['s1'], 3),
            contains_arc=bool(outcome['contains_arc']),
            footprint_mm=outcome['footprint_mm']))
    report['joint_routes'] = [target_route_id] + [
        item['route_id'] for item in report['joint_routes']]
    # ---- exact acceptance: changed routes in a fresh world of the other 1020
    others = [rid for rid in work if rid not in changed]
    world = World(M.layer_stack(), clearance=float(N.MIN_3D_CLEARANCE))
    for rid in sorted(others):
        world.add_route(work[rid])
    placement_errors = []
    for rid in sorted(changed):
        violations = world.check_route(work[rid])
        if violations:
            placement_errors.append(dict(route_id=rid,
                                         violations=violations[:3]))
            continue
        world.add_route(work[rid])
    if placement_errors:
        report['reason'] = 'changed_route_validation_failed'
        report['placement_errors'] = placement_errors
        report['seconds'] = round(time.time() - started, 2)
        return report
    new_env, _bbox = make_env(work, log=None)
    after_total = int(new_env.total())
    report.update(after_total=after_total, net=after_total - original_total,
                  accepted=after_total < original_total)
    report['seconds'] = round(time.time() - started, 2)
    if report['accepted']:
        report['routes'] = work
        report['exact_total'] = after_total
        report['exact_pairs'] = int(new_env.cache.total_pairs())
    return report


def make_env(routes, log=None):
    env = CC.NativeRouteSet(list(routes.values()) if isinstance(routes, dict)
                            else list(routes), log=log)
    bbox = G.BboxCache(list(env.routes.values()))
    return env, bbox


# ------------------------------------------------------------------ batch
def try_route_candidates(env, bbox_cache, route_id, candidates, manual,
                         max_joint=3, log=None):
    """Try several already-built target candidates for one route; return best report."""
    best = None
    attempts = []
    for candidate in candidates:
        report = joint_try(env, bbox_cache, route_id, candidate, manual,
                           max_joint=max_joint, log=log)
        attempts.append(dict(reason=report['reason'],
                             movable=len(report.get('movable_blockers') or []),
                             manual=len(report.get('manual_blockers') or []),
                             accepted=report['accepted'], net=report['net']))
        if report['accepted']:
            if best is None or report['net'] < best['net']:
                best = report
    return best, attempts
