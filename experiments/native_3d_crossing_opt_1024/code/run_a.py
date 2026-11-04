# -*- coding: utf-8 -*-
"""Experiment A driver: A0 geometry unit tests, A1 real-environment scan, A2 single-route gain."""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from collections import Counter
from pathlib import Path

from ...fsd25d import path3d as P
from ...l3d.world import World
from .. import common as C
from ..reheight21 import model as M
from . import common as N
from . import crossing_cache as CC
from . import route_model as RM
from . import single_route as S
from . import transition as T

EXPERIMENT = 'experiment_A'


# ------------------------------------------------------------------ helpers
def _dirs():
    run = N.RUN_DIR
    exp = run / EXPERIMENT
    for sub in ('', 'checks'):
        (exp / sub).mkdir(parents=True, exist_ok=True)
    return run, exp


def _write(path, payload):
    N.write_json(path, payload)


def _make_world(routes, clearance=0.05):
    world = World(M.layer_stack(), clearance=clearance)
    for route in routes:
        world.add_route(route)
    return world


# ------------------------------------------------------------------ A0
def synthetic_route(z_from, z_to, s0=10.0, s1=30.0, path_length=60.0):
    """A self-contained straight-body route with one L_z_from->L_z_to->L_z_from excursion."""
    prims = [dict(kind='line', p0=[10.0, 10.0], p1=[10.0 + path_length, 10.0])]
    excursion = T.build_excursion(prims, s0, s1, z_from, z_to)
    parts = [RM.make_flat(z_from, excursion['prefix'], tag='body'),
             excursion['up'],
             RM.make_flat(z_to, [excursion['middle']], tag='body'),
             excursion['down'],
             RM.make_flat(z_from, excursion['suffix'], tag='body')]
    route = dict(route_id=9001, plane='z1', source_endpoint='SYN:1:1',
                 target_endpoint='SYN:1:2', start_z_mm=z_from,
                 end_z_mm=z_from, n_transitions=2, parts=parts)
    route = N.rebuild_route_metadata(route, interface_z=z_from)
    route = RM.tag_parts(route)
    route['native_3d'] = True
    route['excursions'] = [dict(s_start_mm=s0, s_end_mm=s1,
                                from_z=z_from, to_z=z_to,
                                up_part_index=1, down_part_index=3,
                                middle_part_index=2)]
    return route, excursion


