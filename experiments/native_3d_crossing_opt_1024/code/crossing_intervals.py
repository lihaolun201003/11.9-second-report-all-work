# -*- coding: utf-8 -*-
"""Crossing-position / mid-body excursion interval analysis (Native 3D, experiment B).

For every *movable* route of the frozen C4-free baseline (``E5_joint_repair_final``)
this module answers one question: **where along a route's 2D body path do its
same-layer crossings sit, and which of those crossing clusters could be removed by
one mid-body excursion** -- i.e. a route leaves its body height through an exact
R15 S-curve, travels on another of the 21 routing heights, and returns to its
body height through a second R15 S-curve?

The analysis is deliberately independent of the router:

* the frozen baseline is READ ONLY and is never modified;
* crossings are taken from the frozen ``crossing_stats.json`` (2606 events /
  2067 pairs, strict-D56 legal transverse crossings) and are mapped onto the
  route's body-flat arc length ``s`` with an *exact* analytic line/arc
  parameterisation (not a sampled projection);
* one "cluster" is a gap-connected run of a route's crossings along ``s``;
* one "candidate" is a ``(cluster, target height)`` pair: the excursion interval
  ``[s0, s1]`` is placed on ONE straight line primitive of the body flat,
  ``s1 - s0 >= 2*footprint(target_dz) + min_middle_mm``, and the 1.25 mm
  transition-shadow windows at both ends must be free of same-height crossings;
* ``estimated_removed`` counts the route's own same-height crossing events whose
  ``s`` falls inside ``(s0, s1)``; ``estimated_added`` counts the geometric
  crossing points of OTHER routes' flats at the *target* height with the route's
  XY path inside the middle flat ``[s0+f, s1-f]`` (analytic line/line and
  line/arc intersections, transverse-only, de-duplicated per partner route).

The result feeds experiment B (batch excursion selection); it does not run any
router and never writes outside ``<out-dir>/analysis`` (or the caller-given
plot directory).

CLI::

    python -m four_side_1024.fanout1024.native3d.crossing_intervals \
        --baseline-dir <E5_joint_repair_final> \
        --out-dir <NATIVE_3D_CROSSING_OPT_1024>

Outputs (all deterministic, no timestamps):

* ``<out>/analysis/crossing_intervals.json``
* ``<out>/analysis/crossing_intervals_report.md``
* ``<out>/analysis/crossing_intervals_summary_for_lead.md``
* ``<out>/analysis/plots/*.png`` (when matplotlib is available)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np

from ...fsd25d import path3d as P
from .. import common as C
from . import common as N
from . import transition as T

SCHEMA = 'native3d_crossing_intervals_v1'

# --------------------------------------------------------------------- geometry
TAU = 2.0 * math.pi
R15 = float(N.R15)
#: transition-shadow half width from the report spec (the S-curve is still
#: closer than 50 um to the plane it leaves); ``N.SHADOW_MM`` is 1.2247 mm, the
#: spec rounds this up to 1.25 mm -- the larger value is the safe one.
DEFAULT_SHADOW_MM = max(1.25, float(N.SHADOW_MM))
DEFAULT_MIN_MIDDLE_MM = float(N.MIN_MIDDLE_MM)
DEFAULT_MAX_MIDDLE_MM = 120.0
DEFAULT_CLUSTER_GAP_MM = 10.0        # same gap Experiment A uses (single_route.py)
#: keep the excursion (and the S-curves) away from the body-flat ends, i.e. away
#: from the fanout transitions; Experiment A uses 0.5 mm from the flat ends and
#: ``native3d.route_model.duck_out`` needs s0 > 1e-6 and s1 < length - 1e-6.
DEFAULT_END_MARGIN_MM = 0.5
#: optional spot validation of the estimates against the exact strict-D56
#: crossing cache (``native3d.crossing_cache``); 0 disables it.
DEFAULT_VALIDATE_TOP = 150
MIN_CROSS_ANGLE_DEG = 5.0            # strict-D56 minimum genuine crossing angle
MIN_SINE = math.sin(math.radians(MIN_CROSS_ANGLE_DEG))
CROSSING_DEDUPE_MM = 1e-6
INTERSECT_TOL = 1e-8
PAIR_EPS = 1e-9
#: numerical clearance used when an excursion end is snapped onto a crossing
#: (1 nm: far above double precision, far below any physical row/pitch scale)
EDGE_MM = 1e-6
MAX_RUN_RATIO = 1.0                  # reserved (no truncation by default)


# ============================================================ scalar geometry
def _prim_length(prim):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return abs(float(prim['radius']) * float(prim['sweep']))


def _prim_tangent(prim, t):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        return ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
    angle = float(prim['start_angle']) + float(prim['sweep']) * t
    sign = 1.0 if float(prim['sweep']) >= 0.0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def _prim_point(prim, t):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
    cx, cy = prim['center']
    angle = float(prim['start_angle']) + float(prim['sweep']) * t
    radius = float(prim['radius'])
    return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))


def _arc_contains(angle, prim, tol=1e-8):
    sweep = float(prim['sweep'])
    start = float(prim['start_angle'])
    if sweep >= 0.0:
        distance = (angle - start) % TAU
    else:
        distance = (start - angle) % TAU
    if distance > TAU - tol:
        distance = 0.0
    return distance <= abs(sweep) + tol


def _prim_parameter(prim, point):
    """``(t, distance)`` of the nearest point of ``prim`` to ``point``."""
    px, py = float(point[0]), float(point[1])
    if prim['kind'] == 'line':
        x0, y0 = prim['p0']
        x1, y1 = prim['p1']
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 <= 1e-18:
            return 0.0, math.hypot(px - x0, py - y0)
        t = ((px - x0) * dx + (py - y0) * dy) / length2
        t = min(1.0, max(0.0, t))
        return t, math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
    cx, cy = prim['center']
    radius = float(prim['radius'])
    angle = math.atan2(py - cy, px - cx)
    start = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    if sweep >= 0.0:
        t = ((angle - start) % TAU) / sweep
    else:
        t = ((start - angle) % TAU) / (-sweep)
    t = min(1.0, max(0.0, t))
    a = start + sweep * t
    return t, math.hypot(px - (cx + radius * math.cos(a)),
                         py - (cy + radius * math.sin(a)))


def _prim_bbox(prim):
    if prim['kind'] == 'line':
        x0, y0 = prim['p0']
        x1, y1 = prim['p1']
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    center = prim['center']
    radius = float(prim['radius'])
    angles = [float(prim['start_angle']),
              float(prim['start_angle']) + float(prim['sweep'])]
    for cardinal in (0.0, math.pi / 2.0, math.pi, 1.5 * math.pi):
        if _arc_contains(cardinal, prim):
            angles.append(cardinal)
    xs = [center[0] + radius * math.cos(angle) for angle in angles]
    ys = [center[1] + radius * math.sin(angle) for angle in angles]
    return (min(xs), min(ys), max(xs), max(ys))


def _sine_between(first, second):
    return min(1.0, abs(first[0] * second[1] - first[1] * second[0]))


def _line_line_intersections(first, second, tol=INTERSECT_TOL):
    """``(points, sines, overlap_span_t)`` of two straight primitives."""
    p = first['p0']
    u = (first['p1'][0] - p[0], first['p1'][1] - p[1])
    q = second['p0']
    v = (second['p1'][0] - q[0], second['p1'][1] - q[1])
    lu = math.hypot(u[0], u[1])
    lv = math.hypot(v[0], v[1])
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) > tol:
        qp = (q[0] - p[0], q[1] - p[1])
        t = (qp[0] * v[1] - qp[1] * v[0]) / cross
        s = (qp[0] * u[1] - qp[1] * u[0]) / cross
        if -tol <= t <= 1.0 + tol and -tol <= s <= 1.0 + tol:
            point = (p[0] + t * u[0], p[1] + t * u[1])
            sine = abs(cross) / (lu * lv) if lu * lv > 0.0 else 0.0
            return [point], [min(1.0, sine)], None
        return [], [], None
    # parallel: collinear overlap or nothing
    qp = (q[0] - p[0], q[1] - p[1])
    if abs(qp[0] * u[1] - qp[1] * u[0]) > tol * max(1.0, lu):
        return [], [], None
    uu = u[0] * u[0] + u[1] * u[1]
    if uu <= 1e-18:
        return [], [], None
    tc = (qp[0] * u[0] + qp[1] * u[1]) / uu
    td = ((q[0] + v[0] - p[0]) * u[0] + (q[1] + v[1] - p[1]) * u[1]) / uu
    lo = max(0.0, min(tc, td))
    hi = min(1.0, max(tc, td))
    if hi < lo - tol:
        return [], [], None
    if (hi - lo) * lu > tol:
        return [], [], (lo, hi)
    return [(p[0] + lo * u[0], p[1] + lo * u[1])], [0.0], None


def _line_arc_intersections(line, arc, tol=INTERSECT_TOL):
    """``(points, sines, None)`` of one straight primitive against one arc."""
    p = line['p0']
    v = (line['p1'][0] - p[0], line['p1'][1] - p[1])
    aa = v[0] * v[0] + v[1] * v[1]
    if aa < 1e-18:
        return [], [], None
    span = math.sqrt(aa)
    unit = (v[0] / span, v[1] / span)
    center = arc['center']
    offset = (p[0] - center[0], p[1] - center[1])
    projection = -(offset[0] * unit[0] + offset[1] * unit[1])
    nearest = (offset[0] + projection * unit[0], offset[1] + projection * unit[1])
    radius = float(arc['radius'])
    height2 = radius * radius - (nearest[0] * nearest[0] + nearest[1] * nearest[1])
    roundoff = 64.0 * np.finfo(float).eps * max(
        1.0, offset[0] * offset[0] + offset[1] * offset[1], radius * radius)
    if height2 < -roundoff:
        return [], [], None
    height2 = max(0.0, height2)
    root = math.sqrt(height2)
    points = []
    sines = []
    for t in ((projection - root) / span, (projection + root) / span):
        if not (-tol <= t <= 1.0 + tol):
            continue
        point = (p[0] + t * v[0], p[1] + t * v[1])
        angle = math.atan2(point[1] - center[1], point[0] - center[0])
        if not _arc_contains(angle, arc):
            continue
        if any(math.hypot(point[0] - q[0], point[1] - q[1]) < tol
               for q in points):
            continue
        sign = 1.0 if float(arc['sweep']) >= 0.0 else -1.0
        tangent = (-sign * math.sin(angle), sign * math.cos(angle))
        points.append(point)
        sines.append(_sine_between(unit, tangent))
    return points, sines, None


def _line_prim_intersections(line, other):
    """Line primitive vs any primitive: ``(points, sines, overlap_span_t)``."""
    if other['kind'] == 'line':
        return _line_line_intersections(line, other)
    return _line_arc_intersections(line, other)


# ============================================================== route bodies
class RouteBody(object):
    """Primary body flat of one route: primitives, offsets, z and straights."""

    __slots__ = ('route_id', 'part_index', 'z_mm', 'plane_id', 'prims',
                 'offsets', 'length_mm', 'straights')

    def __init__(self, route_id, part_index, part):
        self.route_id = int(route_id)
        self.part_index = int(part_index)
        self.z_mm = float(part['z_mm'])
        self.plane_id = N.plane_of_z(self.z_mm)
        prims = []
        for prim in part.get('primitives') or ():
            if _prim_length(prim) > 1e-9:
                prims.append(dict(prim))
        self.prims = prims
        offsets = []
        running = 0.0
        for prim in prims:
            offsets.append(running)
            running += _prim_length(prim)
        self.offsets = offsets
        self.length_mm = running
        self.straights = P.straight_intervals(prims)


def route_body(route):
    """Primary (longest) body flat of a route, or ``None``."""
    indices = N.body_flat_indices(route)
    if not indices:
        return None
    index = max(indices, key=lambda item: N.part_length(route['parts'][item]))
    part = route['parts'][index]
    if part.get('kind') != 'flat':
        return None
    body = RouteBody(route['route_id'], index, part)
    if not body.prims or body.plane_id is None:
        return None
    return body


def project_point(body, point):
    """Exact body-flat arc length ``s`` of the nearest path point + distance."""
    best_s = 0.0
    best_distance = float('inf')
    for prim, offset in zip(body.prims, body.offsets):
        t, distance = _prim_parameter(prim, point)
        if distance < best_distance:
            best_distance = distance
            best_s = offset + t * _prim_length(prim)
    return best_s, best_distance


# ============================================================ plane flat index
class PlaneFlatIndex(object):
    """Every flat primitive of every route grouped by its physical height."""

    def __init__(self, routes):
        self.by_z = OrderedDict()
        self.route_ids = OrderedDict()
        self.flat_part_count = OrderedDict()
        for record in routes:
            route_id = int(record['route_id'])
            for part in record.get('parts') or ():
                if part.get('kind') != 'flat':
                    continue
                z_key = round(float(part['z_mm']), 9)
                prims = [dict(prim) for prim in part.get('primitives') or ()
                         if _prim_length(prim) > 1e-9]
                if not prims:
                    continue
                entry = self.by_z.get(z_key)
                if entry is None:
                    entry = self.by_z[z_key] = dict(items=[], boxes=[])
                    self.route_ids[z_key] = set()
                    self.flat_part_count[z_key] = 0
                self.route_ids[z_key].add(route_id)
                self.flat_part_count[z_key] += len(prims)
                for prim in prims:
                    entry['items'].append((route_id, prim))
                    entry['boxes'].append(_prim_bbox(prim))
        for entry in self.by_z.values():
            entry['boxes'] = np.asarray(entry['boxes'], dtype=float).reshape(-1, 4)
            entry['items'] = tuple(entry['items'])

    def query(self, z_mm, box, exclude_route=None):
        """Flat primitives at ``z_mm`` whose bounding box may meet ``box``."""
        entry = self.by_z.get(round(float(z_mm), 9))
        if entry is None or not entry['items']:
            return ()
        boxes = entry['boxes']
        x0, y0, x1, y1 = box
        mask = ((boxes[:, 0] <= x1 + PAIR_EPS) &
                (boxes[:, 2] >= x0 - PAIR_EPS) &
                (boxes[:, 1] <= y1 + PAIR_EPS) &
                (boxes[:, 3] >= y0 - PAIR_EPS))
        indices = np.nonzero(mask)[0]
        if exclude_route is None:
            return tuple(entry['items'][int(index)] for index in indices)
        return tuple(entry['items'][int(index)] for index in indices
                     if entry['items'][int(index)][0] != int(exclude_route))


# ============================================================ intersection cache
def target_intersections(body, prim_index, target_z, plane_index,
                         min_sine=MIN_SINE):
    """Crossing points of one straight body primitive against a target height.

    Returns ``dict(all, transverse, overlaps)``: sorted arc-length arrays of
    every geometric intersection point / the transverse-only subset / collinear
    overlap spans.  Points are de-duplicated per partner route (1e-6 mm) like the
    frozen crossing audit, so a partner prim junction is one event.
    """
    line = body.prims[prim_index]
    offset = body.offsets[prim_index]
    length = _prim_length(line)
    p0 = line['p0']
    unit = ((line['p1'][0] - p0[0]) / length, (line['p1'][1] - p0[1]) / length)
    per_partner = OrderedDict()
    overlaps = []
    for partner_id, other in plane_index.query(target_z, _prim_bbox(line),
                                               exclude_route=body.route_id):
        points, sines, overlap = _line_prim_intersections(line, other)
        if overlap is not None:
            span = (offset + overlap[0] * length, offset + overlap[1] * length)
            if span[1] - span[0] > 1e-9:
                overlaps.append((min(span), max(span)))
            continue
        for point, sine in zip(points, sines):
            t = (((point[0] - p0[0]) * unit[0] + (point[1] - p0[1]) * unit[1])
                 / length)
            s = offset + t * length
            per_partner.setdefault(int(partner_id), []).append(
                (s, point[0], point[1], sine))
    all_s = []
    transverse_s = []
    for records in per_partner.values():
        unique = []
        for record in records:
            duplicate = False
            for kept in unique:
                if (abs(record[1] - kept[1]) < CROSSING_DEDUPE_MM
                        and abs(record[2] - kept[2]) < CROSSING_DEDUPE_MM):
                    duplicate = True
                    break
            if not duplicate:
                unique.append(record)
        for record in unique:
            all_s.append(record[0])
            if record[3] >= min_sine:
                transverse_s.append(record[0])
    return dict(all=np.sort(np.asarray(all_s, dtype=float)),
                transverse=np.sort(np.asarray(transverse_s, dtype=float)),
                overlaps=tuple(overlaps))


# ============================================================ crossing map
def map_crossing_positions(events, bodies):
    """Map each same-body-height crossing event onto both routes' body paths."""
    positions = OrderedDict((route_id, []) for route_id in bodies)
    failures = []
    max_error = 0.0
    for event in events:
        z_key = round(float(event['z_mm']), 9)
        point = (float(event['x_mm']), float(event['y_mm']))
        route_a = int(event['route_a'])
        route_b = int(event['route_b'])
        for route_id, partner_id in ((route_a, route_b), (route_b, route_a)):
            body = bodies.get(route_id)
            if body is None or abs(body.z_mm - z_key) > 1e-9:
                continue
            s_value, distance = project_point(body, point)
            max_error = max(max_error, distance)
            if distance > 1e-3:
                failures.append(dict(route_id=route_id, event_z=z_key,
                                     distance_mm=round(distance, 6)))
                continue
            positions[route_id].append(dict(
                s_mm=round(float(s_value), 6),
                partner_route=int(partner_id),
                partner_layer=int(N.plane_of_z(z_key)),
                partner_z=round(float(z_key), 9),
                x_mm=round(point[0], 6),
                y_mm=round(point[1], 6),
                angle_deg=round(float(event.get('angle_deg') or 0.0), 6),
            ))
    for route_id, items in positions.items():
        items.sort(key=lambda item: (item['s_mm'], item['partner_route']))
    return positions, max_error, failures


