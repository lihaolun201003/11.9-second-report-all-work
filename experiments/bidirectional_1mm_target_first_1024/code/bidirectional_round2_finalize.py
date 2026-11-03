# -*- coding: utf-8 -*-
"""Assemble top-level round-2 deliverables from experiment C (best legal)."""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from .bidirectional_1mm_layer_assignment import OUT as BASE
from .bidirectional_round2_assignment import OUT as OUT2

FINAL = OUT2
C = OUT2 / 'experiment_C'
A = OUT2 / 'experiment_A'
BB = OUT2 / 'experiment_B'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def write(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1,
                                 default=str), encoding='utf-8')


def main():
    routes_payload = read(C / 'routes_l3d.json')
    routes = {int(r['route_id']): r for r in routes_payload['routes']
              if r.get('status') == 'routed'}
    # actual physical layer from route flat parts
    actual = {}
    for rid, route in routes.items():
        layer = None
        for part in route.get('parts') or []:
            if part['kind'] == 'flat' and int(part['layer_id']) != 1:
                layer = int(part['layer_id']); z = float(part['z_mm']); break
        actual[rid] = (layer, z if layer is not None else 0.5)
    # assignment from base (4-Z2 legal stack) then update actual
    rows = list(csv.DictReader(open(BASE / 'assignment_1024.csv',
                                    encoding='utf-8-sig')))
    assign = {int(r['route_id']): r for r in rows}
    for rid, (layer, z) in actual.items():
        row = assign[rid]
        row['physical_layer'] = '' if layer is None else str(layer)
        row['target_z_mm'] = str(z)
        if layer is None:
            row['region'] = 'Z2_INTERFACE'; row['direction'] = 'flat'
        else:
            row['region'] = ('Z1_DOWN' if z < 0 else
                             'Z1_MIDDLE' if layer <= 7 else
                             'Z2_MIDDLE' if layer == 8 else 'Z2_UP')
            row['direction'] = 'down' if z < 0 else 'up'
    with (OUT2 / 'assignment_1024.csv').open('w', newline='',
                                             encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    # logical mapping final
    with (OUT2 / 'logical_to_physical_layers.csv').open(
            'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['plane', 'logical_layer/kind', 'physical_layer',
                         'z_mm', 'region', 'assigned', 'routed'])
        counts = defaultdict(lambda: [0, 0])
        for row in rows:
            key = (row['plane'], row['logical_layer'] if row['logical_layer'] else
                   row['logical_kind'], row['physical_layer'], row['target_z_mm'],
                   row['region'])
            counts[key][0] += 1
            counts[key][1] += int(row['route_id']) in routes
        for key, value in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            writer.writerow([key[0], key[1], key[2], key[3], key[4],
                             value[0], value[1]])
    # copy final routes/failed/validation/crossings/stats
    for name in ('routes_l3d.json', 'failed_routes.json', 'validation.json',
                 'crossings_after.json', 'final_stats.json'):
        shutil.copy2(C / name, OUT2 / name)
    shutil.copy2(C / 'recover_summary.json', OUT2 / 'reroute_summary.json')
    # checkpoints
    shutil.copytree(C / 'checkpoints', OUT2 / 'checkpoints', dirs_exist_ok=True)
    # copy physical model: final legal 4-Z2 stack from base
    for name in ('glass_geometry.json', 'physical_layer_stack.json'):
        shutil.copy2(BASE / name, OUT2 / name)
    # route change audit: first legal run 735 -> C 801
    old_routes = {int(k): v for k, v in read(
        BASE / 'checkpoints/routes.json').items()}
    recovered = [rid for rid in routes if rid not in old_routes]
    lost = [rid for rid in old_routes if rid not in routes]
    layer_changes = []
    for rid in sorted(set(old_routes) & set(routes)):
        old_layer = None
        for part in old_routes[rid].get('parts') or []:
            if part['kind'] == 'flat' and int(part['layer_id']) != 1:
                old_layer = int(part['layer_id']); break
        new_layer = actual[rid][0]
        if old_layer != new_layer:
            layer_changes.append(dict(route_id=rid, old_layer=old_layer,
                                      new_layer=new_layer))
    with (OUT2 / 'route_change_audit.csv').open('w', newline='',
                                                encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['route_id', 'plane', 'old_status', 'new_status',
                    'old_layer', 'new_layer', 'change'])
        for rid in sorted(set(old_routes) | set(routes)):
            old_layer = None
            if rid in old_routes:
                for part in old_routes[rid].get('parts') or []:
                    if part['kind'] == 'flat' and int(part['layer_id']) != 1:
                        old_layer = int(part['layer_id']); break
            new_layer = actual.get(rid, (None, None))[0]
            w.writerow([rid, (old_routes.get(rid) or routes.get(rid) or {}).get('plane'),
                        'routed' if rid in old_routes else 'failed',
                        'routed' if rid in routes else 'failed',
                        old_layer, new_layer,
                        'recovered' if rid in recovered else
                        'lost' if rid in lost else
                        'layer_changed' if old_layer != new_layer else 'unchanged'])
    write(OUT2 / 'final_route_changes.json', dict(
        recovered=len(recovered), lost=len(lost),
        recovered_ids=recovered, lost_ids=lost,
        layer_changed=layer_changes))
    # run log
    parts = ['# BIDIRECTIONAL_1MM_TARGET_FIRST_1024 run log', '']
    for name in ('experiment_A/run.log', 'experiment_B/run.log',
                 'experiment_C/run.log', 'experiment_C/validate.log'):
        p = OUT2 / name
        if p.exists():
            parts += [f'===== {name} =====', p.read_text(encoding='utf-8',
                                                         errors='replace')]
    (OUT2 / 'run.log').write_text('\n'.join(parts), encoding='utf-8')
    print('final C routes', len(routes), 'recovered', len(recovered),
          'lost', len(lost), 'layer changes', len(layer_changes))


if __name__ == '__main__':
    main()
