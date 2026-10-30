# -*- coding: utf-8 -*-
"""Automatic U-bundle grouping + target-layer search on the frozen Hybrid H baseline.

New experiment only: all files live under
``outputs/manual_c4_new_connectivity/auto_u_bundle_hybrid/`` and no existing
module / result is modified.

Inputs
------
* Hybrid H payload (frozen): 1024/1024, U at Structured-A layers.
* Feasibility scan ``_work/scan/g{gid}_{layer}.json`` (see
  ``auto_u_bundle_hybrid.py``).

Algorithm
---------
1. Remove all 64 same-side U quartets from the Hybrid payload; the remaining
   768 routes are the fixed world.
2. Cluster the 64 quartets automatically (k-means on geometry features:
   plane, separation, N-side center) - no group IDs are hard-coded.
3. For each cluster, only layers where *all* its quartets have feasible
   (a, D) parameters are allowed; within a layer the quartets are ordered by
   separation and a 0.5 mm-gap depth chain is solved by DP.
4. Initial layer assignment is built greedily; then coordinate descent tries
   every allowed layer for every cluster, keeping assignments that reduce the
   global unique crossing pairs (tie: transitions, length).
5. Full payload is validated by the frozen l3d validator; metrics are compared
   with Hybrid H (frozen baseline) and the manual Spatial U-bundle result.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply  # noqa: E402

apply()

from four_side_1024.manual_c4 import spatial_u_bundle as S  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity'
HYBRID_H = CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json'
HYBRID_SUMMARY = CAMPAIGN / 'hybrid_c2_c4_directional/H/summary.json'
SPATIAL_SUMMARY = CAMPAIGN / 'spatial_u_bundle_optimization/summary.json'
OUT = CAMPAIGN / 'auto_u_bundle_hybrid'
WORK = OUT / '_work'
SCAN = WORK / 'scan'
LAYERS = [(2, 1.0), (3, 1.5), (4, 2.0), (5, 2.5)]
LAYER_Z = dict(LAYERS)
BUNDLES_MANUAL = {
    'z1_middle_U': (list(range(20, 36)), 2, 1.0),
    'z2_corner_U_1': (list(range(144, 160)), 2, 1.0),
    'z2_corner_U_2': (list(range(160, 176)), 3, 1.5),
    'z2_middle_U': (list(range(176, 192)), 4, 2.0),
}
NEST_GAP = 0.5
CROSS_WEIGHT = 1.0


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=indent),
                          encoding='utf-8')


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_hybrid_campaign():
    campaign = S.Campaign()
    payload = read_json(HYBRID_H)
    records = {int(r['route_id']): r for r in payload['routes']
               if r.get('status') == 'routed'}
    same = {int(r['route_id']) for r in campaign.connectivity['routes']
            if r['relation'] == 'same'}
    campaign.baseline_records = {rid: rec for rid, rec in records.items()
                                 if rid not in same}
    campaign.base_u_records = {rid: rec for rid, rec in records.items()
                               if rid in same}
    campaign.target_rids = set(same)
    campaign.layer_stack_payload = payload['layer_stack']
    return campaign, payload


def load_scan():
    out = {}
    for path in sorted(SCAN.glob('g*_*.json')):
        data = read_json(path)
        gid, layer = int(data['group_id']), int(data['layer'])
        out[(gid, layer)] = [(float(a), float(d)) for a, d in data['feasible']]
    return out


# ---------------------------------------------------------------------------
# automatic clustering
# ---------------------------------------------------------------------------
def quartet_features(campaign):
    from four_side_1024.manual_c4.spatial_u_bundle import group_separation
    features = {}
    for gid, group in campaign.groups.items():
        if group.get('kind') != 'same':
            continue
        gid = int(gid)
        plane = campaign.record(int(group['route_ids'][0]))['plane']
        separation = float(group_separation(campaign, gid))
        # one member starts on the N side; use its edge-coordinate center
        n_center = None
        for rid in group['route_ids']:
            rec = campaign.record(int(rid))
            if rec['source_side'] == 'N':
                p = campaign.port_xy(rec['source_endpoint'])
                q = campaign.port_xy(rec['target_endpoint'])
                n_center = (p[0] + q[0]) / 2.0
                break
        features[gid] = [0.0 if plane == 'z1' else 1.0, separation,
                         float(n_center if n_center is not None else 0.0)]
    return features


def standardize(rows):
    import numpy as np
    arr = np.asarray(rows, dtype=float)
    mu = arr.mean(axis=0)
    sd = arr.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (arr - mu) / sd


def kmeans(points, k, seed=17, n_init=8, max_iter=80):
    import numpy as np
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(n_init):
        # k-means++ init
        centers = [points[int(rng.integers(len(points)))]]
        for _ in range(1, k):
            dist = np.min(((points[:, None, :] - np.array(centers)[None, :, :]) ** 2)
                          .sum(axis=2), axis=1)
            prob = dist / dist.sum() if dist.sum() > 0 else None
            idx = int(rng.choice(len(points), p=prob)) if prob is not None else 0
            centers.append(points[idx])
        centers = np.asarray(centers)
        labels = np.zeros(len(points), dtype=int)
        for _ in range(max_iter):
            d = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            labels = d.argmin(axis=1)
            new = np.asarray([points[labels == i].mean(axis=0)
                              if (labels == i).any() else centers[i]
                              for i in range(k)])
            if np.allclose(new, centers):
                break
            centers = new
        inertia = float(((points - centers[labels]) ** 2).sum())
        if best is None or inertia < best[0]:
            best = (inertia, labels.copy(), centers.copy())
    return best[1], best[2]


def silhouette(points, labels):
    import numpy as np
    labels = np.asarray(labels)
    uniq = sorted(set(labels.tolist()))
    if len(uniq) < 2:
        return -1.0
    scores = []
    for i in range(len(points)):
        same = points[labels == labels[i]]
        if len(same) > 1:
            a = float(np.mean([np.linalg.norm(points[i] - p) for p in same if
                               not np.allclose(p, points[i])]))
        else:
            a = 0.0
        b = min(float(np.mean([np.linalg.norm(points[i] - p)
                               for p in points[labels == o]]))
                for o in uniq if o != labels[i])
        denom = max(a, b)
        scores.append(0.0 if denom < 1e-12 else (b - a) / denom)
    return float(np.mean(scores))


def auto_clusters(campaign, features, k_min=2, k_max=8):
    import numpy as np
    gids = sorted(features)
    rows = standardize([features[g] for g in gids])
    best = None
    for k in range(k_min, min(k_max, len(gids)) + 1):
        labels, centers = kmeans(rows, k)
        score = silhouette(rows, labels)
        if best is None or score > best[0]:
            best = (score, k, labels.copy())
    _, k, labels = best
    clusters = {}
    for gid, lab in zip(gids, labels):
        clusters.setdefault(int(lab), []).append(int(gid))
    return [dict(cluster_id=i, groups=sorted(v)) for i, v in
            enumerate(sorted(clusters.values(), key=lambda x: x[0]))], k


# ---------------------------------------------------------------------------
# cluster route building
# ---------------------------------------------------------------------------
def group_rank(campaign, gid):
    from four_side_1024.manual_c4.spatial_u_bundle import group_separation
    return float(group_separation(campaign, gid))


def build_cluster(campaign, world, gids, layer, layer_z, feasible,
                  max_a_tries=999):
    """Build a cluster with a greedy monotone depth chain (D increases by gap).

    This is more flexible than a single DP chain: for each quartet (ordered by
    separation) it tries feasible (D, a) entries with D >= previous D + gap and
    keeps the first one that is collision-free against the current world.
    """
    ranks = sorted(gids, key=lambda g: group_rank(campaign, g))
    routes = []
    previous_d = None
    for gid in ranks:
        entries = feasible.get((gid, layer), [])
        if not entries:
            return None, f'group {gid}: no feasible entry on L{layer}'
        # prefer shallow depth then short entry straight; enforce nesting gap
        candidates = sorted(entries, key=lambda item: (item[1], item[0]))
        accepted = None
        tried = 0
        for d, a in [(d, a) for a, d in candidates]:
            if previous_d is not None and d < previous_d + NEST_GAP - 1e-9:
                continue
            tried += 1
            if tried > 400:
                break
            built, err = S.build_quartet(campaign, gid, layer, layer_z, d, a, a)
            if built is None:
                continue
            if any(world.check_route(route) for route in built):
                continue
            accepted = (built, d)
            break
        if accepted is None:
            return None, (f'group {gid}: all (D,a) entries conflict on L{layer} '
                          f'(previous D={previous_d})')
        built, d = accepted
        previous_d = d
        for route in built:
            world.add_route(route)
            routes.append(route)
    return routes, None


# ---------------------------------------------------------------------------
# payload / metric
# ---------------------------------------------------------------------------
def make_payload(campaign, hybrid_payload, new_routes):
    records = dict(campaign.baseline_records)
    records.update({int(r['route_id']): r for r in new_routes})
    ordered = [records[rid] for rid in sorted(records)]
    return dict(schema='four_side_1024_v2_l3d_routes_v1',
                experiment='MANUAL_C4_AUTO_U_BUNDLE_HYBRID',
                note=('automatic U-bundle grouping and target-layer assignment '
                      'on top of the frozen Hybrid H baseline; 768 non-U routes '
                      'and z1 direction layering unchanged'),
                layer_stack=hybrid_payload['layer_stack'],
                routes=ordered)


def evaluate(campaign, hybrid_payload, assignment, clusters, feasible,
             order):
    """Assemble one assignment; return payload + metrics or None."""
    world = S.fixed_world(campaign)
    new_routes = []
    details = {}
    for cid in order:
        cluster = clusters[cid]
        layer = assignment[cid]
        routes, err = build_cluster(campaign, world, cluster['groups'], layer,
                                    LAYER_Z[layer], feasible)
        if routes is None:
            return None
        for route in routes:
            new_routes.append(route)
        details[cid] = dict(layer=layer,
                            groups=[int(g) for g in cluster['groups']],
                            route_ids=[int(r['route_id']) for r in routes])
    payload = make_payload(campaign, hybrid_payload, new_routes)
    metrics = S.payload_metrics(campaign, payload)
    metrics['assignment'] = assignment
    metrics['details'] = details
    return dict(payload=payload, metrics=metrics)


def score_of(metrics):
    return (int(metrics['unique_crossing_pairs']),
            int(metrics.get('transitions') or 0),
            float(metrics.get('total_length_mm') or 0.0))


# ---------------------------------------------------------------------------
# layer search
# ---------------------------------------------------------------------------
def feasible_layers_for_cluster(cluster, feasible):
    result = []
    for layer, _z in LAYERS:
        if all(feasible.get((gid, layer)) for gid in cluster['groups']):
            result.append(layer)
    return result


def greedy_initial(campaign, clusters, allowed, feasible, log=print):
    """Greedy cluster-by-cluster assembly; fallback to base Hybrid U on failure."""
    order = sorted(clusters, key=lambda c: (len(allowed[c['cluster_id']]),
                                            c['cluster_id']))
    assignment = {}
    accepted = []
    fallback = {}

    def world_with(routes):
        world = S.fixed_world(campaign)
        for route in routes:
            world.add_route(route)
        return world

    for cluster in order:
        cid = cluster['cluster_id']
        chosen = None
        for layer in allowed[cid]:
            world = world_with(accepted)
            routes, err = build_cluster(campaign, world, cluster['groups'],
                                        layer, LAYER_Z[layer], feasible)
            if routes is not None:
                chosen = (layer, routes)
                break
        if chosen is not None:
            layer, routes = chosen
            assignment[cid] = layer
            accepted.extend(routes)
            log(f'initial cluster {cid}: L{layer} ({len(routes)} routes)')
            continue
        # fallback: keep the frozen Hybrid H geometry for this cluster
        base_routes = [campaign.base_u_records[int(rid)]
                       for gid in cluster['groups']
                       for rid in campaign.groups[int(gid)]['route_ids']]
        world = world_with(accepted)
        if any(world.check_route(route) for route in base_routes):
            log(f'cluster {cid}: no rebuildable layer and base geometry conflicts')
            return None, None
        for route in base_routes:
            world.add_route(route)
            accepted.append(route)
            fallback[int(route['route_id'])] = True
        fallback[cid] = True
        log(f'initial cluster {cid}: fallback to frozen Hybrid U geometry')
    return assignment, accepted, fallback


def search(campaign, hybrid_payload, clusters, feasible, log=print):
    allowed = {c['cluster_id']: feasible_layers_for_cluster(c, feasible)
               for c in clusters}
    log('allowed layers:', allowed)
    assignment, _routes, fallback = greedy_initial(campaign, clusters, allowed,
                                                   feasible, log=log)
    if assignment is None:
        return None
    order = [c['cluster_id'] for c in clusters]
    best = evaluate(campaign, hybrid_payload, assignment, clusters, feasible,
                    order)
    if best is None:
        log('greedy assignment could not be assembled as a payload')
        return None
    best['metrics']['fallback_clusters'] = sorted(
        cid for cid, flag in fallback.items() if isinstance(cid, int) and flag)
    log('initial:', assignment, 'score', score_of(best['metrics']))
    import os
    if os.environ.get('AUTO_LOCAL', '0') != '1':
        return best
    current = dict(assignment)
    current_best = best
    for iteration in range(4):
        improved = False
        for cid in order:
            for layer in allowed[cid]:
                if layer == current[cid]:
                    continue
                probe = dict(current)
                probe[cid] = layer
                result = evaluate(campaign, hybrid_payload, probe, clusters,
                                  feasible, order)
                if result is None:
                    continue
                if score_of(result['metrics']) < score_of(current_best['metrics']):
                    current = probe
                    current_best = result
                    improved = True
                    log(f'iter {iteration}: cluster {cid} -> L{layer}, '
                        f'score {score_of(result["metrics"])}')
        if not improved:
            break
    return current_best


# ---------------------------------------------------------------------------
# variants
# ---------------------------------------------------------------------------
def manual_clusters():
    return [dict(cluster_id=i, groups=list(v[0]))
            for i, v in enumerate(BUNDLES_MANUAL.values())]


def manual_assignment(clusters):
    out = {}
    for cluster in clusters:
        cid = cluster['cluster_id']
        name = list(BUNDLES_MANUAL)[cid]
        out[cid] = BUNDLES_MANUAL[name][1]
    return out


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    campaign, hybrid_payload = load_hybrid_campaign()
    feasible = load_scan()
    if not feasible:
        raise SystemExit('scan results missing; run auto_u_bundle_hybrid.py first')
    log_lines = []

    def log(*args):
        line = ' '.join(str(a) for a in args)
        print(line)
        log_lines.append(line)

    start = time.perf_counter()
    features = quartet_features(campaign)
    clusters, k = auto_clusters(campaign, features)
    log(f'auto clusters k={k}:',
        [(c['cluster_id'], len(c['groups']), c['groups'][:3]) for c in clusters])

    auto = search(campaign, hybrid_payload, clusters, feasible, log=log)
    if auto is None:
        raise SystemExit('automatic assignment failed')
    payload = auto['payload']
    report = S.validate_payload(payload, log=log)
    metrics = S.payload_metrics(campaign, payload, report)
    metrics.update(runtime_seconds=round(time.perf_counter() - start, 2),
                   clustering_k=int(k), clusters=clusters,
                   assignment=auto['metrics']['assignment'],
                   details=auto['metrics']['details'])
    write_json(OUT / 'routes_1024.json', payload, indent=None)
    write_json(OUT / 'auto_assignment.json',
               dict(clusters=clusters, k=int(k),
                    allowed_layers={str(c['cluster_id']):
                                    feasible_layers_for_cluster(c, feasible)
                                    for c in clusters},
                    assignment=auto['metrics']['assignment'],
                    details=auto['metrics']['details']))
    write_json(OUT / 'validation.json', report)
    write_json(OUT / 'summary.json', metrics)
    (OUT / 'run.log').write_text('\n'.join(log_lines) + '\n', encoding='utf-8')

    # manual BUNDLES on the same Hybrid baseline (control)
    mclusters = manual_clusters()
    massign = manual_assignment(mclusters)
    mres = evaluate(campaign, hybrid_payload, massign, mclusters, feasible,
                    [c['cluster_id'] for c in mclusters])
    if mres is not None:
        mreport = S.validate_payload(mres['payload'], log=log)
        mmetrics = S.payload_metrics(campaign, mres['payload'], mreport)
        write_json(OUT / 'manual_on_hybrid_routes_1024.json', mres['payload'],
                   indent=None)
        write_json(OUT / 'manual_on_hybrid_validation.json', mreport)
        write_json(OUT / 'manual_on_hybrid_summary.json',
                   dict(metrics=mmetrics, assignment=massign))
        log('manual-on-hybrid:',
            score_of(mmetrics),
            'validation', mreport.get('status'))

    # comparison table
    hy = read_json(HYBRID_SUMMARY)
    sp = read_json(SPATIAL_SUMMARY)
    table = dict(
        baseline_hybrid=dict(unique_crossing_pairs=hy.get('unique_crossing_pairs'),
                             z1_hv=hy.get('z1_hv_same_height_pairs'),
                             transitions=hy.get('transitions'),
                             length=hy.get('total_length_mm'),
                             min3d=hy.get('min_3d_clearance_mm')),
        manual_spatial_v2=dict(unique_crossing_pairs=sp.get('unique_crossing_pairs'),
                               transitions=sp.get('transitions'),
                               length=sp.get('total_length_mm'),
                               min3d=sp.get('min_3d_clearance_mm')),
        auto_u_bundle=dict(unique_crossing_pairs=metrics['unique_crossing_pairs'],
                           z1_hv=metrics.get('same_layer_u_u_crossing_pairs'),
                           transitions=metrics.get('transitions'),
                           length=metrics.get('total_length_mm'),
                           min3d=metrics.get('min_3d_clearance_mm'),
                           clusters=int(k),
                           assignment=auto['metrics']['assignment']))
    if mres is not None:
        table['manual_on_hybrid'] = dict(
            unique_crossing_pairs=mmetrics['unique_crossing_pairs'],
            transitions=mmetrics.get('transitions'),
            length=mmetrics.get('total_length_mm'),
            min3d=mmetrics.get('min_3d_clearance_mm'))
    write_json(OUT / 'comparison.json', table)
    (OUT / 'READY').write_text('ready\n', encoding='utf-8')
    log('comparison', table)
    return metrics


if __name__ == '__main__':
    run()
