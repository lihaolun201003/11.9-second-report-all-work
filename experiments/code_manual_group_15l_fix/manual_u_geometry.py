# -*- coding: utf-8 -*-
"""Real, deeply nested manual same-side U geometry (R = 15 mm).

This module deliberately does **not** reuse the frozen 2D primitives of the
campaign layout: every manual connection gets a freshly constructed U made of
straight lines and exact R15 quarter arcs.  The depth of each U follows the
measured containment of the endpoint intervals on its board side (outer
connection -> deeper U, inner connection -> shallower U), and the elevation
S-curves are later placed inside the resulting straight arms.

Main entry points
-----------------
``build_manual_u_geometry(source, target, side, arm_mm=...)``
    one legal U chain in world coordinates (port coordinates unchanged,
    tangent-continuous, exact R15 arcs, inside the board).
``nesting_plan(items, arm_min_mm, depth_step_mm)``
    containment analysis of one layer/side and the arm length of every U.
``measure_min_clearance(primitives_by_id)``
    minimum centre-line distance between sampled paths (reporting only).
"""
from __future__ import annotations

import math

from ..fslw import config as C
from ..fslw import geom
from ..geometry import length as geometry_length
from ..legacy_geometry import transform_primitives
from ..r15 import profile_r15
from ..r15 import u_geometry as U

BOARD_MM = 150.0
#: R15 process radius and clearance, resolved from the frozen profile.
PROFILE_RADIUS_MM = float(profile_r15.RADIUS_MM)
PROFILE_CLEARANCE_MM = float(C.CLEARANCE_MM)
#: Same port margin as the frozen crossing-lift engine.
PORT_MARGIN_MM = 1.2
#: Additional depth step used to prove the nested U clearance (mm).
DEPTH_STEP_MM = 0.10
MAX_DEPTH_MM = 140.0

SIDE_INWARD = U.SIDE_INWARD
SIDE_ORDER = U.SIDE_ORDER


# ---------------------------------------------------------------------------
# geometry construction
# ---------------------------------------------------------------------------
def build_manual_u_geometry(source, target, side, *, arm_mm,
                            radius=None, board=None, width=None):
    """Build one real same-side U from ``source`` to ``target``.

    Parameters
    ----------
    source, target : (x, y) world port positions (mm) — never moved.
    side : ``'N' | 'S' | 'E' | 'W'`` — common board side of both ports.
    arm_mm : straight length of each arm before/after the 180-degree turn; the
        U depth (port line -> bottom centre line) is ``radius + arm_mm``.

    Returns
    -------
    dict with ``ok``, ``primitives`` (line/arc chain), ``depth_mm``,
    ``arm_mm``, ``bottom_straight_mm``, ``length_mm``, ``radius_mm`` and an
    ``errors`` list (specific failure reasons; no fake path is ever returned).
    """
    radius = U.resolve_radius(radius)
    board = U.resolve_board(board)
    width = U.resolve_width(width)
    inward = SIDE_INWARD[side]
    end_dir = (-inward[0], -inward[1])
    frame, frame_errors = U._canonical_frame(
        source, target, inward, end_dir, board, width)
    result = dict(ok=False, side=side, source=tuple(map(float, source)),
                  target=tuple(map(float, target)), radius_mm=float(radius),
                  arm_mm=float(arm_mm), depth_mm=float(radius) + float(arm_mm),
                  bottom_straight_mm=None, length_mm=None,
                  primitives=[], errors=list(frame_errors))
    if frame is None:
        return result
    separation = float(frame['separation_mm'])
    two_r = 2.0 * radius
    result['separation_mm'] = separation
    if separation <= 1e-9:
        result['errors'].append('coincident_ports')
        return result
    if separation < two_r - 1e-9:
        result['errors'].append('below_minimum_separation_no_radius_shrink')
        return result
    arm = float(arm_mm)
    depth = radius + arm
    if arm <= 1e-9:
        result['errors'].append('arm_must_be_positive')
        return result
    if depth > min(MAX_DEPTH_MM, board - PORT_MARGIN_MM):
        result['errors'].append('u_depth_exceeds_board')
        return result
    middle = separation - two_r
    canonical = U._quarter_pair(frame['p_canonical'], frame['q_canonical'],
                                radius, arm, middle)
    primitives = transform_primitives(canonical, frame['transform'],
                                      inverse=True)
    # exact port poses + tangent continuity + board bounds + exact R15 arcs
    ok, canonical_errors = geom.canonical_validate(
        primitives, frame['source'], frame['target'],
        frame['start_dir'], frame['end_dir'], radius=radius, width=width)
    errors = list(canonical_errors or [])
    for index, primitive in enumerate(primitives):
        if primitive['kind'] == 'arc':
            if abs(float(primitive['radius']) - radius) > 1e-9:
                errors.append(f'arc_radius_not_r15:{index}')
        elif primitive['kind'] != 'line':
            errors.append(f'unknown_primitive:{index}')
    result.update(
        ok=not errors, errors=errors, primitives=primitives,
        bottom_straight_mm=float(middle),
        length_mm=float(geometry_length(primitives)))
    return result


