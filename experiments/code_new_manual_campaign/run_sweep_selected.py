# -*- coding: utf-8 -*-
"""Run selected layer counts of the sweep (per-config time limit, fresh process)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4 import lift_cross as LIFT  # noqa: E402
from four_side_1024.l3d import layers as LL  # noqa: E402
from four_side_1024.l3d import validate_l3d as VALIDATOR  # noqa: E402
from four_side_1024.l3d import validate_l3d_multi as VALIDATOR_MULTI  # noqa: E402
from four_side_1024.v3c4 import lift_cross_run  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
SELECTED = CAMPAIGN / 'phase2_2d_selected'


def heights_for(count):
    return [round(0.65 + 0.15 * index, 3) for index in range(count - 1)]


def main():
    counts = [int(item) for item in (sys.argv[1].split(',')
                                     if len(sys.argv) > 1 else ['7'])]
    time_limit = float(sys.argv[2]) if len(sys.argv) > 2 else 420.0
    rows = []
    for count in counts:
        LIFT.LAYER_IDS = tuple(range(2, count + 1))
        LL.ROUTING_LAYER_IDS = tuple(range(2, count + 1))
        VALIDATOR.ROUTING_LAYER_IDS = tuple(range(2, count + 1))
        VALIDATOR_MULTI.ROUTING_LAYER_IDS = tuple(range(2, count + 1))
        lift_cross_run.LAYER_PALETTE.update({
            6: '#f08c00', 7: '#c2255c', 8: '#1f6fd6', 9: '#0ca678',
            10: '#845ef7', 11: '#e8590c', 12: '#1098ad', 13: '#d6336c',
            14: '#5c940d', 15: '#5f3dc4'})
        out_dir = CAMPAIGN / '02_layer_sweep' / f'L{count}' / 'lift'
        started = time.perf_counter()
        print(f'[sweep2] L{count} heights={heights_for(count)} '
              f'LAYER_IDS={LIFT.LAYER_IDS} time_limit={time_limit}',
              flush=True)
        try:
            lift_cross_run.run(out_dir=out_dir, v4_root=SELECTED,
                               max_groups=300, time_limit=time_limit,
                               plots=False, heights=heights_for(count))
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            rows.append(dict(layer_count=count, error=repr(exc)))
            continue
        seconds = round(time.perf_counter() - started, 1)
        validation = json.loads((out_dir / 'validation.json').read_text(
            encoding='utf-8'))
        crossings = json.loads((out_dir / 'crossings_after.json').read_text(
            encoding='utf-8'))
        counts_map = dict(validation.get('counts') or {})
        row = dict(layer_count=count, seconds=seconds,
                   violations=counts_map.get('violations'),
                   exploratory_pass=validation.get('exploratory_pass'),
                   unique_pairs=crossings.get('unique_pair_count'),
                   pairs_by_height=crossings.get('pair_count_by_height'),
                   new_high=len(crossings.get('new_high_layer_pairs') or []))
        rows.append(row)
        print(f'[sweep2] L{count}: {row}', flush=True)
        (CAMPAIGN / '02_layer_sweep' / 'sweep2_summary.json').write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