def build_clusters(positions, gap_mm):
    """Gap-connected runs of crossing positions along the body path."""
    clusters = []
    for index, position in enumerate(positions):
        if clusters and position['s_mm'] - clusters[-1]['s_end_mm'] <= gap_mm:
            cluster = clusters[-1]
            cluster['indices'].append(index)
            cluster['s_end_mm'] = position['s_mm']
        else:
            clusters.append(dict(s_start_mm=position['s_mm'],
                                 s_end_mm=position['s_mm'],
                                 indices=[index]))
    for cluster in clusters:
        cluster['count'] = len(cluster['indices'])
        layers = Counter()
        for index in cluster['indices']:
            layers[positions[index]['partner_z']] += 1
        cluster['partner_layers'] = OrderedDict(
            (round_key, layers[round_key]) for round_key in sorted(layers))
    return clusters


# ============================================================ interval placement
def _count_between(values, low, high, closed=True):
    """Number of sorted ``values`` inside ``[low, high]`` / ``(low, high)``."""
    if values.size == 0 or high < low:
        return 0
    left = int(np.searchsorted(values, low, side='left' if closed else 'right'))
    right = int(np.searchsorted(values, high, side='right' if closed else 'left'))
    return max(0, right - left)


def _valid_starts(upper, lower_bound, crossings, shadow_mm):
    """Valid excursion starts ``s0 <= upper`` inside ``[lower_bound, upper]``.

    A start is valid when the transition-shadow window ``[s0, s0 + shadow]``
    contains no same-height crossing.  Returned descending (tight start first);
    each element after the first jumps just before the next earlier crossing,
    with a 1 nm clearance so the snapped crossing is strictly outside the
    closed shadow window.
    """
    starts = []
    s0 = float(upper)
    guard = 0
    while s0 >= lower_bound - EDGE_MM and guard < 10000:
        guard += 1
        low_index = int(np.searchsorted(crossings, s0 - PAIR_EPS, side='left'))
        high_index = int(np.searchsorted(crossings, s0 + shadow_mm + PAIR_EPS,
                                         side='right'))
        if high_index <= low_index:
            starts.append(float(s0))
            before = int(np.searchsorted(crossings, s0 - PAIR_EPS,
                                         side='left')) - 1
            if before < 0:
                break
            s0 = float(crossings[before]) - shadow_mm - EDGE_MM
        else:
            s0 = float(crossings[low_index]) - shadow_mm - EDGE_MM
    if upper >= lower_bound - PAIR_EPS:
        low_index = int(np.searchsorted(crossings, lower_bound - PAIR_EPS,
                                        side='left'))
        high_index = int(np.searchsorted(crossings,
                                         lower_bound + shadow_mm + PAIR_EPS,
                                         side='right'))
        if high_index <= low_index and (not starts or
                                        starts[-1] > lower_bound + PAIR_EPS):
            starts.append(float(lower_bound))
    return starts


