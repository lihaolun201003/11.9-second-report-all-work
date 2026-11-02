# -*- coding: utf-8 -*-
"""FULL 1024-channel manual-first run on the campaign topology (one bounded run).

The 256 manual U's from the isolated phase are FIXED.  The other 768 connections
keep their original endpoint pairs and are rebuilt from scratch with the
unchanged strict-C4 group engine (z1: 64 opposite C4 groups, z2: 128 groups;
manual groups excluded), with the manual U's:
* z1 -> fixed z=0 obstacle geometry (+ transition low-band keep-out);
* z2 -> transition keep-out around z=0.5 (legal same-plane crossings unchanged).
The original crossing-lift then assigns L5-L15 for the 768 non-manual routes
while the 256 manual U's stay fixed.

Output: outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_MANUAL_FIRST_FULL/
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.spatial import cKDTree

from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import manual_u_geometry as UGEOM
from four_side_1024.manual_c4 import state as _STATE_TEMPLATE
from four_side_1024.manual_c4.router import ManualGroupRouter, order_groups as ORDER_GROUPS
from four_side_1024.v2opt.core import new_index, router_cfg
from four_side_1024.d56.index import prepare
from four_side_1024.d56.frames import build_frames
from four_side_1024.d56.search import static_endpoint_lines
from four_side_1024.fslw import config as C
from four_side_1024.fslw.candidates import FrameOracleSet
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.v3c4 import lift_cross_run as LIFT_RUN

NEW_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_GROUP_15L_MANUAL_FIRST_FULL')
MANUAL_JSON = (ROOT / 'outputs/manual_c4_new_connectivity'
               / 'MANUAL_GROUP_15L_COMPARISON_FIXED/manual_first'
               / 'manual_isolated.json')
CAMPAIGN_V4 = (ROOT / 'outputs/manual_c4_new_connectivity'
               / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected')
BUDGET = 1600
RETRY_PASSES = 3
RR_ROUNDS = 2
CROSSING_BUDGET_S = 480.0
MAX_GROUPS = 300


def log(message):
    print(message, flush=True)


def write_json(path, payload, indent=1):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                                     default=str), encoding='utf-8')


# ---------------------------------------------------------------------------
# campaign-topology layout state (frames from the campaign layout itself)
# ---------------------------------------------------------------------------
class CampaignState:
    """Minimal LayoutState-compatible API for the campaign connectivity."""

    def __init__(self, payload, plane, log=print):
        self.plane = plane
        self.log = log
        self.cfg = router_cfg()
        self.routes = [record for record in payload['routes']
                       if record.get('plane') == plane]
        self.route_by_id = {int(record['route_id']): record
                            for record in self.routes}
        # all true endpoint positions from the frozen port model
        self.endpoints = {}
        for record in payload['routes']:
            for key, row_key in (('source', 'source_row'),
                                 ('target', 'target_row')):
                port_id = record.get(key + '_endpoint')
                if port_id is None or port_id in self.endpoints:
                    continue
                xy = LIFT._endpoint_xy(port_id)
                side = str(port_id)[0].upper()
                inward = {'N': (0.0, -1.0), 'S': (0.0, 1.0),
                          'E': (-1.0, 0.0), 'W': (1.0, 0.0)}[side]
                self.endpoints[port_id] = dict(
                    routing_xy=(float(xy[0]), float(xy[1])),
                    side=side, inward=inward,
                    row=int(record.get(row_key) or
                            (1 if record['plane'] == 'z1' else 2)))
        normal = [record for record in self.routes
                  if record.get('relation') != 'same']
        same = [record for record in self.routes
                if record.get('relation') == 'same']
        self.normal_routes = normal
        self.same_side_routes = same
        self.frames = build_frames(normal, self.endpoints)
        stubs = {int(record['route_id']): _SameSideStub(record, self.endpoints)
                 for record in same}
        static_frames = dict(self.frames)
        static_frames.update(stubs)
        self.static_h, self.static_v = static_endpoint_lines(static_frames)
        self.oracles = FrameOracleSet(self.frames, self.static_h,
                                      self.static_v,
                                      clearance=C.CLEARANCE_MM)
        self.index = new_index(self.cfg)
        self.accepted = {}
        self.failed = {}

    def add(self, result):
        self.accepted[result.route_id] = result
        self.failed.pop(result.route_id, None)
        self.index.add(result.route_id, result.prepared)
        self.oracles.add(result.route_id, result.prepared)

    def remove(self, route_id):
        self.accepted.pop(route_id, None)
        self.index.remove(route_id)
        self.oracles.remove(route_id)

    def snapshot(self):
        return dict(accepted=dict(self.accepted),
                    failed=dict(self.failed))

    def restore(self, snapshot):
        self.accepted = dict(snapshot['accepted'])
        self.failed = dict(snapshot['failed'])
        self.index = new_index(self.cfg)
        self.oracles = FrameOracleSet(self.frames, self.static_h,
                                      self.static_v,
                                      clearance=C.CLEARANCE_MM)
        for rid, result in self.accepted.items():
            self.index.add(rid, result.prepared)
            self.oracles.add(rid, result.prepared)

    def oracle_for(self, route_id):
        return self.oracles.oracle_for(self.frames[route_id])


class _SameSideStub:
    __slots__ = ('route_id', 'source_side', 'target_side', 'src_xy', 'dst_xy',
                 'kind')

    def __init__(self, route, endpoints):
        self.route_id = int(route['route_id'])
        self.source_side = route['source_side']
        self.target_side = route['target_side']
        self.src_xy = tuple(endpoints[route['source_endpoint']]['routing_xy'])
        self.dst_xy = tuple(endpoints[route['target_endpoint']]['routing_xy'])
        self.kind = 'same'


# ---------------------------------------------------------------------------
# manual geometry helpers
# ---------------------------------------------------------------------------
def load_manual_routes():
    rows = json.loads(MANUAL_JSON.read_text(encoding='utf-8'))['results']
    connections = M.load_manual_connections()
    routes = {}
    primitives = {}
    for rid_text, row in rows.items():
        rid = int(rid_text)
        if row.get('failed'):
            continue
        connection = connections[rid]
        prims = row['primitives']
        layer = int(row['layer'])
        layer_z = 0.0 if layer == 1 else 0.65 + 0.15 * (layer - 2)
        if layer == 1:
            route = LIFT.flat_route(rid, 'z1', prims, row=1)
        else:
            plan = row['transition']
            route = LIFT.lift_route(connection['record'], 1, layer, layer_z,
                                    plan['rise_start'], plan['fall_start'],
                                    prims)
        if route is None:
            raise SystemExit(f'manual route {rid} rebuild failed')
        routes[rid] = route
        primitives[rid] = prims
    return routes, primitives


def sample_prepared(prepared, step_mm=0.5):
    points = []
    for prim in prepared.prims:
        if prim.kind == 'line':
            p0 = np.asarray(prim.p0, dtype=float)
            p1 = np.asarray(prim.p1, dtype=float)
            length = float(np.linalg.norm(p1 - p0))
            count = max(2, int(length / step_mm) + 1)
            for index in range(count):
                points.append(p0 + (p1 - p0) * (index / (count - 1)))
        else:
            center = np.asarray(prim.center, dtype=float)
            radius = float(prim.radius)
            sweep = float(prim.sweep)
            p0 = np.asarray(prim.p0, dtype=float)
            start = math.atan2(p0[1] - center[1], p0[0] - center[0])
            count = max(2, int(abs(sweep) * radius / step_mm) + 1)
            for index in range(count):
                angle = start + sweep * index / (count - 1)
                points.append(center + radius * np.asarray([math.cos(angle),
                                                            math.sin(angle)]))
    return np.asarray(points, dtype=float)


def make_guard(original_evaluate, guard_points, clearance=0.08):
    tree = cKDTree(guard_points[:, :2]) if len(guard_points) else None

    def guarded(prepared, exclude=(), stop_on_invalid=True):
        result = original_evaluate(prepared, exclude=exclude,
                                   stop_on_invalid=stop_on_invalid)
        if not result.valid:
            return result
        if tree is not None:
            points = sample_prepared(prepared)
            if len(points) and float(tree.query(points)[0].min()) < clearance:
                result.valid = False
                result.reason = 'manual_transition_keepout'
                return result
        return result

    return guarded


def manual_z0_obstacles(manual_routes):
    obstacles = {}
    for rid, route in manual_routes.items():
        for index, part in enumerate(route['parts']):
            if part['kind'] != 'flat' or abs(float(part['z_mm'])) > 1e-9:
                continue
            obstacle_id = rid if index == 0 else rid * 1000 + index
            obstacles[obstacle_id] = [dict(primitive)
                                      for primitive in part['primitives']]
    return obstacles


# ---------------------------------------------------------------------------
# fresh manual-first C4 routing on one plane
# ---------------------------------------------------------------------------
def route_plane(payload, plane, manual_ids, manual_routes, guard_points):
    state = CampaignState(payload, plane, log=log)
    groups = payload['rotation_groups']
    plane_groups = []
    manual_groups = set()
    for group in groups:
        ids = [int(rid) for rid in group['route_ids']]
        if any(records_plane(record) for record in ()):  # placeholder no-op
            pass
        group_plane = _group_plane(payload, group)
        if group_plane != plane:
            continue
        if all(rid in manual_ids for rid in ids):
            manual_groups.add(int(group['group_id']))
            continue
        if any(rid in manual_ids for rid in ids):
            # partially manual group should not exist for the manual design;
            # fixed members stay, the rest are excluded and reported
            log(f'[{plane}] WARNING partial manual group {group["group_id"]} '
                f'{ids} -> skipped')
            manual_groups.add(int(group['group_id']))
            continue
        plane_groups.append(group)
    log(f'[{plane}] groups: total={len(plane_groups)} '
        f'(manual frozen={len(manual_groups)})')
    if plane == 'z1':
        obstacles = manual_z0_obstacles(manual_routes)
        for obstacle_id, prims in obstacles.items():
            try:
                state.index.add(int(obstacle_id), prepare(prims))
            except Exception:  # noqa: BLE001
                continue
        log(f'[z1] manual z=0 obstacle parts: {len(obstacles)}')
    if len(guard_points):
        state.index.evaluate = make_guard(state.index.evaluate, guard_points)
        log(f'[{plane}] transition keep-out guard: {len(guard_points)} points')
    router = ManualGroupRouter(state, plane_groups, log=log)
    cache = router.prime_same_candidates()
    order = ORDER_GROUPS(plane_groups, router, mode='easy')
    started = time.perf_counter()
    details, summary = router.route_all(order, BUDGET,
                                        same_candidates_cache=cache)
    router.reconcile()
    log(f'[{plane}] first pass: routed_routes={len(state.accepted)} '
        f'failed_groups={len(router.failed_groups)} '
        f'({time.perf_counter() - started:.1f}s)')
    retry_history = []
    for pass_index in range(1, RETRY_PASSES + 1):
        router.reconcile()
        pending = [g for g in plane_groups
                   if g['group_id'] in router.failed_groups]
        if not pending:
            break
        pending_order = ORDER_GROUPS(pending, router, mode='easy')
        router.route_all(pending_order, BUDGET,
                         same_candidates_cache=cache)
        router.reconcile()
        retry_history.append(dict(pass_index=pass_index,
                                  attempted=len(pending_order),
                                  routed_routes=len(state.accepted),
                                  failed_groups=len(router.failed_groups),
                                  seconds=round(time.perf_counter() - started,
                                                1)))
        log(f'[{plane}] retry pass {pass_index}: '
            f'routed_routes={len(state.accepted)} '
            f'failed_groups={len(router.failed_groups)} '
            f'({time.perf_counter() - started:.1f}s)')
        if RR_ROUNDS > 0 and router.failed_groups:
            router.rr_groups(budget=BUDGET, max_rounds=RR_ROUNDS)
            router.reconcile()
            log(f'[{plane}] rr: routed_routes={len(state.accepted)} '
                f'failed_groups={len(router.failed_groups)}')
    routed = {int(rid): [dict(primitive) for primitive in result.primitives]
              for rid, result in state.accepted.items()}
    failed_ids = set()
    for group in plane_groups:
        if group['group_id'] in router.failed_groups:
            failed_ids.update(int(rid) for rid in group['route_ids'])
    failures = [dict(route_id=rid, plane=plane, reason='group_failed')
                for rid in sorted(failed_ids)]
    log(f'[{plane}] routed {len(routed)} auto routes, failed={len(failed_ids)}')
    return dict(routed=routed, failures=failures, manual_groups=len(manual_groups),
                retry_history=retry_history, plane=plane)


def _group_plane(payload, group):
    record = None
    for rid in group['route_ids']:
        record = next((item for item in payload['routes']
                       if int(item['route_id']) == int(rid)), None)
        if record is not None:
            break
    return record['plane'] if record is not None else None


def records_plane(record):
    return False


# ---------------------------------------------------------------------------
# main pipeline
# ---------------------------------------------------------------------------
def main():
    started = time.perf_counter()
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    M.install_extended_stack_builder()
    from four_side_1024.r15 import profile_r15
    profile_r15.apply()
    log('[full] R15 process profile applied before 2D candidate generation')
    LIFT.LAYER_IDS = tuple(range(2, 16))

    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json')
                         .read_text(encoding='utf-8'))
    log(f'[full] campaign topology: {len(payload["routes"])} records, '
        f'{len(payload["rotation_groups"])} C4 groups')
    manual_routes, manual_prims = load_manual_routes()
    manual_ids = set(manual_routes)
    log(f'[full] fixed manual routes: {len(manual_ids)}')

    transition_points = []
    for rid, route in manual_routes.items():
        for part in route['parts']:
            if part['kind'] != 'transition':
                continue
            samples = LIFT_RUN._part_samples(part)
            if samples is not None and len(samples):
                transition_points.append(np.asarray(samples, dtype=float))
    transition_points = (np.vstack(transition_points) if transition_points
                         else np.zeros((0, 3)))
    z1_guard = transition_points[transition_points[:, 2] < 0.09]
    z2_guard = transition_points[np.abs(transition_points[:, 2] - 0.5) < 0.09]
    log(f'[full] transition keep-out: z1={len(z1_guard)}, z2={len(z2_guard)} '
        f'points')

    reroute = {
        'z1': route_plane(payload, 'z1', manual_ids, manual_routes, z1_guard),
        'z2': route_plane(payload, 'z2', manual_ids, manual_routes, z2_guard),
    }
    write_json(NEW_DIR / 'reroute_2d.json', reroute, indent=1)

    final_2d = {}
    failures_2d = []
    for plane in ('z1', 'z2'):
        final_2d.update(reroute[plane]['routed'])
        failures_2d.extend(reroute[plane]['failures'])
    for rid in manual_ids:
        final_2d.pop(rid, None)
    log(f'[full] 2D: auto={len(final_2d)}, manual={len(manual_ids)}, '
        f'failed={len(failures_2d)}')

    # ---- 3D: manual fixed + crossing-lift L5-L15 for the auto routes -----
    records = {int(record['route_id']): record
               for record in payload['routes']}
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=NEW_DIR,
                                 heights=M.HEIGHTS, log=log)
    failed_ids = {item['route_id'] for item in failures_2d}
    for rid in failed_ids:
        lifter.routed.pop(int(rid), None)
    groups = []
    for group in lifter.groups:
        ids = [int(rid) for rid in group['route_ids']]
        if any(rid not in lifter.routed for rid in ids):
            continue
        groups.append(group)
    lifter.groups = groups
    lifter.group_by_id = {int(g['group_id']): g for g in groups}
    lifter.route_group = {}
    for group in groups:
        for phase, rid in enumerate(group['route_ids']):
            lifter.route_group[int(rid)] = (int(group['group_id']), phase)
    manual_groups = set()
    for rid in manual_ids:
        entry = lifter.route_group.get(int(rid))
        if entry is not None:
            manual_groups.add(int(entry[0]))
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    for rid, route in manual_routes.items():
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = [dict(primitive)
                                  for primitive in manual_prims[rid]]
        lifter.base_routes[rid] = LIFT.flat_route(rid, 'z1',
                                                  lifter.primitives[rid],
                                                  row=1)
    for rid, prims in final_2d.items():
        record = records[rid]
        plane = record['plane']
        flat = LIFT.flat_route(rid, plane, prims,
                               row=1 if plane == 'z1' else 2)
        lifter.world.add_route(flat)
        lifter.primitives[rid] = [dict(primitive) for primitive in prims]
        lifter.base_routes[rid] = flat
    for gid in manual_groups:
        lifter.group_plans[gid] = dict(group_id=int(gid),
                                       status='manual_fixed_group',
                                       note='manual U L1-L4 fixed')
    log(f'[full] 3D world: manual={len(manual_ids)}, auto={len(final_2d)}, '
        f'total={len(lifter.world.plan)}; manual groups={len(manual_groups)}')

    entries = lifter.final_flat_entries()
    crossings, reports, pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=True,
        primitives_by_id=lifter.primitives)
    lifter.crossings = crossings
    lifter.pair_set = set()
    for plane_pairs in pairs.values():
        lifter.pair_set |= plane_pairs
    lifter.high_pairs = lifter._added_pairs({})
    lifter._finalize_analysis()
    log(f'[full] after manual-first 2D: pairs={len(lifter.pair_set)} '
        f'({time.perf_counter() - started:.1f}s)')

    LIFT.LAYER_IDS = tuple(range(5, 16))
    log(f'[full] crossing-lift L5-L15 (budget {CROSSING_BUDGET_S:.0f}s)')
    history = lifter.optimize(max_groups=MAX_GROUPS,
                              time_limit=CROSSING_BUDGET_S, log=log)
    log(f'[full] optimizer lifted {len(history)} groups '
        f'({time.perf_counter() - started:.1f}s)')
    payload_out = lifter.build_payload()
    LIFT._write_json(NEW_DIR / 'routes_l3d.json', payload_out)
    LIFT._write_json(NEW_DIR / 'layer_stack.json', lifter.stack.to_dict())
    validation = LIFT.validate_payload_v4(payload_out, lifter.v4_root, log=log)
    repair_rounds = 0
    while not validation.get('exploratory_pass') and repair_rounds < 40:
        violations = validation.get('violations') or []
        offending = set()
        for item in violations:
            if item.get('category') != 'clearance_violations':
                continue
            for key in ('route_id', 'other_route'):
                value = item.get(key)
                if value is None:
                    continue
                entry = lifter.route_group.get(int(value))
                if entry is None:
                    continue
                gid = int(entry[0])
                if gid not in manual_groups:
                    offending.add(gid)
        if not offending:
            break
        lifter.revert_groups(offending, log=log)
        repair_rounds += 1
        payload_out = lifter.build_payload()
        LIFT._write_json(NEW_DIR / 'routes_l3d.json', payload_out)
        validation = LIFT.validate_payload_v4(payload_out, lifter.v4_root,
                                              log=log)
    log(f'[full] validation={validation.get("status")} '
        f'repair_rounds={repair_rounds}')

    entries = lifter.final_flat_entries()
    after_crossings, after_reports, after_pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=False)
    unique_pairs = set()
    for plane_pairs in after_pairs.values():
        unique_pairs |= plane_pairs
    after_records = [dict(z=float(value[0]), route_a=int(value[1]),
                          route_b=int(value[2]), x=float(value[3]),
                          y=float(value[4]), angle_deg=float(value[7]))
                     for value in after_crossings]
    LIFT._write_json(NEW_DIR / 'crossings_after.json', dict(
        count=len(after_records), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(key): value['crossing_pair_count']
                              for key, value in after_reports.items()},
        point_count_by_height={str(key): value['crossing_count']
                               for key, value in after_reports.items()},
        remaining_pairs=sorted(unique_pairs), crossings=after_records),
        indent=None)

    summary = lifter.summary(validation=validation,
                             after_reports=after_reports,
                             after_pairs_by_plane=after_pairs)
    routed_by_plane = Counter()
    for rid in lifter.routed:
        routed_by_plane[lifter.routed[rid]['plane']] += 1
    summary.update(
        schema='manual_first_full_campaign_topology_v1',
        layer_heights_mm={str(int(layer.layer_id)):
                          float(layer.physical_z_mm)
                          for layer in lifter.stack.routing_layers},
        remaining_unique_crossing_pairs=len(unique_pairs),
        crossing_pairs_after_by_plane={
            str(key): value['crossing_pair_count']
            for key, value in after_reports.items()},
        manual_fixed=dict(routes=len(manual_ids), groups=len(manual_groups),
                          all_kept=True),
        reroute=dict(z1_routed=len(reroute['z1']['routed']),
                     z1_failed=len(reroute['z1']['failures']),
                     z2_routed=len(reroute['z2']['routed']),
                     z2_failed=len(reroute['z2']['failures'])),
        failed_connections=failures_2d,
        routed_by_plane=dict(routed_by_plane),
        repair_rounds=repair_rounds,
        elapsed_seconds=round(time.perf_counter() - started, 1))
    LIFT._write_json(NEW_DIR / 'summary.json', summary, indent=1)
    LIFT._write_json(NEW_DIR / 'validation.json', validation, indent=1)
    LIFT._write_json(NEW_DIR / 'lift_plans.json', dict(
        lifted=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'lifted'],
        rejected=[plan for plan in lifter.group_plans.values()
                  if plan.get('status') == 'rejected'],
        reverted=[plan for plan in lifter.group_plans.values()
                  if plan.get('status') == 'reverted'],
        manual=[plan for plan in lifter.group_plans.values()
                if plan.get('status') == 'manual_fixed_group'],
        history=history), indent=1)
    try:
        figures = LIFT_RUN.plot_all(lifter, payload_out, summary,
                                    NEW_DIR / 'plots', log=log)
    except Exception as error:  # noqa: BLE001
        log(f'[full] plot_all skipped: {error}')

    baseline = M.baseline_metrics()
    result = dict(lifter=lifter, unique_pairs=unique_pairs,
                  after_records=after_records, history=history,
                  summary=summary)
    comparison, md = M.compare(baseline, result)
    log('')
    log(md)
    write_json(NEW_DIR / 'final_answer.json', dict(
        routed=summary.get('routed_after'),
        unique_pairs=len(unique_pairs),
        baseline=dict(routed=baseline['routed'],
                      unique_pairs=baseline['unique_pairs']),
        delta_pairs=comparison.get('delta_pairs'),
        delta_percent=comparison.get('delta_percent'),
        by_plane=comparison.get('manual', {}).get('by_plane'),
        by_bundle=comparison.get('manual', {}).get('by_bundle'),
        validation_counts=(summary.get('validation_counts')
                           if False else validation.get('counts')),
        routed_by_plane=dict(routed_by_plane),
        manual_kept=True,
        failures=len(failures_2d),
        elapsed_seconds=summary['elapsed_seconds']))
    log(f'[full] artifacts: {NEW_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
