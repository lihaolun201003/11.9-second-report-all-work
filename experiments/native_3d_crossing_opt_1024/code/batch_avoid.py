# -*- coding: utf-8 -*-
"""Experiment B: batch crossing avoidance with one (or several) mid-body excursions.

Strategies compared on the real E5 route space:

* ``B1_adjacent``        only target heights that are physically adjacent (50 um)
* ``B2_all_heights``     every non-manual routing height
* ``B3_merged_clusters`` B2 + clusters separated by small gaps are merged into
                         one longer excursion (one excursion removes many crossings)
* ``B4_multi_excursion`` B3 + up to ``max_excursions`` non-overlapping
                         excursions on one route

Candidate generation is fast D56 + crossing-delta; only the few best options per
route go through the exact 3D guard (same-plane strict D56 on the full plane,
local true-3D world with every nearby route, self clearance, R15 structure).
"""
from __future__ import annotations

import copy
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from ...fsd25d import path3d as P
from . import common as N
from . import crossing_cache as CC
from . import guard as G
from . import route_model as RM
from . import single_route as S
from . import transition as T

STRATEGIES = ('B1_adjacent', 'B2_all_heights', 'B3_merged_clusters',
              'B4_multi_excursion')
MIN_EXCURSION_SEPARATION_MM = 2.5
#: how many guard-checked single options are considered per route
MAX_GUARDED_OPTIONS = 6


# ------------------------------------------------------------------ targets
def candidate_target_planes(z_from, strategy, limit=6):
    ordered = [pid for pid in N.sorted_by_abs_dz(z_from)
               if abs(N.z_of_plane(pid) - z_from) > 1e-9]
    if strategy == 'B1_adjacent':
        adjacent = [pid for pid in ordered
                    if abs(abs(N.z_of_plane(pid) - z_from) - 0.05) < 1e-6]
        return (adjacent or ordered[:2])[:limit]
    return ordered[:limit]


def merge_clusters(clusters, gap_mm=20.0, max_merge=3):
    merged = []
    bucket = []
    for cluster in clusters:
        if bucket and (cluster['s_start_mm'] - bucket[-1]['s_end_mm']) <= gap_mm \
                and len(bucket) < max_merge:
            bucket.append(cluster)
        else:
            if bucket:
                merged.append(_merge_bucket(bucket))
            bucket = [cluster]
    if bucket:
        merged.append(_merge_bucket(bucket))
    merged.sort(key=lambda item: -item['count'])
    return merged


def _merge_bucket(bucket):
    items = [item for cluster in bucket for item in cluster['items']]
    items.sort(key=lambda item: item['s_mm'])
    return dict(s_start_mm=items[0]['s_mm'], s_end_mm=items[-1]['s_mm'],
                items=items, count=len(items),
                member_clusters=len(bucket))


# ------------------------------------------------------------------ fast delta
def route_old_counts(env, route_id):
    from .crossing_cache import route_flat_groups
    route = env.routes[int(route_id)]
    groups = route_flat_groups(route)
    counts = {}
    for z_key, chains in groups.items():
        events, _pairs, ok, reasons = env.plane_cache.crossings_of(
            z_key, chains, exclude_route=int(route_id))
        counts[round(z_key, 9)] = dict(events=int(events), ok=bool(ok),
                                       reasons=reasons)
    return groups, counts


def candidate_fast_delta(env, route_id, old_groups, old_counts, new_route):
    from .crossing_cache import route_flat_groups
    new_groups = route_flat_groups(new_route)
    affected = sorted(set(old_groups) | set(new_groups))
    delta = 0
    per_plane = {}
    problems = []
    for z_key in affected:
        old_entry = old_counts.get(round(z_key, 9)) or dict(events=0, ok=True)
        old_events = int(old_entry['events'])
        if round(z_key, 9) in old_groups:
            pass
        new_events, _pairs, ok, reasons = env.plane_cache.crossings_of(
            z_key, new_groups.get(z_key) or [], exclude_route=int(route_id))
        delta += int(new_events) - old_events
        per_plane[round(z_key, 9)] = dict(old=old_events, new=int(new_events))
        if not ok:
            problems.append(dict(z_mm=round(z_key, 9), reasons=reasons[:3]))
    return dict(delta=delta, per_plane=per_plane, d56_ok=not problems,
                problems=problems, affected_z=affected)


