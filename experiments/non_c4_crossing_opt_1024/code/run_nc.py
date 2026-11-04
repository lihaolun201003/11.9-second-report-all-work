# -*- coding: utf-8 -*-
"""Pipeline driver for the C4-free crossing-optimisation experiments.

Design decisions that differ from the frozen 21-height experiment (all of them
required by the new research brief):

* the 368 manual U routes keep their **exact verified 21-height geometry**:
  their fanout transitions are re-inserted as ``fixed`` world citizens and their
  2D bodies are never re-routed (frozen D56 blockers), so no crossing metric can
  be bought by moving them;
* the C4 rotation-orbit binding is gone: each non-manual ``route_id`` carries
  its own plane (see :mod:`nonc4.assign_nc`);
* every other stage (fanout, layer-wise 2D R15 routing, 3D assembly, strict
  0.05 mm world check) reuses the frozen production modules unchanged.

Stages:

A  C4-free assignment + audit                     -- ``assign_nc``
B  fanout around the frozen manual transitions    -- :func:`stage_b`
C  per-height 2D body routing                     -- :func:`route_layers`
D  full 3D assembly + strict world check          -- :func:`assemble_and_check`
E  joint repair loop + final artifacts            -- :func:`run_pipeline`
"""
from __future__ import annotations

import copy
import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import assemble as ASM
from .. import common as C
from .. import fanout as FANOUT
from .. import layer2d as LAYER2D
from ..reheight21 import model as M
from ..reheight21 import run21
from . import assign_nc
from . import crossings as X
from . import data as D
from . import paths as P


# --------------------------------------------------------------------- logging
def make_logger(exp_dir, tag='nonc4'):
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / 'run.log'

    def log(message):
        line = time.strftime('%H:%M:%S') + f' [{tag}] ' + str(message)
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


def _write_json(path, payload):
    C.write_json(Path(path), payload)


# ------------------------------------------------------ frozen manual geometry
def load_baseline_manual_routes():
    """``{route_id: route record}`` of the 368 frozen manual routes."""
    rows = D.load_baseline_assignment()
    manual_ids = {int(row['route_id']) for row in rows if D.is_manual(row)}
    routes = {}
    for record in D.baseline_routes():
        route_id = int(record['route_id'])
        if route_id in manual_ids:
            routes[route_id] = record
    missing = sorted(manual_ids - set(routes))
    if missing:
        raise RuntimeError(f'baseline is missing manual routes: {missing[:10]}')
    return routes


def load_baseline_manual_fanout():
    """``{route_id: {'source': record, 'target': record}}`` of frozen manuals."""
    rows = D.load_baseline_assignment()
    manual_ids = {int(row['route_id']) for row in rows if D.is_manual(row)}
    selected = D.baseline_fanout_selected()
    out = {}
    for route_id in manual_ids:
        pair = selected.get(route_id)
        if pair:
            out[route_id] = pair
    return out


def frozen_manual_bodies():
    """``{plane_id: {route_id: [primitives]}}`` of the frozen manual 2D bodies."""
    routes = load_baseline_manual_routes()
    out = {}
    for route_id, record in routes.items():
        pid = int(record.get('target_layer', record.get('target_plane')))
        body = D.body_primitives(record)
        if body:
            out.setdefault(pid, {})[route_id] = body
    return out


# --------------------------------------------------------------------- stage B
def stage_b(rows, log=print, fixed_manual=True):
    """Fanout planning with the frozen manual transitions fixed in the world."""
    log('=== STAGE B: fanout (R15 S transitions, manual transitions frozen) ===')
    fixed = load_baseline_manual_fanout() if fixed_manual else None
    started = time.time()
    result = FANOUT.plan_fanout(rows, stack=M.layer_stack(), fixed=fixed,
                                log=log)
    selected = {int(rid): value
                for rid, value in (result.get('selected') or {}).items()}
    missing = [int(row['route_id']) for row in rows
               if int(row['route_id']) not in selected]
    failures = run21._fanout_failures(result, rows)
    for route_id in missing:
        if any(int(record['route_id']) == route_id for record in failures):
            continue
        failures.append(dict(route_id=route_id, reason='fanout_no_record'))
    failures.sort(key=lambda record: int(record['route_id']))
    validation = run21.validate_fanout_selected(rows, selected, log=log)
    run21._fanout_artifacts(rows, selected, validation, failures,
                            result.get('stats') or {}, log=log)
    fixed_conflicts = result.get('fixed_conflicts') or []
    _write_json(M.RUN_DIR / 'checkpoints' / 'stage_B_fanout.json', dict(
        selected_routes=len(selected), failures=len(failures),
        fixed_routes=len(fixed or {}),
        fixed_conflicts=len(fixed_conflicts),
        fixed_conflict_examples=fixed_conflicts[:10],
        validation=validation, seconds=round(time.time() - started, 1)))
    log(f'[B] fanout done: selected={len(selected)} failures={len(failures)} '
        f'fixed_manual={len(fixed or {})} '
        f'fixed_conflicts={len(fixed_conflicts)} '
        f'transitions={validation.get("transition_count")} '
        f'validation_ok={validation.get("ok")} '
        f'({time.time() - started:.1f}s)')
    return selected, failures, validation, fixed_conflicts