def _valid_ends(lower, upper_bound, crossings, shadow_mm):
    """Valid excursion ends ``s1 >= lower`` inside ``[lower, upper_bound]``.

    A 1 nm clearance past the snapped crossing guarantees that the crossing is
    strictly outside the closed shadow window ``[s1 - shadow, s1]`` (without it
    the snapping would keep re-including the crossing and loop forever).
    """
    ends = []
    s1 = float(lower)
    guard = 0
    while s1 <= upper_bound + EDGE_MM and guard < 10000:
        guard += 1
        low_index = int(np.searchsorted(crossings, s1 - shadow_mm - PAIR_EPS,
                                        side='left'))
        high_index = int(np.searchsorted(crossings, s1 + PAIR_EPS, side='right'))
        if high_index <= low_index:
            ends.append(float(s1))
            after = int(np.searchsorted(crossings, s1 + PAIR_EPS, side='right'))
            if after >= crossings.size:
                break
            s1 = float(crossings[after]) + shadow_mm + EDGE_MM
        else:
            s1 = float(crossings[high_index - 1]) + shadow_mm + EDGE_MM
    if lower <= upper_bound + PAIR_EPS:
        low_index = int(np.searchsorted(crossings, upper_bound - shadow_mm
                                        - PAIR_EPS, side='left'))
        high_index = int(np.searchsorted(crossings, upper_bound + PAIR_EPS,
                                         side='right'))
        if high_index <= low_index and (not ends or
                                        ends[-1] < upper_bound - PAIR_EPS):
            ends.append(float(upper_bound))
    return ends


def placement_options(s_cover_lo, s_cover_hi, run_lo, run_hi, need_mm,
                      crossings, shadow_mm, max_options=4):
    """Deterministic feasible ``(s0, s1)`` options covering ``[s_cover_lo, s_cover_hi]``.

    ``s0`` must lie before ``s_cover_lo - shadow`` and ``s1`` after
    ``s_cover_hi + shadow`` (so every covered crossing is outside both shadow
    windows); the interval must satisfy ``s1 - s0 >= need_mm`` and stay inside
    the single straight run ``[run_lo, run_hi]``.
    """
    tight_s0 = s_cover_lo - shadow_mm - EDGE_MM
    tight_s1 = s_cover_hi + shadow_mm + EDGE_MM
    if tight_s0 < run_lo - PAIR_EPS or tight_s1 > run_hi + PAIR_EPS:
        return []
    starts = _valid_starts(tight_s0, run_lo, crossings, shadow_mm)
    ends = _valid_ends(tight_s1, run_hi, crossings, shadow_mm)
    if not starts or not ends:
        return []
    base_s0, base_s1 = starts[0], ends[0]
    options = []
    if base_s1 - base_s0 >= need_mm - PAIR_EPS:
        options.append((base_s0, base_s1))
    else:
        for s0 in starts[:6]:
            target = s0 + need_mm
            for s1 in ends[:8]:
                if s1 >= target - PAIR_EPS:
                    options.append((s0, s1))
                    break
        for s1 in ends[:6]:
            target = s1 - need_mm
            for s0 in starts[:8]:
                if s0 <= target + PAIR_EPS:
                    options.append((s0, s1))
                    break
    if not options:
        # last resort: clamp to the straight run and see whether it fits
        s0 = max(run_lo, tight_s0)
        s1 = min(run_hi, tight_s1)
        if s1 - s0 >= need_mm - PAIR_EPS:
            options.append((s0, s1))
    unique = OrderedDict()
    for s0, s1 in options:
        s0 = min(max(s0, run_lo), run_hi)
        s1 = min(max(s1, run_lo), run_hi)
        if s1 - s0 < need_mm - PAIR_EPS:
            continue
        unique[(round(s0, 6), round(s1, 6))] = (float(s0), float(s1))
    ordered = sorted(unique.values(), key=lambda pair: (pair[1] - pair[0], pair[0]))
    return ordered[:max_options]


def _overlaps_intersect(overlaps, low, high):
    for span_lo, span_hi in overlaps:
        if span_hi > low + PAIR_EPS and span_lo < high - PAIR_EPS:
            return True
    return False


def evaluate_placement(body, run_lo, run_hi, s0, s1, footprint_mm, need_mm,
                       target_z, crossings, target_cache, shadow_mm,
                       min_middle_mm):
    """Evaluate one excursion interval against the analysis definitions."""
    reasons = []
    middle_mm = (s1 - s0) - 2.0 * footprint_mm
    if s0 < run_lo - EDGE_MM or s1 > run_hi + EDGE_MM or s1 <= s0:
        reasons.append('outside_straight_run')
    if middle_mm < min_middle_mm - PAIR_EPS:
        reasons.append('middle_too_short')
    # 1.25 mm transition shadow on the SOURCE height (left at s0, re-entered at s1)
    source_shadow = (_count_between(crossings, s0, s0 + shadow_mm, closed=True)
                     + _count_between(crossings, s1 - shadow_mm, s1,
                                      closed=True))
    shadow_ok = source_shadow == 0
    if not shadow_ok:
        reasons.append('shadow_source')
    middle_lo = s0 + footprint_mm
    middle_hi = s1 - footprint_mm
    added = _count_between(target_cache['transverse'], middle_lo, middle_hi,
                           closed=False)
    tangent_middle = (_count_between(target_cache['all'], middle_lo, middle_hi,
                                     closed=False) - added)
    # mirrored shadow where the S-curve is still close to the TARGET height
    target_shadow = (_count_between(target_cache['all'],
                                    s0 + footprint_mm - shadow_mm,
                                    s0 + footprint_mm, closed=True)
                     + _count_between(target_cache['all'], s1 - footprint_mm,
                                      s1 - footprint_mm + shadow_mm, closed=True))
    target_shadow_ok = target_shadow == 0
    if not target_shadow_ok:
        reasons.append('shadow_target')
    overlap_middle = _overlaps_intersect(target_cache['overlaps'], middle_lo,
                                         middle_hi)
    overlap_shadow = (_overlaps_intersect(target_cache['overlaps'],
                                          s0 + footprint_mm - shadow_mm,
                                          s0 + footprint_mm)
                      or _overlaps_intersect(target_cache['overlaps'],
                                             s1 - footprint_mm,
                                             s1 - footprint_mm + shadow_mm))
    if overlap_middle:
        reasons.append('target_overlap_middle')
    if overlap_shadow:
        reasons.append('target_overlap_shadow')
    if tangent_middle > 0:
        reasons.append('target_tangent_contact')
    removed = _count_between(crossings, s0, s1, closed=False)
    feasible = not reasons
    return dict(s_start_mm=round(s0, 6), s_end_mm=round(s1, 6),
                footprint_mm=round(float(footprint_mm), 6),
                middle_mm=round(float(middle_mm), 6),
                estimated_removed=int(removed),
                estimated_added=int(added),
                estimated_net=int(removed - added),
                shadow_ok=bool(shadow_ok),
                target_shadow_ok=bool(target_shadow_ok),
                source_shadow_crossings=int(source_shadow),
                target_shadow_crossings=int(target_shadow),
                target_tangent_contacts=int(tangent_middle),
                feasible=bool(feasible),
                reasons=tuple(reasons),
                target_z=round(float(target_z), 9))


def _candidate_key(record):
    """Sort key: feasible first, then net, then shorter excursion."""
    return (0 if record['feasible'] else 1,
            -int(record['estimated_net']),
            int(record['estimated_added']),
            record['middle_mm'],
            record['s_start_mm'])


def _infeasible_key(record):
    return (-int(record['estimated_removed']),
            int(record['estimated_added']),
            record['middle_mm'],
            record['s_start_mm'])


# ============================================================ route analysis
def executable_windows(body, params):
    """``[(lo, hi)]`` body-flat arc-length windows where an excursion can start.

    Combines the body-flat end margin, the 1.25 mm source-height shadow at both
    excursion ends and the "inside one straight line primitive" rule.
    """
    windows = []
    total = body.length_mm
    for run_lo, run_hi, _index in body.straights:
        lo = (max(run_lo, params['end_margin_mm']) + params['shadow_mm']
              + EDGE_MM)
        hi = (min(run_hi, total - params['end_margin_mm']) - params['shadow_mm']
              - EDGE_MM)
        if hi > lo + PAIR_EPS:
            windows.append((lo, hi))
    return windows


def cluster_executable(cluster_positions, windows):
    for item in cluster_positions:
        for low, high in windows:
            if low <= item['s_mm'] <= high:
                return True
    return False


