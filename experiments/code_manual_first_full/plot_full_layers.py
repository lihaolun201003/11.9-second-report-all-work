# -*- coding: utf-8 -*-
"""Per-layer routing plots for the manual-first full run."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RUN = (ROOT / 'outputs/manual_c4_new_connectivity'
       / 'MANUAL_GROUP_15L_MANUAL_FIRST_FULL')
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN')
spec = importlib.util.spec_from_file_location(
    'campaign_layer_views', CAMPAIGN / 'make_layer_views.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

payload = json.loads((RUN / 'routes_l3d.json').read_text(encoding='utf-8'))
data = module.build_layer_data(payload)
z_levels = sorted(data['routes_by_layer'])
print('layer planes:', z_levels)
fig, axes = plt.subplots(4, 4, figsize=(4.9 * 4, 4.35 * 4))
axes = np.atleast_2d(axes)
z_to_layer = {0.0: 'L1(z1)', 0.5: 'L1(z2)'}
for layer_id in range(2, 16):
    z_to_layer[round(0.65 + 0.15 * (layer_id - 2), 6)] = f'L{layer_id}'
for index, ax in enumerate(axes.ravel()):
    if index >= 16:
        ax.axis('off')
        continue
    z = z_levels[index] if index < len(z_levels) else None
    if z is None or z not in data['routes_by_layer']:
        ax.axis('off')
        continue
    info = module.draw_layer(ax, z, data, dense_context=True, annotate=False)
    ax.set_title(f"{z_to_layer.get(round(z, 6), '')}  z={z:.2f} mm\n"
                 f"{info['routes']} routes | {info['transition_endpoints']} "
                 f"transition endpoints", fontsize=8.0)
    ax.tick_params(labelsize=5)
    ax.set_xlabel('x (mm)', fontsize=5.5)
    ax.set_ylabel('y (mm)', fontsize=5.5)
fig.suptitle('Manual-first full run (256 manual U fixed + 540 auto routes, '
             '2D-plane solution): per-layer routing plots', fontsize=11)
fig.tight_layout(rect=(0, 0, 1, 0.955))
target = RUN / 'figures_layer_contact_sheet.png'
target.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(target, dpi=160)
plt.close(fig)
print('wrote', target)