# ---------------------------------------------------------------------------
# nesting analysis
# ---------------------------------------------------------------------------
def nesting_plan(items, *, arm_min_mm, depth_step_mm=DEPTH_STEP_MM):
    """Containment analysis of one layer/side.

    ``items`` : list of dicts with ``route_id``, ``source``, ``target``.
    Returns ``{route_id: dict(contains, chain_size, arm_mm, depth_mm)}`` where
    the outermost connection of a nested chain gets the deepest U and the
    innermost one the shallowest (``arm_min_mm``); disjoint chains are sized
    independently.
    """
    axis = None
    spans = []
    for item in items:
        source = item['source']
        target = item['target']
        if axis is None:
            axis = 0 if abs(target[0] - source[0]) >= abs(target[1] - source[1]) else 1
        low = min(source[axis], target[axis])
        high = max(source[axis], target[axis])
        spans.append((low, high, int(item['route_id'])))
    # strict containment count for every interval
    contains = {}
    for index_a, (low_a, high_a, rid_a) in enumerate(spans):
        count = 0
        for index_b, (low_b, high_b, rid_b) in enumerate(spans):
            if index_a == index_b:
                continue
            if low_b < low_a - 1e-9 and high_b > high_a + 1e-9:
                count += 1
        contains[rid_a] = count
    # chain of rid = rid + its containers + its descendants; K = the largest
    # containment index inside that chain (= chain size - 1 for a plain chain)
    plan = {}
    for index_a, (low_a, high_a, rid_a) in enumerate(spans):
        chain = [rid_a]
        for index_b, (low_b, high_b, rid_b) in enumerate(spans):
            if index_b == index_a:
                continue
            if ((low_b < low_a - 1e-9 and high_b > high_a + 1e-9)
                    or (low_a < low_b - 1e-9 and high_a > high_b + 1e-9)):
                chain.append(rid_b)
        k = max(contains[rid] for rid in chain)
        arm = arm_min_mm + (k - contains[rid_a]) * depth_step_mm
        plan[rid_a] = dict(contains=contains[rid_a], chain_k=k,
                           lowest=low_a, highest=high_a,
                           arm_mm=float(arm),
                           depth_mm=float(PROFILE_RADIUS_MM + arm))
    return plan


# ---------------------------------------------------------------------------
# clearance measurement (reporting only — the real gate is the frozen world)
# ---------------------------------------------------------------------------
def _sample_xy(primitives, sagitta=0.002):
    """Deterministic polyline sampling of a line/arc chain (numpy Nx2)."""
    import numpy as np
    points = []
    for primitive in primitives:
        if primitive['kind'] == 'line':
            points.append(list(primitive['p0']))
            points.append(list(primitive['p1']))
        else:
            radius = float(primitive['radius'])
            center = primitive['center']
            start = float(primitive['start_angle'])
            sweep = float(primitive['sweep'])
            step = max(1e-4, math.sqrt(8.0 * sagitta / max(radius, 1e-6)))
            count = max(2, int(math.ceil(abs(sweep) / step)) + 1)
            for index in range(count):
                angle = start + sweep * index / (count - 1)
                points.append([center[0] + radius * math.cos(angle),
                               center[1] + radius * math.sin(angle)])
    if not points:
        return None
    return np.asarray(points, dtype=float)


def measure_min_clearance(primitives_by_id):
    """Minimum sampled centre-line distance between two different routes."""
    import numpy as np
    samples = {}
    for rid, primitives in primitives_by_id.items():
        array = _sample_xy(primitives)
        if array is not None:
            samples[int(rid)] = array
    best = None
    best_pair = None
    ids = sorted(samples)
    for index, first in enumerate(ids):
        array_a = samples[first]
        for second in ids[index + 1:]:
            array_b = samples[second]
            # nearest neighbour distance between the two point sets
            distance = math.inf
            chunk = 256
            for start in range(0, len(array_a), chunk):
                block = array_a[start:start + chunk]
                deltas = block[:, None, :] - array_b[None, :, :]
                distance = min(distance,
                               float(np.min(np.hypot(deltas[..., 0],
                                                     deltas[..., 1]))))
                if best is not None and distance >= best:
                    break
            if distance < math.inf and (best is None or distance < best):
                best = float(distance)
                best_pair = (first, second)
    return dict(min_clearance_mm=best, pair=best_pair)


# ---------------------------------------------------------------------------
# convenience: interval of a metadata row (diagnostics)
# ---------------------------------------------------------------------------
def interval_of(source, target):
    axis = 0 if abs(target[0] - source[0]) >= abs(target[1] - source[1]) else 1
    return (min(source[axis], target[axis]), max(source[axis], target[axis]))


__all__ = ['BOARD_MM', 'PROFILE_RADIUS_MM', 'PROFILE_CLEARANCE_MM',
           'PORT_MARGIN_MM', 'DEPTH_STEP_MM', 'MAX_DEPTH_MM',
           'SIDE_INWARD', 'SIDE_ORDER', 'build_manual_u_geometry',
           'nesting_plan', 'measure_min_clearance', 'interval_of']