def experiment_a0(run_dir, log=print):
    """Geometry unit tests of the mid-body R15 layer change."""
    results = []
    z6 = N.z_of_plane(6)
    z7 = N.z_of_plane(7)
    z20 = N.z_of_plane(20)

    def add(name, passed, detail=None):
        results.append(dict(test=name, passed=bool(passed), detail=detail))

    # -- 1. construction L6 -> L7 -> L6
    try:
        route, excursion = synthetic_route(z6, z7)
        errors = RM.structure_errors(route)
        add('build_L6_L7_L6', not errors, dict(errors=errors,
                                              footprint_mm=excursion['footprint_mm'],
                                              middle_mm=excursion['middle_mm']))
        add('footprint_formula',
            abs(excursion['footprint_mm']
                - T.transition_footprint(z7 - z6)) < 1e-9,
            dict(footprint_mm=excursion['footprint_mm']))
        add('all_arcs_R15',
            not any('radius' in item for item in errors), dict(errors=errors))
        # continuity: consecutive parts join exactly
        max_gap = 0.0
        for first, second in zip(route['parts'], route['parts'][1:]):
            if first['kind'] == 'flat' and second['kind'] == 'transition':
                point = first['primitives'][-1]['p1']
                max_gap = max(max_gap, math.hypot(point[0] - second['start'][0],
                                                 point[1] - second['start'][1]))
            elif first['kind'] == 'transition' and second['kind'] == 'flat':
                point = second['primitives'][0]['p0']
                max_gap = max(max_gap, math.hypot(point[0] - first['end'][0],
                                                 point[1] - first['end'][1]))
        add('continuity_position', max_gap <= 1e-6, dict(max_gap_mm=max_gap))
        # -- 2. World validation in a synthetic empty-ish world
        world = World(M.layer_stack(), clearance=0.05)
        obstacle = dict(route_id=9002, plane='z1', parts=[
            RM.make_flat(z7, [dict(kind='line', p0=[12.0, 40.0],
                                   p1=[12.0, 41.0])], tag='body')])
        obstacle = N.rebuild_route_metadata(obstacle, interface_z=z7)
        world.add_route(obstacle)
        violations = world.check_route(route)
        add('world_accepts_isolated_excursion', not violations,
            dict(violations=violations[:4]))
        # -- 3. L7 -> L20 -> L7
        route2, exc2 = synthetic_route(z7, z20, s0=12.0, s1=34.0)
        add('build_L7_L20_L7', not RM.structure_errors(route2),
            dict(errors=RM.structure_errors(route2),
                 footprint_mm=exc2['footprint_mm'],
                 middle_mm=exc2['middle_mm']))
        # dz table for every pair of heights (footprint grows with dz)
        table = []
        for dz in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.65, 1.00):
            try:
                table.append(dict(dz_mm=dz,
                                  footprint_mm=round(T.transition_footprint(dz), 6)))
            except ValueError as error:
                table.append(dict(dz_mm=dz, error=str(error)))
        add('footprint_table', all('footprint_mm' in item for item in table),
            dict(table=table))
    except Exception as error:  # noqa: BLE001
        add('build_L6_L7_L6', False, dict(exception=repr(error)))

    # -- 4. rejects: 49 um off-height, R=14, discontinuity, overlap
    try:
        route, _excursion = synthetic_route(z6, z7)
        broken = copy.deepcopy(route)
        # 49 um offset -> not one of the 21 heights
        for part in broken['parts']:
            if part['kind'] == 'flat':
                part['z_mm'] = float(part['z_mm']) + 0.049
                break
        add('reject_49um_off_height', bool(RM.structure_errors(broken)),
            dict(errors=RM.structure_errors(broken)[:3]))
        broken = copy.deepcopy(route)
        for part in broken['parts']:
            if part['kind'] == 'transition':
                part['radius_mm'] = 14.0
                break
        add('reject_R14', bool(RM.structure_errors(broken)),
            dict(errors=RM.structure_errors(broken)[:3]))
        broken = copy.deepcopy(route)
        for part in broken['parts']:
            if part['kind'] == 'flat' and part.get('tag') == 'body':
                prim = part['primitives'][0]
                prim['p1'] = [prim['p1'][0] + 1e-3, prim['p1'][1]]
                break
        structural = World.check_structure(broken)
        add('reject_discontinuity', bool(structural), dict(errors=structural[:3]))
        # overlapping another route in 3D
        world = World(M.layer_stack(), clearance=0.05)
        body_part = [part for part in route['parts'] if part['kind'] == 'flat'][1]
        overlap = dict(route_id=9003, plane='z1', parts=[
            RM.make_flat(body_part['z_mm'], body_part['primitives'], tag='body')])
        overlap = N.rebuild_route_metadata(overlap, interface_z=body_part['z_mm'])
        world.add_route(overlap)
        violations = world.check_route(route)
        add('reject_overlap', bool(violations), dict(violations=violations[:3]))
    except Exception as error:  # noqa: BLE001
        add('rejects_block', False, dict(exception=repr(error)))

    payload = dict(schema='native3d_experiment_a0_v1',
                   generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                   tests=results,
                   passed=all(item['passed'] for item in results),
                   note=('geometry unit tests of the mid-body R15 layer change; '
                         'independent from the 1024-route real space'))
    _write(run_dir / EXPERIMENT / 'a0_geometry_tests.json', payload)
    log('[A0] %d/%d tests passed' % (sum(1 for item in results if item['passed']),
                                     len(results)))
    return payload