def analyse_route(record, body, positions, plane_index, params):
    """Clusters + per-target-height candidates of one movable route."""
    route_id = int(record['route_id'])
    crossings = np.asarray([item['s_mm'] for item in positions], dtype=float)
    clusters = build_clusters(positions, params['cluster_gap_mm'])
    windows = executable_windows(body, params)
    candidates = []
    cache = {}
    for cluster_index, cluster in enumerate(clusters):
        members = [positions[index] for index in cluster['indices']]
        if not cluster_executable(members, windows):
            # every crossing of the cluster sits on an arc / too close to a
            # straight-run end: no straight-run excursion can ever remove it
            continue
        for target_plane_id in params['target_plane_ids']:
            target_z = float(N.PLANE_Z[target_plane_id])
            if abs(target_z - body.z_mm) <= 1e-12:
                continue
            footprint = T.transition_footprint(target_z - body.z_mm)
            need = 2.0 * footprint + params['min_middle_mm']
            best = None
            best_infeasible = None
            any_piece = False
            for run_lo, run_hi, prim_index in body.straights:
                eff_lo = max(run_lo, params['end_margin_mm'])
                eff_hi = min(run_hi, body.length_mm - params['end_margin_mm'])
                if eff_hi - eff_lo < need - PAIR_EPS:
                    continue
                piece = [item for item in members
                         if (eff_lo + params['shadow_mm'] + EDGE_MM
                             <= item['s_mm']
                             <= eff_hi - params['shadow_mm'] - EDGE_MM)]
                if not piece:
                    continue
                any_piece = True
                key = (prim_index, target_plane_id)
                target_cache = cache.get(key)
                if target_cache is None:
                    target_cache = target_intersections(
                        body, prim_index, target_z, plane_index)
                    cache[key] = target_cache
                for first in range(len(piece)):
                    for last in range(first, len(piece)):
                        options = placement_options(
                            piece[first]['s_mm'], piece[last]['s_mm'],
                            eff_lo, eff_hi, need, crossings,
                            params['shadow_mm'])
                        for s0, s1 in options:
                            option = evaluate_placement(
                                body, eff_lo, eff_hi, s0, s1, footprint,
                                need, target_z, crossings, target_cache,
                                params['shadow_mm'], params['min_middle_mm'])
                            if option['feasible']:
                                if best is None or _candidate_key(option) < _candidate_key(best):
                                    best = option
                            elif (best is None
                                  and (best_infeasible is None
                                       or _infeasible_key(option) < _infeasible_key(best_infeasible))):
                                best_infeasible = option
            chosen = best if best is not None else best_infeasible
            if chosen is None:
                # no straight run can host this target height for this cluster:
                # the runs long enough for 2*footprint+min_middle do not contain
                # the cluster's crossings, or every placement is shadow-blocked
                if not any_piece:
                    reason = 'straight_run_too_short'
                else:
                    reason = 'no_shadow_clear_placement'
                chosen = dict(s_start_mm=None, s_end_mm=None,
                              footprint_mm=round(float(footprint), 6),
                              middle_mm=None, estimated_removed=0,
                              estimated_added=0, estimated_net=0,
                              shadow_ok=False, target_shadow_ok=False,
                              source_shadow_crossings=0,
                              target_shadow_crossings=0,
                              target_tangent_contacts=0, feasible=False,
                              reasons=(reason,),
                              target_z=round(float(target_z), 9))
            candidate = dict(
                target_z=round(float(target_z), 9),
                target_plane_id=int(target_plane_id),
                target_plane_label=N.PLANE_LABEL[int(target_plane_id)],
                target_is_manual_plane=bool(int(target_plane_id)
                                            in params['manual_plane_ids']),
                s_start_mm=chosen['s_start_mm'],
                s_end_mm=chosen['s_end_mm'],
                footprint_mm=chosen['footprint_mm'],
                middle_mm=chosen['middle_mm'],
                estimated_removed=int(chosen['estimated_removed']),
                estimated_added=int(chosen['estimated_added']),
                estimated_net=int(chosen['estimated_net']),
                shadow_ok=bool(chosen['shadow_ok']),
                target_shadow_ok=bool(chosen['target_shadow_ok']),
                feasible=bool(chosen['feasible']),
                reason='ok' if chosen['feasible']
                else '+'.join(chosen['reasons']) or 'unknown',
                cluster_index=int(cluster_index),
                cluster_count=int(cluster['count']),
                cluster_start_mm=round(float(cluster['s_start_mm']), 6),
                cluster_end_mm=round(float(cluster['s_end_mm']), 6),
                straight_prim_index=int(next(
                    (index for low, high, index in body.straights
                     if chosen['s_start_mm'] is not None
                     and low - PAIR_EPS <= chosen['s_start_mm'] <= high + PAIR_EPS),
                    -1)),
                source_shadow_crossings=int(chosen['source_shadow_crossings']),
                target_shadow_crossings=int(chosen['target_shadow_crossings']),
            )
            candidates.append(candidate)
    return dict(route_id=route_id,
                family=str(record.get('relation') or ''),
                manual=False,
                body_layer=int(body.plane_id),
                body_layer_label=N.PLANE_LABEL[int(body.plane_id)],
                body_z=round(float(body.z_mm), 9),
                body_flat_index=int(body.part_index),
                path_length_mm=round(float(body.length_mm), 6),
                crossings=[dict(item) for item in positions],
                clusters=[dict(s_start_mm=round(float(cluster['s_start_mm']), 6),
                               s_end_mm=round(float(cluster['s_end_mm']), 6),
                               count=int(cluster['count']),
                               partner_layers=OrderedDict(
                                   ('%.3f' % z_key, int(count))
                                   for z_key, count in
                                   cluster['partner_layers'].items()))
                          for cluster in clusters],
                candidates=candidates)


# ============================================================ global analysis
def analyse(baseline_dir, cluster_gap_mm=DEFAULT_CLUSTER_GAP_MM,
            shadow_mm=DEFAULT_SHADOW_MM,
            min_middle_mm=DEFAULT_MIN_MIDDLE_MM,
            max_middle_mm=DEFAULT_MAX_MIDDLE_MM,
            end_margin_mm=DEFAULT_END_MARGIN_MM,
            target_plane_ids=None, log=None):
    """Run the full crossing-interval analysis; returns the result payload."""
    baseline_dir = Path(baseline_dir)
    started = time.time()
    payload = N.load_json(baseline_dir / 'routes_l3d.json')
    routes = [record for record in payload['routes']
              if str(record.get('status') or '') != 'failed']
    stats = N.load_json(baseline_dir / 'crossing_stats.json')
    events = stats.get('crossing_events') or []
    layer_planes_path = baseline_dir / 'layer_planes.json'
    layer_planes = (N.load_json(layer_planes_path)
                    if layer_planes_path.exists() else None)

    if target_plane_ids is None:
        target_plane_ids = [int(plane_id) for plane_id in N.PLANE_Z]
    else:
        target_plane_ids = [int(plane_id) for plane_id in target_plane_ids]
    params = dict(cluster_gap_mm=float(cluster_gap_mm),
                  shadow_mm=float(shadow_mm),
                  min_middle_mm=float(min_middle_mm),
                  max_middle_mm=(None if max_middle_mm is None
                                 else float(max_middle_mm)),
                  end_margin_mm=float(end_margin_mm),
                  min_cross_angle_deg=MIN_CROSS_ANGLE_DEG,
                  crossing_dedupe_mm=CROSSING_DEDUPE_MM,
                  target_plane_ids=target_plane_ids,
                  manual_plane_ids=tuple(int(pid) for pid in N.MANUAL_PLANES))

    movable = [record for record in routes
               if not str(record.get('manual_group') or '').strip()]
    bodies = OrderedDict()
    for record in movable:
        body = route_body(record)
        if body is not None:
            bodies[int(record['route_id'])] = body

    positions, max_error, failures = map_crossing_positions(events, bodies)
    plane_index = PlaneFlatIndex(routes)
    if log:
        log('[intervals] %d routes (%d movable, %d with body flat), '
            '%d crossing events, mapping max error %.2e mm'
            % (len(routes), len(movable), len(bodies), len(events), max_error))

    route_results = []
    for record in movable:
        route_id = int(record['route_id'])
        body = bodies.get(route_id)
        if body is None:
            continue
        route_results.append(analyse_route(record, body, positions[route_id],
                                           plane_index, params))

    routes_by_id = {int(item['route_id']): item for item in routes}
    ranking = build_ranking(route_results, routes_by_id, max_entries=None)
    notes = build_mechanism_notes(
        routes, movable, route_results, events, stats, plane_index, bodies,
        params, max_error, failures, baseline_dir, layer_planes, started)
    result = dict(
        schema=SCHEMA,
        baseline_dir=str(baseline_dir),
        route_count=int(len(routes)),
        movable_routes=int(len(movable)),
        analysis_parameters=dict(params),
        routes=route_results,
        ranking=ranking,
        mechanism_notes=notes,
    )
    if log:
        log('[intervals] analysed %d routes, %d clusters, %d candidates '
            'in %.1fs' % (len(route_results),
                          sum(len(item['clusters']) for item in route_results),
                          sum(len(item['candidates']) for item in route_results),
                          time.time() - started))
    return result


def build_ranking(route_results, routes_by_id, max_entries=1000):
    """Global ranking of feasible candidates with a positive estimated net."""
    entries = []
    for route in route_results:
        for candidate in route['candidates']:
            if not candidate['feasible']:
                continue
            if int(candidate['estimated_net']) < 1:
                continue
            if candidate['s_start_mm'] is None:
                continue
            entries.append(dict(
                route_id=int(route['route_id']),
                family=route['family'],
                body_layer=int(route['body_layer']),
                body_z=float(route['body_z']),
                cluster_index=int(candidate['cluster_index']),
                cluster_count=int(candidate['cluster_count']),
                cluster_start_mm=float(candidate['cluster_start_mm']),
                cluster_end_mm=float(candidate['cluster_end_mm']),
                target_z=float(candidate['target_z']),
                target_plane_id=int(candidate['target_plane_id']),
                target_plane_label=candidate['target_plane_label'],
                target_is_manual_plane=bool(candidate['target_is_manual_plane']),
                s_start_mm=float(candidate['s_start_mm']),
                s_end_mm=float(candidate['s_end_mm']),
                footprint_mm=float(candidate['footprint_mm']),
                middle_mm=float(candidate['middle_mm']),
                estimated_removed=int(candidate['estimated_removed']),
                estimated_added=int(candidate['estimated_added']),
                estimated_net=int(candidate['estimated_net']),
            ))
    entries.sort(key=lambda item: (-item['estimated_net'],
                                   item['middle_mm'],
                                   item['route_id'],
                                   item['target_z']))
    if max_entries is not None:
        entries = entries[:int(max_entries)]
    for rank, entry in enumerate(entries, start=1):
        entry['rank'] = rank
    return entries


