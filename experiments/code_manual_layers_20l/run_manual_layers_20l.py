# -*- coding: utf-8 -*-
"""Run the deterministic L1-L20 manual layer scheme on the 1024 connections.

Output: outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L/
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))

import numpy as np

from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import manual_u_geometry as UGEOM
from four_side_1024.manual_c4_adapt.manual_layer_assignment_20l import (
    INTERFACE_Z, LAYER_HEIGHTS, build_assignment, write_assignment)
from four_side_1024.manual_c4_adapt.run_full_campaign import (
    CAMPAIGN_V4, CampaignState, load_manual_routes)
from four_side_1024.v2opt import search as SEARCH
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.v3c4 import lift_cross_run as LIFT_RUN
from four_side_1024.l3d.world import World

NEW_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_LAYERS_20L')
MANUAL_JSON = (ROOT / 'outputs/manual_c4_new_connectivity'
               / 'MANUAL_GROUP_15L_COMPARISON_FIXED/manual_first'
               / 'manual_isolated.json')
HEIGHTS_20 = [round(0.65 + 0.15 * index, 2) for index in range(19)]  # L2..L20


def log(message):
    print(message, flush=True)


def write_json(path, payload, indent=1):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False,
                                     indent=indent, default=str),
                          encoding='utf-8')


def layer_z(layer):
    if layer == 1:
        return 0.0
    return float(LAYER_HEIGHTS[layer])


def try_route_on_primitives(lifter, record, row, primitives, layer,
                            plan_limit=12):
    """Build the fixed-layer 3D route on the given 2D chain (if legal)."""
    layer_id = int(layer)
    target_z = layer_z(layer_id)
    base_z = 0.0 if row == 1 else 0.5
    plans = []
    for mode, limit in (('arms', plan_limit), ('any', max(8, plan_limit // 2))):
        plans.extend(M._window_candidates(primitives, layer_id, target_z,
                                          lifter, step_mm=0.5,
                                          plan_limit=limit, window_mode=mode))
    if not plans:
        return None, 'no_transition_window'
    last = None
    for plan in plans:
        route = LIFT.lift_route(record, row, layer_id, target_z,
                                plan['rise_start'], plan['fall_start'],
                                primitives)
        if route is None:
            last = 'lift_route_none'
            continue
        if lifter.world.check_structure(route):
            last = 'structure_invalid'
            continue
        violations = lifter.world.check_route(route, check_self=True)
        if violations:
            last = 'world:' + str(violations[0].get('kind'))
            continue
        lifter.world.add_route(route)
        lifter.lifted[record['route_id']] = route
        lifter.primitives[record['route_id']] = [dict(primitive)
                                                for primitive in primitives]
        lifter.base_routes[record['route_id']] = LIFT.flat_route(
            record['route_id'], record['plane'], primitives, row=row)
        return route, None
    return None, last or 'all_plans_conflict'


def alternative_primitives(record, plane_state, layer, lifter, limit=80):
    """Re-plan the XY main path (normal connections) so the transitions fit."""
    rid = int(record['route_id'])
    if record.get('relation') == 'same':
        return []
    frame = plane_state.frames.get(rid)
    if frame is None:
        return []
    oracle = plane_state.oracle_for(rid)
    target_z = layer_z(layer)
    footprint = float(LIFT.transition_geometry(abs(target_z
                                                   - INTERFACE_Z[record['plane']]))[
        'footprint_mm'])
    found = []
    for index, candidate in enumerate(SEARCH.candidates_for(frame, oracle)):
        if index >= limit:
            break
        try:
            prims = frame.to_world(candidate['primitives'])
        except Exception:  # noqa: BLE001
            continue
        windows = LIFT._straight_start_windows(prims, footprint,
                                              LIFT._paths().path_length(prims))
        if len(windows) >= 2:
            found.append(prims)
            if len(found) >= 3:
                break
    return found


def sample_flat_min_clearance(lifter, z_mm, route_ids):
    """Approximate minimum centre-line clearance among routes on one plane."""
    from scipy.spatial import cKDTree
    entries = lifter.world.planes.parts.get(round(float(z_mm), 9)) or {}
    points = []
    owners = []
    for part_id, primitives in entries.items():
        rid = int(part_id) // 1000
        if route_ids is not None and rid not in route_ids:
            continue
        array = UGEOM._sample_xy(primitives, sagitta=0.01)
        if array is None or len(array) < 2:
            continue
        points.append(array)
        owners.extend([rid] * len(array))
    if not points:
        return None
    points = np.vstack(points)
    owners = np.asarray(owners)
    tree = cKDTree(points)
    best = None
    for index, owner in enumerate(owners):
        distances, indices = tree.query(points[index], k=min(8, len(points)))
        for distance, other in zip(np.atleast_1d(distances),
                                   np.atleast_1d(indices)):
            if owners[other] != owner:
                if best is None or distance < best:
                    best = float(distance)
                break
    return None if best is None else round(best, 4)


def main():
    started = time.perf_counter()
    NEW_DIR.mkdir(parents=True, exist_ok=True)
    M.install_extended_stack_builder()
    from four_side_1024.r15 import profile_r15
    profile_r15.apply()
    log('[20L] R15 profile applied')

    payload = json.loads((CAMPAIGN_V4 / 'routes_1024.json')
                         .read_text(encoding='utf-8'))
    records = {int(record['route_id']): record for record in payload['routes']}
    frozen = {rid: [dict(primitive) for primitive in record['primitives']]
              for rid, record in records.items()
              if record.get('status') == 'routed'
              and record.get('primitives')}
    manual_routes, manual_prims = load_manual_routes()
    fake_connections = {rid: dict(layer=(1 if abs(float(route['parts'][0]['z_mm'])) < 1e-9
                                         else None))
                        for rid, route in manual_routes.items()}
    # exact manual layers from the isolated phase
    manual_rows = json.loads(MANUAL_JSON.read_text(encoding='utf-8'))['results']
    manual_connections = {}
    for rid_text, row in manual_rows.items():
        rid = int(rid_text)
        if row.get('failed'):
            continue
        connection = M.load_manual_connections()[rid]
        manual_connections[rid] = dict(layer=int(row['layer']),
                                       connection=connection)
    rows, audit = build_assignment(payload, manual_connections)
    write_assignment(NEW_DIR, rows, audit)
    log(f'[20L] assignment audit: {audit["by_kind"]}')
    log(f'[20L] by layer: { {k: v for k, v in audit["by_layer"].items() if v} }')
    log(f'[20L] dual-endpoint conflicts: {len(audit["dual_conflicts"])}')

    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=NEW_DIR,
                                 heights=HEIGHTS_20, log=log)
    # rebuild the world with only the fixed manual U's first
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
                                                  lifter.primitives[rid], row=1)
    log(f'[20L] fixed manual routes in world: {len(lifter.world.plan)}')

    plane_states = {'z1': CampaignState(payload, 'z1', log=log),
                    'z2': CampaignState(payload, 'z2', log=log)}
    results = OrderedDict()
    failures = []

    def record_result(rid, layer, kind, route, reason=None):
        results[rid] = dict(route_id=rid, layer=layer, kind=kind,
                            ok=route is not None, reason=reason)
        if route is None:
            failures.append(dict(route_id=rid, layer=layer, kind=kind,
                                 reason=reason))

    def build_fixed(row, plane, layer, kind):
        rid = int(row['route_id'])
        record = records[rid]
        row_index = 1 if plane == 'z1' else 2
        attempts = []
        prims = frozen.get(rid)
        if prims:
            attempts.append(prims)
        route, reason = (None, 'no_2d_geometry')
        for primitives in attempts:
            route, reason = try_route_on_primitives(
                lifter, record, row_index, primitives, layer)
            if route is not None:
                return route, None
        # re-plan the XY main path if the frozen path has no transition room
        if plane != 'z1':
            return None, reason or 'fixed_layer_unroutable'
        for primitives in alternative_primitives(record, plane_states[plane],
                                                 layer, lifter):
            route, reason = try_route_on_primitives(
                lifter, record, row_index, primitives, layer)
            if route is not None:
                return route, None
        return None, reason or 'fixed_layer_unroutable'

    # ---- 1. Z2 interface-plane routes (mandatory: stay on z=0.5) ----------
    lifter._refresh_plane_cache()
    interface_rows = [row for row in rows
                      if row['layer'] is None and row['plane'] == 'z2']
    log(f'[20L] Z2 interface-plane connections: {len(interface_rows)}')
    for row in interface_rows:
        rid = int(row['route_id'])
        prims = frozen.get(rid)
        if prims is None:
            record_result(rid, None, row['kind'], None, 'no_frozen_2d_geometry')
            continue
        flat = LIFT.flat_route(rid, 'z2', prims, row=2)
        if lifter.world.check_route(flat, check_self=True):
            record_result(rid, None, row['kind'], None, 'interface_conflict')
            continue
        lifter.world.add_route(flat)
        lifter.base_routes[rid] = flat
        lifter.primitives[rid] = [dict(primitive) for primitive in prims]
        record_result(rid, None, row['kind'], flat)

    # ---- 2. Z2 fixed high-layer connections ------------------------------
    fixed_z2 = [row for row in rows
                if row['plane'] == 'z2' and row['layer'] is not None]
    fixed_z2.sort(key=lambda row: (row['layer'], row['route_id']))
    log(f'[20L] Z2 fixed-layer connections: {len(fixed_z2)}')
    current_layer = None
    layer_counts = Counter()
    for row in fixed_z2:
        if row['layer'] != current_layer:
            current_layer = row['layer']
            lifter._refresh_plane_cache()
            log(f'[20L] Z2 layer L{current_layer} '
                f'({layer_counts[current_layer]} already attempted)')
        route = build_fixed(row, 'z2', row['layer'], row['kind'])
        if route is not None:
            layer_counts[row['layer']] += 1
        record_result(int(row['route_id']), row['layer'], row['kind'], route)
        if len(layer_counts) and sum(layer_counts.values()) % 16 == 0:
            log(f'[20L] z2 fixed progress: {sum(layer_counts.values())} ok '
                f'({time.perf_counter() - started:.1f}s)')

    # ---- 3. Z1 fixed L6 / L7 --------------------------------------------
    for layer in (6, 7):
        z1_rows = [row for row in rows
                   if row['plane'] == 'z1' and row['layer'] == layer]
        lifter._refresh_plane_cache()
        log(f'[20L] Z1 layer L{layer}: {len(z1_rows)} connections')
        for index, row in enumerate(z1_rows, 1):
            try:
                route, reason = build_fixed(row, 'z1', layer, row['kind'])
            except Exception as error:  # noqa: BLE001
                route, reason = None, 'exception:' + type(error).__name__
            if index % 16 == 0:
                log(f'[20L] z1 L{layer} progress: {index}/{len(z1_rows)} '
                    f'({time.perf_counter() - started:.1f}s)')
            record_result(int(row['route_id']), layer, row['kind'], route,
                          reason)

    ok = sum(1 for item in results.values() if item['ok'])
    log(f'[20L] routed after fixed-layer construction: {ok}/{len(results)} '
        f'({time.perf_counter() - started:.1f}s)')

    # ---- 4. assemble payload + validate + crossings ----------------------
    accepted = {rid: item for rid, item in results.items() if item['ok']}
    for rid, route in manual_routes.items():
        accepted[rid] = dict(route_id=rid,
                             layer=manual_connections[rid]['layer'],
                             kind='manual_u', ok=True, reason=None)
    lifter.routed = {}
    lifter.row = {}
    for rid in manual_routes:
        lifter.routed[rid] = records[rid]
        lifter.row[rid] = 1
    for rid, item in accepted.items():
        record = records[rid]
        lifter.routed[rid] = record
        lifter.row[rid] = 1 if record['plane'] == 'z1' else 2
    for rid in lifter.base_routes:
        if rid in manual_routes:
            continue
        if rid not in accepted:
            lifter.base_routes.pop(rid, None)
            lifter.primitives.pop(rid, None)
    for rid in list(lifter.lifted):
        if rid not in accepted and rid not in manual_routes:
            lifter.lifted.pop(rid, None)
    # rebuild the world to contain only accepted routes
    plan = {}
    for rid in accepted:
        plan[rid] = lifter.lifted.get(rid) or lifter.base_routes[rid]
    for rid in manual_routes:
        plan[rid] = manual_routes[rid]
    lifter.world.rebuild(plan)
    # records status for the payload
    for rid, record in records.items():
        if rid in accepted or rid in manual_routes:
            record['status'] = 'routed'
            record.pop('reason', None)
        else:
            record['status'] = 'failed'
            record['reason'] = 'manual_layer_unrouted'
    entries = lifter.final_flat_entries()
    crossings, reports, pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=False)
    unique_pairs = set()
    for plane_pairs in pairs.values():
        unique_pairs |= plane_pairs
    after_records = [dict(z=float(value[0]), route_a=int(value[1]),
                          route_b=int(value[2]), x=float(value[3]),
                          y=float(value[4]), angle_deg=float(value[7]))
                     for value in crossings]
    LIFT._write_json(NEW_DIR / 'crossings_after.json', dict(
        count=len(after_records), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(key): value['crossing_pair_count']
                              for key, value in reports.items()},
        point_count_by_height={str(key): value['crossing_count']
                               for key, value in reports.items()},
        remaining_pairs=sorted(unique_pairs), crossings=after_records),
        indent=None)
    payload_out = lifter.build_payload()
    LIFT._write_json(NEW_DIR / 'routes_l3d.json', payload_out)
    validation = LIFT.validate_payload_v4(payload_out, lifter.v4_root, log=log)

    # ---- 5. per-layer statistics + plots -------------------------------
    stats = {}
    layer_route_ids = {}
    for row in rows:
        layer = row['layer']
        stats_key = str(layer) if layer is not None else 'interface_z2'
        layer_route_ids.setdefault(stats_key, []).append(int(row['route_id']))
    for key, ids in layer_route_ids.items():
        succeeded = [rid for rid in ids if rid in accepted]
        z_mm = 0.5 if key == 'interface_z2' else layer_z(int(key))
        stats[key] = dict(
            assigned=len(ids), routed=len(succeeded),
            failed=len(ids) - len(succeeded),
            z_mm=z_mm,
            transitions=sum(1 for rid in succeeded
                            if (lifter.lifted.get(rid) or {}).get(
                                'n_transitions')),
            crossings=(reports.get(round(z_mm, 9), {}).get(
                'crossing_pair_count')),
            min_clearance_mm=sample_flat_min_clearance(lifter, z_mm,
                                                       set(succeeded)),
            failures=[dict(route_id=rid,
                           reason=results[rid].get('reason'))
                      for rid in ids if rid not in accepted],
        )
    summary = dict(
        schema='manual_layers_20l_v1',
        routed=len(accepted),
        routed_detail=len(accepted) - len(manual_routes),
        total=1024,
        manual_routes=len(manual_routes),
        manual_kept=sum(1 for rid in manual_routes if rid in accepted),
        assignment_audit=audit,
        layer_stats=stats,
        crossings=len(unique_pairs),
        crossing_pairs_by_height={str(key): value['crossing_pair_count']
                                  for key, value in reports.items()},
        validation_status=validation.get('status'),
        validation_counts=dict(validation.get('counts') or {}),
        failures=failures,
        routed_by_plane=dict(Counter(records[rid]['plane']
                                     for rid in lifter.routed)),
        elapsed_seconds=round(time.perf_counter() - started, 1),
    )
    write_json(NEW_DIR / 'summary.json', summary)
    write_json(NEW_DIR / 'validation.json', validation)
    write_json(NEW_DIR / 'layer_stats.json', stats)
    log(f'[20L] DONE: routed={summary["routed"]}/1024, '
        f'crossings={summary["crossings"]}, '
        f'validation={validation.get("status")} '
        f'({time.perf_counter() - started:.1f}s)')
    for key in ('1', '2', '3', '4', '6', '7', '8', '9', '10', '11', '12',
                '13', '14', '15', '16', '17', '18', '19', 'interface_z2'):
        if key in stats:
            item = stats[key]
            log(f'[20L] {key}: assigned={item["assigned"]} '
                f'routed={item["routed"]} failed={item["failed"]} '
                f'z={item["z_mm"]} crossings={item["crossings"]} '
                f'min_clearance={item["min_clearance_mm"]}')
    log(f'[20L] artifacts: {NEW_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
