# -*- coding: utf-8 -*-
"""3D layer sweep for the revised-Z2 1024 layout (same frozen lift engine)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile
apply_profile()

from four_side_1024.l3d import layers as LL  # noqa: E402
from four_side_1024.l3d import validate_l3d, validate_l3d_multi  # noqa: E402
from four_side_1024.v3c4 import lift_cross as LIFT  # noqa: E402
from four_side_1024.v3c4 import lift_cross_run  # noqa: E402

CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
SELECTED = CAMPAIGN / 'phase2_2d_repaired'
LAYER_COUNTS = [int(value) for value in (sys.argv[1].split(',')
                                         if len(sys.argv) > 1
                                         else ['5', '7', '11', '15'])]
TIME_LIMIT = float(sys.argv[2]) if len(sys.argv) > 2 else 480.0
PALETTE = {2: '#2f9e44', 3: '#7048e8', 4: '#e03131', 5: '#0c8599',
           6: '#f08c00', 7: '#c2255c', 8: '#1f6fd6', 9: '#0ca678',
           10: '#845ef7', 11: '#e8590c', 12: '#1098ad', 13: '#d6336c',
           14: '#5c940d', 15: '#5f3dc4'}


def heights_for(count):
    return [round(0.65 + 0.15 * index, 3) for index in range(count - 1)]


def patch_layers(count):
    ids = tuple(range(2, count + 1))
    LIFT.LAYER_IDS = ids
    LL.ROUTING_LAYER_IDS = ids
    validate_l3d.ROUTING_LAYER_IDS = ids
    validate_l3d_multi.ROUTING_LAYER_IDS = ids
    lift_cross_run.LAYER_PALETTE.update(PALETTE)


def main():
    rows = []
    for count in LAYER_COUNTS:
        patch_layers(count)
        out_dir = CAMPAIGN / '02_layer_sweep' / f'L{count}' / 'lift'
        started = time.perf_counter()
        print(f'[z2rev-sweep] L{count} heights={heights_for(count)} '
              f'LAYER_IDS={LIFT.LAYER_IDS}', flush=True)
        lift_cross_run.run(out_dir=out_dir, v4_root=SELECTED,
                           max_groups=300, time_limit=TIME_LIMIT,
                           plots=False, heights=heights_for(count))
        validation = json.loads((out_dir / 'validation.json').read_text(
            encoding='utf-8'))
        crossings = json.loads((out_dir / 'crossings_after.json').read_text(
            encoding='utf-8'))
        summary = json.loads((out_dir / 'summary.json').read_text(
            encoding='utf-8'))
        counts = dict(validation.get('counts') or {})
        row = dict(layer_count=count, seconds=round(time.perf_counter()
                                                    - started, 1),
                   routed=summary.get('routed_after'),
                   violations=counts.get('violations'),
                   unique_crossing_pairs=crossings.get('unique_pair_count'),
                   crossing_points=crossings.get('count'),
                   lifted_groups=summary.get('lifted_groups'),
                   transitions=summary.get('transitions'),
                   pairs_by_height=crossings.get('pair_count_by_height'))
        rows.append(row)
        print(f'[z2rev-sweep] L{count}: {row}', flush=True)
        (CAMPAIGN / '02_layer_sweep' / 'sweep_summary.json').write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
