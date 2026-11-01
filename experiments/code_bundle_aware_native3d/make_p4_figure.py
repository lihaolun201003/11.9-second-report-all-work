# -*- coding: utf-8 -*-
"""P4: layer-count comparison figure (baseline vs bundle-aware)."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
FIGS = CAMPAIGN / 'figures'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def main():
    old = read(OLD / 'comparison.json', []) or []
    baseline = {int(row['layer_count']): row for row in old
                if 'layer_count' in row}
    lift = read(CAMPAIGN / '02_bundle_planning/lift_comparison.json', {}) or {}
    bundle = lift.get('bundle', {}) or {}
    bundle_rows = {int(key): value for key, value in bundle.items()}
    counts = [5, 7, 11, 15]
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.8))
    x = np.arange(len(counts))
    width = 0.38
    base_values = [baseline.get(count, {}).get('unique_crossing_pairs')
                   for count in counts]
    axes[0].bar(x - width / 2, base_values, width,
                label='per-route 2D+lift (A)', color='#adb5bd')
    bundle_values = [bundle_rows.get(count, {}).get('pairs')
                     for count in counts]
    axes[0].bar(x + width / 2,
                [value if value is not None else 0 for value in bundle_values],
                width, label='bundle-aware layer plan (C)', color='#1971c2')
    axes[0].set_xticks(x, [f'{count}L' for count in counts])
    axes[0].set_ylabel('global unique crossing pairs')
    axes[0].set_title('crossing pairs: per-route lift vs bundle-aware lift')
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2, axis='y')
    for index, value in enumerate(base_values):
        if value:
            axes[0].text(index - width / 2, value, str(value), ha='center',
                         va='bottom', fontsize=7)
    routed = [baseline.get(count, {}).get('routed') for count in counts]
    axes[1].bar(x - width / 2, routed, width,
                label='2D baseline routed (992/1024)', color='#adb5bd')
    axes[1].bar(x + width / 2,
                [bundle_rows.get(count, {}).get('routed')
                 if bundle_rows.get(count) else 0 for count in counts],
                width, label='bundle-aware lift routed', color='#2f9e44')
    axes[1].set_xticks(x, [f'{count}L' for count in counts])
    axes[1].set_ylabel('routed routes / 1024')
    axes[1].set_ylim(900, 1030)
    axes[1].set_title('routed count is identical (992/1024): layer count only '
                      'changes crossings')
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(FIGS / 'fig12_layer_comparison.png', dpi=175)
    plt.close(fig)
    print('figure written', FIGS / 'fig12_layer_comparison.png')


if __name__ == '__main__':
    main()