# ------------------------------------------------------------------ A1
def experiment_a1(env, events, top_routes=20, deadline_seconds=420.0,
                  log=print, run_dir=None):
    """Scan the highest-crossing movable routes for legal mid-body excursions."""
    run_dir = run_dir or N.RUN_DIR
    started = time.time()
    per_route = Counter()
    for event in events:
        per_route[int(event['route_a'])] += 1
        per_route[int(event['route_b'])] += 1
    movable = [rid for rid in per_route
               if not N.is_manual_route(env.routes[rid])]
    movable.sort(key=lambda rid: (-per_route[rid], rid))
    selected = movable[:int(top_routes)]
    report = dict(schema='native3d_experiment_a1_scan_v1',
                  generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                  baseline_total=int(env.total()),
                  routes_scanned=[], attempts=[], reasons=Counter(),
                  per_route_best={})
    log('[A1] scanning %d routes (top crossings), baseline crossings=%d'
        % (len(selected), env.total()))
    for rid in selected:
        route = env.routes[rid]
        started_route = time.time()
        world = S.world_without(env, rid)
        results = S.scan_route(env, rid, events, world=world,
                               deadline=started + deadline_seconds, log=log)
        feasible = [item for item in results if item.get('feasible')]
        gains = [item for item in feasible if int(item['delta']) < 0]
        best = min(gains, key=lambda item: int(item['delta'])) if gains else None
        reasons = Counter()
        for item in results:
            for reason in item.get('reasons') or []:
                reasons[reason.split(':')[0]] += 1
        report['reasons'].update(reasons)
        report['routes_scanned'].append(dict(
            route_id=int(rid), crossings=int(per_route[rid]),
            body_z=float(N.PLANE_Z[int(route['target_layer'])]),
            window_part_chain=len(S.route_body_chain(route)[1]),
            attempts=len(results), feasible=len(feasible),
            gains=len(gains),
            best_delta=(int(best['delta']) if best else None),
            best_target_z=(float(best['target_z']) if best else None),
            reasons=dict(reasons),
            seconds=round(time.time() - started_route, 2)))
        if best is not None:
            report['per_route_best'][str(rid)] = dict(
                delta=int(best['delta']),
                target_plane=int(best['target_plane']),
                target_z=float(best['target_z']),
                from_z=float(best['from_z']),
                s0=float(best['s0']), s1=float(best['s1']),
                cluster_count=int(best['cluster_count']),
                cluster_start=float(best['cluster_start']),
                cluster_end=float(best['cluster_end']),
                footprint_mm=float(best['footprint_mm']),
                middle_mm=float(best['middle_mm']),
                per_plane=best.get('per_plane'))
        for item in results:
            slim = {key: item[key] for key in
                    ('route_id', 'target_plane', 'target_z', 'from_z', 's0', 's1',
                     'cluster_count', 'footprint_mm', 'middle_mm', 'delta',
                     'feasible', 'reasons', 'd56_ok')
                    if key in item}
            if item.get('world_errors'):
                slim['world_error_kind'] = item['world_errors'][0].get('kind')
            if item.get('d56_problems'):
                slim['d56_problem'] = str(item['d56_problems'])[:200]
            report['attempts'].append(slim)
        log('[A1] route %d crossings=%d attempts=%d feasible=%d gains=%d best=%s'
            % (rid, per_route[rid], len(results), len(feasible), len(gains),
               (int(best['delta']) if best else None)))
        if time.time() - started > deadline_seconds:
            log('[A1] time budget reached after %d routes' % len(report['routes_scanned']))
            break
    report['reasons'] = dict(report['reasons'])
    report['seconds'] = round(time.time() - started, 1)
    _write(run_dir / EXPERIMENT / 'a1_scan.json', report)
    log('[A1] scan done: routes=%d attempts=%d total feasible-gain routes=%d'
        % (len(report['routes_scanned']), len(report['attempts']),
           len(report['per_route_best'])))
    return report


# ------------------------------------------------------------------ A2
def experiment_a2(env, report_a1, log=print, run_dir=None, max_apply=1):
    """Apply the best single-route excursion and verify the exact global total."""
    run_dir = run_dir or N.RUN_DIR
    best = sorted(report_a1['per_route_best'].items(),
                  key=lambda item: int(item[1]['delta']))
    accepted = []
    changes = []
    for route_id, entry in best[:int(max_apply)]:
        rid = int(route_id)
        route = env.routes[rid]
        body_index, prims = S.route_body_chain(route)
        before_route = copy.deepcopy(route)
        before_total = env.total()
        built = RM.duck_out(route, body_index, entry['s0'], entry['s1'],
                            entry['target_z'])
        world = S.world_without(env, rid)
        detail = S.evaluate_candidate(env, rid, built['route'], world=world)
        if not detail.get('feasible'):
            log('[A2] route %d rejected on re-check: %s' % (rid, detail.get('reasons')))
            continue
        env.replace_route(built['route'])
        after_total = env.total()
        accepted.append(dict(route_id=rid, from_z=entry['from_z'],
                             to_z=entry['target_zone'] if 'target_zone' in entry
                             else entry['target_z'],
                             s0=entry['s0'], s1=entry['s1'],
                             footprint_mm=entry['footprint_mm'],
                             middle_mm=entry['middle_mm'],
                             delta=int(after_total - before_total),
                             crossings_before=int(before_total),
                             crossings_after=int(after_total)))
        changes.append(dict(route_id=rid, before=before_route,
                            after=env.routes[rid]))
        log('[A2] applied route %d: crossings %d -> %d (%+d)'
            % (rid, before_total, after_total, after_total - before_total))
        if env.total() <= 0 or len(accepted) >= int(max_apply):
            break
    payload = dict(schema='native3d_experiment_a2_v1',
                   generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                   accepted=accepted,
                   changes=changes,
                   baseline_crossings=2606,
                   final_crossings=int(env.total()),
                   note=('single-route mid-body layer change applied in the real '
                         '1024-route space; exact crossing recount after each change'))
    _write(run_dir / EXPERIMENT / 'a2_single_route_result.json', payload)
    return payload


