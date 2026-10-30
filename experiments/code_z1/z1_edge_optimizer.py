# -*- coding: utf-8 -*-
"""Joint Z1 edge optimisation on the existing 7-layer result.

Key change vs. previous 7L run: move the eight Z2-opposite routes off L2 and
rebuild the Z1 C2 pairs with early climbs (EW -> L2, NS -> L3).  This frees the
Z1 port-lead windows and removes most Z1 base-stub crossings without touching
the overall architecture.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from four_side_1024.manual_c4.hybrid_c2_c4 import HybridData

OUT = Z.OUT_ROOT / 'z1_edge_optimization'
BASE = Z.OUT_ROOT / 'optimized_7L'
MAX_LAYER = 7


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build():
    campaign = HybridData().campaign
    data, z1 = Z.z1_opposite_sets()
    conn = read(Z.CAMPAIGN / 'inputs/connectivity_1024.json')
    z2_opposite = [int(r['route_id']) for r in conn['routes']
                   if r['relation'] == 'opposite' and r['plane'] == 'z2']
    z1_opposite = set(int(r) for r in z1)
    payload = read(BASE / 'routes_1024.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    by_id = {int(r['route_id']): r for r in records}
    fixed = [r for r in records
             if int(r['route_id']) not in z1_opposite | set(z2_opposite)]
    world = Z.make_world(fixed, MAX_LAYER)

    # 1) Z2-opposite: move off L2 -> L4 (or first feasible L3-L5)
    z2_groups = [g for g in conn['groups']
                 if g['kind'] == 'opposite' and g['plane'] == 'z2']
    z2_new = []
    for group in z2_groups:
        ids = [int(x) for x in group['route_ids']]
        chosen = None
        for layer in (4, 5, 3):
            for a in (1.2, 2, 4, 6, 9, 13, 18, 24, 31, 39, 48, 60):
                routes = [Z.build_pair_route(campaign, rid, layer,
                                             Z.layer_z(layer), a, a)
                          for rid in ids]
                if any(route is None for route in routes):
                    continue
                if any(world.check_route(route) for route in routes):
                    continue
                chosen = routes
                break
            if chosen:
                break
        if chosen is None:
            chosen = [by_id[rid] for rid in ids]
        for route in chosen:
            world.add_route(route)
            z2_new.append(route)

    # 2) Z1 pairs: early climbs, EW -> L2, NS -> L3
    z1_new = []
    layers = {}
    fallback = 0
    for pair in data.pairs:
        for key, preferred in (('ew', 2), ('ns', 3)):
            chosen = None
            for layer in [preferred] + [x for x in (4, 5, 6, 7, 3, 2)
                                        if x != preferred]:
                for a in (1.2, 1.8, 2.5, 3.5, 5, 7, 10, 15, 22, 30, 40, 55):
                    routes = Z.build_pair(campaign, pair, key, layer,
                                          Z.layer_z(layer), a)
                    if routes is None:
                        continue
                    if any(world.check_route(route) for route in routes):
                        continue
                    chosen = routes
                    layers[layer] = layers.get(layer, 0) + 1
                    break
                if chosen:
                    break
            if chosen is None:
                chosen = Z.flat_pair(campaign, pair, key)
                fallback += 1
            for route in chosen:
                world.add_route(route)
                z1_new.append(route)

    all_records = fixed + z2_new + z1_new
    return all_records, dict(fallback_pairs=fallback,
                             z1_layer_counts={str(k): v for k, v in layers.items()},
                             fixed_routes=len(fixed),
                             z2_opposite_routes=len(z2_new),
                             z1_routes=len(z1_new))


def main():
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / 'optimized_7L_joint'
    (dst / 'figures').mkdir(parents=True, exist_ok=True)
    records, extra = build()
    report = Z.validate_records if False else None
    payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                   experiment='optimized_7L_joint',
                   layer_stack=Z.stack_payload(MAX_LAYER),
                   routes=records)
    report = Z.validate_payload(payload, max_layer=MAX_LAYER,
                                log=lambda *a: None)
    metrics = Z.crossing_metrics(records, MAX_LAYER)
    metrics.update(extra)
    metrics['validation_status'] = report.get('status')
    metrics['validation_counts'] = dict(report.get('counts') or {})
    metrics['validation_exploratory_pass'] = report.get('exploratory_pass')
    metrics['runtime_seconds'] = round(time.perf_counter() - started, 1)
    Z.write_json(dst / 'routes_1024.json', payload, indent=None)
    Z.write_json(dst / 'summary.json', metrics)
    Z.write_json(dst / 'validation.json', report)
    old = read(BASE / 'summary.json')
    comparison = dict(
        old_7L=dict(unique_crossing_pairs=old.get('unique_crossing_pairs'),
                    z1_hv=old.get('z1_hv_same_height_pairs'),
                    transitions=old.get('transitions'),
                    length_mm=old.get('total_length_mm')),
        new_7L_joint=dict(unique_crossing_pairs=metrics['unique_crossing_pairs'],
                          z1_hv=metrics.get('z1_hv_same_height_pairs'),
                          transitions=metrics['transitions'],
                          length_mm=metrics['total_length_mm'],
                          validation=metrics['validation_status'],
                          violations=metrics['validation_counts'].get('violations')))
    Z.write_json(OUT / 'joint_vs_old.json', comparison)
    print(json.dumps(comparison, ensure_ascii=False, indent=1))
    print('saved', dst)


if __name__ == '__main__':
    main()
