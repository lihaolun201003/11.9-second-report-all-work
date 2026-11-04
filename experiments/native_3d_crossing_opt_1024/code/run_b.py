# -*- coding: utf-8 -*-
"""Experiment B driver: strategy comparison + batch avoidance result."""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from pathlib import Path

from .. import common as C
from . import batch_avoid as BA
from . import common as N
from . import crossing_cache as CC
from . import guard as G
from . import single_route as S

EXPERIMENT = 'experiment_B'


def make_env(log=print):
    _payload, routes = N.load_routes()
    env = CC.NativeRouteSet(routes, log=log)
    return env, G.BboxCache(list(env.routes.values()))


def route_priority(env, events):
    counter = Counter()
    for event in events:
        counter[int(event['route_a'])] += 1
        counter[int(event['route_b'])] += 1
    movable = [rid for rid in counter
               if not N.is_manual_route(env.routes[rid]) and counter[rid] > 0]
    movable.sort(key=lambda rid: (-counter[rid], rid))
    return movable, counter


def save_crossing_stats(env, path, experiment):
    from ..nonc4 import crossings as X
    routes = [env.routes[rid] for rid in sorted(env.routes)]
    report = X.crossing_report(routes, planes=None,
                              assignment_by_id={},
                              include_events=True,
                              routes_path=None)
    report['experiment'] = experiment
    report['routed'] = len(routes)
    report['failed'] = 0
    N.write_json(path, report)
    return report


