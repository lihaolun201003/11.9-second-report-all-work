# -*- coding: utf-8 -*-
"""Screen phase-2 group orders for the new manual campaign to maximise routing."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import run2d  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
SCREEN = CAMPAIGN / 'phase2_2d_screen'

CONFIGS = [
    ('z1', 'opposite_first', 2000, 1, 1, 900.0),
    ('z1', 'frame_easy', 2000, 1, 1, 900.0),
    ('z1', 'csv', 2000, 1, 1, 900.0),
    ('z2', 'same_first', 2000, 1, 1, 900.0),
    ('z2', 'adjacent_first', 2000, 1, 1, 900.0),
]


def main():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None
    CONN.combined_topology()
    SCREEN.mkdir(parents=True, exist_ok=True)
    rows = []
    for plane, order, budget, rr, retry, time_limit in CONFIGS:
        out = SCREEN / f'{plane}_{order}'
        started = time.perf_counter()
        try:
            result = run2d.run_plane(
                plane, order_mode=order, budget=budget, out_dir=out,
                rr_rounds=rr, rr_budget=0, retry_passes=retry,
                time_limit=time_limit, checkpoint_every=16)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            result = dict(error=repr(exc))
        result['order'] = order
        result['budget'] = budget
        result['seconds_wall'] = round(time.perf_counter() - started, 1)
        rows.append(dict(plane=plane, order=order, budget=budget,
                         routed=result.get('routed'),
                         failed_groups=result.get('failed_groups'),
                         validation_passed=result.get('validation_passed'),
                         seconds=result.get('seconds_wall')))
        print(f'[screen] plane={plane} order={order} routed={result.get("routed")} '
              f'failed_groups={result.get("failed_groups")} '
              f'({result["seconds_wall"]}s)', flush=True)
        (SCREEN / 'screen_summary.json').write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
