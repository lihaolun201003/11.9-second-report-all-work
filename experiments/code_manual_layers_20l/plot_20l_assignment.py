# -*- coding: utf-8 -*-
"""Layer assignment statistics figure (L1-L20) for the 20-layer scheme."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RUN = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L'
data = json.loads((RUN / 'layer_assignment_1024.json').read_text(encoding='utf-8'))
rows = data['rows']
counts = Counter()
for row in rows:
    key = 'interface_z2' if row['layer'] is None else f"L{row['layer']}"
    counts[key] += 1
labels = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'] + [f'L{i}' for i in range(8, 21)] + ['z2_iface']
values = [counts.get(label, 0) for label in labels]
colors = ['#2f9e44' if label in ('L1', 'L2', 'L3', 'L4') else
          '#1f6fd6' if label in ('L6', 'L7') else
          '#e07b1a' if label.startswith('L') and label not in ('L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7') and label != 'L20' else
          '#adb5bd' for label in labels]
fig, ax = plt.subplots(figsize=(12.5, 5.6))
bars = ax.bar(range(len(labels)), values, color=colors, edgecolor='#343a40', linewidth=0.5)
for bar, value in zip(bars, values):
    if value:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.2,
                str(value), ha='center', fontsize=7)
ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=0, fontsize=8)
ax.set_ylabel('connections assigned')
ax.set_title('Deterministic L1-L20 layer assignment (1024 connections)\n'
             'green = fixed manual U (L1-L4), blue = Z1 N-S / E-W '
             '(L6/L7), orange = Z2 connector groups (L8-L19), '
             'grey = Z2 interface plane; L5/L20 unused', fontsize=9.5)
ax.grid(axis='y', alpha=0.25)
fig.tight_layout()
target = RUN / 'layer_assignment_counts.png'
fig.savefig(target, dpi=160)
plt.close(fig)
print('wrote', target)
print('counts:', dict(counts))
