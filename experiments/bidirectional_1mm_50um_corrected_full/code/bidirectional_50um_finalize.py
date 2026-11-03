# -*- coding: utf-8 -*-
"""Assemble corrected 50 um top-level deliverables."""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from . import bidirectional_50um_assignment as A50
from . import glass_1mm_process_rules as RULES

OUT = Path(A50.OUT)
B = OUT / 'experiment_B'
C = OUT / 'experiment_C'
OLD_A = OUT / 'old_A_revalidation'
OLD_B = OUT / 'old_B_revalidation'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def write(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1,
                                 default=str), encoding='utf-8')


def main():
    routes_payload = read(C / 'routes_l3d.json')
    routes = {int(r['route_id']): r for r in routes_payload['routes']
              if r.get('status') == 'routed'}
    actual = {}
    for rid, route in routes.items():
        layer = None; z = 0.5
        for part in route.get('parts') or []:
            if part['kind'] == 'flat' and int(part['layer_id']) != 1:
                layer = int(part['layer_id']); z = float(part['z_mm']); break
        actual[rid] = (layer, z)
    rows = list(csv.DictReader(open(A50.OUT / 'assignment_1024.csv',
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
                             'Z2_MIDDLE' if z < RULES.Z2_MM else 'Z2_UP')
            row['direction'] = 'down' if z < 0 else 'up'
    with (OUT / 'assignment_1024.csv').open('w', newline='',
                                             encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    # final routes / validation / stats
    for name in ('routes_l3d.json', 'failed_routes.json', 'validation.json',
                 'crossings_after.json', 'final_stats.json',
                 'per_layer_stats.json'):
        src = C / name
        if src.exists():
            shutil.copy2(src, OUT / name)
    shutil.copy2(C / 'recover_summary.json', OUT / 'reroute_summary.json')
    shutil.copytree(C / 'checkpoints', OUT / 'checkpoints', dirs_exist_ok=True)
    # experiment A = old revalidation evidence
    shutil.copytree(OLD_A, OUT / 'experiment_A', dirs_exist_ok=True)
    # experiment B and C already there
    # old revalidation files
    oldA = read(OLD_A / 'final_stats.json')
    oldB = read(OLD_B / 'final_stats.json')
    newA = read(OLD_A / 'validation.json')
    newB = read(OLD_B / 'validation.json')
    old_counts = {}
    for label, path in (('A', OUT.parent / 'BIDIRECTIONAL_1MM_TARGET_FIRST_1024/experiment_A/validation.json'),
                        ('B', OUT.parent / 'BIDIRECTIONAL_1MM_TARGET_FIRST_1024/experiment_B/validation.json')):
        old_counts[label] = read(path)['counts']['violations']
    write(OUT / 'old_A_revalidation.json', dict(
        old_80um_violations=old_counts['A'],
        new_50um_violations=newA['counts']['violations'],
        eliminated=old_counts['A'] - newA['counts']['violations'],
        remaining_kinds=dict(Counter(v['kind'] for v in newA['violations'])),
        layer_stack_errors=(newA.get('layer_stack') or {}).get('errors'),
        routed=oldA['routed'], z1=oldA['z1_routed'], z2=oldA['z2_routed'],
        min_3d_clearance=newA.get('stats', {}).get('min_3d_clearance_mm')))
    write(OUT / 'old_B_revalidation.json', dict(
        old_80um_violations=old_counts['B'],
        new_50um_violations=newB['counts']['violations'],
        eliminated=old_counts['B'] - newB['counts']['violations'],
        remaining_kinds=dict(Counter(v['kind'] for v in newB['violations'])),
        layer_stack_errors=(newB.get('layer_stack') or {}).get('errors'),
        routed=oldB['routed'], z1=oldB['z1_routed'], z2=oldB['z2_routed'],
        min_3d_clearance=newB.get('stats', {}).get('min_3d_clearance_mm')))
    # B -> C audit
    b_routes = {int(k): v for k, v in read(B / 'checkpoints/routes.json').items()}
    recovered = [rid for rid in routes if rid not in b_routes]
    lost = [rid for rid in b_routes if rid not in routes]
    with (OUT / 'route_change_audit.csv').open('w', newline='',
                                               encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['route_id', 'plane', 'old_status', 'new_status', 'change'])
        for rid in sorted(set(b_routes) | set(routes)):
            plane = (read(B / 'checkpoints/routes.json').get(str(rid)) or
                     routes.get(rid) or {}).get('plane')
            w.writerow([rid, plane,
                        'routed' if rid in b_routes else 'failed',
                        'routed' if rid in routes else 'failed',
                        'recovered' if rid in recovered else
                        'lost' if rid in lost else 'unchanged'])
    write(OUT / 'final_route_changes.json', dict(
        recovered=len(recovered), lost=len(lost),
        recovered_ids=recovered, lost_ids=lost))
    # per-layer final from actual
    heights = sorted(A50.PHYSICAL_LAYERS.values())
    cross = read(OUT / 'crossings_after.json')
    by_h = {float(k): v for k, v in cross.get('pair_count_by_height', {}).items()}
    layers = defaultdict(lambda: [0, 0])
    for rid, row in assign.items():
        key = row['physical_layer'] or 'interface'
        layers[key][0] += 1
        layers[key][1] += rid in routes
    per = {}
    for key, (assigned, routed) in layers.items():
        z = 0.5 if key == 'interface' else float(A50.PHYSICAL_LAYERS[int(key)])
        per[str(key)] = dict(assigned=assigned, routed=routed,
                             failed=assigned - routed,
                             z_mm=z, crossings=by_h.get(round(z, 9), 0))
    write(OUT / 'per_layer_stats.json', per)
    # run log
    parts = ['# BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL run log', '']
    for name in ('experiment_B/run.log', 'experiment_B/validate.log',
                 'experiment_C/run.log', 'experiment_C/validate.log',
                 'old_A_revalidation.log', 'old_B_revalidation.log', 'tests.log'):
        p = OUT / name
        if p.exists():
            parts += [f'===== {name} =====',
                      p.read_text(encoding='utf-8', errors='replace')]
    (OUT / 'run.log').write_text('\n'.join(parts), encoding='utf-8')
    # process rules copy
    write(OUT / 'process_rules.json', RULES.rules_payload())
    print('final C', len(routes), 'recovered', len(recovered), 'lost', len(lost))
    print('regions', Counter(assign[rid]['region'] for rid in routes))
    print('interface', sum(1 for rid in routes if assign[rid]['region'] == 'Z2_INTERFACE'))


if __name__ == '__main__':
    main()
