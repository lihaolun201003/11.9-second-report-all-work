# -*- coding: utf-8 -*-
"""Mid-body R15 layer-change geometry (up/down S-curve pair on a straight run)."""
from __future__ import annotations

import copy
import math

from ...fsd25d import path3d as P
from . import common as N

R15 = float(N.R15)


# ------------------------------------------------------------------ footprint
def transition_footprint(dz_mm, radius=R15):
    """Horizontal run of one two-arc R15 S-curve for a height change ``dz``."""
    dz = abs(float(dz_mm))
    if dz <= 1e-12:
        return 0.0
    ratio = 1.0 - dz / (2.0 * float(radius))
    if ratio <= -1.0:
        raise ValueError('height change %.6f too large for R=%.3f' % (dz, radius))
    theta = math.acos(max(-1.0, min(1.0, ratio)))
    return float(2.0 * float(radius) * math.sin(theta))


def transition_theta(dz_mm, radius=R15):
    dz = abs(float(dz_mm))
    if dz <= 1e-12:
        return 0.0
    ratio = 1.0 - dz / (2.0 * float(radius))
    return float(math.acos(max(-1.0, min(1.0, ratio))))


def make_s_curve(start, direction, z0, z1, radius=R15, tag='mid'):
    transition = P.make_transition(start, direction, z0, z1, radius=radius)
    transition['tag'] = str(tag)
    return transition


# ------------------------------------------------------------------ path helpers
def path_total(prims):
    return float(P.path_length(prims))


def point_and_tangent(prims, s):
    point, tangent = P.path_point_at(prims, s)
    return (float(point[0]), float(point[1])), (float(tangent[0]),
                                                float(tangent[1]))


def straight_primitive_span(prims, s):
    """``(start_s, end_s, direction)`` of the straight primitive containing ``s``."""
    total = 0.0
    for prim in prims:
        length = P.prim_length(prim)
        if prim.get('kind') == 'line' and length > 1e-9:
            if total - 1e-9 <= s <= total + length + 1e-9:
                p0, p1 = prim['p0'], prim['p1']
                direction = ((p1[0] - p0[0]) / length,
                             (p1[1] - p0[1]) / length)
                return (total, total + length, direction)
        total += length
    return None


def same_straight_run(prims, s0, s1, tol=1e-6):
    """True when ``[s0, s1]`` lies inside one single straight line primitive."""
    span = straight_primitive_span(prims, 0.5 * (s0 + s1))
    if span is None:
        return None
    lo, hi, direction = span
    if s0 < lo - tol or s1 > hi + tol:
        return None
    return direction


def split_chain(prims, s):
    head, tail = P.path_split(prims, s)
    return [_clean(prim) for prim in head if _clean(prim) is not None], \
        [_clean(prim) for prim in tail if _clean(prim) is not None]


def _clean(prim):
    if prim.get('kind') == 'line':
        p0, p1 = prim['p0'], prim['p1']
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) <= 1e-9:
            return None
    elif prim.get('kind') == 'arc':
        if abs(float(prim.get('sweep') or 0.0)) <= 1e-12:
            return None
    return dict(prim)


def line_primitive(p0, p1):
    return dict(kind='line', p0=[float(p0[0]), float(p0[1])],
                p1=[float(p1[0]), float(p1[1])])


# ------------------------------------------------------------------ excursion
def build_excursion(prims, s0, s1, z_from, z_to, radius=R15,
                    min_middle=float(N.MIN_MIDDLE_MM), max_middle=None):
    """Build one up/travel/down excursion on the straight run ``[s0, s1]``.

    Returns ``dict(prefix, up, middle, down, suffix, footprint_mm,
    middle_mm, direction, z_from, z_to)`` or raises ``ValueError`` with the
    real geometric reason.
    """
    z_from = float(z_from)
    z_to = float(z_to)
    if abs(z_to - z_from) <= 1e-12:
        raise ValueError('target height equals the body height')
    if N.plane_of_z(z_to) is None:
        raise ValueError('target height %.6f is not one of the 21 heights' % z_to)
    total = path_total(prims)
    s0 = float(s0)
    s1 = float(s1)
    if not (1e-6 < s0 < s1 < total - 1e-6):
        raise ValueError('excursion interval outside the flat body')
    direction = same_straight_run(prims, s0, s1)
    if direction is None:
        raise ValueError('excursion interval is not inside one straight run')
    footprint = transition_footprint(z_to - z_from, radius)
    middle = (s1 - s0) - 2.0 * footprint
    if middle < min_middle - 1e-9:
        raise ValueError('excursion too short: middle=%.3f mm < %.3f mm '
                         '(interval %.3f, footprint %.3f)'
                         % (middle, min_middle, s1 - s0, footprint))
    if max_middle is not None and middle > max_middle:
        raise ValueError('excursion too long: middle=%.3f mm > %.3f mm'
                         % (middle, max_middle))
    point0, tangent0 = point_and_tangent(prims, s0)
    point1, tangent1 = point_and_tangent(prims, s1)
    if abs(tangent0[0] - direction[0]) > 1e-6 or abs(tangent0[1] - direction[1]) > 1e-6 \
            or abs(tangent1[0] - direction[0]) > 1e-6 or abs(tangent1[1] - direction[1]) > 1e-6:
        raise ValueError('tangent mismatch inside the straight run')
    up = make_s_curve(point0, direction, z_from, z_to, radius=radius, tag='mid')
    middle_start = tuple(up['end'])
    middle_end = (point1[0] - direction[0] * footprint,
                  point1[1] - direction[1] * footprint)
    middle_length = math.hypot(middle_end[0] - middle_start[0],
                               middle_end[1] - middle_start[1])
    if abs(middle_length - middle) > 1e-6:
        raise ValueError('middle segment length mismatch')
    down = make_s_curve(middle_end, direction, z_to, z_from, radius=radius,
                        tag='mid')
    end = down['end']
    if math.hypot(end[0] - point1[0], end[1] - point1[1]) > 1e-6:
        raise ValueError('down transition does not land on the original path')
    prefix, _rest = split_chain(prims, s0)
    _head, suffix = split_chain(prims, s1)
    return dict(prefix=prefix, up=up,
                middle=line_primitive(middle_start, middle_end),
                down=down, suffix=suffix,
                footprint_mm=float(footprint), middle_mm=float(middle_length),
                direction=[float(direction[0]), float(direction[1])],
                z_from=z_from, z_to=z_to,
                s_start_mm=s0, s_end_mm=s1,
                point_start=[point0[0], point0[1]],
                point_end=[point1[0], point1[1]])


def excursion_from_prims(prims, centre_s, half_span, z_from, z_to, radius=R15,
                         min_middle=float(N.MIN_MIDDLE_MM)):
    """Build an excursion of total length ``2*half_span`` centred at ``centre_s``."""
    s0 = float(centre_s) - float(half_span)
    s1 = float(centre_s) + float(half_span)
    return build_excursion(prims, s0, s1, z_from, z_to, radius=radius,
                           min_middle=min_middle)