# --------------------------------------------------------------------- stage C
def build_layer_tasks(rows, selected):
    """Per-plane 2D tasks: non-manual routes only (manual bodies are frozen)."""
    landings = FANOUT.landings(selected)
    by_plane = OrderedDict()
    for pid in M.PLANE_IDS:
        by_plane[int(pid)] = dict(plane_id=int(pid), label=M.plane_label(pid),
                                  z_mm=float(M.plane_z(pid)), tasks=[],
                                  obstacles=[])
    for row in rows:
        if D.is_manual(row):
            continue
        route_id = int(row['route_id'])
        pid = int(row['target_layer'])
        pose = landings.get(route_id)
        if pose is None:
            continue
        by_plane[pid]['tasks'].append(
            run21._task_from_pose(row, pose, not row['needs_transition']))
    for pid, entry in by_plane.items():
        entry['obstacles'] = FANOUT.layer_obstacles(
            selected, pid, layer_z=entry['z_mm'])
    return by_plane


def initial_routes_for(selected, layer_tasks=None):
    """Frozen same-layer blockers: interface leads + manual bodies."""
    lead_blockers = run21._interface_lead_blockers(selected)
    manual_bodies = frozen_manual_bodies()
    out = {}
    for pid in M.PLANE_IDS:
        frozen = {}
        frozen.update(lead_blockers.get(int(pid), {}))
        frozen.update(manual_bodies.get(int(pid), {}))
        if frozen:
            out[int(pid)] = frozen
    return out


def route_layers(rows, selected, budget=600, seed=0, log=print, router=None,
                 layer_tasks=None, initial_routes=None, layer2d_module=None):
    """Per-height 2D routing (manual bodies frozen, interface leads fixed)."""
    mod = layer2d_module or router or LAYER2D
    layer_tasks = layer_tasks or build_layer_tasks(rows, selected)
    if initial_routes is None:
        initial_routes = initial_routes_for(selected)
    tasks_payload = {int(pid): dict(z_mm=entry['z_mm'], tasks=entry['tasks'],
                                    obstacles=entry['obstacles'])
                     for pid, entry in layer_tasks.items()}
    started = time.time()
    try:
        result = mod.route_all_layers(
            tasks_payload, out_dir=None, log=log, ordering_seed=seed,
            budget=budget, initial_routes=initial_routes)
    except TypeError:
        result = mod.route_all_layers(tasks_payload, out_dir=None, log=log)
    normalized = run21._normalize_layer_result(result)
    elapsed = time.time() - started
    reconciled = run21._reconcile_layer_failures(tasks_payload, normalized)
    for pid, failures in reconciled.items():
        if pid in normalized:
            normalized[pid]['failed'] = failures
    routed_total = sum(len(value['routed']) for value in normalized.values())
    failed_total = sum(len(value) for value in reconciled.values())
    log(f'[layer2d] planes={len(normalized)} routed={routed_total} '
        f'failed={failed_total} ({elapsed:.1f}s, seed={seed}, budget={budget})')
    return normalized, result, elapsed, tasks_payload


# ---------------------------------------------------------------- stage D
def assemble_all(rows, selected, routed, manual_routes=None, log=print):
    """Assemble all 1024 3D routes; the manual ones are copied from baseline."""
    manual_routes = manual_routes if manual_routes is not None else \
        load_baseline_manual_routes()
    routes = []
    failures = []
    for row in rows:
        route_id = int(row['route_id'])
        pid = int(row['target_layer'])
        if D.is_manual(row):
            record = manual_routes.get(route_id)
            if record is None:
                failures.append(dict(route_id=route_id, plane=row['plane'],
                                     target_layer=pid, reason='missing_manual'))
                continue
            routes.append(copy.deepcopy(record))
            continue
        body = run21._body_lookup(routed, pid, route_id)
        if body is None:
            record = dict(route_id=route_id, plane=row['plane'],
                          target_layer=pid,
                          target_plane_label=row.get('target_plane_label'),
                          manual_group='', reason='layer2d_failed')
            entry = routed.get(pid) or {}
            for failure in entry.get('failed') or ():
                if int(failure.get('route_id', -1)) == route_id:
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
                pair = selected.get(route_id) or {}
                source = pair.get('source')
                target = pair.get('target')
                if source is None or target is None:
                    raise ASM.AssemblyError(route_id, 'missing_transition')
                route = ASM.assemble_route(row, source, target, body)
        except ASM.AssemblyError as error:
            failures.append(dict(
                route_id=route_id, plane=row['plane'], target_layer=pid,
                target_plane_label=row.get('target_plane_label'),
                manual_group='', reason='assembly:' + error.reason,
                detail=dict(error.detail)))
            continue
        routes.append(route)
    return routes, failures


def assemble_and_check(rows, selected, routed, log=print):
    routes, assembly_failures = assemble_all(rows, selected, routed, log=log)
    check = run21._world_check(routes)
    return routes, assembly_failures, check