def spot_validate(routes_by_id, route_results, ranking, top_n=150, log=None):
    """Optional verification of the estimates against the exact strict-D56 cache.

    Uses ``native3d.crossing_cache.NativeRouteSet`` (the shared exact crossing
    cache) plus ``native3d.route_model.duck_out`` to build the candidate route and
    measure the real crossing delta / D56 validity.  Purely a diagnostic: the
    deliverable ``feasible`` flag follows the geometric definition in the spec.
    Import failures are reported instead of raised (the cache is shared code).
    """
    try:
        from . import crossing_cache as CC
        from . import route_model as RM
    except Exception as error:                      # pragma: no cover
        return dict(available=False,
                    reason='native3d.crossing_cache unavailable: %s' % error)
    lookup = {}
    for route in route_results:
        for candidate in route['candidates']:
            if candidate['s_start_mm'] is None:
                continue
            key = (int(route['route_id']), round(float(candidate['s_start_mm']), 6),
                   round(float(candidate['s_end_mm']), 6),
                   round(float(candidate['target_z']), 9))
            lookup[key] = (int(route['body_flat_index']), candidate)
    try:
        env = CC.NativeRouteSet(list(routes_by_id.values()))
    except Exception as error:                      # pragma: no cover
        return dict(available=False,
                    reason='crossing cache build failed: %s' % error)

    def _evaluate(route_id, body_part, s0, s1, target_z, estimated_net):
        route = routes_by_id[int(route_id)]
        try:
            built = RM.duck_out(route, int(body_part), float(s0), float(s1),
                                float(target_z))
        except Exception as error:                  # pragma: no cover
            return dict(route_id=int(route_id), target_z=round(float(target_z), 9),
                        s_start_mm=round(float(s0), 6),
                        s_end_mm=round(float(s1), 6),
                        estimated_net=int(estimated_net), build_error=str(error))
        structure = RM.structure_errors(built['route'])
        if structure:                               # pragma: no cover
            return dict(route_id=int(route_id), target_z=round(float(target_z), 9),
                        s_start_mm=round(float(s0), 6),
                        s_end_mm=round(float(s1), 6),
                        estimated_net=int(estimated_net),
                        build_error='structure:' + ';'.join(structure[:2]))
        fast = env.evaluate_candidate(int(route_id), built['route'])
        return dict(route_id=int(route_id), target_z=round(float(target_z), 9),
                    s_start_mm=round(float(s0), 6),
                    s_end_mm=round(float(s1), 6),
                    estimated_net=int(estimated_net),
                    exact_net=int(-int(fast['delta'])),
                    d56_ok=bool(fast['d56_ok']),
                    build_error='')

    def _summarize(rows):
        built = [row for row in rows if row.get('build_error') == '']
        agree = sum(1 for row in built
                    if int(row['exact_net']) == int(row['estimated_net']))
        d56 = sum(1 for row in built if row['d56_ok'])
        positive = sum(1 for row in built if int(row['exact_net']) >= 1)
        positive_d56 = sum(1 for row in built
                           if int(row['exact_net']) >= 1 and row['d56_ok'])
        return dict(evaluated=len(rows), built=len(built),
                    build_failures=len(rows) - len(built),
                    estimate_equals_exact=int(agree),
                    exact_d56_ok=int(d56),
                    exact_gain_ge_1=int(positive),
                    exact_gain_ge_1_and_d56_ok=int(positive_d56),
                    mismatches=[row for row in built
                                if int(row['exact_net']) != int(row['estimated_net'])][:8])

    started = time.time()
    ranking_rows = []
    for rank in ranking[:max(0, int(top_n))]:
        key = (int(rank['route_id']), round(float(rank['s_start_mm']), 6),
               round(float(rank['s_end_mm']), 6),
               round(float(rank['target_z']), 9))
        found = lookup.get(key)
        if found is None:
            continue
        body_part, _candidate = found
        ranking_rows.append(_evaluate(rank['route_id'], body_part,
                                      rank['s_start_mm'], rank['s_end_mm'],
                                      rank['target_z'], rank['estimated_net']))
    route_best_rows = []
    for route in route_results:
        feasible = [candidate for candidate in route['candidates']
                    if candidate['feasible'] and candidate['s_start_mm'] is not None]
        if not feasible:
            continue
        best = max(feasible, key=lambda candidate: (
            int(candidate['estimated_net']), -float(candidate['middle_mm'])))
        if int(best['estimated_net']) < 1:
            continue
        route_best_rows.append(_evaluate(route['route_id'], route['body_flat_index'],
                                         best['s_start_mm'], best['s_end_mm'],
                                         best['target_z'], best['estimated_net']))
    report = dict(available=True,
                  top_n=int(top_n),
                  ranking_top=_summarize(ranking_rows),
                  per_route_best=_summarize(route_best_rows),
                  note='diagnostic only: the deliverable feasible flag is the '
                       'geometric definition; the exact cache re-audits strict '
                       'D56 and is the ground truth for experiment B')
    if log:
        log('[intervals] spot validation: ranking top %d -> estimate==exact %d/%d, '
            'd56_ok %d; per-route best %d routes -> estimate==exact %d/%d, '
            'd56_ok %d (%.1fs)'
            % (report['top_n'],
               report['ranking_top']['estimate_equals_exact'],
               report['ranking_top']['built'],
               report['ranking_top']['exact_d56_ok'],
               report['per_route_best']['evaluated'],
               report['per_route_best']['estimate_equals_exact'],
               report['per_route_best']['built'],
               report['per_route_best']['exact_d56_ok'],
               time.time() - started))
    return report


def _reason_counter(route_results):
    counter = Counter()
    for route in route_results:
        for candidate in route['candidates']:
            if candidate['feasible']:
                counter['feasible'] += 1
                continue
            for reason in str(candidate['reason']).split('+'):
                counter[reason] += 1
    return counter


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * float(fraction)
    lower = int(math.floor(position))
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight)
                 + sorted_values[upper] * weight)


def build_mechanism_notes(routes, movable, route_results, events, stats,
                          plane_index, bodies, params, max_error, failures,
                          baseline_dir, layer_planes, started):
    """Explain estimates, definitions, verification totals and limitations."""
    route_count = len(routes)
    crossing_total = int((stats.get('totals') or {}).get('crossings') or 0)
    pairs_total = int((stats.get('totals') or {}).get('crossing_pairs') or 0)
    heights = int((stats.get('totals') or {}).get('audited_heights') or 0)
    planes_with_crossings = int(
        (stats.get('totals') or {}).get('planes_with_crossings') or 0)

    with_events = [item for item in route_results if item['crossings']]
    per_route_counts = sorted(len(item['crossings']) for item in with_events)
    cluster_counts = [len(item['clusters']) for item in with_events]
    candidate_total = sum(len(item['candidates']) for item in route_results)
    feasible_total = sum(1 for item in route_results
                         for candidate in item['candidates']
                         if candidate['feasible'])
    net_by_route = []
    for item in route_results:
        best = max((int(candidate['estimated_net'])
                    for candidate in item['candidates']
                    if candidate['feasible']), default=0)
        net_by_route.append(best)
    net_by_route.sort()
    net_values = [int(candidate['estimated_net']) for item in route_results
                  for candidate in item['candidates'] if candidate['feasible']]
    net_values.sort()
    removed_values = [int(candidate['estimated_removed']) for item in route_results
                      for candidate in item['candidates'] if candidate['feasible']]
    routes_at_least = {threshold: sum(1 for value in net_by_route if value >= threshold)
                       for threshold in (1, 2, 3, 5, 10)}

    # where do the crossings sit: straight vs arc, and clusters that cannot be
    # reached by any straight-run excursion at all
    crossing_kind = Counter()
    arc_locked_clusters = 0
    executable_clusters = 0
    for item in route_results:
        body = bodies[int(item['route_id'])]
        windows = executable_windows(body, params)
        for crossing in item['crossings']:
            s_value = float(crossing['s_mm'])
            kind = 'line'
            offset = 0.0
            for prim in body.prims:
                length = _prim_length(prim)
                if s_value <= offset + length + 1e-9:
                    kind = prim['kind']
                    break
                offset += length
            crossing_kind[kind] += 1
        crossings = item['crossings']
        for cluster in item['clusters']:
            low_s = float(cluster['s_start_mm']) - PAIR_EPS
            high_s = float(cluster['s_end_mm']) + PAIR_EPS
            members = [crossing for crossing in crossings
                       if low_s <= float(crossing['s_mm']) <= high_s]
            if cluster_executable(members, windows):
                executable_clusters += 1
            else:
                arc_locked_clusters += 1

    reasons = _reason_counter(route_results)
    # target-height occupancy (all flat parts at that height, incl. manual)
    target_stats = []
    stats_planes = {round(float(row['z_mm']), 9): row
                    for row in (stats.get('planes') or [])}
    for plane_id in params['target_plane_ids']:
        z_value = round(float(N.PLANE_Z[plane_id]), 9)
        row = stats_planes.get(z_value) or {}
        feasible_count = sum(1 for item in route_results
                             for candidate in item['candidates']
                             if candidate['feasible']
                             and int(candidate['target_plane_id']) == int(plane_id))
        best_net = max((int(candidate['estimated_net'])
                        for item in route_results
                        for candidate in item['candidates']
                        if candidate['feasible']
                        and int(candidate['target_plane_id']) == int(plane_id)),
                       default=None)
        target_stats.append(dict(
            target_plane_id=int(plane_id),
            target_plane_label=N.PLANE_LABEL[int(plane_id)],
            target_z=z_value,
            is_manual_plane=bool(int(plane_id) in params['manual_plane_ids']),
            flat_route_count=int(len(plane_index.route_ids.get(z_value, ()))),
            flat_primitive_count=int(plane_index.flat_part_count.get(z_value, 0)),
            existing_crossing_events=int(row.get('crossings') or 0),
            feasible_candidate_count=int(feasible_count),
            best_estimated_net=best_net))

    notes = dict(
        definitions=dict(
            movable_route='manual_group is empty (656 of 1024 routes)',
            body_flat='longest body flat of the route: parts[2] for the 926 lifted '
                      'routes, parts[0] for the 98 interface-direct routes',
            s_mm='arc length along the body flat only; interface leads are excluded',
            crossing='frozen E5 crossing_stats.json event (strict D56 legal '
                     'transverse crossing); mapped to s analytically',
            cluster='gap-connected run of one route\'s crossings, '
                    'gap=%.3f mm' % params['cluster_gap_mm'],
            candidate='excursion [s0, s1] on one straight line primitive: two '
                      'R15 S-curves + middle flat at target_z',
            estimated_removed='count of the route\'s source-height crossing '
                              'events with s in (s0, s1)',
            estimated_added='count of OTHER routes\' target-height flat crossings '
                            'with the route XY path inside [s0+f, s1-f]'),
        parameters=dict(params),
        verification=dict(
            baseline_dir=str(baseline_dir),
            routes_file_sha256=N.sha256_file(baseline_dir / 'routes_l3d.json'),
            crossing_stats_sha256=N.sha256_file(
                baseline_dir / 'crossing_stats.json'),
            route_count=int(route_count),
            movable_routes=int(len(movable)),
            movable_routes_with_body_flat=int(len(bodies)),
            crossing_events=int(len(events)),
            crossing_stats_totals=dict(crossings=crossing_total,
                                       crossing_pairs=pairs_total,
                                       audited_heights=heights,
                                       planes_with_crossings=planes_with_crossings),
            event_incidences_on_movable_body_flats=int(
                sum(len(item['crossings']) for item in route_results)),
            manual_route_event_involvement=int(
                sum(1 for event in events
                    if event.get('manual_a') or event.get('manual_b'))),
            max_crossing_projection_error_mm=round(float(max_error), 9),
            projection_failures=list(failures[:10]),
            mapping_failures=int(len(failures)),
        ),
        crossing_distribution_along_route=dict(
            routes_with_crossings=int(len(with_events)),
            routes_without_crossings=int(len(route_results) - len(with_events)),
            crossings_per_route_min=int(per_route_counts[0]) if per_route_counts else 0,
            crossings_per_route_median=round(_percentile(per_route_counts, 0.5), 6),
            crossings_per_route_p90=round(_percentile(per_route_counts, 0.9), 6),
            crossings_per_route_p99=round(_percentile(per_route_counts, 0.99), 6),
            crossings_per_route_max=int(per_route_counts[-1]) if per_route_counts else 0,
            crossings_per_route_mean=round(
                sum(per_route_counts) / float(len(per_route_counts)), 6)
            if per_route_counts else 0.0,
            clusters_per_route_median=round(_percentile(cluster_counts, 0.5), 6)
            if cluster_counts else 0.0,
            clusters_per_route_max=int(max(cluster_counts)) if cluster_counts else 0,
            clusters_total=int(sum(cluster_counts)),
            clusters_executable=int(executable_clusters),
            clusters_arc_locked=int(arc_locked_clusters),
            crossing_positions_on_line=int(crossing_kind.get('line', 0)),
            crossing_positions_on_arc=int(crossing_kind.get('arc', 0)),
            crossing_positions_on_line_fraction=round(
                crossing_kind.get('line', 0) / float(
                    max(1, crossing_kind.get('line', 0)
                        + crossing_kind.get('arc', 0))), 6),
        ),
        candidate_statistics=dict(
            candidates_total=int(candidate_total),
            candidates_feasible=int(feasible_total),
            candidates_feasible_fraction=round(
                feasible_total / float(max(1, candidate_total)), 6),
            reason_counts=OrderedDict(sorted(reasons.items())),
            feasible_candidates_with_estimated_net_ge_1=int(
                sum(1 for value in net_values if value >= 1)),
            feasible_candidates_with_estimated_net_ge_3=int(
                sum(1 for value in net_values if value >= 3)),
            feasible_candidates_with_estimated_net_ge_5=int(
                sum(1 for value in net_values if value >= 5)),
            routes_with_feasible_net_ge_1=int(routes_at_least[1]),
            routes_with_feasible_net_ge_2=int(routes_at_least[2]),
            routes_with_feasible_net_ge_3=int(routes_at_least[3]),
            routes_with_feasible_net_ge_5=int(routes_at_least[5]),
            routes_with_feasible_net_ge_10=int(routes_at_least[10]),
            best_feasible_estimated_net=int(net_values[-1]) if net_values else 0,
            best_feasible_estimated_removed=int(max(removed_values))
            if removed_values else 0,
            feasible_net_mean=round(sum(net_values) / float(len(net_values)), 6)
            if net_values else 0.0,
            feasible_net_median=round(_percentile(net_values, 0.5), 6),
            candidates_middle_over_max=int(sum(
                1 for item in route_results for candidate in item['candidates']
                if candidate['feasible'] and params['max_middle_mm'] is not None
                and float(candidate['middle_mm'] or 0.0)
                > float(params['max_middle_mm']))),
        ),
        target_height_occupancy=target_stats,
        approximations=[
            'estimated_added counts analytic geometric intersection points of the '
            'straight middle run against all other flats at target_z '
            '(line/line + line/arc); points are de-duplicated per partner route '
            'within 1e-6 mm and only transverse contacts (angle >= %.1f deg) are '
            'counted as crossings; collinear overlaps and tangent contacts are '
            'reported separately (never counted as crossings).' % MIN_CROSS_ANGLE_DEG,
            'the frozen audit runs the strict D56 pair policy; this analysis does '
            'not re-audit D56 validity, so individually impossible spacing near '
            'misses are not part of estimated_added.',
            'estimated_removed counts crossing events in the open interval (s0, s1); '
            'feasible candidates have an empty 1.25 mm transition-shadow window at '
            'both source-height ends, so every removed event really disappears.',
            'the landing-side (target-height) shadow is checked as an extra '
            'feasibility guard (the S-curve is also within 50 um of the target '
            'plane near that end); shadow_ok in the schema refers to the '
            'source-height rule, target_shadow_ok is reported next to it.',
            'manual-plane target heights are evaluated (they are among the 21 '
            'heights) but flagged with target_is_manual_plane because the frozen '
            'manual routes occupy those planes.',
            'one excursion covers one gap-cluster piece on one straight run; '
            'multi-excursion routes and batch interactions between simultaneously '
            'moved routes are out of scope (experiment B evaluates those).'],
    )
    return notes


