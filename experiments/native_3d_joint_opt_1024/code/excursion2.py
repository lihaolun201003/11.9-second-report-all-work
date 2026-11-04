# -*- coding: utf-8 -*-
"""Phase-2 excursion geometry: arc-spanning excursions and multi-step staircases.

Both are *exact* geometry built only from R15 two-arc S-curves
(:func:`fsd25d.path3d.make_transition`) and axis-aligned / R15 primitives of the
original path.  Nothing is approximated and no z step without a real S-curve is
ever created.

* :func:`build_excursion_general` - move a whole sub-path (which may contain
  R15 arcs, i.e. the experiment-E "arc region") to another routing height:
  the two S-curves are placed on the straight runs flanking the sub-path and the
  sub-path itself is re-used verbatim at the travel height.
* :func:`build_staircase` - climb to a far height in small steps (each S-curve
  between two neighbouring routing planes) with short flats between, then
  descend symmetrically; used when a single far S-curve is blocked by the
  intermediate-height planes.
"""
from __future__ import annotations

import copy
import math

from ...fsd25d import path3d as P
from . import common as N
from . import route_model as RM
from . import transition as T

R15 = float(N.R15)


# ------------------------------------------------------------------ helpers
def _straight(prims, s_start, s_end, tol=1e-6):
    """Unit direction of the single straight run containing ``[s_start, s_end]``."""
    direction = T.same_straight_run(prims, s_start, s_end, tol=tol)
    if direction is None:
        return None
    return direction


def _sub_chain(prims, s_start, s_end):
    total = P.path_length(prims)
    s_start = max(0.0, min(total, float(s_start)))
    s_end = max(0.0, min(total, float(s_end)))
    if s_end - s_start <= 1e-9:
        return []
    _head, rest = P.path_split(prims, s_start)
    segment, _tail = P.path_split(rest, s_end - s_start)
    return [dict(prim) for prim in segment if _non_degenerate(prim)]


def _non_degenerate(prim):
    if prim.get('kind') == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 1e-9
    if prim.get('kind') == 'arc':
        return abs(float(prim.get('sweep') or 0.0)) > 1e-12
    return True


# ------------------------------------------------------------------ general
def build_excursion_general(prims, s0, s1, z_from, z_to, radius=R15,
                            min_middle=float(N.MIN_MIDDLE_MM)):
    """Move the sub-path ``[s0+f, s1-f]`` to ``z_to`` (may contain R15 arcs).

    ``[s0, s0+f]`` and ``[s1-f, s1]`` must each lie inside one straight run so
    that the S-curve footprints align exactly with the original path.
    """
    z_from = float(z_from)
    z_to = float(z_to)
    if abs(z_to - z_from) <= 1e-12:
        raise ValueError('target height equals the body height')
    if N.plane_of_z(z_to) is None:
        raise ValueError('target height %.6f is not one of the 21 heights' % z_to)
    total = P.path_length(prims)
    s0 = float(s0)
    s1 = float(s1)
    if not (1e-6 < s0 < s1 < total - 1e-6):
        raise ValueError('excursion interval outside the body path')
    f = T.transition_footprint(z_to - z_from, radius)
    start_end = s0 + f
    end_start = s1 - f
    middle_length = end_start - start_end
    if middle_length < min_middle - 1e-9:
        raise ValueError('excursion too short (middle %.3f mm < %.3f mm)'
                         % (middle_length, min_middle))
    direction_start = _straight(prims, s0, start_end)
    direction_end = _straight(prims, end_start, s1)
    if direction_start is None or direction_end is None:
        raise ValueError('S-curve feet are not on straight runs')
    point0, _t0 = T.point_and_tangent(prims, s0)
    point_mid_start, _tm = T.point_and_tangent(prims, start_end)
    point_mid_end, _te = T.point_and_tangent(prims, end_start)
    point1, _t1 = T.point_and_tangent(prims, s1)
    up = T.make_s_curve(point0, direction_start, z_from, z_to, radius=radius,
                        tag='mid')
    middle = _sub_chain(prims, start_end, end_start)
    down = T.make_s_curve(point_mid_end, direction_end, z_to, z_from,
                          radius=radius, tag='mid')
    if math.hypot(up['end'][0] - point_mid_start[0],
                  up['end'][1] - point_mid_start[1]) > 1e-6:
        raise ValueError('up S-curve does not land on the path')
    if math.hypot(down['end'][0] - point1[0],
                  down['end'][1] - point1[1]) > 1e-6:
        raise ValueError('down S-curve does not land on the path')
    contains_arc = any(prim.get('kind') == 'arc' for prim in middle)
    prefix = _sub_chain(prims, 0.0, s0)
    suffix = _sub_chain(prims, s1, total)
    return dict(prefix=prefix, up=up, middle=middle, down=down,
                suffix=suffix, footprint_mm=float(f),
                middle_mm=float(middle_length),
                contains_arc=bool(contains_arc),
                s_start_mm=s0, s_end_mm=s1,
                z_from=z_from, z_to=z_to)


