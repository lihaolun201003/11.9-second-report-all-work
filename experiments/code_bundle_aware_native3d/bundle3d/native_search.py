"""Native 3D A* search prototype (P3).

State: ``(cell_x, cell_y, heading, layer)`` where heading is one of the four axis
directions, layer is the interface plane (1 = z 0.5 for Z2) or a high routing
layer.  Actions are:
  * straight runs (1..32 cells, pitch 1.25 mm),
  * R15 quarter-turn arcs (displacement R*h + R*new_heading, heading rotates),
  * vertical S-curve transitions to any other layer (frozen transition model).
Every action is sampled and checked against the full 3D obstacle cloud of the
best 15-layer layout, so the corridor is genuinely generated in XYZ.

The final connection to the exact port pose uses frozen R15 docking templates
(straight / S / L / U) whose geometry is solved exactly; this is the remaining
template-assisted part and is reported as such.
"""
from __future__ import annotations

import heapq
import json
import math
import time
from pathlib import Path

import numpy as np

RADIUS = 15.0
CLEARANCE = 0.08
SAMPLE = 0.35
PITCH = 1.25
BOARD = 150.0
ARC_CELLS = 12
INTERFACE_Z = 0.5


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def sample_line_dir(p0, p1, step=SAMPLE):
    direction = (p1[0] - p0[0], p1[1] - p0[1])
    norm = math.hypot(*direction)
    direction = (0.0, 0.0) if norm < 1e-12 else (direction[0] / norm,
                                                 direction[1] / norm)
    return [(x, y, direction[0], direction[1])
            for x, y in sample_line(p0, p1, step)]


def sample_arc_dir(start, heading, direction, angle=math.pi / 2.0, radius=RADIUS,
                   step=SAMPLE):
    points = sample_arc(start, heading, direction, angle, radius, step)
    out = []
    for index, point in enumerate(points):
        if index + 1 < len(points):
            nxt = points[index + 1]
        else:
            nxt = points[index]
            point = points[index - 1]
        dx, dy = nxt[0] - point[0], nxt[1] - point[1]
        norm = math.hypot(dx, dy) or 1.0
        out.append((nxt[0], nxt[1], dx / norm, dy / norm))
    return out


def sample_transition_dir(start, heading, z0, z1, radius=RADIUS, step=0.2):
    return [(x, y, z, heading[0], heading[1])
            for x, y, z in sample_transition(start, heading, z0, z1, radius, step)]


def sample_line(p0, p1, step=SAMPLE):
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    count = max(2, int(math.ceil(length / step)) + 1)
    return [(p0[0] + (p1[0] - p0[0]) * index / (count - 1),
             p0[1] + (p1[1] - p0[1]) * index / (count - 1))
            for index in range(count)]


def sample_arc(start, heading, direction, angle=math.pi / 2.0, radius=RADIUS,
               step=SAMPLE):
    """Arc from ``start`` heading ``heading`` turning by signed ``direction*angle``.

    ``direction=+1`` is a left turn (heading rotates towards the left normal).
    """
    count = max(2, int(math.ceil(radius * angle / step)) + 1)
    left = (-heading[1], heading[0])
    points = []
    for index in range(count):
        phi = angle * index / (count - 1)
        u = radius * math.sin(phi)
        v = direction * radius * (1.0 - math.cos(phi))
        points.append((start[0] + heading[0] * u + left[0] * v,
                       start[1] + heading[1] * u + left[1] * v))
    return points


def transition_footprint(dz, radius=RADIUS):
    ratio = 1.0 - abs(float(dz)) / (2.0 * radius)
    theta = math.acos(max(-1.0, min(1.0, ratio)))
    return 2.0 * radius * math.sin(theta), theta


def sample_transition(start, heading, z0, z1, radius=RADIUS, step=0.2):
    dz = z1 - z0
    footprint, theta = transition_footprint(dz)
    sign = 1.0 if dz >= 0 else -1.0
    length = 2.0 * radius * theta
    count = max(2, int(math.ceil(length / step)) + 1)
    points = []
    for index in range(count):
        s = length * index / (count - 1)
        if s <= length / 2.0:
            phi = s / radius
            u = radius * math.sin(phi)
            z = z0 + sign * radius * (1.0 - math.cos(phi))
        else:
            phi = (length - s) / radius
            u = footprint - radius * math.sin(phi)
            z = z1 - sign * radius * (1.0 - math.cos(phi))
        points.append((start[0] + heading[0] * u,
                       start[1] + heading[1] * u, z))
    return points


