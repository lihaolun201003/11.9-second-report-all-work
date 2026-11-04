# -*- coding: utf-8 -*-
"""G4-1 independent geometry-contract metrics for the 1024-route XYZ joint run.

This module is DELIBERATELY INDEPENDENT of the historical audit code: it does not
import ``validate_fslw`` / ``nonc4.crossings`` / ``validate21`` to compute any
number.  Every quantity below is recomputed from ``routes_l3d.json`` with this
module's own 2-D primitive distance / intersection algebra, its own spatial grid
and its own arc-length minimisers.  The only project code it uses is *data*
(``fanout1024.common`` for the true 1024 connections and port table, and
``reheight21.model`` for the 21-height table) plus ``fsd25d.path3d`` **only** to
cross-check the analytic transition formula (never to compute a reported value).

Geometric model (taken from the JSON primitives themselves)
-----------------------------------------------------------
* ``flat`` part   : ``line`` (2-D segment) or ``arc`` (exact circular arc),
                    at constant physical height ``z``.
* ``transition``  : exact S-curve = two circular arcs of radius R=15 mm lying in
                    the vertical plane that contains the local axis direction.
                    Re-implemented analytically from (start, direction, z0, z1,
                    R, theta):  u(phi)=R sin(phi), w(phi)=z0+sign*R(1-cos(phi))
                    for the first arc, mirrored for the second one.  This is
                    *not* a polyline approximation; the step is only used for
                    coarse bracketing and every reported minimum is refined.

Reported numerics
-----------------
* flat-flat 2-D distances          : closed-form (line-line / line-arc / arc-arc),
                                     error <= 1e-12 mm.
* flat-transition 3-D distances    : 1-D minimisation of the exact analytic
                                     curve distance, golden-section tol 1e-10,
                                     error <= 1e-8 mm.
* transition-transition 3-D        : coarse grid (1-Lipschitz bracket) + nested
                                     golden-section coordinate refinement,
                                     error <= 1e-6 mm.
* crossings                        : exact quadratic / circle-circle solutions,
                                     residual reported.

CLI::

    python -m four_side_1024.fanout1024.xyzrouter.g4.independent_metrics \
        [--run-dir ...] [--out-dir ...]

Writes ``independent_metrics.json`` and ``min_distance_evidence.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TAU = 2.0 * math.pi

# ---- contract constants (values live in the code; quoted in the report) ------
CLEARANCE_2D_MM = 0.08          # fanout1024/common.py CLEARANCE_2D_MM
WIDTH_MM = 0.05                 # fanout1024/common.py WIDTH_MM
EDGE_GAP_MM = 0.03              # fanout1024/common.py EDGE_GAP_MM
MIN_3D_CLEARANCE_MM = 0.05      # fanout1024/common.py MIN_3D_CLEARANCE_MM
MIN_LAYER_PITCH_MM = 0.05       # fanout1024/common.py MIN_LAYER_PITCH_MM
R15_MM = 15.0                   # fanout1024/common.py MIN_BEND_RADIUS_MM
MIN_CROSS_ANGLE_DEG = 5.0       # fslw/config.py MIN_CROSS_ANGLE_DEG
STRICT_MAX_HALF_WINDOW_MM = 4.0  # fslw/validate_fslw.py STRICT_MAX_HALF_WINDOW
SAGITTA_MM = 0.0005
GLASS_XY_MM = 150.0
GLASS_Z_MIN_MM = -0.35
GLASS_Z_MAX_MM = 0.65
WAVEGUIDE_HALF_WIDTH_MM = WIDTH_MM / 2.0
BOARD_MM = 150.0

GRID_CELL_MM = 1.0              # candidate grid (2-D XY)
GRID_PAD_MM = 0.20              # 3-D region of interest radius
LIMIT_2D = CLEARANCE_2D_MM - 1e-7
LIMIT_3D = MIN_3D_CLEARANCE_MM - 1e-9

DEFAULT_RUN = (ROOT / 'outputs' / 'manual_c4_new_connectivity' /
               'XYZ_JOINT_G123_1024' / 'best_valid')
DEFAULT_OUT = ROOT / 'experiments' / 'xyz_joint_g4_1024' / '00_baseline_audit'
EXPECTED_ROUTES_SHA256 = ('711cf910d5c75ea788be877ef88b588fe3d9a90a2ae2d3636bb5b5896834077')


# ===========================================================================
# small scalar 2-D geometry
# ===========================================================================
def clamp01(value):
    return 0.0 if value <= 0.0 else (1.0 if value >= 1.0 else value)


def point_seg_dist(px, py, x0, y0, x1, y1):
    dx = x1 - x0
    dy = y1 - y0
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / length2
    t = clamp01(t)
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def angle_in_arc(angle, start, sweep, tol=1e-12):
    if sweep >= 0.0:
        delta = (angle - start) % TAU
        return delta <= sweep + tol
    delta = (start - angle) % TAU
    return delta <= (-sweep) + tol


def arc_point(arc, t):
    angle = arc['start'] + arc['sweep'] * t
    return (arc['center'][0] + arc['radius'] * math.cos(angle),
            arc['center'][1] + arc['radius'] * math.sin(angle))


def arc_tangent(arc, t):
    angle = arc['start'] + arc['sweep'] * t
    sign = 1.0 if arc['sweep'] >= 0.0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def prim_point(prim, t):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
    return arc_point(prim, t)


def prim_tangent(prim, t):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        norm = math.hypot(dx, dy)
        return (dx / norm, dy / norm)
    return arc_tangent(prim, t)


def prim_length(prim):
    if prim['kind'] == 'line':
        return math.hypot(prim['p1'][0] - prim['p0'][0],
                          prim['p1'][1] - prim['p0'][1])
    return abs(prim['sweep']) * prim['radius']


def point_prim_dist(px, py, prim):
    """Exact 2-D distance from a point to a line segment or circular arc."""
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return point_seg_dist(px, py, p0[0], p0[1], p1[0], p1[1])
    cx, cy = prim['center']
    radius = prim['radius']
    vx, vy = px - cx, py - cy
    d = math.hypot(vx, vy)
    if d > 1e-15:
        angle = math.atan2(vy, vx)
        if angle_in_arc(angle, prim['start'], prim['sweep']):
            return abs(d - radius)
    p0 = prim['p0']
    p1 = prim['p1']
    return min(math.hypot(px - p0[0], py - p0[1]),
               math.hypot(px - p1[0], py - p1[1]))


# ---- vectorised point-primitive distance (for dense scans) ------------------
def point_prim_dist_array(xs, ys, prim):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length2 = dx * dx + dy * dy
        if length2 <= 0.0:
            return np.hypot(xs - p0[0], ys - p0[1])
        t = ((xs - p0[0]) * dx + (ys - p0[1]) * dy) / length2
        t = np.clip(t, 0.0, 1.0)
        return np.hypot(xs - (p0[0] + t * dx), ys - (p0[1] + t * dy))
    cx, cy = prim['center']
    radius = prim['radius']
    vx = xs - cx
    vy = ys - cy
    d = np.hypot(vx, vy)
    angle = np.arctan2(vy, vx)
    start = prim['start']
    sweep = prim['sweep']
    if sweep >= 0.0:
        delta = np.mod(angle - start, TAU)
        inside = delta <= sweep + 1e-12
    else:
        delta = np.mod(start - angle, TAU)
        inside = delta <= (-sweep) + 1e-12
    dist = np.abs(d - radius)
    p0 = prim['p0']
    p1 = prim['p1']
    endpoint = np.minimum(np.hypot(xs - p0[0], ys - p0[1]),
                          np.hypot(xs - p1[0], ys - p1[1]))
    return np.where(inside, dist, endpoint)


# ---- segment / arc / arc distance ------------------------------------------
def seg_seg_dist(a0, a1, b0, b1):
    d1x = a1[0] - a0[0]
    d1y = a1[1] - a0[1]
    d2x = b1[0] - b0[0]
    d2y = b1[1] - b0[1]
    rx = a0[0] - b0[0]
    ry = a0[1] - b0[1]
    a = d1x * d1x + d1y * d1y
    e = d2x * d2x + d2y * d2y
    f = d2x * rx + d2y * ry
    if a <= 1e-30 and e <= 1e-30:
        return math.hypot(rx, ry)
    if a <= 1e-30:
        s = 0.0
        t = clamp01(f / e)
    else:
        c = d1x * rx + d1y * ry
        if e <= 1e-30:
            t = 0.0
            s = clamp01(-c / a)
        else:
            b = d1x * d2x + d1y * d2y
            denom = a * e - b * b
            s = clamp01((b * f - c * e) / denom) if denom > 1e-30 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = clamp01(-c / a)
            elif t > 1.0:
                t = 1.0
                s = clamp01((b - c) / a)
    px = a0[0] + d1x * s - (b0[0] + d2x * t)
    py = a0[1] + d1y * s - (b0[1] + d2y * t)
    return math.hypot(px, py)


def line_arc_intersections(line, arc):
    """Exact 2-D line-segment / circular-arc intersections (may be 0/1/2)."""
    x0, y0 = line['p0']
    x1, y1 = line['p1']
    dx, dy = x1 - x0, y1 - y0
    cx, cy = arc['center']
    radius = arc['radius']
    fx, fy = x0 - cx, y0 - cy
    a = dx * dx + dy * dy
    if a <= 1e-30:
        return []
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < -1e-12:
        return []
    if disc < 1e-12:
        roots = [-b / (2.0 * a)]
    else:
        root = math.sqrt(disc)
        roots = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
    points = []
    for t in roots:
        if t < -1e-12 or t > 1.0 + 1e-12:
            continue
        px = x0 + dx * t
        py = y0 + dy * t
        angle = math.atan2(py - cy, px - cx)
        if angle_in_arc(angle, arc['start'], arc['sweep'], tol=1e-9):
            points.append((px, py, t))
    return points


def arc_arc_intersections(arc1, arc2):
    c1 = arc1['center']
    c2 = arc2['center']
    r1 = arc1['radius']
    r2 = arc2['radius']
    dx = c2[0] - c1[0]
    dy = c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d <= 1e-12:
        return []          # concentric: handled as common/overlap by the caller
    if d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h2 = r1 * r1 - a * a
    if h2 < -1e-9:
        return []
    h = math.sqrt(max(0.0, h2))
    ux, uy = dx / d, dy / d
    mx, my = c1[0] + a * ux, c1[1] + a * uy
    candidates = [(mx + h * -uy, my + h * ux)]
    if h > 1e-9:
        candidates.append((mx - h * -uy, my - h * ux))
    points = []
    for px, py in candidates:
        angle1 = math.atan2(py - c1[1], px - c1[0])
        angle2 = math.atan2(py - c2[1], px - c2[0])
        if angle_in_arc(angle1, arc1['start'], arc1['sweep'], tol=1e-9) and \
                angle_in_arc(angle2, arc2['start'], arc2['sweep'], tol=1e-9):
            points.append((px, py))
    return points


def line_line_intersections(line1, line2):
    """Return (points, common). ``common`` True when the segments overlap."""
    p = line1['p0']
    r = (line1['p1'][0] - p[0], line1['p1'][1] - p[1])
    q = line2['p0']
    s = (line2['p1'][0] - q[0], line2['p1'][1] - q[1])
    denom = r[0] * s[1] - r[1] * s[0]
    qp = (q[0] - p[0], q[1] - p[1])
    if abs(denom) <= 1e-14:
        cross = qp[0] * r[1] - qp[1] * r[0]
        if abs(cross) > 1e-9 * max(1.0, math.hypot(*r)):
            return [], False
        # collinear: project onto the direction, compute overlap interval
        rr = r[0] * r[0] + r[1] * r[1]
        if rr <= 1e-30:
            return [], False
        t0 = (qp[0] * r[0] + qp[1] * r[1]) / rr
        s_len = math.hypot(*s)
        t1 = t0 + (s[0] * r[0] + s[1] * r[1]) / rr
        lo = max(0.0, min(t0, t1))
        hi = min(1.0, max(t0, t1))
        if hi < lo - 1e-12:
            return [], False
        if abs(hi - lo) <= 1e-12:
            t = clamp01(lo)
            return [(p[0] + r[0] * t, p[1] + r[1] * t, t)], False
        return [(p[0] + r[0] * lo, p[1] + r[1] * lo, lo)], True
    t = (qp[0] * s[1] - qp[1] * s[0]) / denom
    u = (qp[0] * r[1] - qp[1] * r[0]) / denom
    if t < -1e-12 or t > 1.0 + 1e-12 or u < -1e-12 or u > 1.0 + 1e-12:
        return [], False
    t = clamp01(t)
    return [(p[0] + r[0] * t, p[1] + r[1] * t, t)], False


def prim_intersections(pa, pb):
    """Return ``(points, common, ok)``; points carry no parameter here."""
    if pa['kind'] == 'line' and pb['kind'] == 'line':
        points, common = line_line_intersections(pa, pb)
        return [(item[0], item[1]) for item in points], common
    if pa['kind'] == 'line' and pb['kind'] == 'arc':
        return [(item[0], item[1]) for item in line_arc_intersections(pa, pb)], False
    if pa['kind'] == 'arc' and pb['kind'] == 'line':
        return [(item[0], item[1]) for item in line_arc_intersections(pb, pa)], False
    c1 = pa['center']
    c2 = pb['center']
    if math.hypot(c1[0] - c2[0], c1[1] - c2[1]) <= 1e-12:
        if abs(pa['radius'] - pb['radius']) <= 1e-12:
            # identical circles: angular ranges decide overlap
            shared = _arc_ranges_overlap(pa, pb)
            return [], shared
        return [], False
    return arc_arc_intersections(pa, pb), False


def _arc_ranges_overlap(arc1, arc2):
    for offset in (0.0, TAU):
        start = arc2['start'] + offset
        if angle_in_arc(start, arc1['start'], arc1['sweep'], tol=1e-12):
            return True
        start = arc1['start']
        if angle_in_arc(start, arc2['start'], arc2['sweep'], tol=1e-12):
            return True
    return False


def param_of_point(prim, point):
    """Parameter t in [0, 1] of ``point`` on ``prim``."""
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length2 = dx * dx + dy * dy
        if length2 <= 0.0:
            return 0.0
        return clamp01(((point[0] - p0[0]) * dx + (point[1] - p0[1]) * dy) / length2)
    angle = math.atan2(point[1] - prim['center'][1], point[0] - prim['center'][0])
    sweep = prim['sweep']
    if abs(sweep) <= 1e-15:
        return 0.0
    delta = (angle - prim['start']) % TAU if sweep >= 0 else -((prim['start'] - angle) % TAU)
    return clamp01(delta / sweep)


# ---- exact primitive-primitive 2-D distance --------------------------------
def prim_prim_distance(pa, pb):
    """Exact 2-D centreline distance between two flat primitives."""
    # cheap bounding-box rejection is handled by the caller
    points, common = prim_intersections(pa, pb)
    if common:
        return 0.0
    if points:
        return 0.0
    if pa['kind'] == 'line' and pb['kind'] == 'line':
        return seg_seg_dist(pa['p0'], pa['p1'], pb['p0'], pb['p1'])
    if pa['kind'] == 'arc' and pb['kind'] == 'arc':
        return _arc_arc_distance(pa, pb)
    if pa['kind'] == 'line':
        line, arc = pa, pb
    else:
        line, arc = pb, pa
    best = float('inf')
    best = min(best, point_prim_dist(line['p0'][0], line['p0'][1], arc))
    best = min(best, point_prim_dist(line['p1'][0], line['p1'][1], arc))
    best = min(best, point_seg_dist(arc['p0'][0], arc['p0'][1],
                                    line['p0'][0], line['p0'][1],
                                    line['p1'][0], line['p1'][1]))
    best = min(best, point_seg_dist(arc['p1'][0], arc['p1'][1],
                                    line['p0'][0], line['p0'][1],
                                    line['p1'][0], line['p1'][1]))
    # radial stationary point: foot of the arc centre on the line
    x0, y0 = line['p0']
    x1, y1 = line['p1']
    dd = (x1 - x0, y1 - y0)
    dd2 = dd[0] * dd[0] + dd[1] * dd[1]
    if dd2 > 1e-30:
        t = ((arc['center'][0] - x0) * dd[0] + (arc['center'][1] - y0) * dd[1]) / dd2
        if -1e-12 <= t <= 1.0 + 1e-12:
            t = clamp01(t)
            fx = x0 + dd[0] * t
            fy = y0 + dd[1] * t
            dist_center = math.hypot(fx - arc['center'][0], fy - arc['center'][1])
            angle = math.atan2(fy - arc['center'][1], fx - arc['center'][0])
            if angle_in_arc(angle, arc['start'], arc['sweep'], tol=1e-12):
                best = min(best, abs(dist_center - arc['radius']))
    return best


def _arc_arc_distance(arc1, arc2):
    c1 = arc1['center']
    c2 = arc2['center']
    r1 = arc1['radius']
    r2 = arc2['radius']
    best = float('inf')
    for arc, other in ((arc1, arc2), (arc2, arc1)):
        for point in (arc['p0'], arc['p1']):
            best = min(best, point_prim_dist(point[0], point[1], other))
    dx = c2[0] - c1[0]
    dy = c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d > 1e-12:
        ux, uy = dx / d, dy / d
        for s1 in (1.0, -1.0):
            for s2 in (1.0, -1.0):
                a1 = math.atan2(s1 * uy, s1 * ux)
                a2 = math.atan2(s2 * uy, s2 * ux)
                if angle_in_arc(a1, arc1['start'], arc1['sweep'], tol=1e-12) and \
                        angle_in_arc(a2, arc2['start'], arc2['sweep'], tol=1e-12):
                    # point1 = c1 + s1*R1*u, point2 = c2 + s2*R2*u
                    value = abs(d - s1 * r1 + s2 * r2)
                    best = min(best, value)
    else:
        # concentric: radial separation where the angular ranges overlap
        if _arc_ranges_overlap(arc1, arc2):
            best = min(best, abs(r1 - r2))
    return best


# ===========================================================================
# transition curve (analytic, re-implemented from the stored definition)
# ===========================================================================
class Transition:
    __slots__ = ('start', 'direction', 'z0', 'z1', 'radius', 'theta', 'sign',
                 'length', 'footprint', 'z_min', 'z_max')

    def __init__(self, part):
        self.start = (float(part['start'][0]), float(part['start'][1]))
        dx, dy = float(part['direction'][0]), float(part['direction'][1])
        norm = math.hypot(dx, dy)
        self.direction = (dx / norm, dy / norm)
        self.z0 = float(part['z0'])
        self.z1 = float(part['z1'])
        self.radius = float(part['radius_mm'])
        self.theta = float(part['theta_rad'])
        self.sign = 1.0 if self.z1 >= self.z0 else -1.0
        self.length = 2.0 * self.radius * self.theta
        self.footprint = 2.0 * self.radius * math.sin(self.theta)
        self.z_min = min(self.z0, self.z1)
        self.z_max = max(self.z0, self.z1)

    def point(self, s):
        radius = self.radius
        theta = self.theta
        if theta <= 0.0:
            sx, sy = self.start
            dx, dy = self.direction
            return (sx + dx * s, sy + dy * s, self.z0)
        half = radius * theta
        if s <= half:
            phi = s / radius
            u = radius * math.sin(phi)
            w = self.z0 + self.sign * radius * (1.0 - math.cos(phi))
        else:
            phi = theta - (s - half) / radius
            u = 2.0 * radius * math.sin(theta) - radius * math.sin(phi)
            w = self.z1 - self.sign * radius * (1.0 - math.cos(phi))
        sx, sy = self.start
        dx, dy = self.direction
        return (sx + dx * u, sy + dy * u, w)

    def points(self, ss):
        """Vectorised point evaluation for an array of arc-length values."""
        ss = np.asarray(ss, dtype=float)
        radius = self.radius
        theta = self.theta
        sx, sy = self.start
        dx, dy = self.direction
        if theta <= 0.0:
            return (sx + dx * ss, sy + dy * ss, np.full_like(ss, self.z0))
        half = radius * theta
        phi = np.where(ss <= half, ss / radius,
                       theta - (ss - half) / radius)
        u = np.where(ss <= half, radius * np.sin(phi),
                     2.0 * radius * math.sin(theta) - radius * np.sin(phi))
        w = np.where(ss <= half,
                     self.z0 + self.sign * radius * (1.0 - np.cos(phi)),
                     self.z1 - self.sign * radius * (1.0 - np.cos(phi)))
        return (sx + dx * u, sy + dy * u, w)


# ===========================================================================
# route / primitive loading
# ===========================================================================
def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_routes(run_dir):
    path = Path(run_dir) / 'routes_l3d.json'
    digest = sha256_file(path)
    payload = json.loads(path.read_text(encoding='utf-8'))
    return path, digest, payload


def _make_flat_prim(prim):
    kind = prim['kind']
    if kind == 'line':
        p0 = (float(prim['p0'][0]), float(prim['p0'][1]))
        p1 = (float(prim['p1'][0]), float(prim['p1'][1]))
        return dict(kind='line', p0=p0, p1=p1,
                    bbox=(min(p0[0], p1[0]), min(p0[1], p1[1]),
                          max(p0[0], p1[0]), max(p0[1], p1[1])))
    if kind == 'arc':
        cx, cy = float(prim['center'][0]), float(prim['center'][1])
        radius = float(prim['radius'])
        start = float(prim['start_angle'])
        sweep = float(prim['sweep'])
        p0 = (float(prim['p0'][0]), float(prim['p0'][1]))
        p1 = (float(prim['p1'][0]), float(prim['p1'][1]))
        xs = [p0[0], p1[0]]
        ys = [p0[1], p1[1]]
        for k in range(-4, 13):
            angle = k * math.pi / 2.0
            if angle_in_arc(angle, start, sweep):
                xs.append(cx + radius * math.cos(angle))
                ys.append(cy + radius * math.sin(angle))
        return dict(kind='arc', center=(cx, cy), radius=radius, start=start,
                    sweep=sweep, p0=p0, p1=p1,
                    bbox=(min(xs), min(ys), max(xs), max(ys)))
    raise ValueError('unknown flat primitive kind %r' % kind)


def build_curves(routes):
    """Flatten every flat primitive + every transition into one curve list."""
    curves = []
    for route in routes:
        route_id = int(route['route_id'])
        for part_index, part in enumerate(route.get('parts') or ()):
            kind = part.get('kind')
            if kind == 'flat':
                z = float(part['z_mm'])
                for prim in part.get('primitives') or ():
                    flat = _make_flat_prim(prim)
                    flat.update(curve_kind='flat', route_id=route_id,
                                part_index=part_index, z=z,
                                length=prim_length(flat))
                    curves.append(flat)
            elif kind == 'transition':
                transition = Transition(part)
                curves.append(dict(curve_kind='transition', route_id=route_id,
                                   part_index=part_index, transition=transition,
                                   z_min=transition.z_min,
                                   z_max=transition.z_max,
                                   bbox=(min(transition.start[0],
                                             transition.start[0] +
                                             transition.direction[0] *
                                             transition.footprint),
                                         min(transition.start[1],
                                             transition.start[1] +
                                             transition.direction[1] *
                                             transition.footprint),
                                         max(transition.start[0],
                                             transition.start[0] +
                                             transition.direction[0] *
                                             transition.footprint),
                                         max(transition.start[1],
                                             transition.start[1] +
                                             transition.direction[1] *
                                             transition.footprint))))
    return curves


def bbox_distance(b1, b2):
    dx = max(0.0, b1[0] - b2[2], b2[0] - b1[2])
    dy = max(0.0, b1[1] - b2[3], b2[1] - b1[3])
    return math.hypot(dx, dy)


# ===========================================================================
# candidate pair grid
# ===========================================================================
def build_candidate_pairs(curves, cell=GRID_CELL_MM, pad=GRID_PAD_MM):
    grid = defaultdict(list)
    for index, curve in enumerate(curves):
        box = curve['bbox']
        x0 = int(math.floor((box[0] - pad) / cell))
        x1 = int(math.floor((box[2] + pad) / cell))
        y0 = int(math.floor((box[1] - pad) / cell))
        y1 = int(math.floor((box[3] + pad) / cell))
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                grid[(ix, iy)].append(index)
    chunks = []
    total_cells = len(grid)
    raw = 0
    for entries in grid.values():
        if len(entries) < 2:
            continue
        arr = np.asarray(entries, dtype=np.int64)
        ii, jj = np.triu_indices(len(arr), 1)
        raw += len(ii)
        if len(ii):
            chunks.append(arr[ii] * len(curves) + arr[jj])
    if chunks:
        keys = np.unique(np.concatenate(chunks))
    else:
        keys = np.zeros(0, dtype=np.int64)
    first = (keys // len(curves)).astype(np.int64)
    second = (keys % len(curves)).astype(np.int64)
    keep = np.array([curves[a]['route_id'] != curves[b]['route_id']
                     for a, b in zip(first.tolist(), second.tolist())],
                    dtype=bool)
    return first[keep], second[keep], dict(cells=total_cells, raw_pairs=raw,
                                           unique_pairs=int(len(keys)),
                                           cross_route_pairs=int(keep.sum()))


# ===========================================================================
# self-check of the analytic primitive distances (independent numeric solver)
# ===========================================================================
def cross_validate_distances(curves, first, second, limit_mm=0.25,
                             max_pairs=6000, log=print):
    """Cross-check the closed-form distances with a brute 1-D numeric solver.

    For ``arc/arc`` and ``line/arc`` candidate pairs whose distance is below
    ``limit_mm`` the minimum is re-solved numerically (dense sampling + golden
    section) and compared against the closed form: this certifies the analytic
    algebra independently of itself.
    """
    candidates = []
    for a, b in zip(first.tolist(), second.tolist()):
        ca, cb = curves[a], curves[b]
        if ca['curve_kind'] != 'flat' or cb['curve_kind'] != 'flat':
            continue
        if ca['kind'] == 'line' and cb['kind'] == 'line':
            continue
        candidates.append((ca, cb))
    if len(candidates) > max_pairs:
        stride = max(1, len(candidates) // max_pairs)
        candidates = candidates[::stride]
    max_error = 0.0
    checked = 0
    worst = None
    for ca, cb in candidates:
        analytic = prim_prim_distance(ca, cb)
        if analytic > limit_mm:
            continue
        numeric = _numeric_prim_distance(ca, cb, 4001)
        checked += 1
        error = abs(numeric - analytic)
        if error > max_error:
            max_error = error
            worst = dict(route_a=ca['route_id'], route_b=cb['route_id'],
                         kinds=[ca['kind'], cb['kind']],
                         analytic_mm=round(analytic, 12),
                         numeric_mm=round(numeric, 12),
                         error_mm=round(error, 12))
    return dict(mode='dense 1-D numeric re-solve + golden section',
                pairs_checked=checked,
                max_absolute_error_mm=max_error,
                worst_case=worst,
                pass_=(max_error <= 2e-6))


def _numeric_prim_distance(pa, pb, samples):
    """Numeric minimum distance; exact for line/arc and arc/arc pairs."""
    if pa['kind'] == 'line' and pb['kind'] == 'line':
        return seg_seg_dist(pa['p0'], pa['p1'], pb['p0'], pb['p1'])
    if pa['kind'] == 'arc' and pb['kind'] == 'arc':
        ts = np.linspace(0.0, 1.0, samples)
        angles = pa['start'] + pa['sweep'] * ts
        xs = pa['center'][0] + pa['radius'] * np.cos(angles)
        ys = pa['center'][1] + pa['radius'] * np.sin(angles)
        values = point_prim_dist_array(xs, ys, pb)
        index = int(np.argmin(values))
        lo = float(ts[max(0, index - 2)])
        hi = float(ts[min(samples - 1, index + 2)])
        return _golden_scalar(lambda t: point_prim_dist(
            pa['center'][0] + pa['radius'] * math.cos(pa['start'] + pa['sweep'] * t),
            pa['center'][1] + pa['radius'] * math.sin(pa['start'] + pa['sweep'] * t),
            pb), lo, hi)
    if pa['kind'] == 'arc':
        pa, pb = pb, pa
    ts = np.linspace(0.0, 1.0, samples)
    xs = pa['p0'][0] + (pa['p1'][0] - pa['p0'][0]) * ts
    ys = pa['p0'][1] + (pa['p1'][1] - pa['p0'][1]) * ts
    values = point_prim_dist_array(xs, ys, pb)
    index = int(np.argmin(values))
    lo = float(ts[max(0, index - 2)])
    hi = float(ts[min(samples - 1, index + 2)])
    return _golden_scalar(
        lambda t: point_prim_dist(pa['p0'][0] + (pa['p1'][0] - pa['p0'][0]) * t,
                                  pa['p0'][1] + (pa['p1'][1] - pa['p0'][1]) * t,
                                  pb), lo, hi)


def _golden_scalar(function, lo, hi):
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - golden * (b - a)
    d = a + golden * (b - a)
    fc, fd = function(c), function(d)
    for _ in range(90):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - golden * (b - a)
            fc = function(c)
        else:
            a, c, fc = c, d, fd
            d = a + golden * (b - a)
            fd = function(d)
    return min(function(0.5 * (a + b)), fc, fd)


# ===========================================================================
# route chains per physical height (needed for window / arc-length bookkeeping)
# ===========================================================================
def build_height_chains(routes):
    """``{(z_key, route_id): [(curve_index, offset, length), ...]}``."""
    chains = {}
    # curve index lookup: (route_id, part_index, prim ordinal) -> index is not
    # needed; instead rebuild in the same order build_curves used.
    position = {}
    cursor = 0
    flat_order = []
    for route in routes:
        route_id = int(route['route_id'])
        for part_index, part in enumerate(route.get('parts') or ()):
            if part.get('kind') == 'flat':
                for _prim in part.get('primitives') or ():
                    flat_order.append((route_id, part_index, float(part['z_mm']),
                                       cursor))
                    cursor += 1
    for route_id, part_index, z, index in flat_order:
        key = (round(z, 9), route_id)
        chains.setdefault(key, []).append(index)
    return chains


# ===========================================================================
# checks: identity / ports / heights / R15 / continuity / glass
# ===========================================================================
def check_identity(payload, routes):
    from four_side_1024.fanout1024 import common as C
    truth = {int(row['route_id']): row for row in C.routes()}
    endpoints = C.endpoints()
    problems = []
    seen = set()
    for route in routes:
        route_id = int(route['route_id'])
        row = truth.get(route_id)
        if row is None:
            problems.append(dict(kind='unknown_route_id', route_id=route_id))
            continue
        for field in ('source_endpoint', 'target_endpoint', 'plane'):
            if str(route.get(field)) != str(row.get(field)):
                problems.append(dict(kind='identity_field', route_id=route_id,
                                     field=field, got=route.get(field),
                                     expected=row.get(field)))
        pair = (str(route['source_endpoint']), str(route['target_endpoint']))
        if pair in seen:
            problems.append(dict(kind='duplicate_connection', pair=pair))
        seen.add(pair)
    # port poses: path endpoints and interface heights
    pose_problems = []
    max_start_xy = max_end_xy = 0.0
    max_start_z = max_end_z = 0.0
    for route in routes:
        route_id = int(route['route_id'])
        row = truth[route_id]
        parts = route.get('parts') or ()
        if not parts:
            continue
        first = parts[0]
        last = parts[-1]
        if first.get('kind') != 'flat' or last.get('kind') != 'flat':
            pose_problems.append(dict(kind='route_not_flat_bounded',
                                      route_id=route_id))
            continue
        start = first['primitives'][0]
        end = last['primitives'][-1]
        sx, sy = float(start['p0'][0]), float(start['p0'][1])
        ex, ey = float(end['p1'][0]), float(end['p1'][1])
        want_s = row['source_xy']
        want_e = row['target_xy']
        ds = math.hypot(sx - want_s[0], sy - want_s[1])
        de = math.hypot(ex - want_e[0], ey - want_e[1])
        max_start_xy = max(max_start_xy, ds)
        max_end_xy = max(max_end_xy, de)
        if ds > 1e-6 or de > 1e-6:
            pose_problems.append(dict(kind='port_xy', route_id=route_id,
                                      start_error=ds, end_error=de))
        z_start = float(first['z_mm'])
        z_end = float(last['z_mm'])
        want_z = 0.0 if str(route.get('plane')) == 'z1' else 0.5
        dzs = abs(z_start - want_z)
        dze = abs(z_end - want_z)
        max_start_z = max(max_start_z, dzs)
        max_end_z = max(max_end_z, dze)
        if dzs > 1e-9 or dze > 1e-9:
            pose_problems.append(dict(kind='port_z', route_id=route_id,
                                      start_z=z_start, end_z=z_end,
                                      expected_z=want_z))
        # tangent direction at the ports
        dir_s = prim_tangent(_make_flat_prim(start), 0.0)
        inward = row['source_inward']
        dot_s = dir_s[0] * inward[0] + dir_s[1] * inward[1]
        if dot_s < 1.0 - 1e-9:
            pose_problems.append(dict(kind='port_start_direction',
                                      route_id=route_id, dot=dot_s))
        dir_e = prim_tangent(_make_flat_prim(end), 1.0)
        target_inward = row['target_inward']
        out = (-target_inward[0], -target_inward[1])
        dot_e = dir_e[0] * out[0] + dir_e[1] * out[1]
        if dot_e < 1.0 - 1e-9:
            pose_problems.append(dict(kind='port_end_direction',
                                      route_id=route_id, dot=dot_e))
    return dict(route_count=len(routes), unique_connections=len(seen),
                identity_problems=problems[:50],
                identity_problem_count=len(problems),
                port_pose_problems=pose_problems[:50],
                port_pose_problem_count=len(pose_problems),
                max_port_start_xy_error_mm=max_start_xy,
                max_port_end_xy_error_mm=max_end_xy,
                max_port_start_z_error_mm=max_start_z,
                max_port_end_z_error_mm=max_end_z,
                pass_=not problems and not pose_problems)


def check_heights_and_r15(routes):
    from four_side_1024.fanout1024.reheight21 import model as M
    model_heights = sorted(round(float(M.plane_z(pid)), 9) for pid in M.PLANE_IDS)
    heights = Counter()
    arc_radii = []
    transitions = []
    for route in routes:
        for part in route.get('parts') or ():
            if part.get('kind') == 'flat':
                heights[round(float(part['z_mm']), 9)] += 1
                for prim in part.get('primitives') or ():
                    if prim.get('kind') == 'arc':
                        arc_radii.append(float(prim['radius']))
            elif part.get('kind') == 'transition':
                tr = Transition(part)
                transitions.append((route['route_id'], part, tr))
    used = sorted(heights)
    gaps = [round(used[i + 1] - used[i], 9) for i in range(len(used) - 1)]
    arc_min = min(arc_radii) if arc_radii else None
    arc_max = max(arc_radii) if arc_radii else None
    radius_problems = []
    formula_problems = []
    max_theta_error = max_footprint_error = max_length_error = max_end_error = 0.0
    max_declared_dz_error = 0.0
    for route_id, part, tr in transitions:
        declared_radius = float(part['radius_mm'])
        declared_theta = float(part['theta_rad'])
        dz = abs(float(part['dz_mm']))
        expected_theta = math.acos(max(-1.0, min(1.0, 1.0 - dz / (2.0 * declared_radius))))
        theta_error = abs(declared_theta - expected_theta)
        max_theta_error = max(max_theta_error, theta_error)
        footprint_error = abs(float(part['footprint_mm']) -
                              2.0 * declared_radius * math.sin(declared_theta))
        max_footprint_error = max(max_footprint_error, footprint_error)
        length_error = abs(float(part['length_mm']) -
                           2.0 * declared_radius * declared_theta)
        max_length_error = max(max_length_error, length_error)
        end = part['end']
        want_end = (float(part['start'][0]) + tr.direction[0] * tr.footprint,
                    float(part['start'][1]) + tr.direction[1] * tr.footprint)
        end_error = math.hypot(end[0] - want_end[0], end[1] - want_end[1])
        max_end_error = max(max_end_error, end_error)
        dz_error = abs((float(part['z1']) - float(part['z0'])) - float(part['dz_mm']))
        max_declared_dz_error = max(max_declared_dz_error, dz_error)
        if declared_radius < R15_MM - 1e-9:
            radius_problems.append(dict(route_id=route_id,
                                        radius=declared_radius))
        if theta_error > 1e-9 or footprint_error > 1e-9 or length_error > 1e-9:
            formula_problems.append(dict(route_id=route_id,
                                         theta_error=theta_error,
                                         footprint_error=footprint_error,
                                         length_error=length_error))
    # cross-check the analytic transition formula against the stored generator
    from four_side_1024.fsd25d import path3d as P3
    formula_crosscheck = 0.0
    for _route_id, part, tr in transitions:
        samples = P3.transition_samples(part, step=1e9)  # exactly 2 points? no
        # evaluate our analytic point at the same phi grid the generator uses
        count = 8
        radius = tr.radius
        theta = tr.theta
        sign = 1.0 if tr.z1 >= tr.z0 else -1.0
        angle = []
        for index in range(count + 1):
            phi = theta * index / count
            u = radius * math.sin(phi)
            w = tr.z0 + sign * radius * (1.0 - math.cos(phi))
            angle.append((u, w))
        mid_u = radius * math.sin(theta)
        mid_w = tr.z0 + sign * abs(tr.z1 - tr.z0) / 2.0
        local = angle + [(2.0 * mid_u - u, 2.0 * mid_w - w)
                         for u, w in reversed(angle)][1:]
        for index, (u, w) in enumerate(local):
            s = tr.length * index / (len(local) - 1)
            point = tr.point(s)
            formula_crosscheck = max(formula_crosscheck,
                                     abs(point[0] - (tr.start[0] + tr.direction[0] * u)),
                                     abs(point[1] - (tr.start[1] + tr.direction[1] * u)),
                                     abs(point[2] - w))
        # the generator's own samples at the same phi values
        generated = P3.transition_samples(part, step=radius * theta / count)
        for index, sample in enumerate(generated):
            point = tr.point(tr.length * index / (len(generated) - 1))
            formula_crosscheck = max(
                formula_crosscheck,
                abs(point[0] - sample[0]), abs(point[1] - sample[1]),
                abs(point[2] - sample[2]))
    heights_ok = [round(value, 9) for value in model_heights] == used
    return dict(model_height_count=len(model_heights),
                used_height_count=len(used),
                heights_used=used,
                heights_match_model=heights_ok,
                min_height_gap_mm=min(gaps) if gaps else None,
                max_height_gap_mm=max(gaps) if gaps else None,
                flat_parts_per_height={('%.6f' % z): int(count)
                                       for z, count in sorted(heights.items())},
                arc_count=len(arc_radii),
                arc_radius_min_mm=arc_min,
                arc_radius_max_mm=arc_max,
                arc_radius_violations=len([r for r in arc_radii
                                           if r < R15_MM - 1e-9]),
                transition_count=len(transitions),
                transition_radius_values=sorted({float(part['radius_mm'])
                                                 for _r, part, _t in transitions}),
                transition_radius_violations=len(radius_problems),
                transition_theta_max_error_rad=max_theta_error,
                transition_footprint_max_error_mm=max_footprint_error,
                transition_length_max_error_mm=max_length_error,
                transition_end_max_error_mm=max_end_error,
                transition_declared_dz_max_error_mm=max_declared_dz_error,
                transition_formula_vs_generator_max_error_mm=formula_crosscheck,
                pass_=(heights_ok and arc_min is not None
                       and arc_min >= R15_MM - 1e-9
                       and max(arc_radii or [R15_MM]) <= R15_MM + 1e-9
                       and not radius_problems and not formula_problems
                       and formula_crosscheck < 1e-9))


def check_continuity(routes):
    max_position_gap = 0.0
    max_tangent_gap = 0.0
    max_z_gap = 0.0
    junctions = 0
    problems = []
    for route in routes:
        route_id = int(route['route_id'])
        parts = route.get('parts') or ()
        previous = None          # (end_xy, tangent_xy, z)
        for part_index, part in enumerate(parts):
            if part.get('kind') == 'flat':
                for prim in part.get('primitives') or ():
                    flat = _make_flat_prim(prim)
                    if previous is not None:
                        prev_end, prev_tangent, prev_z = previous
                        gap = math.hypot(flat['p0'][0] - prev_end[0],
                                         flat['p0'][1] - prev_end[1])
                        z_gap = abs(float(part['z_mm']) - prev_z)
                        tangent = prim_tangent(flat, 0.0)
                        angle = math.acos(max(-1.0, min(1.0,
                            tangent[0] * prev_tangent[0] +
                            tangent[1] * prev_tangent[1])))
                        max_position_gap = max(max_position_gap, gap)
                        max_tangent_gap = max(max_tangent_gap, angle)
                        max_z_gap = max(max_z_gap, z_gap)
                        junctions += 1
                        if gap > 1e-6 or z_gap > 1e-9:
                            problems.append(dict(kind='flat_position_gap',
                                                 route_id=route_id,
                                                 part_index=part_index,
                                                 gap=gap, z_gap=z_gap))
                    previous = (flat['p1'], prim_tangent(flat, 1.0),
                                float(part['z_mm']))
            elif part.get('kind') == 'transition':
                tr = Transition(part)
                if previous is not None:
                    prev_end, prev_tangent, prev_z = previous
                    gap = math.hypot(tr.start[0] - prev_end[0],
                                     tr.start[1] - prev_end[1])
                    z_gap = abs(tr.z0 - prev_z)
                    tangent = _transition_start_tangent(tr)
                    angle = math.acos(max(-1.0, min(1.0,
                        tangent[0] * prev_tangent[0] +
                        tangent[1] * prev_tangent[1])))
                    max_position_gap = max(max_position_gap, gap)
                    max_tangent_gap = max(max_tangent_gap, angle)
                    max_z_gap = max(max_z_gap, z_gap)
                    junctions += 1
                    if gap > 1e-6 or z_gap > 1e-9:
                        problems.append(dict(kind='transition_position_gap',
                                             route_id=route_id, gap=gap,
                                             z_gap=z_gap))
                end_point = tr.point(tr.length)
                previous = ((end_point[0], end_point[1]),
                            _transition_end_tangent(tr), tr.z1)
    return dict(junctions=junctions,
                max_z_gap_mm=max_z_gap,
                max_position_gap_mm=max_position_gap,
                max_tangent_gap_rad=max_tangent_gap,
                problems=problems[:20], problem_count=len(problems),
                pass_=not problems)


def _transition_start_tangent(tr):
    # first arc starts with zero vertical slope: tangent = local XY direction
    return tr.direction


def _transition_end_tangent(tr):
    # the S-curve is symmetric: it lands with the same local XY direction
    return tr.direction


def check_glass(routes):
    """Independent sampling of the whole 3-D centreline against the glass box."""
    xs_all = []
    ys_all = []
    zs_all = []
    for route in routes:
        for part in route.get('parts') or ():
            if part.get('kind') == 'flat':
                z = float(part['z_mm'])
                for prim in part.get('primitives') or ():
                    flat = _make_flat_prim(prim)
                    if flat['kind'] == 'line':
                        xs_all.extend([flat['p0'][0], flat['p1'][0]])
                        ys_all.extend([flat['p0'][1], flat['p1'][1]])
                        zs_all.extend([z, z])
                    else:
                        length = prim_length(flat)
                        count = max(2, int(math.ceil(length / 0.05)) + 1)
                        for index in range(count + 1):
                            point = arc_point(flat, index / count)
                            xs_all.append(point[0])
                            ys_all.append(point[1])
                            zs_all.append(z)
            elif part.get('kind') == 'transition':
                tr = Transition(part)
                count = max(2, int(math.ceil(tr.length / 0.01)) + 1)
                ss = np.linspace(0.0, tr.length, count)
                xs, ys, zs = tr.points(ss)
                xs_all.extend(xs.tolist())
                ys_all.extend(ys.tolist())
                zs_all.extend(zs.tolist())
    xs = np.asarray(xs_all, dtype=float)
    ys = np.asarray(ys_all, dtype=float)
    zs = np.asarray(zs_all, dtype=float)
    center_margin = np.minimum(np.minimum(xs, GLASS_XY_MM - xs),
                               np.minimum(ys, GLASS_XY_MM - ys))
    min_center_margin = float(np.min(center_margin))
    min_edge_margin = min_center_margin - WAVEGUIDE_HALF_WIDTH_MM
    min_z = float(np.min(zs))
    max_z = float(np.max(zs))
    xy_outside = int(np.sum((xs < -1e-6) | (xs > GLASS_XY_MM + 1e-6) |
                            (ys < -1e-6) | (ys > GLASS_XY_MM + 1e-6)))
    return dict(board_mm=[GLASS_XY_MM, GLASS_XY_MM],
                z_range_mm=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM],
                samples=int(len(xs)),
                x_range_mm=[float(np.min(xs)), float(np.max(xs))],
                y_range_mm=[float(np.min(ys)), float(np.max(ys))],
                min_centerline_margin_mm=min_center_margin,
                min_edge_margin_mm=min_edge_margin,
                min_z_mm=min_z, max_z_mm=max_z,
                xy_outside_samples=xy_outside,
                z_outside_samples=int(np.sum(
                    (zs < GLASS_Z_MIN_MM - 1e-6) |
                    (zs > GLASS_Z_MAX_MM + 1e-6))),
                edge_margin_note=('the two interface ports sit exactly on the '
                                  '150 mm board edge (centreline margin 0), so '
                                  'the -25 um edge margin is a known property of '
                                  'the exploratory centreline model and is not '
                                  'counted as a glass violation here'),
                pass_=(min_center_margin >= -1e-6
                       and min_z >= GLASS_Z_MIN_MM - 1e-6
                       and max_z <= GLASS_Z_MAX_MM + 1e-6))


def check_manual_u(run_dir, routes, baseline_dir=None):
    """Manual-U contract check; falls back to the frozen baseline assignment."""
    from four_side_1024.fanout1024 import common as C
    path = Path(run_dir) / 'assignment_1024.csv'
    source = 'run'
    if not path.exists() and baseline_dir is not None:
        fallback = Path(baseline_dir) / 'assignment_1024.csv'
        if fallback.exists():
            path = fallback
            source = 'baseline_fallback'
    rows, digest = C.read_csv_rows(path)
    manual_ids = sorted({int(row['route_id']) for row in rows
                         if str(row.get('manual_group') or '').strip()})
    route_ids = {int(route['route_id']) for route in routes}
    groups = Counter(str(row.get('manual_group') or '').strip()
                     for row in rows if str(row.get('manual_group') or '').strip())
    return dict(assignment_rows=len(rows),
                assignment_source=source,
                assignment_file=str(path),
                assignment_sha256=digest,
                manual_route_count=len(manual_ids),
                manual_groups=dict(groups),
                manual_routes_present=all(rid in route_ids for rid in manual_ids),
                pass_=(len(rows) == 1024 and len(manual_ids) == 368))


# ===========================================================================
# same-layer crossing / spacing audit (strict D56 rule, independently applied)
# ===========================================================================
def _interval_union_length(intervals):
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    total = 0.0
    current_lo, current_hi = intervals[0]
    for lo, hi in intervals[1:]:
        if lo > current_hi:
            total += current_hi - current_lo
            current_lo, current_hi = lo, hi
        else:
            current_hi = max(current_hi, hi)
    total += current_hi - current_lo
    return total


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [tuple(item) for item in merged]


def _close_regions_on_chain(chain_curves, chain_offsets, chain_length,
                            partner_curves, limit, step=0.005,
                            bbox_limit=0.15):
    """Arc-length intervals of a route chain where distance < ``limit``.

    Only chain primitives whose 2-D bbox is within ``bbox_limit`` of a partner
    primitive are scanned (bbox distance is a lower bound, so nothing can be
    missed for the ``limit``-neighbourhood).  Returns
    ``(intervals, min_distance, min_point)``.
    """
    intervals = []
    best = (float('inf'), None)
    for local_index, curve in enumerate(chain_curves):
        partner_indexes = [k for k, other in enumerate(partner_curves)
                           if bbox_distance(curve['bbox'], other['bbox']) <= bbox_limit]
        if not partner_indexes:
            continue
        length = curve['length']
        if length <= 1e-12:
            continue
        count = max(3, int(math.ceil(length / step)) + 1)
        ts = np.linspace(0.0, 1.0, count)
        ss = ts * length
        if curve['kind'] == 'line':
            xs = curve['p0'][0] + (curve['p1'][0] - curve['p0'][0]) * ts
            ys = curve['p0'][1] + (curve['p1'][1] - curve['p0'][1]) * ts
        else:
            angles = curve['start'] + curve['sweep'] * ts
            xs = curve['center'][0] + curve['radius'] * np.cos(angles)
            ys = curve['center'][1] + curve['radius'] * np.sin(angles)
        for partner_index in partner_indexes:
            partner = partner_curves[partner_index]
            distance = point_prim_dist_array(xs, ys, partner)
            local = float(np.min(distance))
            if local < best[0]:
                index = int(np.argmin(distance))
                best = (local, (float(xs[index]), float(ys[index])))
            mask = distance < limit
            if not np.any(mask):
                continue
            # contiguous runs
            indices = np.flatnonzero(mask)
            gaps = np.flatnonzero(np.diff(indices) > 1)
            starts = np.concatenate(([indices[0]], indices[gaps + 1]))
            ends = np.concatenate((indices[gaps], [indices[-1]]))
            offset = chain_offsets[local_index]
            for start_index, end_index in zip(starts.tolist(), ends.tolist()):
                lo = offset + float(ss[start_index])
                hi = offset + float(ss[end_index])
                intervals.append((lo, hi))
    intervals = _merge_intervals(intervals)
    return intervals, best[0], best[1]


def same_layer_audit(curves, routes, chains, first, second, log=print):
    """Strict D56 audit of every physical height, recomputed from scratch."""
    # group flat curves by physical height
    height_curves = defaultdict(list)
    for index, curve in enumerate(curves):
        if curve['curve_kind'] == 'flat':
            height_curves[round(curve['z'], 9)].append(index)
    # per (height, route) chain of flat curve indexes in path order
    chain_groups = defaultdict(list)
    for index, curve in enumerate(curves):
        if curve['curve_kind'] == 'flat':
            chain_groups[(round(curve['z'], 9), curve['route_id'])].append(index)
    # pair candidate map per height
    pair_map = defaultdict(lambda: defaultdict(list))
    for a, b in zip(first.tolist(), second.tolist()):
        ca = curves[a]
        cb = curves[b]
        if ca['curve_kind'] != 'flat' or cb['curve_kind'] != 'flat':
            continue
        za = round(ca['z'], 9)
        zb = round(cb['z'], 9)
        if za != zb:
            continue
        ra, rb = ca['route_id'], cb['route_id']
        if ra > rb:
            ra, rb, ca, cb = rb, ra, cb, ca
        pair_map[za][(ra, rb)].append((ca, cb))
    # chain offsets per (height, route)
    chain_info = {}
    for key, indexes in chain_groups.items():
        offsets = []
        cursor = 0.0
        ordered = []
        for index in indexes:
            curve = curves[index]
            offsets.append(cursor)
            ordered.append(curve)
            cursor += curve['length']
        chain_info[key] = (ordered, offsets, cursor)

    events = []
    illegal_events = []
    min_non_crossing = (float('inf'), None)
    crossings_per_route = Counter()
    crossing_pairs = set()
    heights_with_crossings = Counter()
    close_region_problems = []
    window_half_max = 0.0
    spacing_violation_pairs = []
    intersection_residual_max = 0.0
    groups_total = 0
    for z_key in sorted(pair_map):
        for (route_a, route_b), prim_pairs in pair_map[z_key].items():
            exact_min = float('inf')
            intersection_records = []
            overlap = False
            double = False
            for ca, cb in prim_pairs:
                points, common = prim_intersections(ca, cb)
                distance = prim_prim_distance(ca, cb) if not points else 0.0
                if distance < exact_min:
                    exact_min = distance
                if common:
                    overlap = True
                    break
                if len(points) > 1:
                    double = True
                for point in points:
                    intersection_residual_max = max(
                        intersection_residual_max,
                        abs(prim_prim_distance(ca, cb)))
                    intersection_records.append((point, ca, cb))
            if overlap or double:
                illegal_events.append(dict(
                    height_mm=z_key, route_a=route_a, route_b=route_b,
                    kind='overlap' if overlap else 'double_cross'))
                continue
            if exact_min > 1e-6:
                if exact_min < min_non_crossing[0]:
                    min_non_crossing = (exact_min, dict(
                        height_mm=z_key, route_a=route_a, route_b=route_b))
                if exact_min < LIMIT_2D:
                    spacing_violation_pairs.append(dict(
                        height_mm=z_key, route_a=route_a, route_b=route_b,
                        distance_mm=exact_min))
                continue
            # ---- genuine intersection(s) -> group coincident points --------
            info_a = chain_info[(z_key, route_a)]
            info_b = chain_info[(z_key, route_b)]
            groups = []
            for point, ca, cb in intersection_records:
                t_a = param_of_point(ca, point)
                t_b = param_of_point(cb, point)
                tangent_a = prim_tangent(ca, t_a)
                tangent_b = prim_tangent(cb, t_b)
                sine = min(1.0, abs(tangent_a[0] * tangent_b[1] -
                                    tangent_a[1] * tangent_b[0]))
                member = dict(point=point, sine=sine,
                              sa=_chain_sa(info_a, ca, t_a),
                              sb=_chain_sa(info_b, cb, t_b))
                for group in groups:
                    reference = group[0]
                    if (abs(point[0] - reference['point'][0]) < 1e-6 and
                            abs(point[1] - reference['point'][1]) < 1e-6):
                        group.append(member)
                        break
                else:
                    groups.append([member])
            # close regions (distance < strict limit) along both chains
            intervals_a, _min_a, _point_a = _close_regions_on_chain(
                info_a[0], info_a[1], info_a[2], info_b[0], LIMIT_2D)
            intervals_b, _min_b, _point_b = _close_regions_on_chain(
                info_b[0], info_b[1], info_b[2], info_a[0], LIMIT_2D)
            # every group must be a genuine transverse interior crossing
            allowed = True
            reasons = []
            windows_a = []
            for group in groups:
                reference = group[0]
                if reference['sine'] < math.sin(math.radians(MIN_CROSS_ANGLE_DEG)):
                    allowed = False
                    reasons.append('tangent_touch')
                    continue
                if min(reference['sa'], info_a[2] - reference['sa'],
                       reference['sb'], info_b[2] - reference['sb']) < 1e-7:
                    allowed = False
                    reasons.append('endpoint_touch')
                    continue
                # distance along chain A from the crossing to the 0.08 edge
                left = _edge_distance(info_a, reference['sa'], info_b[0],
                                      LIMIT_2D, -1.0)
                right = _edge_distance(info_a, reference['sa'], info_b[0],
                                       LIMIT_2D, 1.0)
                half = max(left, right)
                if half > STRICT_MAX_HALF_WINDOW_MM + SAGITTA_MM:
                    allowed = False
                    reasons.append('crossing_window_excessive')
                window_half_max = max(window_half_max, half)
                windows_a.append((reference['sa'] - left - SAGITTA_MM,
                                  reference['sa'] + right + SAGITTA_MM))
            # measured near-region extent (sanity number reported to the user)
            for interval in intervals_a:
                window_half_max = max(window_half_max,
                                      0.5 * (interval[1] - interval[0]))
            groups_total += len(groups)
            if not allowed:
                illegal_events.append(dict(
                    height_mm=z_key, route_a=route_a, route_b=route_b,
                    kinds=reasons,
                    angles_deg=[round(math.degrees(math.asin(info[0]['sine'])), 6)
                                for info in groups]))
                continue
            # windows of the same route pair must not overlap
            windows_a = _merge_intervals(windows_a)
            overlap_windows = len(windows_a) < len(groups)
            if overlap_windows:
                illegal_events.append(dict(
                    height_mm=z_key, route_a=route_a, route_b=route_b,
                    kinds=['crossing_window_overlap']))
                continue
            # outside the windows the strict clearance must be kept
            uncovered = _uncovered_close_regions(intervals_a, windows_a)
            if uncovered:
                close_region_problems.append(dict(
                    height_mm=z_key, route_a=route_a, route_b=route_b,
                    uncovered=[(round(lo, 6), round(hi, 6)) for lo, hi in uncovered]))
                continue
            for group in groups:
                reference = group[0]
                events.append(dict(
                    height_mm=round(z_key, 6), route_a=route_a, route_b=route_b,
                    x_mm=round(reference['point'][0], 6),
                    y_mm=round(reference['point'][1], 6),
                    angle_deg=round(math.degrees(math.asin(reference['sine'])), 6)))
                crossings_per_route[route_a] += 1
                crossings_per_route[route_b] += 1
                crossing_pairs.add((route_a, route_b))
                heights_with_crossings[round(z_key, 6)] += 1
    return dict(
        event_count=len(events),
        crossing_pair_count=len(crossing_pairs),
        illegal_event_count=len(illegal_events),
        illegal_events=illegal_events[:50],
        intersection_group_count=groups_total,
        max_crossings_per_route=int(max(crossings_per_route.values())
                                    if crossings_per_route else 0),
        max_crossings_route_id=(int(max(crossings_per_route.items(),
                                        key=lambda item: item[1])[0])
                                if crossings_per_route else None),
        per_route_crossings={str(rid): int(count)
                             for rid, count in sorted(crossings_per_route.items())},
        crossings_per_height={('%.6f' % z): int(count)
                              for z, count in sorted(heights_with_crossings.items())},
        heights_with_crossings=len(heights_with_crossings),
        crossing_angle_min_deg=round(min(item['angle_deg'] for item in events), 6)
        if events else None,
        crossing_angle_max_deg=round(max(item['angle_deg'] for item in events), 6)
        if events else None,
        crossing_window_half_max_mm=window_half_max,
        spacing_violation_count=len(spacing_violation_pairs),
        spacing_violations=spacing_violation_pairs[:50],
        always_close_region_problem_count=len(close_region_problems),
        always_close_region_problems=close_region_problems[:50],
        min_non_crossing_centerline_mm=(None if not math.isfinite(min_non_crossing[0])
                                        else round(min_non_crossing[0], 9)),
        min_non_crossing_evidence=min_non_crossing[1],
        intersection_residual_max_mm=intersection_residual_max,
        events=events,
        events_sample=events[:5])


def _chain_sa(info, curve, t):
    ordered, offsets, _length = info
    for index, candidate in enumerate(ordered):
        if candidate is curve:
            return offsets[index] + t * curve['length']
    # fallback by identity of geometry (should not happen)
    return t * curve['length']


def _point_on_chain(info, sa):
    ordered, offsets, length = info
    sa = min(max(sa, 0.0), length)
    for index in range(len(ordered) - 1, -1, -1):
        if sa >= offsets[index] - 1e-12:
            curve = ordered[index]
            if curve['length'] <= 1e-15:
                return prim_point(curve, 0.0)
            t = (sa - offsets[index]) / curve['length']
            return prim_point(curve, clamp01(t))
    return prim_point(ordered[0], 0.0)


def _min_distance_from_chain_point(info, sa, partner_curves):
    point = _point_on_chain(info, sa)
    best = float('inf')
    for curve in partner_curves:
        best = min(best, point_prim_dist(point[0], point[1], curve))
    return best


def _edge_distance(info, sa, partner_curves, limit, direction):
    """Arc length from ``sa`` until the distance to the partner reaches limit."""
    step = 0.005
    max_span = STRICT_MAX_HALF_WINDOW_MM + 0.5
    span = 0.0
    previous = _min_distance_from_chain_point(info, sa, partner_curves)
    if previous >= limit:
        return 0.0
    while span < max_span:
        span += step
        current = _min_distance_from_chain_point(info, sa + direction * span,
                                                 partner_curves)
        if current >= limit:
            lo, hi = previous, current
            lo_span, hi_span = span - step, span
            for _ in range(40):
                mid = 0.5 * (lo_span + hi_span)
                value = _min_distance_from_chain_point(
                    info, sa + direction * mid, partner_curves)
                if value >= limit:
                    hi_span = mid
                else:
                    lo_span = mid
            return 0.5 * (lo_span + hi_span)
        previous = current
    return max_span


def _uncovered_close_regions(intervals, windows):
    if not intervals:
        return []
    uncovered = []
    merged_windows = _merge_intervals(windows)
    for lo, hi in intervals:
        cursor = lo
        for window_lo, window_hi in merged_windows:
            if window_hi <= cursor:
                continue
            if window_lo >= hi:
                break
            if window_lo > cursor:
                uncovered.append((cursor, min(window_lo, hi)))
            cursor = max(cursor, window_hi)
            if cursor >= hi:
                break
        if cursor < hi - 1e-9:
            uncovered.append((cursor, hi))
    return [item for item in uncovered if item[1] - item[0] > 1e-6]


# ===========================================================================
# 3-D clearance audit: flat-flat cross height, flat-transition, trans-trans
# ===========================================================================
def flat_flat_3d(curves, first, second):
    entries = []
    for a, b in zip(first.tolist(), second.tolist()):
        ca = curves[a]
        cb = curves[b]
        if ca['curve_kind'] != 'flat' or cb['curve_kind'] != 'flat':
            continue
        za, zb = ca['z'], cb['z']
        if abs(za - zb) <= 1e-9:
            continue
        entries.append((ca, cb))
    min_value = (float('inf'), None)
    violations = []
    exact_pairs = 0
    for ca, cb in entries:
        dz = abs(ca['z'] - cb['z'])
        d2 = prim_prim_distance(ca, cb)
        value = math.hypot(d2, dz)
        exact_pairs += 1
        if value < min_value[0]:
            min_value = (value, dict(route_a=ca['route_id'],
                                     route_b=cb['route_id'],
                                     z_a_mm=round(ca['z'], 6),
                                     z_b_mm=round(cb['z'], 6),
                                     dz_mm=round(dz, 6),
                                     distance_2d_mm=round(d2, 9),
                                     distance_3d_mm=round(value, 9)))
        if value < LIMIT_3D:
            violations.append(dict(route_a=ca['route_id'],
                                   route_b=cb['route_id'],
                                   z_a_mm=ca['z'], z_b_mm=cb['z'],
                                   distance_mm=value))
    return dict(candidate_pairs=len(entries), exact_pairs=exact_pairs,
                min_distance_mm=(None if not math.isfinite(min_value[0])
                                 else round(min_value[0], 9)),
                min_evidence=min_value[1],
                violation_count=len(violations),
                violations=violations[:50])


def transition_flat_3d(curves, first, second):
    pairs = []
    for a, b in zip(first.tolist(), second.tolist()):
        ca = curves[a]
        cb = curves[b]
        if ca['curve_kind'] == 'flat' and cb['curve_kind'] == 'transition':
            pairs.append((cb, ca))
        elif ca['curve_kind'] == 'transition' and cb['curve_kind'] == 'flat':
            pairs.append((ca, cb))
    # coarse pass over every candidate pair
    coarse = []
    for tr_curve, flat_curve in pairs:
        tr = tr_curve['transition']
        count = max(9, int(math.ceil(tr.length / 0.05)) + 1)
        ss = np.linspace(0.0, tr.length, count)
        xs, ys, zs = tr.points(ss)
        d2 = point_prim_dist_array(xs, ys, flat_curve)
        values = np.hypot(d2, zs - flat_curve['z'])
        index = int(np.argmin(values))
        step = tr.length / (count - 1)
        upper = float(values[index])
        lower = max(0.0, upper - step)
        coarse.append((lower, upper, tr_curve, flat_curve, ss, index, step))
    coarse.sort(key=lambda item: item[0])
    min_value = (float('inf'), None)
    violations = []
    accurate_pairs = 0
    for lower, upper, tr_curve, flat_curve, ss, index, step in coarse:
        if lower > min_value[0] and lower >= LIMIT_3D:
            break
        tr = tr_curve['transition']
        lo = float(ss[max(0, index - 1)])
        hi = float(ss[min(len(ss) - 1, index + 1)])
        value, point = _transition_flat_minimum(tr, flat_curve, lo, hi)
        accurate_pairs += 1
        if value < min_value[0]:
            min_value = (value, dict(
                route_a=tr_curve['route_id'], route_b=flat_curve['route_id'],
                transition_part_index=tr_curve['part_index'],
                z0_mm=round(tr.z0, 6), z1_mm=round(tr.z1, 6),
                flat_z_mm=round(flat_curve['z'], 6),
                distance_mm=round(value, 9),
                point=[round(item, 6) for item in point]))
        if value < LIMIT_3D:
            violations.append(dict(route_a=tr_curve['route_id'],
                                   route_b=flat_curve['route_id'],
                                   z0_mm=tr.z0, z1_mm=tr.z1,
                                   flat_z_mm=flat_curve['z'],
                                   distance_mm=value,
                                   point=[round(item, 6) for item in point]))
    return dict(candidate_pairs=len(pairs), accurate_pairs=accurate_pairs,
                min_distance_mm=(None if not math.isfinite(min_value[0])
                                 else round(min_value[0], 9)),
                min_evidence=min_value[1],
                violation_count=len(violations),
                violations=violations[:50])


def _transition_flat_minimum(tr, flat_curve, lo, hi):
    def evaluate(s):
        x, y, z = tr.point(s)
        d2 = point_prim_dist(x, y, flat_curve)
        return d2 * d2 + (z - flat_curve['z']) ** 2

    a, b = lo, hi
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    c = b - golden * (b - a)
    d = a + golden * (b - a)
    fc, fd = evaluate(c), evaluate(d)
    for _ in range(80):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - golden * (b - a)
            fc = evaluate(c)
        else:
            a, c, fc = c, d, fd
            d = a + golden * (b - a)
            fd = evaluate(d)
    s = 0.5 * (a + b)
    x, y, z = tr.point(s)
    d2 = point_prim_dist(x, y, flat_curve)
    return math.hypot(d2, z - flat_curve['z']), (x, y, z)


def transition_transition_3d(curves, first, second):
    pairs = []
    for a, b in zip(first.tolist(), second.tolist()):
        ca = curves[a]
        cb = curves[b]
        if ca['curve_kind'] != 'transition' or cb['curve_kind'] != 'transition':
            continue
        pairs.append((ca, cb))
    coarse = []
    for ca, cb in pairs:
        tra = ca['transition']
        trb = cb['transition']
        na = max(9, int(math.ceil(tra.length / 0.05)) + 1)
        nb = max(9, int(math.ceil(trb.length / 0.05)) + 1)
        sa = np.linspace(0.0, tra.length, na)
        sb = np.linspace(0.0, trb.length, nb)
        xa, ya, za = tra.points(sa)
        xb, yb, zb = trb.points(sb)
        dx = xa[:, None] - xb[None, :]
        dy = ya[:, None] - yb[None, :]
        dz = za[:, None] - zb[None, :]
        values = np.sqrt(dx * dx + dy * dy + dz * dz)
        flat_index = int(np.argmin(values))
        ia, ib = divmod(flat_index, nb)
        step = max(tra.length / (na - 1), trb.length / (nb - 1))
        upper = float(values[ia, ib])
        lower = max(0.0, upper - step)
        coarse.append((lower, upper, ca, cb, float(sa[ia]), float(sb[ib]), step))
    coarse.sort(key=lambda item: item[0])
    min_value = (float('inf'), None)
    violations = []
    accurate_pairs = 0
    for lower, upper, ca, cb, sa0, sb0, step in coarse:
        if lower > min_value[0] and lower >= LIMIT_3D:
            break
        value, point, sa, sb = _transition_transition_minimum(
            ca['transition'], cb['transition'], sa0, sb0, step)
        accurate_pairs += 1
        if value < min_value[0]:
            min_value = (value, dict(
                route_a=ca['route_id'], route_b=cb['route_id'],
                distance_mm=round(value, 9),
                point=[round(item, 6) for item in point],
                s_a=round(sa, 6), s_b=round(sb, 6),
                z0a=round(ca['transition'].z0, 6),
                z1a=round(ca['transition'].z1, 6),
                z0b=round(cb['transition'].z0, 6),
                z1b=round(cb['transition'].z1, 6)))
        if value < LIMIT_3D:
            violations.append(dict(route_a=ca['route_id'],
                                   route_b=cb['route_id'],
                                   distance_mm=value,
                                   point=[round(item, 6) for item in point]))
    return dict(candidate_pairs=len(pairs), accurate_pairs=accurate_pairs,
                min_distance_mm=(None if not math.isfinite(min_value[0])
                                 else round(min_value[0], 9)),
                min_evidence=min_value[1],
                violation_count=len(violations),
                violations=violations[:50])


def _transition_transition_minimum(tra, trb, sa0, sb0, step):
    def distance(sa, sb):
        pa = tra.point(sa)
        pb = trb.point(sb)
        dx = pa[0] - pb[0]
        dy = pa[1] - pb[1]
        dz = pa[2] - pb[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    sa, sb = sa0, sb0
    brackets_a = (max(0.0, sa - step), min(tra.length, sa + step))
    brackets_b = (max(0.0, sb - step), min(trb.length, sb + step))
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    for _round in range(6):
        lo, hi = brackets_a
        c = hi - golden * (hi - lo)
        d = lo + golden * (hi - lo)
        fc, fd = distance(c, sb), distance(d, sb)
        for _ in range(60):
            if fc < fd:
                hi, d, fd = d, c, fc
                c = hi - golden * (hi - lo)
                fc = distance(c, sb)
            else:
                lo, c, fc = c, d, fd
                d = lo + golden * (hi - lo)
                fd = distance(d, sb)
        sa = 0.5 * (lo + hi)
        brackets_a = (max(0.0, sa - step * 0.25), min(tra.length, sa + step * 0.25))
        lo, hi = brackets_b
        c = hi - golden * (hi - lo)
        d = lo + golden * (hi - lo)
        fc, fd = distance(sa, c), distance(sa, d)
        for _ in range(60):
            if fc < fd:
                hi, d, fd = d, c, fc
                c = hi - golden * (hi - lo)
                fc = distance(sa, c)
            else:
                lo, c, fc = c, d, fd
                d = lo + golden * (hi - lo)
                fd = distance(sa, d)
        sb = 0.5 * (lo + hi)
        brackets_b = (max(0.0, sb - step * 0.25),
                      min(trb.length, sb + step * 0.25))
    point = tra.point(sa)
    return distance(sa, sb), point, sa, sb


# ===========================================================================
# self clearance (one route against itself, |ds| > 1 mm)
# ===========================================================================
def self_clearance_audit(routes, log=print):
    """Independent route-vs-itself clearance scan.

    Points are sampled at 0.25 mm (flat) / 0.05 mm (transition); a per-route
    cKDTree finds every point pair closer than 1 mm, pairs whose arc-length
    separation is <= 1 mm (local path neighbourhood) are ignored, and the
    minimum remaining 3-D distance is reported.
    """
    import scipy.spatial as spatial
    min_distance = (float('inf'), None)
    violations = []
    search_radius = 1.0
    for route in routes:
        route_id = int(route['route_id'])
        points = []
        lengths = []
        total = 0.0
        for part in route.get('parts') or ():
            if part.get('kind') == 'flat':
                z = float(part['z_mm'])
                for prim in part.get('primitives') or ():
                    flat = _make_flat_prim(prim)
                    length = prim_length(flat)
                    count = max(2, int(math.ceil(length / 0.25)) + 1)
                    for index in range(count + 1):
                        t = index / count
                        point = prim_point(flat, t)
                        if points:
                            total += math.hypot(point[0] - points[-1][0],
                                                point[1] - points[-1][1])
                        points.append((point[0], point[1], z))
                        lengths.append(total)
            elif part.get('kind') == 'transition':
                tr = Transition(part)
                count = max(3, int(math.ceil(tr.length / 0.05)) + 1)
                for index in range(count + 1):
                    point = tr.point(tr.length * index / count)
                    if points:
                        total += math.hypot(point[0] - points[-1][0],
                                            point[1] - points[-1][1])
                    points.append(point)
                    lengths.append(total)
        if len(points) < 2:
            continue
        array = np.asarray(points, dtype=float)
        lengths_array = np.asarray(lengths, dtype=float)
        tree = spatial.cKDTree(array)
        neighbours = tree.query_ball_point(array, r=search_radius, workers=-1)
        for index, items in enumerate(neighbours):
            for other_index in items:
                if other_index <= index:
                    continue
                if abs(lengths_array[index] - lengths_array[other_index]) <= 1.0:
                    continue
                distance = float(np.linalg.norm(array[index] - array[other_index]))
                if distance < min_distance[0]:
                    min_distance = (distance, dict(
                        route_id=route_id,
                        point=[round(value, 6) for value in array[index]]))
                if distance < LIMIT_3D:
                    violations.append(dict(
                        route_id=route_id, distance_mm=distance,
                        point=[round(value, 6) for value in array[index]]))
    return dict(min_self_distance_mm=(None if not math.isfinite(min_distance[0])
                                      else round(min_distance[0], 9)),
                min_self_evidence=(min_distance[1]
                                   if math.isfinite(min_distance[0]) else None),
                search_radius_mm=search_radius,
                sample_step_flat_mm=0.25,
                sample_step_transition_mm=0.05,
                note=('pairs with arc-length separation <= 1 mm are excluded '
                      '(local path neighbourhood, same convention as '
                      'fsd25d.world25d.self_clearance_violations)'),
                violation_count=len(violations),
                violations=violations[:50])


# ===========================================================================
# main
# ===========================================================================
def run_audit(run_dir, out_dir, expect_sha256=None, baseline_dir=None, log=print):
    """Independent geometry audit of ONE run directory (any 1024-route XYZ run).

    ``run_dir``       directory containing ``routes_l3d.json``
    ``out_dir``       where ``independent_metrics.json`` / ``min_distance_evidence.json`` go
    ``expect_sha256`` optional expected routes SHA256 (None -> recorded, not enforced)
    ``baseline_dir``  optional frozen baseline dir used only as an assignment fallback
    """
    started = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    routes_path, digest, payload = load_routes(run_dir)
    routes = payload['routes']
    log('[load] %s sha256=%s routes=%d' % (routes_path, digest, len(routes)))
    result = OrderedDict(
        schema='g4_independent_geometry_metrics_v1',
        run_dir=str(Path(run_dir)),
        routes_file=str(routes_path),
        routes_sha256=digest,
        routes_sha256_expected=expect_sha256,
        routes_sha256_match=((digest == expect_sha256)
                             if expect_sha256 else None),
        route_count=len(routes),
        routed=int(payload.get('routed') or 0),
        failed=len(payload.get('failed') or []),
        timing_seconds={},
    )

    def save():
        (out_dir / 'independent_metrics.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')

    mark = time.time()
    result['identity'] = check_identity(payload, routes)
    log('[identity] pass=%s problems=%d ports=%d (%.1fs)'
        % (result['identity']['pass_'],
           result['identity']['identity_problem_count'],
           result['identity']['port_pose_problem_count'], time.time() - mark))
    save()

    mark = time.time()
    result['heights_r15'] = check_heights_and_r15(routes)
    log('[heights_r15] pass=%s heights=%d arcs=%d transitions=%d (%.1fs)'
        % (result['heights_r15']['pass_'],
           result['heights_r15']['used_height_count'],
           result['heights_r15']['arc_count'],
           result['heights_r15']['transition_count'], time.time() - mark))
    save()

    mark = time.time()
    result['continuity'] = check_continuity(routes)
    log('[continuity] pass=%s junctions=%d max_gap=%.3g (%.1fs)'
        % (result['continuity']['pass_'], result['continuity']['junctions'],
           result['continuity']['max_position_gap_mm'], time.time() - mark))
    save()

    mark = time.time()
    result['glass'] = check_glass(routes)
    log('[glass] pass=%s min_margin=%s min_z=%s max_z=%s (%.1fs)'
        % (result['glass']['pass_'], result['glass']['min_centerline_margin_mm'],
           result['glass']['min_z_mm'], result['glass']['max_z_mm'],
           time.time() - mark))
    save()

    mark = time.time()
    result['manual_u'] = check_manual_u(run_dir, routes, baseline_dir=baseline_dir)
    log('[manual_u] %d manual routes (%.1fs)'
        % (result['manual_u']['manual_route_count'], time.time() - mark))
    save()

    mark = time.time()
    curves = build_curves(routes)
    result['curve_counts'] = dict(
        total=len(curves),
        flat_line=sum(1 for c in curves if c['curve_kind'] == 'flat'
                      and c['kind'] == 'line'),
        flat_arc=sum(1 for c in curves if c['curve_kind'] == 'flat'
                     and c['kind'] == 'arc'),
        transition=sum(1 for c in curves if c['curve_kind'] == 'transition'))
    log('[curves] %s (%.1fs)' % (result['curve_counts'], time.time() - mark))

    mark = time.time()
    first, second, stats = build_candidate_pairs(curves)
    result['candidate_grid'] = stats
    result['candidate_grid']['seconds'] = round(time.time() - mark, 2)
    log('[grid] %s' % stats)
    save()

    mark = time.time()
    result['distance_function_selfcheck'] = cross_validate_distances(
        curves, first, second, log=log)
    result['distance_function_selfcheck']['seconds'] = round(time.time() - mark, 2)
    log('[distance selfcheck] pairs=%d max_error=%.3g pass=%s (%.1fs)'
        % (result['distance_function_selfcheck']['pairs_checked'],
           result['distance_function_selfcheck']['max_absolute_error_mm'],
           result['distance_function_selfcheck']['pass_'],
           time.time() - mark))
    save()

    mark = time.time()
    chains = build_height_chains(routes)
    result['same_layer'] = same_layer_audit(curves, routes, chains,
                                            first, second, log=log)
    result['same_layer']['seconds'] = round(time.time() - mark, 2)
    log('[same_layer] events=%d pairs=%d illegal=%d min_non_crossing=%s (%.1fs)'
        % (result['same_layer']['event_count'],
           result['same_layer']['crossing_pair_count'],
           result['same_layer']['illegal_event_count'],
           result['same_layer']['min_non_crossing_centerline_mm'],
           time.time() - mark))
    save()

    mark = time.time()
    result['flat_flat_cross_height'] = flat_flat_3d(curves, first, second)
    result['flat_flat_cross_height']['seconds'] = round(time.time() - mark, 2)
    log('[flat-flat 3d] min=%s violations=%d (%.1fs)'
        % (result['flat_flat_cross_height']['min_distance_mm'],
           result['flat_flat_cross_height']['violation_count'],
           time.time() - mark))
    save()

    mark = time.time()
    result['transition_vs_flat'] = transition_flat_3d(curves, first, second)
    result['transition_vs_flat']['seconds'] = round(time.time() - mark, 2)
    log('[trans-flat 3d] min=%s violations=%d accurate=%d (%.1fs)'
        % (result['transition_vs_flat']['min_distance_mm'],
           result['transition_vs_flat']['violation_count'],
           result['transition_vs_flat']['accurate_pairs'], time.time() - mark))
    save()

    mark = time.time()
    result['transition_vs_transition'] = transition_transition_3d(curves, first, second)
    result['transition_vs_transition']['seconds'] = round(time.time() - mark, 2)
    log('[trans-trans 3d] min=%s violations=%d accurate=%d (%.1fs)'
        % (result['transition_vs_transition']['min_distance_mm'],
           result['transition_vs_transition']['violation_count'],
           result['transition_vs_transition']['accurate_pairs'],
           time.time() - mark))
    save()

    mark = time.time()
    result['self_clearance'] = self_clearance_audit(routes, log=log)
    result['self_clearance']['seconds'] = round(time.time() - mark, 2)
    log('[self] min=%s violations=%d (%.1fs)'
        % (result['self_clearance']['min_self_distance_mm'],
           result['self_clearance']['violation_count'], time.time() - mark))
    save()

    # ---- required quantities -------------------------------------------------
    same = result['same_layer']
    cross = result['flat_flat_cross_height']
    trans_flat = result['transition_vs_flat']
    trans_trans = result['transition_vs_transition']
    self_block = result['self_clearance']
    non_crossing_3d_candidates = []
    if cross['min_distance_mm'] is not None:
        non_crossing_3d_candidates.append(
            ('flat_flat_different_physical_height', cross['min_distance_mm'],
             cross['min_evidence']))
    if trans_flat['min_distance_mm'] is not None:
        non_crossing_3d_candidates.append(
            ('transition_vs_flat', trans_flat['min_distance_mm'],
             trans_flat['min_evidence']))
    if trans_trans['min_distance_mm'] is not None:
        non_crossing_3d_candidates.append(
            ('transition_vs_transition', trans_trans['min_distance_mm'],
             trans_trans['min_evidence']))
    if non_crossing_3d_candidates:
        min_3d = min(non_crossing_3d_candidates, key=lambda item: item[1])
    else:  # degenerate run: no cross-height pair reached the search radius
        min_3d = ('none', float('inf'), None)
    clearance_violation_count = (same['spacing_violation_count']
                                 + same['illegal_event_count']
                                 + same['always_close_region_problem_count']
                                 + cross['violation_count']
                                 + trans_flat['violation_count']
                                 + trans_trans['violation_count']
                                 + self_block['violation_count'])
    # global minimum over ALL centreline pairs (crossings included)
    if same['event_count'] > 0:
        min_all_pairs = 0.0
        min_all_evidence = (same['events_sample'][0]
                            if same['events_sample'] else None)
    else:
        candidates = list(non_crossing_3d_candidates)
        if same['min_non_crossing_centerline_mm'] is not None:
            candidates.append(('same_layer_2d_non_crossing',
                               same['min_non_crossing_centerline_mm'],
                               same['min_non_crossing_evidence']))
        if self_block['min_self_distance_mm'] is not None:
            candidates.append(('same_route_self_clearance',
                               self_block['min_self_distance_mm'],
                               self_block['min_self_evidence']))
        pick = min(candidates, key=lambda item: item[1])
        min_all_pairs = pick[1]
        min_all_evidence = dict(category=pick[0], evidence=pick[2])
    result['required_quantities'] = OrderedDict(
        minimum_distance_all_pairs_mm=min_all_pairs,
        minimum_distance_all_pairs_evidence=min_all_evidence,
        minimum_clearance_non_crossing_mm=(
            min_3d[1] if math.isfinite(min_3d[1]) else None),
        minimum_clearance_non_crossing_detail=dict(
            overall_min_category=min_3d[0],
            overall_min_evidence=min_3d[2],
            per_category={name: dict(
                distance_mm=value,
                evidence=evidence,
                violation_count={
                    'flat_flat_different_physical_height': cross['violation_count'],
                    'transition_vs_flat': trans_flat['violation_count'],
                    'transition_vs_transition': trans_trans['violation_count'],
                }.get(name))
                for name, value, evidence in non_crossing_3d_candidates},
            same_layer_2d_non_crossing_mm=same['min_non_crossing_centerline_mm'],
            same_layer_2d_evidence=same['min_non_crossing_evidence'],
            self_clearance_min_mm=self_block['min_self_distance_mm'],
        ),
        allowed_crossing_count=same['event_count'],
        illegal_crossing_count=same['illegal_event_count'],
        clearance_violation_count=clearance_violation_count,
        crossing_exemption_policy=dict(
            same_physical_height_rule=(
                'strict D56 2-D centreline clearance %.2f mm (width %.2f + '
                'edge gap %.2f); legal transverse crossings exempt'
                % (CLEARANCE_2D_MM, WIDTH_MM, EDGE_GAP_MM)),
            min_crossing_angle_deg=MIN_CROSS_ANGLE_DEG,
            max_window_half_mm=STRICT_MAX_HALF_WINDOW_MM,
            different_physical_height_rule=(
                'legal when |dz| >= %.2f mm; XY overlap alone is not a '
                'violation' % MIN_3D_CLEARANCE_MM),
            transition_rule=('true 3-D centreline distance >= %.2f mm to every '
                             'other route (transition-vs-flat, '
                             'transition-vs-transition)' % MIN_3D_CLEARANCE_MM),
            min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
            crossing_window_half_max_measured_mm=same['crossing_window_half_max_mm'],
            crossing_angle_range_deg=[same['crossing_angle_min_deg'],
                                      same['crossing_angle_max_deg']],
            source_files=[
                'four_side_1024/fanout1024/common.py',
                'four_side_1024/l3d/world.py',
                'four_side_1024/fsd25d/world25d.py',
                'four_side_1024/fslw/config.py',
                'four_side_1024/fslw/validate_fslw.py',
                'four_side_1024/d56/index.py',
                'four_side_1024/fanout1024/nonc4/crossings.py',
                'four_side_1024/fanout1024/reheight21/validate21.py',
                'four_side_1024/fanout1024/xyzrouter/world_adapter.py',
            ]),
    )
    checks = dict(
        identity=result['identity']['pass_'],
        heights_r15=result['heights_r15']['pass_'],
        continuity=result['continuity']['pass_'],
        glass=result['glass']['pass_'],
        manual_u=result['manual_u']['pass_'],
        crossings_all_allowed=(same['illegal_event_count'] == 0),
        clearance_no_violation=(clearance_violation_count == 0),
    )
    result['independent_verdict'] = dict(
        checks=checks,
        all_passed=all(checks.values()),
        runtime_seconds=round(time.time() - started, 2))

    # ---- evidence file -------------------------------------------------------
    evidence = OrderedDict(
        schema='g4_min_distance_evidence_v1',
        routes_sha256=digest,
        minimum_distance_all_pairs=dict(
            distance_mm=min_all_pairs,
            kind=('same-physical-height flat/flat legal transverse crossing'
                  if same['event_count'] > 0 else 'minimum non-crossing pair'),
            interpretation=(
                'the global minimum over ALL centreline pairs is exactly 0 '
                'because genuine D56 crossings exist; this is the documented '
                'crossing exemption, not a clearance violation'
                if same['event_count'] > 0 else
                'no same-height crossing exists in this run; the global minimum '
                'is the minimum over the non-crossing categories below'),
            evidence=min_all_evidence,
        ),
        minimum_clearance_non_crossing=dict(
            overall=dict(category=min_3d[0],
                         distance_mm=(min_3d[1]
                                      if math.isfinite(min_3d[1]) else None),
                         evidence=min_3d[2]),
            flat_flat_different_height=dict(
                distance_mm=cross['min_distance_mm'],
                evidence=cross['min_evidence'],
                note=('bounded below by the 21-height layer pitch (0.05 mm): '
                      'every flat pair on different heights is vertically '
                      'separated by >= 0.05 mm by construction')),
            transition_vs_flat=dict(distance_mm=trans_flat['min_distance_mm'],
                                    evidence=trans_flat['min_evidence']),
            transition_vs_transition=dict(
                distance_mm=trans_trans['min_distance_mm'],
                evidence=trans_trans['min_evidence']),
            same_layer_2d_non_crossing=dict(
                distance_mm=same['min_non_crossing_centerline_mm'],
                evidence=same['min_non_crossing_evidence']),
            self_clearance=dict(distance_mm=self_block['min_self_distance_mm'],
                                evidence=self_block['min_self_evidence']),
        ),
        crossing_statistics=dict(
            allowed_events=same['event_count'],
            unique_crossing_pairs=same['crossing_pair_count'],
            illegal_events=same['illegal_event_count'],
            max_crossings_per_route=same['max_crossings_per_route'],
            angle_range_deg=[same['crossing_angle_min_deg'],
                             same['crossing_angle_max_deg']],
        ),
        numerical_error_bounds=dict(
            flat_flat_2d_mm=1e-12,
            flat_flat_3d_mm=1e-12,
            transition_vs_flat_mm=1e-8,
            transition_vs_transition_mm=1e-6,
            crossing_point_mm=1e-9,
            note=('flat/flat distances are closed-form; flat/transition minima '
                  'are golden-section refined on the exact analytic S-curve '
                  '(tolerance 1e-10 in s); transition/transition uses a '
                  '1-Lipschitz coarse bracket + nested golden refinement.'),
        ),
    )
    (out_dir / 'min_distance_evidence.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    result['timing_seconds'] = dict(total=round(time.time() - started, 2))
    save()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Independent geometry audit of any 1024-route XYZ joint run.')
    parser.add_argument('--run-dir', default=str(DEFAULT_RUN),
                        help='run directory containing routes_l3d.json')
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT),
                        help='directory for independent_metrics.json / '
                             'min_distance_evidence.json')
    parser.add_argument('--expect-sha256', default=None,
                        help='optional expected routes_l3d.json SHA256')
    parser.add_argument('--baseline-dir', default=None,
                        help='optional frozen baseline dir (assignment fallback)')
    args = parser.parse_args(argv)
    result = run_audit(args.run_dir, args.out_dir,
                       expect_sha256=args.expect_sha256,
                       baseline_dir=args.baseline_dir,
                       log=lambda message: print(message, flush=True))
    summary = dict(
        run_dir=result['run_dir'],
        routes_sha256=result['routes_sha256'],
        all_passed=result['independent_verdict']['all_passed'],
        events=result['same_layer']['event_count'],
        pairs=result['same_layer']['crossing_pair_count'],
        illegal=result['same_layer']['illegal_event_count'],
        clearance_violations=result['required_quantities'][
            'clearance_violation_count'],
        min_non_crossing=result['required_quantities'][
            'minimum_clearance_non_crossing_mm'],
        runtime=result['timing_seconds']['total'])
    print('SUMMARY ' + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result['independent_verdict']['all_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