def insert_excursion_general(route, body_part_index, s0, s1, z_to,
                             radius=R15,
                             interface_z=None):
    """Insert one (possibly arc-containing) excursion into a route."""
    parts = route['parts']
    body = parts[body_part_index]
    if body['kind'] != 'flat':
        raise ValueError('excursion must start from a flat body part')
    z_from = float(body['z_mm'])
    prims = [dict(prim) for prim in body['primitives']]
    built = build_excursion_general(prims, s0, s1, z_from, float(z_to),
                                    radius=radius)
    new_route = copy.deepcopy(route)
    new_parts = [copy.deepcopy(part) for part in parts[:body_part_index]]
    base = len(new_parts)
    new_parts.append(RM.make_flat(z_from, built['prefix'], tag='body'))
    up = built['up']
    up['tag'] = 'mid'
    new_parts.append(up)
    new_parts.append(RM.make_flat(float(z_to), built['middle'], tag='body'))
    down = built['down']
    down['tag'] = 'mid'
    new_parts.append(down)
    new_parts.append(RM.make_flat(z_from, built['suffix'], tag='body'))
    new_parts.extend(copy.deepcopy(part) for part in parts[body_part_index + 1:])
    new_route['parts'] = new_parts
    record = dict(s_start_mm=round(float(s0), 6),
                  s_end_mm=round(float(s1), 6),
                  from_z=z_from, to_z=float(z_to),
                  from_plane=N.plane_of_z(z_from),
                  to_plane=N.plane_of_z(float(z_to)),
                  up_part_index=base + 1, down_part_index=base + 3,
                  middle_part_index=base + 2, prefix_part_index=base,
                  suffix_part_index=base + 4,
                  footprint_mm=round(float(built['footprint_mm']), 6),
                  middle_mm=round(float(built['middle_mm']), 6),
                  contains_arc=bool(built['contains_arc']),
                  kind='arc_span' if built['contains_arc'] else 'excursion',
                  body_part_index=int(body_part_index))
    new_route = N.rebuild_route_metadata(new_route, interface_z=interface_z)
    new_route = RM.tag_parts(new_route)
    new_route['native_3d'] = True
    new_route['excursions'] = list(new_route.get('excursions') or []) + [record]
    return dict(route=new_route, excursion=record,
                footprint_mm=float(built['footprint_mm']),
                middle_mm=float(built['middle_mm']),
                contains_arc=bool(built['contains_arc']))


