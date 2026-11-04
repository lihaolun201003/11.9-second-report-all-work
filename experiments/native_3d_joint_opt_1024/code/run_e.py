# -*- coding: utf-8 -*-
"""Experiment E: arc-region local 3D rebuild.

The previous rounds required the mid-body S-curves to sit on straight runs, so
~half of all crossings (those on R15 arcs) could never participate in a height
change.  Here a whole local sub-path *containing arcs* is moved to another
routing height: two exact R15 S-curves are placed on the straight runs that
flank the arc region, and the arc sub-path itself is re-used verbatim at the
travel height.  Three variants are compared:

* ``E_A`` local arc span     - minimal interval around one hot arc
* ``E_B`` expanded arc span  - interval expanded over neighbouring straight runs
* ``E_C`` far-height span    - same interval but to a non-adjacent height
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

from ...fsd25d import path3d as P
from . import common as N
from . import crossing_cache as CC
from . import excursion2 as E2
from . import guard as G
from . import joint_reroute as J
from . import phase2 as P2
from . import route_model as RM
from . import single_route as S
from . import transition as T

EXPERIMENT = 'experiment_E'


def log_to(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(message):
        line = time.strftime('%H:%M:%S') + ' [E] ' + str(message)
        print(line, flush=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return log


# ------------------------------------------------------------------ geometry
def prim_point_distance(prim, point):
    px, py = float(point[0]), float(point[1])
    if prim.get('kind') == 'line':
        x0, y0 = prim['p0'][0], prim['p0'][1]
        x1, y1 = prim['p1'][0], prim['p1'][1]
        dx, dy = x1 - x0, y1 - y0
        norm = dx * dx + dy * dy
        if norm <= 1e-12:
            return ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / norm))
        qx, qy = x0 + t * dx, y0 + t * dy
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
    if prim.get('kind') == 'arc':
        cx, cy = prim['center'][0], prim['center'][1]
        radius = float(prim['radius'])
        angle = __import__('math').atan2(py - cy, px - cx)
        start = float(prim['start_angle'])
        sweep = float(prim['sweep'])
        import math
        delta = (angle - start) % (2 * math.pi)
        if sweep >= 0:
            inside = delta <= sweep + 1e-9
        else:
            inside = (-delta if delta > math.pi else delta) <= abs(sweep) + 1e-9
        if inside:
            return abs(((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 - radius)
        ends = [prim['p0'], prim['p1']]
        return min(((px - e[0]) ** 2 + (py - e[1]) ** 2) ** 0.5 for e in ends)
    return float('inf')


def locate_point(part, point):
    """Primitive kind + local arc-length + cumulative span index of a point."""
    prims = part['primitives']
    best = (float('inf'), None, 0.0, 0.0, 0.0)
    cursor = 0.0
    for prim in prims:
        length = float(P.prim_length(prim))
        distance = prim_point_distance(prim, point)
        if distance < best[0]:
            best = (distance, prim.get('kind'), cursor, cursor + length,
                    length)
        cursor += length
    return dict(distance=best[0], kind=best[1], s_prim_start=best[2],
                s_prim_end=best[3], prim_length=best[4])


def arc_crossing_hits(route, events, route_id):
    """Crossing events that fall on an arc primitive of ``route``."""
    hits = []
    for event in events:
        if int(route_id) not in (int(event['route_a']), int(event['route_b'])):
            continue
        point = (float(event['x_mm']), float(event['y_mm']))
        z = round(float(event['z_mm']), 9)
        for part_index, part in enumerate(route['parts']):
            if part['kind'] != 'flat' or round(float(part['z_mm']), 9) != z:
                continue
            located = locate_point(part, point)
            if located['distance'] <= 0.25 and located['kind'] == 'arc':
                hits.append(dict(event=event, part_index=part_index,
                                 located=located,
                                 other_route=int(event['route_b'])
                                 if int(event['route_a']) == int(route_id)
                                 else int(event['route_a'])))
                break
    return hits


# ------------------------------------------------------------------ planning
def _spans(prims):
    spans = []
    cursor = 0.0
    for index, prim in enumerate(prims):
        length = float(P.prim_length(prim))
        spans.append(dict(index=index, kind=prim.get('kind'),
                          s_start=cursor, s_end=cursor + length,
                          length=length))
        cursor += length
    return spans


def straight_bounds(part, located):
    """Straight runs (line primitives) immediately before/after the hot arc."""
    prims = part['primitives']
    spans = _spans(prims)
    hot_index = None
    for span in spans:
        if span['s_start'] - 1e-9 <= located['s_prim_start'] <= span['s_end'] + 1e-9:
            hot_index = span['index']
            break
    if hot_index is None:
        return None
    before = None
    index = hot_index - 1
    while index >= 0 and spans[index]['kind'] == 'arc':
        index -= 1
    if index >= 0 and spans[index]['kind'] == 'line':
        before = spans[index]
    after = None
    index = hot_index + 1
    while index < len(spans) and spans[index]['kind'] == 'arc':
        index += 1
    if index < len(spans) and spans[index]['kind'] == 'line':
        after = spans[index]
    return dict(spans=spans, hot_index=hot_index, before=before, after=after)


def rebuild_intervals(route, part_index, located, target_z):
    """Candidate intervals whose S-curve feet sit on the flanking straight runs."""
    part = route['parts'][part_index]
    z_from = float(part['z_mm'])
    footprint = T.transition_footprint(float(target_z) - z_from)
    bounds = straight_bounds(part, located)
    if bounds is None:
        return []
    before = bounds['before']
    after = bounds['after']
    if before is None or after is None:
        return []
    if before['length'] < footprint + 0.2 or after['length'] < footprint + 0.2:
        return []
    total = float(P.path_length(part['primitives']))
    intervals = []
    for method, pad in (('E_A', 0.5), ('E_B', 3.0), ('E_C', 0.5)):
        max_pad_before = before['length'] - footprint - 0.1
        max_pad_after = after['length'] - footprint - 0.1
        pad_before = min(pad, max_pad_before)
        pad_after = min(pad, max_pad_after)
        s0 = before['s_end'] - footprint - pad_before
        s1 = after['s_start'] + footprint + pad_after
        if s0 < 0.2 or s1 > total - 0.2 or s1 - s0 < 2 * footprint + 0.5:
            continue
        intervals.append(dict(method=method, s0=s0, s1=s1))
    # E_B also uses the full available straight runs
    if (before['length'] - footprint - 0.1 > 3.0
            or after['length'] - footprint - 0.1 > 3.0):
        s0 = before['s_start'] + 0.1
        s1 = after['s_end'] - 0.1
        if s1 - s0 >= 2 * footprint + 0.5 and s1 <= total - 0.2:
            intervals.append(dict(method='E_B', s0=s0, s1=s1))
    return intervals


def try_rebuild(env, route_id, part_index, s0, s1, target_z, bbox_cache):
    route = env.routes[int(route_id)]
    try:
        built = E2.insert_excursion_general(route, part_index, s0, s1, target_z)
    except ValueError as error:
        return dict(ok=False, reason='build:%s' % error)
    candidate = built['route']
    structural = RM.structure_errors(candidate)
    if structural:
        return dict(ok=False, reason='structure:%s' % structural[0])
    guard = G.candidate_guard(env, candidate, bbox_cache=bbox_cache)
    if not guard['ok']:
        return dict(ok=False, reason='guard:%s' % guard['stage'])
    fast = env.evaluate_candidate(int(route_id), candidate)
    if not fast['d56_ok']:
        return dict(ok=False, reason='d56')
    return dict(ok=True, candidate=candidate, delta=int(fast['delta']),
                contains_arc=bool(built['contains_arc']),
                footprint_mm=built['footprint_mm'],
                middle_mm=built['middle_mm'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routes', type=int, default=14,
                        help='how many arc-hot routes to rebuild')
    parser.add_argument('--time-budget', type=float, default=300.0)
    parser.add_argument('--max-accept', type=int, default=15)
    args = parser.parse_args(argv)
    P2.ensure_dirs()
    exp_dir = P2.RUN2 / EXPERIMENT
    exp_dir.mkdir(parents=True, exist_ok=True)
    log = log_to(P2.RUN2 / 'logs' / 'experiment_E.log')

    # start from the best validated solution of D (if any) or the baseline
    start_dir = None
    for candidate_dir in (P2.RUN2 / 'best_valid', P2.RUN2 / 'experiment_D'):
        path = candidate_dir / 'routes_l3d.json'
        if path.is_file():
            start_dir = candidate_dir
            break
    if start_dir is None:
        start_dir = P2.PHASE1_RUN_DIR
    payload = P2.load_json(start_dir / 'routes_l3d.json')
    routes = {int(route['route_id']): route for route in payload['routes']}
    env, bbox = J.make_env(routes, log=log)
    rows, _ = N.load_assignment()
    manual = {int(row['route_id']) for row in rows
              if str(row.get('manual_group') or '').strip()}
    started = time.time()
    log('start from %s: %d crossings' % (start_dir.name, env.total()))
    report, _ = P2.crossing_report([env.routes[rid] for rid in sorted(env.routes)])
    events = report.get('crossing_events') or []
    # ---- arc crossing analysis
    movable = [rid for rid in env.routes if rid not in manual]
    arc_hits = {}
    for route_id in movable:
        hits = arc_crossing_hits(env.routes[route_id], events, route_id)
        if hits:
            arc_hits[route_id] = hits
    ordered = sorted(arc_hits, key=lambda rid: -len(arc_hits[rid]))
    log('routes with arc crossings: %d; top: %s'
        % (len(arc_hits),
           [(rid, len(arc_hits[rid])) for rid in ordered[:10]]))
    P2.write_json(exp_dir / 'arc_crossing_analysis.json', dict(
        schema='native3d_phase2_arc_crossing_analysis_v1',
        total_crossings=int(env.total()),
        routes_with_arc_crossings=len(arc_hits),
        top_routes=[dict(route_id=int(rid), arc_crossings=len(arc_hits[rid]))
                    for rid in ordered[:40]],
        route_arc_counts={str(rid): len(arc_hits[rid]) for rid in ordered}))
    # ---- rebuild attempts
    results = []
    accepted = 0
    attempts = 0
    deadline = started + float(args.time_budget)
    for route_id in ordered[:int(args.routes)]:
        if accepted >= int(args.max_accept) or time.time() > deadline:
            break
        hits = arc_hits[route_id]
        route = env.routes[route_id]
        by_part = Counter(hit['part_index'] for hit in hits)
        chosen = None
        for part_index, _count in by_part.most_common():
            part = route['parts'][part_index]
            for hit in hits:
                if hit['part_index'] != part_index:
                    continue
                bounds = straight_bounds(part, hit['located'])
                if bounds and bounds['before'] and bounds['after']:
                    chosen = (part_index, hit['located'])
                    break
            if chosen is not None:
                break
        if chosen is None:
            results.append(dict(route_id=int(route_id), accepted=False,
                                reason='no_flanking_straight',
                                before_arc=len(hits),
                                before_route_events=len(hits)))
            continue
        part_index, located = chosen
        z_from = float(route['parts'][part_index]['z_mm'])
        before_route_events = len([
            event for event in events
            if int(route_id) in (int(event['route_a']),
                                 int(event['route_b']))])
        before_arc = len(hits)
        best = None
        tried_methods = Counter()
        targets = [pid for pid in N.sorted_by_abs_dz(z_from)
                   if abs(N.z_of_plane(pid) - z_from) > 1e-9]
        for method, target_limit in (('E_A', 4), ('E_B', 4), ('E_C', 8)):
            for target_plane in targets[:target_limit]:
                target_z = N.z_of_plane(target_plane)
                intervals = rebuild_intervals(env.routes[route_id],
                                              part_index, located, target_z)
                for interval in intervals:
                    if interval['method'] != method:
                        continue
                    attempts += 1
                    tried_methods[method] += 1
                    outcome = try_rebuild(env, route_id, part_index,
                                          interval['s0'], interval['s1'],
                                          target_z, bbox)
                    if not outcome['ok']:
                        results.append(dict(route_id=int(route_id),
                                            method=method,
                                            target_z=target_z,
                                            s0=interval['s0'],
                                            s1=interval['s1'],
                                            accepted=False,
                                            reason=outcome['reason']))
                        continue
                    candidate = outcome['candidate']
                    if best is None or outcome['delta'] < best['delta']:
                        best = dict(route_id=int(route_id),
                                    method=method,
                                    target_z=target_z,
                                    s0=interval['s0'], s1=interval['s1'],
                                    delta=outcome['delta'],
                                    candidate=candidate,
                                    footprint_mm=outcome['footprint_mm'],
                                    middle_mm=outcome['middle_mm'],
                                    before_route_events=before_route_events,
                                    before_arc=before_arc)
        if best is None:
            results.append(dict(route_id=int(route_id), accepted=False,
                                reason='no_candidate',
                                before_arc=before_arc,
                                methods=dict(tried_methods)))
            continue
        before_total = int(env.total())
        env.replace_route(best['candidate'])
        bbox.update(best['candidate'])
        after_total = int(env.total())
        if after_total < before_total:
            accepted += 1
            report2, _ = P2.crossing_report(
                [env.routes[rid] for rid in sorted(env.routes)])
            new_events = report2.get('crossing_events') or []
            after_route_events = len([
                event for event in new_events
                if int(route_id) in (int(event['route_a']),
                                     int(event['route_b']))])
            after_arc = len(arc_crossing_hits(env.routes[route_id],
                                              new_events, route_id))
            results.append(dict(
                route_id=int(route_id), accepted=True,
                method=best['method'], target_z=best['target_z'],
                s0=round(best['s0'], 3), s1=round(best['s1'], 3),
                before_total=before_total, after_total=after_total,
                net=after_total - before_total,
                before_route_events=before_route_events,
                after_route_events=after_route_events,
                before_arc=before_arc, after_arc=after_arc,
                footprint_mm=best['footprint_mm'],
                middle_mm=best['middle_mm'],
                length_delta_mm=round(float(env.routes[route_id].get(
                    'length_mm') or 0.0) - float(route.get('length_mm') or 0.0),
                    4)))
            log('ACCEPT route %d %s z=%.2f net=%+d total=%d arc %d->%d'
                % (route_id, best['method'], best['target_z'],
                   after_total - before_total, after_total, before_arc,
                   after_arc))
        else:
            env.replace_route(route)
            bbox.update(route)
            results.append(dict(route_id=int(route_id), accepted=False,
                                reason='exact_not_better',
                                method=best['method'], target_z=best['target_z'],
                                before_total=before_total,
                                after_total=after_total))
        events = P2.crossing_report(
            [env.routes[rid] for rid in sorted(env.routes)])[0].get(
                'crossing_events') or []
    # ---- save
    P2.save_experiment(env.routes, EXPERIMENT, log=log,
                       note='arc-region local 3D rebuild (arcs moved to another height)')
    summary = dict(
        schema='native3d_phase2_experiment_e_v1',
        start_crossings=int(payload['native_3d'].get('total_crossings')
                            or P2.BASELINE_CROSSINGS) if False else None,
        final_crossings=int(env.total()),
        accepted=accepted, attempts=attempts,
        net=sum(int(row.get('net') or 0) for row in results
                if row.get('accepted')),
        methods=dict(Counter(row.get('method') for row in results
                             if row.get('accepted'))),
        before_arc_total=sum(int(row.get('before_arc') or 0) for row in results
                             if row.get('accepted')),
        after_arc_total=sum(int(row.get('after_arc') or 0) for row in results
                            if row.get('accepted')),
        seconds=round(time.time() - started, 1))
    summary['start_crossings'] = P2.BASELINE_CROSSINGS
    P2.write_json(exp_dir / 'arc_rebuild_results.json', dict(
        schema='native3d_phase2_arc_rebuild_v1',
        results=results, summary=summary))
    P2.write_json(exp_dir / 'summary.json', summary)
    routes_dict = {rid: route for rid, route in env.routes.items()}
    validation = P2.validate(routes_dict, log=log)
    P2.write_json(exp_dir / 'validation.json', validation)
    if validation['validation_pass'] and int(env.total()) < P2.BASELINE_CROSSINGS:
        P2.save_best_valid(routes_dict, validation, log=log, tag='best_valid')
    log('done: accepted=%d total=%d violations=%s'
        % (accepted, int(env.total()), validation['violations']))
    return dict(final=int(env.total()), accepted=accepted,
                validation=validation)


if __name__ == '__main__':
    main()
