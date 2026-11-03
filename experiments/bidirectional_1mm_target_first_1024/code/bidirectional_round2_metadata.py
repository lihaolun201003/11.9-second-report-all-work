# -*- coding: utf-8 -*-
"""Finalize round-2 metadata: per-layer stats, audit, run log."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .bidirectional_round2_assignment import OUT as OUT2, PHYSICAL_LAYERS
from .bidirectional_1mm_layer_assignment import OUT as BASE

C = OUT2 / 'experiment_C'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def main():
    routes = {int(r['route_id']): r for r in read(
        OUT2 / 'routes_l3d.json')['routes'] if r.get('status') == 'routed'}
    assign = {int(r['route_id']): r for r in csv.DictReader(
        open(OUT2 / 'assignment_1024.csv', encoding='utf-8-sig'))}
    cross = read(OUT2 / 'crossings_after.json')
    by_height = {float(k): v for k, v in cross.get('pair_count_by_height',
                                                    {}).items()}
    layers = defaultdict(lambda: [0, 0, 0])
    for rid, row in assign.items():
        layer = row['physical_layer']
        layers[layer][0] += 1
        layers[layer][1] += int(rid in routes)
        layers[layer][2] += int(rid not in routes)
    stats = {}
    z_map = {row['physical_layer']: float(row['target_z_mm'])
             for row in assign.values()}
    for layer, value in layers.items():
        z = z_map[layer]
        stats[layer] = dict(assigned=value[0], routed=value[1],
                            failed=value[2], z_mm=z,
                            crossings=by_height.get(round(z, 9), 0))
    (OUT2 / 'per_layer_stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
    # enriched final stats
    final = read(OUT2 / 'final_stats.json')
    regions = Counter(assign[rid]['region'] for rid in routes)
    final.update(dict(
        z1_routed=sum(1 for rid in routes if assign[rid]['plane'] == 'z1'),
        z2_routed=sum(1 for rid in routes if assign[rid]['plane'] == 'z2'),
        manual_u_routed=sum(1 for rid in routes
                            if assign[rid]['logical_kind'] == 'manual_u'),
        interface_routed=sum(1 for rid in routes
                             if assign[rid]['region'] == 'Z2_INTERFACE'),
        routed_by_region=dict(regions),
        total_length_mm=round(sum(float(r.get('length_mm') or 0)
                                  for r in routes.values()), 4),
        total_transitions=sum(int(r.get('n_transitions') or 0)
                              for r in routes.values()),
        z2_independent_planes=4,
        z2_logical_groups=12,
        glass=read(BASE / 'glass_geometry.json'),
        note=('Experiment C uses the best legal 4-Z2-plane stack; the 12-plane '
              'A/B attempts are kept with their invalid-clearance evidence.'),
    ))
    (OUT2 / 'final_stats.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    # allocation audit
    audit = read(OUT2 / 'route_change_audit.csv') if False else None
    a = read(OUT2 / 'experiment_A/final_stats.json')
    b = read(OUT2 / 'experiment_B/final_stats.json')
    audit = dict(
        experiment_A=dict(z2_independent_planes=12, routed=a['routed'],
                          z1=a['z1_routed'], z2=a['z2_routed'],
                          violations=a['validation_counts']['violations'],
                          geometry_pass=a.get('geometry_pass')),
        experiment_B=dict(z2_independent_planes=12, routed=b['routed'],
                          z1=b['z1_routed'], z2=b['z2_routed'],
                          violations=b['validation_counts']['violations'],
                          geometry_pass=b.get('geometry_pass')),
        experiment_C=dict(z2_independent_planes=4, routed=final['routed'],
                          z1=final['z1_routed'], z2=final['z2_routed'],
                          violations=final['validation_counts']['violations'],
                          geometry_pass=final.get('geometry_pass')),
        finding=('12 independent Z2 planes at 0.05 mm pitch cannot satisfy '
                 'the 0.08 mm true-3D clearance with the current route XY '
                 'envelopes: A has 330916 and B 388276 clearance violations. '
                 'The best legal result is the 4-Z2-plane C fallback.'))
    (OUT2 / 'layer_allocation_audit.json').write_text(
        json.dumps(audit, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    # run log
    parts = ['# BIDIRECTIONAL_1MM_TARGET_FIRST_1024 run log', '']
    for name in ('experiment_A/run.log', 'experiment_A/validate.log',
                 'experiment_B/run.log', 'experiment_B/validate.log',
                 'experiment_C/run.log', 'experiment_C/validate.log',
                 'run_plots.log', 'finalize.log'):
        p = OUT2 / name
        if p.exists():
            parts += [f'===== {name} =====',
                      p.read_text(encoding='utf-8', errors='replace')]
    (OUT2 / 'run.log').write_text('\n'.join(parts), encoding='utf-8')
    print('final', final['routed'], final['z1_routed'], final['z2_routed'],
          final['manual_u_routed'], final['validation_counts'], stats)


if __name__ == '__main__':
    main()