# ------------------------------------------------------------------ save
def save_experiment(env, run_dir=None, experiment=EXPERIMENT, log=print,
                    payload_extra=None):
    """Write routes_l3d.json + assignment + model payloads for validation."""
    run_dir = Path(run_dir or N.RUN_DIR)
    exp = run_dir / experiment
    exp.mkdir(parents=True, exist_ok=True)
    base_payload = N.load_e5_payload()
    routes = [env.routes[rid] for rid in sorted(env.routes)]
    native_routes = [route for route in routes
                     if int(route.get('n_mid_transitions') or 0) > 0]
    payload = dict(base_payload)
    payload['schema'] = 'native3d_routes_l3d_v1'
    payload['experiment'] = experiment
    payload['parent_experiment'] = 'NON_C4_CROSSING_OPT_1024/E5_joint_repair_final'
    payload['native_3d'] = dict(
        model='one body may own several flat segments on different heights',
        mid_body_transitions=2 * len(native_routes),
        routes_with_mid_transitions=len(native_routes),
        geometry='exact R15 S-curves generated by fsd25d.path3d.make_transition',
        note=payload_extra or '')
    payload['route_count'] = len(routes)
    payload['routed'] = len(routes)
    payload['failed'] = 0
    payload['routes'] = routes
    _write(exp / 'routes_l3d.json', payload)
    for name in ('assignment_1024.csv', 'layer_planes.json',
                 'process_rules.json', 'physical_layer_stack.json'):
        source = N.E5_DIR / name
        if source.is_file():
            (exp / name).write_bytes(source.read_bytes())
    summary = dict(schema='native3d_experiment_summary_v1',
                   experiment=experiment,
                   routes=len(routes),
                   routes_with_mid_transitions=len(native_routes),
                   mid_transitions=sum(int(route.get('n_mid_transitions') or 0)
                                       for route in native_routes),
                   total_crossings=int(env.total()),
                   total_length_mm=round(sum(float(route.get('length_mm') or 0.0)
                                             for route in routes), 3))
    _write(exp / 'summary.json', summary)
    log('[save] %s: routes=%d native=%d crossings=%d'
        % (exp, len(routes), len(native_routes), env.total()))
    return payload, summary


# ------------------------------------------------------------------ CLI
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--top-routes', type=int, default=20)
    parser.add_argument('--time-budget', type=float, default=420.0)
    parser.add_argument('--max-apply', type=int, default=1)
    parser.add_argument('--skip-a1', action='store_true')
    args = parser.parse_args(argv)
    run_dir, exp_dir = _dirs()
    log_path = run_dir / 'logs' / 'experiment_A.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message):
        line = time.strftime('%H:%M:%S') + ' [A] ' + str(message)
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')

    log('experiment A start (run dir %s)' % run_dir)
    a0 = experiment_a0(run_dir, log=log)
    if not a0['passed']:
        log('[A] A0 geometry tests FAILED - stopping before the real-space scan')
        return dict(a0=a0)
    _payload, routes = N.load_routes()
    env = CC.NativeRouteSet(routes, log=log)
    log('[A] loaded E5 baseline: routes=%d exact crossings=%d'
        % (len(env.routes), env.total()))
    events = env.cache.crossing_events()
    a1 = experiment_a1(env, events, top_routes=args.top_routes,
                       deadline_seconds=args.time_budget, log=log,
                       run_dir=run_dir)
    a2 = experiment_a2(env, a1, log=log, run_dir=run_dir,
                       max_apply=args.max_apply)
    payload, summary = save_experiment(env, run_dir=run_dir, log=log)
    log('[A] done: %d single-route change(s), crossings %d -> %d'
        % (len(a2['accepted']), a2['baseline_crossings'], a2['final_crossings']))
    return dict(a0=a0, a1=a1, a2=a2, summary=summary)


if __name__ == '__main__':
    main()
