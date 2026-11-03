# -*- coding: utf-8 -*-
"""Experiment A-E driver for the 21-routing-height rebalanced 1024 experiment.

Pipeline
--------
A  audit/load the new 1024-row assignment and the 21-height layer model
B  fanout: 924 normal routes get R15 S transitions, 100 interface-direct routes
   stay on their interface plane (no transition, no lead)
C  layer-wise 2D routing on all 21 heights (first pass)
D  full 3D assembly + fresh strict world check (first pass)
E  joint repair (fanout lead re-plan, deterministic re-runs, whole-plane
   rip-up & re-solve) until the best legal 1024-route solution is frozen

Every route counted as routed must pass the strict 0.05 mm 3D world check.
The baseline 18-layer experiment is never modified: this module only writes
inside ``reheight21.model.RUN_DIR``.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import assemble as ASM
from .. import common as C
from . import model as M

MANUAL_ROLES = ('z1_manual_u', 'z2_manual_u')
_LAYER_BUDGETS = (600, 1200, 1800, 2400)
_LEAD_REPAIR_VARIANTS = (
    (4.0, 8.0, 2.0, 1.0, 0.25, 16.0),
    (8.0, 16.0, 4.0, 2.0, 1.0, 0.25),
    (0.25, 1.0, 2.0, 4.0, 8.0, 16.0),
    (16.0, 8.0, 4.0, 2.0, 1.0, 0.25),
)
_LEAD_PAIRS = (
    (0.25, 0.25), (4.0, 4.0), (8.0, 8.0), (2.0, 2.0), (1.0, 1.0),
    (16.0, 16.0), (0.25, 4.0), (4.0, 0.25), (0.25, 8.0), (8.0, 0.25),
    (2.0, 8.0), (8.0, 2.0), (0.25, 16.0), (16.0, 0.25),
)



def _body_primitives_of(route):
    target_layer = int(route['target_layer'])
    for part in route.get('parts') or []:
        if part['kind'] == 'flat' and int(part.get('layer_id', -1)) == target_layer:
            return [dict(prim) for prim in part['primitives']]
    return None


# ================================================================ utilities
def _ensure_run_dir():
    M.RUN_DIR.mkdir(parents=True, exist_ok=True)


def make_logger(tag='21h'):
    _ensure_run_dir()
    log_path = M.RUN_DIR / 'run.log'

    def log(message):
        line = time.strftime('%H:%M:%S') + f' [{tag}] ' + str(message)
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


def _json_write(path, obj):
    C.write_json(path, obj)


def _load_fanout():
    from .. import fanout
    return fanout


def _load_layer2d():
    from .. import layer2d
    return layer2d


def _as_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in ('1', 'true', 'yes', 'y')


def _read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


# ================================================================ stage A
def read_assignment(path=None):
    path = Path(path or M.NEW_ASSIGNMENT)
    if not path.is_file():
        raise FileNotFoundError(f'21-height assignment missing: {path}')
    rows = _read_csv(path)
    if len(rows) != 1024:
        raise ValueError(f'assignment must have 1024 rows, got {len(rows)}')
    out = []
    int_fields = ('route_id', 'target_layer', 'source_row', 'target_row',
                  'c4_group_id', 'rotation_phase')
    float_fields = ('target_z_mm', 'interface_z_mm', 'source_x_mm',
                    'source_y_mm', 'target_x_mm', 'target_y_mm')
    str_fields = ('plane', 'relation', 'manual_group', 'manual_pattern',
                  'layer_role', 'direction', 'target_plane_label',
                  'baseline_old_layer', 'source_endpoint', 'target_endpoint',
                  'source_side', 'target_side', 'source_connector',
                  'target_connector')
    for raw in rows:
        record = dict(raw)
        for key in int_fields:
            if key in record and str(record[key]).strip() not in ('', 'None'):
                record[key] = int(float(record[key]))
            elif key in record:
                record[key] = 0 if key != 'target_layer' else record[key]
        for key in float_fields:
            if key in record and str(record[key]).strip() not in ('', 'None'):
                record[key] = float(record[key])
        for key in str_fields:
            if key in record and record[key] is None:
                record[key] = ''
        record['target_layer'] = int(record['target_layer'])
        record['route_id'] = int(record['route_id'])
        record['needs_transition'] = _as_bool(record.get('needs_transition', 'True'))
        out.append(record)
    ids = [row['route_id'] for row in out]
    if len(set(ids)) != 1024:
        raise ValueError('assignment route ids are not unique')
    out.sort(key=lambda row: row['route_id'])
    return out


def stage_a(log=print):
    log('=== STAGE A: 21-height layer model + assignment audit ===')
    if not (M.RUN_DIR / 'assignment_1024.csv').is_file():
        log('assignment missing -> invoking reheight21.assign21')
        from . import assign21
        assign21.main()
    if not (M.RUN_DIR / 'layer_planes.json').is_file():
        planes_payload = None
        try:
            planes_payload = M.layer_planes_payload()
        except AttributeError:
            planes_payload = dict(
                schema='reheight21_layer_planes_v1',
                glass=dict(z_min=-0.35, z_max=0.65, thickness_mm=1.0),
                interfaces=dict(z1=0.0, z2=0.5),
                plane_count=len(M.PLANE_IDS),
                min_pitch_mm=0.05,
                planes=[dict(plane_id=int(pid),
                             label=M.plane_label(pid),
                             z_mm=float(M.plane_z(pid)),
                             kind=M.plane_kind(pid),
                             role='body' if M.plane_kind(pid) == 'body'
                             else 'interface_body')
                        for pid in M.PLANE_IDS])
        _json_write(M.RUN_DIR / 'layer_planes.json', planes_payload)
    rows = read_assignment()
    planes = Counter(row['plane'] for row in rows)
    roles = Counter(row['layer_role'] for row in rows)
    direct = [row for row in rows if not row['needs_transition']]
    by_plane = Counter(int(row['target_layer']) for row in rows)
    if planes != Counter({'z1': 512, 'z2': 512}):
        raise ValueError(f'plane split wrong: {planes}')
    expected_counts = {
        2: 64, 3: 64, 4: 64, 5: 64, 6: 52, 7: 52, 20: 52, 1001: 52, 8: 48,
        9: 48, 10: 16, 11: 16, 12: 40, 13: 40, 14: 48, 15: 48, 16: 52,
        1002: 48, 17: 52, 18: 52, 19: 52,
    }
    for plane, expected in expected_counts.items():
        if by_plane.get(plane, 0) != expected:
            raise ValueError(f'plane {plane}: {by_plane.get(plane, 0)} rows '
                             f'!= expected {expected}')
    heights = {round(M.plane_z(pid), 9) for pid in M.PLANE_IDS}
    if len(heights) != 21:
        raise ValueError(f'expected 21 distinct heights, got {sorted(heights)}')
    if len(direct) != 100:
        raise ValueError(f'expected 100 interface-direct rows, got {len(direct)}')
    log(f'stage A ok: rows={len(rows)} planes={dict(planes)} '
        f'roles={dict(roles)} direct={len(direct)} heights=21')
    return rows


# ================================================================ stage B
def _partial_route_for_check(fanout_mod, row, role, record, world_id):
    return fanout_mod.partial_route(row, role, record, world_id)


def validate_fanout_selected(rows, selected, log=print):
    """Independent checks for the 1848 transitions + 200 direct endpoints."""
    from ...l3d.world import World
    fanout_mod = _load_fanout()
    eps = C.endpoints()
    world = World(M.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
    violations = []
    transition_count = 0
    direct_endpoints = 0
    row_by_id = {int(row['route_id']): row for row in rows}
    for rid in sorted(selected):
        pair = selected[rid]
        row = row_by_id.get(int(rid))
        for role in ('source', 'target'):
            record = pair.get(role)
            if record is None:
                violations.append(dict(route_id=rid, role=role,
                                       kind='missing_endpoint_record'))
                continue
            if record.get('direct'):
                direct_endpoints += 1
                endpoint = (row['source_endpoint'] if role == 'source'
                            else row['target_endpoint'])
                port_xy = tuple(float(v) for v in eps[endpoint]['routing_xy'])
                if math.dist(tuple(record['start_xy']), port_xy) > 1e-6:
                    violations.append(dict(route_id=rid, role=role,
                                           kind='direct_pose_mismatch'))
                continue
            transition_count += 1
            radius = float(record.get('radius_mm', 0.0))
            if abs(radius - C.MIN_BEND_RADIUS_MM) > 1e-6:
                violations.append(dict(route_id=rid, role=role,
                                       kind='radius_not_15',
                                       radius_mm=radius))
            partial = _partial_route_for_check(fanout_mod, row, role, record,
                                               2 * rid + (0 if role == 'source' else 1))
            found = world.check_route(partial)
            for item in found:
                violations.append(dict(item, route_id=rid, role=role))
            if found:
                continue
            world.add_route(partial)
    kinds = Counter(item.get('kind') for item in violations)
    return dict(ok=not violations, transition_count=transition_count,
                direct_endpoints=direct_endpoints,
                expected_transitions=2 * (len(rows) - 100),
                expected_direct_endpoints=200,
                violations=len(violations), violation_kinds=dict(kinds),
                examples=violations[:10])


def _fanout_artifacts(rows, selected, validation, failures, stats, log=print):
    eps = C.endpoints()
    endpoints = []
    for row in rows:
        rid = int(row['route_id'])
        pair = selected.get(rid) or {}
        for role in ('source', 'target'):
            record = pair.get(role) or {}
            entry = dict(record)
            entry.setdefault('route_id', rid)
            entry.setdefault('endpoint_role', role)
            entry.setdefault('plane', row['plane'])
            entry.setdefault('target_layer', int(row['target_layer']))
            entry.setdefault('target_plane_label', row.get('target_plane_label'))
            entry.setdefault('target_z_mm', float(row['target_z_mm']))
            entry.setdefault('n_transitions',
                             0 if entry.get('direct') else 1)
            endpoints.append(entry)
    _json_write(M.RUN_DIR / 'fanout_selected.json', dict(
        schema='reheight21_fanout_selected_v1',
        layer_model='21 heights (19 body planes + 2 routable interface planes)',
        route_count=len(rows),
        direct_routes=sum(1 for row in rows if not row['needs_transition']),
        transition_routes=sum(1 for row in rows if row['needs_transition']),
        transition_count=sum(1 for entry in endpoints
                             if not entry.get('direct')),
        selected={str(rid): selected[rid] for rid in sorted(selected)},
    ))
    _json_write(M.RUN_DIR / 'fanout_validation.json', validation)
    _json_write(M.RUN_DIR / 'layerwise_endpoints' / 'endpoints.json', dict(
        schema='reheight21_layerwise_endpoints_v1',
        endpoint_count=len(endpoints), endpoints=endpoints))
    out = M.RUN_DIR / 'experiment_B'
    out.mkdir(parents=True, exist_ok=True)
    _json_write(out / 'summary.json', dict(
        schema='reheight21_fanout_experiment_v1', experiment='B',
        input_routes=len(rows), attempted_routes=len(rows),
        success_routes=len(selected),
        failed_routes=len(failures),
        direct_routes=sum(1 for row in rows if not row['needs_transition']),
        transition_routes=sum(1 for row in rows if row['needs_transition']),
        transition_count=validation.get('transition_count'),
        direct_endpoints=validation.get('direct_endpoints'),
        failure_reasons=dict(Counter(record.get('reason')
                                     for record in failures)),
        failed_route_ids=sorted({int(record['route_id'])
                                 for record in failures}),
        validation=validation, stats=stats))
    _json_write(out / 'failed_routes.json',
                dict(total=len(failures), failures=failures))
    log(f'[B] fanout done: selected={len(selected)} failures={len(failures)} '
        f'transitions={validation.get("transition_count")} '
        f'direct_endpoints={validation.get("direct_endpoints")} '
        f'validation_ok={validation.get("ok")}')


def _fanout_failures(fanout_result, rows):
    row_by_id = {int(row['route_id']): row for row in rows}
    merged = {}
    for record in fanout_result.get('failures') or []:
        rid = int(record.get('route_id', -1))
        if rid not in row_by_id:
            continue
        base = merged.setdefault(rid, dict(
            route_id=rid, plane=row_by_id[rid]['plane'],
            target_layer=int(row_by_id[rid]['target_layer']),
            target_plane_label=row_by_id[rid].get('target_plane_label'),
            manual_group=row_by_id[rid].get('manual_group') or '',
            reason='fanout_failed', roles=[], blockers=[]))
        base['roles'].append(record.get('endpoint_role')
                             or record.get('role') or 'source+target')
        reason = record.get('reason') or 'fanout_failed'
        if reason not in base['reason']:
            base['reason'] = str(base['reason']) + '+' + str(reason)
        for blocker in record.get('blockers') or []:
            try:
                base['blockers'].append(int(blocker))
            except (TypeError, ValueError):
                pass
    return [merged[rid] for rid in sorted(merged)]


def stage_b(rows, log=print):
    log('=== STAGE B: endpoint transitions + interface-direct records ===')
    fanout_mod = _load_fanout()
    started = time.time()
    result = fanout_mod.plan_fanout(rows, stack=M.layer_stack(), log=log)
    selected = {int(rid): value
                for rid, value in (result.get('selected') or {}).items()}
    missing = [int(row['route_id']) for row in rows
               if int(row['route_id']) not in selected]
    failures = _fanout_failures(result, rows)
    for rid in missing:
        failures.append(dict(route_id=rid, reason='fanout_no_record'))
    failures.sort(key=lambda record: int(record['route_id']))
    validation = validate_fanout_selected(rows, selected, log=log)
    _fanout_artifacts(rows, selected, validation, failures,
                      result.get('stats') or {}, log=log)
    _json_write(M.RUN_DIR / 'checkpoints' / 'stage_B_fanout.json', dict(
        selected_routes=len(selected), failures=len(failures),
        validation=validation, seconds=round(time.time() - started, 1)))
    log(f'[B] seconds={time.time() - started:.1f}')
    return selected, failures, validation


# ================================================================ layer tasks
def _interface_lead_blockers(selected):
    """Frozen interface lead segments, per interface plane (D56 blockers)."""
    lead_map = {pid: {} for pid in M.INTERFACE_PLANES}
    for rid, pair in selected.items():
        if not isinstance(pair, dict):
            continue
        for role_index, role in enumerate(('source', 'target')):
            record = pair.get(role)
            if not record or record.get('direct'):
                continue
            lead = record.get('lead_part')
            if not lead or not lead.get('primitives'):
                continue
            if float(lead.get('length_mm') or 0.0) <= 1e-9:
                continue
            z = float(lead['z_mm'])
            plane = 'z1' if abs(z) < 0.25 else 'z2'
            pid = M.interface_plane_for(plane)
            lead_map[pid][int(rid) * 2 + role_index] = lead['primitives']
    return lead_map


def _task_from_pose(row, pose, direct):
    return dict(
        route_id=int(row['route_id']),
        manual_group=row.get('manual_group') or '',
        relation=row.get('relation') or '',
        source_side=row.get('source_side'),
        target_side=row.get('target_side'),
        A=tuple(pose['A']), dA=tuple(pose['dA']),
        B=tuple(pose['B']), dB=tuple(pose['dB']),
        direct=bool(direct),
    )


def _build_layer_tasks(rows, selected, log=print):
    fanout_mod = _load_fanout()
    landings = fanout_mod.landings(selected)
    by_plane = OrderedDict()
    for pid in M.PLANE_IDS:
        by_plane[pid] = dict(
            plane_id=int(pid), label=M.plane_label(pid),
            z_mm=float(M.plane_z(pid)), tasks=[], obstacles=[])
    for row in rows:
        rid = int(row['route_id'])
        pid = int(row['target_layer'])
        pose = landings.get(rid)
        if pose is None:
            continue
        by_plane[pid]['tasks'].append(
            _task_from_pose(row, pose, not row['needs_transition']))
    for pid, entry in by_plane.items():
        entry['obstacles'] = fanout_mod.layer_obstacles(
            selected, pid, layer_z=entry['z_mm'])
    return by_plane


def _initial_routes_for(layer_tasks, lead_blockers=None):
    out = {}
    for pid, entry in layer_tasks.items():
        if not M.is_direct_plane(pid):
            continue
        frozen = dict((lead_blockers or {}).get(pid, {}))
        out[int(pid)] = frozen
    return out


def _route_all_layers(rows, selected, budget, seed, log=print,
                      lead_blockers=None):
    layer2d_mod = _load_layer2d()
    layer_tasks = _build_layer_tasks(rows, selected, log=log)
    tasks_payload = {int(pid): dict(z_mm=entry['z_mm'],
                                    tasks=entry['tasks'],
                                    obstacles=entry['obstacles'])
                     for pid, entry in layer_tasks.items()}
    initial = _initial_routes_for(layer_tasks, lead_blockers)
    started = time.time()
    try:
        result = layer2d_mod.route_all_layers(
            tasks_payload, out_dir=None, log=log, ordering_seed=seed,
            budget=budget, initial_routes=initial)
    except TypeError:
        result = layer2d_mod.route_all_layers(
            tasks_payload, out_dir=None, log=log)
    normalized = _normalize_layer_result(result)
    elapsed = time.time() - started
    reconciled = _reconcile_layer_failures(tasks_payload, normalized)
    routed_total = sum(len(value['routed']) for value in normalized.values())
    failed_total = sum(len(value) for value in reconciled.values())
    log(f'[layer2d] planes={len(normalized)} routed={routed_total} '
        f'failed={failed_total} ({elapsed:.1f}s, seed={seed}, '
        f'budget={budget})')
    for pid, failures in reconciled.items():
        if pid in normalized:
            normalized[pid]['failed'] = failures
    return normalized, result, elapsed


def _normalize_layer_result(result):
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
            z_mm=value.get('z_mm'))
    return normalized


def _reconcile_layer_failures(layer_tasks, normalized):
    reconciled = {}
    for pid, payload in layer_tasks.items():
        entry = normalized.get(int(pid))
        if entry is None:
            continue
        routed_ids = {int(rid) for rid in entry['routed']}
        historical = {}
        for record in entry['failed']:
            historical.setdefault(int(record.get('route_id', -1)), record)
        failures = []
        for task in payload.get('tasks', []):
            rid = int(task['route_id'])
            if rid in routed_ids:
                continue
            record = dict(historical.get(rid) or {})
            record.setdefault('route_id', rid)
            record.setdefault('reason', 'layer2d_unrouted')
            failures.append(record)
        reconciled[int(pid)] = failures
    return reconciled


# ================================================================ assembly
def _body_lookup(routed, pid, rid):
    entry = routed.get(int(pid))
    if entry is None:
        return None
    payload = entry['routed'].get(rid)
    if payload is None:
        payload = entry['routed'].get(str(rid))
    if payload is None:
        return None
    return payload.get('primitives') if isinstance(payload, dict) else payload


def _assemble_all(rows, selected, routed, log=print):
    routes = []
    failures = []
    for row in rows:
        rid = int(row['route_id'])
        pid = int(row['target_layer'])
        body = _body_lookup(routed, pid, rid)
        if body is None:
            record = dict(route_id=rid, plane=row['plane'],
                          target_layer=pid,
                          target_plane_label=row.get('target_plane_label'),
                          manual_group=row.get('manual_group') or '',
                          reason='layer2d_failed')
            entry = routed.get(pid) or {}
            for failure in entry.get('failed') or []:
                if int(failure.get('route_id', -1)) == rid:
                    record['reason'] = ('layer2d_failed:'
                                        + str(failure.get('reason')))
                    record['detail'] = failure
                    break
            failures.append(record)
            continue
        try:
            if not row['needs_transition']:
                route = ASM.assemble_route(row, None, None, body)
            else:
                pair = selected.get(rid) or {}
                source = pair.get('source')
                target = pair.get('target')
                if source is None or target is None:
                    raise ASM.AssemblyError(rid, 'missing_transition')
                route = ASM.assemble_route(row, source, target, body)
        except ASM.AssemblyError as error:
            failures.append(dict(
                route_id=rid, plane=row['plane'], target_layer=pid,
                target_plane_label=row.get('target_plane_label'),
                manual_group=row.get('manual_group') or '',
                reason='assembly:' + error.reason, detail=dict(error.detail)))
            continue
        routes.append(route)
    return routes, failures


def _world_check(routes):
    return ASM.validate_routes_independent(routes, stack=M.layer_stack())


# ================================================================ repair
def _replan_leads(rows, selected, failed_ids, iteration, log=print):
    failed_ids = {int(rid) for rid in failed_ids}
    if not failed_ids:
        return selected
    row_by_id = {int(row['route_id']): row for row in rows}
    direct_failed = {rid for rid in failed_ids
                     if not row_by_id[rid]['needs_transition']}
    repair_ids = sorted(failed_ids - direct_failed)
    if not repair_ids:
        return selected
    fanout_mod = _load_fanout()
    fixed = {int(rid): value for rid, value in selected.items()
             if int(rid) not in failed_ids}
    leads = _LEAD_REPAIR_VARIANTS[(int(iteration) - 1)
                                  % len(_LEAD_REPAIR_VARIANTS)]
    try:
        result = fanout_mod.plan_fanout(
            rows, stack=M.layer_stack(), fixed=fixed,
            repair_ids=repair_ids, leads=leads, log=log)
    except Exception as error:  # noqa: BLE001
        log(f'[E] fanout lead repair failed: {error!r}')
        return selected
    merged = dict(selected)
    merged.update(fixed)
    for rid, value in (result.get('selected') or {}).items():
        merged[int(rid)] = value
    gained = sum(1 for rid in repair_ids if rid in result.get('selected') or {})
    log(f'[E] lead repair iteration {iteration}: leads={leads} '
        f'repaired={gained}/{len(repair_ids)} '
        f'direct_failures={sorted(direct_failed)}')
    return merged


def _layer_resolve(rows, selected, valid, routed, failed_rows, log=print,
                   max_seeds=16):
    """Whole-plane rip-up & re-solve with deterministic orderings."""
    from ...l3d.world import World
    layer2d_mod = _load_layer2d()
    fanout_mod = _load_fanout()
    row_by_id = {int(row['route_id']): row for row in rows}
    by_plane = {}
    for row in failed_rows:
        by_plane.setdefault(int(row['target_layer']), []).append(row)
    improved = []
    remaining_failures = []
    lead_blockers = _interface_lead_blockers(selected)
    for pid, plane_failed in sorted(by_plane.items()):
        z = M.plane_z(pid)
        plane_rows = [row for row in rows if int(row['target_layer']) == pid]
        if M.is_direct_plane(pid):
            blocked = dict(lead_blockers.get(pid, {}))
        else:
            blocked = {}
            for rid in [int(r['route_id']) for r in valid
                        if int(valid[int(r['route_id'])]['target_layer']) == pid]:
                body = ASM._body_primitives(valid[rid])
                if body is not None:
                    blocked[rid] = body
        obstacles = fanout_mod.layer_obstacles(selected, pid, layer_z=z)
        best_entries = None
        best_seed = None
        for seed in range(int(max_seeds)):
            tasks = []
            for row in plane_rows:
                rid = int(row['route_id'])
                record = selected.get(rid) or {}
                if row['needs_transition']:
                    src = record.get('source')
                    tgt = record.get('target')
                    if not src or not tgt:
                        continue
                    tasks.append(dict(
                        route_id=rid, manual_group=row.get('manual_group') or '',
                        relation=row.get('relation') or '',
                        source_side=row.get('source_side'),
                        target_side=row.get('target_side'),
                        A=tuple(src['end_xy']), dA=tuple(src['direction']),
                        B=tuple(tgt['end_xy']), dB=tuple(tgt['direction']),
                        direct=False))
                else:
                    eps = C.endpoints()
                    src_ep = row['source_endpoint']
                    tgt_ep = row['target_endpoint']
                    p_s = tuple(float(v) for v in eps[src_ep]['routing_xy'])
                    d_s = tuple(float(v) for v in eps[src_ep]['inward'])
                    p_t = tuple(float(v) for v in eps[tgt_ep]['routing_xy'])
                    d_t = tuple(float(v) for v in eps[tgt_ep]['inward'])
                    tasks.append(dict(
                        route_id=rid, manual_group=row.get('manual_group') or '',
                        relation=row.get('relation') or '',
                        source_side=row.get('source_side'),
                        target_side=row.get('target_side'),
                        A=p_s, dA=d_s, B=p_t, dB=d_t, direct=True))
            try:
                result = layer2d_mod.route_layer(
                    pid, z, tasks, obstacles=obstacles,
                    initial_routes=blocked, budget=2400, rr_rounds=2,
                    ordering_seed=seed, log=lambda *_a: None)
            except TypeError:
                result = layer2d_mod.route_layer(
                    pid, z, tasks, obstacles=obstacles, budget=2400,
                    rr_rounds=2, log=lambda *_a: None)
            entries = result.get('routed') or {}
            if best_entries is None or len(entries) > len(best_entries):
                best_entries = entries
                best_seed = seed
            if len(best_entries) >= len(tasks):
                break
        current_plane_ids = [int(rid) for rid in valid
                             if int(valid[int(rid)]['target_layer']) == pid]
        if best_entries is None or len(best_entries) <= len(current_plane_ids):
            remaining_failures.extend(plane_failed)
            log(f'[E] layer-resolve L{pid} ({z:+.2f}): no gain '
                f'(current={len(current_plane_ids)}, '
                f'best={len(best_entries or {})})')
            continue
        # verify in a world without the current plane routes
        world = World(M.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
        for rid, route in valid.items():
            if int(route['target_layer']) != pid:
                world.add_route(route)
        new_valid = {}
        ok = True
        for rid in sorted(best_entries):
            key = rid if rid in best_entries else str(rid)
            payload = best_entries[key]
            body = (payload.get('primitives')
                    if isinstance(payload, dict) else payload)
            row = row_by_id[int(rid)]
            try:
                if row['needs_transition']:
                    record = selected[int(rid)]
                    route = ASM.assemble_route(row, record['source'],
                                               record['target'], body)
                else:
                    route = ASM.assemble_route(row, None, None, body)
            except ASM.AssemblyError:
                ok = False
                break
            if world.check_route(route):
                ok = False
                break
            world.add_route(route)
            new_valid[int(rid)] = (route, body)
        if not ok:
            remaining_failures.extend(plane_failed)
            log(f'[E] layer-resolve L{pid}: best={len(best_entries)} '
                f'but assembly/world failed')
            continue
        for rid in current_plane_ids:
            valid.pop(rid, None)
        plane_routed = routed.setdefault(pid, dict(routed={}, failed=[],
                                                   stats={}, z_mm=z))
        plane_routed.setdefault('routed', {})
        recovered = []
        plane_failed_ids = {int(record['route_id'])
                            for record in plane_failed}
        for rid, (route, body) in new_valid.items():
            if rid in plane_failed_ids:
                recovered.append(rid)
            valid[rid] = route
            plane_routed['routed'][rid] = dict(primitives=body,
                                               family='LAYER_RESOLVE')
        improved.extend(recovered)
        log(f'[E] layer-resolve L{pid} ({z:+.2f}): committed '
            f'{len(new_valid)} routes (seed {best_seed}), '
            f'recovered={recovered}')
    return improved, remaining_failures


# ================================================================ stage C/D/E
def _experiment_c_summary(rows, routed, elapsed, log=print):
    assigned = Counter(int(row['target_layer']) for row in rows)
    cases = {'Z1_INTERFACE': 1001, 'Z2_INTERFACE': 1002}
    per_plane = {}
    for pid in M.PLANE_IDS:
        entry = routed.get(int(pid)) or {}
        routed_ids = {int(rid) for rid in (entry.get('routed') or {})}
        per_plane[str(pid)] = dict(
            plane_id=int(pid), label=M.plane_label(pid),
            z_mm=M.plane_z(pid), kind=M.plane_kind(pid),
            assigned=int(assigned.get(int(pid), 0)),
            routed=len(routed_ids),
            failed=int(assigned.get(int(pid), 0)) - len(routed_ids),
            stats=entry.get('stats') or {})
    interface_planes = {
        label: per_plane[str(pid)] for label, pid in cases.items()}
    total_assigned = sum(value['assigned'] for value in per_plane.values())
    total_routed = sum(value['routed'] for value in per_plane.values())
    summary = dict(
        schema='reheight21_experiment_c_v1', experiment='C',
        input_routes=len(rows), attempted_routes=len(rows),
        routed=total_routed, failed=total_assigned - total_routed,
        interface_planes=interface_planes, per_plane=per_plane,
        elapsed_seconds=round(elapsed, 2))
    out = M.RUN_DIR / 'experiment_C'
    out.mkdir(parents=True, exist_ok=True)
    _json_write(out / 'summary.json', summary)
    _json_write(M.RUN_DIR / 'checkpoints' / 'stage_C_2d.json', summary)
    log(f'[C] routed={total_routed}/{total_assigned} '
        f'Z1_INTERFACE={interface_planes["Z1_INTERFACE"]["routed"]}/52 '
        f'Z2_INTERFACE={interface_planes["Z2_INTERFACE"]["routed"]}/48')
    return summary


def _experiment_d_summary(routes, failures, violations, log=print):
    out = M.RUN_DIR / 'experiment_D'
    out.mkdir(parents=True, exist_ok=True)
    summary = dict(
        schema='reheight21_experiment_d_v1', experiment='D',
        input_routes=1024, assembled=len(routes),
        world_valid=len(routes) - len({int(rec.get('route_id', -1))
                                       for rec in violations}),
        assembly_failures=len(failures),
        world_violations=len(violations),
        violation_kinds=dict(Counter(rec.get('kind') for rec in violations)),
        failure_reasons=dict(Counter(rec.get('reason') for rec in failures)))
    _json_write(out / 'summary.json', summary)
    _json_write(out / 'failed_routes.json',
                dict(total=len(failures), failures=failures))
    log(f'[D] assembled={len(routes)} world_violations={len(violations)} '
        f'assembly_failures={len(failures)}')
    return summary


def _write_routes_payload(rows, routes, failed, history, log=print):
    stack_payload = M.stack_payload()
    process_payload = M.process_rules_payload()
    row_by_id = {int(row['route_id']): row for row in rows}
    records = []
    for route in sorted(routes, key=lambda item: int(item['route_id'])):
        record = dict(route)
        row = row_by_id[int(route['route_id'])]
        record.setdefault('target_plane', int(row['target_layer']))
        record.setdefault('target_plane_label', row.get('target_plane_label'))
        record.setdefault('needs_transition', bool(row['needs_transition']))
        record['direct'] = not bool(row['needs_transition'])
        records.append(record)
    for failure in sorted(failed, key=lambda item: int(item['route_id'])):
        record = dict(failure)
        record['status'] = 'failed'
        row = row_by_id.get(int(record['route_id']))
        if row is not None:
            record.setdefault('plane', row['plane'])
            record.setdefault('source_endpoint', row['source_endpoint'])
            record.setdefault('target_endpoint', row['target_endpoint'])
            record.setdefault('target_plane', int(row['target_layer']))
            record.setdefault('target_plane_label', row.get('target_plane_label'))
            record.setdefault('needs_transition', bool(row['needs_transition']))
        records.append(record)
    payload = dict(
        schema='reheight21_routes_l3d_v1',
        topology='MANUAL_C4',
        algorithm='FANOUT_FIRST_THEN_LAYERWISE_2D',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        process_mode='corrected_50um',
        layer_model='21 routing heights = 19 body planes + 2 routable interface planes',
        route_count=1024, routed=len(routes), failed=len(failed),
        layer_stack=stack_payload, process=process_payload,
        joint_repair_history=history,
        routes=records)
    _json_write(M.RUN_DIR / 'routes_l3d.json', payload)
    _json_write(M.RUN_DIR / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    log(f'[final] wrote routes_l3d.json: routed={len(routes)} '
        f'failed={len(failed)}')


def _write_final_stats(rows, routes, failed, history, best, log=print):
    by_plane = Counter()
    direct = 0
    transitions = 0
    total_length = 0.0
    max_length = 0.0
    for route in routes:
        plane = int(route.get('target_plane', route.get('target_layer')))
        by_plane[str(plane)] += 1
        if not route.get('n_transitions'):
            direct += 1
        transitions += int(route.get('n_transitions') or 0)
        length = float(route.get('length_mm') or 0.0)
        total_length += length
        max_length = max(max_length, length)
    by_plane_role = Counter()
    for row in rows:
        by_plane_role[f"{row['layer_role']}:{int(row['target_layer'])}"] += 1
    stats = dict(
        schema='reheight21_final_stats_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        input_routes=1024, attempted_routes=1024,
        routed=len(routes), failed=len(failed),
        z1_routed=sum(1 for route in routes if route.get('plane') == 'z1'),
        z2_routed=sum(1 for route in routes if route.get('plane') == 'z2'),
        direct_routes=direct, transition_routes=len(routes) - direct,
        total_transitions=transitions,
        per_plane_routed=dict(sorted(by_plane.items(),
                                     key=lambda item: int(item[0]))),
        per_plane_assigned=dict(sorted(
            ((str(pid), int(Counter(int(row['target_layer'])
                                    for row in rows).get(pid, 0)))
             for pid in M.PLANE_IDS),
            key=lambda item: int(item[0]))),
        failure_reasons=dict(Counter(record.get('reason')
                                     for record in failed)),
        failed_route_ids=sorted(int(record['route_id']) for record in failed),
        total_length_mm=round(total_length, 3),
        max_route_length_mm=round(max_length, 3),
        min_3d_clearance_mm=C.MIN_3D_CLEARANCE_MM,
        radius_mm=C.MIN_BEND_RADIUS_MM,
        process_mode='corrected_50um',
        world_violations=len(best.get('violations') or []),
        joint_repair_iterations=len(history),
        per_plane_roles=dict(sorted(by_plane_role.items())),
        note='only routes passing the strict 0.05 mm 3D world check count as '
             'routed; failures carry real route ids and reasons',
    )
    _json_write(M.RUN_DIR / 'final_stats.json', stats)
    return stats


def _write_experiment_e(rows, best, failed, history, log=print):
    out = M.RUN_DIR / 'experiment_E'
    out.mkdir(parents=True, exist_ok=True)
    assigned = Counter(int(row['target_layer']) for row in rows)
    per_plane = {}
    for pid in M.PLANE_IDS:
        entry = (best.get('routed') or {}).get(int(pid)) or {}
        routed_ids = {int(rid) for rid in (entry.get('routed') or {})}
        plane_failed = [dict(record) for record in (entry.get('failed') or [])
                        if int(record.get('route_id', -1)) not in routed_ids]
        known = {int(record['route_id']) for record in plane_failed}
        for record in failed:
            rid = int(record['route_id'])
            if record.get('target_plane') is not None \
                    and int(record['target_plane']) == int(pid) \
                    and rid not in known and rid not in routed_ids:
                plane_failed.append(dict(record))
                known.add(rid)
        per_plane[str(pid)] = dict(
            plane_id=int(pid), label=M.plane_label(pid),
            z_mm=M.plane_z(pid), kind=M.plane_kind(pid),
            assigned=int(assigned.get(int(pid), 0)),
            routed=len(routed_ids),
            failed=int(assigned.get(int(pid), 0)) - len(routed_ids),
            failed_routes=plane_failed)
    summary = dict(
        schema='reheight21_experiment_e_v1', experiment='E',
        input_routes=1024, attempted_routes=1024,
        successful_routes=len(best['valid']),
        failed_routes=len(failed),
        failure_reasons=dict(Counter(record.get('reason')
                                     for record in failed)),
        per_plane=per_plane, iterations=history,
        validation=dict(world_valid=len(best['valid']),
                        violations=len(best.get('violations') or []),
                        strict_clearance_mm=C.MIN_3D_CLEARANCE_MM,
                        status='passed' if not best.get('violations')
                        else 'failed'),
        artifact='routes_l3d.json')
    _json_write(out / 'summary.json', summary)
    _json_write(out / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    _json_write(out / 'violations.json',
                dict(total=len(best.get('violations') or []),
                     violations=best.get('violations') or []))
    payload = dict(schema='reheight21_layerwise_routes_v1', layers={})
    for pid, entry in (best.get('routed') or {}).items():
        payload['layers'][str(pid)] = dict(
            plane_id=int(pid), label=M.plane_label(int(pid)),
            z_mm=M.plane_z(int(pid)), kind=M.plane_kind(int(pid)),
            routes={str(rid): dict(value)
                    for rid, value in (entry.get('routed') or {}).items()},
            failed=[dict(record) for record in (entry.get('failed') or [])],
            stats=entry.get('stats') or {})
    _json_write(M.RUN_DIR / 'layerwise_routes' / 'routes.json', payload)
    _json_write(M.RUN_DIR / 'checkpoints' / 'experiment_E_best.json',
                dict(score=len(best['valid']),
                     iteration=best.get('iteration'),
                     violations=len(best.get('violations') or [])))
    log(f'[E] wrote experiment_E summary ({len(best["valid"])} valid)')
    return summary


def _local_insert(rows, selected, best, log=print):
    """Fit failed routes into the frozen accepted layout (single-route insert)."""
    from ...l3d.world import World
    layer2d_mod = _load_layer2d()
    fanout_mod = _load_fanout()
    valid = dict(best['valid'])
    routed = {int(pid): dict(value) for pid, value in
              (best.get('routed') or {}).items()}
    failed_rows = [row for row in rows
                   if int(row['route_id']) not in valid]
    if not failed_rows:
        return valid, routed, [], []
    log(f'[local-insert] attempting {len(failed_rows)} failed routes')
    world = World(M.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
    frozen_bodies = {}
    for rid in sorted(valid):
        route = valid[rid]
        world.add_route(route)
        body = _body_primitives_of(route)
        if body is not None:
            frozen_bodies.setdefault(int(route['target_layer']),
                                     {})[int(rid)] = body
    lead_blockers = _interface_lead_blockers(selected)
    obstacles_by_plane = {pid: fanout_mod.layer_obstacles(
        selected, pid, layer_z=M.plane_z(pid)) for pid in M.PLANE_IDS}
    repaired = []
    remaining = []
    for row in sorted(failed_rows, key=lambda item: int(item['route_id'])):
        rid = int(row['route_id'])
        pid = int(row['target_layer'])
        z = M.plane_z(pid)
        direct = not row['needs_transition']
        frozen = dict(frozen_bodies.get(pid, {}))
        if M.is_direct_plane(pid):
            frozen.update(lead_blockers.get(pid, {}))
        obstacles = [item for item in obstacles_by_plane.get(pid, [])
                     if item.get('route_id') != rid]
        outcome = None
        lead_pairs = ((0.0, 0.0),) if direct else _LEAD_PAIRS
        for lead_pair in lead_pairs:
            if direct:
                eps = C.endpoints()
                p_s = tuple(float(v) for v in eps[row['source_endpoint']]['routing_xy'])
                d_s = tuple(float(v) for v in eps[row['source_endpoint']]['inward'])
                p_t = tuple(float(v) for v in eps[row['target_endpoint']]['routing_xy'])
                d_t = tuple(float(v) for v in eps[row['target_endpoint']]['inward'])
                task = dict(route_id=rid,
                            manual_group=row.get('manual_group') or '',
                            relation=row.get('relation') or '',
                            source_side=row.get('source_side'),
                            target_side=row.get('target_side'),
                            A=p_s, dA=d_s, B=p_t, dB=d_t, direct=True)
                src = tgt = None
            else:
                try:
                    src = fanout_mod.candidate_transitions(
                        row, 'source', pid, leads=[lead_pair[0]])[0]
                    tgt = fanout_mod.candidate_transitions(
                        row, 'target', pid, leads=[lead_pair[1]])[0]
                except Exception:  # noqa: BLE001
                    continue
                partial_s = fanout_mod.partial_route(row, 'source', src,
                                                     2 * rid)
                partial_t = fanout_mod.partial_route(row, 'target', tgt,
                                                     2 * rid + 1)
                if world.check_route(partial_s) or world.check_route(partial_t):
                    continue
                task = dict(route_id=rid,
                            manual_group=row.get('manual_group') or '',
                            relation=row.get('relation') or '',
                            source_side=row.get('source_side'),
                            target_side=row.get('target_side'),
                            A=tuple(src['end_xy']), dA=tuple(src['direction']),
                            B=tuple(tgt['end_xy']), dB=tuple(tgt['direction']),
                            direct=False)
            try:
                result = layer2d_mod.route_layer(
                    pid, z, [task], obstacles=obstacles,
                    initial_routes=frozen, budget=2400, rr_rounds=0,
                    log=lambda *_a: None)
            except TypeError:
                result = layer2d_mod.route_layer(
                    pid, z, [task], obstacles=obstacles,
                    budget=2400, rr_rounds=0, log=lambda *_a: None)
            entries = result.get('routed') or {}
            payload = entries.get(rid) or entries.get(str(rid))
            if payload is None:
                continue
            body = (payload.get('primitives')
                    if isinstance(payload, dict) else payload)
            try:
                if direct:
                    route = ASM.assemble_route(row, None, None, body)
                else:
                    route = ASM.assemble_route(row, src, tgt, body)
            except ASM.AssemblyError:
                continue
            if world.check_route(route):
                continue
            world.add_route(route)
            outcome = dict(route=route, body=body, source=src, target=tgt)
            break
        if outcome is None:
            remaining.append(row)
            continue
        valid[rid] = outcome['route']
        if not direct:
            selected[rid] = dict(source=outcome['source'],
                                 target=outcome['target'])
        frozen_bodies.setdefault(pid, {})[rid] = outcome['body']
        plane_entry = routed.setdefault(pid, dict(routed={}, failed=[],
                                                  stats={}, z_mm=z))
        plane_entry.setdefault('routed', {})[rid] = dict(
            primitives=outcome['body'], family='LOCAL_INSERT')
        repaired.append(rid)
    failures = [dict(route_id=int(row['route_id']), reason='local_insert_failed')
                for row in remaining]
    log(f'[local-insert] repaired={len(repaired)} remaining={len(remaining)}')
    return valid, routed, repaired, failures


# ================================================================ stage E
def stage_e(rows, selected, log=print, max_iters=3):
    history = []
    best = None
    previous_failed_ids = []
    for iteration in range(1, int(max_iters) + 1):
        log(f'=== STAGE E iteration {iteration}/{max_iters} ===')
        if iteration > 1 and previous_failed_ids:
            selected = _replan_leads(rows, selected, previous_failed_ids,
                                     iteration, log=log)
        budget = _LAYER_BUDGETS[(iteration - 1) % len(_LAYER_BUDGETS)]
        routed, raw, elapsed = _route_all_layers(
            rows, selected, budget=budget, seed=iteration - 1, log=log)
        routes, assembly_failures = _assemble_all(rows, selected, routed, log=log)
        check = _world_check(routes)
        valid = check['valid']
        violations = check['violations']
        score = len(valid)
        valid_ids = set(valid)
        failed_ids = sorted(
            {int(record['route_id']) for record in assembly_failures}
            | {int(record.get('route_id', -1)) for record in violations}
            - valid_ids)
        failed_ids = [rid for rid in failed_ids if rid not in valid_ids]
        record = dict(iteration=iteration, routed_2d=sum(
            len(value['routed']) for value in routed.values()),
            assembled=len(routes), world_valid=score,
            violations=len(violations),
            violation_kinds=dict(Counter(rec.get('kind')
                                         for rec in violations)),
            assembly_failures=len(assembly_failures),
            lead_repair=bool(iteration > 1 and previous_failed_ids),
            budget=budget,
            layer_stats={int(pid): value.get('stats')
                         for pid, value in routed.items()},
            failed_route_ids=failed_ids)
        history.append(record)
        log(f'[E] iteration {iteration}: assembled={len(routes)} '
            f'world_valid={score} violations={len(violations)} '
            f'assembly_failures={len(assembly_failures)} '
            f'failed_ids={failed_ids}')
        if best is None or score > best['score'] or (
                score == best['score']
                and len(violations) < len(best.get('violations') or [])):
            best = dict(score=score, valid=valid, routes=routes,
                        violations=violations, routed=routed,
                        assembly_failures=assembly_failures,
                        iteration=iteration)
        previous_failed_ids = failed_ids
        if score == len(rows) and not violations:
            log('[E] all 1024 routes valid')
            break
    if best is None:
        raise RuntimeError('stage E produced no state')
    # ---- local single-route insertion into the frozen best layout
    valid, routed, repaired, local_failures = _local_insert(rows, selected, best)
    if repaired:
        best = dict(best)
        best['valid'] = valid
        best['routed'] = routed
        best['score'] = len(valid)
        history.append(dict(stage='local_insert', repaired=len(repaired),
                            world_valid=len(valid)))
        # refresh transitions artifacts for repaired routes
        _refresh_fanout_for_repairs(rows, selected, log=log)
    # ---- whole-plane rip-up & re-solve for the remaining failures
    failed_rows = [row for row in rows if int(row['route_id']) not in valid]
    if failed_rows:
        recovered, remaining = _layer_resolve(rows, selected, valid, routed,
                                              failed_rows, log=log)
        if recovered:
            best = dict(best)
            best['valid'] = valid
            best['routed'] = routed
            best['score'] = len(valid)
            history.append(dict(stage='layer_resolve',
                                recovered=recovered,
                                world_valid=len(valid)))
            _refresh_fanout_for_repairs(rows, selected, log=log)
            failed_rows = remaining
    failed_map = {int(record['route_id']): dict(record)
                  for record in (best.get('assembly_failures') or [])}
    failed = []
    for row in failed_rows:
        rid = int(row['route_id'])
        record = failed_map.get(rid) or dict(
            route_id=rid, plane=row['plane'],
            target_layer=int(row['target_layer']),
            target_plane_label=row.get('target_plane_label'),
            manual_group=row.get('manual_group') or '',
            reason='unresolved_after_joint_repair')
        record.setdefault('target_plane', int(row['target_layer']))
        failed.append(record)
    routes = [best['valid'][rid] for rid in sorted(best['valid'])]
    _write_routes_payload(rows, routes, failed, history, log=log)
    _write_experiment_e(rows, best, failed, history, log=log)
    stats = _write_final_stats(rows, routes, failed, history, best, log=log)
    log(f'[E] FINAL routed={stats["routed"]}/1024 failed={stats["failed"]} '
        f'direct={stats["direct_routes"]} transitions={stats["total_transitions"]}')
    return dict(routes=routes, failed=failed, best=best, history=history,
                stats=stats)


def stage_finalize(log=print):
    """Rewrite experiment_D as the FINAL accepted 3D assembly + world check."""
    rows = read_assignment()
    payload = C.read_json(M.RUN_DIR / 'routes_l3d.json')
    routes = [record for record in payload['routes']
              if record.get('status') != 'failed']
    check = ASM.validate_routes_independent(routes, stack=M.layer_stack())
    valid = check['valid']
    violations = check['violations']
    failed = [record for record in payload['routes']
              if record.get('status') == 'failed']
    out = M.RUN_DIR / 'experiment_D'
    out.mkdir(parents=True, exist_ok=True)
    summary = dict(
        schema='reheight21_experiment_d_v1', experiment='D',
        stage='final_full_3d_assembly_and_world_check',
        input_routes=1024, assembled=len(routes),
        world_valid=len(valid), failed=len(failed),
        assembly_failures=len(failed),
        world_violations=len(violations),
        violation_kinds=dict(Counter(rec.get('kind') for rec in violations)),
        failure_reasons=dict(Counter(rec.get('reason') for rec in failed)),
        direct_routes=sum(1 for record in routes
                          if not record.get('n_transitions')),
        transition_count=sum(int(record.get('n_transitions') or 0)
                             for record in routes),
        note='final accepted assembly after joint repair; identical route set '
             'to routes_l3d.json and experiment_E')
    _json_write(out / 'summary.json', summary)
    _json_write(out / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    log(f'[F] experiment_D final: assembled={len(routes)} '
        f'world_valid={len(valid)} violations={len(violations)}')
    return summary


def _refresh_fanout_for_repairs(rows, selected, log=print):
    validation = validate_fanout_selected(rows, selected, log=log)
    _json_write(M.RUN_DIR / 'fanout_selected.json', dict(
        schema='reheight21_fanout_selected_v1',
        route_count=len(selected),
        direct_routes=sum(1 for row in rows if not row['needs_transition']),
        transition_count=validation.get('transition_count'),
        selected={str(rid): selected[rid] for rid in sorted(selected)}))
    _json_write(M.RUN_DIR / 'fanout_validation.json', validation)
    # refresh endpoint table for the final selected set
    eps = C.endpoints()
    endpoints = []
    for row in rows:
        rid = int(row['route_id'])
        pair = selected.get(rid) or {}
        for role in ('source', 'target'):
            record = dict(pair.get(role) or {})
            record.setdefault('route_id', rid)
            record.setdefault('endpoint_role', role)
            record.setdefault('plane', row['plane'])
            record.setdefault('target_layer', int(row['target_layer']))
            record.setdefault('target_plane_label', row.get('target_plane_label'))
            record.setdefault('target_z_mm', float(row['target_z_mm']))
            endpoints.append(record)
    _json_write(M.RUN_DIR / 'layerwise_endpoints' / 'endpoints.json', dict(
        schema='reheight21_layerwise_endpoints_v1',
        endpoint_count=len(endpoints), endpoints=endpoints))


# ================================================================ main
_STAGES = 'ABCDE'


def run_stages(stages='ABCDE', max_iters=3, log=print):
    _ensure_run_dir()
    rows = stage_a(log=log)
    selected = None
    if 'B' in stages or 'C' in stages or 'D' in stages or 'E' in stages:
        selected, fanout_failures, fanout_validation = stage_b(rows, log=log)
        _json_write(M.RUN_DIR / 'checkpoints' / 'fanout_failures.json',
                    dict(total=len(fanout_failures),
                         failures=fanout_failures))
    if 'C' in stages:
        routed, raw, elapsed = _route_all_layers(
            rows, selected, budget=_LAYER_BUDGETS[0], seed=0, log=log,
            lead_blockers=_interface_lead_blockers(selected))
        _experiment_c_summary(rows, routed, elapsed, log=log)
        routes, assembly_failures = _assemble_all(rows, selected, routed, log=log)
        check = _world_check(routes)
        _experiment_d_summary(routes, assembly_failures,
                              check['violations'], log=log)
    if 'D' in stages:
        routed, raw, elapsed = _route_all_layers(
            rows, selected, budget=_LAYER_BUDGETS[0], seed=0, log=log)
        routes, assembly_failures = _assemble_all(rows, selected, routed, log=log)
        check = _world_check(routes)
        _experiment_d_summary(routes, assembly_failures,
                              check['violations'], log=log)
    result = None
    if 'E' in stages:
        result = stage_e(rows, selected, log=log, max_iters=max_iters)
    if 'F' in stages:
        stage_finalize(log=log)
    return dict(rows=rows, selected=selected, result=result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', default='ABCDE')
    parser.add_argument('--max-iters', type=int, default=3)
    args = parser.parse_args(argv)
    log = make_logger()
    log(f'run21 stages={args.stages} max_iters={args.max_iters}')
    started = time.time()
    result = run_stages(args.stages, max_iters=args.max_iters, log=log)
    log(f'run21 done in {time.time() - started:.1f}s')
    return result


if __name__ == '__main__':
    main()