# ============================================================ reports
def _pick_top(route_results, limit=30, dedupe='interval'):
    """Best feasible candidates; ``dedupe`` keeps one entry per route/interval."""
    entries = []
    for route in route_results:
        for candidate in route['candidates']:
            if candidate['feasible'] and int(candidate['estimated_net']) >= 1:
                entries.append((route, candidate))
    entries.sort(key=lambda pair: (-int(pair[1]['estimated_net']),
                                   pair[1]['middle_mm'],
                                   int(pair[0]['route_id']),
                                   float(pair[1]['target_z'])))
    if dedupe is None:
        return entries[:limit]
    seen = set()
    unique = []
    for route, candidate in entries:
        if dedupe == 'route':
            key = int(route['route_id'])
        else:
            key = (int(route['route_id']),
                   round(float(candidate['cluster_start_mm']), 3),
                   round(float(candidate['cluster_end_mm']), 3))
        if key in seen:
            continue
        seen.add(key)
        unique.append((route, candidate))
        if len(unique) >= limit:
            break
    return unique


def write_report(result, out_dir):
    """Chinese analysis report (concise, deterministic)."""
    notes = result['mechanism_notes']
    params = notes['parameters']
    verification = notes['verification']
    distribution = notes['crossing_distribution_along_route']
    stats = notes['candidate_statistics']
    occupancy = notes['target_height_occupancy']
    routes = result['routes']
    routes_by_id = {int(item['route_id']): item
                    for item in result['routes']}
    top = _pick_top(routes, 30)

    lines = []
    lines.append('# Native 3D 同层交叉位置与中部换层区间分析（实验 B 输入）')
    lines.append('')
    lines.append('## 1. 数据与口径')
    lines.append('')
    lines.append('- 冻结基线：`%s`（只读，未修改）。' % result['baseline_dir'])
    lines.append('- 基线 %d 条路由，其中可移动（非手工组）路由 **%d** 条；'
                 '交叉事件 **%d** 个 / %d 对，严格 D56 合法横穿。'
                 % (result['route_count'], result['movable_routes'],
                    verification['crossing_events'],
                    verification['crossing_stats_totals']['crossing_pairs']))
    lines.append('- 每个可移动路由只分析其**本体 flat**（lifted 路线为 parts[2]，'
                 'interface-direct 路线为 parts[0]），参数 `s` 为本体 flat 弧长；'
                 '接口 0.25 mm 引线不参与。')
    lines.append('- 交叉事件 (x, y) 用解析线/圆弧参数映射到本体弧长，最大映射误差 '
                 '%.2e mm，失败 %d 个。'
                 % (verification['max_crossing_projection_error_mm'],
                    verification['mapping_failures']))
    lines.append('- 聚类：沿 `s` 间距 ≤ %.1f mm 的交叉事件归为一簇；'
                 '候选：在**同一段直线 primitive** 上放置 [s0, s1]，'
                 '两条 R15 S 曲线 + 目标高度中段，要求 '
                 '`s1-s0 ≥ 2*footprint(dz) + %.1f mm`，且两端 1.25 mm '
                 'transition-shadow（源高度上无其他 flat 横穿）。'
                 % (params['cluster_gap_mm'], params['min_middle_mm']))
    lines.append('- 估计口径：removed = 落入 (s0, s1) 的源高度交叉事件数；'
                 'added = 目标高度其他路由 flat 与本路线 XY 路径在 [s0+f, s1-f] '
                 '内的合法横穿点（解析交点、按伙伴去重、夹角 ≥5°）；net = removed − added。')
    lines.append('')
    lines.append('## 2. 交叉沿路径的分布')
    lines.append('')
    lines.append('- 有本体层交叉的可移动路由 **%d** 条（无交叉 %d 条）；'
                 '每路线交叉数：中位 %s，P90 %s，P99 %s，最大 %d，均值 %.2f。'
                 % (distribution['routes_with_crossings'],
                    distribution['routes_without_crossings'],
                    distribution['crossings_per_route_median'],
                    distribution['crossings_per_route_p90'],
                    distribution['crossings_per_route_p99'],
                    distribution['crossings_per_route_max'],
                    distribution['crossings_per_route_mean']))
    lines.append('- 共 **%d** 个簇（可执行 %d 个；交叉落在圆弧段或直线段端点 '
                 '1.25 mm shadow 内、没有可用直线窗口 %d 个），'
                 '每路线簇数中位 %s，最大 %d。'
                 % (distribution['clusters_total'],
                    distribution['clusters_executable'],
                    distribution['clusters_arc_locked'],
                    distribution['clusters_per_route_median'],
                    distribution['clusters_per_route_max']))
    lines.append('- 交叉事件位置：直线段 %d 个（%.1f%%），圆弧段 %d 个（%.1f%%）——'
                 '圆弧段上的交叉无法用“直线段中部换层”移除，是本分析的结构性上限。'
                 % (distribution['crossing_positions_on_line'],
                    100.0 * distribution['crossing_positions_on_line_fraction'],
                    distribution['crossing_positions_on_arc'],
                    100.0 * (1.0 - distribution['crossing_positions_on_line_fraction'])))
    lines.append('')
    lines.append('## 3. 候选估计结果')
    lines.append('')
    lines.append('- 共评估候选 **%d** 个（可执行簇 × 20 个其他高度），其中几何+shadow 可行 '
                 '**%d** 个（%.1f%%）。'
                 % (stats['candidates_total'], stats['candidates_feasible'],
                    100.0 * stats['candidates_feasible_fraction']))
    lines.append('- 可行候选中：estimated_net ≥1 的 **%d** 个，≥3 的 %d 个，'
                 '≥5 的 %d 个；单候选最好 net = **%d**，单候选最多移除 %d 个交叉。'
                 % (stats['feasible_candidates_with_estimated_net_ge_1'],
                    stats['feasible_candidates_with_estimated_net_ge_3'],
                    stats['feasible_candidates_with_estimated_net_ge_5'],
                    stats['best_feasible_estimated_net'],
                    stats['best_feasible_estimated_removed']))
    lines.append('- 至少有一个可行候选 net≥1 的路由 **%d** 条；net≥3 的 **%d** 条；'
                 'net≥5 的 **%d** 条；net≥10 的 %d 条。'
                 % (stats['routes_with_feasible_net_ge_1'],
                    stats['routes_with_feasible_net_ge_3'],
                    stats['routes_with_feasible_net_ge_5'],
                    stats['routes_with_feasible_net_ge_10']))
    lines.append('- 不可行原因计数（可多个并存）：%s。'
                 % '，'.join('%s=%d' % (key, value)
                            for key, value in stats['reason_counts'].items()
                            if key != 'feasible'))
    lines.append('')
    lines.append('## 4. Top-30 候选（按 estimated_net 排序）')
    lines.append('')
    lines.append('| # | route | 本体层 | 簇区间 s (mm) | 簇内交叉 | 目标高度 z (mm) | '
                 '中段 (mm) | removed | added | net |')
    lines.append('|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|')
    for rank, (route, candidate) in enumerate(top, start=1):
        lines.append('| %d | %d | %s(%.2f) | %.2f–%.2f | %d | %.2f | %.2f | %d | %d | **%d** |'
                     % (rank, route['route_id'], route['body_layer_label'],
                        route['body_z'], candidate['cluster_start_mm'],
                        candidate['cluster_end_mm'], candidate['cluster_count'],
                        candidate['target_z'], candidate['middle_mm'],
                        candidate['estimated_removed'],
                        candidate['estimated_added'],
                        candidate['estimated_net']))
    lines.append('')
    lines.append('## 5. 估计的边界与限制因素')
    lines.append('')
    lines.append('1. **shadow / 可放置性是第一限制**：source 端 1.25 mm 空窗由候选区间'
                 '“吸附”自动满足（`shadow_source` 冲突 0 次），代价是区间被迫伸缩；'
                 '真正无法构造候选的是 `no_shadow_clear_placement` %d 次与 '
                 '`straight_run_too_short` %d 次，落点侧 shadow 冲突 '
                 '`shadow_target` %d 次。'
                 % (stats['reason_counts'].get('no_shadow_clear_placement', 0),
                    stats['reason_counts'].get('straight_run_too_short', 0),
                    stats['reason_counts'].get('shadow_target', 0)))
    lines.append('2. **直线段可用性**：%d 个簇（×20 个目标高度不生成候选）完全落在圆弧段'
                 '或直线段端部 shadow 内；另有目标高度上与其他 flat 重叠/相切/间距风险'
                 '（target_overlap_middle %d、target_overlap_shadow %d、'
                 'target_tangent_contact %d 次）。'
                 % (distribution['clusters_arc_locked'],
                    stats['reason_counts'].get('target_overlap_middle', 0),
                    stats['reason_counts'].get('target_overlap_shadow', 0),
                    stats['reason_counts'].get('target_tangent_contact', 0)))
    lines.append('3. **目标高度占用**：中段越长、目标高度越拥挤，added 越多。'
                 '各目标高度的可行候选数与最好 net 见 JSON 的 '
                 '`target_height_occupancy`；其中手工高度（目标 z 属于 L2–L5/L10–L13）'
                 '被冻结手工路由占用，估计净收益整体偏低。')
    lines.append('4. 本估计不重新执行 D56 审计，也不考虑多路线同时换层后的相互影响；'
                 '实验 B 必须用精确评估（`native3d.single_route.evaluate_candidate` '
                 '或 `native3d.crossing_cache`）复核候选。')
    lines.append('5. 中段长度：advisory max = %.0f mm（`MAX_MIDDLE_MM`），'
                 '可行候选中超过该值的有 %d 个；排序已按 net 优先、中段长度次序，'
                 '实验 B 可对过长中段的候选加长度代价。'
                 % (float(params['max_middle_mm'] or 0.0),
                    stats['candidates_middle_over_max']))
    validation = notes.get('spot_validation') or {}
    if validation.get('available'):
        top_stats = validation.get('ranking_top') or {}
        best_stats = validation.get('per_route_best') or {}
        lines.append('')
        lines.append('## 5.1 估计精度：对精确 strict-D56 缓存的抽检')
        lines.append('')
        lines.append('- Ranking 前 %d 个候选：可构建 %d 个，`estimated_net == exact_net` '
                     '**%d/%d**，精确 D56 通过 **%d/%d**（%.1f%%）。'
                     % (validation.get('top_n', 0), top_stats.get('built', 0),
                        top_stats.get('estimate_equals_exact', 0),
                        top_stats.get('built', 0),
                        top_stats.get('exact_d56_ok', 0),
                        top_stats.get('built', 0),
                        100.0 * top_stats.get('exact_d56_ok', 0)
                        / float(max(1, top_stats.get('built', 0)))))
        lines.append('- 每条“有正收益候选”路由的最优候选（%d 条路由）：'
                     '`estimated_net == exact_net` **%d/%d**，精确 D56 通过 **%d/%d**。'
                     % (best_stats.get('evaluated', 0),
                        best_stats.get('estimate_equals_exact', 0),
                        best_stats.get('built', 0),
                        best_stats.get('exact_d56_ok', 0),
                        best_stats.get('built', 0)))
        lines.append('- 被精确 D56 拒绝的少量候选是目标高度上的**间距过近**（不是交叉数'
                     '估计错误），实验 B 的精确评估会剔除它们。')
    lines.append('')
    lines.append('## 6. 结论：一次换层能否移除多个交叉？')
    lines.append('')
    lines.append('- 能。数据中可行候选的最大 estimated_removed = %d，最大 '
                 'estimated_net = **%d**；net≥3 的候选 %d 个、net≥5 的 %d 个，'
                 '说明一次换层可以同时移除（并避免新增）多个同层交叉。'
                 % (stats['best_feasible_estimated_removed'],
                    stats['best_feasible_estimated_net'],
                    stats['feasible_candidates_with_estimated_net_ge_3'],
                    stats['feasible_candidates_with_estimated_net_ge_5']))
    lines.append('- 正收益并不稀少（可行候选中 net≥1 占 %.0f%%），但按路由看只有 '
                 '**%d/%d** 条可移动路由存在正收益候选；收益集中在交叉数最多的路由上，'
                 '一次换层有效移除量典型为 2–6 个交叉。'
                 % (100.0 * stats['feasible_candidates_with_estimated_net_ge_1']
                    / float(max(1, stats['candidates_feasible'])),
                    stats['routes_with_feasible_net_ge_1'], len(routes)))
    lines.append('- 因此实验 B 的策略应是：只对 top 候选做批量换层，其余路由保持 2D 基线；'
                 '并逐候选用精确 D56/3D 评估确认后再接受。')
    lines.append('')
    lines.append('_由 `four_side_1024/fanout1024/native3d/crossing_intervals.py` 生成；'
                 '所有数值均来自冻结 E5 基线与解析几何，确定性输出（无时间戳/随机数）。_')
    text = '\n'.join(lines) + '\n'
    path = Path(out_dir) / 'analysis' / 'crossing_intervals_report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def write_summary_for_lead(result, out_dir):
    """<=25 lines Chinese summary: top candidates + the multiple-crossing answer."""
    notes = result['mechanism_notes']
    stats = notes['candidate_statistics']
    distribution = notes['crossing_distribution_along_route']
    top = _pick_top(result['routes'], 5, dedupe='route')
    lines = []
    lines.append('# 交叉区间分析 → Lead 摘要')
    lines.append('')
    lines.append('输入：冻结 E5（只读）；可移动路由 %d；交叉事件 %d；'
                 '分析对象=本体 flat 弧长。' % (result['movable_routes'],
                                            notes['verification']['crossing_events']))
    lines.append('')
    lines.append('Top-5 候选（route / 本体层 / 簇区间 s / 目标高度 / removed→added = net）：')
    for rank, (route, candidate) in enumerate(top, start=1):
        lines.append('%d. r%d %s(z=%.2f) s=%.2f–%.2f (%.0f mm, 簇内 %d 交叉) → %s(z=%.2f) '
                     'removed=%d added=%d **net=%d** middle=%.2fmm'
                     % (rank, route['route_id'], route['body_layer_label'],
                        route['body_z'], candidate['cluster_start_mm'],
                        candidate['cluster_end_mm'],
                        candidate['cluster_end_mm'] - candidate['cluster_start_mm'],
                        candidate['cluster_count'],
                        candidate['target_plane_label'], candidate['target_z'],
                        candidate['estimated_removed'],
                        candidate['estimated_added'],
                        candidate['estimated_net'],
                        candidate['middle_mm']))
    lines.append('')
    lines.append('规模：候选 %d 个，可行 %d 个；可行中 net≥1 的 %d 个、≥3 的 %d 个、'
                 '≥5 的 %d 个。' % (stats['candidates_total'],
                                   stats['candidates_feasible'],
                                   stats['feasible_candidates_with_estimated_net_ge_1'],
                                   stats['feasible_candidates_with_estimated_net_ge_3'],
                                   stats['feasible_candidates_with_estimated_net_ge_5']))
    lines.append('路线级：至少一个可行候选 net≥1 的路由 %d 条；≥3 的 %d 条；≥5 的 %d 条；'
                 '≥10 的 %d 条。'
                 % (stats['routes_with_feasible_net_ge_1'],
                    stats['routes_with_feasible_net_ge_3'],
                    stats['routes_with_feasible_net_ge_5'],
                    stats['routes_with_feasible_net_ge_10']))
    lines.append('单候选上限：removed 最多 %d，net 最好 %d，中段长度通常 %.1f–%.1f mm。'
                 % (stats['best_feasible_estimated_removed'],
                    stats['best_feasible_estimated_net'],
                    min((candidate['middle_mm'] for _r, candidate in top), default=0.0),
                    max((candidate['middle_mm'] for _r, candidate in top), default=0.0)))
    lines.append('')
    lines.append('一次换层能否移除多个交叉？**能**：可行候选中 net≥3 有 %d 个、'
                 'net≥5 有 %d 个，最好 net=%d（removed=%d）。'
                 % (stats['feasible_candidates_with_estimated_net_ge_3'],
                    stats['feasible_candidates_with_estimated_net_ge_5'],
                    stats['best_feasible_estimated_net'],
                    stats['best_feasible_estimated_removed']))
    lines.append('注意：正收益集中在交叉多的路由；按路由看 %d/%d 条可移动路由有正收益候选，'
                 '其中 %d 条 net≥3、%d 条 net≥5。'
                 % (stats['routes_with_feasible_net_ge_1'], len(result['routes']),
                    stats['routes_with_feasible_net_ge_3'],
                    stats['routes_with_feasible_net_ge_5']))
    validation = notes.get('spot_validation') or {}
    if validation.get('available'):
        top_stats = validation.get('ranking_top') or {}
        best_stats = validation.get('per_route_best') or {}
        lines.append('精确 strict-D56 抽检：ranking 前 %d 候选 estimate==exact %d/%d、'
                     'D56 通过 %d/%d；各路由最优候选 estimate==exact %d/%d、D56 通过 %d/%d。'
                     % (validation.get('top_n', 0),
                        top_stats.get('estimate_equals_exact', 0),
                        top_stats.get('built', 0),
                        top_stats.get('exact_d56_ok', 0),
                        top_stats.get('built', 0),
                        best_stats.get('estimate_equals_exact', 0),
                        best_stats.get('built', 0),
                        best_stats.get('exact_d56_ok', 0),
                        best_stats.get('built', 0)))
    lines.append('交叉位置的 %.0f%% 在圆弧段、无法用直线段换层移除（结构性上限）。'
                 % (100.0 * (1.0 - distribution['crossing_positions_on_line_fraction'])))
    lines.append('')
    lines.append('主要限制因素：①区间可放置性（shadow 吸附后无法构造候选 '
                 'no_shadow_clear_placement %d 次、straight_run_too_short %d 次、'
                 '落点 shadow_target %d 次）；'
                 '②圆弧段/端部不可用（%d 个簇不生成候选）；③目标高度占用推高 added。'
                 % (stats['reason_counts'].get('no_shadow_clear_placement', 0),
                    stats['reason_counts'].get('straight_run_too_short', 0),
                    stats['reason_counts'].get('shadow_target', 0),
                    distribution['clusters_arc_locked']))
    lines.append('')
    lines.append('产物：analysis/crossing_intervals.json（656 条可移动路由、逐候选估计）、'
                 'crossing_intervals_report.md、plots/*.png。'
                 '建议实验 B 只取 ranking 顶部候选做精确评估，其余保持 2D 基线。')
    text = '\n'.join(lines) + '\n'
    path = Path(out_dir) / 'analysis' / 'crossing_intervals_summary_for_lead.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


