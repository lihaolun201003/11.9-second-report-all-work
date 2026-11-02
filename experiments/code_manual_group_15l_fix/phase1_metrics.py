# -*- coding: utf-8 -*-
"""Post-process phase-1: per-layer manual-vs-manual clearance, nesting proof,
transition positions and failure catalogue (no re-run needed)."""
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
from four_side_1024.manual_c4_adapt import manual_u_geometry as G

OUT = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_COMPARISON_FIXED'
phase1 = json.loads((OUT / 'manual_phase1.json').read_text(encoding='utf-8'))


def pair_distance(array_a, array_b, chunk=256):
    best = math.inf
    for start in range(0, len(array_a), chunk):
        block = array_a[start:start + chunk]
        deltas = block[:, None, :] - array_b[None, :, :]
        best = min(best, float(np.min(np.hypot(deltas[..., 0],
                                               deltas[..., 1]))))
    return best


metrics = dict(layers={})
for layer in ('1', '2', '3', '4'):
    rows = phase1['layer_orders'][layer]
    placed = [row for row in rows if not row.get('failed')]
    failed = [row for row in rows if row.get('failed')]
    entry = dict(expected=len(rows), placed=len(placed), failed=len(failed),
                 sides=dict(Counter(row['side'] for row in placed)))
    if placed:
        depths = sorted(row['depth_mm'] for row in placed)
        entry['depth_min_mm'] = round(depths[0], 3)
        entry['depth_max_mm'] = round(depths[-1], 3)
        entry['strict_nesting'] = sum(
            1 for row in placed
            if abs(row['arm_mm'] - row['strict_arm_mm']) <= 1e-6)
        entry['transitions'] = sum(1 for row in placed
                                   if row.get('n_transitions') == 2)
        entry['transition_positions'] = [
            dict(route_id=row['route_id'],
                 rise_start_mm=round(row['transition']['rise_start'], 3),
                 fall_start_mm=round(row['transition']['fall_start'], 3))
            for row in placed if row.get('transition')]
        # manual <-> manual clearance: sample both chains, separate legal crossings
        samples = {row['route_id']: G._sample_xy(row['primitives'],
                                                 sagitta=0.0005)
                   for row in placed}
        clearance = math.inf
        clearance_pair = None
        crossing_pairs = 0
        for index, first in enumerate(placed):
            array_a = samples[first['route_id']]
            for second in placed[index + 1:]:
                distance = pair_distance(array_a, samples[second['route_id']])
                if distance < 0.02:
                    crossing_pairs += 1
                    continue
                if distance < clearance:
                    clearance = distance
                    clearance_pair = (first['route_id'], second['route_id'])
        entry['manual_min_clearance_mm'] = (
            None if clearance == math.inf else round(clearance, 6))
        entry['manual_min_clearance_pair'] = clearance_pair
        entry['manual_crossing_pairs'] = crossing_pairs
    failures = [dict(route_id=row['route_id'], side=row['side'],
                     reason=row['reason']) for row in failed]
    entry['failure_reasons'] = dict(Counter(row['reason'] for row in failed))
    entry['failures'] = failures
    metrics['layers'][layer] = entry

metrics['schema'] = 'manual_u_phase1_metrics_v1'
metrics['manual_total'] = dict(expected=256,
                               placed=phase1['placed'],
                               failed=phase1['failed'],
                               complete=phase1['complete'])
metrics['runtime_seconds'] = phase1['elapsed_seconds']
(OUT / 'phase1_metrics.json').write_text(
    json.dumps(metrics, ensure_ascii=False, indent=1, default=str),
    encoding='utf-8')

print(json.dumps(metrics, ensure_ascii=False, indent=1, default=str)[:6000])
