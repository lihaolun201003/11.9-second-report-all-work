# -*- coding: utf-8 -*-
"""Generate the round-2 plots from final C routes plus A/B/C summaries."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from . import bidirectional_1mm_plots as P
from .bidirectional_1mm_layer_assignment import OUT as BASE
from .bidirectional_round2_assignment import OUT as OUT2, PHYSICAL_LAYERS

P.OUT = OUT2
P.ROUTES = OUT2 / 'routes_l3d.json'
P.ASSIGN = OUT2 / 'assignment_1024.csv'
P.FINAL = OUT2 / 'final_stats.json'
P.CROSS = OUT2 / 'crossings_after.json'
P.PLOTS = OUT2 / 'plots'
P.COLORS['Z2_UP'] = '#c53030'
P.COLORS['Z2_MIDDLE'] = '#ed8936'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def extra_plots():
    plots = OUT2 / 'plots'; plots.mkdir(exist_ok=True)
    # 13: 12 candidate Z2 heights vs actual 4 legal target planes
    fig, ax = plt.subplots(figsize=(12, 6))
    cand = [0.08 + 0.05 * i for i in range(9)] + [0.53, 0.58, 0.63]
    ax.scatter([1] * len(cand), cand, color='#c53030', s=60,
               label='A 候选：12 个独立 Z2 目标高度')
    actual = [v for k, v in PHYSICAL_LAYERS.items() if v >= 0]
    ax.scatter([2] * len(actual), actual, color='#2f855a', s=90,
               label='C 合法：4 个实际 Z2 物理层')
    for z in cand:
        ax.text(1.08, z, f'{z:.2f}', va='center', fontsize=7)
    for z in actual:
        ax.text(2.08, z, f'{z:.2f}', va='center', fontsize=8)
    ax.axhline(0.5, color='black', ls='--', lw=1)
    ax.text(1.3, .505, 'Z2 interface z=0.50', fontsize=8)
    ax.set_xlim(.7, 2.5); ax.set_ylim(0, .8)
    ax.set_xticks([1, 2]); ax.set_xticklabels(['A 12 层候选', 'C 最终合法'])
    ax.set_ylabel('z (mm)')
    ax.set_title('图13 Z2 12 个候选独立层 vs 最终满足 0.08 mm 净空的 4 层')
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(plots / '13_z2_12_vs_legal.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    # 14: A/B/C comparison
    stats = {}
    for label, path in (('A', OUT2 / 'experiment_A/final_stats.json'),
                        ('B', OUT2 / 'experiment_B/final_stats.json'),
                        ('C', OUT2 / 'final_stats.json')):
        d = read(path)
        stats[label] = d
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    labels = ['A 12层冻结XY', 'B 12层目标重布', 'C 4层目标重布']
    routed = [stats[k]['routed'] for k in 'ABC']
    z2 = [stats[k]['z2_routed'] for k in 'ABC']
    axes[0].bar(labels, routed, color=['#9ca3af', '#ed8936', '#2f855a'])
    axes[0].set_title('总布通数')
    for i, v in enumerate(routed):
        axes[0].text(i, v + 8, str(v), ha='center')
    axes[1].bar(labels, z2, color=['#9ca3af', '#ed8936', '#2f855a'])
    axes[1].set_title('Z2 布通数')
    for i, v in enumerate(z2):
        axes[1].text(i, v + 3, str(v), ha='center')
    fig.suptitle('图14 A/B/C 实际布通对比')
    fig.tight_layout()
    fig.savefig(plots / '14_ABC_comparison.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    # 15: recovery classification
    audit = list(__import__('csv').DictReader(open(
        OUT2 / 'route_change_audit.csv', encoding='utf-8-sig')))
    counts = {}
    for row in audit:
        counts[row['change']] = counts.get(row['change'], 0) + 1
    fig, ax = plt.subplots(figsize=(8, 5))
    keys = list(counts); vals = [counts[k] for k in keys]
    ax.bar(keys, vals, color=['#2f855a' if k == 'recovered' else '#9ca3af'
                              if k == 'unchanged' else '#c53030' for k in keys])
    for i, v in enumerate(vals):
        ax.text(i, v + 3, str(v), ha='center')
    ax.set_title('图15 第一轮合法 735 条 → 第二轮 C 801 条的逐线路变化')
    ax.set_ylabel('route count')
    fig.tight_layout()
    fig.savefig(plots / '15_recovery_classification.png', dpi=150,
                bbox_inches='tight')
    plt.close(fig)
    manifest = read(plots / 'manifest.json')
    manifest['figures'] += [
        dict(file='13_z2_12_vs_legal.png', status='rendered',
             title='Z2 12 independent candidate planes vs final legal 4'),
        dict(file='14_ABC_comparison.png', status='rendered',
             title='A/B/C actual routed comparison'),
        dict(file='15_recovery_classification.png', status='rendered',
             title='recovery classification from 735 to 801')]
    (plots / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False,
                                                    indent=1), encoding='utf-8')


if __name__ == '__main__':
    P.main()
    extra_plots()
    print('plots done')