class ObstacleCloud:
    def __init__(self, payload):
        from scipy.spatial import cKDTree
        heights = {}
        for key, value in ((payload.get('layer_stack') or {})
                           .get('layers') or {}).items():
            if value.get('layer_type') == 'routing':
                heights[int(key)] = float(value['physical_z_mm'])
        self.heights = dict(sorted(heights.items()))
        points = []
        for record in payload['routes']:
            if record.get('status') != 'routed':
                continue
            for part in record.get('parts') or []:
                if part.get('kind') == 'flat':
                    z = float(part['z_mm'])
                    for primitive in part.get('primitives') or []:
                        points.extend(_sample_primitive(primitive, z))
                elif part.get('kind') == 'transition':
                    points.extend(sample_transition_dir(
                        part['start'], part['direction'], float(part['z0']),
                        float(part['z1'])))
        self.points = np.asarray([point[:3] for point in points], dtype=float)
        self.dirs = np.asarray([point[3:5] for point in points], dtype=float)
        self.tree = cKDTree(self.points)

    def min_distance(self, samples):
        if not samples:
            return float('inf')
        distance, _index = self.tree.query(np.asarray(samples, dtype=float))
        return float(np.min(distance))

    def clear(self, samples, dirs=None, threshold=CLEARANCE,
              parallel_sin=0.5, k=6):
        """Clearance that allows transversal crossings but blocks parallel overlap."""
        if not samples:
            return True
        sample_points = np.asarray([point[:3] for point in samples], dtype=float)
        distances, indices = self.tree.query(sample_points, k=min(k, len(self.points)))
        if distances.ndim == 1:
            distances = distances[:, None]
            indices = indices[:, None]
        if dirs is None:
            return float(np.min(distances)) >= threshold
        sample_dirs = np.asarray(dirs, dtype=float)
        for row in range(len(sample_points)):
            for column in range(distances.shape[1]):
                if distances[row, column] >= threshold:
                    continue
                obstacle_dir = self.dirs[indices[row, column]]
                candidate_dir = sample_dirs[row]
                cross = abs(candidate_dir[0] * obstacle_dir[1]
                            - candidate_dir[1] * obstacle_dir[0])
                if cross < parallel_sin:
                    return False
        return True


def _sample_primitive(primitive, z):
    kind = primitive.get('kind')
    if kind == 'line':
        p0, p1 = primitive['p0'], primitive['p1']
        return [(x, y, z, dx, dy) for x, y, dx, dy
                in sample_line_dir(tuple(p0), tuple(p1))]
    # arc primitive used by the frozen V4 layout: p0, p1, center, radius, sweep
    from ..v3c4 import lift_cross_run as LCR
    sampled = LCR._sample_primitive(dict(primitive), step_deg=2.0)
    if sampled is None:
        return []
    points = [(float(x), float(y)) for x, y in sampled]
    out = []
    for index, point in enumerate(points):
        if index + 1 < len(points):
            other = points[index + 1]
            dx, dy = other[0] - point[0], other[1] - point[1]
        elif index > 0:
            other = points[index - 1]
            dx, dy = point[0] - other[0], point[1] - other[1]
        else:
            dx, dy = 0.0, 0.0
        norm = math.hypot(dx, dy) or 1.0
        out.append((point[0], point[1], z, dx / norm, dy / norm))
    return out