# ============================================================ plots
def make_plots(result, out_dir, top_routes=5):
    """Crossing profiles for the highest-crossing routes + net-gain histogram."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:                                   # pragma: no cover
        return []
    plots_dir = Path(out_dir) / 'analysis' / 'plots'
    plots_dir.mkdir(parents=True, exist_ok=True)
    written = []
    routes = sorted(result['routes'], key=lambda item: (-len(item['crossings']),
                                                       item['route_id']))
    for route in routes[:top_routes]:
        if not route['crossings']:
            continue
        figure, axis = plt.subplots(figsize=(9, 3.2))
        for cluster in route['clusters']:
            axis.axvspan(cluster['s_start_mm'], cluster['s_end_mm'],
                         color='#ffd27f', alpha=0.45, linewidth=0)
        positions = [item['s_mm'] for item in route['crossings']]
        angles = [item['angle_deg'] for item in route['crossings']]
        axis.vlines(positions, 0.0, angles, color='#1f4e9c', linewidth=1.0)
        axis.scatter(positions, angles, s=14, color='#1f4e9c', zorder=3)
        axis.set_xlim(0.0, max(1.0, route['path_length_mm']))
        axis.set_xlabel('body-flat arc length s (mm)')
        axis.set_ylabel('crossing angle (deg)')
        axis.set_title('route %d  %s z=%.2f mm  crossings=%d  clusters=%d'
                       % (route['route_id'], route['body_layer_label'],
                          route['body_z'], len(route['crossings']),
                          len(route['clusters'])), fontsize=10)
        figure.tight_layout()
        path = plots_dir / ('crossing_profile_route_%04d.png' % route['route_id'])
        figure.savefig(path, dpi=130)
        plt.close(figure)
        written.append(str(path.relative_to(Path(out_dir))))
    net_values = [int(candidate['estimated_net'])
                  for route in result['routes']
                  for candidate in route['candidates'] if candidate['feasible']]
    best_per_route = []
    for route in result['routes']:
        values = [int(candidate['estimated_net']) for candidate in route['candidates']
                  if candidate['feasible']]
        if values:
            best_per_route.append(max(values))
    figure, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    if net_values:
        low, high = min(net_values), max(net_values)
        bins = range(low, high + 2)
        axes[0].hist(net_values, bins=list(bins), color='#1f4e9c', rwidth=0.85)
    axes[0].set_xlabel('estimated net (removed - added)')
    axes[0].set_ylabel('feasible candidates')
    axes[0].set_title('all feasible candidates', fontsize=10)
    if best_per_route:
        low, high = min(best_per_route), max(best_per_route)
        axes[1].hist(best_per_route, bins=list(range(low, high + 2)),
                     color='#d9822b', rwidth=0.85)
    axes[1].set_xlabel('best estimated net per route')
    axes[1].set_ylabel('routes')
    axes[1].set_title('per-route best', fontsize=10)
    figure.tight_layout()
    path = plots_dir / 'estimated_net_histogram.png'
    figure.savefig(path, dpi=130)
    plt.close(figure)
    written.append(str(path.relative_to(Path(out_dir))))
    return written


# ============================================================ CLI
def summary_stdout(result):
    stats = result['mechanism_notes']['candidate_statistics']
    distribution = result['mechanism_notes']['crossing_distribution_along_route']
    lines = [
        'crossing-interval analysis: %d routes (%d movable), '
        '%d crossing events' % (result['route_count'],
                                result['movable_routes'],
                                result['mechanism_notes']['verification']
                                ['crossing_events']),
        '  routes with body-layer crossings: %d, clusters: %d '
        '(arc-locked %d, straight-executable %d)'
        % (distribution['routes_with_crossings'],
           distribution['clusters_total'],
           distribution['clusters_arc_locked'],
           distribution['clusters_executable']),
        '  candidates: %d total, %d feasible; net>=1: %d, net>=3: %d, net>=5: %d'
        % (stats['candidates_total'], stats['candidates_feasible'],
           stats['feasible_candidates_with_estimated_net_ge_1'],
           stats['feasible_candidates_with_estimated_net_ge_3'],
           stats['feasible_candidates_with_estimated_net_ge_5']),
        '  routes with a feasible net>=1: %d, >=3: %d, >=5: %d, >=10: %d'
        % (stats['routes_with_feasible_net_ge_1'],
           stats['routes_with_feasible_net_ge_3'],
           stats['routes_with_feasible_net_ge_5'],
           stats['routes_with_feasible_net_ge_10']),
        '  best feasible net: %d (max removed %d)'
        % (stats['best_feasible_estimated_net'],
           stats['best_feasible_estimated_removed']),
    ]
    return '\n'.join(lines)


def run(baseline_dir, out_dir, cluster_gap_mm=DEFAULT_CLUSTER_GAP_MM,
        shadow_mm=DEFAULT_SHADOW_MM, min_middle_mm=DEFAULT_MIN_MIDDLE_MM,
        max_middle_mm=DEFAULT_MAX_MIDDLE_MM,
        end_margin_mm=DEFAULT_END_MARGIN_MM, target_plane_ids=None,
        validate_top=DEFAULT_VALIDATE_TOP, plots=True, log=None):
    """Analyse, write the three artifacts and return the result payload."""
    result = analyse(baseline_dir, cluster_gap_mm=cluster_gap_mm,
                     shadow_mm=shadow_mm, min_middle_mm=min_middle_mm,
                     max_middle_mm=max_middle_mm, end_margin_mm=end_margin_mm,
                     target_plane_ids=target_plane_ids, log=log)
    out_dir = Path(out_dir)
    if validate_top and int(validate_top) > 0:
        routes_by_id = {int(record['route_id']):
                        record for record in
                        N.load_json(Path(baseline_dir) / 'routes_l3d.json')['routes']}
        result['mechanism_notes']['spot_validation'] = spot_validate(
            routes_by_id, result['routes'], result['ranking'],
            top_n=int(validate_top), log=log)
    else:
        result['mechanism_notes']['spot_validation'] = dict(
            available=False, reason='disabled (validate-top=0)')
    analysis_dir = out_dir / 'analysis'
    analysis_dir.mkdir(parents=True, exist_ok=True)
    plots_paths = make_plots(result, out_dir) if plots else []
    result['mechanism_notes']['plots'] = plots_paths
    json_path = analysis_dir / 'crossing_intervals.json'
    C.write_json(json_path, result, indent=1)
    report_path = write_report(result, out_dir)
    summary_path = write_summary_for_lead(result, out_dir)
    if log:
        for path in (json_path, report_path, summary_path):
            log('[intervals] wrote %s (%.2f MB)' % (
                path, path.stat().st_size / 1e6))
        for path in plots_paths:
            log('[intervals] wrote %s' % (out_dir / path))
    return result


def _parse_target_planes(text):
    if not text:
        return None
    ids = []
    for token in str(text).split(','):
        token = token.strip()
        if not token:
            continue
        ids.append(int(token))
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Native 3D crossing-position / excursion interval analysis')
    parser.add_argument('--baseline-dir', default=str(N.E5_DIR),
                        help='frozen E5 run dir (read only)')
    parser.add_argument('--out-dir', default=str(N.RUN_DIR),
                        help='new experiment run dir (writes <out>/analysis)')
    parser.add_argument('--cluster-gap-mm', type=float,
                        default=DEFAULT_CLUSTER_GAP_MM,
                        help='crossing cluster gap along the body path (mm)')
    parser.add_argument('--shadow-mm', type=float, default=DEFAULT_SHADOW_MM,
                        help='transition-shadow window at both excursion ends (mm)')
    parser.add_argument('--min-middle-mm', type=float,
                        default=DEFAULT_MIN_MIDDLE_MM,
                        help='minimum middle-flat length at the target height (mm)')
    parser.add_argument('--max-middle-mm', type=float,
                        default=DEFAULT_MAX_MIDDLE_MM,
                        help='advisory maximum middle-flat length (mm)')
    parser.add_argument('--end-margin-mm', type=float,
                        default=DEFAULT_END_MARGIN_MM,
                        help='keep the excursion this far from the body-flat ends (mm)')
    parser.add_argument('--target-planes', default=None,
                        help='comma separated target plane ids (default: all 21)')
    parser.add_argument('--validate-top', type=int, default=DEFAULT_VALIDATE_TOP,
                        help='exact strict-D56 spot validation of this many top '
                             'ranking candidates (0 disables)')
    parser.add_argument('--no-plots', action='store_true',
                        help='do not write analysis/plots')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    log = None if args.quiet else (lambda message: print(message, flush=True))
    started = time.time()
    result = run(args.baseline_dir, args.out_dir,
                 cluster_gap_mm=args.cluster_gap_mm,
                 shadow_mm=args.shadow_mm,
                 min_middle_mm=args.min_middle_mm,
                 max_middle_mm=(None if args.max_middle_mm is None
                                else args.max_middle_mm),
                 end_margin_mm=args.end_margin_mm,
                 target_plane_ids=_parse_target_planes(args.target_planes),
                 validate_top=args.validate_top,
                 plots=not args.no_plots, log=log)
    if not args.quiet:
        print(summary_stdout(result))
        print('runtime: %.1fs' % (time.time() - started))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
