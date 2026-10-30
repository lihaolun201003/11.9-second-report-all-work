# -*- coding: utf-8 -*-
"""E1 integration: comparison table/figure, best_solution selection, report."""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from four_side_1024.e1 import core as C

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

GROUPS = [
    ('BASE', C.E1 / 'baseline', 'complete',
     'published best_solution (7L, Z1 206 lifted / 58 flat)'),
    ('C1', C.E1 / 'E1_C1_z1_only', 'complete',
     'Z1-only: extra legal lift windows, Z2 identical to BASE'),
    ('C2', C.E1 / 'E1_C2_z2_local', 'complete',
     'Z1 priority + single-line Z2 local layer swaps'),
    ('C3', C.E1 / 'E1_C3_z2_bundle', 'complete',
     'Z1 priority + bundle-level Z2 clearance + Z1 window re-optimisation'),
    ('B1 (diagnostic)', C.E1 / 'E1_B1_remove_all_z2', 'diagnostic',
     'all 512 Z2 routes removed from the world - diagnostic only'),
    ('B2 (diagnostic)', C.E1 / 'E1_B2_remove_movable_z2', 'diagnostic',
     'movable Z2 removed (same_u_z2 + opposite_z2 kept out) - diagnostic only'),
    ('D2', C.E1 / 'E1_D_early_lift' / 'D2_baseline_asymmetric', 'complete',
     'BASE layout + asymmetric S-bend windows for the 206 lifted Z1 routes'),
    ('D3', C.E1 / 'E1_D_early_lift' / 'D3_e1c_best', 'complete',
     'E1-C best layout + asymmetric S-bend window refinement'),
    ('D3+Z2retune', C.E1 / 'E1_D_early_lift' / 'D3_e1c_best' /
     'z2_retune_extension', 'complete',
     'C3 layout + re-windowed 8 opposite_z2 L4 routes (48->15 mm) - D3 extension'),
]

FIELDS = ['experiment', 'kind', 'routed', 'unique_crossing_pairs',
          'z1_crossing_pairs', 'z2_crossing_pairs', 'high_layer_crossing_pairs',
          'adjacent_related_events', 'adjacent_line_events',
          'adjacent_arc_events', 'z1_hv_same_height_pairs',
          'opposite_opposite_events', 'transitions', 'total_length_mm',
          'fabrication_hours', 'l6_routes', 'l7_routes', 'validation_status',
          'violations', 'note']

B_KEYS = {
    'routed': 'routed', 'unique_crossing_pairs': 'unique_crossing_pairs',
    'z1_crossing_pairs': 'z1_crossing_pairs',
    'z2_crossing_pairs': 'z2_crossing_pairs',
    'high_layer_crossing_pairs': 'high_layer_crossing_pairs',
    'transitions': 'transitions', 'total_length_mm': 'total_length_mm',
}


def _load_json(path, default=None):
    path = C.Path(path)
    if not path.exists():
        return default
    return C.read_json(path)


def group_row(label, folder, kind, note):
    folder = C.Path(folder)
    row = {field: None for field in FIELDS}
    row.update(experiment=label, kind=kind, note=note)
    summary = _load_json(folder / 'summary.json')
    if summary is None:
        return None
    # B diagnostics store their numbers in E1_B*_metrics.json
    metrics = summary
    if label.startswith('B'):
        extra = list(folder.glob('E1_B*_metrics.json'))
        if extra:
            payload = _load_json(extra[0])
            if payload:
                metrics = dict(summary)
                for key in ('unique_crossing_pairs', 'z1_crossing_pairs',
                            'z2_crossing_pairs', 'high_layer_crossing_pairs',
                            'transitions', 'total_length_mm', 'routed'):
                    if key in payload:
                        metrics[key] = payload[key]
                if 'unique_crossing_pairs' in payload:
                    metrics['unique_crossing_pairs'] = payload[
                        'unique_crossing_pairs']
                for alt in ('z1_pairs', 'z1_crossing_pairs'):
                    if alt in payload:
                        metrics['z1_crossing_pairs'] = payload[alt]
                if metrics.get('unique_crossing_pairs') is None:
                    for alt in ('unique', 'unique_pairs'):
                        if alt in payload:
                            metrics['unique_crossing_pairs'] = payload[alt]
    for field in FIELDS:
        if field in ('experiment', 'kind', 'note'):
            continue
        if field == 'fabrication_hours':
            if metrics.get('fabrication_hours') is not None:
                row[field] = round(float(metrics['fabrication_hours']), 4)
            elif metrics.get('total_length_mm') is not None:
                row[field] = round(float(metrics['total_length_mm']) / 3600.0, 4)
            continue
        if field == 'l6_routes':
            value = metrics.get('l6_route_count', metrics.get('l6_routes'))
            row[field] = value
            continue
        if field == 'l7_routes':
            value = metrics.get('l7_route_count', metrics.get('l7_routes'))
            row[field] = value
            continue
        if field in metrics and metrics[field] is not None:
            row[field] = metrics[field]
    counts = (summary.get('validation_counts') or {})
    row['violations'] = summary.get('n_violations', counts.get('violations'))
    row['validation_status'] = summary.get('validation_status')
    if kind == 'diagnostic':
        # diagnostic worlds are not 1024-channel results: never show them as
        # validated layouts
        row['violations'] = None
        row['validation_status'] = 'not_validated (diagnostic only)'
    return row


