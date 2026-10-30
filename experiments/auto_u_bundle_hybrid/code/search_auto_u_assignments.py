# -*- coding: utf-8 -*-
"""Search automatic U-cluster -> layer assignments in parallel and save the best.

Candidates are all distinct-layer permutations allowed by the scan, plus a few
same-layer variants. Each candidate is evaluated by the same
``run_auto_u_bundle_hybrid.evaluate`` used by the greedy experiment; the best
(by global unique crossing pairs, then transitions, length) is re-evaluated and
written to the output directory.
"""
from __future__ import annotations

import itertools
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply  # noqa: E402

apply()

from four_side_1024.manual_c4 import run_auto_u_bundle_hybrid as R  # noqa: E402

OUT = R.OUT
_CTX = {}


def _init():
    campaign, payload = R.load_hybrid_campaign()
    feasible = R.load_scan()
    clusters, k = R.auto_clusters(campaign, R.quartet_features(campaign))
    _CTX.update(campaign=campaign, payload=payload, feasible=feasible,
                clusters=clusters, order=[c['cluster_id'] for c in clusters])


def _eval_assignment(assignment):
    ctx = _CTX
    started = time.perf_counter()
    result = R.evaluate(ctx['campaign'], ctx['payload'], assignment,
                        ctx['clusters'], ctx['feasible'], ctx['order'])
    elapsed = time.perf_counter() - started
    if result is None:
        return None
    m = result['metrics']
    return dict(assignment={str(k): int(v) for k, v in assignment.items()},
                unique_crossing_pairs=int(m['unique_crossing_pairs']),
                transitions=int(m.get('transitions') or 0),
                length=float(m.get('total_length_mm') or 0.0),
                seconds=round(elapsed, 1))


def candidates(clusters):
    allowed = {c['cluster_id']: R.feasible_layers_for_cluster(c, _CTX['feasible'])
               for c in clusters}
    cids = [c['cluster_id'] for c in clusters]
    out = []
    # 1) all distinct-layer permutations allowed by the scan
    for layers in itertools.permutations([2, 3, 4, 5], len(cids)):
        assignment = {}
        ok = True
        for cid, layer in zip(cids, layers):
            if layer not in allowed[cid]:
                ok = False
                break
            assignment[cid] = layer
        if ok:
            out.append(assignment)
    # 2) a few shared-layer variants (same layer for two middle bundles etc.)
    shared = [
        {0: 3, 1: 4, 2: 5, 3: 3},
        {0: 4, 1: 3, 2: 5, 3: 4},
        {0: 5, 1: 3, 2: 4, 3: 5},
        {0: 3, 1: 3, 2: 4, 3: 5},
        {0: 2, 1: 3, 2: 4, 3: 5},
        {0: 2, 1: 4, 2: 3, 3: 5},
        {0: 2, 1: 5, 2: 3, 3: 4},
        {0: 3, 1: 4, 2: 5, 3: 2},
    ]
    for item in shared:
        if all(item[cid] in allowed[cid] for cid in cids):
            out.append(dict(item))
    # de-duplicate
    seen, uniq = set(), []
    for item in out:
        key = tuple(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq


def main():
    _init()
    plans = candidates(_CTX['clusters'])
    print('candidates', len(plans))
    started = time.perf_counter()
    results = []
    with mp.Pool(4, initializer=_init) as pool:
        for i, res in enumerate(pool.imap_unordered(_eval_assignment, plans)):
            if res is not None:
                results.append(res)
            print('done', i + 1, 'valid', len(results), res)
    results.sort(key=lambda r: (r['unique_crossing_pairs'], r['transitions'],
                                r['length']))
    print('evaluated seconds', round(time.perf_counter() - started, 1))
    for row in results[:10]:
        print('TOP', row)
    if not results:
        raise SystemExit('no valid assignment')
    best = results[0]
    assignment = {int(k): int(v) for k, v in best['assignment'].items()}
    # re-evaluate in the parent process to get the payload, then validate
    campaign = _CTX['campaign']
    payload_ctx = _CTX['payload']
    feasible = _CTX['feasible']
    clusters = _CTX['clusters']
    order = _CTX['order']
    result = R.evaluate(campaign, payload_ctx, assignment, clusters, feasible,
                        order)
    payload = result['payload']
    report = R.S.validate_payload(payload, log=print)
    metrics = R.S.payload_metrics(campaign, payload, report)
    metrics.update(assignment=assignment, clusters=clusters,
                   clustering_k=4, search='automatic layer search',
                   candidates=len(plans), best=best)
    R.write_json(OUT / 'routes_1024.json', payload, indent=None)
    R.write_json(OUT / 'auto_assignment.json',
                 dict(clusters=clusters, assignment=assignment,
                      candidates=len(plans), best=best,
                      details=result['metrics'].get('details')))
    R.write_json(OUT / 'validation.json', report)
    R.write_json(OUT / 'summary.json', metrics)
    table = json.loads((OUT / 'comparison.json').read_text(encoding='utf-8'))
    table['auto_u_bundle'] = dict(
        unique_crossing_pairs=metrics['unique_crossing_pairs'],
        transitions=metrics.get('transitions'),
        length=metrics.get('total_length_mm'),
        min3d=metrics.get('min_3d_clearance_mm'),
        clusters=4, assignment=assignment, candidates=len(plans),
        best=best)
    R.write_json(OUT / 'comparison.json', table)
    (OUT / 'SEARCH_READY').write_text('ready\n', encoding='utf-8')
    print('BEST', best)
    print('comparison', table)


if __name__ == '__main__':
    main()
