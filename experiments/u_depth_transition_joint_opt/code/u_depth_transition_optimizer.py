# -*- coding: utf-8 -*-
"""Joint optimization of Z1 manual-U depth and S-transition positions.

The experiment starts from the final L1-L20 checkpoint (256 manual U's on
L2-L5) and asks whether moving the two R15 transition curves along the U arms
-- and, in experiment B, deepening the U -- can make the frozen z=0.5 mm Z2
interface routes compatible with the Z1 world.

Hard invariants
---------------
* all 256 manual U endpoints, tangents, pairings, groups and target layers stay
  unchanged;
* the original depth ordering of nested same-side U's is preserved;
* R15, 0.08 mm true-3D clearance, z1=0, z2=0.5 and the 150x150 mm board are
  never relaxed;
* every accepted change is checked by the real ``l3d.world.World`` and the
  final payload is checked by the repository validator.

The module is deliberately independent of the production 1024-channel router;
it only re-parameterises the 256 already-validated manual U's.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..fsd25d.world25d import (point_primitive_distance_2d,
                               self_clearance_violations)
from ..manual_c4_adapt import compare_15L as M
from ..manual_c4_adapt import fixed_layer_3d as F3
from ..manual_c4_adapt import manual_20l_assignment as A
from ..manual_c4_adapt import manual_u_geometry as UGEOM
from ..manual_c4_adapt.run_full_campaign import CAMPAIGN_V4
from ..r15 import profile_r15
from ..v3c4 import lift_cross as LIFT

ROOT = Path(__file__).resolve().parents[2]
CKPT = (ROOT / 'outputs/manual_c4_new_connectivity'
        / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/checkpoints')
OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
       / 'U_DEPTH_TRANSITION_JOINT_OPT')
HEIGHTS = [round(0.65 + 0.15 * index, 2) for index in range(19)]  # L2..L20
CLEARANCE = 0.08
BOARD = 150.0


def log(message):
    print(message, flush=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
@dataclass
class UParam:
    route_id: int
    layer: int
    side: str
    group: str | None
    order: str | None
    u_pair: str | None
    arm_mm: float
    depth_mm: float
    rise_start: float
    fall_start: float
    source: tuple
    target: tuple
    source_port_id: str
    target_port_id: str
    record: dict
    original_route: dict
    original_primitives: list
    nesting_contains: int = 0
    nesting_k: int = 0


def setup_environment():
    M.install_extended_stack_builder()
    profile_r15.apply()
    return M


def load_manual_u_params(ckpt=CKPT):
    """Load the 256 manual U's, their original arm/depth and transition plan."""
    phase_b = read_json(ROOT / 'outputs/manual_c4_new_connectivity'
                        / 'MANUAL_LAYERS_20L_PROTO/phaseB.json')['results']
    conns = M.load_manual_connections()
    ckpt = Path(ckpt)
    routes = {int(k): v for k, v in read_json(ckpt / 'z1/z1_all_routes.json').items()}
    prims = {int(k): v for k, v in read_json(ckpt / 'z1/primitives.json').items()}
    manual = A.load_manual_u_mapping()
    params = OrderedDict()
    for rid in sorted(manual):
        row = phase_b[str(rid)]
        conn = conns[rid]
        transition = row.get('transition') or {}
        params[rid] = UParam(
            route_id=rid, layer=int(row['layer']), side=row['side'],
            group=row.get('group'), order=row.get('order'),
            u_pair=row.get('u_pair'), arm_mm=float(row['arm_mm']),
            depth_mm=float(row['depth_mm']),
            rise_start=float(transition.get('rise_start', 1.2)),
            fall_start=float(transition.get('fall_start', 0.0)),
            source=tuple(float(v) for v in conn['source']),
            target=tuple(float(v) for v in conn['target']),
            source_port_id=conn['record']['source_endpoint'],
            target_port_id=conn['record']['target_endpoint'],
            record=conn['record'],
            original_route=routes[rid],
            original_primitives=prims[rid],
            nesting_contains=int(row.get('nesting_contains', 0)),
            nesting_k=int(row.get('nesting_k', 0)))
    return params


def load_records_and_interface(ckpt=CKPT):
    """Return baseline records and the 48 interface Z2 routes with 2D geometry."""
    ckpt = Path(ckpt)
    payload = read_json(CAMPAIGN_V4 / 'routes_1024.json')
    records = {int(r['route_id']): r for r in payload['routes']}
    audit = list(csv.DictReader(open(
        ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_20L_FIXED_ASSIGNMENT_FULL/'
        'z2_assignment_audit.csv', encoding='utf-8-sig')))
    interface = []
    for row in audit:
        rid = int(row['route_id'])
        if row['target_layer']:
            continue
        if records[rid].get('primitives'):
            interface.append(rid)
    return records, interface


# ---------------------------------------------------------------------------
# U construction
# ---------------------------------------------------------------------------
def layer_z(layer):
    return float(A.layer_z(int(layer)))


def build_u_geometry(param, arm_mm):
    return UGEOM.build_manual_u_geometry(param.source, param.target,
                                         param.side, arm_mm=float(arm_mm))