# ---------------------------------------------------------------------------
# docking templates
# ---------------------------------------------------------------------------
class Dock:
    def __init__(self, radius=RADIUS):
        self.radius = radius

    def _points(self, primitives):
        points = []
        for item in primitives:
            if item[0] == 'line':
                points.extend(sample_line(item[1], item[2]))
            else:
                points.extend(item[5])
        return points

    def candidates(self, start, heading, heading_index, target_xy,
                   target_heading_index):
        """Return list of (primitives, sampled_points, final_heading_index)."""
        end = tuple(target_xy)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        forward = heading[0] * dx + heading[1] * dy
        left = (-heading[1], heading[0])
        lateral = left[0] * dx + left[1] * dy
        results = []
        diff = (target_heading_index - heading_index) % 4
        if diff == 0:
            if abs(lateral) <= 1e-6 and forward >= 0:
                prims = [('line', start, end)]
                results.append((prims, sample_line(start, end),
                                target_heading_index))
            elif forward >= 0 and abs(lateral) <= 2.0 * self.radius + 1e-9:
                angle = math.acos(max(-1.0, min(1.0,
                                                1.0 - abs(lateral)
                                                / (2.0 * self.radius))))
                direction = 1 if lateral >= 0 else -1
                s_forward = 2.0 * self.radius * math.sin(angle)
                if forward >= s_forward - 1e-9:
                    straight1 = forward - s_forward
                    p1 = (start[0] + heading[0] * straight1,
                          start[1] + heading[1] * straight1)
                    arc1 = sample_arc(p1, heading, direction, angle)
                    turned = (direction * left[0], direction * left[1])
                    arc2 = sample_arc(arc1[-1], turned, -direction, angle)
                    p3 = arc2[-1]
                    if math.hypot(p3[0] - end[0], p3[1] - end[1]) < 1e-6:
                        prims = ([('line', start, p1)]
                                 + ([('line', start, p1)] if straight1 > 0
                                    else [])
                                 + [('arc', p1, arc1[-1], direction, angle,
                                     arc1),
                                    ('arc', arc1[-1], p3, -direction, angle,
                                     arc2)])
                        results.append((prims, sample_line(start, p1) + arc1
                                        + arc2, target_heading_index))
        elif diff in (1, 3):
            direction = 1 if diff == 1 else -1
            normal = (direction * left[0], direction * left[1])
            # displacement = (L1+R)*h + (R+L2)*normal
            f = forward
            l = normal[0] * dx + normal[1] * dy
            if f >= self.radius - 1e-9 and l >= self.radius - 1e-9:
                l1 = f - self.radius
                l2 = l - self.radius
                p1 = (start[0] + heading[0] * l1, start[1] + heading[1] * l1)
                arc = sample_arc(p1, heading, direction)
                p2 = arc[-1]
                p3 = (p2[0] + normal[0] * l2, p2[1] + normal[1] * l2)
                prims = [('line', start, p1),
                         ('arc', p1, p2, direction, math.pi / 2.0, arc),
                         ('line', p2, p3)]
                results.append((prims, sample_line(start, p1) + arc
                                + sample_line(p2, p3),
                                (heading_index + (1 if direction > 0 else -1)) % 4))
        else:
            for direction in (1, -1):
                normal = (direction * left[0], direction * left[1])
                l = normal[0] * dx + normal[1] * dy
                f = forward
                m = l - 2.0 * self.radius
                if m < -1e-9:
                    continue
                l1 = max(0.0, f)
                l3 = max(0.0, -f)
                p1 = (start[0] + heading[0] * l1, start[1] + heading[1] * l1)
                arc1 = sample_arc(p1, heading, direction)
                p2 = arc1[-1]
                p3 = (p2[0] + normal[0] * m, p2[1] + normal[1] * m)
                turned = (direction * left[0], direction * left[1])
                arc2 = sample_arc(p3, turned, direction)
                p4 = arc2[-1]
                final_heading = (-heading[0], -heading[1])
                p5 = (p4[0] - heading[0] * l3, p4[1] - heading[1] * l3)
                if math.hypot(p5[0] - end[0], p5[1] - end[1]) > 1e-6:
                    continue
                prims = [('line', start, p1),
                         ('arc', p1, p2, direction, math.pi / 2.0, arc1),
                         ('line', p2, p3),
                         ('arc', p3, p4, direction, math.pi / 2.0, arc2),
                         ('line', p4, p5)]
                results.append((prims, sample_line(start, p1) + arc1
                                + sample_line(p2, p3) + arc2
                                + sample_line(p4, p5),
                                (heading_index + 2) % 4))
        return results


