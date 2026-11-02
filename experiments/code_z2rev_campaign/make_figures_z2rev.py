# -*- coding: utf-8 -*-
"""Figures + per-route/per-layer tables for the revised-Z2 (1000/1024) campaign."""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
BEST = CAMPAIGN / 'best_solution'
FIGS = BEST / 'figures'
LIFT = CAMPAIGN / '02_layer_sweep/L15/lift'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_old_finalize():
    spec = importlib.util.spec_from_file_location('old_finalize2',
                                                  OLD / 'finalize2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    F = load_old_finalize()
    payload = read(LIFT / 'routes_l3d.json')
    records = payload['routes']
    crossings = read(LIFT / 'crossings_after.json')
    routed = [record for record in records
              if record.get('status') == 'routed']
    F.figure_overall_3d(records, FIGS / 'overall_3d.png',
                        'revised Z2 (user directions): 15L overall 3D, '
                        f'{len(routed)}/1024 routed')
    F.figure_overall_2d(records, FIGS / 'overall_2d.png',
                        'revised Z2 (user directions): 15L overall XY')
    F.figure_crossings(crossings.get('crossings') or [],
                       FIGS / 'crossing_hotspots.png',
                       f'revised Z2 15L crossing hotspots '
                       f'({crossings.get("unique_pair_count")} pairs)')
    # per-route / per-layer tables
    per_route = []
    layer_counts = Counter()
    for record in records:
        rid = int(record['route_id'])
        if record.get('status') != 'routed':
            per_route.append(dict(route_id=rid, plane=record.get('plane'),
                                  status='failed', transitions=0,
                                  length_mm=0.0, layers=''))
            continue
        parts = record.get('parts') or []
        zs = sorted({round(float(part['z_mm']), 6) for part in parts
                     if part.get('kind') == 'flat'})
        trans = sum(1 for part in parts if part.get('kind') == 'transition')
        length = float(record.get('length_mm') or 0.0)
        per_route.append(dict(route_id=rid, plane=record.get('plane'),
                              status='routed', transitions=trans,
                              length_mm=round(length, 4),
                              layers=';'.join(str(z) for z in zs)))
        for z in zs:
            layer_counts[z] += 1
    with (BEST / 'per_route.csv').open('w', encoding='utf-8',
                                       newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_route[0].keys()))
        writer.writeheader()
        writer.writerows(per_route)
    layers = sorted(layer_counts)
    with (BEST / 'per_layer.csv').open('w', encoding='utf-8',
                                       newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['z_mm', 'routes'])
        for z in layers:
            writer.writerow([z, layer_counts[z]])
    # comparison figure (old vs new)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    comparison = read(CAMPAIGN / 'comparison_z2rev.json')
    phase2 = read(CAMPAIGN / 'phase2_summary.json')
    old_row = read(OLD / 'best_solution/layer_row.json')
    labels = ['2D routed\n(/1024)', '15L routed\n(/1024)',
              '2D crossing pairs', '15L crossing pairs']
    old_values = [992, old_row.get('routed'), 116748,
                  old_row.get('unique_crossing_pairs')]
    new_values = [comparison['two_d']['new_routed'],
                  comparison['three_d_15l']['new_routed'],
                  comparison['two_d']['new_pairs'],
                  comparison['three_d_15l']['new_pairs']]
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.4))
    x = np.arange(2)
    width = 0.36
    axes[0].bar(x - width / 2, old_values[:2], width,
                label='previous Z2 (992)', color='#adb5bd')
    axes[0].bar(x + width / 2, new_values[:2], width,
                label='revised Z2 (1000)', color='#1971c2')
    axes[0].set_xticks(x, ['2D routed', '15L routed'])
    axes[0].set_ylim(960, 1010)
    axes[0].set_ylabel('routed connections (/1024)')
    axes[0].set_title('routed count: revised Z2 vs previous')
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2, axis='y')
    for index, (old_v, new_v) in enumerate(zip(old_values[:2], new_values[:2])):
        axes[0].text(index - width / 2, old_v, str(old_v), ha='center',
                     va='bottom', fontsize=8)
        axes[0].text(index + width / 2, new_v, str(new_v), ha='center',
                     va='bottom', fontsize=8)
    axes[1].bar(x - width / 2, old_values[2:], width,
                label='previous Z2 (992)', color='#adb5bd')
    axes[1].bar(x + width / 2, new_values[2:], width,
                label='revised Z2 (1000)', color='#1971c2')
    axes[1].set_xticks(x, ['2D crossing pairs', '15L crossing pairs'])
    axes[1].set_ylabel('global unique crossing pairs')
    axes[1].set_title('crossings: revised Z2 vs previous')
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.2, axis='y')
    for index, (old_v, new_v) in enumerate(zip(old_values[2:], new_values[2:])):
        axes[1].text(index - width / 2, old_v, str(old_v), ha='center',
                     va='bottom', fontsize=8)
        axes[1].text(index + width / 2, new_v, str(new_v), ha='center',
                     va='bottom', fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / 'comparison_old_vs_new.png', dpi=175)
    plt.close(fig)
    print('figures written:', sorted(path.name for path in FIGS.glob('*.png')))
    print('layer counts:', dict(sorted(layer_counts.items())))


if __name__ == '__main__':
    main()
