# -*- coding: utf-8 -*-
"""Experiment D: multi-route joint reroute / make-way.

Phase 1 (D0): screen the highest-gain excursion candidates of the previous
round's interval analysis and classify their true-3D blockers.
Phase 2 (D1/D2): for candidates blocked by 1..3 movable routes only, try to
realise them by jointly rerouting those blockers with exact R15 make-way
excursions.  Accepted only on exact crossing improvement + fresh validation.
"""
from __future__ import annotations

import argparse
import csv
import time
from collections import Counter

from ...fsd25d import path3d as P
from . import common as N
from . import joint_reroute as J
from . import phase2 as P2
from . import route_model as RM
from . import single_route as S

EXPERIMENT = 'experiment_D'
MIN_NET = 3


def log_to(path):
    path = path if hasattr(path, 'open') else __import__('pathlib').Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(message):
        line = time.strftime('%H:%M:%S') + ' [D] ' + str(message)
        print(line, flush=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


def load_analysis_candidates(min_net=MIN_NET, per_route=3):
    payload = P2.load_json(P2.PHASE1_DIR / 'analysis' / 'crossing_intervals.json')
    routes = {}
    for entry in payload.get('routes') or ():
        rid = int(entry['route_id'])
        candidates = []
        for candidate in entry.get('candidates') or ():
            if not candidate.get('feasible'):
                continue
            net = int(candidate.get('estimated_net') or 0)
            if net < int(min_net):
                continue
            candidates.append(dict(
                target_z=float(candidate['target_z']),
                s_start_mm=float(candidate['s_start_mm']),
                s_end_mm=float(candidate['s_end_mm']),
                estimated_net=net,
                world_3d_ok=bool(candidate.get('world_3d_ok'))))
        if not candidates:
            continue
        best_by_z = {}
        for candidate in candidates:
            key = round(candidate['target_z'], 6)
            if key not in best_by_z or candidate['estimated_net'] > best_by_z[key]['estimated_net']:
                best_by_z[key] = candidate
        ranked = sorted(best_by_z.values(), key=lambda item: -item['estimated_net'])
        routes[rid] = ranked[:int(per_route)]
    return sorted(routes.items(),
                  key=lambda item: -max(c['estimated_net'] for c in item[1]))


def build_candidate(env, route_id, candidate):
    route = env.routes[int(route_id)]
    body_index, prims = S.route_body_chain(route)
    total = float(P.path_length(prims))
    s0 = max(0.5, min(total - 1.0, float(candidate['s_start_mm'])))
    s1 = min(total - 0.5, max(s0 + 1.0, float(candidate['s_end_mm'])))
    built = RM.duck_out(route, body_index, s0, s1, float(candidate['target_z']))
    return built['route'], built


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen', type=int, default=80)
    parser.add_argument('--repairs', type=int, default=40)
    parser.add_argument('--max-joint', type=int, default=3)
    parser.add_argument('--time-budget', type=float, default=260.0)
    parser.add_argument('--max-accept', type=int, default=12)
    args = parser.parse_args(argv)
    P2.ensure_dirs()
    exp_dir = P2.RUN2 / EXPERIMENT
    exp_dir.mkdir(parents=True, exist_ok=True)
    log = log_to(P2.RUN2 / 'logs' / 'experiment_D.log')
    started = time.time()
    deadline = started + float(args.time_budget)

    _payload, route_list = P2.load_baseline_routes()
    baseline_routes = {int(route['route_id']): route for route in route_list}
    rows, _ = N.load_assignment()
    manual = {int(row['route_id']) for row in rows
              if str(row.get('manual_group') or '').strip()}
    native_baseline = {rid for rid, route in baseline_routes.items()
                       if int(route.get('n_mid_transitions') or 0) > 0}
    env, bbox = J.make_env(baseline_routes, log=log)
    log('baseline: %d routes, %d crossings, %d native, %d manual'
        % (len(baseline_routes), env.total(), len(native_baseline), len(manual)))
    pool = [(rid, cands) for rid, cands in load_analysis_candidates()
            if rid not in native_baseline]
    log('candidate routes: %d' % len(pool))

    # ---------------- D0: blocker screening
    blocker_rows = []
    screened = []
    for route_id, candidates in pool[:int(args.screen)]:
        if time.time() > deadline:
            break
        try:
            candidate_route, _built = build_candidate(env, route_id,
                                                      candidates[0])
        except ValueError:
            continue
        collection = J.collect_blockers(
            {rid: route for rid, route in env.routes.items()},
            bbox, route_id, candidate_route, manual)
        movable = [item['route_id'] for item in collection['blockers']
                   if item['route_id'] not in manual]
        manual_hit = [item['route_id'] for item in collection['blockers']
                      if item['route_id'] in manual]
        row = dict(route_id=int(route_id),
                   target_z=float(candidates[0]['target_z']),
                   predicted_net=int(candidates[0]['estimated_net']),
                   clean=bool(collection['clean']),
                   reason=collection['reason'],
                   n_blockers=len(collection['blockers']),
                   n_movable=len(movable), n_manual=len(manual_hit),
                   movable_ids=movable, manual_ids=manual_hit)
        blocker_rows.append(row)
        if (row['clean'] and row['n_manual'] == 0
                and 0 < row['n_movable'] <= int(args.max_joint)):
            screened.append(dict(row=row, candidates=candidates))
    histogram = Counter()
    for row in blocker_rows:
        count = row['n_movable']
        histogram[str(count) if count <= 8 else '9+'] += 1
    blocker_summary = dict(
        screened=len(blocker_rows),
        clean=sum(1 for row in blocker_rows if row['clean']),
        histogram=dict(histogram),
        manual_blocked=sum(1 for row in blocker_rows if row['n_manual'] > 0),
        own_geometry=sum(1 for row in blocker_rows
                         if row['reason'] in ('own_geometry',
                                              'unattributed_violation')),
        repair_candidates=len(screened),
        rows=blocker_rows)
    P2.write_json(exp_dir / 'blocker_map.json', blocker_summary)
    log('D0: screened=%d clean=%d manual=%d hist=%s repair_candidates=%d'
        % (blocker_summary['screened'], blocker_summary['clean'],
           blocker_summary['manual_blocked'], dict(histogram), len(screened)))

    # ---------------- D1/D2: joint repairs
    history = []
    accepted = []
    attempts = 0
    for item in screened[:int(args.repairs)]:
        if attempts >= int(args.repairs) or time.time() > deadline:
            break
        if len(accepted) >= int(args.max_accept):
            break
        row = item['row']
        route_id = row['route_id']
        if route_id not in env.routes:
            continue
        for candidate in item['candidates'][:2]:
            attempts += 1
            try:
                candidate_route, _built = build_candidate(env, route_id,
                                                          candidate)
            except ValueError as error:
                history.append(dict(route_id=route_id,
                                    target_z=candidate['target_z'],
                                    predicted_net=candidate['estimated_net'],
                                    accepted=False, reason='build:%s' % error,
                                    joint_size=0, net=0))
                continue
            report = J.joint_try(env, bbox, route_id, candidate_route, manual,
                                 max_joint=int(args.max_joint))
            history.append(dict(route_id=route_id,
                                target_z=float(candidate['target_z']),
                                predicted_net=int(candidate['estimated_net']),
                                accepted=bool(report['accepted']),
                                reason=report['reason'],
                                joint_size=len(report.get('joint_routes') or []),
                                net=int(report['net']),
                                joint_routes=report.get('joint_routes'),
                                after_total=report.get('after_total')))
            if report['accepted']:
                for rid in report['joint_routes']:
                    env.replace_route(report['routes'][int(rid)])
                    bbox.update(report['routes'][int(rid)])
                accepted.append(dict(route_id=route_id,
                                     target_z=float(candidate['target_z']),
                                     predicted_net=int(candidate['estimated_net']),
                                     joint_routes=report['joint_routes'],
                                     net=int(report['net']),
                                     after_total=int(report['after_total'])))
                log('ACCEPT route %d predicted %+d -> exact %+d joint=%s total=%d'
                    % (route_id, row['predicted_net'], report['net'],
                       report['joint_routes'], env.total()))
                break
    # ---------------- save
    P2.save_experiment(env.routes, EXPERIMENT, log=log,
                       note='joint make-way reroute of blocked high-gain candidates')
    routes_dict = {rid: route for rid, route in env.routes.items()}
    validation = P2.validate(routes_dict, log=log)
    P2.write_json(exp_dir / 'validation.json', validation)
    with (exp_dir / 'joint_search_history.csv').open(
            'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            'route_id', 'target_z', 'predicted_net', 'accepted', 'net',
            'reason', 'joint_size', 'joint_routes', 'after_total'])
        writer.writeheader()
        for row in history:
            writer.writerow({key: row.get(key, '') for key in writer.fieldnames})
    report, _ = P2.crossing_report(list(routes_dict.values()))
    summary = dict(
        schema='native3d_phase2_experiment_d_v1',
        baseline_crossings=P2.BASELINE_CROSSINGS,
        final_crossings=int(env.total()),
        crossing_pairs=int(report['totals']['crossing_pairs']),
        routes=len(routes_dict),
        blocker_screen=dict(screened=blocker_summary['screened'],
                            clean=blocker_summary['clean'],
                            histogram=dict(histogram),
                            manual_blocked=blocker_summary['manual_blocked'],
                            repair_candidates=len(screened)),
        repair_attempts=attempts, accepted=len(accepted),
        net=sum(row['net'] for row in accepted),
        seconds=round(time.time() - started, 1))
    P2.write_json(exp_dir / 'summary.json', summary)
    if validation['validation_pass'] and int(env.total()) < P2.BASELINE_CROSSINGS:
        P2.save_best_valid(routes_dict, validation, log=log, tag='best_valid')
    log('done: attempts=%d accepted=%d total=%d violations=%s'
        % (attempts, len(accepted), int(env.total()),
           validation['violations']))
    return summary


if __name__ == '__main__':
    main()