# ------------------------------------------------------------------ staircase
def staircase_path(z_from, z_goal, step_mm=0.05, min_middle=float(N.MIN_MIDDLE_MM),
                   radius=R15):
    """Plan a staircase through the real 21 heights (never by plane id).

    Each S-curve changes the height by ``step_mm`` (0.05 => strictly between two
    neighbouring routing planes; 0.10 => crosses exactly one intermediate
    plane).  Returns ``dict(steps=[{z0,z1,footprint}], climb_mm, n_steps,
    n_transitions, min_middle_mm, feasible)``.
    """
    z_from = float(z_from)
    z_goal = float(z_goal)
    if abs(z_goal - z_from) <= 1e-12:
        raise ValueError('staircase target equals the source height')
    heights = sorted(N.all_heights())
    step = float(step_mm)
    if step <= 0:
        raise ValueError('step must be positive')
    # heights between (exclusive)
    sign = 1.0 if z_goal > z_from else -1.0
    lo, hi = sorted((z_from, z_goal))
    between = [z for z in heights if lo + 1e-9 < z < hi - 1e-9]
    if sign > 0:
        between = between
    mid_steps = [z_from] + between + [z_goal]
    steps = []
    for first, second in zip(mid_steps, mid_steps[1:]):
        dz = second - first
        if abs(dz) > step + 1e-6:
            # split into equal sub-steps of <= step (using only real heights is
            # impossible here; caller should use step=0.05/0.10 patterns)
            count = int(math.ceil(abs(dz) / step - 1e-9))
            for index in range(count):
                a = first + dz * index / count
                b = first + dz * (index + 1) / count
                steps.append(dict(z0=a, z1=b,
                                  footprint=T.transition_footprint(b - a,
                                                                   radius)))
        else:
            steps.append(dict(z0=first, z1=second,
                              footprint=T.transition_footprint(dz, radius)))
    climb = sum(step['footprint'] for step in steps) \
        + max(0, len(steps) - 1) * float(min_middle)
    return dict(steps=steps, z_from=z_from, z_goal=z_goal,
                sign=sign, climb_mm=float(climb),
                n_steps=len(steps), n_transitions=2 * len(steps),
                min_middle_mm=float(min_middle),
                total_required_mm=float(2.0 * climb),
                feasible=True)


def build_staircase(prims, s0, s1, z_from, z_goal, step_mm=0.05,
                    min_middle=float(N.MIN_MIDDLE_MM), radius=R15,
                    top_min_mm=0.0):
    """Replace the straight run ``[s0, s1]`` by a staircase visit to ``z_goal``.

    The traverse must stay on one straight run (all S-curves share the same
    direction); the resulting parts chain is
    ``up steps + top flat + down steps``.
    """
    total = P.path_length(prims)
    s0 = float(s0)
    s1 = float(s1)
    if not (1e-6 < s0 < s1 < total - 1e-6):
        raise ValueError('staircase interval outside the body path')
    direction = _straight(prims, s0, s1)
    if direction is None:
        raise ValueError('staircase traverse is not one straight run')
    plan = staircase_path(z_from, z_goal, step_mm=step_mm,
                          min_middle=min_middle, radius=radius)
    climb = plan['climb_mm']
    needed = 2.0 * climb + float(top_min_mm)
    available = s1 - s0
    if available < needed - 1e-9:
        raise ValueError('staircase run too short: available %.3f mm < '
                         'required %.3f mm' % (available, needed))
    top_length = available - 2.0 * climb
    point_start, _t = T.point_and_tangent(prims, s0)
    parts = []
    cursor = s0
    # climbing
    z_current = float(z_from)
    for index, step in enumerate(plan['steps']):
        point, _tangent = T.point_and_tangent(prims, cursor)
        up = T.make_s_curve(point, direction, z_current, step['z1'],
                            radius=radius, tag='mid')
        parts.append(up)
        cursor += step['footprint']
        z_current = step['z1']
        if index < len(plan['steps']) - 1:
            point_a, _ta = T.point_and_tangent(prims, cursor)
            point_b, _tb = T.point_and_tangent(prims,
                                               cursor + float(min_middle))
            parts.append(RM.make_flat(z_current,
                                      [dict(kind='line', p0=list(point_a),
                                            p1=list(point_b))], tag='body'))
            cursor += float(min_middle)
    # top flat at z_goal
    if top_length > 1e-6:
        point_a, _ta = T.point_and_tangent(prims, cursor)
        point_b, _tb = T.point_and_tangent(prims, cursor + top_length)
        parts.append(RM.make_flat(float(z_goal),
                                  [dict(kind='line', p0=list(point_a),
                                        p1=list(point_b))], tag='body'))
        cursor += top_length
    # descending (mirror of the climb)
    z_current = float(z_goal)
    descending = list(reversed(plan['steps']))
    for index, step in enumerate(descending):
        point, _tangent = T.point_and_tangent(prims, cursor)
        down = T.make_s_curve(point, direction, z_current, step['z0'],
                              radius=radius, tag='mid')
        parts.append(down)
        cursor += step['footprint']
        z_current = step['z0']
        if index < len(descending) - 1:
            point_a, _ta = T.point_and_tangent(prims, cursor)
            point_b, _tb = T.point_and_tangent(prims,
                                               cursor + float(min_middle))
            parts.append(RM.make_flat(z_current,
                                      [dict(kind='line', p0=list(point_a),
                                            p1=list(point_b))], tag='body'))
            cursor += float(min_middle)
    if abs(cursor - s1) > 1e-6:
        raise ValueError('staircase did not rejoin the original path '
                         '(cursor %.9f != s1 %.9f)' % (cursor, s1))
    prefix = _sub_chain(prims, 0.0, s0)
    suffix = _sub_chain(prims, s1, total)
    return dict(prefix=prefix, parts=parts, suffix=suffix, plan=plan,
                top_length_mm=float(top_length), footprint_total=float(climb),
                s_start_mm=s0, s_end_mm=s1, z_from=float(z_from),
                z_goal=float(z_goal))