def write_routes_payload(env, path, experiment):
    base = N.load_e5_payload()
    routes = [env.routes[rid] for rid in sorted(env.routes)]
    native = [route for route in routes
              if int(route.get('n_mid_transitions') or 0) > 0]
    payload = dict(base)
    payload['schema'] = 'native3d_routes_l3d_v1'
    payload['experiment'] = experiment
    payload['parent_experiment'] = 'NON_C4_CROSSING_OPT_1024/E5_joint_repair_final'
    payload['native_3d'] = dict(
        model='one body may own several flat segments on different heights',
        routes_with_mid_transitions=len(native),
        mid_transitions=sum(int(route.get('n_mid_transitions') or 0)
                            for route in native),
        geometry='exact R15 S-curves (fsd25d.path3d.make_transition)',
        strategies=list(BA.STRATEGIES))
    payload['route_count'] = len(routes)
    payload['routed'] = len(routes)
    payload['failed'] = 0
    payload['routes'] = routes
    payload['crossing_definition'] = (
        'every flat part grouped by its physical z, fslw strict D56 audit '
        '(multi-height aware); interface leads included')
    N.write_json(path, payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', type=int, default=40)
    parser.add_argument('--batch', type=int, default=120)
    parser.add_argument('--time-budget', type=float, default=200.0)
    parser.add_argument('--max-excursions', type=int, default=3)
    parser.add_argument('--skip-strategies', action='store_true')
    args = parser.parse_args(argv)
    run_dir = N.RUN_DIR
    exp_dir = run_dir / EXPERIMENT
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / 'logs' / 'experiment_B.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message):
        line = time.strftime('%H:%M:%S') + ' [B] ' + str(message)
        print(line, flush=True)
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write(line + '\n')

    env, bbox_cache = make_env(log=log)
    events = env.cache.crossing_events()
    priority, counter = route_priority(env, events)
    sample = priority[:int(args.sample)]
    log('baseline total=%d, movable routes with crossings=%d, sample=%d'
        % (env.total(), len(priority), len(sample)))

    comparison = []
    strategy_records = {}
    if not args.skip_strategies:
        for strategy in BA.STRATEGIES:
            env_s, bbox_s = make_env(log=lambda *_a: None)
            log('== strategy %s on %d routes ==' % (strategy, len(sample)))
            summary, records, reasons = BA.run_strategy(
                strategy, sample, events, env_s, bbox_cache=bbox_s,
                max_excursions=args.max_excursions, log=log,
                deadline=time.time() + args.time_budget)
            summary['statistics'] = BA.excursion_statistics(records)
            summary['top_excursions'] = sorted(
                [item for record in records if record['applied']
                 for item in record['excursion_details']],
                key=lambda item: int(item.get('delta') or 0))[:10]
            comparison.append(summary)
            strategy_records[strategy] = records
            N.write_json(exp_dir / ('strategy_%s.json' % strategy), dict(
                schema='native3d_experiment_b_strategy_v1',
                summary=summary, records=records))
            log('== %s: applied=%d net=%+d total=%d (%.1fs)'
                % (strategy, summary['applied'], summary['net_crossings'],
                   summary['final_total'], summary['seconds']))
    comparison.sort(key=lambda item: item['net_crossings'])
    best = comparison[0] if comparison else dict(strategy='B4_multi_excursion',
                                                net_crossings=0)
    log('best strategy: %s (net %+d on sample)' % (best['strategy'],
                                                   best['net_crossings']))

    # ---- batch result with the winning strategy
    env_b, bbox_b = make_env(log=log)
    batch = priority[:int(args.batch)]
    summary, records, reasons = BA.run_strategy(
        best['strategy'], batch, events, env_b, bbox_cache=bbox_b,
        max_excursions=args.max_excursions, log=log,
        deadline=time.time() + 2.0 * args.time_budget)
    summary['statistics'] = BA.excursion_statistics(records)
    summary['sample_routes'] = len(batch)
    log('batch: applied=%d net=%+d total=%d' % (summary['applied'],
                                                summary['net_crossings'],
                                                summary['final_total']))

    # ---- artifacts
    N.write_json(exp_dir / 'strategy_comparison.json', dict(
        schema='native3d_experiment_b_comparison_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        baseline_total=2606, sample_routes=len(sample),
        strategies=comparison, best_strategy=best['strategy'],
        note='net_crossings are exact global recounts (all heights)'))
    N.write_json(exp_dir / 'batch_result.json', dict(
        schema='native3d_experiment_b_batch_v1',
        summary=summary, records=records))
    excursions = [item for record in records if record['applied']
                  for item in record['excursion_details']]
    N.write_json(exp_dir / 'candidates.json', dict(
        schema='native3d_experiment_b_candidates_v1',
        strategy=best['strategy'], excursions=excursions,
        accepted_routes=[record['route_id'] for record in records
                         if record['applied']]))
    N.write_json(exp_dir / 'failed_attempts.json', dict(
        schema='native3d_experiment_b_failures_v1',
        reasons=dict(reasons),
        records=[record for record in records if not record['applied']]))
    N.write_json(exp_dir / 'excursion_statistics.json', dict(
        schema='native3d_experiment_b_stats_v1',
        statistics=summary['statistics'],
        aggregate=dict(excursions=summary['excursions'],
                       net_crossings=summary['net_crossings'],
                       applied_routes=summary['applied'],
                       final_total=summary['final_total'])))
    routes_payload = write_routes_payload(env_b, exp_dir / 'routes_l3d.json',
                                          EXPERIMENT)
    crossing_report = save_crossing_stats(env_b, exp_dir / 'crossing_stats.json',
                                          EXPERIMENT)
    for name in ('assignment_1024.csv', 'layer_planes.json',
                 'process_rules.json', 'physical_layer_stack.json'):
        source = N.E5_DIR / name
        if source.is_file():
            (exp_dir / name).write_bytes(source.read_bytes())
    validation = G.full_validate(list(env_b.routes.values()), log=log)
    clearance = G.measure_min_clearance(list(env_b.routes.values()), log=log)
    native_routes = [route for route in env_b.routes.values()
                     if int(route.get('n_mid_transitions') or 0) > 0]
    N.write_json(exp_dir / 'summary.json', dict(
        schema='native3d_experiment_b_summary_v1',
        strategy=best['strategy'],
        routes=len(env_b.routes),
        routes_with_mid_transitions=len(native_routes),
        mid_transitions=sum(int(route.get('n_mid_transitions') or 0)
                            for route in native_routes),
        baseline_crossings=2606,
        final_crossings=int(env_b.total()),
        crossing_pairs=int(env_b.cache.total_pairs()),
        validation=validation,
        min_3d_clearance=clearance,
        total_length_mm=round(sum(float(route.get('length_mm') or 0.0)
                                  for route in env_b.routes.values()), 3)))
    log('[B] done: crossings 2606 -> %d, excursions=%d, validation=%s'
        % (env_b.total(), summary['excursions'],
           'ok' if validation['violations'] == 0 else 'FAILED'))
    return dict(comparison=comparison, batch=summary,
                validation=validation, clearance=clearance,
                crossings=int(env_b.total()))


if __name__ == '__main__':
    main()
