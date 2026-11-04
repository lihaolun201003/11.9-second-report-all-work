# -*- coding: utf-8 -*-
"""Geometry guards: local 3D world check, full validation, minimum clearance."""
from __future__ import annotations

import math
import time
from collections import Counter
from pathlib import Path

from ...fsd25d import path3d as P
from ...fsd25d.world25d import primitive_bbox
from ...l3d.world import World
from ..reheight21 import model as M
from ..reheight21 import validate21 as V21
from . import common as N
from . import route_model as RM


# ------------------------------------------------------------------ bboxes
def part_bbox(part, step=0.02):
    if part.get('kind') == 'flat':
        boxes = [primitive_bbox(prim) for prim in part.get('primitives') or ()]
        if not boxes:
            return None
        return (min(box[0] for box in boxes), min(box[1] for box in boxes),
                max(box[2] for box in boxes), max(box[3] for box in boxes))
    samples = P.transition_samples(part, step=step)
    xs = [sample[0] for sample in samples]
    ys = [sample[1] for sample in samples]
    return (min(xs), min(ys), max(xs), max(ys))


def route_bbox(route):
    boxes = [part_bbox(part) for part in route.get('parts') or ()]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def bbox_overlap(first, second, margin=0.0):
    if first is None or second is None:
        return False
    return not (first[2] + margin < second[0] or second[2] + margin < first[0]
                or first[3] + margin < second[1] or second[3] + margin < first[1])


class BboxCache:
    """2D bounding box of every route, kept in sync with the route set."""

    def __init__(self, routes):
        self.boxes = {}
        for route in routes:
            self.boxes[int(route['route_id'])] = route_bbox(route)

    def update(self, route):
        self.boxes[int(route['route_id'])] = route_bbox(route)

    def remove(self, route_id):
        self.boxes.pop(int(route_id), None)

    def nearby(self, bbox, margin=0.6, exclude=None):
        return [rid for rid, box in self.boxes.items()
                if rid != exclude and bbox_overlap(box, bbox, margin)]


# ------------------------------------------------------------------ local check
def local_world_check(env, candidate, bbox_cache=None, margin=0.6,
                      clearance=float(N.MIN_3D_CLEARANCE)):
    """Exact 3D check of one candidate against the routes that can possibly matter."""
    rid = int(candidate['route_id'])
    bbox = route_bbox(candidate)
    cache = bbox_cache if bbox_cache is not None else BboxCache(
        [env.routes[other] for other in env.routes if other != rid])
    x0, y0, x1, y1 = bbox
    probe = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    others = cache.nearby(probe, margin=0.0, exclude=rid)
    world = World(M.layer_stack(), clearance=clearance)
    added = 0
    for other_id in sorted(others):
        route = env.routes.get(other_id)
        if route is None:
            continue
        world.add_route(route)
        added += 1
    violations = world.check_route(candidate)
    return violations, dict(nearby_routes=added, bbox=bbox)


def ensure_flat_d56(env, candidate, exclude_route=None):
    """Full-plane strict D56 check of every candidate flat part."""
    from .crossing_cache import route_flat_groups
    groups = route_flat_groups(candidate)
    problems = []
    for z_key, chains in groups.items():
        events, _pairs, ok, reasons = env.plane_cache.crossings_of(
            z_key, chains, exclude_route=exclude_route)
        if not ok:
            problems.append(dict(z_mm=float(z_key), reasons=reasons[:4]))
    return problems


def forbidden_cross_plane(candidate, all_heights=None):
    """True when two flat parts of the candidate are closer than 50 um in z."""
    heights = sorted({round(float(part['z_mm']), 9)
                      for part in candidate.get('parts') or ()
                      if part.get('kind') == 'flat'})
    for first, second in zip(heights, heights[1:]):
        if 1e-9 < second - first < float(N.MIN_3D_CLEARANCE) - 1e-9:
            return dict(gap_mm=second - first)
    return None


def candidate_guard(env, candidate, bbox_cache=None):
    """Full legality gate used before a candidate can be accepted."""
    errors = []
    structural = RM.structure_errors(candidate)
    if structural:
        return dict(ok=False, stage='structure', errors=structural[:8])
    metadata = RM.route_metadata_errors(candidate)
    if metadata:
        return dict(ok=False, stage='metadata', errors=metadata[:8])
    gap = forbidden_cross_plane(candidate)
    if gap is not None:
        return dict(ok=False, stage='layer_pitch', errors=[gap])
    d56 = ensure_flat_d56(env, candidate,
                          exclude_route=int(candidate['route_id']))
    if d56:
        return dict(ok=False, stage='d56', errors=d56[:4])
    violations, info = local_world_check(env, candidate, bbox_cache=bbox_cache)
    if violations:
        return dict(ok=False, stage='world', errors=violations[:4], info=info)
    return dict(ok=True, stage='ok', errors=[], info=info)


# ------------------------------------------------------------------ full checks
def full_validate(routes, clearance=float(N.MIN_3D_CLEARANCE), log=None):
    """Fresh-world validation of all routes in route-id order."""
    started = time.time()
    world = World(M.layer_stack(), clearance=clearance)
    violations = []
    valid = []
    for route in sorted(routes, key=lambda item: int(item['route_id'])):
        structural = RM.structure_errors(route)
        if structural:
            violations.append(dict(route_id=int(route['route_id']),
                                   kind='structure', detail=structural[:6]))
            continue
        found = world.check_route(route)
        if found:
            for record in found:
                violations.append(dict(record, route_id=int(route['route_id'])))
            continue
        world.add_route(route)
        valid.append(int(route['route_id']))
    result = dict(valid=len(valid), violations=len(violations),
                  violation_kinds=dict(Counter(item.get('kind')
                                                for item in violations)),
                  examples=violations[:10],
                  seconds=round(time.time() - started, 2))
    if log:
        log('[guard] full validation: valid=%d violations=%d %.1fs'
            % (len(valid), len(violations), result['seconds']))
    return result


def measure_min_clearance(routes, log=None):
    """True 3D minimum centre-line clearance of the whole route set."""
    routed = sorted(routes, key=lambda item: int(item['route_id']))
    started = time.time()
    scan = V21.measure_min_3d_clearance(routed)
    value = scan.get('min_3d_clearance_mm')
    if log:
        log('[guard] min 3D clearance = %s mm (%.1fs)'
            % (value, time.time() - started))
    return dict(min_3d_clearance_mm=value,
                lower_bound_mm=scan.get('min_3d_clearance_lower_bound_mm'),
                seconds=round(time.time() - started, 2))


def route_radius_audit(route):
    """R15 audit of one route (flat arcs exact, transitions sampled 3D)."""
    violations = []
    details = V21.check_radius(route, violations)
    return dict(violations=violations, details=details)
