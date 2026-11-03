"""V4-C4 crossing-avoidance 3D lift experiment.

Keep the accepted V4 1020/1024 XY routes (ports, connections, 2D primitives)
completely unchanged and reduce same-height crossings by raising selected C4
groups to L2-L5:

``straight -> early climb -> high-layer flat (through the crossing region) ->
descent -> original height``

Hard rules implemented here:

* transitions (R15 S-curves) may only start inside a *straight* segment of the
  original 2D path (``fsd25d.path3d.straight_intervals``); an arc can never be
  split by a transition - the whole arc stays on one constant Z;
* if a crossing lies on an arc, the climb is placed on an earlier straight and
  the arc is crossed at the high layer;
* nearby crossings are merged into one high-layer interval (one climb + one
  descent per route), never repeated up/down;
* a C4 group is only modified as a whole: one representative lift is searched,
  the other three members are exact 90/180/270 deg rotations with identical Z,
  all four are checked jointly in the true-XYZ world and committed atomically;
* no new same-height crossing is introduced: a plan is accepted only when the
  number of same-height crossing pairs strictly decreases and the plan creates
  zero new same-layer crossing pairs.

The crossing measurement uses the frozen ``fslw.validate_fslw`` pair audit on
every physical Z plane (L1 has two planes z=0 and z=0.5; L2-L5 one each).
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from .profile import apply as apply_profile

OUT_ROOT_NAME = 'outputs/four_side_1024_v4_c4_crossing_lift'
RADIUS_MM = 15.0
PORT_MARGIN_MM = 1.2
SEGMENT_MARGIN_MM = 0.25
MIN_TRAVEL_MM = 5.0
CROSSING_EXCLUSION_MARGIN_MM = 0.2


def safe_transition_length(clearance=0.08, extra=0.03, radius=RADIUS_MM):
    """Horizontal length of the S-curve until its height exceeds the
    clearance (plus a small extra), derived from the actual S geometry:
    dz(u) = R*(1-cos(asin(u/R))) = u^2/(2R) until u = R."""
    reach = float(clearance) + float(extra)
    return math.sqrt(max(0.0, 2.0 * float(radius) * reach - reach * reach))

MAX_PLANS_PER_GROUP = 24
LAYER_IDS = (2, 3, 4, 5)
LAYER_COLORS = {0.0: '#1f6fd6', 0.5: '#e07b1a', 1.0: '#2f9e44',
                1.5: '#7048e8', 2.0: '#e03131', 2.5: '#0c8599'}


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_json(path, payload, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent),
                    encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def _paths():
    from ..fsd25d import path3d as P
    return P


def _prim_length(primitive):
    return _paths().prim_length(primitive)


def position_on_route(primitives, point):
    """Arc-length position (mm) of the closest point of ``point`` on the chain."""
    best_distance = float('inf')
    best_s = 0.0
    offset = 0.0
    px, py = float(point[0]), float(point[1])
    for primitive in primitives:
        length = _prim_length(primitive)
        if primitive['kind'] == 'line':
            x0, y0 = primitive['p0']
            x1, y1 = primitive['p1']
            dx, dy = x1 - x0, y1 - y0
            denominator = dx * dx + dy * dy
            t = 0.0 if denominator <= 1e-18 else (
                (px - x0) * dx + (py - y0) * dy) / denominator
            t = max(0.0, min(1.0, t))
            cx, cy = x0 + t * dx, y0 + t * dy
            distance = math.hypot(px - cx, py - cy)
            if distance < best_distance:
                best_distance, best_s = distance, offset + t * length
        else:
            cx, cy = primitive['center']
            radius = float(primitive['radius'])
            start_angle = float(primitive['start_angle'])
            sweep = float(primitive['sweep'])
            angle = math.atan2(py - cy, px - cx)
            if sweep >= 0.0:
                delta = (angle - start_angle) % (2.0 * math.pi)
                inside = delta <= sweep + 1e-9
            else:
                delta = (start_angle - angle) % (2.0 * math.pi)
                inside = delta <= -sweep + 1e-9
            local = min(length, delta * radius) if inside else (
                0.0 if delta > abs(sweep) / 2.0 else length)
            point_angle = start_angle + math.copysign(local / radius, sweep)
            qx = cx + radius * math.cos(point_angle)
            qy = cy + radius * math.sin(point_angle)
            distance = math.hypot(px - qx, py - qy)
            if distance < best_distance:
                best_distance, best_s = distance, offset + local
        offset += length
    return best_s


def transition_geometry(dz, radius=RADIUS_MM):
    from ..fsd25d import path3d as P
    dz = abs(float(dz))
    theta = P.transition_theta(dz, radius)
    return dict(dz_mm=dz, theta_rad=float(theta),
                footprint_mm=2.0 * radius * math.sin(theta),
                length_mm=2.0 * radius * theta)


def _straight_start_windows(primitives, footprint, total):
    P = _paths()
    windows = []
    for start, end, _index in P.straight_intervals(primitives):
        lo = max(start + SEGMENT_MARGIN_MM, 0.0, PORT_MARGIN_MM)
        hi = min(end - SEGMENT_MARGIN_MM - footprint,
                 total - PORT_MARGIN_MM - footprint)
        if hi < lo - 1e-9:
            continue
        windows.append((lo, hi))
    return windows


def _inside_window(position, windows):
    return any(lo - 1e-9 <= position <= hi + 1e-9 for lo, hi in windows)


def row_z(row):
    return 0.0 if int(row) == 1 else 0.5


def _endpoint_xy(endpoint):
    from .inputs import ENDPOINTS
    return tuple(float(value) for value in ENDPOINTS[endpoint]['routing_xy'])


# ---------------------------------------------------------------------------
# flat / lifted route assembly
# ---------------------------------------------------------------------------
def flat_route(route_id, plane, primitives, row):
    from ..l3d.world import World
    return World.flat_route(route_id, plane, primitives,
                            row_z(row), layer_id=1, row=int(row))


def lift_route(record, row, layer_id, layer_z, rise_start, fall_start,
               primitives, radius=RADIUS_MM):
    """Assemble one SCHEMA_L3D route with an early climb and a late descent."""
    P = _paths()
    from ..l3d.paths import _subchain
    total = P.path_length(primitives)
    base_z = row_z(row)
    geometry = transition_geometry(float(layer_z) - base_z, radius)
    footprint = geometry['footprint_mm']
    if rise_start < PORT_MARGIN_MM - 1e-9:
        return None
    if rise_start + footprint > fall_start - MIN_TRAVEL_MM + 1e-9:
        return None
    if fall_start + footprint > total - PORT_MARGIN_MM + 1e-9:
        return None
    head = _subchain(primitives, 0.0, rise_start)
    travel = _subchain(primitives, rise_start + footprint, fall_start)
    tail = _subchain(primitives, fall_start + footprint, total)
    if not travel:
        return None
    parts = []
    head_length = P.path_length(head)
    if head_length > 1e-9:
        parts.append(dict(kind='flat', layer_id=1, z_mm=float(base_z),
                          length_mm=float(head_length), primitives=head))
    point, direction = P.path_point_at(primitives, rise_start)
    up = dict(P.make_transition(point, direction, float(base_z),
                                float(layer_z), radius))
    up['kind'] = 'transition'
    up['from_layer'] = 1
    up['to_layer'] = int(layer_id)
    parts.append(up)
    travel_length = P.path_length(travel)
    if travel_length > 1e-9:
        parts.append(dict(kind='flat', layer_id=int(layer_id),
                          z_mm=float(layer_z), length_mm=float(travel_length),
                          primitives=travel))
    point, direction = P.path_point_at(primitives, fall_start)
    down = dict(P.make_transition(point, direction, float(layer_z),
                                  float(base_z), radius))
    down['kind'] = 'transition'
    down['from_layer'] = int(layer_id)
    down['to_layer'] = 1
    parts.append(down)
    tail_length = P.path_length(tail)
    if tail_length > 1e-9:
        parts.append(dict(kind='flat', layer_id=1, z_mm=float(base_z),
                          length_mm=float(tail_length), primitives=tail))
    source_xy = _endpoint_xy(record['source_endpoint'])
    target_xy = _endpoint_xy(record['target_endpoint'])
    route = dict(
        route_id=int(record['route_id']), plane=record['plane'],
        source_row=int(row), target_row=int(row),
        source_port=dict(xy=[source_xy[0], source_xy[1]], z_mm=float(base_z),
                         layer_id=1),
        target_port=dict(xy=[target_xy[0], target_xy[1]], z_mm=float(base_z),
                         layer_id=1),
        start_z_mm=float(base_z), end_z_mm=float(base_z),
        layer_sequence=[1, int(layer_id), 1],
        layer_z_sequence=[float(base_z), float(layer_z), float(base_z)],
        n_transitions=2, lifted=True,
        layers_used=[1, int(layer_id)],
        xy_length_mm=float(total),
        length_mm=float(sum(part['length_mm'] for part in parts)),
        z_span_mm=abs(float(layer_z) - base_z),
        parts=parts)
    return route


def _high_flat_parts(route):
    return [part for part in route['parts']
            if part['kind'] == 'flat' and int(part['layer_id']) != 1]


def _high_chain(route):
    primitives = []
    for part in _high_flat_parts(route):
        primitives.extend(dict(primitive) for primitive in part['primitives'])
    return primitives


def _high_layer(route):
    parts = _high_flat_parts(route)
    return int(parts[0]['layer_id']) if parts else 1


def route_high_span_stored(member_route, record):
    """High-layer arc-length span in the *stored* member path coordinates."""
    high = _high_flat_parts(member_route)
    if not high:
        return None
    primitives = record['primitives']
    start_s = position_on_route(primitives, high[0]['primitives'][0]['p0'])
    end_s = position_on_route(primitives, high[-1]['primitives'][-1]['p1'])
    if start_s > end_s:
        start_s, end_s = end_s, start_s
    return (float(start_s), float(end_s))


def route_elevated_span_stored(member_route, record, safe):
    """Span where the route is either on the high layer or high enough
    (>= clearance) inside the climb/descent S-curves."""
    span = route_high_span_stored(member_route, record)
    if span is None:
        return None
    low = span[0] + float(safe)
    high = span[1] - float(safe)
    if high <= low:
        return (span[0], span[1])
    return (float(low), float(high))


def _free_zone(low, high, positions, margin=0.0):
    """True when no crossing position lies in ``[low-margin, high+margin]``."""
    low = low - margin
    high = high + margin
    index = bisect.bisect_right(positions, high)
    if index == 0:
        return True
    return positions[index - 1] < low


# ---------------------------------------------------------------------------
# crossing analysis
# ---------------------------------------------------------------------------
def analyze_planes(entries, log=print, compute_positions=False,
                   primitives_by_id=None):
    """Pair-audit every physical Z plane.

    ``entries``: dict ``z_mm -> [(route_id, primitives), ...]``.
    Returns ``(crossings, reports, pairs_by_plane)``; crossing tuples are
    ``(plane_key, a, b, x, y, s_a, s_b, angle_deg)``.
    """
    from ..fslw import validate_fslw as V
    crossings = []
    reports = {}
    pairs_by_plane = {}
    for z_mm, plane_entries in sorted(entries.items()):
        if not plane_entries:
            continue
        prepared = [(rid, V.prepare_route(prims, rid))
                    for rid, prims in plane_entries]
        prepared_only = [item[1] for item in prepared]
        report = V.audit_route_pairs(prepared_only, policy='strict')
        reports[z_mm] = dict(crossing_pair_count=report['crossing_pair_count'],
                             crossing_count=report['crossing_count'],
                             candidate_pair_count=report['candidate_pair_count'])
        pairs = set()
        for item in report['crossings']:
            a, b = int(item['route_a']), int(item['route_b'])
            pairs.add((min(a, b), max(a, b)))
            point = (float(item['x']), float(item['y']))
            if compute_positions:
                prims_map = primitives_by_id or dict(plane_entries)
                s_a = position_on_route(prims_map[a], point)
                s_b = position_on_route(prims_map[b], point)
            else:
                s_a = s_b = None
            crossings.append((float(z_mm), a, b, point[0], point[1],
                              s_a, s_b, float(item['angle_deg'])))
        pairs_by_plane[z_mm] = pairs
    return crossings, reports, pairs_by_plane


def count_pair_crossings(primitives_a, primitives_b):
    from ..fslw import validate_fslw as V
    if not primitives_a or not primitives_b:
        return 0
    first = V.prepare_route(primitives_a, 0).prims
    second = V.prepare_route(primitives_b, 1).prims
    count = 0
    for one in first:
        for other in second:
            if V._prims_intersect(one, other):
                count += 1
    return count


# ---------------------------------------------------------------------------
# planner / optimizer
# ---------------------------------------------------------------------------
class CrossingLifter:
    def __init__(self, v4_root=None, out_dir=None, log=print,
                 stack_name=None, heights=None, clearance=0.08):
        apply_profile()
        from ..l3d import layers as LL
        from ..l3d.world import World
        from . import l3d as L3
        from . import inputs as V3

        self.log = log
        self.clearance = float(clearance)
        self.L3 = L3
        self.V3 = V3
        default_v4 = Path(__file__).resolve().parents[2] / \
            'outputs/four_side_1024_v4_c4_routing'
        self.v4_root = Path(v4_root or default_v4)
        self.out_dir = Path(out_dir or (Path(__file__).resolve().parents[2]
                                        / OUT_ROOT_NAME))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        payload = _read_json(self.v4_root / 'routes_1024.json')
        self.records = {int(record['route_id']): record
                        for record in payload['routes']}
        self.groups = payload['rotation_groups']
        self.group_by_id = {int(group['group_id']): group
                            for group in self.groups}
        self.routed = {rid: record for rid, record in self.records.items()
                       if record.get('status') == 'routed'}
        self.failed = {rid: record for rid, record in self.records.items()
                       if record.get('status') != 'routed'}
        self.route_group = {}
        for group in self.groups:
            for phase, rid in enumerate(group['route_ids']):
                self.route_group[int(rid)] = (int(group['group_id']), phase)
        if heights is not None:
            layer_heights = {int(index) + 2: float(value)
                             for index, value in enumerate(heights)}
            self.stack = LL.build_stack('ablation_custom',
                                        heights=layer_heights)
        else:
            self.stack = LL.build_stack(stack_name or 'medium_050')
        self.safe_length = safe_transition_length(self.clearance)
        self.transition_margin = self.clearance + 0.25
        self.world = World(self.stack, clearance=self.clearance)
        self.base_routes = {}
        self.primitives = {}
        self.row = {}
        for rid, record in sorted(self.routed.items()):
            row = 1 if record['plane'] == 'z1' else 2
            self.row[rid] = row
            self.primitives[rid] = [dict(primitive)
                                    for primitive in record['primitives']]
            route = flat_route(rid, record['plane'], self.primitives[rid], row)
            self.base_routes[rid] = route
            self.world.add_route(route)
        self.lifted = {}
        self.group_plans = {}
        self.crossings = []
        self.crossing_z = {}
        self.pair_set = set()
        self.high_pairs = set()
        self.initial_pair_count = 0
        self.initial_crossing_count = 0
        self.before_reports = {}
        self.before_pairs_by_plane = {}
        self.route_priority = Counter()
        self.group_crossing_priority = {}

    # -- initial analysis --------------------------------------------------
    def _finalize_analysis(self):
        priority = Counter()
        for _z, a, b, *_rest in self.crossings:
            priority[a] += 1
            priority[b] += 1
        self.route_priority = priority
        for group in self.groups:
            ids = [int(rid) for rid in group['route_ids']]
            if any(rid not in self.routed for rid in ids):
                continue
            score = sum(priority[rid] for rid in ids)
            if score:
                self.group_crossing_priority[int(group['group_id'])] = score
        self.log(f'[lift] before: pairs={self.initial_pair_count} '
                 f'points={self.initial_crossing_count} '
                 f'per-plane={ {k: v["crossing_pair_count"] for k, v in self.before_reports.items()} }')

    def analyze(self, cache_path=None):
        if cache_path and Path(cache_path).exists():
            cached = _read_json(cache_path)
            self.crossings = [tuple(item) for item in cached['crossings']]
            self.initial_crossings = list(self.crossings)
            self.before_reports = {float(key): value
                                   for key, value in cached['reports'].items()}
            self.before_pairs_by_plane = {
                float(key): {(int(pair[0]), int(pair[1])) for pair in pairs}
                for key, pairs in cached['pairs'].items()}
            self.pair_set = set()
            for plane_pairs in self.before_pairs_by_plane.values():
                self.pair_set |= plane_pairs
            self.initial_pair_count = len(self.pair_set)
            self.initial_crossing_count = len(self.crossings)
            self.log(f'[lift] loaded crossing cache {cache_path} '
                     f'({self.initial_pair_count} pairs)')
            self._finalize_analysis()
            return
        entries = defaultdict(list)
        for rid, primitives in self.primitives.items():
            entries[row_z(self.row[rid])].append((rid, primitives))
        crossings, reports, pairs = analyze_planes(
            entries, log=self.log, compute_positions=True,
            primitives_by_id=self.primitives)
        self.crossings = crossings
        self.initial_crossings = list(crossings)
        self.before_reports = reports
        self.before_pairs_by_plane = pairs
        self.pair_set = set()
        for plane_pairs in pairs.values():
            self.pair_set |= plane_pairs
        self.initial_pair_count = len(self.pair_set)
        self.initial_crossing_count = len(self.crossings)
        if cache_path:
            _write_json(cache_path, dict(
                crossings=[list(item) for item in self.crossings],
                reports={str(key): value for key, value in self.before_reports.items()},
                pairs={str(key): sorted([list(pair) for pair in pairs])
                       for key, pairs in self.before_pairs_by_plane.items()}),
                indent=None)
            self.log(f'[lift] crossing cache written {cache_path}')
        self._finalize_analysis()

    def _crossings_involving(self, route_ids):
        ids = set(int(rid) for rid in route_ids)
        return [entry for entry in self.crossings
                if entry[1] in ids or entry[2] in ids]

    def _current_priority(self):
        priority = Counter()
        for _z, a, b, *_rest in self.crossings:
            priority[a] += 1
            priority[b] += 1
        return priority

    # -- true-3D transition clearance pre-check -----------------------------
    def _refresh_plane_cache(self):
        from ..fslw import validate_fslw as V
        cache = {}
        for z_mm, parts in self.world.planes.parts.items():
            entries = []
            for part_id, primitives in parts.items():
                prepared = V.prepare_route(primitives, part_id).prims
                min_x = min(p.bbox[0] for p in prepared)
                min_y = min(p.bbox[1] for p in prepared)
                max_x = max(p.bbox[2] for p in prepared)
                max_y = max(p.bbox[3] for p in prepared)
                entries.append((part_id, prepared, (min_x, min_y, max_x, max_y)))
            cache[round(float(z_mm), 9)] = entries
        self._plane_cache = cache

    @staticmethod
    def _point_primitive_distance(px, py, prim):
        if prim.kind == 'line':
            x0, y0 = prim.p0
            x1, y1 = prim.p1
            dx, dy = x1 - x0, y1 - y0
            denominator = dx * dx + dy * dy
            t = 0.0 if denominator <= 1e-18 else (
                (px - x0) * dx + (py - y0) * dy) / denominator
            t = max(0.0, min(1.0, t))
            return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        cx, cy = prim.center
        radius = float(prim.radius)
        start_angle = float(prim.start)
        sweep = float(prim.sweep)
        angle = math.atan2(py - cy, px - cx)
        if sweep >= 0.0:
            delta = (angle - start_angle) % (2.0 * math.pi)
            inside = delta <= sweep + 1e-12
        else:
            delta = (start_angle - angle) % (2.0 * math.pi)
            inside = delta <= -sweep + 1e-12
        if inside:
            point_angle = start_angle + math.copysign(delta, sweep)
        else:
            d0 = abs((angle - start_angle + math.pi) % (2.0 * math.pi) - math.pi)
            d1 = abs((angle - (start_angle + sweep) + math.pi)
                     % (2.0 * math.pi) - math.pi)
            point_angle = start_angle if d0 <= d1 else start_angle + sweep
        qx = cx + radius * math.cos(point_angle)
        qy = cy + radius * math.sin(point_angle)
        return math.hypot(px - qx, py - qy)

    def _plane_min_distance(self, point, z_plane, threshold=None):
        cache = getattr(self, '_plane_cache', None)
        if cache is None:
            self._refresh_plane_cache()
            cache = self._plane_cache
        entries = cache.get(round(float(z_plane), 9)) or []
        px, py = float(point[0]), float(point[1])
        best = float('inf')
        limit = float(threshold) if threshold is not None else float('inf')
        for _part_id, prepared, bbox in entries:
            if px < bbox[0] - 0.6 or px > bbox[2] + 0.6:
                continue
            if py < bbox[1] - 0.6 or py > bbox[3] + 0.6:
                continue
            for prim in prepared:
                distance = self._point_primitive_distance(px, py, prim)
                if distance < best:
                    best = distance
                    if best <= limit:
                        return best
        return best

    @staticmethod
    def _transition_z_at(u, z0, z1, radius, footprint):
        sign = 1.0 if z1 >= z0 else -1.0
        half = footprint / 2.0
        if u <= half:
            phi = math.asin(max(-1.0, min(1.0, u / radius)))
            return z0 + sign * radius * (1.0 - math.cos(phi))
        u2 = footprint - u
        phi = math.asin(max(-1.0, min(1.0, u2 / radius)))
        return z1 - sign * radius * (1.0 - math.cos(phi))

    def _transition_u_for_z(self, z_target, z0, z1, radius, footprint):
        low, high = 0.0, float(footprint)
        for _ in range(40):
            mid = (low + high) / 2.0
            value = self._transition_z_at(mid, z0, z1, radius, footprint)
            if (z1 - z0) >= 0:
                below = value < z_target
            else:
                below = value > z_target
            if below:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0

    def _transition_clearance_ok(self, point, direction, z0, z1, footprint,
                                 radius=RADIUS_MM, margin=None):
        if margin is None:
            margin = self.transition_margin
        z_low, z_high = sorted((float(z0), float(z1)))
        crossed = [z for z in (getattr(self, '_plane_cache', None) or {})
                   if z_low + 1e-9 < z < z_high - 1e-9]
        for z_plane in crossed:
            u = self._transition_u_for_z(z_plane, z0, z1, radius, footprint)
            px = float(point[0]) + float(direction[0]) * u
            py = float(point[1]) + float(direction[1]) * u
            if self._plane_min_distance((px, py), z_plane, margin) < margin:
                return False
        return True

    # -- candidates --------------------------------------------------------
    def plan_candidates(self, rep_id, max_plans=MAX_PLANS_PER_GROUP):
        record = self.routed[rep_id]
        primitives = record['primitives']
        total = _paths().path_length(primitives)
        inputs = self._crossings_involving([rep_id])
        positions = sorted(_position_of(entry, rep_id) for entry in inputs)
        row = self.row[rep_id]
        base_z = row_z(row)
        plans = []
        for layer_id in LAYER_IDS:
            layer_z = float(self.stack.z_for_layer(layer_id))
            geometry = transition_geometry(layer_z - base_z)
            footprint = geometry['footprint_mm']
            windows = _straight_start_windows(primitives, footprint, total)
            if not windows:
                continue
            margin = CROSSING_EXCLUSION_MARGIN_MM
            candidate_starts = set()

            def _add(value, low, high):
                if low - 1e-9 <= value <= high + 1e-9:
                    candidate_starts.add(round(float(value), 6))

            for lo, hi in windows:
                span = hi - lo
                for fraction in (0.0, 0.5, 1.0):
                    _add(lo + span * fraction, lo, hi)
            for position in positions:
                for low, high in windows:
                    _add(position - footprint - margin, low, high)
                    _add(position + margin, low, high)
            ordered = sorted(candidate_starts)
            safe = self.safe_length

            def _free_rise(start):
                return _free_zone(start, start + safe, positions, margin)

            def _free_fall(start):
                return _free_zone(start + footprint - safe,
                                  start + footprint, positions, margin)

            rise_valid = [start for start in ordered
                          if _inside_window(start, windows) and _free_rise(start)]
            fall_valid = [start for start in ordered
                          if _inside_window(start, windows)
                          and start + footprint <= total - PORT_MARGIN_MM + 1e-9
                          and _free_fall(start)]

            def _cap(values, limit=60):
                if len(values) <= limit:
                    return values
                stride = max(1, len(values) // limit)
                return values[::stride][:limit]

            rise_valid = _cap(rise_valid)
            fall_valid = _cap(fall_valid)
            for rise_start in rise_valid:
                rise_end = rise_start + footprint
                for fall_start in fall_valid:
                    if fall_start < rise_end + MIN_TRAVEL_MM:
                        continue
                    low = rise_start + safe + margin
                    high = fall_start + footprint - safe - margin
                    if high <= low:
                        continue
                    removed = bisect.bisect_left(positions, high) - \
                        bisect.bisect_right(positions, low)
                    if removed <= 0:
                        continue
                    plans.append(dict(
                        layer_id=int(layer_id), layer_z=float(layer_z),
                        dz=float(layer_z - base_z), footprint=float(footprint),
                        rise_start=float(rise_start), fall_start=float(fall_start),
                        removed_crossings=int(removed)))
        plans.sort(key=lambda item: (-item['removed_crossings'], item['layer_id'],
                                     item['rise_start']))
        self._refresh_plane_cache()
        P = _paths()
        accepted = []
        checked = 0
        for plan in plans:
            if plan['removed_crossings'] <= 0:
                continue
            checked += 1
            if checked > 4000:
                break
            rise_point, rise_dir = P.path_point_at(primitives, plan['rise_start'])
            fall_point, fall_dir = P.path_point_at(primitives, plan['fall_start'])
            if not self._transition_clearance_ok(
                    rise_point, rise_dir, base_z, plan['layer_z'],
                    plan['footprint']):
                continue
            if not self._transition_clearance_ok(
                    fall_point, fall_dir, plan['layer_z'], base_z,
                    plan['footprint']):
                continue
            accepted.append(plan)
            if len(accepted) >= max_plans * 4:
                break
        chosen = []
        seen = set()
        per_layer = Counter()
        limit = max(2, max_plans // max(1, len(LAYER_IDS)))

        def _remember(plan):
            key = (plan['layer_id'], round(plan['rise_start'], 4),
                   round(plan['fall_start'], 4))
            if key in seen or len(chosen) >= max_plans:
                return
            seen.add(key)
            chosen.append(plan)

        for plan in accepted:
            if per_layer[plan['layer_id']] >= limit:
                continue
            per_layer[plan['layer_id']] += 1
            _remember(plan)
            if len(chosen) >= max_plans:
                break
        for layer_id in LAYER_IDS:
            layer_plans = [plan for plan in accepted
                           if plan['layer_id'] == layer_id]
            layer_plans.sort(key=lambda plan: (plan['fall_start']
                                               + plan['footprint']
                                               - plan['rise_start']))
            for plan in layer_plans[:3]:
                _remember(plan)
                if len(chosen) >= max_plans:
                    break
        return chosen

    def build_group_routes(self, group, plan):
        ids = [int(rid) for rid in group['route_ids']]
        rep_id = ids[0]
        record = self.routed[rep_id]
        row = self.row[rep_id]
        rep_route = lift_route(record, row, plan['layer_id'], plan['layer_z'],
                               plan['rise_start'], plan['fall_start'],
                               record['primitives'])
        if rep_route is None:
            return None
        routes = {rep_id: rep_route}
        for phase, rid in enumerate(ids[1:], start=1):
            member = self.routed[rid]
            from types import SimpleNamespace
            frame = SimpleNamespace(
                src_xy=_endpoint_xy(member['source_endpoint']),
                dst_xy=_endpoint_xy(member['target_endpoint']))
            try:
                member_route = self.L3.rotate_to_member(rep_route, phase, frame)
            except ValueError:
                return None
            member_row = self.row[rid]
            source_xy = _endpoint_xy(member['source_endpoint'])
            target_xy = _endpoint_xy(member['target_endpoint'])
            member_route['source_port'] = dict(
                xy=[source_xy[0], source_xy[1]], z_mm=row_z(member_row),
                layer_id=1)
            member_route['target_port'] = dict(
                xy=[target_xy[0], target_xy[1]], z_mm=row_z(member_row),
                layer_id=1)
            routes[rid] = member_route
        return routes

    def _added_pairs(self, routes):
        """New same-layer crossing pairs among the candidate group / old lifted."""
        pairs = set()
        by_layer = defaultdict(list)
        chains = {}
        for rid, route in routes.items():
            layer = _high_layer(route)
            chains[rid] = _high_chain(route)
            by_layer[layer].append(rid)
        for rid, route in self.lifted.items():
            layer = _high_layer(route)
            chains[rid] = _high_chain(route)
            by_layer[layer].append(rid)
        for _layer, ids in by_layer.items():
            for index, first in enumerate(ids):
                for second in ids[index + 1:]:
                    if count_pair_crossings(chains[first], chains[second]):
                        pairs.add((min(first, second), max(first, second)))
        return pairs

    def _drop_base_routes(self, ids):
        plan = {int(rid): route for rid, route in self.world.plan.items()
                if int(rid) not in set(int(value) for value in ids)}
        self.world.rebuild(plan)

    def _restore_base_routes(self, ids):
        for rid in ids:
            self.world.add_route(self.base_routes[int(rid)])

    # -- one group attempt -------------------------------------------------
    def try_group(self, group, log=None):
        log = log or self.log
        ids = [int(rid) for rid in group['route_ids']]
        plans = self.plan_candidates(ids[0])
        self.last_reject = None
        if not plans:
            self.last_reject = 'no_transition_window'
            return None
        current_pair_count = len(self.pair_set)
        self._drop_base_routes(ids)
        candidates = []
        for plan in plans:
            routes = self.build_group_routes(group, plan)
            if routes is None:
                self.last_reject = 'rotation_failed'
                continue
            high_spans = {}
            ok = True
            for rid in ids:
                span = route_elevated_span_stored(routes[rid],
                                                  self.routed[rid],
                                                  self.safe_length)
                if span is None:
                    ok = False
                    break
                high_spans[rid] = [span]
            if not ok:
                self.last_reject = 'no_high_span'
                continue
            kept = []
            removed_points = 0
            for entry in self.crossings:
                _z, a, b, _x, _y, s_a, s_b = entry[:7]
                if a not in ids and b not in ids:
                    kept.append(entry)
                    continue

                def elevated(rid, s):
                    if rid not in ids:
                        return False
                    return any(low < s < high for low, high in high_spans[rid])

                high_a = elevated(a, s_a)
                high_b = elevated(b, s_b)
                if a in ids and b in ids:
                    if high_a and high_b:
                        kept.append(entry)
                        continue
                    if high_a or high_b:
                        removed_points += 1
                        continue
                    kept.append(entry)
                    continue
                if high_a or high_b:
                    removed_points += 1
                    continue
                kept.append(entry)
            remaining_pairs = {(min(entry[1], entry[2]), max(entry[1], entry[2]))
                               for entry in kept}
            added_all = self._added_pairs(routes)
            added_new = added_all - remaining_pairs - self.high_pairs
            new_pair_count = len(remaining_pairs | added_all | self.high_pairs)
            if new_pair_count >= current_pair_count:
                self.last_reject = 'no_pair_reduction'
                continue
            candidates.append(dict(
                plan=plan, routes=routes, high_spans=high_spans,
                kept=kept, remaining_pairs=remaining_pairs,
                added_all=added_all, added_new=added_new,
                new_pair_count=new_pair_count,
                removed_points=removed_points))
        candidates.sort(key=lambda item: (len(item['added_new']),
                                          -item['removed_points']))
        for candidate in candidates:
            routes = candidate['routes']
            added_routes = []
            world_ok = True
            violations = []
            for rid in ids:
                found = self.world.check_route(routes[rid], check_self=True)
                if found:
                    world_ok = False
                    violations = found[:2]
                    break
                self.world.add_route(routes[rid])
                added_routes.append(rid)
            if not world_ok:
                for rid in reversed(added_routes):
                    self.world.remove_route(rid)
                self.last_reject = 'true_3d_clearance'
                continue
            former_pairs = {(min(entry[1], entry[2]), max(entry[1], entry[2]))
                            for entry in self.crossings}
            self.crossings = candidate['kept']
            self.high_pairs |= candidate['added_all']
            self.pair_set = candidate['remaining_pairs'] | self.high_pairs
            for rid in ids:
                self.lifted[rid] = routes[rid]
            plan = candidate['plan']
            info = dict(
                group_id=int(group['group_id']), kind=group['kind'],
                plane=self.routed[ids[0]]['plane'], route_ids=ids,
                layer_id=int(plan['layer_id']), layer_z_mm=float(plan['layer_z']),
                rise_start_mm=float(plan['rise_start']),
                fall_start_mm=float(plan['fall_start']),
                footprint_mm=float(plan['footprint']),
                removed_crossing_points=int(candidate['removed_points']),
                removed_crossing_pairs=int(len(former_pairs)
                                           - len(candidate['remaining_pairs'])),
                added_crossing_pairs=int(len(candidate['added_new'])),
                added_crossing_pairs_total=int(len(candidate['added_all'])),
                pair_count_after=int(candidate['new_pair_count']),
                high_spans_mm={str(rid): [[round(low, 4), round(high, 4)]
                                          for low, high in spans]
                               for rid, spans in candidate['high_spans'].items()},
                length_delta_mm=float(sum(routes[rid]['length_mm'] for rid in ids)
                                      - sum(self.base_routes[rid]['length_mm']
                                            for rid in ids)))
            return info
        self._restore_base_routes(ids)
        return None

    # -- loop --------------------------------------------------------------
    def optimize(self, max_groups=40, time_limit=1800.0, log=None):
        log = log or self.log
        started = time.perf_counter()
        history = []
        lifted_groups = 0
        while lifted_groups < max_groups and time.perf_counter() - started < time_limit:
            priority = self._current_priority()
            scored = []
            for gid, _initial in self.group_crossing_priority.items():
                if gid in self.group_plans:
                    continue
                group = self.group_by_id[gid]
                ids = [int(rid) for rid in group['route_ids']]
                if any(rid in self.lifted for rid in ids):
                    continue
                score = sum(priority.get(rid, 0) for rid in ids)
                if score > 0:
                    scored.append((score, gid))
            scored.sort(reverse=True)
            if not scored:
                break
            progress = False
            for _score, gid in scored[:15]:
                if time.perf_counter() - started > time_limit:
                    break
                group = self.group_by_id[gid]
                info = self.try_group(group, log=log)
                if info is None:
                    self.group_plans[gid] = dict(group_id=gid, status='rejected',
                                                 reason=getattr(
                                                     self, 'last_reject', None))
                    continue
                info['status'] = 'lifted'
                self.group_plans[gid] = info
                lifted_groups += 1
                progress = True
                history.append(dict(group_id=gid, layer_id=info['layer_id'],
                                    removed_pairs=info['removed_crossing_pairs'],
                                    pair_count_after=len(self.pair_set),
                                    length_delta_mm=round(
                                        info['length_delta_mm'], 4),
                                    seconds=round(time.perf_counter() - started, 2)))
                log(f'[lift] group {gid:3d} ({info["kind"]:8s}) -> L{info["layer_id"]} '
                    f'removed={info["removed_crossing_pairs"]} pairs '
                    f'now={len(self.pair_set)} '
                    f'len+{info["length_delta_mm"]:.1f}mm')
                _write_json(self.out_dir / 'checkpoints'
                            / f'step_{lifted_groups:02d}.json',
                            dict(history=history,
                                 group_plans=self._jsonable_plans(),
                                 pair_count=len(self.pair_set),
                                 lifted_routes=sorted(self.lifted)),
                            indent=1)
                break
            if not progress:
                break
        self.history = history
        return history

    def revert_groups(self, group_ids, log=print):
        """Remove the lifts of the given groups (restore their V4 flat routes)."""
        from ..l3d.world import World
        reverted = []
        for gid in group_ids:
            group = self.group_by_id[int(gid)]
            for rid in [int(value) for value in group['route_ids']]:
                if rid in self.lifted:
                    del self.lifted[rid]
                    reverted.append(rid)
            self.group_plans[int(gid)] = dict(group_id=int(gid),
                                              status='reverted')
        world = World(self.stack, clearance=self.clearance)
        for rid in sorted(self.routed):
            world.add_route(self.base_routes[rid])
        for rid in sorted(self.lifted):
            world.add_route(self.lifted[rid])
        self.world = world
        log(f'[lift] reverted groups {sorted(int(value) for value in group_ids)} '
            f'({len(reverted)} routes)')
        return reverted

    def _jsonable_plans(self):
        return {str(gid): plan for gid, plan in self.group_plans.items()}

    # -- final artefact helpers -------------------------------------------
    def final_flat_entries(self):
        """Physical-plane flat primitives of the CURRENT layout."""
        entries = defaultdict(list)
        for rid in self.routed:
            route = self.lifted.get(rid) or self.base_routes[rid]
            for part in route['parts']:
                if part['kind'] != 'flat':
                    continue
                entries[round(float(part['z_mm']), 9)].append(
                    (rid, [dict(primitive) for primitive in part['primitives']]))
        return entries

    def build_payload(self):
        records = []
        for rid in sorted(self.records):
            record = self.records[rid]
            if record.get('status') != 'routed':
                out = dict(record)
                out['reason'] = record.get('reason') or 'not_routed_v3'
                source_xy = _endpoint_xy(record['source_endpoint'])
                target_xy = _endpoint_xy(record['target_endpoint'])
                row = 1 if record['plane'] == 'z1' else 2
                out.setdefault('source_port',
                               dict(xy=[source_xy[0], source_xy[1]],
                                    z_mm=row_z(row), layer_id=1))
                out.setdefault('target_port',
                               dict(xy=[target_xy[0], target_xy[1]],
                                    z_mm=row_z(row), layer_id=1))
                out.setdefault('source_row', row)
                out.setdefault('target_row', row)
                records.append(out)
                continue
            route = self.lifted.get(rid) or self.base_routes[rid]
            out = dict(record)
            out.update(route)
            out['route_id'] = int(rid)
            out['status'] = 'routed'
            source_xy = _endpoint_xy(record['source_endpoint'])
            target_xy = _endpoint_xy(record['target_endpoint'])
            row = 1 if record['plane'] == 'z1' else 2
            out.setdefault('source_port', dict(xy=[source_xy[0], source_xy[1]],
                                               z_mm=row_z(row), layer_id=1))
            out.setdefault('target_port', dict(xy=[target_xy[0], target_xy[1]],
                                               z_mm=row_z(row), layer_id=1))
            out.setdefault('source_row', row)
            out.setdefault('target_row', row)
            records.append(out)
        payload = dict(
            schema='four_side_1024_v2_l3d_routes_v1',
            experiment='V4_C4_CROSSING_LIFT',
            note='XY paths/ports/connections unchanged; selected C4 groups lifted '
                 'to L2-L5 to remove same-height crossings',
            layer_stack=self.stack.to_dict(),
            routes=records)
        return payload

    def summary(self, validation=None, after_reports=None,
                after_pairs_by_plane=None):
        lifted_plans = [plan for plan in self.group_plans.values()
                        if plan.get('status') == 'lifted']
        transitions = 2 * len(self.lifted)
        length_before = sum(route['length_mm'] for route in self.base_routes.values())
        length_after = sum(self.lifted.get(rid, route)['length_mm']
                           for rid, route in self.base_routes.items())
        after_reports = after_reports or {}
        after_pair_total = sum(report['crossing_pair_count']
                               for report in after_reports.values())
        after_point_total = sum(report['crossing_count']
                                for report in after_reports.values())
        before_pair_by_plane = {str(key): value['crossing_pair_count']
                                for key, value in self.before_reports.items()}
        after_pair_by_plane = {str(key): value['crossing_pair_count']
                               for key, value in after_reports.items()}
        remaining_pairs = set()
        for plane_pairs in (after_pairs_by_plane or {}).values():
            remaining_pairs |= plane_pairs
        return dict(
            schema='four_side_1024_v4_c4_crossing_lift_summary_v1',
            routed_before=len(self.base_routes), routed_after=len(self.base_routes),
            total_records=len(self.records), failed=len(self.failed),
            crossing_pairs_before=int(self.initial_pair_count),
            crossing_points_before=int(self.initial_crossing_count),
            crossing_pairs_after=int(after_pair_total),
            crossing_points_after=int(after_point_total),
            crossing_pairs_before_by_plane=before_pair_by_plane,
            crossing_pairs_after_by_plane=after_pair_by_plane,
            crossing_pair_reduction=int(self.initial_pair_count - after_pair_total),
            lifted_groups=len(lifted_plans),
            lifted_routes=len(self.lifted),
            transitions=int(transitions),
            added_high_crossing_pairs_total=int(sum(
                int(plan.get('added_crossing_pairs', 0) or 0)
                for plan in lifted_plans)),
            high_layer_crossing_pairs=int(len(self.high_pairs)),
            length_total_before_mm=round(float(length_before), 4),
            length_total_after_mm=round(float(length_after), 4),
            length_delta_mm=round(float(length_after - length_before), 4),
            lifted_group_details=sorted(lifted_plans,
                                        key=lambda plan: plan['group_id']),
            rejected_groups=sum(1 for plan in self.group_plans.values()
                                if plan.get('status') == 'rejected'),
            radius_mm=RADIUS_MM,
            layer_heights_mm={str(layer): float(self.stack.z_for_layer(layer))
                              for layer in LAYER_IDS},
            remaining_crossing_pairs=sorted(
                [list(pair) for pair in remaining_pairs])[:50000],
            validation_status=(validation or {}).get('status'),
            validation_pass=bool(validation and (validation.get('passed')
                                                 or validation.get('exploratory_pass'))),
            timestamp=time.strftime('%Y-%m-%dT%H:%M:%S'))


def _position_of(entry, route_id):
    _z, a, b, _x, _y, s_a, s_b = entry[:7]
    return s_a if a == route_id else s_b


# ---------------------------------------------------------------------------
# V4 identity injection for the repository 3D validator
# ---------------------------------------------------------------------------
def validate_payload_v4(payload, v4_root, log=print):
    from ..l3d import validate_l3d as V
    from .inputs import ENDPOINTS

    records_payload = _read_json(Path(v4_root) / 'routes_1024.json')
    identity = {'available': True, 'error': None, 'planes': {}}
    for plane in ('z1', 'z2'):
        routes = {}
        for record in records_payload['routes']:
            rid = int(record['route_id'])
            if record.get('plane') != plane:
                continue
            routes[rid] = dict(
                route_id=rid,
                source_endpoint=record['source_endpoint'],
                target_endpoint=record['target_endpoint'],
                source_side=record['source_side'],
                target_side=record['target_side'],
                source_row=int(record['source_row']),
                target_row=int(record['target_row']),
                relation=record['relation'],
                pair=record['pair'])
        identity['planes'][plane] = {'routes': routes, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity
    log('[lift] running repository l3d validate_payload with V4-C4 identity')
    report = V.validate_payload(payload, allow_exploratory=True)
    log(f'[lift] 3D validator: status={report.get("status")} '
        f'exploratory_pass={report.get("exploratory_pass")} '
        f'geometry_pass={report.get("geometry_pass")} '
        f'counts={report.get("counts")}')
    return report
