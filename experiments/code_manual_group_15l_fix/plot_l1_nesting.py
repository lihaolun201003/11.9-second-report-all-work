# -*- coding: utf-8 -*-
"""Clean nested-U proof plot for L1 (colour = U depth / nesting level)."""
import json
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.collections import LineCollection

from four_side_1024.manual_c4_adapt import manual_u_geometry as G

OUT = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_COMPARISON_FIXED'
phase1 = json.loads((OUT / 'manual_phase1.json').read_text(encoding='utf-8'))
rows = [row for row in phase1['layer_orders']['1'] if not row.get('failed')]

cmap = cm.get_cmap('viridis')
depths = sorted({round(row['depth_mm'], 3) for row in rows})
color_of = {depth: cmap(index / max(1, len(depths) - 1))
            for index, depth in enumerate(depths)}

fig, axes = plt.subplots(1, 2, figsize=(13.2, 6.6))
for ax, side in zip(axes, ('N', 'S')):
    side_rows = [row for row in rows if row['side'] == side]
    for row in side_rows:
        array = G._sample_xy(row['primitives'], sagitta=0.002)
        if array is None:
            continue
        color = color_of[round(row['depth_mm'], 3)]
        ax.plot(array[:, 0], array[:, 1], color=color, lw=1.6, zorder=3)
        ax.text(array[0, 0], array[0, 1] + (1.4 if side == 'N' else -2.2),
                f"{row['depth_mm']:.2f}", fontsize=4.6, color=color,
                ha='center', va='center')
    ax.set_xlim(10, 140)
    ax.set_ylim(15, 40) if side == 'S' else ax.set_ylim(118, 152)
    ax.set_aspect('equal')
    ax.grid(alpha=0.20)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title(f'L1 / {side} side: 32 real R15 U\'s, depth-coloured '
                 f'(nesting order, deepest = {max(depths):.2f} mm)', fontsize=8.5)
sm = plt.cm.ScalarMappable(cmap=cmap,
                           norm=plt.Normalize(min(depths), max(depths)))
fig.colorbar(sm, ax=axes, shrink=0.8, label='U depth (mm)')
fig.suptitle('L1 manual U geometry after the fix: every connection is a freshly '
             'built straight+R15-arc U (outer deeper, inner shallower); '
             'minimum U-to-U clearance 0.25 mm', fontsize=10)
fig.savefig(OUT / 'plots_manual' / 'manual_layer_L1_nesting_zoom.png', dpi=180,
            bbox_inches='tight')
plt.close(fig)
print('wrote', OUT / 'plots_manual' / 'manual_layer_L1_nesting_zoom.png')
print('depths:', min(depths), '..', max(depths), 'count', len(rows))
