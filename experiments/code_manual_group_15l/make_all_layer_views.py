# -*- coding: utf-8 -*-
"""Full 16-panel per-layer contact sheet (L1 row1, L1 row2, L2..L15) +
individual plots for the currently empty L2/L3 planes."""
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RUN_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_GROUP_15L_COMPARISON')
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN')
PER_LAYER = RUN_DIR / 'plots' / 'per_layer'
FIGURES = RUN_DIR / 'figures'
PER_LAYER.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    'campaign_layer_views', CAMPAIGN / 'make_layer_views.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

payload = json.loads((RUN_DIR / 'routes_l3d.json').read_text(encoding='utf-8'))
data = module.build_layer_data(payload)

Z_LAYERS = [(0.0, 'L1 (Z1 row)'), (0.5, 'L1 (Z2 row)')] + [
    (round(0.65 + 0.15 * index, 6), f'L{index + 2}') for index in range(14)]

# individual plots for the empty L2/L3 planes (no route flats there in this run)
for z, label in Z_LAYERS:
    if z in data['routes_by_layer']:
        continue
    fig, ax = plt.subplots(figsize=(7.0, 6.8))
    info = module.draw_layer(ax, z, data, dense_context=True, annotate=False)
    # draw_layer only titles when the layer has content; force the title anyway
    ax.set_title(f'{label}  z={z:.2f} mm | 0 routes (this run) '
                 f'| interface context shown in grey', fontsize=8.5)
    fig.tight_layout()
    target = PER_LAYER / f'layer_z{z:.2f}.png'
    fig.savefig(target, dpi=185)
    plt.close(fig)
    print('[per-layer] wrote empty', target, info)

# --- 16-panel contact sheet, 4 columns x 4 rows ---------------------------
fig, axes = plt.subplots(4, 4, figsize=(4.9 * 4, 4.35 * 4))
axes = np.atleast_2d(axes)
for index, (z, layer_label) in enumerate(Z_LAYERS):
    ax = axes.ravel()[index]
    info = module.draw_layer(ax, z, data, dense_context=True, annotate=False)
    routes = info['routes']
    ax.set_title(f'{layer_label}  z={z:.2f} mm\n{routes} routes | '
                 f'{info["transition_endpoints"]} transition endpoints',
                 fontsize=8.0)
    ax.tick_params(labelsize=5)
    ax.set_xlabel('x (mm)', fontsize=5.5)
    ax.set_ylabel('y (mm)', fontsize=5.5)
for index in range(len(Z_LAYERS), axes.size):
    axes.ravel()[index].axis('off')
fig.suptitle('Manual-grouping 15L run (L1-L4 manual + L5-L15 old algorithm): '
             'routing plot of every layer plane\n'
             'blue = opposite connection, orange = same-side U, '
             'green = adjacent connection; grey = interface context; '
             'red dots = elevation transition endpoints on this layer',
             fontsize=11)
fig.tight_layout(rect=(0, 0, 1, 0.955))
target = FIGURES / 'layer_contact_sheet_all.png'
fig.savefig(target, dpi=170)
plt.close(fig)
print('[per-layer] wrote', target)

summary = dict(schema='per_layer_views_manual_group_15L', layers=[])
for z, layer_label in Z_LAYERS:
    key = round(z, 6)
    summary['layers'].append(dict(
        layer_label=layer_label, z_mm=z,
        routes=len(data['routes_by_layer'].get(key) or set()),
        flat_primitives=len(data['flat'].get(key) or []),
        transition_endpoints=len(data['endpoint_markers'].get(key) or []),
        figure=str(PER_LAYER / f'layer_z{z:.2f}.png')))
summary['contact_sheet_all'] = str(target)
summary['contact_sheet_high'] = str(FIGURES / 'layer_contact_sheet_high.png')
summary['contact_sheet_interface'] = str(FIGURES / 'layer_contact_sheet_interface.png')
(RUN_DIR / 'per_layer_view_summary.json').write_text(
    json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=1))