# ------------------------------------------------------------------- artifacts
def _route_records_for_payload(routes, rows):
    row_by_id = {int(row['route_id']): row for row in rows}
    records = []
    for route in sorted(routes, key=lambda item: int(item['route_id'])):
        record = dict(route)
        row = row_by_id.get(int(record['route_id']))
        if row is not None:
            record.setdefault('target_plane', int(row['target_layer']))
            record.setdefault('target_plane_label', row.get('target_plane_label'))
            record.setdefault('needs_transition', bool(row['needs_transition']))
            record['direct'] = not bool(row['needs_transition'])
        records.append(record)
    return records


def write_routes_payload(exp_dir, rows, routes, failed, history,
                         experiment='', log=print):
    exp_dir = Path(exp_dir)
    records = _route_records_for_payload(routes, rows)
    row_by_id = {int(row['route_id']): row for row in rows}
    for failure in sorted(failed, key=lambda item: int(item['route_id'])):
        record = dict(failure)
        record['status'] = 'failed'
        row = row_by_id.get(int(record.get('route_id', -1)))
        if row is not None:
            record.setdefault('plane', row['plane'])
            record.setdefault('source_endpoint', row['source_endpoint'])
            record.setdefault('target_endpoint', row['target_endpoint'])
            record.setdefault('target_plane', int(row['target_layer']))
            record.setdefault('target_plane_label',
                              row.get('target_plane_label'))
            record.setdefault('needs_transition', bool(row['needs_transition']))
        records.append(record)
    payload = dict(
        schema='nonc4_routes_l3d_v1',
        topology='NON_C4_PER_ROUTE_ASSIGNMENT',
        algorithm='FANOUT_FIRST_THEN_LAYERWISE_2D',
        experiment=experiment,
        parent_experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        c4_binding='removed',
        manual_geometry='frozen from FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        process_mode='corrected_50um',
        layer_model=('21 routing heights = 19 body planes + 2 routable '
                     'interface planes; one body plane per route'),
        route_count=1024, routed=len(routes), failed=len(failed),
        layer_stack=M.stack_payload(), process=M.process_rules_payload(),
        joint_repair_history=history, routes=records)
    _write_json(exp_dir / 'routes_l3d.json', payload)
    _write_json(exp_dir / 'failed_routes.json',
                dict(total=len(failed),
                     failures=sorted(failed,
                                     key=lambda item: int(item['route_id']))))
    log(f'[final] wrote routes_l3d.json: routed={len(routes)} '
        f'failed={len(failed)}')
    return payload


def write_final_stats(exp_dir, rows, routes, failed, history, best,
                      experiment='', log=print):
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
    by_role = Counter()
    for row in rows:
        by_role[f"{row['layer_role']}:{int(row['target_layer'])}"] += 1
    stats = dict(
        schema='nonc4_final_stats_v1',
        experiment=experiment,
        c4_binding='removed',
        input_routes=1024, attempted_routes=1024,
        routed=len(routes), failed=len(failed),
        z1_routed=sum(1 for route in routes if route.get('plane') == 'z1'),
        z2_routed=sum(1 for route in routes if route.get('plane') == 'z2'),
        direct_routes=direct, transition_routes=len(routes) - direct,
        total_transitions=transitions,
        per_plane_routed=dict(sorted(by_plane.items(),
                                     key=lambda item: int(item[0]))),
        total_length_mm=round(total_length, 3),
        max_route_length_mm=round(max_length, 3),
        min_3d_clearance_rule_mm=C.MIN_3D_CLEARANCE_MM,
        radius_mm=C.MIN_BEND_RADIUS_MM,
        process_mode='corrected_50um',
        world_violations=len(best.get('violations') or []),
        joint_repair_iterations=len([item for item in history
                                     if 'iteration' in item]),
        per_plane_roles=dict(sorted(by_role.items())),
        note=('only routes passing the strict 0.05 mm 3D world check count '
              'as routed; failed routes carry real route ids and reasons'),
    )
    _write_json(exp_dir / 'final_stats.json', stats)
    return stats