def build_comparison():
    rows = []
    for label, folder, kind, note in GROUPS:
        row = group_row(label, folder, kind, note)
        if row is None:
            print(f'[compare] missing {label} ({folder})')
            continue
        rows.append(row)
    C.write_csv(C.E1 / 'comparison.csv', rows, FIELDS)
    C.write_json(C.E1 / 'comparison.json',
                 dict(rows=rows, groups=[dict(label=g[0], folder=str(g[1]),
                                              kind=g[2], note=g[3])
                                         for g in GROUPS]))
    _comparison_figure(rows)
    return rows


def _comparison_figure(rows):
    valid = [row for row in rows if row.get('unique_crossing_pairs')]
    labels = [row['experiment'] for row in valid]
    metrics = [
        ('unique_crossing_pairs', 'global unique crossing pairs'),
        ('z1_crossing_pairs', 'Z1 interface pairs'),
        ('adjacent_related_events', 'adjacent-related pairs (Z1)'),
        ('fabrication_hours', 'ideal fabrication time (h @1 mm/s)'),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.6))
    colors = ['#868e96' if row['kind'] == 'diagnostic' else '#1971c2'
              for row in valid]
    for ax, (key, title) in zip(axes.ravel(), metrics):
        values = [row.get(key) or 0 for row in valid]
        bars = ax.bar(labels, values, color=colors)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis='x', rotation=30, labelsize=8)
        ax.grid(alpha=0.2, axis='y')
        for rect, value in zip(bars, values):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                    f'{value:.0f}' if float(value) >= 10 else f'{value:.2f}',
                    ha='center', va='bottom', fontsize=7)
    fig.suptitle('E1: Z1 priority + Z2 rerouting experiments '
                 '(grey = diagnostic only)', fontsize=12)
    fig.tight_layout()
    fig.savefig(C.E1 / 'comparison.png', dpi=190, bbox_inches='tight')
    plt.close(fig)


def select_best():
    candidates = []
    for label, folder, kind, note in GROUPS:
        if kind != 'complete' or label in ('BASE',):
            continue
        summary = _load_json(C.Path(folder) / 'summary.json')
        if not summary:
            continue
        if int(summary.get('routed') or 0) != 1024:
            continue
        counts = summary.get('validation_counts') or {}
        if int(counts.get('violations') or 0) != 0:
            continue
        candidates.append((int(summary['unique_crossing_pairs']), label,
                           C.Path(folder), summary))
    if not candidates:
        print('[compare] no complete valid candidate')
        return None
    candidates.sort(key=lambda item: (item[0], item[3].get('transitions') or 0,
                                      item[3].get('total_length_mm') or 0))
    unique, label, folder, summary = candidates[0]
    best = C.ensure_dir(C.E1 / 'best_solution')
    for name in ('routes_1024.json', 'summary.json', 'validation.json',
                 'per_route.csv', 'per_layer.csv', '_analysis.json'):
        source = folder / name
        if source.exists():
            shutil.copy2(source, best / name)
    figures = folder / 'figures'
    if figures.exists():
        target = best / 'figures'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(figures, target)
    C.write_json(best / 'BEST_SOURCE.json',
                 dict(source_experiment=label, source_folder=str(folder),
                      unique_crossing_pairs=unique,
                      summary=C.summary_row(label, summary)))
    print(f'[compare] best_solution = {label} ({folder}) unique={unique}')
    return dict(label=label, folder=folder, unique=unique, summary=summary)


def main():
    rows = build_comparison()
    best = select_best()
    for row in rows:
        print({key: row[key] for key in
               ('experiment', 'kind', 'unique_crossing_pairs',
                'z1_crossing_pairs', 'adjacent_related_events',
                'transitions', 'fabrication_hours', 'violations')})
    print('best:', None if best is None else best['label'])


if __name__ == '__main__':
    main()