# ------------------------------------------------------------------ options
def excursion_options(env, route_id, route, body_index, prims, clusters,
                      strategy, max_options=MAX_GUARDED_OPTIONS,
                      log=None):
    """Fast-ranked single-excursion options (not yet 3D-guarded)."""
    route_id = int(route_id)
    z_from = float(route['parts'][body_index]['z_mm'])
    target_planes = candidate_target_planes(z_from, strategy)
    old_groups, old_counts = route_old_counts(env, route_id)
    options = []
    reasons = Counter()
    for cluster in clusters:
        for plane_id in target_planes:
            target_z = N.z_of_plane(plane_id)
            for interval in S.interval_candidates(prims, cluster, target_z,
                                                  z_from, env=env,
                                                  exclude_route=route_id):
                if not interval['feasible']:
                    for reason in interval['reasons']:
                        reasons[reason] += 1
                    continue
                if interval.get('shadow') and not interval['shadow']['ok']:
                    reasons['shadow'] += 1
                    continue
                try:
                    built = RM.duck_out(route, body_index, interval['s0'],
                                        interval['s1'], target_z)
                except ValueError as error:
                    reasons['build'] += 1
                    continue
                fast = candidate_fast_delta(env, route_id, old_groups,
                                            old_counts, built['route'])
                if not fast['d56_ok']:
                    reasons['d56'] += 1
                    continue
                if int(fast['delta']) >= 0:
                    reasons['no_gain'] += 1
                    continue
                options.append(dict(
                    route_id=route_id, body_part_index=int(body_index),
                    target_plane=int(plane_id), target_z=float(target_z),
                    from_z=z_from, s0=float(interval['s0']),
                    s1=float(interval['s1']),
                    footprint_mm=float(built['footprint_mm']),
                    middle_mm=float(built['middle_mm']),
                    cluster_count=int(cluster['count']),
                    cluster_start=float(cluster['s_start_mm']),
                    cluster_end=float(cluster['s_end_mm']),
                    delta=int(fast['delta']), per_plane=fast['per_plane'],
                    route=built['route'], guarded=False))
    # de-duplicate by interval
    unique = {}
    for option in options:
        key = (round(option['s0'], 2), round(option['s1'], 2),
               option['target_plane'])
        if key not in unique or option['delta'] < unique[key]['delta']:
            unique[key] = option
    ranked = sorted(unique.values(), key=lambda item: (item['delta'],
                                                       -item['cluster_count']))
    return ranked, dict(reasons)


def _non_overlapping(selected, option):
    for other in selected:
        if option['s1'] + MIN_EXCURSION_SEPARATION_MM <= other['s0']:
            continue
        if other['s1'] + MIN_EXCURSION_SEPARATION_MM <= option['s0']:
            continue
        return False
    return True


def route_plan(env, route_id, events, strategy='B4_multi_excursion',
               max_excursions=3, bbox_cache=None, log=None):
    """Greedy plan for one route (no application to env)."""
    route_id = int(route_id)
    route = env.routes[route_id]
    body_index, prims = S.route_body_chain(route)
    positions = S.crossing_positions(route, events)
    clusters = S.cluster_positions(positions, gap_mm=10.0)
    if strategy in ('B3_merged_clusters', 'B4_multi_excursion'):
        clusters = merge_clusters(clusters)
    clusters = clusters[:6]
    limit = 1 if strategy != 'B4_multi_excursion' else int(max_excursions)
    options, reasons = excursion_options(env, route_id, route, body_index,
                                         prims, clusters, strategy, log=log)
    reasons = Counter(reasons)
    if not options:
        return dict(route_id=route_id, new_route=None, excursions=[],
                    predicted_delta=0, options=0, reasons=dict(reasons))
    # one best option per target plane first (target-plane diversity), then guard
    by_plane = {}
    for option in options:
        key = int(option['target_plane'])
        current = by_plane.get(key)
        if current is None or option['delta'] < current['delta']:
            by_plane[key] = option
    candidates = sorted(by_plane.values(), key=lambda item: (item['delta'],
                                                             -item['cluster_count']))
    remaining = [option for option in options
                 if option not in candidates]
    candidates.extend(remaining)
    selected = []
    guarded = 0
    for option in candidates:
        if len(selected) >= limit or guarded >= MAX_GUARDED_OPTIONS:
            break
        if not _non_overlapping(selected, option):
            continue
        checked = G.candidate_guard(env, option['route'], bbox_cache=bbox_cache)
        guarded += 1
        if not checked['ok']:
            reasons['guard:%s' % checked['stage']] += 1
            continue
        selected.append(option)
    if not selected:
        return dict(route_id=route_id, new_route=None, excursions=[],
                    predicted_delta=0, options=len(options),
                    reasons=dict(reasons))
    if len(selected) == 1:
        chosen = selected[0]
        return dict(route_id=route_id, new_route=chosen['route'],
                    excursions=[chosen], predicted_delta=int(chosen['delta']),
                    per_plane=chosen['per_plane'], options=len(options),
                    reasons=dict(reasons))
    selected.sort(key=lambda item: item['s0'])
    intervals = [(item['s0'], item['s1'], item['target_z']) for item in selected]
    try:
        built = RM.build_multi_excursion(route, body_index, intervals,
                                         interface_z=float(route.get('start_z_mm',
                                                                     route['target_z_mm'])))
    except ValueError as error:
        chosen = selected[0]
        return dict(route_id=route_id, new_route=chosen['route'],
                    excursions=[chosen], predicted_delta=int(chosen['delta']),
                    per_plane=chosen['per_plane'], options=len(options),
                    reasons=dict(reasons, build_combined=str(error)))
    old_groups, old_counts = route_old_counts(env, route_id)
    fast = candidate_fast_delta(env, route_id, old_groups, old_counts,
                                built['route'])
    checked = G.candidate_guard(env, built['route'], bbox_cache=bbox_cache)
    if not checked['ok']:
        chosen = selected[0]
        return dict(route_id=route_id, new_route=chosen['route'],
                    excursions=[chosen], predicted_delta=int(chosen['delta']),
                    per_plane=chosen['per_plane'], options=len(options),
                    reasons=dict(reasons, guard_combined=checked['stage']))
    return dict(route_id=route_id, new_route=built['route'],
                excursions=[dict(item) for item in selected],
                predicted_delta=int(fast['delta']), per_plane=fast['per_plane'],
                options=len(options), reasons=dict(reasons))


