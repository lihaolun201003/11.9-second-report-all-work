# -*- coding: utf-8 -*-
"""Automatic U-bundle / target-layer experiment on top of the frozen Hybrid H result.

This module does NOT modify any existing module or output. It reuses the
Structured-A / Hybrid / Spatial-U builders through imports and writes only to
the new directory ``auto_u_bundle_hybrid``.

Phase 1 (this script): scan feasible (a, D) parameters for every same-side U
quartet and every target layer L2..L5 against the *frozen Hybrid H world minus
all 64 U quartets*. Results are cached as one JSON per (group, layer).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply  # noqa: E402

apply()

from four_side_1024.manual_c4 import spatial_u_bundle as S  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity'
HYBRID_H = CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json'
OUT = CAMPAIGN / 'auto_u_bundle_hybrid'
WORK = OUT / '_work'
SCAN = WORK / 'scan'

LAYERS = [(2, 1.0), (3, 1.5), (4, 2.0), (5, 2.5)]
A_VALUES = [1.2, 2.4, 4.0, 6.0, 8.0, 10.0, 13.0, 16.0, 20.0, 25.0, 30.0,
            36.0, 44.0, 52.0]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_hybrid_campaign():
    """Spatial-U Campaign with Hybrid-H as the *fixed* world."""
    campaign = S.Campaign()
    payload = read_json(HYBRID_H)
    records = {int(r['route_id']): r for r in payload['routes']
               if r.get('status') == 'routed'}
    connectivity = campaign.connectivity
    same = {int(r['route_id']) for r in connectivity['routes']
            if r['relation'] == 'same'}
    campaign.baseline_records = {rid: rec for rid, rec in records.items()
                                 if rid not in same}
    campaign.target_rids = set(same)
    campaign.layer_stack_payload = payload['layer_stack']
    return campaign


def candidate_pairs(layer_z, base_z):
    from four_side_1024.v3c4.lift_cross import transition_geometry
    f = float(transition_geometry(layer_z - base_z)['footprint_mm'])
    out = []
    for a in A_VALUES:
        for k in range(20):
            d = a + f + 2.4 + 0.5 * k
            out.append((round(a, 3), round(d, 3)))
    return out


def scan_group_layer(campaign, world, gid, layer, layer_z):
    """Return feasible [(a, D)] for one quartet on one target layer."""
    group = campaign.groups[int(gid)]
    ids = [int(r) for r in group['route_ids']]
    from four_side_1024.v3c4.lift_cross import row_z
    base_z = row_z(1 if campaign.record(ids[0])['plane'] == 'z1' else 2)
    pairs = candidate_pairs(layer_z, base_z)
    feasible = []
    for a, d in pairs:
        routes, err = S.build_quartet(campaign, int(gid), layer, layer_z,
                                      d, a, a)
        if routes is None:
            continue
        violations = S.check_routes(world, routes)
        if violations:
            continue
        feasible.append((a, d))
    return feasible


_INIT = {}


def _init_worker():
    campaign = load_hybrid_campaign()
    world = S.fixed_world(campaign)
    _INIT['campaign'] = campaign
    _INIT['world'] = world


def _task(args):
    gid, layer, layer_z = args
    started = time.perf_counter()
    feasible = scan_group_layer(_INIT['campaign'], _INIT['world'], gid, layer,
                                layer_z)
    elapsed = round(time.perf_counter() - started, 2)
    path = SCAN / f'g{int(gid)}_{int(layer)}.json'
    payload = dict(group_id=int(gid), layer=int(layer), layer_z=float(layer_z),
                   feasible=[[float(a), float(d)] for a, d in feasible],
                   seconds=elapsed)
    path.write_text(json.dumps(payload), encoding='utf-8')
    return int(gid), int(layer), len(feasible), elapsed


def run_scan(workers=8):
    SCAN.mkdir(parents=True, exist_ok=True)
    campaign = load_hybrid_campaign()
    tasks = []
    for gid in sorted(campaign.groups):
        group = campaign.groups[int(gid)]
        if group.get('kind') != 'same':
            continue
        for layer, layer_z in LAYERS:
            tasks.append((int(gid), int(layer), float(layer_z)))
    print(f'scan tasks: {len(tasks)}')
    started = time.perf_counter()
    if workers <= 1:
        _init_worker()
        for task in tasks:
            print(_task(task))
    else:
        with mp.Pool(workers, initializer=_init_worker) as pool:
            for result in pool.imap_unordered(_task, tasks):
                print('done', result)
    print('total seconds', round(time.perf_counter() - started, 1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    run_scan(args.workers)
