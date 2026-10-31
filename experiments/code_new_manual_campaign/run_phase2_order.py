# -*- coding: utf-8 -*-
"""Run phase-2 strict-C4 2D routing with a configurable group order / budget."""
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    order = argv[0] if argv else 'same_first'
    budget = int(argv[1]) if len(argv) > 1 else 2000
    rr_rounds = int(argv[2]) if len(argv) > 2 else 2
    retry_passes = int(argv[3]) if len(argv) > 3 else 3
    time_limit = float(argv[4]) if len(argv) > 4 else 1200.0
    planes = (argv[5].split(',') if len(argv) > 5 else ['z1', 'z2'])
    target = CAMPAIGN / f'phase2_2d_order_{order}'
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None
    target.mkdir(parents=True, exist_ok=True)
    results = {}
    for plane in planes:
        t0 = time.perf_counter()
        try:
            result = run2d.run_plane(
                plane, order_mode=order, budget=budget,
                out_dir=target / plane, rr_rounds=rr_rounds, rr_budget=0,
                retry_passes=retry_passes, time_limit=time_limit,
                checkpoint_every=16)
            results[plane] = result
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            results[plane] = dict(error=repr(exc))
        print(f'[order={order}] plane {plane} done in '
              f'{time.perf_counter() - t0:.1f}s -> {results[plane]}', flush=True)
    summary = dict(order=order, budget=budget, rr_rounds=rr_rounds,
                   retry_passes=retry_passes, planes=planes,
                   results=results, campaign=str(CAMPAIGN))
    (target / 'order_run_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
