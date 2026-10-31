# -*- coding: utf-8 -*-
"""Layer sweep 5L/7L/9L/11L/13L/15L on the new-manual-CSV 2D layout.

Same 2D layout for every layer count (fair initialisation); the frozen crossing
lift engine (v3c4/lift_cross) regenerates real XYZ routes for each stack:
L2 = 0.65 mm, +0.15 mm per layer, so L5=1.10, L7=1.40, L9=1.70, L11=2.00,
L13=2.30, L15=2.60 mm.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4 import lift_cross_run  # noqa: E402
from four_side_1024.v3c4 import lift_cross as LIFT  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
LAYER_COUNTS = [5, 7, 9, 11, 13, 15]


def heights_for(count):
    return [round(0.65 + 0.15 * index, 3) for index in range(count - 1)]


def metrics_for(out_dir, count):
    out_dir = Path(out_dir)
    summary = json.loads((out_dir / 'summary.json').read_text(encoding='utf-8'))
    validation = json.loads((out_dir / 'validation.json').read_text(encoding='utf-8'))
    after = json.loads((out_dir / 'crossings_after.json').read_text(encoding='utf-8'))
    payload = json.loads((out_dir / 'routes_l3d.json').read_text(encoding='utf-8'))
    records = payload.get('routes') or []
    routed = [r for r in records if r.get('status') == 'routed']
    layer_counts = {}
    for record in routed:
        used = set()
        for part in record.get('parts') or []:
            if part.get('kind') == 'flat':
                layer_id = int(part.get('layer_id') or 1)
                if layer_id > 1:
                    used.add(layer_id)
        if not used:
            layer_counts[1] = layer_counts.get(1, 0) + 1
        for layer_id in used:
            layer_counts[layer_id] = layer_counts.get(layer_id, 0) + 1
    transitions = sum(int(r.get('n_transitions') or 0) for r in routed)
    total_length = sum(float(r.get('length_mm') or 0) for r in routed)
    xy_length = sum(float(r.get('xy_length_mm') or r.get('length_mm') or 0)
                    for r in routed)
    return dict(
        layer_count=count, layer_heights_mm=heights_for(count),
        routed=len(routed), failed=len(records) - len(routed),
        violations=(validation.get('counts') or {}).get('violations'),
        validation_status=validation.get('status'),
        exploratory_pass=validation.get('exploratory_pass'),
        unique_pairs=after.get('unique_pair_count'),
        crossing_points=after.get('count'),
        pairs_by_height=after.get('pair_count_by_height'),
        new_high_pairs=len(after.get('new_high_layer_pairs') or []),
        remaining_pairs=len(after.get('remaining_pairs') or []),
        transitions=transitions,
        total_length_mm=round(total_length, 3),
        fabrication_hours=round(total_length / 3600.0, 4),
        layer_route_counts={str(k): v for k, v in sorted(layer_counts.items())},
        summary=summary)


def main():
    selected = CAMPAIGN / 'phase2_2d_selected'
    if not (selected / 'routes_1024.json').exists():
        raise SystemExit('phase2_2d_selected/routes_1024.json missing (run selection first)')
    results = []
    for count in LAYER_COUNTS:
        out_dir = CAMPAIGN / '02_layer_sweep' / f'L{count}' / 'lift'
        started = time.perf_counter()
        LIFT.LAYER_IDS = tuple(range(2, int(count) + 1))
        print(f'[sweep] L{count} heights={heights_for(count)} '
              f'LAYER_IDS={LIFT.LAYER_IDS}', flush=True)
        try:
            lift_cross_run.run(
                out_dir=out_dir, v4_root=selected, max_groups=300,
                time_limit=1200.0, plots=True, heights=heights_for(count))
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            results.append(dict(layer_count=count, error=repr(exc)))
            continue
        row = metrics_for(out_dir, count)
        row['seconds'] = round(time.perf_counter() - started, 1)
        results.append(row)
        print(f'[sweep] L{count}: routed={row["routed"]} '
              f'violations={row["violations"]} unique_pairs={row["unique_pairs"]} '
              f'layer_counts={row["layer_route_counts"]} '
              f'({row["seconds"]}s)', flush=True)
        (CAMPAIGN / '02_layer_sweep' / 'sweep_summary.json').write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps([{k: row.get(k) for k in
                       ('layer_count', 'routed', 'failed', 'violations',
                        'unique_pairs', 'new_high_pairs', 'transitions',
                        'fabrication_hours', 'seconds')}
                      for row in results], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