def insert_staircase(route, body_part_index, s0, s1, z_goal, step_mm=0.05,
                     min_middle=float(N.MIN_MIDDLE_MM), interface_z=None):
    parts = route['parts']
    body = parts[body_part_index]
    if body['kind'] != 'flat':
        raise ValueError('staircase must start from a flat body part')
    z_from = float(body['z_mm'])
    prims = [dict(prim) for prim in body['primitives']]
    built = build_staircase(prims, s0, s1, z_from, float(z_goal),
                            step_mm=step_mm, min_middle=min_middle)
    new_route = copy.deepcopy(route)
    new_parts = [copy.deepcopy(part) for part in parts[:body_part_index]]
    base = len(new_parts)
    new_parts.append(RM.make_flat(z_from, built['prefix'], tag='body'))
    new_parts.extend(copy.deepcopy(part) for part in built['parts'])
    new_parts.append(RM.make_flat(z_from, built['suffix'], tag='body'))
    new_parts.extend(copy.deepcopy(part) for part in parts[body_part_index + 1:])
    new_route['parts'] = new_parts
    first_mid = base + 1
    record = dict(s_start_mm=round(float(s0), 6),
                  s_end_mm=round(float(s1), 6),
                  from_z=z_from, to_z=float(z_goal),
                  from_plane=N.plane_of_z(z_from),
                  to_plane=N.plane_of_z(float(z_goal)),
                  up_part_index=first_mid,
                  down_part_index=first_mid + len(built['parts']) - 1,
                  middle_part_index=first_mid,
                  prefix_part_index=base,
                  suffix_part_index=base + 1 + len(built['parts']),
                  footprint_mm=round(float(built['footprint_total']), 6),
                  middle_mm=round(float(built['top_length_mm']), 6),
                  contains_arc=False,
                  kind='staircase',
                  n_steps=built['plan']['n_steps'],
                  step_mm=float(step_mm),
                  body_part_index=int(body_part_index))
    new_route = N.rebuild_route_metadata(new_route, interface_z=interface_z)
    new_route = RM.tag_parts(new_route)
    new_route['native_3d'] = True
    new_route['excursions'] = list(new_route.get('excursions') or []) + [record]
    return dict(route=new_route, excursion=record,
                footprint_total=float(built['footprint_total']),
                top_length_mm=float(built['top_length_mm']),
                n_steps=built['plan']['n_steps'],
                n_transitions=built['plan']['n_transitions'])
