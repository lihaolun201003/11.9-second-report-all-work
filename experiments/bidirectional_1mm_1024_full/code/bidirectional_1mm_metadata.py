# -*- coding: utf-8 -*-
"""Final metadata: logical-to-physical layer table and combined run log."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

OUT = (Path(__file__).resolve().parents[2] / 'outputs/manual_c4_new_connectivity'
       / 'BIDIRECTIONAL_1MM_1024_FULL')


def main():
    rows = list(csv.DictReader(open(OUT / 'assignment_1024.csv',
                                    encoding='utf-8-sig')))
    routed = {int(r['route_id']) for r in
              json.loads((OUT / 'routes_l3d.json').read_text(encoding='utf-8'))['routes']
              if r.get('status') == 'routed'}
    stats = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        key = (row['plane'], row['logical_layer'], row['physical_layer'],
               row['target_z_mm'], row['region'], row['direction'])
        stats[key][0] += 1
        stats[key][1] += 1 if int(row['route_id']) in routed else 0
        stats[key][2] += 0 if int(row['route_id']) in routed else 1
    with (OUT / 'logical_to_physical_layers.csv').open(
            'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['plane', 'logical_layer', 'physical_layer', 'z_mm',
                         'region', 'direction', 'assigned', 'routed', 'failed'])
        for key, value in sorted(stats.items(), key=lambda kv: (
                kv[0][0], kv[0][1], kv[0][2])):
            writer.writerow([key[0], key[1], key[2], key[3], key[4], key[5],
                             value[0], value[1], value[2]])
    # combined run log
    lines = ['# BIDIRECTIONAL_1MM_1024_FULL run log', '']
    for name in ('run_order5.log', 'run_repair.log', 'run_finalize2.log',
                 'run_plots.log'):
        path = OUT / name
        if path.exists():
            lines.append(f'===== {name} =====')
            lines.append(path.read_text(encoding='utf-8', errors='replace'))
    (OUT / 'run.log').write_text('\n'.join(lines), encoding='utf-8')
    print('logical_to_physical_layers.csv and run.log written')
    print('routed', len(routed), 'assignment', len(rows))


if __name__ == '__main__':
    main()
