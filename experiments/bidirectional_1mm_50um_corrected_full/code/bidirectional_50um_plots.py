# -*- coding: utf-8 -*-
"""Plots for corrected 50 um run."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from . import bidirectional_1mm_plots as P
from . import bidirectional_50um_assignment as A50

OUT = Path(A50.OUT)
P.OUT = OUT
P.ROUTES = OUT / 'routes_l3d.json'
P.ASSIGN = OUT / 'assignment_1024.csv'
P.FINAL = OUT / 'final_stats.json'
P.CROSS = OUT / 'crossings_after.json'
P.PLOTS = OUT / 'plots'
P.PHYSICAL_LAYERS = A50.PHYSICAL_LAYERS


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def extra():
    plots = OUT / 'plots'; plots.mkdir(exist_ok=True)
    # 50 um legal XY-overlap example: find two flats on adjacent z with overlap.
    routes = {int(r['route_id']): r for r in read(OUT / 'routes_l3d.json')['routes']
              if r.get('status') == 'routed'}
    by_z = {}
    for rid, route in routes.items():
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                by_z.setdefault(round(float(part['z_mm']), 9), []).append(
                    (rid, part))
    zs = sorted(z for z in by_z if z < 0.5 and z > -0.5)
    example = None
    for za, zb in zip(zs, zs[1:]):
        if abs((zb - za) - 0.05) < 1e-8:
            for ra, pa in by_z[za]:
                for rb, pb in by_z[zb]:
                    example = (za, zb, ra, pa, rb, pb); break
                if example: break
        if example: break
    fig, ax = plt.subplots(figsize=(10, 5))
    if example:
        za, zb, ra, pa, rb, pb = example
        for z, rid, part in ((za, ra, pa), (zb, rb, pb)):
            pts = []
            for prim in part['primitives']:
                if prim['kind'] == 'line':
                    pts += [prim['p0'], prim['p1']]
                else:
                    pts += [prim['p0'], prim['p1']]
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    marker='o', ms=2, label=f'route {rid}, z={z:.3f}')
        ax.set_title('图13 50 μm 层距、XY 可重合的合法实例（不同 z，真实平面）')
        ax.legend(fontsize=8); ax.set_aspect('equal')
    fig.tight_layout()
    fig.savefig(plots / '13_50um_legal_overlap.png', dpi=150,
                bbox_inches='tight')
    plt.close(fig)
    # rule comparison bars
    oldA = read(OUT / 'old_A_revalidation.json')
    oldB = read(OUT / 'old_B_revalidation.json')
    c = read(OUT / 'final_stats.json')
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].bar(['old A', 'new A', 'old B', 'new B'],
                [oldA['old_80um_violations'], oldA['new_50um_violations'],
                 oldB['old_80um_violations'], oldB['new_50um_violations']],
                color=['#9ca3af', '#2b6cb0', '#9ca3af', '#2f855a'])
    axes[0].set_title('旧 80 μm vs 新 50 μm 规则违规数')
    axes[0].set_yscale('log')
    for i, v in enumerate([oldA['old_80um_violations'],
                           oldA['new_50um_violations'],
                           oldB['old_80um_violations'],
                           oldB['new_50um_violations']]):
        axes[0].text(i, v * 1.2, str(v), ha='center', fontsize=8)
    axes[1].bar(['old C 801', 'new B 723', 'new C 809'],
                [801, 723, c['routed']],
                color=['#9ca3af', '#ed8936', '#2f855a'])
    axes[1].set_title('实际合法布通对比')
    for i, v in enumerate([801, 723, c['routed']]):
        axes[1].text(i, v + 8, str(v), ha='center')
    fig.suptitle('图14 修正规则后的违规定量变化与最终布通')
    fig.tight_layout()
    fig.savefig(plots / '14_rule_and_final_comparison.png', dpi=150,
                bbox_inches='tight')
    plt.close(fig)
    # 12-layer allocation
    fig, ax = plt.subplots(figsize=(11, 6))
    for lid, z in A50.PHYSICAL_LAYERS.items():
        color = '#2b6cb0' if lid <= 7 else '#c53030'
        ax.axhline(z, color=color, lw=3)
        ax.text(0.1, z, f'L{lid} {z:+.2f}', va='center', fontsize=7)
    ax.axhline(0.0, color='k', ls='--', lw=1)
    ax.axhline(0.5, color='k', ls='--', lw=1)
    ax.set_xlim(0, 2); ax.set_yticks([])
    ax.set_title('图15 Z1 6 层与 Z2 12 个独立目标层的 50 μm 高度分配')
    fig.tight_layout()
    fig.savefig(plots / '15_18_layer_allocation.png', dpi=150,
                bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    P.main()
    extra()
    print('plots done')
