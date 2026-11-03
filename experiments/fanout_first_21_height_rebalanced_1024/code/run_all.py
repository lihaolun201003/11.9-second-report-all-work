# -*- coding: utf-8 -*-
"""Experiment A-E driver and joint repair loop of the Fanout-First 1024 system.

Stages
------
A  data verification + 1024 assignment (delegated to verify.py / assign.py)
B  R15 3D fanout of the 368 manual-U routes (experiment B)
C  layer-wise 2D routing of the 8 manual layers L2-L5/L10-L13 (experiment C)
D  R15 3D fanout of all 1024 routes with the manual transitions fixed (experiment D)
E  layer-wise 2D routing of all 18 layers + assembly + strict 3D world check +
   joint repair iterations (experiment E), then final artifacts.

The driver never invents a success: a route is counted only when its assembled
3D route passes the strict 0.05 mm world check.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import traceback
from collections import Counter, OrderedDict
from pathlib import Path

from . import common as C
from . import assemble as ASM

MANUAL_ROLES = ('z1_manual_u', 'z2_manual_u')
MANUAL_LAYERS = (2, 3, 4, 5, 10, 11, 12, 13)


# ---------------------------------------------------------------- utilities
def _ensure_run_dir():
    C.RUN_DIR.mkdir(parents=True, exist_ok=True)


def make_logger():
    _ensure_run_dir()
    log_path = C.RUN_DIR / 'run.log'

    def log(message):
        line = time.strftime('%H:%M:%S') + ' ' + str(message)
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


def _as_bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'y')


def read_assignment(path=None):
    path = Path(path or (C.RUN_DIR / 'assignment_1024.csv'))
    if not path.is_file():
        raise FileNotFoundError(f'assignment table missing: {path}')
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1024:
        raise ValueError(f'assignment must have 1024 rows, got {len(rows)}')
    converted = []
    for row in rows:
        record = dict(row)
        for key in ('route_id', 'target_layer', 'source_row', 'target_row'):
            record[key] = int(float(record[key]))
        for key in ('target_z_mm', 'interface_z_mm', 'source_x_mm',
                    'source_y_mm', 'target_x_mm', 'target_y_mm'):
            if key in record and record[key] not in (None, ''):
                record[key] = float(record[key])
        for key in ('source_side', 'target_side', 'plane', 'manual_group',
                    'manual_pattern', 'layer_role', 'source_endpoint',
                    'target_endpoint', 'source_connector', 'target_connector',
                    'direction', 'relation'):
            if key in record and record[key] is None:
                record[key] = ''
        converted.append(record)
    ids = {row['route_id'] for row in converted}
    if len(ids) != 1024:
        raise ValueError('assignment route ids are not unique')
    converted.sort(key=lambda row: row['route_id'])
    return converted


def _json_write(path, obj):
    C.write_json(path, obj)


def _load_fanout():
    from . import fanout
    return fanout


def _load_layer2d():
    from . import layer2d
    return layer2d


def _rows_by_layer(rows, manual_only=False):
    by_layer = OrderedDict()
    for row in rows:
        if manual_only and row['layer_role'] not in MANUAL_ROLES:
            continue
        by_layer.setdefault(int(row['target_layer']), []).append(row)
    return by_layer


# ---------------------------------------------------------------- stage A
def stage_a(force=False, log=print):
    log('=== STAGE A: data verification + 1024 assignment ===')
    from . import verify, assign
    if force or not (C.RUN_DIR / 'input_excel_audit.json').is_file():
        verify.main()
    if force or not (C.RUN_DIR / 'assignment_1024.csv').is_file():
        assign.main()
    rows = read_assignment()
    planes = Counter(row['plane'] for row in rows)
    roles = Counter(row['layer_role'] for row in rows)
    if planes != Counter({'z1': 512, 'z2': 512}):
        raise ValueError(f'plane split wrong: {planes}')
    log(f'stage A ok: {len(rows)} rows, planes={dict(planes)}, roles={dict(roles)}')
    return rows


# ---------------------------------------------------------------- fanout adapters
def _normalize_fanout_artifacts(fanout_mod, result, experiment_name, out_dir,
                                log):
    """Write fanout artifacts defensively across the small API surface."""
    try:
        fanout_mod.write_artifacts(result, out_dir,
                                   experiment_name=experiment_name)
        log(f'wrote fanout artifacts -> {out_dir} ({experiment_name})')
    except TypeError:
        fanout_mod.write_artifacts(result, out_dir)
        log('wrote fanout artifacts (default experiment dir)')


def _selected_or_fail(result):
    selected = result.get('selected') or {}
    failures = list(result.get('failures') or [])
    return selected, failures


def _endpoint_failure_rows(failures, rows):
    """Expand endpoint failures to route-level failure records."""
    by_route = {}
    for failure in failures:
        rid = int(failure.get('route_id', -1))
        record = by_route.setdefault(rid, dict(route_id=rid, roles=[],
                                               reasons=[], blockers=[]))
        record['roles'].append(failure.get('endpoint_role')
                               or failure.get('role') or 'unknown')
        reason = failure.get('reason') or 'fanout_failed'
        record['reasons'].append(str(reason))
        blockers = failure.get('blockers') or []
        record['blockers'].extend(int(v) for v in blockers
                                  if str(v).lstrip('-').isdigit())
    pending = [row for row in rows if row['route_id'] in by_route]
    records = []
    for row in pending:
        base = by_route[row['route_id']]
        records.append(dict(
            route_id=row['route_id'], plane=row['plane'],
            target_layer=row['target_layer'],
            manual_group=row.get('manual_group') or '',
            reason='fanout_incomplete:' + '+'.join(sorted(set(base['reasons']))),
            endpoint_roles=base['roles'],
            blockers=sorted(set(base['blockers'])),
        ))
    return records


def _fanout_stage(rows, stage_name, out_dir, experiment_name, fixed=None,
                  repair_ids=None, log=print):
    fanout_mod = _load_fanout()
    started = time.time()
    result = fanout_mod.plan_fanout(rows, stack=C.layer_stack(), fixed=fixed,
                                    repair_ids=repair_ids, log=log)
    selected, failures = _selected_or_fail(result)
    route_failures = _endpoint_failure_rows(failures, rows)
    manual_rows = [row for row in rows
                   if row['layer_role'] in MANUAL_ROLES]
    manual_selected = {rid: value for rid, value in selected.items()
                       if rid in {row['route_id'] for row in manual_rows}}
    stats = dict(
        stage=stage_name,
        input_routes=len(rows),
        routes_with_both_transitions=len(
            [rid for rid in selected
             if selected[rid].get('source') and selected[rid].get('target')]),
        routes_with_incomplete_transitions=len(rows) - len(selected),
        failed_routes=len(route_failures),
        manual_group_transitions=len(manual_selected),
        endpoint_failures=len(failures),
        elapsed_seconds=round(time.time() - started, 1),
        fanout_stats=result.get('stats'),
    )
    stats['validation'] = _validate_fanout_selected(fanout_mod, selected,
                                                    rows, log=log)
    _json_write(out_dir / 'summary.json', stats)
    _json_write(out_dir / 'failed_routes.json',
                dict(total=len(route_failures), failures=route_failures))
    _json_write(C.RUN_DIR / 'checkpoints' / f'{stage_name}_fanout.json', stats)
    _normalize_fanout_artifacts(fanout_mod, result, experiment_name,
                                C.RUN_DIR, log)
    log(f'{stage_name}: routes={len(rows)} complete={stats["routes_with_both_transitions"]} '
        f'failed={stats["failed_routes"]} '
        f'fanout_validation={stats["validation"]} '
        f'({stats["elapsed_seconds"]}s)')
    return result, stats, route_failures


def _validate_fanout_selected(fanout_mod, selected, rows=None, log=print):
    """Independent re-check of the selected transitions (fresh 3D world)."""
    from ..fslw import geom
    from ..l3d.world import World
    from . import common as C

    row_by_id = {int(row['route_id']): row for row in (rows or [])}
    eps = C.endpoints()
    world = World(C.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
    violations = []
    transition_count = 0
    min_radius = None
    for rid in sorted(selected):
        record = selected[rid]
        row = row_by_id.get(int(rid))
        for role in ('source', 'target'):
            payload = record.get(role)
            if not payload:
                violations.append(dict(route_id=rid, role=role,
                                       kind='missing_transition'))
                continue
            transition_count += 1
            radius = float(payload.get('radius_mm', 0.0))
            min_radius = radius if min_radius is None else min(min_radius, radius)
            if abs(radius - C.MIN_BEND_RADIUS_MM) > 1e-6:
                violations.append(dict(route_id=rid, role=role,
                                       kind='radius_not_15',
                                       radius_mm=radius))
            transition = dict(payload['transition'])
            transition['kind'] = 'transition'
            z0 = float(payload.get('z0', 0.0))
            interface_z = C.interface_z(row['plane']) if row is not None else z0
            parts = []
            if row is not None:
                endpoint = (row['source_endpoint'] if role == 'source'
                            else row['target_endpoint'])
                port_xy = tuple(float(v) for v in eps[endpoint]['routing_xy'])
                start_xy = tuple(float(v) for v in payload['start_xy'])
                lead = math.hypot(start_xy[0] - port_xy[0],
                                  start_xy[1] - port_xy[1])
                if lead > 1e-9:
                    if role == 'source':
                        parts.append(dict(
                            kind='flat', layer_id=1, z_mm=interface_z,
                            length_mm=lead,
                            primitives=[geom.line(port_xy, start_xy)]))
                    else:
                        parts.append(dict(
                            kind='flat', layer_id=1, z_mm=interface_z,
                            length_mm=lead,
                            primitives=[geom.line(start_xy, port_xy)]))
            if role == 'source':
                parts.append(transition)
            else:
                reverse = dict(payload['reverse_transition'])
                reverse['kind'] = 'transition'
                parts.insert(0, reverse)
            partial = dict(route_id=rid * 2 + (0 if role == 'source' else 1),
                           plane=(row['plane'] if row is not None else 'z1'),
                           parts=parts,
                           start_z_mm=z0,
                           end_z_mm=(float(transition['z1'])
                                     if role == 'source' else z0))
            found = world.check_route(partial, check_self=False)
            for item in found:
                violations.append(dict(item, route_id=rid, role=role))
            if found:
                continue
            try:
                world.add_route(partial)
            except Exception as error:  # noqa: BLE001
                violations.append(dict(route_id=rid, role=role,
                                       kind='world_add_error',
                                       detail=repr(error)))
    kinds = Counter(item.get('kind') for item in violations)
    return dict(ok=not violations, transition_count=transition_count,
                endpoints_expected=2 * len(selected),
                violations=len(violations),
                violation_kinds=dict(kinds),
                min_radius_mm=min_radius,
                examples=violations[:10])


# ---------------------------------------------------------------- layer tasks
def _build_layer_tasks(rows, selected, extra_obstacles=None, log=print):
    fanout_mod = _load_fanout()
    landings = fanout_mod.landings(selected)
    extra_obstacles = extra_obstacles or {}
    layers = OrderedDict()
    for row in rows:
        rid = row['route_id']
        layer = int(row['target_layer'])
        entry = layers.setdefault(layer, dict(
            layer_id=layer, z_mm=C.layer_z(layer), tasks=[], obstacles=[]))
        pose = landings.get(rid)
        if pose is None:
            continue
        entry['tasks'].append(dict(
            route_id=rid, manual_group=row.get('manual_group') or '',
            relation=row.get('relation') or '',
            source_side=row.get('source_side'), target_side=row.get('target_side'),
            A=tuple(pose['A']), dA=tuple(pose['dA']),
            B=tuple(pose['B']), dB=tuple(pose['dB']),
        ))
    for layer, entry in layers.items():
        entry['obstacles'] = list(entry['obstacles']) + list(
            fanout_mod.layer_obstacles(selected, layer))
        entry['obstacles'].extend(extra_obstacles.get(layer, []))
    return layers


# ---------------------------------------------------------------- 2D stage
def _normalize_layer_result(result):
    """Return ``{layer_id: {'routed':..., 'failed':..., 'stats':...}}``."""
    if result is None:
        return {}
    if isinstance(result, dict) and 'layers' in result:
        layers = result['layers']
    elif isinstance(result, dict) and all(
            str(key).lstrip('-').isdigit() for key in result):
        layers = result
    else:
        raise ValueError('unexpected layer2d result shape')
    normalized = {}
    for key, value in layers.items():
        if not isinstance(value, dict):
            raise ValueError(f'unexpected layer payload for {key}')
        normalized[int(key)] = dict(
            routed=value.get('routed') or {},
            failed=list(value.get('failed') or []),
            stats=value.get('stats') or {},
            z_mm=value.get('z_mm'),
        )
    return normalized


def _route_layers(rows, selected, extra_obstacles=None, ordering_seed=0,
                  budget=600, log=print):
    layer2d_mod = _load_layer2d()
    layers = _build_layer_tasks(rows, selected, extra_obstacles, log=log)
    started = time.time()
    try:
        result = layer2d_mod.route_all_layers(
            layers, out_dir=None, log=log, ordering_seed=ordering_seed,
            budget=budget)
    except TypeError:
        result = layer2d_mod.route_all_layers(layers, out_dir=None, log=log)
    normalized = _normalize_layer_result(result)
    elapsed = time.time() - started
    reconciled = _reconcile_layer_failures(layers, normalized)
    routed_total = sum(len(value['routed']) for value in normalized.values())
    failed_total = sum(len(value) for value in reconciled.values())
    log(f'[layer2d] layers={len(normalized)} routed={routed_total} '
        f'failed={failed_total} ({elapsed:.1f}s)')
    for layer in normalized:
        if layer in reconciled:
            normalized[layer]['failed'] = reconciled[layer]
    return normalized, result


def _reconcile_layer_failures(layers, normalized):
    """Rebuild each layer's failure list from assigned tasks minus routed ids.

    The layer router keeps a historical failure list across rip-up rounds; a
    route that was recovered later can therefore still appear there.  Only
    routes that are really unrouted at the end count as failures.
    """
    reconciled = {}
    for layer, tasks in (layers or {}).items():
        entry = normalized.get(int(layer))
        if entry is None:
            continue
        routed_ids = {int(rid) for rid in entry['routed']}
        historical = {}
        for record in entry['failed']:
            historical.setdefault(int(record.get('route_id', -1)), record)
        failures = []
        for task in tasks.get('tasks', []):
            rid = int(task['route_id'])
            if rid in routed_ids:
                continue
            record = dict(historical.get(rid) or {})
            record.setdefault('route_id', rid)
            record.setdefault('reason', 'layer2d_unrouted')
            failures.append(record)
        reconciled[int(layer)] = failures
    return reconciled


# ---------------------------------------------------------------- assembly
def _assemble_all(rows, selected, routed, log=print):
    routes = []
    failures = []
    for row in rows:
        rid = row['route_id']
        entry = routed.get(int(row['target_layer']))
        body = None
        if entry is not None:
            payload = entry['routed'].get(rid) or entry['routed'].get(str(rid))
            if payload is not None:
                body = payload.get('primitives') if isinstance(payload, dict) \
                    else payload
        if rid not in selected or not selected[rid].get('source') \
                or not selected[rid].get('target'):
            failures.append(dict(route_id=rid, plane=row.get('plane'),
                                 target_layer=row['target_layer'],
                                 manual_group=row.get('manual_group') or '',
                                 reason='fanout_incomplete'))
            continue
        if body is None:
            layer_failure = {}
            if entry is not None:
                for record in entry['failed']:
                    if int(record.get('route_id', -1)) == rid:
                        layer_failure = record
                        break
            failures.append(dict(route_id=rid, plane=row.get('plane'),
                                 target_layer=row['target_layer'],
                                 manual_group=row.get('manual_group') or '',
                                 reason='layer2d_failed:' + str(
                                     layer_failure.get('reason')
                                     or 'no_body'),
                                 detail=layer_failure))
            continue
        try:
            route = ASM.assemble_route(row, selected[rid]['source'],
                                       selected[rid]['target'], body)
        except ASM.AssemblyError as error:
            failures.append(dict(route_id=rid, plane=row.get('plane'),
                                 target_layer=row['target_layer'],
                                 manual_group=row.get('manual_group') or '',
                                 reason='assembly:' + error.reason,
                                 detail=dict(error.detail)))
            continue
        routes.append(route)
    return routes, failures


def _world_check(routes):
    check = ASM.validate_routes_independent(routes)
    return check


def _violation_obstacles(violations, routes_by_id):
    """Turn world violations into extra transition-obstacle samples for repair."""
    extra = {}
    for record in violations:
        rid = int(record.get('route_id', -1))
        route = routes_by_id.get(rid)
        if route is None:
            continue
        layer = int(route['target_layer'])
        kind = record.get('kind')
        if kind not in ('transition_vs_flat', 'flat_vs_transition'):
            continue
        point = record.get('point')
        if point and len(point) >= 3:
            extra.setdefault(layer, []).append(dict(
                x=float(point[0]), y=float(point[1]), z=float(point[2]),
                route_id=rid, role='violation'))
    return extra


def _merge_failures(fanout_failures, assembly_failures, violation_route_ids):
    merged = {}
    for record in assembly_failures:
        merged[int(record['route_id'])] = dict(record)
    for record in fanout_failures:
        merged.setdefault(int(record['route_id']), dict(record))
    for rid in violation_route_ids:
        merged.setdefault(int(rid), dict(route_id=int(rid),
                                         reason='world_violation'))
    return [merged[rid] for rid in sorted(merged)]


# ---------------------------------------------------------------- local repair
def _transition_record(row, role, lead):
    """Build a fanout-compatible transition record for one endpoint + lead."""
    from ..fsd25d import path3d as P3
    from . import common as C

    eps = C.endpoints()
    endpoint = row['source_endpoint'] if role == 'source' else row['target_endpoint']
    ep = eps[endpoint]
    p = (float(ep['routing_xy'][0]), float(ep['routing_xy'][1]))
    d = (float(ep['inward'][0]), float(ep['inward'][1]))
    z0 = C.interface_z(row['plane'])
    zt = float(row['target_z_mm'])
    lead = float(lead)
    Q = (p[0] + d[0] * lead, p[1] + d[1] * lead)
    forward = P3.make_transition(Q, d, z0, zt, radius=C.MIN_BEND_RADIUS_MM)
    A = tuple(float(v) for v in forward['end'])
    reverse = P3.make_transition(A, (-d[0], -d[1]), zt, z0,
                                 radius=C.MIN_BEND_RADIUS_MM)
    record = dict(
        route_id=int(row['route_id']), endpoint_role=role,
        endpoint_id=endpoint, lead_mm=lead,
        start_xy=[Q[0], Q[1]], end_xy=[A[0], A[1]],
        start_xyz=[Q[0], Q[1], z0], end_xyz=[A[0], A[1], zt],
        direction=[d[0], d[1]], z0=z0, z1=zt,
        target_layer=int(row['target_layer']), target_z_mm=zt,
        footprint_mm=float(forward['footprint_mm']),
        length_mm=float(forward['length_mm']),
        theta_rad=float(forward['theta_rad']),
        radius_mm=float(C.MIN_BEND_RADIUS_MM),
        geometry='two_arc_S', needs_transition=abs(zt - z0) > 1e-12,
        transition=dict(forward, kind='transition'),
        reverse_transition=dict(reverse, kind='transition'),
    )
    return record


def _body_primitives(route):
    """The target-layer flat part of an assembled route."""
    target_layer = int(route['target_layer'])
    for part in route.get('parts') or []:
        if part['kind'] == 'flat' and int(part.get('layer_id', -1)) == target_layer:
            return [dict(prim) for prim in part['primitives']]
    return None


def _build_frozen_world(valid, log=print):
    from ..l3d.world import World
    world = World(C.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
    bodies = {}
    for rid in sorted(valid):
        route = valid[rid]
        world.add_route(route)
        body = _body_primitives(route)
        if body is None:
            raise RuntimeError(f'frozen route {rid} has no body flat part')
        bodies.setdefault(int(route['target_layer']), {})[int(rid)] = body
    log(f'[local-repair] frozen world: {len(valid)} routes, '
        f'bodies on {len(bodies)} layers')
    return world, bodies


def _partial_route(record, row, world_id):
    from ..fslw import geom
    from . import common as C

    eps = C.endpoints()
    interface_z = C.interface_z(row['plane'])
    parts = []
    if record['endpoint_role'] == 'source':
        p = tuple(float(v) for v in eps[record['endpoint_id']]['routing_xy'])
        Q = tuple(float(v) for v in record['start_xy'])
        lead = math.hypot(Q[0] - p[0], Q[1] - p[1])
        if lead > 1e-9:
            parts.append(dict(kind='flat', layer_id=1, z_mm=interface_z,
                              length_mm=lead,
                              primitives=[geom.line(p, Q)]))
        parts.append(dict(record['transition'], kind='transition'))
    else:
        p = tuple(float(v) for v in eps[record['endpoint_id']]['routing_xy'])
        Q = tuple(float(v) for v in record['start_xy'])
        lead = math.hypot(Q[0] - p[0], Q[1] - p[1])
        parts.append(dict(record['reverse_transition'], kind='transition'))
        if lead > 1e-9:
            parts.append(dict(kind='flat', layer_id=1, z_mm=interface_z,
                              length_mm=lead,
                              primitives=[geom.line(Q, p)]))
    return dict(route_id=int(world_id), plane=row['plane'], parts=parts,
                start_z_mm=interface_z, end_z_mm=interface_z)


def _attempt_local_route(row, world, frozen_bodies, obstacles, layer2d_mod,
                         lead_variants, budget=1500, log=print):
    """Try to insert one failed route into the frozen layout."""
    from . import common as C

    rid = int(row['route_id'])
    layer = int(row['target_layer'])
    z = C.layer_z(layer)
    body_initial = dict(frozen_bodies.get(layer, {}))
    body_initial.pop(rid, None)
    layer_obstacles = [item for item in obstacles if item.get('route_id') != rid]
    last_detail = None
    for (lead_s, lead_t) in lead_variants:
        try:
            src = _transition_record(row, 'source', lead_s)
            tgt = _transition_record(row, 'target', lead_t)
        except Exception:  # noqa: BLE001
            continue
        source_partial = _partial_route(src, row, 2 * rid)
        target_partial = _partial_route(tgt, row, 2 * rid + 1)
        if world.check_route(source_partial, check_self=False):
            continue
        if world.check_route(target_partial, check_self=False):
            continue
        task = dict(
            route_id=rid, manual_group=row.get('manual_group') or '',
            relation=row.get('relation') or '',
            source_side=row.get('source_side'),
            target_side=row.get('target_side'),
            A=tuple(src['end_xy']), dA=tuple(src['direction']),
            B=tuple(tgt['end_xy']), dB=tuple(tgt['direction']),
        )
        try:
            result = layer2d_mod.route_layer(
                layer, z, [task], obstacles=layer_obstacles,
                initial_routes=body_initial, budget=budget, rr_rounds=0,
                log=lambda *_a: None)
        except TypeError:
            result = layer2d_mod.route_layer(
                layer, z, [task], obstacles=layer_obstacles,
                budget=budget, rr_rounds=0, log=lambda *_a: None)
        entry = result.get('routed') or {}
        payload = entry.get(rid) or entry.get(str(rid))
        if payload is None:
            for record in (result.get('failed') or []):
                if int(record.get('route_id', -1)) == rid:
                    last_detail = record
                    break
            continue
        body = payload.get('primitives') if isinstance(payload, dict) else payload
        try:
            route = ASM.assemble_route(row, src, tgt, body)
        except ASM.AssemblyError:
            continue
        violations = world.check_route(route)
        if violations:
            continue
        world.add_route(route)
        frozen_bodies.setdefault(layer, {})[rid] = [dict(p) for p in body]
        return dict(route=route, source=src, target=tgt, body=body), None, last_detail
    return None, 'local_repair_failed', last_detail


def _local_repair(rows, selected, best, log=print, max_rounds=2):
    """Fit the failed routes into the frozen valid layout (rip-up free)."""
    from ..l3d.world import World
    from . import common as C

    valid = dict(best['valid'])
    routed = {int(layer): dict(value) for layer, value in best['routed'].items()}
    failed_rows = [row for row in rows if int(row['route_id']) not in valid]
    if not failed_rows:
        return dict(valid=valid, routed=routed, repaired={}, failures=[],
                    rounds=[], world=World(C.layer_stack(),
                                           clearance=C.MIN_3D_CLEARANCE_MM))
    log(f'[local-repair] attempting {len(failed_rows)} failed routes')
    world, frozen_bodies = _build_frozen_world(valid, log=log)
    fanout_mod = _load_fanout()
    layer2d_mod = _load_layer2d()
    all_obstacles = {}
    for layer in C.ROUTING_LAYER_IDS:
        all_obstacles[layer] = fanout_mod.layer_obstacles(selected, layer)
    flat_obstacles = [item for items in all_obstacles.values() for item in items]
    lead_variants = [
        (0.25, 0.25), (4.0, 4.0), (8.0, 8.0), (2.0, 2.0), (1.0, 1.0),
        (16.0, 16.0), (0.25, 4.0), (4.0, 0.25), (0.25, 8.0), (8.0, 0.25),
        (2.0, 8.0), (8.0, 2.0), (0.25, 16.0), (16.0, 0.25),
    ]
    difficulty = lambda row: (-abs(float(row['target_z_mm'])
                                   - C.interface_z(row['plane'])),
                              int(row['route_id']))
    repaired = {}
    rounds = []
    failed_now = list(failed_rows)
    last_details = {}
    for round_index in range(1, int(max_rounds) + 1):
        gained = 0
        still = []
        for row in sorted(failed_now, key=difficulty):
            layer = int(row['target_layer'])
            obstacles = all_obstacles.get(layer) or flat_obstacles
            outcome, reason, detail = _attempt_local_route(
                row, world, frozen_bodies, obstacles, layer2d_mod,
                lead_variants, log=log)
            if outcome is None:
                still.append(row)
                if detail is not None:
                    last_details[int(row['route_id'])] = detail
                continue
            rid = int(row['route_id'])
            valid[rid] = outcome['route']
            selected[rid] = dict(source=outcome['source'],
                                 target=outcome['target'])
            repaired[rid] = outcome
            gained += 1
            # keep routed bookkeeping in sync for artifact generation
            layer = int(row['target_layer'])
            routed.setdefault(layer, dict(routed={}, failed=[],
                                          stats={}, z_mm=C.layer_z(layer)))
            routed[layer].setdefault('routed', {})[rid] = dict(
                primitives=outcome['body'], family='LOCAL_REPAIR')
        rounds.append(dict(round=round_index, attempted=len(failed_now),
                           repaired=gained, remaining=len(still)))
        log(f'[local-repair] round {round_index}: repaired={gained} '
            f'remaining={len(still)}')
        failed_now = still
        if not failed_now:
            break
    failures = []
    for row in failed_now:
        rid = int(row['route_id'])
        failures.append(dict(route_id=rid,
                             plane=row.get('plane'),
                             target_layer=int(row['target_layer']),
                             manual_group=row.get('manual_group') or '',
                             reason='local_repair_unresolved',
                             detail=last_details.get(rid)))
    return dict(valid=valid, routed=routed, repaired=repaired,
                failures=failures, rounds=rounds, world=world,
                frozen_bodies=frozen_bodies, all_obstacles=all_obstacles)


def _local_rrr(rows, selected, local, log=print, max_attempts=6):
    """Local rip-up & reroute: rip same-layer blockers, reinsert the batch."""
    from ..l3d.world import World
    from . import common as C

    valid = local['valid']
    routed = local['routed']
    failures = list(local['failures'])
    if not failures:
        return local
    row_by_id = {int(row['route_id']): row for row in rows}
    layer2d_mod = _load_layer2d()
    lead_variants = [
        (0.25, 0.25), (4.0, 4.0), (8.0, 8.0), (2.0, 2.0), (1.0, 1.0),
        (16.0, 16.0), (0.25, 4.0), (4.0, 0.25), (0.25, 8.0), (8.0, 0.25),
        (2.0, 8.0), (8.0, 2.0),
    ]
    by_layer = {}
    for failure in failures:
        by_layer.setdefault(int(failure['target_layer']), []).append(failure)
    repaired_total = {}
    remaining_failures = []
    rounds = []
    for layer, layer_failures in sorted(by_layer.items()):
        z = C.layer_z(layer)
        failed_ids = [int(record['route_id']) for record in layer_failures]
        blocker_ids = set()
        for record in layer_failures:
            detail = record.get('detail') or {}
            for blocker in detail.get('blockers') or []:
                try:
                    blocker = int(blocker)
                except (TypeError, ValueError):
                    continue
                if blocker in valid and int(valid[blocker]['target_layer']) == layer:
                    blocker_ids.add(blocker)
        blocker_ids = sorted(blocker_ids)[:10]
        rip = sorted(set(failed_ids) | set(blocker_ids))
        if len(rip) > 14:
            rip = sorted(set(failed_ids) | set(blocker_ids[:12]))
        obstacles = local['all_obstacles'].get(layer) or []
        committed = False
        attempt_record = []
        for attempt in range(1, int(max_attempts) + 1):
            world = World(C.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
            frozen_bodies = {}
            for rid in sorted(valid):
                if rid in rip:
                    continue
                world.add_route(valid[rid])
                body = _body_primitives(valid[rid])
                if body is not None:
                    frozen_bodies.setdefault(int(valid[rid]['target_layer']),
                                             {})[int(rid)] = body
            layer_initial = dict(frozen_bodies.get(layer, {}))
            tasks = []
            task_records = {}
            shift = (attempt - 1) % len(lead_variants)
            lead_order = lead_variants[shift:] + lead_variants[:shift]
            if attempt % 2 == 0:
                lead_order = list(reversed(lead_order))
            for rid in rip:
                row = row_by_id[rid]
                if rid in failed_ids:
                    chosen = None
                    for (lead_s, lead_t) in lead_order:
                        try:
                            src = _transition_record(row, 'source', lead_s)
                            tgt = _transition_record(row, 'target', lead_t)
                        except Exception:  # noqa: BLE001
                            continue
                        if world.check_route(_partial_route(src, row, 2 * rid),
                                             check_self=False):
                            continue
                        if world.check_route(_partial_route(tgt, row, 2 * rid + 1),
                                             check_self=False):
                            continue
                        chosen = (src, tgt)
                        break
                    if chosen is None:
                        break
                    task_records[rid] = chosen
                else:
                    record = selected[rid]
                    task_records[rid] = (record['source'], record['target'])
                src, tgt = task_records[rid]
                tasks.append(dict(
                    route_id=rid, manual_group=row.get('manual_group') or '',
                    relation=row.get('relation') or '',
                    source_side=row.get('source_side'),
                    target_side=row.get('target_side'),
                    A=tuple(src['end_xy']), dA=tuple(src['direction']),
                    B=tuple(tgt['end_xy']), dB=tuple(tgt['direction'])))
            if len(tasks) != len(rip):
                attempt_record.append(dict(attempt=attempt,
                                           reason='no_valid_lead_for_batch'))
                continue
            try:
                result = layer2d_mod.route_layer(
                    layer, z, tasks, obstacles=obstacles,
                    initial_routes=layer_initial, budget=3000, rr_rounds=2,
                    ordering_seed=attempt - 1, log=lambda *_a: None)
            except TypeError:
                result = layer2d_mod.route_layer(
                    layer, z, tasks, obstacles=obstacles,
                    initial_routes=layer_initial, budget=3000, rr_rounds=2,
                    log=lambda *_a: None)
            entries = result.get('routed') or {}
            if len(entries) != len(rip):
                # cascading rip-up: add same-layer blockers of the unrouted
                # tasks to the ripped batch and retry (bounded).
                cascade = set()
                for record in (result.get('failed') or []):
                    for blocker in record.get('blockers') or []:
                        try:
                            blocker = int(blocker)
                        except (TypeError, ValueError):
                            continue
                        if blocker in valid and int(
                                valid[blocker]['target_layer']) == layer:
                            cascade.add(blocker)
                added = sorted(cascade - set(rip))[:4]
                attempt_record.append(dict(
                    attempt=attempt, reason='batch_not_fully_routed',
                    routed=sorted(int(k) for k in entries),
                    tasks=len(rip), cascade_added=added))
                if added and len(rip) + len(added) <= 20:
                    rip = sorted(set(rip) | set(added))
                continue
            new_routes = {}
            ok = True
            for rid in rip:
                row = row_by_id[rid]
                payload = entries.get(rid) or entries.get(str(rid))
                body = (payload.get('primitives')
                        if isinstance(payload, dict) else payload)
                src, tgt = task_records[rid]
                try:
                    route = ASM.assemble_route(row, src, tgt, body)
                except ASM.AssemblyError:
                    ok = False
                    break
                violations = world.check_route(route)
                if violations:
                    ok = False
                    break
                world.add_route(route)
                new_routes[rid] = dict(route=route, source=src, target=tgt,
                                       body=body)
            if not ok:
                attempt_record.append(dict(attempt=attempt,
                                           reason='assembly_or_world_conflict'))
                continue
            for rid in rip:
                valid.pop(rid, None)
            for rid, outcome in new_routes.items():
                valid[rid] = outcome['route']
                selected[rid] = dict(source=outcome['source'],
                                     target=outcome['target'])
                routed.setdefault(layer, dict(routed={}, failed=[],
                                              stats={}, z_mm=z))
                routed[layer].setdefault('routed', {})[rid] = dict(
                    primitives=outcome['body'], family='LOCAL_RRR')
            for rid in failed_ids:
                repaired_total[rid] = new_routes[rid]
            committed = True
            attempt_record.append(dict(attempt=attempt, reason='committed',
                                       rip=rip))
            break
        rounds.append(dict(layer=layer, failed_ids=failed_ids,
                           blockers=blocker_ids, attempts=attempt_record,
                           committed=committed))
        if not committed:
            for record in layer_failures:
                remaining_failures.append(record)
        log(f'[local-rrr] layer L{layer}: failed={failed_ids} '
            f'blockers={blocker_ids} committed={committed}')
    local = dict(local)
    local['valid'] = valid
    local['routed'] = routed
    merged_repaired = dict(local.get('repaired') or {})
    merged_repaired.update(repaired_total)
    local['repaired'] = merged_repaired
    local['failures'] = remaining_failures
    local['rrr_rounds'] = rounds
    return local


def _layer_resolve(rows, selected, local, log=print, max_seeds=24):
    """Whole-layer rip-up & re-solve with different deterministic orderings."""
    from ..l3d.world import World
    from . import common as C

    valid = local['valid']
    routed = local['routed']
    failures = list(local['failures'])
    if not failures:
        return local
    layer2d_mod = _load_layer2d()
    row_by_id = {int(row['route_id']): row for row in rows}
    current_by_layer = {}
    for failure in failures:
        current_by_layer.setdefault(int(failure['target_layer']), []).append(
            int(failure['route_id']))
    improved = {}
    remaining = []
    rounds = []
    for layer, failed_ids in sorted(current_by_layer.items()):
        layer_rows = [row for row in rows
                      if int(row['target_layer']) == layer]
        tasks = []
        missing = []
        for row in layer_rows:
            rid = int(row['route_id'])
            record = selected.get(rid)
            if not record or not record.get('source') or not record.get('target'):
                missing.append(rid)
                continue
            tasks.append(dict(
                route_id=rid, manual_group=row.get('manual_group') or '',
                relation=row.get('relation') or '',
                source_side=row.get('source_side'),
                target_side=row.get('target_side'),
                A=tuple(record['source']['end_xy']),
                dA=tuple(record['source']['direction']),
                B=tuple(record['target']['end_xy']),
                dB=tuple(record['target']['direction'])))
        z = C.layer_z(layer)
        obstacles = local['all_obstacles'].get(layer) or []
        best_entries = None
        best_seed = None
        seed_stats = []
        for seed in range(int(max_seeds)):
            try:
                result = layer2d_mod.route_layer(
                    layer, z, tasks, obstacles=obstacles, budget=2000,
                    rr_rounds=2, ordering_seed=seed, log=lambda *_a: None)
            except TypeError:
                result = layer2d_mod.route_layer(
                    layer, z, tasks, obstacles=obstacles, budget=2000,
                    rr_rounds=2, log=lambda *_a: None)
            entries = result.get('routed') or {}
            seed_stats.append(dict(seed=seed, routed=len(entries)))
            if best_entries is None or len(entries) > len(best_entries):
                best_entries = entries
                best_seed = seed
            if len(best_entries) >= len(tasks):
                break
        current_layer = [rid for rid in valid
                         if int(valid[rid]['target_layer']) == layer]
        if best_entries is None or len(best_entries) <= len(current_layer):
            rounds.append(dict(layer=layer, failed_ids=failed_ids,
                               current=len(current_layer),
                               best_seed=best_seed,
                               best_routed=(len(best_entries)
                                            if best_entries else 0),
                               committed=False))
            remaining.extend(record for record in failures
                             if int(record['target_layer']) == layer)
            log(f'[layer-repair] L{layer}: current={len(current_layer)} '
                f'best_seed={best_seed} best={len(best_entries or {})} '
                f'no gain')
            continue
        world = World(C.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
        for rid in sorted(valid):
            if int(valid[rid]['target_layer']) == layer:
                continue
            world.add_route(valid[rid])
        new_valid = {}
        ok = True
        for rid in sorted(best_entries):
            row = row_by_id[int(rid)]
            payload = best_entries[rid] if rid in best_entries \
                else best_entries[str(rid)]
            body = (payload.get('primitives')
                    if isinstance(payload, dict) else payload)
            record = selected[int(rid)]
            try:
                route = ASM.assemble_route(row, record['source'],
                                           record['target'], body)
            except ASM.AssemblyError:
                ok = False
                break
            if world.check_route(route):
                ok = False
                break
            world.add_route(route)
            new_valid[int(rid)] = (route, body)
        if not ok:
            rounds.append(dict(layer=layer, failed_ids=failed_ids,
                               current=len(current_layer),
                               best_seed=best_seed,
                               best_routed=len(best_entries),
                               committed=False, reason='world_conflict'))
            remaining.extend(record for record in failures
                             if int(record['target_layer']) == layer)
            log(f'[layer-repair] L{layer}: best={len(best_entries)} but '
                f'world check failed')
            continue
        for rid in current_layer:
            valid.pop(rid, None)
        layer_routed = routed.setdefault(
            layer, dict(routed={}, failed=[], stats={}, z_mm=z))
        layer_routed.setdefault('routed', {})
        for rid, (route, body) in new_valid.items():
            valid[rid] = route
            layer_routed['routed'][rid] = dict(primitives=body,
                                               family='LAYER_RESOLVE')
            improved[rid] = dict(route=route, body=body,
                                 source=selected[rid]['source'],
                                 target=selected[rid]['target'])
        repaired_here = set(failed_ids) & set(new_valid)
        rounds.append(dict(layer=layer, failed_ids=failed_ids,
                           current=len(current_layer),
                           best_seed=best_seed,
                           best_routed=len(best_entries),
                           committed=True,
                           recovered=sorted(repaired_here),
                           seed_stats=seed_stats))
        log(f'[layer-repair] L{layer}: committed {len(new_valid)} routes '
            f'(seed {best_seed}), recovered={sorted(repaired_here)}')
    local = dict(local)
    local['valid'] = valid
    local['routed'] = routed
    merged_repaired = dict(local.get('repaired') or {})
    merged_repaired.update(improved)
    local['repaired'] = merged_repaired
    local['failures'] = remaining
    local['layer_resolve_rounds'] = rounds
    return local


# ---------------------------------------------------------------- stage E
_LEAD_REPAIR_VARIANTS = (
    (4.0, 8.0, 2.0, 1.0, 0.25, 16.0),
    (8.0, 16.0, 4.0, 2.0, 1.0, 0.25),
    (0.25, 1.0, 2.0, 4.0, 8.0, 16.0),
    (16.0, 8.0, 4.0, 2.0, 1.0, 0.25),
)
_REPAIR_BUDGETS = (600, 1200, 1800, 2400)


def _replan_failed_fanout(rows, selected, failed_ids, iteration, log=print):
    """Fanout joint repair: re-plan only the failed routes with other leads."""
    fanout_mod = _load_fanout()
    failed_ids = {int(rid) for rid in failed_ids}
    if not failed_ids:
        return selected, None
    fixed = {int(rid): value for rid, value in selected.items()
             if int(rid) not in failed_ids}
    leads = _LEAD_REPAIR_VARIANTS[(int(iteration) - 1)
                                  % len(_LEAD_REPAIR_VARIANTS)]
    try:
        result = fanout_mod.plan_fanout(rows, stack=C.layer_stack(),
                                        fixed=fixed,
                                        repair_ids=sorted(failed_ids),
                                        leads=leads, log=log)
    except Exception as error:  # noqa: BLE001
        log(f'fanout repair failed at iteration {iteration}: {error!r}')
        return selected, None
    repaired = result.get('selected') or {}
    merged = dict(fixed)
    merged.update({int(rid): value for rid, value in repaired.items()})
    log(f'fanout repair iteration {iteration}: leads={leads} '
        f'repaired={len(repaired)}/{len(failed_ids)}')
    return merged, result


def stage_e(rows, fanout_result, log=print, max_iters=3, base_extra=None):
    selected, fanout_failures = _selected_or_fail(fanout_result)
    fanout_route_failures = _endpoint_failure_rows(fanout_failures, rows)
    extra = {int(layer): list(items)
             for layer, items in (base_extra or {}).items()}
    best = None
    history = []
    previous_failed = []
    for iteration in range(1, int(max_iters) + 1):
        log(f'=== STAGE E iteration {iteration}/{max_iters} ===')
        if iteration > 1 and previous_failed:
            selected, _repair = _replan_failed_fanout(
                rows, selected, previous_failed, iteration, log=log)
        budget = _REPAIR_BUDGETS[(int(iteration) - 1)
                                 % len(_REPAIR_BUDGETS)]
        routed, raw = _route_layers(rows, selected, extra,
                                    ordering_seed=iteration - 1,
                                    budget=budget, log=log)
        routes, assembly_failures = _assemble_all(rows, selected, routed, log=log)
        check = _world_check(routes)
        valid = check['valid']
        violations = check['violations']
        score = len(valid)
        log(f'iteration {iteration}: assembled={len(routes)} '
            f'world_valid={score} violations={len(violations)} '
            f'assembly_failures={len(assembly_failures)}')
        record = dict(iteration=iteration, assembled=len(routes),
                      world_valid=score, violations=len(violations),
                      violation_kinds=dict(Counter(
                          rec.get('kind') for rec in violations)),
                      lead_repair=(iteration > 1 and bool(previous_failed)),
                      budget=budget,
                      layer_stats={int(k): v['stats'] for k, v in routed.items()},
                      assembly_failures=len(assembly_failures))
        history.append(record)
        if best is None or score > best['score'] or (
                score == best['score']
                and len(violations) < len(best['violations'])):
            best = dict(score=score, valid=valid, routes=routes,
                        violations=violations, routed=routed, raw=raw,
                        assembly_failures=assembly_failures,
                        iteration=iteration,
                        layer_stats={int(k): v['stats']
                                     for k, v in routed.items()})
        valid_ids = set(valid)
        violation_route_ids = {int(rec.get('route_id', -1))
                               for rec in violations}
        previous_failed = sorted(
            {int(record['route_id']) for record in assembly_failures}
            | violation_route_ids)
        previous_failed = [rid for rid in previous_failed
                           if rid not in valid_ids]
        if score == len(rows) and not violations:
            log('stage E: all routes valid')
            break
        new_obstacles = _violation_obstacles(violations,
                                             {r['route_id']: r for r in routes})
        for layer, items in new_obstacles.items():
            extra.setdefault(layer, []).extend(items)
        if not previous_failed:
            log('stage E: no failed routes left to repair')
            break
        log(f'stage E: next repair targets={previous_failed} '
            f'obstacle_layers={sorted(new_obstacles)}')

    # ---------------- local joint repair: fit the remaining failures into the
    # frozen accepted layout (no global rip-up, bounded local attempts).
    local = _local_repair(rows, selected, best, log=log)
    if local.get('all_obstacles') is not None and local['failures']:
        local = _local_rrr(rows, selected, local, log=log)
    if local['failures'] and local.get('all_obstacles') is not None:
        local = _layer_resolve(rows, selected, local, log=log)
    if local['repaired']:
        best = dict(best)
        best['valid'] = local['valid']
        best['routed'] = local['routed']
        best['violations'] = list(best.get('violations') or [])
        best['score'] = len(local['valid'])
        _write_repaired_fanout(rows, selected, log=log)
    if local.get('rounds') or local.get('rrr_rounds') \
            or local.get('layer_resolve_rounds'):
        history.append(dict(stage='local_joint_repair',
                            rounds=local.get('rounds'),
                            rrr_rounds=local.get('rrr_rounds'),
                            layer_resolve_rounds=local.get(
                                'layer_resolve_rounds'),
                            repaired=len(local['repaired']),
                            world_valid=len(local['valid']),
                            remaining=len(local['failures'])))
        log('[stage E] local repair record: '
            f'repaired={len(local["repaired"])} '
            f'world_valid={len(local["valid"])} '
            f'remaining={len(local["failures"])}')

    # ---------------- final artifacts
    valid = best['valid']
    routes = [valid[rid] for rid in sorted(valid)]
    violation_route_ids = {int(rec.get('route_id', -1))
                           for rec in best['violations']}
    merged = _merge_failures(fanout_route_failures,
                             best['assembly_failures'], violation_route_ids)
    original = {int(record['route_id']): record for record in merged}
    failed = []
    for record in local['failures']:
        rid = int(record['route_id'])
        base = dict(original.get(rid) or {})
        base.update(record)
        if 'original_reason' not in base:
            base['original_reason'] = original.get(rid, {}).get('reason')
        failed.append(base)
    for rid, record in original.items():
        if rid not in valid and rid not in {int(r['route_id']) for r in failed}:
            failed.append(record)
    failed.sort(key=lambda record: int(record['route_id']))
    _write_experiment_e(rows, best, failed, history, log)
    _write_final_artifacts(rows, routes, failed, best, history, log)
    log(f'stage E final: {len(routes)}/1024 strict-valid routes, '
        f'{len(failed)} failed (local repair recovered '
        f'{len(local["repaired"])})')
    return dict(routes=routes, failed=failed, best=best, history=history,
                local_repair=local)


# ---------------------------------------------------------------- artifacts
def _write_repaired_fanout(rows, selected, log=print):
    """Update fanout_selected.json / fanout_validation.json after local repair."""
    fanout_mod = _load_fanout()
    path = C.RUN_DIR / 'fanout_selected.json'
    payload = {}
    if path.is_file():
        try:
            payload = C.read_json(path)
        except Exception:  # noqa: BLE001
            payload = {}
    payload.update(dict(
        schema=payload.get('schema') or 'fanout_selected_v1',
        route_count=len(selected),
        selected={str(rid): selected[rid] for rid in sorted(selected)},
        local_repair=True,
    ))
    C.write_json(path, payload)
    # refresh layerwise_endpoints for the repaired routes
    endpoints_path = C.RUN_DIR / 'layerwise_endpoints' / 'endpoints.json'
    try:
        endpoints_payload = C.read_json(endpoints_path)
        entries = endpoints_payload.get('endpoints') or []
        index = {(int(item.get('route_id', -1)),
                  item.get('endpoint_role')): position
                 for position, item in enumerate(entries)}
        for rid in sorted(selected):
            for role in ('source', 'target'):
                record = selected[rid].get(role)
                if not record:
                    continue
                position = index.get((int(rid), role))
                if position is None:
                    continue
                updated = dict(record)
                updated.setdefault('candidate_id',
                                   f'{rid}-{role}-local-repair')
                entries[position] = updated
        endpoints_payload['endpoints'] = entries
        endpoints_payload['endpoint_count'] = len(entries)
        C.write_json(endpoints_path, endpoints_payload)
    except Exception as error:  # noqa: BLE001
        log(f'[local-repair] could not refresh layerwise_endpoints: {error!r}')
    try:
        validation = fanout_mod.validate_selected(selected, rows=rows,
                                                  log=None)
    except Exception as error:  # noqa: BLE001
        validation = dict(ok=None, error=repr(error))
    C.write_json(C.RUN_DIR / 'fanout_validation.json', validation)
    log(f'[local-repair] rewrote fanout_selected.json '
        f'({len(selected)} routes) and fanout_validation.json '
        f'(ok={validation.get("ok")})')


def _write_experiment_e(rows, best, failed, history, log):
    out = C.RUN_DIR / 'experiment_E'
    out.mkdir(parents=True, exist_ok=True)
    assigned = Counter(int(row['target_layer']) for row in rows)
    per_layer = {}
    for layer in sorted(assigned):
        entry = best['routed'].get(int(layer)) or {}
        layer_routed = entry.get('routed') or {}
        routed_ids = {int(rid) for rid in layer_routed}
        layer_failed = [dict(record) for record in (entry.get('failed') or [])
                        if int(record.get('route_id', -1)) not in routed_ids]
        known = {int(record['route_id']) for record in layer_failed}
        for record in failed:
            rid = int(record['route_id'])
            if record.get('target_layer') is not None \
                    and int(record['target_layer']) == int(layer) \
                    and rid not in known and rid not in routed_ids:
                layer_failed.append(dict(record))
                known.add(rid)
        per_layer[str(layer)] = dict(
            assigned=int(assigned[layer]),
            routed=len(routed_ids),
            failed=int(assigned[layer]) - len(routed_ids),
            failed_routes=layer_failed,
        )
    final_fanout = None
    try:
        fanout_payload = C.read_json(C.RUN_DIR / 'fanout_selected.json')
        selected = fanout_payload.get('selected') or {}
        leads = Counter()
        for rid, record in selected.items():
            src = record.get('source') or {}
            tgt = record.get('target') or {}
            leads[f"{src.get('lead_mm')}/{tgt.get('lead_mm')}"] += 1
        final_fanout = dict(
            routes=len(selected),
            lead_histogram={str(key): int(value)
                            for key, value in sorted(leads.items())},
            transition_count=2 * len(selected),
            note='final lead state after local joint repair / RRR '
                 '(fanout_selected.json); experiment_D records the initial '
                 'all-0.25 mm fanout plan',
        )
    except Exception as error:  # noqa: BLE001
        final_fanout = dict(error=repr(error))
    summary = dict(
        stage='experiment_E',
        input_routes=1024,
        attempted_routes=1024,
        successful_routes=len(best['valid']),
        failed_routes=len(failed),
        failure_reasons=dict(Counter(record.get('reason')
                                     for record in failed)),
        per_layer=per_layer,
        iterations=history,
        final_fanout=final_fanout,
        validation=dict(
            world_valid=len(best['valid']),
            violations=len(best['violations']),
            violation_kinds=dict(Counter(rec.get('kind')
                                         for rec in best['violations'])),
            strict_clearance_mm=C.MIN_3D_CLEARANCE_MM,
            status='passed' if not best['violations'] else 'failed',
        ),
        artifact='routes_l3d.json',
    )
    _json_write(out / 'summary.json', summary)
    _json_write(out / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    _json_write(out / 'violations.json',
                dict(total=len(best['violations']),
                     violations=best['violations']))
    # layerwise routes for the winning iteration
    payload = dict(schema='fanout_first_layerwise_routes_v1',
                   layers={})
    for layer, entry in best['routed'].items():
        payload['layers'][str(layer)] = dict(
            layer_id=int(layer), z_mm=C.layer_z(int(layer)),
            routes={str(rid): dict(value) for rid, value in
                    entry['routed'].items()},
            failed=[dict(record) for record in entry['failed']],
            stats=entry['stats'],
        )
    _json_write(C.RUN_DIR / 'layerwise_routes' / 'routes.json', payload)
    _json_write(C.RUN_DIR / 'checkpoints' / 'experiment_E_best.json',
                dict(score=best.get('score'), iteration=best.get('iteration'),
                     valid=len(best['valid']),
                     violations=len(best['violations'])))
    log(f'wrote experiment_E summary ({len(best["valid"])} valid)')


def _write_final_artifacts(rows, routes, failed, best, history, log):
    stack_payload = C.physical_layer_stack_payload()
    process_payload = C.process_rules_payload()
    payload = ASM.routes_payload(routes, failed, stack_payload,
                                 process_payload, rows)
    payload['joint_repair_history'] = history
    _json_write(C.RUN_DIR / 'routes_l3d.json', payload)
    _json_write(C.RUN_DIR / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    by_plane = Counter(route['plane'] for route in routes)
    by_group = Counter((route.get('manual_group') or 'other')
                       for route in routes)
    failed_by_plane = Counter(record.get('plane') for record in failed)
    stats = dict(
        schema='fanout_first_final_stats_v1',
        input_routes=1024,
        attempted_routes=1024,
        routed=len(routes),
        failed=len(failed),
        z1_routed=by_plane.get('z1', 0),
        z2_routed=by_plane.get('z2', 0),
        z1_failed=failed_by_plane.get('z1', 0),
        z2_failed=failed_by_plane.get('z2', 0),
        manual_group_routed=dict(by_group),
        failure_reasons=dict(Counter(record.get('reason')
                                     for record in failed)),
        failed_route_ids=sorted(record['route_id'] for record in failed),
        validation_status='strict_world_pass'
        if not best['violations'] else 'strict_world_violations',
        min_3d_clearance_mm=C.MIN_3D_CLEARANCE_MM,
        radius_mm=C.MIN_BEND_RADIUS_MM,
        process_mode='corrected_50um',
        total_length_mm=round(sum(route.get('length_mm') or 0.0
                                  for route in routes), 3),
        total_transitions=sum(route.get('n_transitions') or 0
                              for route in routes),
        joint_repair_iterations=len(history or []),
        world_violations=len(best['violations']),
        note='only routes that pass the strict 0.05 mm 3D world check are '
             'counted as routed; failures are listed with real route ids',
    )
    _json_write(C.RUN_DIR / 'final_stats.json', stats)
    log(f'wrote final artifacts: routes_l3d.json routed={len(routes)} '
        f'failed={len(failed)}')


# ---------------------------------------------------------------- local repair stage
def stage_local_repair(log=print):
    """Resume from the current RUN_DIR state and run the local joint repair."""
    rows = read_assignment()
    fanout_payload = C.read_json(C.RUN_DIR / 'fanout_selected.json')
    selected = {int(key): value
                for key, value in fanout_payload['selected'].items()}
    routes_payload = C.read_json(C.RUN_DIR / 'routes_l3d.json')
    history = list(routes_payload.get('joint_repair_history') or [])
    valid = {}
    for record in routes_payload['routes']:
        if record.get('status') == 'failed':
            continue
        valid[int(record['route_id'])] = record
    layerwise_path = C.RUN_DIR / 'layerwise_routes' / 'routes.json'
    routed = {}
    if layerwise_path.is_file():
        layers = C.read_json(layerwise_path).get('layers') or {}
        for key, value in layers.items():
            routed[int(key)] = dict(routed=value.get('routes') or {},
                                    failed=value.get('failed') or [],
                                    stats=value.get('stats') or {},
                                    z_mm=value.get('z_mm'))
    best = dict(valid=valid, routed=routed, violations=[],
                assembly_failures=[], score=len(valid),
                iteration=len(history) + 1)
    log(f'[local-repair] resume: {len(valid)} valid routes, '
        f'{1024 - len(valid)} unresolved')
    local = _local_repair(rows, selected, best, log=log)
    if local.get('all_obstacles') is not None and local['failures']:
        local = _local_rrr(rows, selected, local, log=log)
    if local['failures'] and local.get('all_obstacles') is not None:
        local = _layer_resolve(rows, selected, local, log=log)
    if local['repaired']:
        best['valid'] = local['valid']
        best['routed'] = local['routed']
        best['score'] = len(local['valid'])
        _write_repaired_fanout(rows, selected, log=log)
    if local.get('rounds') or local.get('rrr_rounds') \
            or local.get('layer_resolve_rounds'):
        history.append(dict(stage='local_joint_repair',
                            rounds=local.get('rounds'),
                            rrr_rounds=local.get('rrr_rounds'),
                            layer_resolve_rounds=local.get(
                                'layer_resolve_rounds'),
                            repaired=len(local['repaired']),
                            world_valid=len(local['valid']),
                            remaining=len(local['failures'])))
        log('[local-repair] record: '
            f'repaired={len(local["repaired"])} '
            f'world_valid={len(local["valid"])} '
            f'remaining={len(local["failures"])}')
    valid_final = best['valid']
    routes = [valid_final[rid] for rid in sorted(valid_final)]
    original = {int(record['route_id']): record for record in
                (C.read_json(C.RUN_DIR / 'failed_routes.json').get('failures')
                 if (C.RUN_DIR / 'failed_routes.json').is_file() else [])}
    failed = []
    for record in local['failures']:
        rid = int(record['route_id'])
        base = dict(original.get(rid) or {})
        base.update(record)
        base.setdefault('original_reason', original.get(rid, {}).get('reason'))
        failed.append(base)
    if not local['repaired'] and not failed:
        failed = [original[rid] for rid in sorted(original)]
    failed.sort(key=lambda record: int(record['route_id']))
    _write_experiment_e(rows, best, failed, history, log)
    _write_final_artifacts(rows, routes, failed, best, history, log)
    log(f'local repair stage final: {len(routes)}/1024 strict-valid, '
        f'{len(failed)} failed (recovered {len(local["repaired"])})')
    return dict(routes=routes, failed=failed, best=best, history=history,
                local_repair=local)


def stage_rewrite_artifacts(log=print):
    """Recompute experiment_E / per-layer summaries from the final artifacts."""
    rows = read_assignment()
    d = C.RUN_DIR
    routes_payload = C.read_json(d / 'routes_l3d.json')
    history = list(routes_payload.get('joint_repair_history') or [])
    valid = {int(record['route_id']): record
             for record in routes_payload['routes']
             if record.get('status') != 'failed'}
    layers = C.read_json(d / 'layerwise_routes' / 'routes.json')['layers']
    routed = {int(key): dict(routed=value.get('routes') or {},
                             failed=value.get('failed') or [],
                             stats=value.get('stats') or {},
                             z_mm=value.get('z_mm'))
              for key, value in layers.items()}
    failed_payload = C.read_json(d / 'failed_routes.json')
    failed = list(failed_payload.get('failures') or [])
    best = dict(valid=valid, routed=routed, violations=[], score=len(valid))
    _write_experiment_e(rows, best, failed, history, log)
    log(f'rewrote experiment_E summary: valid={len(valid)} failed={len(failed)}')
    return dict(valid=len(valid), failed=len(failed))


# ---------------------------------------------------------------- main
def run_stages(stages='ABCDE', max_iters=3, force_a=False, limit=None,
               log=print):
    _ensure_run_dir()
    rows = stage_a(force=force_a, log=log)
    if limit:
        keep = {row['route_id'] for row in rows[:int(limit)]}
        rows = [row for row in rows if row['route_id'] in keep]
        log(f'DEBUG limit={limit} rows={len(rows)}')
    manual_rows = [row for row in rows
                   if row['layer_role'] in MANUAL_ROLES]
    fanout_manual = None
    fanout_all = None
    if 'B' in stages:
        fanout_manual, b_stats, b_failures = _fanout_stage(
            manual_rows, 'experiment_B',
            C.RUN_DIR / 'experiment_B', 'experiment_B', log=log)
    if 'C' in stages:
        if fanout_manual is None:
            raise RuntimeError('stage C needs stage B fanout')
        selected, _ = _selected_or_fail(fanout_manual)
        layer2d_mod = _load_layer2d()
        layers = _build_layer_tasks(manual_rows, selected, log=log)
        manual_layers = OrderedDict((layer, value) for layer, value in
                                    layers.items() if layer in MANUAL_LAYERS)
        out = C.RUN_DIR / 'experiment_C'
        out.mkdir(parents=True, exist_ok=True)
        try:
            result = layer2d_mod.route_all_layers(
                manual_layers, out_dir=out, log=log)
        except TypeError:
            result = layer2d_mod.route_all_layers(manual_layers, log=log)
        normalized = _normalize_layer_result(result)
        stats = _experiment_c_stats(manual_rows, selected, normalized)
        _json_write(out / 'summary.json', stats)
        _json_write(C.RUN_DIR / 'checkpoints' / 'experiment_C_2d.json', stats)
        log(f'experiment_C: routed={stats["routed"]}/{stats["input_routes"]} '
            f'failed={stats["failed"]} validation={stats["validation"]["status"]}')
    if 'D' in stages:
        fixed = None
        if fanout_manual is not None:
            fixed, _ = _selected_or_fail(fanout_manual)
        fanout_all, d_stats, d_failures = _fanout_stage(
            rows, 'experiment_D', C.RUN_DIR / 'experiment_D',
            'experiment_D', fixed=fixed, log=log)
    if 'E' in stages:
        if fanout_all is None:
            raise RuntimeError('stage E needs stage D fanout')
        stage_e(rows, fanout_all, log=log, max_iters=max_iters)
    if 'L' in stages:
        stage_local_repair(log=log)
    if 'R' in stages:
        stage_rewrite_artifacts(log=log)
    return dict(rows=rows, fanout_manual=fanout_manual, fanout_all=fanout_all)


def _experiment_c_stats(manual_rows, selected, normalized):
    routed = 0
    failed_records = []
    per_group = {}
    for row in manual_rows:
        layer = int(row['target_layer'])
        entry = normalized.get(layer)
        group = row.get('manual_group') or 'unknown'
        group_stats = per_group.setdefault(group, dict(
            input=0, routed=0, failed=0, layer=layer))
        group_stats['input'] += 1
        ok = False
        if entry is not None:
            payload = entry['routed'].get(row['route_id']) or \
                entry['routed'].get(str(row['route_id']))
            ok = payload is not None
        if ok:
            routed += 1
            group_stats['routed'] += 1
        else:
            group_stats['failed'] += 1
            record = dict(route_id=row['route_id'], plane=row['plane'],
                          target_layer=layer, manual_group=group,
                          reason='layer2d_failed')
            if entry is not None:
                for failure in entry['failed']:
                    if int(failure.get('route_id', -1)) == row['route_id']:
                        record['detail'] = failure
                        record['reason'] = ('layer2d_failed:'
                                            + str(failure.get('reason')))
                        break
            failed_records.append(record)
    per_layer = {}
    for layer, entry in normalized.items():
        per_layer[str(layer)] = dict(
            routed=len(entry['routed']), failed=len(entry['failed']),
            total=len(entry['routed']) + len(entry['failed']),
            stats=entry['stats'])
    validation = dict(
        status='passed' if routed == len(manual_rows) else 'incomplete',
        routed=routed, input=len(manual_rows))
    return dict(stage='experiment_C', input_routes=len(manual_rows),
                attempted_routes=len(manual_rows), routed=routed,
                failed=len(manual_rows) - routed,
                per_group=per_group, per_layer=per_layer,
                failure_reasons=dict(Counter(record['reason']
                                             for record in failed_records)),
                validation=validation, failed_routes=failed_records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', default='ABCDE')
    parser.add_argument('--max-iters', type=int, default=3)
    parser.add_argument('--force-a', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args(argv)
    log = make_logger()
    log(f'run_all stages={args.stages} max_iters={args.max_iters} '
        f'limit={args.limit}')
    started = time.time()
    result = run_stages(args.stages, max_iters=args.max_iters,
                        force_a=args.force_a, limit=args.limit, log=log)
    log(f'run_all done in {time.time() - started:.1f}s')
    return result


if __name__ == '__main__':
    main()