def write_experiment_e(exp_dir, rows, best, failed, history,
                       experiment='', log=print):
    out = Path(exp_dir) / 'experiment_E'
    out.mkdir(parents=True, exist_ok=True)
    assigned = Counter(int(row['target_layer']) for row in rows)
    per_plane = {}
    for pid in M.PLANE_IDS:
        entry = (best.get('routed') or {}).get(int(pid)) or {}
        routed_ids = {int(rid) for rid in (entry.get('routed') or {})}
        manual_count = sum(1 for row in rows
                           if D.is_manual(row)
                           and int(row['target_layer']) == int(pid))
        per_plane[str(pid)] = dict(
            plane_id=int(pid), label=M.plane_label(pid),
            z_mm=M.plane_z(pid), kind=M.plane_kind(pid),
            assigned=int(assigned.get(int(pid), 0)),
            routed=len(routed_ids) + manual_count,
            routed_2d=len(routed_ids), manual_frozen=manual_count,
            failed=int(assigned.get(int(pid), 0)) - len(routed_ids)
            - manual_count)
    summary = dict(
        schema='nonc4_experiment_e_v1', experiment='E',
        experiment_name=experiment,
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
    _write_json(out / 'summary.json', summary)
    _write_json(out / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    _write_json(out / 'violations.json',
                dict(total=len(best.get('violations') or []),
                     violations=best.get('violations') or []))
    _write_json(Path(exp_dir) / 'checkpoints' / 'experiment_E_best.json',
                dict(score=len(best['valid']),
                     iteration=best.get('iteration'),
                     violations=len(best.get('violations') or [])))
    return summary


def write_experiment_c(exp_dir, rows, routed, elapsed, log=print):
    out = Path(exp_dir) / 'experiment_C'
    out.mkdir(parents=True, exist_ok=True)
    assigned = Counter(int(row['target_layer']) for row in rows)
    per_plane = []
    total_routed = 0
    for pid in M.PLANE_IDS:
        entry = routed.get(int(pid)) or {}
        stats = entry.get('stats') or {}
        count = len(entry.get('routed') or {})
        total_routed += count
        per_plane.append(dict(
            plane_id=int(pid), label=M.plane_label(pid),
            z_mm=float(M.plane_z(pid)), kind=M.plane_kind(pid),
            assigned=int(assigned.get(int(pid), 0)), routed=count,
            failed=len(entry.get('failed') or []),
            seconds=round(float(stats.get('seconds') or 0.0), 3),
            families=stats.get('families') or {},
            crossings_router=(stats.get('crossings_after')
                              if 'crossings_after' in stats else None),
            input=stats.get('input')))
    summary = dict(
        schema='nonc4_experiment_c_v1', experiment='C',
        routed=total_routed, input=1024, failed=1024 - total_routed,
        seconds=round(float(elapsed), 2), per_plane=per_plane,
        note=('2D body routing pass of the accepted best iteration; manual '
              'bodies were frozen, not re-routed'))
    _write_json(out / 'summary.json', summary)
    return summary


def write_experiment_d(exp_dir, rows, routes, failed, check, log=print):
    out = Path(exp_dir) / 'experiment_D'
    out.mkdir(parents=True, exist_ok=True)
    summary = dict(
        schema='nonc4_experiment_d_v1', experiment='D',
        input_routes=1024, assembled=len(routes),
        world_valid=len(check.get('valid') or []),
        failed=len(failed),
        world_violations=len(check.get('violations') or []),
        violation_kinds=dict(Counter(record.get('kind')
                                     for record in (check.get('violations')
                                                    or []))),
        direct_routes=sum(1 for record in routes
                          if not record.get('n_transitions')),
        transition_count=sum(int(record.get('n_transitions') or 0)
                             for record in routes),
        note='final accepted 3D assembly + strict 0.05 mm world check')
    _write_json(out / 'summary.json', summary)
    _write_json(out / 'failed_routes.json',
                dict(total=len(failed), failures=failed))
    return summary


# ------------------------------------------------------------------ pipeline
def run_pipeline(exp_dir, rows, selected, experiment='',
                 budgets=(600, 1200), max_iters=2, log=print, router=None,
                 checkpoint=True):
    """Stages C-E: route -> assemble -> world check -> joint repair -> finalize."""
    exp_dir = Path(exp_dir)
    manual_routes = load_baseline_manual_routes()
    history = []
    best = None
    previous_failed_ids = []
    started_all = time.time()
    for iteration in range(1, int(max_iters) + 1):
        log(f'=== STAGE C/D iteration {iteration}/{max_iters} ===')
        if iteration > 1 and previous_failed_ids:
            selected = run21._replan_leads(rows, selected, previous_failed_ids,
                                           iteration, log=log)
        budget = budgets[(iteration - 1) % len(budgets)]
        routed, raw, elapsed, tasks_payload = route_layers(
            rows, selected, budget=budget, seed=iteration - 1, log=log,
            router=router)
        routes, assembly_failures = assemble_all(rows, selected, routed,
                                                 manual_routes=manual_routes,
                                                 log=log)
        check = run21._world_check(routes)
        valid = check['valid']
        violations = check['violations']
        score = len(valid)
        valid_ids = set(valid)
        failed_ids = sorted(
            {int(record['route_id']) for record in assembly_failures}
            | {int(record.get('route_id', -1)) for record in violations}
            - valid_ids)
        failed_ids = [rid for rid in failed_ids if rid not in valid_ids]
        routed_2d = sum(len(value['routed']) for value in routed.values())
        record = dict(iteration=iteration, routed_2d=routed_2d,
                      assembled=len(routes), world_valid=score,
                      violations=len(violations),
                      violation_kinds=dict(Counter(
                          rec.get('kind') for rec in violations)),
                      assembly_failures=len(assembly_failures),
                      budget=budget, seconds=round(float(elapsed), 3),
                      failed_route_ids=failed_ids)
        history.append(record)
        log(f'[C/D] iteration {iteration}: 2d={routed_2d} '
            f'assembled={len(routes)} world_valid={score} '
            f'violations={len(violations)} '
            f'assembly_failures={len(assembly_failures)}')
        improved = (best is None or score > best['score']
                    or (score == best['score']
                        and len(violations) < len(best.get('violations') or [])))
        if improved:
            best = dict(score=score, valid=valid, routes=routes,
                        violations=violations, routed=routed,
                        assembly_failures=assembly_failures,
                        iteration=iteration)
            if checkpoint:
                save_best_checkpoint(exp_dir, rows, best, experiment,
                                     history, log=log)
        previous_failed_ids = failed_ids
        if score == len(rows) and not violations:
            log('[C/D] all 1024 routes valid')
            break
    if best is None:
        raise RuntimeError('pipeline produced no state')
    # ---- local single-route insertion / whole-plane re-solve for failures
    failed_rows = [row for row in rows if int(row['route_id']) not in best['valid']]
    if failed_rows:
        log(f'[E] repairing {len(failed_rows)} failed routes')
        world_routes = [best['valid'][rid] for rid in best['valid']]
        valid, routed, repaired, remaining = repair_failed(
            rows, selected, world_routes, failed_rows, manual_routes=manual_routes,
            log=log)
        if repaired:
            best = dict(best)
            best['valid'] = valid
            best['routed'] = routed
            best['score'] = len(valid)
            best['routes'] = [valid[rid] for rid in sorted(valid)]
            history.append(dict(stage='joint_repair', repaired=len(repaired),
                                world_valid=len(valid)))
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
    write_routes_payload(exp_dir, rows, routes, failed, history,
                         experiment=experiment, log=log)
    core = dict(exp_dir=exp_dir, rows=rows, selected=selected,
                routes=routes, failed=failed, best=best, history=history,
                elapsed=round(time.time() - started_all, 2))
    finalize_experiment(core, experiment=experiment, log=log)
    return core


def repair_failed(rows, selected, world_routes, failed_rows,
                  manual_routes=None, log=print):
    """Fit failed non-manual routes into the frozen accepted layout.

    Reuses the production primitives (single-route insertion with a frozen
    same-layer layout, then a whole-plane rip-up & re-solve with several seeds).
    """
    manual_routes = manual_routes if manual_routes is not None else \
        load_baseline_manual_routes()
    valid = {int(route['route_id']): route for route in world_routes}
    routed = layers_from_routes(world_routes, rows)
    # ---- 1) single-route insertion into the frozen layout
    layer_tasks = build_layer_tasks(rows, selected)
    obstacles_by_plane = {entry['plane_id']: entry['obstacles']
                          for entry in layer_tasks.values()}
    frozen_bodies = frozen_manual_bodies()
    lead_blockers = run21._interface_lead_blockers(selected)
    from ...l3d.world import World
    world = World(M.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
    for route_id in sorted(valid):
        world.add_route(valid[route_id])
    repaired = []
    remaining = []
    for row in sorted(failed_rows, key=lambda item: int(item['route_id'])):
        if D.is_manual(row):
            route_id = int(row['route_id'])
            valid[route_id] = copy.deepcopy(manual_routes[route_id])
            world.add_route(valid[route_id])
            repaired.append(route_id)
            continue
        outcome = _insert_one_route(rows, selected, row, world, layer_tasks,
                                    obstacles_by_plane, frozen_bodies,
                                    lead_blockers, valid, log=log)
        if outcome is None:
            remaining.append(row)
            continue
        valid[int(row['route_id'])] = outcome['route']
        world.add_route(outcome['route'])
        if not D.is_direct(row) and outcome.get('source') is not None:
            selected[int(row['route_id'])] = dict(
                source=outcome['source'], target=outcome['target'])
        plane_entry = routed.setdefault(
            int(row['target_layer']),
            dict(routed={}, failed=[], stats={},
                 z_mm=float(M.plane_z(int(row['target_layer'])))))
        plane_entry.setdefault('routed', {})[int(row['route_id'])] = dict(
            primitives=outcome['body'], family='LOCAL_INSERT')
        plane_entry.setdefault('failed', [])
        repaired.append(int(row['route_id']))
    log(f'[E] local insert: repaired={len(repaired)} '
        f'remaining={len(remaining)}')
    if remaining:
        recovered, remaining = _resolve_planes(rows, selected, valid, routed,
                                              remaining, log=log)
        repaired.extend([int(row['route_id']) for row in failed_rows
                         if int(row['route_id']) in valid
                         and int(row['route_id']) not in repaired])
    run21._refresh_fanout_for_repairs(rows, selected, log=log)
    return valid, routed, repaired, remaining


def _insert_one_route(rows, selected, row, world, layer_tasks,
                      obstacles_by_plane, frozen_bodies, lead_blockers,
                      valid, log=print):
    """One failed-route insertion with a whole-plane frozen D56 layout."""
    pid = int(row['target_layer'])
    z_mm = float(M.plane_z(pid))
    route_id = int(row['route_id'])
    direct = not bool(row['needs_transition'])
    frozen = {}
    frozen.update(frozen_bodies.get(pid, {}))
    frozen.update(lead_blockers.get(pid, {}))
    for other_id, other in valid.items():
        try:
            other_plane = int(other.get('target_layer',
                                        other.get('target_plane')))
        except (TypeError, ValueError):
            continue
        if other_plane != pid:
            continue
        body = D.body_primitives(other)
        if body:
            frozen[int(other_id)] = body
    obstacles = [item for item in obstacles_by_plane.get(pid, [])
                 if int(item.get('route_id', -1)) != route_id]
    lead_pairs = ((0.0, 0.0),) if direct else run21._LEAD_PAIRS
    for lead_pair in lead_pairs:
        if direct:
            eps = C.endpoints()
            p_s = tuple(float(v) for v in
                        eps[row['source_endpoint']]['routing_xy'])
            d_s = tuple(float(v) for v in eps[row['source_endpoint']]['inward'])
            p_t = tuple(float(v) for v in
                        eps[row['target_endpoint']]['routing_xy'])
            d_t = tuple(float(v) for v in eps[row['target_endpoint']]['inward'])
            task = dict(route_id=route_id, manual_group='',
                        relation=row.get('relation') or '',
                        source_side=row.get('source_side'),
                        target_side=row.get('target_side'),
                        A=p_s, dA=d_s, B=p_t, dB=d_t, direct=True)
            src = tgt = None
        else:
            try:
                src = FANOUT.candidate_transitions(
                    row, 'source', pid, leads=[lead_pair[0]])[0]
                tgt = FANOUT.candidate_transitions(
                    row, 'target', pid, leads=[lead_pair[1]])[0]
            except Exception:  # noqa: BLE001
                continue
            partial_s = FANOUT.partial_route(row, 'source', src, 2 * route_id)
            partial_t = FANOUT.partial_route(row, 'target', tgt, 2 * route_id + 1)
            if world.check_route(partial_s) or world.check_route(partial_t):
                continue
            task = dict(route_id=route_id, manual_group='',
                        relation=row.get('relation') or '',
                        source_side=row.get('source_side'),
                        target_side=row.get('target_side'),
                        A=tuple(src['end_xy']), dA=tuple(src['direction']),
                        B=tuple(tgt['end_xy']), dB=tuple(tgt['direction']),
                        direct=False)
        result = LAYER2D.route_layer(pid, z_mm, [task], obstacles=obstacles,
                                     initial_routes=frozen, budget=2400,
                                     rr_rounds=0, log=lambda *_a: None)
        entries = result.get('routed') or {}
        payload = entries.get(route_id) or entries.get(str(route_id))
        if payload is None:
            continue
        body = payload.get('primitives') if isinstance(payload, dict) else payload
        try:
            if direct:
                route = ASM.assemble_route(row, None, None, body)
            else:
                route = ASM.assemble_route(row, src, tgt, body)
        except ASM.AssemblyError:
            continue
        if world.check_route(route):
            continue
        return dict(route=route, body=body, source=src, target=tgt)
    return None


def _resolve_planes(rows, selected, valid, routed, remaining_rows, log=print):
    """Whole-plane rip-up & re-solve for still-failed routes (deterministic)."""
    from ...l3d.world import World
    layer_tasks = build_layer_tasks(rows, selected)
    manual_routes = load_baseline_manual_routes()
    global_frozen = initial_routes_for(selected)
    by_plane = OrderedDict()
    for row in remaining_rows:
        by_plane.setdefault(int(row['target_layer']), []).append(row)
    recovered = 0
    still = []
    for pid, plane_rows in by_plane.items():
        tasks = list(layer_tasks[pid]['tasks'])
        failed_ids = {int(row['route_id']) for row in plane_rows}
        frozen = dict(global_frozen.get(int(pid), {}))
        for other_id, other in valid.items():
            try:
                other_plane = int(other.get('target_layer',
                                            other.get('target_plane')))
            except (TypeError, ValueError):
                continue
            if other_plane != int(pid):
                continue
            body = D.body_primitives(other)
            if body:
                frozen[int(other_id)] = body
        for seed in range(4):
            result = LAYER2D.route_layer(
                int(pid), float(M.plane_z(int(pid))), tasks,
                obstacles=layer_tasks[pid]['obstacles'],
                initial_routes=frozen, budget=2400, rr_rounds=2,
                log=lambda *_a: None, ordering_seed=seed)
            routed_map = result.get('routed') or {}
            entries = {}
            for route_id in failed_ids:
                payload = (routed_map.get(route_id)
                           or routed_map.get(str(route_id)))
                if payload is None:
                    continue
                body = (payload.get('primitives')
                        if isinstance(payload, dict) else payload)
                entries[route_id] = body
            if not entries:
                continue
            # staged commit: re-add the other same-plane bodies too (regenerated)
            world = World(M.layer_stack(), clearance=C.MIN_3D_CLEARANCE_MM)
            for route_id in sorted(valid):
                world.add_route(valid[route_id])
            ok_ids = []
            new_routes = {}
            for route_id in sorted(entries):
                row = next(item for item in plane_rows
                           if int(item['route_id']) == route_id)
                try:
                    if D.is_direct(row):
                        route = ASM.assemble_route(row, None, None,
                                                   entries[route_id])
                    else:
                        pair = selected.get(route_id) or {}
                        route = ASM.assemble_route(
                            row, pair.get('source'), pair.get('target'),
                            entries[route_id])
                except ASM.AssemblyError:
                    continue
                if world.check_route(route):
                    continue
                world.add_route(route)
                ok_ids.append(route_id)
                new_routes[route_id] = route
            if ok_ids:
                for route_id in ok_ids:
                    valid[route_id] = new_routes[route_id]
                recovered += len(ok_ids)
                failed_ids -= set(ok_ids)
                break
        for route_id in sorted(failed_ids):
            still.append(next(row for row in plane_rows
                              if int(row['route_id']) == route_id))
    log(f'[E] plane re-solve: recovered={recovered} remaining={len(still)}')
    return recovered, still


def layers_from_routes(routes, rows):
    by_plane = OrderedDict((int(pid), dict(routed={}, failed={}, stats={},
                                           z_mm=float(M.plane_z(pid))))
                           for pid in M.PLANE_IDS)
    for route in routes:
        try:
            pid = int(route.get('target_layer', route.get('target_plane')))
        except (TypeError, ValueError):
            continue
        entry = by_plane.setdefault(pid, dict(routed={}, failed={}, stats={},
                                              z_mm=float(M.plane_z(pid))))
        rid = int(route['route_id'])
        entry['routed'][rid] = dict(route_id=rid,
                                    primitives=D.body_primitives(route),
                                    layer_id=pid, z_mm=float(M.plane_z(pid)))
        entry.setdefault('failed', {})
    for entry in by_plane.values():
        entry.setdefault('failed', [])
        entry.setdefault('stats', {})
    return by_plane


def save_best_checkpoint(exp_dir, rows, best, experiment, history, log=print):
    exp_dir = Path(exp_dir)
    ckpt = exp_dir / 'checkpoints'
    ckpt.mkdir(parents=True, exist_ok=True)
    routes = [best['valid'][rid] for rid in sorted(best['valid'])]
    payload = dict(
        schema='nonc4_best_checkpoint_v1', experiment=experiment,
        score=len(routes), world_violations=len(best.get('violations') or []),
        iteration=best.get('iteration'),
        recorded_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        history=history, routes=_route_records_for_payload(routes, rows))
    _write_json(ckpt / 'best_solution.json', payload)
    _write_json(ckpt / 'best_summary.json',
                dict(score=payload['score'],
                     world_violations=payload['world_violations'],
                     iteration=payload['iteration'],
                     recorded_at=payload['recorded_at']))
    log(f'[checkpoint] best solution: {payload["score"]} routes, '
        f'{payload["world_violations"]} violations')


def load_best_checkpoint(exp_dir):
    path = Path(exp_dir) / 'checkpoints' / 'best_solution.json'
    if not path.is_file():
        return None
    payload = D.load_json(path)
    routes = [record for record in payload.get('routes') or []
              if str(record.get('status') or '') != 'failed']
    return dict(payload=payload, routes=routes)


# ------------------------------------------------------------------ finalize
def finalize_experiment(core, experiment='', log=print):
    """Write the authoritative crossing report + independent validation."""
    exp_dir = Path(core['exp_dir'])
    rows = core['rows']
    routes = core['routes']
    failed = core['failed']
    best = core['best']
    history = core['history']
    routed = best.get('routed') or {}
    write_experiment_c(exp_dir, rows, routed, core.get('elapsed', 0.0), log=log)
    check = ASM.validate_routes_independent(routes, stack=M.layer_stack())
    write_experiment_d(exp_dir, rows, routes, failed, check, log=log)
    stats = write_final_stats(exp_dir, rows, routes, failed, history, best,
                              experiment=experiment, log=log)
    write_experiment_e(exp_dir, rows, best, failed, history,
                       experiment=experiment, log=log)
    layerwise = dict(schema='nonc4_layerwise_routes_v1', layers={})
    for pid, entry in routed.items():
        layerwise['layers'][str(pid)] = dict(
            plane_id=int(pid), label=M.plane_label(int(pid)),
            z_mm=M.plane_z(int(pid)), kind=M.plane_kind(int(pid)),
            routes={str(rid): dict(value)
                    for rid, value in (entry.get('routed') or {}).items()},
            failed=[dict(record) for record in (entry.get('failed') or [])],
            stats=entry.get('stats') or {})
    _write_json(exp_dir / 'layerwise_routes' / 'routes.json', layerwise)
    # frozen manual geometry verification (bit-identical to the baseline)
    _write_json(exp_dir / 'manual_frozen_check.json',
                manual_frozen_check(routes))
    # authoritative crossing statistics
    assignment_by_id = {int(row['route_id']): row for row in rows}
    records = D.route_records(exp_dir / 'routes_l3d.json')
    try:
        planes_payload = D.layer_planes(exp_dir)
    except FileNotFoundError:
        planes_payload = None
    report = X.crossing_report(records, planes=planes_payload,
                               assignment_by_id=assignment_by_id,
                               include_events=True,
                               routes_path=exp_dir / 'routes_l3d.json')
    report['experiment'] = experiment
    report['routed'] = len(records)
    report['failed'] = len(failed)
    report['geometry'] = dict(
        min_3d_clearance_mm=check.get('min_3d_clearance_mm'),
        total_length_mm=stats.get('total_length_mm'),
        max_route_length_mm=stats.get('max_route_length_mm'),
        transitions=stats.get('total_transitions'),
        world_violations=len(check.get('violations') or []),
    )
    _write_json(exp_dir / 'crossing_stats.json', report)
    history_rows = []
    for row in history:
        item = {key: (json.dumps(value) if isinstance(value, (dict, list))
                      else value) for key, value in row.items()}
        item.setdefault('stage', 'pipeline')
        history_rows.append(item)
    C.write_csv(exp_dir / 'optimization_history.csv',
                history_rows,
                ['stage', 'iteration', 'routed_2d', 'assembled', 'world_valid',
                 'violations', 'assembly_failures', 'budget', 'seconds',
                 'failed_route_ids'])
    log(f'[final] crossings={report["totals"]["crossings"]} '
        f'pairs={report["totals"]["crossing_pairs"]} '
        f'world_violations={len(check.get("violations") or [])}')
    core['crossing'] = report
    core['check'] = check
    core['stats'] = stats
    return report


def manual_frozen_check(routes):
    """Verify that every manual route equals the frozen baseline record."""
    manual_routes = load_baseline_manual_routes()
    by_id = {int(route['route_id']): route for route in routes}
    mismatches = []
    for route_id, baseline in manual_routes.items():
        current = by_id.get(route_id)
        if current is None:
            mismatches.append(dict(route_id=route_id, kind='missing'))
            continue
        if (json.dumps(current.get('parts'), sort_keys=True, default=str)
                != json.dumps(baseline.get('parts'), sort_keys=True,
                              default=str)):
            mismatches.append(dict(route_id=route_id, kind='parts_changed'))
            continue
        for key in ('start_z_mm', 'end_z_mm', 'target_layer', 'length_mm',
                    'n_transitions'):
            if str(current.get(key)) != str(baseline.get(key)):
                mismatches.append(dict(route_id=route_id, kind=f'{key}_changed'))
                break
    return dict(schema='nonc4_manual_frozen_check_v1',
                manual_routes=len(manual_routes),
                frozen=not mismatches,
                mismatches=mismatches[:200],
                mismatch_count=len(mismatches))


# --------------------------------------------------------------- convenience
def load_fanout_selected(exp_dir):
    payload = D.load_json(Path(exp_dir) / 'fanout_selected.json')
    return {int(rid): value for rid, value in (payload.get('selected')
                                               or {}).items()}


def run_standard(exp_name, plan=None, allocation=None, order='port',
                 budgets=(600, 1200), max_iters=2, router=None,
                 checkpoint=True, log=print, notes=None, experiment_dir=None,
                 base_rows=None, fixed_manual=True):
    """One complete experiment: assignment -> fanout -> 2D/3D -> crossing report."""
    exp_dir = Path(experiment_dir or P.experiment_dir(exp_name))
    base_rows = base_rows if base_rows is not None else D.load_baseline_assignment()
    if plan is None:
        plan = assign_nc.plan_with_manual(
            base_rows,
            assign_nc.plan_family_allocation(base_rows, allocation, order=order))
    rows, audit, digest = assign_nc.prepare_experiment(
        exp_dir, plan, base_rows=base_rows, experiment=exp_name,
        allocation=allocation, order=order, notes=notes)
    log(f'[A] experiment={exp_name} rows={len(rows)} '
        f'manual={audit["manual_total"]} direct={audit["direct_routes"]} '
        f'per_plane={audit["per_plane_counts"]}')
    selected, fanout_failures, fanout_validation, fixed_conflicts = stage_b(
        rows, log=log, fixed_manual=fixed_manual)
    if fanout_failures:
        log(f'[B] WARNING fanout failures: {len(fanout_failures)} '
            f'{fanout_failures[:5]}')
    core = run_pipeline(exp_dir, rows, selected, experiment=exp_name,
                        budgets=budgets, max_iters=max_iters, log=log,
                        router=router, checkpoint=checkpoint)
    return core


# --------------------------------------------------------------- cross router
class CrossAwareRouterShim:
    """Adapter exposing the cross-aware router through the layer2d API."""

    def __init__(self, config=None):
        from . import cross_router as CR
        self.module = CR
        self.config = dict(config or {})

    def _merged(self, cfg):
        merged = dict(self.config)
        merged.update(cfg or {})
        return merged

    def route_layer(self, layer_id, z_mm, tasks, obstacles=None, budget=600,
                    rr_rounds=2, rr_ripmax=3, log=print, ordering_seed=0,
                    cfg=None, initial_routes=None):
        return self.module.route_layer_cross_aware(
            layer_id, z_mm, tasks, obstacles=obstacles, budget=budget,
            ordering_seed=ordering_seed, initial_routes=initial_routes,
            cfg=self._merged(cfg), log=log)

    def route_all_layers(self, layer_tasks, out_dir=None, cfg=None, log=print,
                         ordering_seed=0, budget=600, rr_rounds=2,
                         rr_ripmax=3, initial_routes=None):
        return self.module.route_all_layers_cross_aware(
            layer_tasks, out_dir=out_dir, cfg=self._merged(cfg), log=log,
            ordering_seed=ordering_seed, budget=budget,
            initial_routes=initial_routes)
