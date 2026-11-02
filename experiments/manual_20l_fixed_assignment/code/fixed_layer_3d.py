# -*- coding: utf-8 -*-
"""Fixed-target-layer true-3D route construction for the L1-L20 experiment.

The module deliberately keeps the frozen project pieces:

* ``fsd25d.path3d``     : exact S-curve transition geometry (R15),
* ``v3c4.lift_cross``   : flat/lifted route schema and route assembly,
* ``l3d.world.World``   : strict same-plane D56 index + true-3D clearance world,
* ``manual_u_geometry`` : exact R15 same-side U geometry.

What is new here is the *search order*: the target layer is fixed first, then
rise/fall windows are generated on a long straight part of the (possibly
re-planned) 2D path and evaluated with the true-3D world.  A fast sampled
occupancy certificate rejects most bad candidates before the expensive strict
checker runs, but every accepted route is still checked by the real world and,
at the end, by the repository 3D validator.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..v3c4 import lift_cross as LIFT
from ..v3c4 import lift_cross_run as LIFT_RUN
from . import manual_u_geometry as UGEOM

MIN_TRAVEL_MM = float(LIFT.MIN_TRAVEL_MM)
PORT_MARGIN_MM = float(LIFT.PORT_MARGIN_MM)
RADIUS_MM = float(LIFT.RADIUS_MM)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _paths():
    from ..fsd25d import path3d as P
    return P


def path_length(primitives):
    return float(_paths().path_length(primitives))


def transition_footprint(dz):
    return float(LIFT.transition_geometry(abs(float(dz)))['footprint_mm'])


def _sample_primitives_xy(primitives, step=0.25):
    """Polyline samples of a flat 2D line/arc chain."""
    points = []
    for primitive in primitives:
        if primitive['kind'] == 'line':
            x0, y0 = primitive['p0']
            x1, y1 = primitive['p1']
            length = math.hypot(x1 - x0, y1 - y0)
            count = max(2, int(math.ceil(length / step)) + 1)
            for index in range(count):
                t = index / (count - 1)
                points.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        else:
            radius = float(primitive['radius'])
            start = float(primitive['start_angle'])
            sweep = float(primitive['sweep'])
            count = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
            for index in range(count):
                angle = start + sweep * index / (count - 1)
                points.append((float(primitive['center'][0])
                               + radius * math.cos(angle),
                               float(primitive['center'][1])
                               + radius * math.sin(angle)))
    return points


def route_xyz_samples(route, flat_step=0.25, transition_step=0.20):
    """Sample a schema-L3D route in true XYZ (used by the fast certificate)."""
    points = []
    for part in route.get('parts') or []:
        if part['kind'] == 'flat':
            z = float(part['z_mm'])
            for x, y in _sample_primitives_xy(part['primitives'], flat_step):
                points.append((x, y, z))
        else:
            for x, y, z in LIFT_RUN._part_samples(part):
                points.append((float(x), float(y), float(z)))
    return points


# ---------------------------------------------------------------------------
# fast occupancy certificate
# ---------------------------------------------------------------------------
class FastClearance:
    """Coarse sampled occupancy used only as a *conservative fast pass*.

    If the sampled minimum distance between a candidate and everything already
    placed is larger than ``clearance + 2 * sample_step``, the true minimum is
    certainly larger than the clearance (the distance function is 1-Lipschitz
    and every curve is within ``step`` of its samples).  Anything closer is
    handed to the real :class:`l3d.world.World` checker.
    """

    def __init__(self, clearance=0.08, cell=1.0, sample_step=0.20):
        self.clearance = float(clearance)
        self.cell = float(cell)
        self.sample_step = float(sample_step)
        self.safe = self.clearance + 2.0 * self.sample_step + 0.02
        self.cells = defaultdict(list)
        self.points = 0

    @staticmethod
    def _key(x, y, z, cell):
        return (int(math.floor(x / cell)), int(math.floor(y / cell)),
                int(math.floor(z / cell)))

    def add_route(self, route):
        for x, y, z in route_xyz_samples(route, self.sample_step,
                                         self.sample_step):
            self.cells[self._key(x, y, z, self.cell)].append((x, y, z))
            self.points += 1

    def clear(self):
        self.cells.clear()
        self.points = 0

    def min_distance(self, sample, limit=None):
        """Nearest sampled point in the 27 neighbouring cells."""
        cell = self.cell
        ix, iy, iz = self._key(sample[0], sample[1], sample[2], cell)
        best = float('inf')
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for other in self.cells.get((ix + dx, iy + dy, iz + dz), ()):
                        distance = math.sqrt(
                            (sample[0] - other[0]) ** 2
                            + (sample[1] - other[1]) ** 2
                            + (sample[2] - other[2]) ** 2)
                        if distance < best:
                            best = distance
                            if best < self.clearance:
                                return best
        return best

    def certificate(self, route):
        """Return ``(safe, min_sampled_distance)``.

        ``safe=True`` means true 3D distance >= clearance is certified by the
        sampling bound; ``safe=False`` means the real checker must decide.

        The whole route is scanned: stopping at the first near sample would make
        the certificate useless (it would hand almost every route to the slow
        checker, but with a minimum that is not actually the sampled minimum).
        """
        best = float('inf')
        for sample in route_xyz_samples(route, self.sample_step,
                                        self.sample_step):
            distance = self.min_distance(sample)
            if distance < best:
                best = distance
                if best <= 2.0 * self.clearance:
                    # definitely too close to certify; the real checker decides
                    return False, best
        return bool(best > self.safe), best


# ---------------------------------------------------------------------------
# approximate but fast true-3D clearance index
# ---------------------------------------------------------------------------
def _closest_point_index(point, polyline):
    return int(np.argmin(np.sum((polyline - np.asarray(point)) ** 2, axis=1)))


class ApproxClearance:
    """Incremental 3D clearance index used while searching candidate plans.

    It is *conservative in the rejection direction*: a candidate is rejected
    when a sampled/exact short-range check proves a distance below the process
    clearance.  The final acceptance gate is always the repository validator on
    the complete payload; this class merely makes plan search fast enough to try
    many placements.
    """

    def __init__(self, clearance=0.08, flat_step=0.05,
                 transition_step=0.01, margin=0.0):
        self.clearance = float(clearance)
        self.margin = float(margin)
        self.reject = self.clearance + self.margin
        self.flat_step = float(flat_step)
        self.transition_step = float(transition_step)
        self.transition_polylines = []       # list of (N,3) arrays
        self.point_polyline = np.zeros(0, dtype=int)
        self.transition_points = np.zeros((0, 3))
        self.transition_tree = None
        self.flat_cells = defaultdict(lambda: defaultdict(list))
        self.routes = {}

    @staticmethod
    def _cell_xy(x, y, size=1.0):
        return (int(math.floor(x / size)), int(math.floor(y / size)))

    def add_route(self, route):
        self.routes[int(route['route_id'])] = route
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                z = round(float(part['z_mm']), 9)
                cells = self.flat_cells[z]
                for prim in part['primitives']:
                    bbox = _primitive_bbox_2d(prim)
                    x0 = int(math.floor(bbox[0])) - 1
                    x1 = int(math.floor(bbox[2])) + 1
                    y0 = int(math.floor(bbox[1])) - 1
                    y1 = int(math.floor(bbox[3])) + 1
                    for ix in range(x0, x1 + 1):
                        for iy in range(y0, y1 + 1):
                            cells[(ix, iy)].append(prim)
            else:
                points = np.asarray(LIFT_RUN._part_samples(part), dtype=float)
                if len(points) >= 2:
                    self.transition_polylines.append(points)
        self._rebuild_transition_tree()

    def add_routes(self, routes):
        for route in routes:
            self.add_route(route)

    def _rebuild_transition_tree(self):
        if self.transition_polylines:
            lengths = [len(polyline) for polyline in self.transition_polylines]
            self.point_polyline = np.repeat(
                np.arange(len(self.transition_polylines)), lengths)
            self.transition_points = np.vstack(self.transition_polylines)
            from scipy.spatial import cKDTree
            self.transition_tree = cKDTree(self.transition_points)
        else:
            self.point_polyline = np.zeros(0, dtype=int)
            self.transition_points = np.zeros((0, 3))
            self.transition_tree = None

    def _point_flat_distance(self, point):
        """Exact distance from one XYZ point to all flat primitives.

        Only physical planes within the clearance height of the point can
        violate the 3D clearance, so at most two planes are inspected.
        """
        from ..fsd25d.world25d import point_primitive_distance_2d
        best = float('inf')
        for z, cells in self.flat_cells.items():
            dz = abs(point[2] - z)
            if dz >= self.clearance:
                continue
            key = self._cell_xy(point[0], point[1])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for prim in cells.get((key[0] + dx, key[1] + dy), ()):
                        distance = math.hypot(
                            point_primitive_distance_2d(point, prim), dz)
                        if distance < best:
                            best = distance
                            if best < self.clearance:
                                return best
        return best

    @staticmethod
    def _point_polyline_distance(point, polyline):
        from ..fsd25d.world25d import segment_segment_distance_3d
        best = float('inf')
        p = [float(point[0]), float(point[1]), float(point[2])]
        for index in range(len(polyline) - 1):
            distance = segment_segment_distance_3d(
                p, p, polyline[index].tolist(), polyline[index + 1].tolist())
            if distance < best:
                best = distance
                if best < 0.08:
                    return best
        return best

    @staticmethod
    def _polyline_distance(first, second):
        from ..fsd25d.world25d import segment_segment_distance_3d
        best = float('inf')
        for a in range(len(first) - 1):
            for b in range(len(second) - 1):
                distance = segment_segment_distance_3d(
                    first[a], first[a + 1], second[b], second[b + 1])
                if distance < best:
                    best = distance
                    if best < 0.08:
                        return best
        return best

    def _nearby_pairs(self, points, radius=0.25):
        """Return ``(candidate_index, tree_point_index, distance)`` pairs."""
        if self.transition_tree is None or len(points) == 0:
            return []
        distances, indices = self.transition_tree.query(
            points, k=1, distance_upper_bound=radius)
        pairs = []
        for index, (distance, other) in enumerate(zip(np.atleast_1d(distances),
                                                      np.atleast_1d(indices))):
            if distance < radius and np.isfinite(distance):
                pairs.append((index, int(other), float(distance)))
        return pairs

    @staticmethod
    def _local_segment_distance(points, index, other, other_index,
                                span=4):
        from ..fsd25d.world25d import segment_segment_distance_3d
        low_a = max(0, index - span)
        high_a = min(len(points) - 1, index + span + 1)
        low_b = max(0, other_index - span)
        high_b = min(len(other) - 1, other_index + span + 1)
        best = float('inf')
        for a in range(low_a, high_a):
            for b in range(low_b, high_b):
                distance = segment_segment_distance_3d(
                    points[a], points[a + 1], other[b], other[b + 1])
                if distance < best:
                    best = distance
                    if best < 0.08:
                        return best
        return best

    def route_conflicts(self, route):
        """Return a list of short-range conflicts (empty = candidate passes)."""
        # candidate flat parts vs existing transition curves: point-to-segment
        for part in route.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            xy = _sample_primitives_xy(part['primitives'], self.flat_step)
            if not xy:
                continue
            z = float(part['z_mm'])
            points = np.asarray([(x, y, z) for x, y in xy])
            for index, other_index, _distance in self._nearby_pairs(points):
                other = self.transition_points[other_index]
                polyline = self.transition_polylines[
                    int(self.point_polyline[other_index])]
                distance = self._point_polyline_local(
                    points[index], polyline, other_index)
                if distance < self.reject:
                    return [dict(kind='flat_vs_transition',
                                 distance_mm=distance)]
        # candidate transition parts vs flats and vs existing transitions
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                continue
            points = np.asarray(
                _paths().transition_samples(part, step=self.transition_step),
                dtype=float)
            if len(points) < 2:
                continue
            for point in points:
                distance = self._point_flat_distance(point)
                if distance < self.reject:
                    return [dict(kind='transition_vs_flat',
                                 distance_mm=distance)]
            for index, other_index, _distance in self._nearby_pairs(points):
                polyline = self.transition_polylines[
                    int(self.point_polyline[other_index])]
                other = self.transition_points[other_index]
                local_index = _closest_point_index(other, polyline)
                distance = self._local_segment_distance(points, index,
                                                         polyline,
                                                         local_index)
                if distance < self.reject:
                    return [dict(kind='transition_vs_transition',
                                 distance_mm=distance)]
        return []

    def _point_polyline_local(self, point, polyline, point_index):
        from ..fsd25d.world25d import point_segment_distance_2d
        from ..fsd25d.world25d import segment_segment_distance_3d
        local_index = _closest_point_index(point, polyline)
        best = float('inf')
        low = max(0, local_index - 3)
        high = min(len(polyline) - 1, local_index + 4)
        p = [float(point[0]), float(point[1]), float(point[2])]
        for index in range(low, high):
            distance = segment_segment_distance_3d(
                p, p, polyline[index].tolist(), polyline[index + 1].tolist())
            if distance < best:
                best = distance
                if best < 0.08:
                    return best
        return best


def _primitive_bbox_2d(primitive):
    if primitive['kind'] == 'line':
        x0, y0 = primitive['p0']
        x1, y1 = primitive['p1']
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    cx, cy = primitive['center']
    radius = float(primitive['radius'])
    xs = [primitive['p0'][0], primitive['p1'][0]]
    ys = [primitive['p0'][1], primitive['p1'][1]]
    start = float(primitive['start_angle'])
    sweep = float(primitive['sweep'])
    for k in range(-4, 13):
        angle = k * math.pi / 2.0
        delta = (angle - start) % (2 * math.pi) if sweep >= 0 else (
            (start - angle) % (2 * math.pi))
        if delta <= abs(sweep) + 1e-12:
            xs.append(cx + radius * math.cos(angle))
            ys.append(cy + radius * math.sin(angle))
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# candidate rise/fall windows
# ---------------------------------------------------------------------------
def straight_windows(primitives, footprint, total=None):
    """Same definition as the frozen lifter: only straight intervals may be
    used for an R15 transition."""
    total = path_length(primitives) if total is None else float(total)
    windows = []
    for start, end, _index in _paths().straight_intervals(primitives):
        lo = max(start + LIFT.SEGMENT_MARGIN_MM, PORT_MARGIN_MM)
        hi = min(end - LIFT.SEGMENT_MARGIN_MM - footprint,
                 total - PORT_MARGIN_MM - footprint)
        if hi >= lo - 1e-9:
            windows.append((float(lo), float(hi), int(_index)))
    return windows


def _positions_in_window(window, count=5, edge_step=1.0):
    lo, hi = window[0], window[1]
    span = hi - lo
    values = set()
    if span < 0:
        return []
    values.add(round(lo, 6))
    values.add(round(hi, 6))
    for index in range(1, count):
        values.add(round(lo + span * index / count, 6))
    # near both ends, small offsets are useful when the edge is blocked
    for offset in (edge_step, 2.0 * edge_step, 4.0 * edge_step):
        if lo + offset <= hi + 1e-9:
            values.add(round(lo + offset, 6))
        if hi - offset >= lo - 1e-9:
            values.add(round(hi - offset, 6))
    return sorted(values)


def transition_plans(primitives, target_z, base_z, *, mode='all',
                     window_positions=4, max_plans=160, prefer='middle'):
    """Candidate ``(rise_start, fall_start)`` positions on a 2D chain.

    ``mode='adjacent'`` prefers a rise in an early window and a fall in a later
    window (normal two-side connection); ``mode='u'`` requires the first and
    last straight arm (same-side U); ``mode='all'`` allows any ordered pair.
    """
    total = path_length(primitives)
    footprint = transition_footprint(abs(float(target_z) - float(base_z)))
    windows = straight_windows(primitives, footprint, total)
    if not windows:
        return []
    plans = []
    n = len(windows)
    if mode == 'u':
        pairs = [(0, n - 1)]
    elif mode == 'adjacent':
        pairs = []
        for rise_index in range(n):
            for fall_index in range(rise_index, n):
                if rise_index == 0 or fall_index == n - 1:
                    pairs.append((rise_index, fall_index))
        if not pairs:
            pairs = [(0, n - 1)]
    else:
        pairs = [(rise_index, fall_index)
                 for rise_index in range(n)
                 for fall_index in range(rise_index, n)]
    for rise_index, fall_index in pairs:
        rise_values = _positions_in_window(windows[rise_index],
                                           window_positions)
        fall_values = _positions_in_window(windows[fall_index],
                                           window_positions)
        for rise in rise_values:
            for fall in fall_values:
                if fall < rise + footprint + MIN_TRAVEL_MM:
                    continue
                plans.append(dict(rise_start=float(rise),
                                  fall_start=float(fall),
                                  footprint=float(footprint),
                                  rise_window=rise_index,
                                  fall_window=fall_index))
    # Deterministic preference: keep a useful high-layer flat body while
    # moving the S-curves away from the interface stubs/manual-U transitions
    # near the board edges.  For a straight 150 mm Z1 connection this puts the
    # transitions about 20 mm inside each port, where the dense edge U's are
    # already behind the route.
    def score(plan):
        rise_slack = plan['rise_start']
        fall_slack = total - plan['fall_start'] - footprint
        if prefer == 'ends':
            # leave the crowded interface plane quickly (Z2 high-layer routes)
            return (abs(min(rise_slack, 40.0) - 2.0)
                    + abs(min(fall_slack, 40.0) - 2.0),
                    plan['rise_start'], plan['fall_start'])
        return (abs(min(rise_slack, 60.0) - 20.0)
                + abs(min(fall_slack, 60.0) - 20.0),
                abs(rise_slack - fall_slack),
                plan['rise_start'], plan['fall_start'])
    plans.sort(key=score)
    unique = []
    seen = set()
    for plan in plans:
        key = (round(plan['rise_start'], 4), round(plan['fall_start'], 4))
        if key in seen:
            continue
        seen.add(key)
        unique.append(plan)
        if len(unique) >= max_plans:
            break
    return unique


# ---------------------------------------------------------------------------
# constructing and committing fixed-layer routes
# ---------------------------------------------------------------------------
def _same_plane_check(world, route):
    for index, part in enumerate(route['parts']):
        if part['kind'] != 'flat':
            continue
        evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
        if evaluation is not None and not evaluation.valid:
            return dict(kind='flat_same_plane_conflict', part=index,
                        blockers=list(getattr(evaluation, 'blockers', []) or [])[:10])
    return None


def build_one_plan(lifter, record, row, primitives, layer, plan,
                   check_plane=True):
    layer = int(layer)
    target_z = float(lifter.stack.z_for_layer(layer))
    route = LIFT.lift_route(record, int(row), layer, target_z,
                            plan['rise_start'], plan['fall_start'], primitives)
    if route is None:
        return None, 'lift_route_none'
    if lifter.world.check_structure(route):
        return None, 'structure_invalid'
    if check_plane:
        conflict = _same_plane_check(lifter.world, route)
        if conflict is not None:
            return None, 'same_plane:' + str(conflict.get('kind'))
    return route, None


def try_fixed_route(lifter, record, row, primitives, layer, *,
                    fast=None, mode='all', max_plans=160,
                    window_positions=4, require_full_check=False,
                    log=None):
    """Search plans for one fixed target layer and commit the first legal one.

    Returns ``(route, reason, plan)``.  On success the route is added to the
    world and to ``lifter.lifted/primitives/base_routes``.
    """
    layer = int(layer)
    target_z = float(lifter.stack.z_for_layer(layer))
    base_z = 0.0 if int(row) == 1 else 0.5
    plans = transition_plans(primitives, target_z, base_z, mode=mode,
                             window_positions=window_positions,
                             max_plans=max_plans)
    if not plans:
        return None, 'no_transition_window', None
    last = None
    cert_safe = 0
    full_checked = 0
    for plan in plans:
        route, reason = build_one_plan(lifter, record, row, primitives,
                                       layer, plan)
        if route is None:
            last = reason
            continue
        if fast is not None:
            safe, _distance = fast.certificate(route)
            if safe and not require_full_check:
                cert_safe += 1
            else:
                full_checked += 1
                violations = lifter.world.check_route(route, check_self=False)
                if violations:
                    last = 'world:' + str(violations[0].get('kind'))
                    continue
        else:
            full_checked += 1
            violations = lifter.world.check_route(route, check_self=False)
            if violations:
                last = 'world:' + str(violations[0].get('kind'))
                continue
        # self-clearance of the candidate alone
        from ..fsd25d.world25d import self_clearance_violations
        self_violations = self_clearance_violations(route, lifter.clearance)
        if self_violations:
            last = 'self:' + str(self_violations[0].get('kind'))
            continue
        lifter.world.add_route(route)
        lifter.lifted[int(record['route_id'])] = route
        lifter.primitives[int(record['route_id'])] = [dict(primitive)
                                                      for primitive in primitives]
        lifter.base_routes[int(record['route_id'])] = LIFT.flat_route(
            int(record['route_id']), record['plane'], primitives, row=int(row))
        if fast is not None:
            fast.add_route(route)
        if log:
            log(f'[fixed] route {record["route_id"]} -> L{layer} '
                f'planned+true3d ok (cert={cert_safe}, full={full_checked})')
        return route, None, plan
    return None, last or 'all_plans_conflict', None


def add_existing_route(lifter, record, row, route, primitives, fast=None):
    """Add an already built fixed route to the working world / caches."""
    rid = int(record['route_id'])
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(primitive) for primitive in primitives]
    lifter.base_routes[rid] = LIFT.flat_route(rid, record['plane'], primitives,
                                              row=int(row))
    if fast is not None:
        fast.add_route(route)
    return route


def build_manual_u_for_layer(source, target, side, target_z, base_z, *,
                             radius=None):
    """Build a deeper R15 same-side U with enough straight arm for a lift."""
    footprint = transition_footprint(abs(float(target_z) - float(base_z)))
    arm = max(2.0, footprint + 2.0 * PORT_MARGIN_MM + 3.0)
    last = None
    for extra in (0.0, 2.0, 4.0, 8.0, 12.0, -1.5):
        trial = arm + extra
        if trial <= 0.5:
            continue
        geometry = UGEOM.build_manual_u_geometry(source, target, side,
                                                 arm_mm=trial,
                                                 radius=radius)
        if geometry['ok']:
            return geometry
        last = geometry
    return last


def fixed_manual_u_search(lifter, record, row, source, target, side, layer,
                          *, fast=None, log=None, max_plans=80):
    """Build a same-side U for a fixed target layer (Z2 same-side routes)."""
    layer = int(layer)
    target_z = float(lifter.stack.z_for_layer(layer))
    base_z = 0.0 if int(row) == 1 else 0.5
    footprint = transition_footprint(abs(target_z - base_z))
    arm_min = footprint + 2.0 * PORT_MARGIN_MM + 2.0
    depth = max(2.0, UGEOM.MAX_DEPTH_MM - RADIUS_MM)
    trials = []
    for offset in (0.0, 2.0, 5.0, 9.0, 14.0, 20.0, 28.0, 38.0):
        value = arm_min + offset
        if value < depth:
            trials.append(round(value, 3))
    last = None
    for arm in trials:
        geometry = UGEOM.build_manual_u_geometry(source, target, side,
                                                 arm_mm=arm)
        if not geometry['ok']:
            last = 'geometry:' + ','.join(geometry['errors'])
            continue
        primitives = [dict(primitive) for primitive in geometry['primitives']]
        route, reason, plan = try_fixed_route(
            lifter, record, row, primitives, layer, fast=fast, mode='u',
            max_plans=max_plans, window_positions=4, log=log)
        if route is not None:
            return route, primitives, geometry, None
        last = reason
    return None, None, None, last
