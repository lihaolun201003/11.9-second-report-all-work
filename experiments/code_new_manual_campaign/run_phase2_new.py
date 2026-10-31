# -*- coding: utf-8 -*-
"""Run phase-2 strict-C4 2D routing on the new manual section-2 connectivity."""
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
PHASE2 = CAMPAIGN / 'phase2_2d'


def main():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None
    topology = CONN.combined_topology()
    print('[phase2] topology connections=', topology['connections'],
          'groups=', topology['group_count'],
          'relations=', topology['relation_counts'], flush=True)
    PHASE2.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    plane_results = {}
    errors = {}
    for plane in ('z1', 'z2'):
        t0 = time.perf_counter()
        try:
            result = run2d.run_plane(
                plane, order_mode='easy', budget=1600,
                out_dir=PHASE2 / plane, rr_rounds=2, rr_budget=0,
                retry_passes=3, time_limit=1800.0, checkpoint_every=16)
            plane_results[plane] = result
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            errors[plane] = repr(exc)
        print(f'[phase2] plane {plane} done in '
              f'{time.perf_counter() - t0:.1f}s', flush=True)
    combine_result = None
    combine_error = None
    try:
        combine_result = run2d.combine(phase2_dir=PHASE2)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        combine_error = repr(exc)
    summary = dict(
        schema='new_manual_csv_phase2_run_v1',
        campaign=str(CAMPAIGN), topology=topology['relation_counts'],
        groups=topology['group_count'],
        plane_results=plane_results, errors=errors,
        combine=combine_result, combine_error=combine_error,
        seconds=round(time.perf_counter() - started, 1))
    (PHASE2 / 'new_campaign_phase2_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items()
                      if k in ('plane_results', 'errors', 'combine_error',
                               'seconds')}, ensure_ascii=False, indent=1))
    return summary


if __name__ == '__main__':
    main()
