# -*- coding: utf-8 -*-
"""Experiment F: global joint crossing optimisation.

Starts from the best validated layout of experiments D/E (or the inherited 2440
baseline) and runs repeated sweeps with an automatic strategy selector:

* ``plain``   - single mid-body excursion on a straight run of one body flat
* ``arc_span``- arc-region local 3D rebuild (experiment E engine)
* ``joint``   - multi-route joint make-way reroute (experiment D engine)

Every change is transactional: guards must pass, the exact global crossing
recount must strictly improve, otherwise it is rolled back.  The best validated
layout is checkpointed after every accepted improvement and every sweep.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from ...fsd25d import path3d as P
from . import common as N
from . import crossing_cache as CC
from . import excursion2 as E2
from . import guard as G
from . import joint_reroute as J
from . import phase2 as P2
from . import route_model as RM
from . import run_e as RE
from . import single_route as S
from . import transition as T

EXPERIMENT = 'experiment_F'


def log_to(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(message):
        line = time.strftime('%H:%M:%S') + ' [F] ' + str(message)
        print(line, flush=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


# ------------------------------------------------------------------ start state
def candidate_starts():
    starts = []
    for directory, label in ((P2.RUN2 / 'best_valid', 'best_valid'),
                             (P2.RUN2 / 'experiment_E', 'experiment_E'),
                             (P2.RUN2 / 'experiment_D', 'experiment_D'),
                             (P2.PHASE1_RUN_DIR, 'phase1_baseline')):
        path = directory / 'routes_l3d.json'
        if path.is_file():
            starts.append((label, path))
    return starts


def load_start(log):
    best = None
    for label, path in candidate_starts():
        try:
            payload = P2.load_json(path)
            routes = {int(route['route_id']): route for route in payload['routes']}
            total, _report = P2.exact_total(list(routes.values()))
        except Exception as error:  # noqa: BLE001
            log('start %s unreadable: %r' % (label, error))
            continue
        log('start candidate %-16s crossings=%d' % (label, total))
        if best is None or total < best[0]:
            best = (total, label, routes)
    return best


# ------------------------------------------------------------------ strategies
def crossing_positions_on_part(route, part_index, events, route_id):
    part = route['parts'][part_index]
    z = round(float(part['z_mm']), 9)
    positions = []
    for event in events:
        if int(route_id) not in (int(event['route_a']),
                                 int(event['route_b'])):
            continue
        if round(float(event['z_mm']), 9) != z:
            continue
        point = (float(event['x_mm']), float(event['y_mm']))
        located = RE.locate_point(part, point)
        if located['distance'] <= 0.25:
            positions.append(dict(s_mm=located['s_prim_start'], x_mm=point[0],
                                  y_mm=point[1], event=event))
    positions.sort(key=lambda item: item['s_mm'])
    return positions


def plain_attempt(env, bbox_cache, route_id, events, target_limit=4,
                  max_options=8):
    """Single mid-body excursion on any body flat of the route."""
    route = env.routes[int(route_id)]
    best = None
    evaluated = 0
    z_from = None
    for part_index, part in enumerate(route['parts']):
        if part['kind'] != 'flat':
            continue
        positions = crossing_positions_on_part(route, part_index, events,
                                              route_id)
        if not positions:
            continue
        clusters = S.cluster_positions(positions, gap_mm=10.0)
        clusters.sort(key=lambda item: -item['count'])
        z_from = float(part['z_mm'])
        prims = part['primitives']
        targets = [pid for pid in N.sorted_by_abs_dz(z_from)
                   if abs(N.z_of_plane(pid) - z_from) > 1e-9][:int(target_limit)]
        for cluster in clusters[:3]:
            for target_plane in targets:
                target_z = N.z_of_plane(target_plane)
                try:
                    intervals = S.interval_candidates(prims, cluster, target_z,
                                                      z_from, env=env,
                                                      exclude_route=int(route_id))
                except Exception:  # noqa: BLE001
                    continue
                for interval in intervals[:3]:
                    if not interval['feasible']:
                        continue
                    evaluated += 1
                    if evaluated > int(max_options) * 6:
                        break
                    try:
                        built = RM.duck_out(route, part_index,
                                            interval['s0'], interval['s1'],
                                            target_z)
                    except ValueError:
                        continue
                    candidate = built['route']
                    if RM.structure_errors(candidate):
                        continue
                    guard = G.candidate_guard(env, candidate,
                                              bbox_cache=bbox_cache)
                    if not guard['ok']:
                        continue
                    fast = env.evaluate_candidate(int(route_id), candidate)
                    if not fast['d56_ok'] or int(fast['delta']) >= 0:
                        continue
                    if best is None or int(fast['delta']) < best['delta']:
                        best = dict(candidate=candidate,
                                    delta=int(fast['delta']),
                                    method='plain', target_z=target_z,
                                    part_index=part_index,
                                    s0=interval['s0'], s1=interval['s1'],
                                    footprint_mm=built['footprint_mm'],
                                    middle_mm=built['middle_mm'])
                    break
                if best is not None:
                    break
            if best is not None:
                break
        if best is not None:
            break
    return best


def arc_attempt(env, bbox_cache, route_id, arc_hits, target_limit=4,
                max_targets=8):
    """Arc-region rebuild (experiment E engine) for one route."""
    hits = arc_hits.get(int(route_id)) or []
    if not hits:
        return None
    by_part = Counter(hit['part_index'] for hit in hits)
    part_index = by_part.most_common(1)[0][0]
    located = [hit['located'] for hit in hits
               if hit['part_index'] == part_index][0]
    route = env.routes[int(route_id)]
    z_from = float(route['parts'][part_index]['z_mm'])
    targets = [pid for pid in N.sorted_by_abs_dz(z_from)
               if abs(N.z_of_plane(pid) - z_from) > 1e-9][:int(target_limit)]
    best = None
    evaluated = 0
    for target_plane in targets:
        target_z = N.z_of_plane(target_plane)
        intervals = RE.rebuild_intervals(route, part_index, located, target_z)
        for interval in intervals:
            evaluated += 1
            if evaluated > int(max_targets) * 4:
                break
            outcome = RE.try_rebuild(env, int(route_id), part_index,
                                     interval['s0'], interval['s1'],
                                     target_z, bbox_cache)
            if not outcome['ok']:
                continue
            if best is None or outcome['delta'] < best['delta']:
                best = dict(candidate=outcome['candidate'],
                            delta=int(outcome['delta']),
                            method='arc_span', target_z=target_z,
                            part_index=part_index,
                            s0=interval['s0'], s1=interval['s1'],
                            footprint_mm=outcome['footprint_mm'],
                            middle_mm=outcome['middle_mm'])
        if best is not None:
            break
    return best


# ------------------------------------------------------------------ joint pool
def load_joint_candidates(min_net=5, per_route=2):
    from .run_d import load_analysis_candidates
    return load_analysis_candidates(min_net=min_net, per_route=per_route)


# ------------------------------------------------------------------ main
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sweeps', type=int, default=2)
    parser.add_argument('--time-budget', type=float, default=600.0)
    parser.add_argument('--joint-per-sweep', type=int, default=10)
    args = parser.parse_args(argv)
    P2.ensure_dirs()
    exp_dir = P2.RUN2 / EXPERIMENT
    exp_dir.mkdir(parents=True, exist_ok=True)
    log = log_to(P2.RUN2 / 'logs' / 'experiment_F.log')
    started = time.time()
    deadline = started + float(args.time_budget)

    start = load_start(log)
    if start is None:
        raise SystemExit('no readable start layout')
    start_total, start_label, routes = start
    env, bbox = J.make_env(routes, log=log)
    rows, _ = N.load_assignment()
    manual = {int(row['route_id']) for row in rows
              if str(row.get('manual_group') or '').strip()}
    movable = [rid for rid in env.routes if rid not in manual]
    events = env.cache.crossing_events()
    log('start %s: %d crossings, %d movable routes, %d manual'
        % (start_label, env.total(), len(movable), len(manual)))
    history = []
    strategy = dict(plain=dict(attempts=0, accepted=0, net=0, best=0),
                    arc_span=dict(attempts=0, accepted=0, net=0, best=0),
                    joint=dict(attempts=0, accepted=0, net=0, best=0))
    best_valid_total = int(env.total())
    counter = Counter()
    for event in events:
        counter[int(event['route_a'])] += 1
        counter[int(event['route_b'])] += 1
    joint_pool = [(rid, cands) for rid, cands in load_joint_candidates()
                  if rid in counter]
    joint_pool.sort(key=lambda item: -counter[item[0]])
    log('joint pool: %d routes' % len(joint_pool))

    def save_checkpoint(tag):
        P2.save_experiment(env.routes, EXPERIMENT, log=log,
                           note='global joint optimisation (%s)' % tag)
        routes_dict = {rid: route for rid, route in env.routes.items()}
        validation = P2.validate(routes_dict, log=log)
        P2.write_json(exp_dir / 'validation.json', validation)
        if validation['validation_pass'] and int(env.total()) <= best_valid_total:
            P2.save_best_valid(routes_dict, validation, log=log,
                               tag='best_valid')
            return validation['violations']
        return validation['violations']

    for sweep in range(1, int(args.sweeps) + 1):
        if time.time() > deadline:
            break
        log('=== sweep %d (start total=%d) ===' % (sweep, env.total()))
        # priority: routes with most crossings first
        order = sorted([rid for rid in movable if counter.get(rid, 0) > 0],
                       key=lambda rid: -counter.get(rid, 0))
        arc_hits = {}
        for route_id in order:
            hits = RE.arc_crossing_hits(env.routes[route_id], events, route_id)
            if hits:
                arc_hits[route_id] = hits
        joint_tried = 0
        sweep_start = int(env.total())
        for route_id in order:
            if time.time() > deadline:
                break
            before_total = int(env.total())
            best = None
            # 1) plain excursion
            strategy['plain']['attempts'] += 1
            try:
                best = plain_attempt(env, bbox, route_id, events)
            except Exception as error:  # noqa: BLE001
                log('plain error route %d: %r' % (route_id, error))
            # 2) arc rebuild when the route has arc crossings
            if (best is None or int(best['delta']) >= -2) and arc_hits.get(route_id):
                strategy['arc_span']['attempts'] += 1
                try:
                    arc_best = arc_attempt(env, bbox, route_id, arc_hits)
                except Exception as error:  # noqa: BLE001
                    log('arc error route %d: %r' % (route_id, error))
                    arc_best = None
                if arc_best is not None and (best is None
                                             or arc_best['delta'] < best['delta']):
                    best = arc_best
            # 3) joint make-way for stubborn high-crossing routes
            if best is None and joint_tried < int(args.joint_per_sweep):
                pool_entry = next((item for item in joint_pool
                                   if item[0] == route_id), None)
                if pool_entry is not None:
                    joint_tried += 1
                    strategy['joint']['attempts'] += 1
                    route = env.routes[route_id]
                    for candidate in pool_entry[1][:2]:
                        try:
                            candidate_route, _built = __import__(
                                'four_side_1024.fanout1024.native3d.run_d',
                                fromlist=['build_candidate']).build_candidate(
                                    env, route_id, candidate)
                        except ValueError:
                            continue
                        report = J.joint_try(env, bbox, route_id,
                                             candidate_route, manual,
                                             max_joint=2)
                        if report['accepted'] and (best is None or
                                                   report['net'] < best['delta']):
                            best = dict(candidate=report['routes'][route_id],
                                        delta=int(report['net']),
                                        method='joint', target_z=candidate['target_z'],
                                        joint_routes=report['joint_routes'])
                            best['routes_override'] = report['routes']
                        if report['accepted']:
                            break
            if best is None:
                continue
            if 'routes_override' in best:
                for rid in best['joint_routes']:
                    env.replace_route(best['routes_override'][int(rid)])
                    bbox.update(best['routes_override'][int(rid)])
                method = 'joint'
                delta = best['delta']
            else:
                env.replace_route(best['candidate'])
                bbox.update(best['candidate'])
                method = best['method']
                delta = int(env.total()) - before_total
            after_total = int(env.total())
            if after_total < before_total:
                strategy[method]['accepted'] += 1
                strategy[method]['net'] += after_total - before_total
                strategy[method]['best'] = min(strategy[method]['best'],
                                               after_total - before_total)
                history.append(dict(stage=method, sweep=sweep,
                                    route_id=int(route_id),
                                    delta=int(after_total - before_total),
                                    total=int(after_total),
                                    target_z=best.get('target_z')))
                log('ACCEPT %-8s route %d net=%+d total=%d'
                    % (method, route_id, after_total - before_total,
                       after_total))
                events = env.cache.crossing_events()
                counter = Counter()
                for event in events:
                    counter[int(event['route_a'])] += 1
                    counter[int(event['route_b'])] += 1
            else:
                # rollback the single change
                old = routes.get(route_id)
                env.replace_route(old if old is not None else env.routes[route_id])
                bbox.update(env.routes[route_id])
        violations = save_checkpoint('sweep_%02d' % sweep)
        log('sweep %d done: total=%d (net %+d), violations=%s'
            % (sweep, env.total(), int(env.total()) - sweep_start, violations))
        if int(env.total()) >= sweep_start:
            log('no improvement in sweep %d - stop' % sweep)
            break
    # ---- final save + validation
    final_total = int(env.total())
    P2.save_experiment(env.routes, EXPERIMENT, log=log,
                       note='final global joint optimisation')
    routes_dict = {rid: route for rid, route in env.routes.items()}
    validation = P2.validate(routes_dict, log=log)
    P2.write_json(exp_dir / 'validation.json', validation)
    report, _ = P2.crossing_report(list(routes_dict.values()))
    P2.write_json(exp_dir / 'crossing_stats.json', report)
    transition = P2.transition_stats(list(routes_dict.values()))
    P2.write_json(P2.RUN2 / 'transition_stats.json', transition)
    P2.write_json(exp_dir / 'transition_stats.json', transition)
    with (P2.RUN2 / 'optimization_history.csv').open(
            'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            'stage', 'sweep', 'route_id', 'delta', 'total', 'target_z'])
        writer.writeheader()
        for row in history:
            writer.writerow(row)
    P2.write_json(exp_dir / 'strategy_stats.json', dict(strategy=strategy))
    summary = dict(
        schema='native3d_phase2_experiment_f_v1',
        start_from=start_label, start_crossings=int(start_total),
        final_crossings=final_total,
        crossing_pairs=int(report['totals']['crossing_pairs']),
        routes=len(routes_dict),
        routes_with_mid_transitions=transition['routes_with_mid_transitions'],
        mid_transitions=transition['mid_transitions'],
        validation=dict(validation_pass=validation['validation_pass'],
                        violations=validation['violations']),
        min_3d_clearance=validation.get('min_3d_clearance'),
        strategy=strategy,
        history=history,
        seconds=round(time.time() - started, 1))
    P2.write_json(exp_dir / 'summary.json', summary)
    if validation['validation_pass'] and final_total <= best_valid_total:
        P2.save_best_valid(routes_dict, validation, log=log, tag='best_valid')
    log('FINAL: %d -> %d crossings, violations=%s'
        % (start_total, final_total, validation['violations']))
    return summary


if __name__ == '__main__':
    main()