# ---------------------------------------------------------------------------
# A* search
# ---------------------------------------------------------------------------
class NativeSearch:
    def __init__(self, obstacle_cloud, layer_heights, interface_z=INTERFACE_Z,
                 pitch=PITCH):
        self.obstacles = obstacle_cloud
        self.pitch = float(pitch)
        self.layers = {1: float(interface_z)}
        for layer_id, z in layer_heights.items():
            self.layers[int(layer_id)] = float(z)
        self.layer_ids = sorted(self.layers)
        self.headings = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        self.dock = Dock()

    def _cell(self, xy):
        return (round(xy[0] / self.pitch), round(xy[1] / self.pitch))

    def _xy(self, cell):
        return (cell[0] * self.pitch, cell[1] * self.pitch)

    def _inside(self, xy):
        return 0.0 <= xy[0] <= BOARD and 0.0 <= xy[1] <= BOARD

    # -- actions -----------------------------------------------------------
    def straight(self, pos, heading, length, z):
        end = (pos[0] + heading[0] * length, pos[1] + heading[1] * length)
        if not self._inside(end):
            return None
        sampled = sample_line_dir(pos, end)
        points = [(x, y, z) for x, y, _dx, _dy in sampled]
        if not self.obstacles.clear(points, [(dx, dy) for _x, _y, dx, dy
                                             in sampled]):
            return None
        return end, length

    def turn(self, pos, heading_index, direction, z):
        heading = self.headings[heading_index]
        left = (-heading[1], heading[0])
        new_heading = (direction * left[0], direction * left[1])
        new_heading_index = self.headings.index(new_heading)
        end = (pos[0] + RADIUS * (heading[0] + new_heading[0]),
               pos[1] + RADIUS * (heading[1] + new_heading[1]))
        if not self._inside(end):
            return None
        sampled = sample_arc_dir(pos, heading, direction)
        points = [(x, y, z) for x, y, _dx, _dy in sampled]
        if not self.obstacles.clear(points, [(dx, dy) for _x, _y, dx, dy
                                             in sampled]):
            return None
        return end, new_heading_index, math.pi * RADIUS / 2.0

    def transition(self, pos, heading_index, target_layer):
        heading = self.headings[heading_index]
        z0 = self.layers[1]
        z1 = self.layers[int(target_layer)]
        footprint, _theta = transition_footprint(z1 - z0)
        end = (pos[0] + heading[0] * footprint,
               pos[1] + heading[1] * footprint)
        if not self._inside(end):
            return None
        sampled = sample_transition_dir(pos, heading, z0, z1)
        points = [(x, y, z) for x, y, z, _dx, _dy in sampled]
        if not self.obstacles.clear(points, [(dx, dy) for _x, _y, _z, dx, dy
                                             in sampled]):
            return None
        return end, footprint + 8.0 + 2.0 * abs(z1 - z0)

    # -- heuristic ---------------------------------------------------------
    def heuristic(self, pos, layer, target_xy):
        manhattan = abs(pos[0] - target_xy[0]) + abs(pos[1] - target_xy[1])
        layer_penalty = 40.0 if int(layer) != 1 else 0.0
        return manhattan + layer_penalty

    # -- goal test ---------------------------------------------------------
    def find_dock(self, pos, heading_index, target_xy, target_heading_index):
        for primitives, points, final_heading in self.dock.candidates(
                pos, self.headings[heading_index], heading_index,
                target_xy, target_heading_index):
            all_points = [(x, y, self.layers[1]) for x, y in points]
            dirs = []
            for index in range(len(points)):
                if index + 1 < len(points):
                    dx = points[index + 1][0] - points[index][0]
                    dy = points[index + 1][1] - points[index][1]
                else:
                    dx = points[index][0] - points[index - 1][0]
                    dy = points[index][1] - points[index - 1][1]
                norm = math.hypot(dx, dy) or 1.0
                dirs.append((dx / norm, dy / norm))
            if all(self._inside(point) for point in points):
                if self.obstacles.clear(all_points, dirs):
                    return dict(primitives=primitives,
                                final_heading=final_heading)
        return None

    # -- main search -------------------------------------------------------
    def search(self, start_xy, start_heading, target_xy, target_heading,
               expansions_limit=200000, time_limit=30.0):
        started = time.perf_counter()
        try:
            start_heading_index = self.headings.index(
                (int(round(start_heading[0])), int(round(start_heading[1]))))
            target_heading_index = self.headings.index(
                (int(round(target_heading[0])), int(round(target_heading[1]))))
        except ValueError:
            return dict(found=False, reason='heading_not_axis_aligned',
                        expansions=0, seconds=0.0)
        immediate = self.find_dock(tuple(start_xy), start_heading_index,
                                   tuple(target_xy), target_heading_index)
        if immediate is not None:
            return dict(found=True, primitives=immediate['primitives'],
                        corridor=[], expansions=0, layers_used=[1],
                        seconds=round(time.perf_counter() - started, 2))

        def key_of(pos, heading_index, layer):
            return (round(pos[0] / 0.625), round(pos[1] / 0.625),
                    int(heading_index), int(layer))

        start_pos = tuple(float(v) for v in start_xy)
        start_state = key_of(start_pos, start_heading_index, 1)
        frontier = []
        counter = 0
        best = {start_state: 0.0}
        parent = {start_state: None}
        actions = {start_state: []}
        h0 = self.heuristic(start_pos, 1, target_xy)
        heapq.heappush(frontier, (h0, counter, 0.0, start_state, start_pos,
                                  start_heading_index, 1))
        expansions = 0
        straight_options = (1.25, 2.5, 5.0, 10.0, 20.0, 40.0)
        while frontier and expansions < expansions_limit:
            if time.perf_counter() - started > time_limit:
                break
            _f, _c, cost, state, pos, heading_index, layer = heapq.heappop(
                frontier)
            if cost > best.get(state, float('inf')) + 1e-9:
                continue
            expansions += 1
            dock = self.find_dock(pos, heading_index, tuple(target_xy),
                                  target_heading_index)
            if dock is not None:
                corridor = []
                node = state
                while node is not None:
                    corridor.append(node)
                    node = parent.get(node)
                corridor.reverse()
                path = []
                node = state
                while parent.get(node) is not None:
                    path = list(actions.get(node) or []) + path
                    node = parent.get(node)
                path = path + list(dock['primitives'])
                layers_used = sorted({int(item[2]) for item in corridor})
                transitions = sum(1 for item in path
                                  if item[0] == 'transition')
                return dict(found=True, primitives=path,
                            corridor=[list(item) for item in corridor],
                            expansions=expansions,
                            layers_used=layers_used,
                            transitions=transitions,
                            seconds=round(time.perf_counter() - started, 2))
            heading = self.headings[heading_index]
            z_now = self.layers[int(layer)]
            moves = []
            for length in straight_options:
                straight = self.straight(pos, heading, length, z_now)
                if straight is not None:
                    moves.append((straight[0], heading_index, int(layer),
                                  straight[1],
                                  [('line', pos, straight[0])]))
            for direction in (1, -1):
                turn = self.turn(pos, heading_index, direction, z_now)
                if turn is not None:
                    moves.append((turn[0], turn[1], int(layer), turn[2],
                                  [('arc', pos, turn[0], direction,
                                    math.pi / 2.0,
                                    sample_arc(pos, heading, direction))]))
            for target_layer in self.layer_ids:
                if int(target_layer) != int(layer):
                    transition = self.transition(pos, heading_index,
                                                 target_layer)
                    if transition is not None:
                        moves.append((transition[0], heading_index,
                                      int(target_layer), transition[1],
                                      [('transition', pos, transition[0],
                                        float(self.layers[int(layer)]),
                                        float(self.layers[int(target_layer)]))]))
            for new_pos, new_heading, new_layer, move_cost, primitives in moves:
                new_state = key_of(new_pos, new_heading, new_layer)
                new_cost = cost + move_cost
                if new_cost >= best.get(new_state, float('inf')) - 1e-9:
                    continue
                best[new_state] = new_cost
                parent[new_state] = state
                actions[new_state] = list(actions.get(state) or []) + list(primitives)
                counter += 1
                h = self.heuristic(new_pos, new_layer, target_xy)
                heapq.heappush(frontier, (new_cost + h, counter, new_cost,
                                          new_state, new_pos, new_heading,
                                          new_layer))
        return dict(found=False, expansions=expansions,
                    seconds=round(time.perf_counter() - started, 2))


def build_obstacles(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    return ObstacleCloud(payload), payload