# ------------------------------------------------------------------ strategy run
def run_strategy(strategy, route_ids, events, env, bbox_cache=None,
                 max_excursions=3, log=print, deadline=None):
    records = []
    reasons = Counter()
    started = time.time()
    for route_id in route_ids:
        if deadline is not None and time.time() > deadline:
            log('[B] deadline reached after %d routes' % len(records))
            break
        route_id = int(route_id)
        before_total = env.total()
        plan = route_plan(env, route_id, events, strategy=strategy,
                          max_excursions=max_excursions,
                          bbox_cache=bbox_cache, log=log)
        for key, value in (plan.get('reasons') or {}).items():
            if isinstance(value, int):
                reasons[key] += value
            else:
                reasons[str(key)] += 1
        record = dict(route_id=route_id, strategy=strategy,
                      options=int(plan.get('options') or 0),
                      excursion_count=len(plan.get('excursions') or []),
                      predicted_delta=int(plan.get('predicted_delta') or 0),
                      applied=False, exact_delta=0,
                      crossing_before=int(before_total),
                      crossing_before_route=int(sum(
                          1 for event in events
                          if route_id in (int(event['route_a']),
                                          int(event['route_b'])))),
                      excursion_details=[
                          {key: item.get(key) for key in
                           ('target_plane', 'target_z', 'from_z', 's0', 's1',
                            'footprint_mm', 'middle_mm', 'cluster_count', 'delta')}
                          for item in plan.get('excursions') or []])
        if plan.get('new_route') is not None and record['predicted_delta'] < 0:
            env.replace_route(plan['new_route'])
            if bbox_cache is not None:
                bbox_cache.update(plan['new_route'])
            after_total = env.total()
            exact = int(after_total - before_total)
            if exact >= 0:
                env.replace_route(env.routes[route_id])
                if bbox_cache is not None:
                    bbox_cache.update(env.routes[route_id])
                record['reverted'] = True
            else:
                record.update(applied=True, exact_delta=exact,
                              crossings_after=int(after_total))
        records.append(record)
        log('[B] %-18s route %4d excursions=%d predicted=%+d exact=%+d total=%d'
            % (strategy, route_id, record['excursion_count'],
               record['predicted_delta'], record['exact_delta'], env.total()))
    summary = dict(strategy=strategy, routes=len(records),
                   applied=sum(1 for item in records if item['applied']),
                   excursions=sum(item['excursion_count'] for item in records
                                  if item['applied']),
                   net_crossings=sum(item['exact_delta'] for item in records
                                     if item['applied']),
                   final_total=int(env.total()),
                   reasons=dict(reasons),
                   seconds=round(time.time() - started, 1))
    return summary, records, dict(reasons)


# ------------------------------------------------------------------ statistics
def excursion_statistics(records):
    applied = [item for item in records if item['applied']]
    excursions = [entry for item in applied for entry in item['excursion_details']]
    nets = [int(item['exact_delta']) for item in applied]
    stats = dict(routes_processed=len(records), routes_improved=len(applied),
                 excursions=len(excursions), net_crossings=sum(nets),
                 mean_net_per_route=(sum(nets) / len(nets) if nets else 0.0),
                 best_route=(min(nets) if nets else 0),
                 worst_route=(max(nets) if nets else 0),
                 mean_excursions_per_route=(len(excursions) / len(applied)
                                            if applied else 0.0))
    deltas = [int(entry.get('delta') or 0) for entry in excursions]
    if deltas:
        stats['mean_excursion_delta'] = round(sum(deltas) / len(deltas), 3)
        stats['best_excursion_delta'] = min(deltas)
        stats['best_single_excursion_cluster_count'] = max(
            (int(entry.get('cluster_count') or 0)
             for entry in excursions if int(entry.get('delta') or 0) < 0),
            default=0)
    return stats