def build_u_route(param, primitives, rise_start, fall_start):
    layer = int(param.layer)
    target_z = layer_z(layer)
    return LIFT.lift_route(param.record, 1, layer, target_z,
                           float(rise_start), float(fall_start), primitives)


def transition_polylines(route):
    result = []
    for part in route.get('parts') or []:
        if part['kind'] == 'transition':
            result.append(np.asarray(LIFT._paths().transition_samples(part),
                                     dtype=float))
    return result


def _positions_between(lo, hi, fractions=(0.0, 0.25, 0.5, 0.75, 1.0),
                       offsets=(1.0, 2.0, 4.0)):
    values = set()
    span = float(hi) - float(lo)
    for fraction in fractions:
        values.add(round(float(lo) + span * fraction, 6))
    for offset in offsets:
        if lo + offset <= hi + 1e-9:
            values.add(round(float(lo) + offset, 6))
        if hi - offset >= lo - 1e-9:
            values.add(round(float(hi) - offset, 6))
    return sorted(value for value in values if lo - 1e-9 <= value <= hi + 1e-9)


def candidate_plans(param, arm_mm, *, max_plans=80, include_original=True):
    """Transition ``(rise_start, fall_start)`` candidates for one U depth."""
    geom = build_u_geometry(param, arm_mm)
    if not geom.get('ok'):
        return [], geom
    primitives = geom['primitives']
    total = F3.path_length(primitives)
    footprint = F3.transition_footprint(abs(layer_z(param.layer)))
    windows = F3.straight_windows(primitives, footprint, total)
    if len(windows) < 2:
        return [], geom
    first, last = windows[0], windows[-1]
    rise_values = _positions_between(first[0], first[1])
    # fall is parameterised by tail length (distance to the target port)
    tail_min = 1.2
    tail_max = total - footprint - last[0]
    tail_values = _positions_between(tail_min, max(tail_min, tail_max),
                                     fractions=(0.0, 0.25, 0.5, 0.75, 1.0))
    plans = []
    if include_original:
        plans.append(dict(rise_start=param.rise_start,
                          fall_start=param.fall_start,
                          footprint=footprint, arm_mm=float(arm_mm),
                          total=total,
                          fall_defined_from_end=total - param.fall_start - footprint))
    for rise in rise_values:
        for tail in tail_values:
            fall = total - tail - footprint
            if fall < rise + footprint + F3.MIN_TRAVEL_MM:
                continue
            if fall < last[0] - 1e-9 or fall > last[1] + 1e-9:
                continue
            plans.append(dict(rise_start=float(rise), fall_start=float(fall),
                              footprint=float(footprint), arm_mm=float(arm_mm),
                              total=total, fall_defined_from_end=float(tail)))
    # Prefer moving both transitions deeper into the U arms: the S-curve then
    # crosses z=0.5 further away from the crowded port rows.
    plans.sort(key=lambda p: (-(p['rise_start'] + p['fall_defined_from_end']),
                              abs(p['rise_start'] - param.rise_start)))
    unique = []
    seen = set()
    for plan in plans:
        key = (round(plan['rise_start'], 5), round(plan['fall_start'], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(plan)
        if len(unique) >= max_plans:
            break
    return unique, geom


# ---------------------------------------------------------------------------
# local geometry context / U legality
# ---------------------------------------------------------------------------
class UContext:
    """Other 255 U's as strict/approx obstacles for one candidate U."""

    def __init__(self, world, uid):
        self.uid = int(uid)
        self.world = world
        self.other = {rid: route for rid, route in world.plan.items()
                      if rid != self.uid}
        from ..l3d.world import PlaneWorld
        self.plane = PlaneWorld()
        for rid, route in self.other.items():
            for index, part in enumerate(route.get('parts') or []):
                if part['kind'] == 'flat':
                    self.plane.add(rid * 1000 + index, part['primitives'],
                                   part['z_mm'])
        self.approx = F3.ApproxClearance(margin=0.0)
        for route in self.other.values():
            self.approx.add_route(route)

    def legal(self, route):
        if self.world.check_structure(route):
            return False, 'structure'
        for part in route.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            evaluation = self.plane.evaluate(part['primitives'], part['z_mm'])
            if evaluation is not None and not evaluation.valid:
                return False, 'same_plane'
        if self.approx.route_conflicts(route):
            return False, 'approx_3d'
        if self_clearance_violations(route, CLEARANCE):
            return False, 'self_clearance'
        return True, None


# ---------------------------------------------------------------------------
# Z2 interface compatibility index
# ---------------------------------------------------------------------------
class Z2Index:
    """Exact-ish point-to-offset-route distance between U transitions and the
    frozen z=0.5 Z2 interface paths."""

    def __init__(self, u_routes, z2_records, interface_ids):
        self.u_routes = {int(k): v for k, v in u_routes.items()}
        self.records = z2_records
        self.ids = list(interface_ids)
        self.z2_prims = {rid: [dict(p) for p in z2_records[rid]['primitives']]
                         for rid in self.ids}
        self.pair_cache = {}
        self.uid_polys = {}
        for uid, route in self.u_routes.items():
            self.uid_polys[uid] = transition_polylines(route)
        self.z2_points = {}
        self.z2_trees = {}
        from scipy.spatial import cKDTree
        for rid in self.ids:
            points = F3._sample_primitives_xy(self.z2_prims[rid], 0.05)
            array = np.asarray(points, dtype=float)
            self.z2_points[rid] = array
            self.z2_trees[rid] = cKDTree(array) if len(array) else None

    @staticmethod
    def _point_route_distance(point, primitives):
        px, py, pz = float(point[0]), float(point[1]), float(point[2])
        best = float('inf')
        for prim in primitives:
            bbox = F3._primitive_bbox_2d(prim)
            if (px < bbox[0] - 0.3 or px > bbox[2] + 0.3
                    or py < bbox[1] - 0.3 or py > bbox[3] + 0.3):
                continue
            distance = math.hypot(point_primitive_distance_2d((px, py),
                                                               prim),
                                  pz - 0.5)
            if distance < best:
                best = distance
                if best < CLEARANCE:
                    return best
        return best

    def pair_distance(self, uid, rid):
        key = (int(uid), int(rid))
        cached = self.pair_cache.get(key)
        if cached is not None:
            return cached
        prims = self.z2_prims[int(rid)]
        tree = self.z2_trees[int(rid)]
        points = self.z2_points[int(rid)]
        best = float('inf')
        if tree is not None:
            for polyline in self.uid_polys.get(int(uid), ()):
                distances, indices = tree.query(polyline[:, :2],
                                                distance_upper_bound=0.25)
                for index in np.nonzero(np.isfinite(distances))[0]:
                    if abs(float(polyline[index, 2]) - 0.5) > 0.25:
                        continue
                    distance = self._point_route_distance(polyline[index],
                                                          prims)
                    if distance < best:
                        best = distance
                        if best < CLEARANCE:
                            self.pair_cache[key] = best
                            return best
        else:
            for polyline in self.uid_polys.get(int(uid), ()):
                for point in polyline:
                    distance = self._point_route_distance(point, prims)
                    if distance < best:
                        best = distance
                        if best < CLEARANCE:
                            self.pair_cache[key] = best
                            return best
        self.pair_cache[key] = best
        return best

    def candidate_distance(self, polylines, rid):
        prims = self.z2_prims[int(rid)]
        tree = self.z2_trees[int(rid)]
        best = float('inf')
        if tree is None:
            return best
        for polyline in polylines:
            distances, indices = tree.query(polyline[:, :2],
                                            distance_upper_bound=0.25)
            for index in np.nonzero(np.isfinite(distances))[0]:
                if abs(float(polyline[index, 2]) - 0.5) > 0.25:
                    continue
                distance = self._point_route_distance(polyline[index], prims)
                if distance < best:
                    best = distance
                    if best < CLEARANCE:
                        return best
        return best

    def blockers(self, rid):
        return [uid for uid in self.u_routes
                if self.pair_distance(uid, rid) < CLEARANCE]

    def success_set(self):
        result = set()
        for rid in self.ids:
            if all(self.pair_distance(uid, rid) >= CLEARANCE
                   for uid in self.u_routes):
                result.add(rid)
        return result

    def refresh_uid(self, uid, route):
        self.uid_polys[int(uid)] = transition_polylines(route)
        for rid in self.ids:
            self.pair_cache.pop((int(uid), int(rid)), None)


# ---------------------------------------------------------------------------
# world / validation helpers
# ---------------------------------------------------------------------------
def build_lifter(out_dir, heights=None):
    heights = heights or HEIGHTS
    return LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out_dir,
                               heights=heights, log=log)


def make_u_routes(params):
    return {int(rid): dict(param.original_route) for rid, param in params.items()}


def add_route_to_world(world, route):
    world.add_route(route)


def world_from_routes(lifter, routes):
    lifter.world.rebuild({})
    for rid in sorted(routes):
        lifter.world.add_route(routes[rid])
    return lifter.world


def make_failed_record(record, reason):
    out = dict(record)
    out['status'] = 'failed'
    out['reason'] = reason
    out.pop('parts', None)
    out.pop('primitives', None)
    row = int(record.get('source_row') or
              (1 if record.get('plane') == 'z1' else 2))
    source_xy = LIFT._endpoint_xy(record['source_endpoint'])
    target_xy = LIFT._endpoint_xy(record['target_endpoint'])
    out['source_row'] = row
    out['target_row'] = row
    out['start_z_mm'] = 0.0 if row == 1 else 0.5
    out['end_z_mm'] = out['start_z_mm']
    out['source_port'] = dict(xy=[source_xy[0], source_xy[1]],
                              z_mm=out['start_z_mm'], layer_id=1)
    out['target_port'] = dict(xy=[target_xy[0], target_xy[1]],
                              z_mm=out['start_z_mm'], layer_id=1)
    return out


def make_routed_record(record, route, primitives=None):
    out = dict(record)
    out.update(route)
    out['status'] = 'routed'
    out['route_id'] = int(record['route_id'])
    out.pop('reason', None)
    if primitives is not None:
        out['primitives'] = [dict(p) for p in primitives]
    row = int(record.get('source_row') or
              (1 if record.get('plane') == 'z1' else 2))
    if 'source_port' not in out:
        source_xy = LIFT._endpoint_xy(record['source_endpoint'])
        out['source_port'] = dict(xy=[source_xy[0], source_xy[1]],
                                  z_mm=0.0 if row == 1 else 0.5,
                                  layer_id=1)
    if 'target_port' not in out:
        target_xy = LIFT._endpoint_xy(record['target_endpoint'])
        out['target_port'] = dict(xy=[target_xy[0], target_xy[1]],
                                  z_mm=0.0 if row == 1 else 0.5,
                                  layer_id=1)
    out.setdefault('source_row', row)
    out.setdefault('target_row', row)
    return out


def validate_route_subset(route_map, prims_map, records, out_path,
                          layer_stack=None):
    """Run the real repository validator on an arbitrary routed subset."""
    from ..l3d import validate_l3d as V
    from ..v3c4.inputs import ENDPOINTS
    V.set_routing_layer_ids(range(2, 21))
    payload_routes = []
    for rid in sorted(records):
        record = records[rid]
        if rid in route_map:
            payload_routes.append(make_routed_record(
                record, route_map[rid], prims_map.get(rid)))
        else:
            payload_routes.append(make_failed_record(
                record, 'not_in_this_subset'))
    payload = dict(
        schema='four_side_1024_v2_l3d_routes_v1',
        experiment='U_DEPTH_TRANSITION_JOINT_OPT',
        note='Z1 manual U depth / transition optimization subset',
        layer_stack=layer_stack or A.layer_stack_payload(),
        routes=payload_routes)
    identity = {'available': True, 'error': None, 'planes': {}}
    base = read_json(CAMPAIGN_V4 / 'routes_1024.json')
    for plane in ('z1', 'z2'):
        rr = {}
        for record in base['routes']:
            if record.get('plane') != plane:
                continue
            rid = int(record['route_id'])
            rr[rid] = dict(route_id=rid,
                           source_endpoint=record['source_endpoint'],
                           target_endpoint=record['target_endpoint'],
                           source_side=record['source_side'],
                           target_side=record['target_side'],
                           source_row=int(record['source_row']),
                           target_row=int(record['target_row']),
                           relation=record['relation'], pair=record['pair'])
        identity['planes'][plane] = {'routes': rr, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity
    report = V.validate_payload(payload, allow_exploratory=True)
    write_json(out_path, report)
    return report


# ---------------------------------------------------------------------------
# experiment A/B search
# ---------------------------------------------------------------------------
@dataclass
class Change:
    route_id: int
    old_arm_mm: float
    new_arm_mm: float
    old_depth_mm: float
    new_depth_mm: float
    old_rise: float
    new_rise: float
    old_fall: float
    new_fall: float
    old_fall_tail: float
    new_fall_tail: float
    recovered_z2: list = field(default_factory=list)
    budget_index: int = 0


def _max_arm_for_uid(uid, params, arms, layer_side):
    """Largest arm that still preserves the original nested depth ordering."""
    current = float(arms[uid])
    same = [(rid, arm) for rid, arm in arms.items()
            if rid != uid and layer_side[rid] == layer_side[uid]
            and arm > current + 1e-9]
    if not same:
        return float(UGEOM.MAX_DEPTH_MM - UGEOM.PROFILE_RADIUS_MM)
    return min(arm for _rid, arm in same) - 1e-6


def _depth_arms(uid, params, arms, layer_side, mode):
    current = float(arms[uid])
    if mode == 'A':
        return [current]
    limit = min(current + 30.0,
                _max_arm_for_uid(uid, params, arms, layer_side),
                float(UGEOM.MAX_DEPTH_MM - UGEOM.PROFILE_RADIUS_MM))
    arms_out = [current]
    for delta in (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0):
        value = round(current + delta, 3)
        if value <= limit + 1e-9 and value not in arms_out:
            arms_out.append(value)
    return arms_out


def _candidate_polylines(route):
    return transition_polylines(route)


def _candidate_route(param, plan):
    geom = build_u_geometry(param, plan['arm_mm'])
    if not geom.get('ok'):
        return None, None, 'geometry:' + ','.join(geom.get('errors') or [])
    route = build_u_route(param, geom['primitives'],
                          plan['rise_start'], plan['fall_start'])
    if route is None:
        return None, geom['primitives'], 'lift_route_none'
    return route, geom['primitives'], None


class Optimizer:
    def __init__(self, mode, params, records, interface, out_dir,
                 max_candidates=20000, max_seconds=900):
        self.mode = mode
        self.params = params
        self.records = records
        self.interface = interface
        self.out_dir = Path(out_dir)
        self.max_candidates = int(max_candidates)
        self.max_seconds = float(max_seconds)
        self.candidates = 0
        self._started = time.perf_counter()
        self._deadline = self._started + self.max_seconds
        self.lifter = build_lifter(self.out_dir)
        self.u_routes = make_u_routes(params)
        self.u_prims = {rid: [dict(p) for p in param.original_primitives]
                        for rid, param in params.items()}
        self.arms = {rid: float(param.arm_mm)
                     for rid, param in params.items()}
        self.layer_side = {rid: (param.layer, param.side)
                           for rid, param in params.items()}
        world_from_routes(self.lifter, self.u_routes)
        self.z2 = Z2Index(self.u_routes, records, interface)
        self.baseline_success = self.z2.success_set()
        self.success = set(self.baseline_success)
        self.changes = []
        self.blocker_events = []

    def blockers(self, rid):
        return self.z2.blockers(rid)

    def _base_min_excluding(self, uid, rid):
        best = float('inf')
        for other in self.u_routes:
            if other == uid:
                continue
            distance = self.z2.pair_distance(other, rid)
            if distance < best:
                best = distance
                if best < CLEARANCE:
                    break
        return best

    def _after_blockers(self, uid, candid_polys, rid, group=()):
        """Number of Z2 blockers for ``rid`` after replacing ``group``."""
        group = set(group) | {int(uid)}
        count = 0
        for other in self.u_routes:
            if other in group:
                continue
            if self.z2.pair_distance(other, rid) < CLEARANCE:
                count += 1
        if self.z2.candidate_distance(candid_polys, rid) < CLEARANCE:
            count += 1
        return count

    def _no_success_regression(self, uid, candid_polys, group=()):
        group = set(group) | {int(uid)}
        for other_rid in self.success:
            base = min((self.z2.pair_distance(other, other_rid)
                        for other in self.u_routes if other not in group),
                       default=float('inf'))
            if base < CLEARANCE:
                return False
            if self.z2.candidate_distance(candid_polys, other_rid) < CLEARANCE:
                return False
        return True

    def _candidate_clears(self, uid, candid_polys, rid, success):
        return self._after_blockers(uid, candid_polys, rid) == 0 and \
            self._no_success_regression(uid, candid_polys)

    def _ancestor_chain(self, uid):
        """Outer-to-inner U chain that must move together to preserve nesting."""
        target = self.params[uid]
        group = [rid for rid, param in self.params.items()
                 if rid != uid and param.layer == target.layer
                 and param.side == target.side
                 and self.arms[rid] > self.arms[uid] + 1e-9]
        group.sort(key=lambda rid: self.arms[rid], reverse=True)
        return group + [uid]

    def try_group_depth_for_route(self, uid, target_rid):
        """B-mode coordinated move of one U and all its outer ancestors.

        Deepening an inner U without moving the surrounding nested chain would
        destroy the original depth ordering; this helper moves the whole outer
        chain by the same delta and checks the complete 3D result.
        """
        if self.mode != 'B':
            return None
        group = self._ancestor_chain(uid)
        if len(group) <= 1 and self.mode != 'B':
            return None
        outer = group[0]
        max_outer = float(UGEOM.MAX_DEPTH_MM - UGEOM.PROFILE_RADIUS_MM)
        old_routes = {rid: self.u_routes[rid] for rid in group}
        before_blockers = len(self.blockers(target_rid))
        # remove all old group routes once
        for rid in group:
            self.lifter.world.remove_route(rid)
        # local context of the remaining U world
        remaining = dict(self.lifter.world.plan)
        from ..l3d.world import PlaneWorld
        plane = PlaneWorld()
        for rid, route in remaining.items():
            for index, part in enumerate(route.get('parts') or []):
                if part['kind'] == 'flat':
                    plane.add(rid * 1000 + index, part['primitives'],
                              part['z_mm'])
        approx = F3.ApproxClearance(margin=0.0)
        for route in remaining.values():
            approx.add_route(route)
        accepted = None
        delta_values = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0)
        try:
            for delta in delta_values:
                if any(self.arms[rid] + delta > max_outer + 1e-9
                       for rid in group):
                    continue
                new_routes = {}
                new_prims = {}
                failed = False
                for rid in group:
                    param = self.params[rid]
                    arm = float(self.arms[rid] + delta)
                    plans, geom = candidate_plans(param, arm, max_plans=4,
                                                  include_original=False)
                    if not plans or not geom.get('ok'):
                        failed = True
                        break
                    plan = plans[0]
                    route, primitives, reason = _candidate_route(param, plan)
                    if route is None:
                        failed = True
                        break
                    if self.candidates >= self.max_candidates:
                        return None
                    self.candidates += 1
                    # plane checks are performed below on each flat part
                    ok = True
                    for part in route.get('parts') or []:
                        if part['kind'] != 'flat':
                            continue
                        evaluation = plane.evaluate(part['primitives'],
                                                    part['z_mm'])
                        if evaluation is not None and not evaluation.valid:
                            ok = False
                            break
                    if not ok or approx.route_conflicts(route):
                        failed = True
                        break
                    if self_clearance_violations(route, CLEARANCE):
                        failed = True
                        break
                    # add to local plane/approx to check the next group member
                    for index, part in enumerate(route.get('parts') or []):
                        if part['kind'] == 'flat':
                            plane.add(rid * 1000 + index, part['primitives'],
                                      part['z_mm'])
                    approx.add_route(route)
                    new_routes[rid] = route
                    new_prims[rid] = [dict(p) for p in primitives]
                if failed or len(new_routes) != len(group):
                    continue
                # add the candidate group; pairwise group legality was checked
                # incrementally by plane + approx above.  The final payload is
                # validated by the repository validator after the search.
                for rid, route in new_routes.items():
                    self.lifter.world.add_route(route)
                # Z2 compatibility: all changed U transitions together
                after = 0
                for other in self.u_routes:
                    if other in group:
                        continue
                    if self.z2.pair_distance(other, target_rid) < CLEARANCE:
                        after += 1
                for route in new_routes.values():
                    if self.z2.candidate_distance(
                            transition_polylines(route), target_rid) < CLEARANCE:
                        after += 1
                if after >= before_blockers:
                    for rid in group:
                        self.lifter.world.remove_route(rid)
                    continue
                regression = False
                for other_rid in self.success:
                    base = min((self.z2.pair_distance(other, other_rid)
                                for other in self.u_routes if other not in group),
                               default=float('inf'))
                    cand = min(self.z2.candidate_distance(
                        transition_polylines(route), other_rid)
                        for route in new_routes.values())
                    if base < CLEARANCE or cand < CLEARANCE:
                        regression = True
                        break
                if regression:
                    for rid in group:
                        self.lifter.world.remove_route(rid)
                    continue
                accepted = (delta, new_routes, new_prims)
                break
        finally:
            if accepted is None:
                for rid in group:
                    self.lifter.world.add_route(old_routes[rid])
        if accepted is None:
            return None
        delta, new_routes, new_prims = accepted
        recovered_before = set(self.success)
        for rid in group:
            self.u_routes[rid] = new_routes[rid]
            self.u_prims[rid] = new_prims[rid]
            self.arms[rid] = self.params[rid].arm_mm + delta
            self.z2.refresh_uid(rid, new_routes[rid])
        self.success = self.z2.success_set()
        recovered = sorted(self.success - recovered_before)
        for rid in group:
            route = new_routes[rid]
            old_route = old_routes[rid]
            # record the actual transition plan from the route's part positions
            rise = next((part['length_mm'] for part in route['parts']
                         if part['kind'] == 'flat'), 0.0)
            fall = next((part['length_mm'] for part in reversed(route['parts'])
                         if part['kind'] == 'flat'), 0.0)
            self.changes.append(Change(
                route_id=rid, old_arm_mm=float(old_routes[rid].get('arm_mm')
                                               or self.params[rid].arm_mm),
                new_arm_mm=float(self.arms[rid]),
                old_depth_mm=float(self.params[rid].depth_mm),
                new_depth_mm=float(self.arms[rid] + UGEOM.PROFILE_RADIUS_MM),
                old_rise=self.params[rid].rise_start, new_rise=float(rise),
                old_fall=self.params[rid].fall_start, new_fall=float(fall),
                old_fall_tail=0.0, new_fall_tail=0.0,
                recovered_z2=recovered if rid == uid else [],
                budget_index=self.candidates))
        return self.changes[-1]

    def try_uid_for_route(self, uid, target_rid):
        old_route = self.u_routes[uid]
        param = self.params[uid]
        old_arm = self.arms[uid]
        self.lifter.world.remove_route(uid)
        context = UContext(self.lifter.world, uid)
        accepted = None
        before_blockers = len(self.blockers(target_rid))
        arm_options = _depth_arms(uid, self.params, self.arms,
                                  self.layer_side, self.mode)
        try:
            for arm in arm_options:
                plans, geom = candidate_plans(
                    param, arm, max_plans=70,
                    include_original=(abs(arm - old_arm) < 1e-9))
                if not plans:
                    continue
                for plan in plans:
                    if self.candidates >= self.max_candidates:
                        return None
                    self.candidates += 1
                    route, primitives, reason = _candidate_route(param, plan)
                    if route is None:
                        continue
                    legal, why = context.legal(route)
                    if not legal:
                        continue
                    cand_polys = _candidate_polylines(route)
                    if self._after_blockers(uid, cand_polys,
                                            target_rid) >= before_blockers:
                        continue
                    if not self._no_success_regression(uid, cand_polys):
                        continue
                    violations = self.lifter.world.check_route(
                        route, check_self=True)
                    if violations:
                        self.blocker_events.append(dict(
                            route_id=target_rid, uid=uid,
                            reason='strict:' + str(violations[0].get('kind'))))
                        continue
                    accepted = (route, primitives, plan, arm)
                    break
                if accepted is not None:
                    break
        finally:
            if accepted is None:
                self.lifter.world.add_route(old_route)
        if accepted is None:
            return None
        route, primitives, plan, arm = accepted
        self.lifter.world.add_route(route)
        recovered_before = set(self.success)
        self.u_routes[uid] = route
        self.u_prims[uid] = [dict(p) for p in primitives]
        self.arms[uid] = float(arm)
        self.z2.refresh_uid(uid, route)
        self.success = self.z2.success_set()
        recovered = sorted(self.success - recovered_before)
        change = Change(
            route_id=uid, old_arm_mm=old_arm, new_arm_mm=float(arm),
            old_depth_mm=float(old_arm + UGEOM.PROFILE_RADIUS_MM),
            new_depth_mm=float(arm + UGEOM.PROFILE_RADIUS_MM),
            old_rise=param.rise_start, new_rise=plan['rise_start'],
            old_fall=param.fall_start, new_fall=plan['fall_start'],
            old_fall_tail=float(param.original_route.get('length_mm') or 0)
            - param.fall_start - plan['footprint'],
            new_fall_tail=plan['fall_defined_from_end'],
            recovered_z2=recovered, budget_index=self.candidates)
        self.changes.append(change)
        return change

    def run(self, max_passes=3):
        for pass_index in range(max_passes):
            if time.perf_counter() > self._deadline:
                log(f'[{self.mode}] time budget reached')
                break
            failures = [rid for rid in self.interface if rid not in self.success]
            failures.sort(key=lambda rid: len(self.blockers(rid)))
            if not failures:
                break
            improved = False
            for rid in failures:
                if time.perf_counter() > self._deadline:
                    break
                if rid in self.success:
                    continue
                blockers = self.blockers(rid)
                for uid in blockers[:8]:
                    change = self.try_uid_for_route(uid, rid)
                    if change is not None:
                        improved = True
                        log(f'[{self.mode}] changed U{uid} for Z2 {rid}; '
                            f'success={len(self.success)}')
                        break
                    if self.mode == 'B':
                        change = self.try_group_depth_for_route(uid, rid)
                        if change is not None:
                            improved = True
                            log(f'[{self.mode}] group change U{uid} for Z2 {rid}; '
                                f'success={len(self.success)}')
                            break
            recovered = len(self.success) - len(self.baseline_success)
            log(f'[{self.mode}] pass={pass_index + 1} '
                f'recovered={recovered} success={len(self.success)}/'
                f'{len(self.interface)} candidates={self.candidates} '
                f'changes={len(self.changes)}')
            if not improved:
                break
        return self.success

    # -- output ------------------------------------------------------------
    def results(self):
        results = {}
        for rid in self.interface:
            results[rid] = dict(route_id=rid,
                                ok=rid in self.success,
                                blockers=self.blockers(rid))
        return results

    def save(self, out_dir=None):
        out_dir = Path(out_dir or self.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_dir / 'u_routes.json',
                   {str(rid): self.u_routes[rid] for rid in self.u_routes})
        write_json(out_dir / 'u_primitives.json',
                   {str(rid): self.u_prims[rid] for rid in self.u_prims})
        write_json(out_dir / 'u_parameters.json',
                   {str(rid): dict(
                       route_id=rid, layer=self.params[rid].layer,
                       side=self.params[rid].side,
                       group=self.params[rid].group,
                       original_arm_mm=self.params[rid].arm_mm,
                       current_arm_mm=self.arms[rid],
                       current_depth_mm=self.arms[rid] + UGEOM.PROFILE_RADIUS_MM,
                       current_rise_start=next(
                           (c.new_rise for c in reversed(self.changes)
                            if c.route_id == rid),
                           self.params[rid].rise_start),
                       current_fall_start=next(
                           (c.new_fall for c in reversed(self.changes)
                            if c.route_id == rid),
                           self.params[rid].fall_start))
                   for rid in self.params})
        results = self.results()
        write_json(out_dir / 'z2_results.json', dict(
            total=len(self.interface), baseline_ok=len(self.baseline_success),
            results=results,
            baseline_ok_ids=sorted(self.baseline_success),
            recovered_ids=sorted(self.success - self.baseline_success),
            still_failed_ids=sorted(set(self.interface) - self.success)))
        write_json(out_dir / 'summary.json', dict(
            mode=self.mode, total_interface=len(self.interface),
            baseline_success=len(self.baseline_success),
            success=len(self.success),
            recovered=len(self.success - self.baseline_success),
            candidates=self.candidates,
            changed_u=len(self.changes),
            deepened_u=sum(1 for change in self.changes
                           if change.new_arm_mm > change.old_arm_mm + 1e-9),
            total_depth_increase_mm=sum(
                max(0.0, change.new_arm_mm - change.old_arm_mm)
                for change in self.changes),
            changes=[change.__dict__ for change in self.changes],
            blocker_events=self.blocker_events,
            elapsed=self._elapsed))
        # CSV outputs
        with (out_dir / 'route_changes.csv').open('w', newline='',
                                                  encoding='utf-8-sig') as fh:
            fields = ['route_id', 'old_arm_mm', 'new_arm_mm', 'old_depth_mm',
                      'new_depth_mm', 'old_rise', 'new_rise', 'old_fall',
                      'new_fall', 'old_fall_tail', 'new_fall_tail',
                      'recovered_z2', 'budget_index']
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for change in self.changes:
                row = dict(change.__dict__)
                row['recovered_z2'] = ';'.join(map(str, change.recovered_z2))
                writer.writerow(row)
        with (out_dir / 'u_depth_changes.csv').open('w', newline='',
                                                    encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                'route_id', 'old_depth_mm', 'new_depth_mm', 'delta_depth_mm',
                'new_arm_mm'])
            writer.writeheader()
            for change in self.changes:
                if change.new_arm_mm <= change.old_arm_mm + 1e-9:
                    continue
                writer.writerow(dict(
                    route_id=change.route_id, old_depth_mm=change.old_depth_mm,
                    new_depth_mm=change.new_depth_mm,
                    delta_depth_mm=change.new_depth_mm - change.old_depth_mm,
                    new_arm_mm=change.new_arm_mm))
        with (out_dir / 'transition_position_changes.csv').open(
                'w', newline='', encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                'route_id', 'old_rise', 'new_rise', 'rise_delta',
                'old_fall_start', 'new_fall_start', 'fall_delta',
                'new_fall_tail'])
            writer.writeheader()
            for change in self.changes:
                writer.writerow(dict(
                    route_id=change.route_id, old_rise=change.old_rise,
                    new_rise=change.new_rise,
                    rise_delta=change.new_rise - change.old_rise,
                    old_fall_start=change.old_fall,
                    new_fall_start=change.new_fall,
                    fall_delta=change.new_fall - change.old_fall,
                    new_fall_tail=change.new_fall_tail))
        # validation: U + successful interface routes
        routed = dict(self.u_routes)
        prims = dict(self.u_prims)
        for rid in self.success:
            prims[rid] = [dict(p) for p in self.records[rid]['primitives']]
            routed[rid] = LIFT.flat_route(rid, 'z2', prims[rid], row=2)
        report = validate_route_subset(routed, prims, self.records,
                                       out_dir / 'validation.json')
        write_json(out_dir / 'validation_summary.json', dict(
            status=report.get('status'),
            geometry_pass=report.get('geometry_pass'),
            counts=report.get('counts')))
        return out_dir

    @property
    def _elapsed(self):
        return round(time.perf_counter() - self._started, 2)

    def __post_init__(self):
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run_baseline(out_dir):
    params = load_manual_u_params()
    records, interface = load_records_and_interface()
    lifter = build_lifter(out_dir / 'baseline')
    u_routes = make_u_routes(params)
    world_from_routes(lifter, u_routes)
    z2 = Z2Index(u_routes, records, interface)
    success = z2.success_set()
    results = {rid: dict(route_id=rid, ok=rid in success,
                         blockers=z2.blockers(rid))
               for rid in interface}
    prims = {rid: [dict(p) for p in param.original_primitives]
             for rid, param in params.items()}
    out = Path(out_dir) / 'baseline'
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'u_routes.json',
               {str(rid): u_routes[rid] for rid in u_routes})
    write_json(out / 'u_primitives.json',
               {str(rid): prims[rid] for rid in prims})
    write_json(out / 'z2_results.json', dict(
        total=len(interface), ok=len(success), results=results,
        success_ids=sorted(success), failed_ids=sorted(set(interface) - success)))
    write_json(out / 'blocker_analysis.json', dict(
        baseline=dict(ok=len(success), failed=len(interface) - len(success)),
        blockers={str(rid): [int(uid) for uid in z2.blockers(rid)]
                  for rid in interface if rid not in success}))
    routed = dict(u_routes)
    for rid in success:
        prims[rid] = [dict(p) for p in records[rid]['primitives']]
        routed[rid] = LIFT.flat_route(rid, 'z2', prims[rid], row=2)
    report = validate_route_subset(routed, prims, records,
                                   out / 'validation.json')
    write_json(out / 'validation_summary.json', dict(
        status=report.get('status'), geometry_pass=report.get('geometry_pass'),
        counts=report.get('counts')))
    write_json(out_dir / 'baseline_summary.json', dict(
        total=len(interface), success=len(success), failed=len(interface) - len(success),
        success_ids=sorted(success), failed_ids=sorted(set(interface) - success)))
    return dict(options=params, records=records, interface=interface,
                world=lifter.world, z2=z2, u_routes=u_routes, prims=prims)


def run_experiment(mode, out_dir, max_candidates=20000, max_seconds=900):
    params = load_manual_u_params()
    records, interface = load_records_and_interface()
    name = ('experiment_A_fixed_depth' if mode == 'A'
            else 'experiment_B_adaptive_depth')
    target = Path(out_dir) / name
    opt = Optimizer(mode, params, records, interface, target, max_candidates,
                    max_seconds)
    opt.run()
    opt.save(target)
    return opt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', default=str(OUT))
    parser.add_argument('--mode', choices=['baseline', 'A', 'B', 'all'],
                        default='all')
    parser.add_argument('--max-candidates', type=int, default=20000)
    parser.add_argument('--max-seconds', type=float, default=900.0)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode in ('baseline', 'all'):
        log('[baseline] building 256 U + 48 Z2 interface baseline')
        run_baseline(out_dir)
    if args.mode in ('A', 'all'):
        log('[A] fixed-depth transition-position search')
        run_experiment('A', out_dir, args.max_candidates, args.max_seconds)
    if args.mode in ('B', 'all'):
        log('[B] adaptive-depth joint search')
        run_experiment('B', out_dir, args.max_candidates, args.max_seconds)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

