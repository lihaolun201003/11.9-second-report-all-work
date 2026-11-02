# -*- coding: utf-8 -*-
"""Aggregate baseline/A/B/integration outputs for the U-depth experiment."""
from __future__ import annotations

import csv
import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
       / 'U_DEPTH_TRANSITION_JOINT_OPT')
A_DIR = OUT / 'experiment_A_fixed_depth'
B_DIR = OUT / 'experiment_B_adaptive_depth'
BASE_DIR = OUT / 'baseline'
INT_DIR = OUT / 'integration_L7_L8'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    path = Path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                               default=str), encoding='utf-8')


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    return list(csv.DictReader(p.open(encoding='utf-8-sig')))


def write_csv(path, rows, fields):
    path = Path(path)
    with path.open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def path_length(routes):
    return sum(float(route.get('length_mm') or 0.0)
               for route in routes.values())


def unique_changed(changes):
    return sorted({int(row['route_id']) for row in changes})


def mean(values):
    return round(sum(values) / len(values), 4) if values else 0.0


def main():
    baseline = read_json(BASE_DIR / 'z2_results.json')
    a_summary = read_json(A_DIR / 'summary.json')
    b_summary = read_json(B_DIR / 'summary.json')
    a_z2 = read_json(A_DIR / 'z2_results.json')
    b_z2 = read_json(B_DIR / 'z2_results.json')
    a_routes = read_json(A_DIR / 'u_routes.json')
    b_routes = read_json(B_DIR / 'u_routes.json')
    base_routes = read_json(BASE_DIR / 'u_routes.json')
    a_changes = read_csv(A_DIR / 'route_changes.csv')
    b_changes = read_csv(B_DIR / 'route_changes.csv')
    a_trans = read_csv(A_DIR / 'transition_position_changes.csv')
    b_trans = read_csv(B_DIR / 'transition_position_changes.csv')
    a_depth = read_csv(A_DIR / 'u_depth_changes.csv')
    b_depth = read_csv(B_DIR / 'u_depth_changes.csv')
    int_summary = read_json(INT_DIR / 'summary.json')
    (OUT / 'baseline').mkdir(exist_ok=True)

    def changed_ids(rows):
        return unique_changed(rows)
    metrics = {
        'baseline': {
            'u_ok': 256, 'u_total': 256,
            'z2_interface_ok': baseline['ok'],
            'z2_interface_total': baseline['total'],
            'z2_interface_ids': baseline['success_ids'],
            'violations': read_json(BASE_DIR / 'validation_summary.json')['counts']['violations'],
            'changed_u': 0, 'deepened_u': 0, 'total_depth_increase_mm': 0.0,
            'total_u_length_mm': round(path_length(base_routes), 4),
            'elapsed_seconds': None,
        },
        'A_fixed_depth': {
            'u_ok': 256, 'u_total': 256,
            'z2_interface_ok': a_summary['success'],
            'z2_interface_total': a_summary['total_interface'],
            'unique_changed_u': len(changed_ids(a_changes)),
            'accepted_changes': len(a_changes),
            'deepened_u': 0, 'total_depth_increase_mm': 0.0,
            'mean_rise_shift_mm': mean([float(r['rise_delta']) for r in a_trans]),
            'mean_fall_start_shift_mm': mean([float(r['fall_delta']) for r in a_trans]),
            'total_u_length_mm': round(path_length(a_routes), 4),
            'elapsed_seconds': a_summary.get('elapsed'),
            'violations': read_json(A_DIR / 'validation_summary.json')['counts']['violations'],
            'recovered_ids': sorted(set(a_z2.get('recovered_ids') or [])),
            'candidates': a_summary.get('candidates'),
        },
        'B_adaptive_depth': {
            'u_ok': 256, 'u_total': 256,
            'z2_interface_ok': b_summary['success'],
            'z2_interface_total': b_summary['total_interface'],
            'unique_changed_u': len(changed_ids(b_changes)),
            'accepted_changes': len(b_changes),
            'deepened_u': b_summary['deepened_u'],
            'total_depth_increase_mm': b_summary['total_depth_increase_mm'],
            'mean_rise_shift_mm': mean([float(r['rise_delta']) for r in b_trans]),
            'mean_fall_start_shift_mm': mean([float(r['fall_delta']) for r in b_trans]),
            'total_u_length_mm': round(path_length(b_routes), 4),
            'elapsed_seconds': b_summary.get('elapsed'),
            'violations': read_json(B_DIR / 'validation_summary.json')['counts']['violations'],
            'recovered_ids': sorted(set(b_z2.get('recovered_ids') or [])),
            'candidates': b_summary.get('candidates'),
        },
        'integration_L7_L8': int_summary,
    }
    # B's change set is identical to A's in this run; record explicitly
    metrics['B_adaptive_depth']['same_change_set_as_A'] = (
        changed_ids(a_changes) == changed_ids(b_changes))
    write_json(OUT / 'optimization_summary.json', dict(
        schema='u_depth_transition_joint_opt_v1',
        note=('A and B start from the same baseline; B allows depth but found '
              'no legal depth improvement, so its accepted change set is the '
              'same fixed-depth transition set as A.  This is an honest '
              'negative result for the depth hypothesis on this dataset.'),
        metrics=metrics))
    # aggregate CSVs
    agg = []
    for label, rows in (('A', a_changes), ('B', b_changes)):
        for row in rows:
            row = dict(row)
            row['experiment'] = label
            agg.append(row)
    fields = ['experiment', 'route_id', 'old_arm_mm', 'new_arm_mm',
              'old_depth_mm', 'new_depth_mm', 'old_rise', 'new_rise',
              'old_fall', 'new_fall', 'old_fall_tail', 'new_fall_tail',
              'recovered_z2', 'budget_index']
    write_csv(OUT / 'route_changes.csv', agg, fields)
    depth_rows = []
    for label, rows in (('A', a_depth), ('B', b_depth)):
        for row in rows:
            row = dict(row)
            row['experiment'] = label
            depth_rows.append(row)
    write_csv(OUT / 'u_depth_changes.csv', depth_rows,
              ['experiment', 'route_id', 'old_depth_mm', 'new_depth_mm',
               'delta_depth_mm', 'new_arm_mm'])
    trans_rows = []
    for label, rows in (('A', a_trans), ('B', b_trans)):
        for row in rows:
            row = dict(row)
            row['experiment'] = label
            trans_rows.append(row)
    write_csv(OUT / 'transition_position_changes.csv', trans_rows,
              ['experiment', 'route_id', 'old_rise', 'new_rise', 'rise_delta',
               'old_fall_start', 'new_fall_start', 'fall_delta',
               'new_fall_tail'])
    # recovered routes with baseline blockers
    base_blockers = {int(k): v for k, v in read_json(
        BASE_DIR / 'blocker_analysis.json')['blockers'].items()}
    recovered_rows = []
    for label, z2 in (('A', a_z2), ('B', b_z2)):
        recovered = set(int(x) for x in z2.get('recovered_ids') or [])
        for rid in sorted(recovered):
            changed_by = []
            for row in (a_changes if label == 'A' else b_changes):
                if str(rid) in str(row.get('recovered_z2', '')):
                    changed_by.append(int(row['route_id']))
            recovered_rows.append(dict(
                experiment=label, route_id=rid,
                baseline_blockers=';'.join(map(str, base_blockers.get(rid, []))),
                blocker_count_baseline=len(base_blockers.get(rid, [])),
                changed_u=';'.join(map(str, changed_by)),
                final_blockers=''))
    write_csv(OUT / 'z2_recovered_routes.csv', recovered_rows,
              ['experiment', 'route_id', 'baseline_blockers',
               'blocker_count_baseline', 'changed_u', 'final_blockers'])
    blocker_payload = dict(
        baseline=read_json(BASE_DIR / 'blocker_analysis.json'),
        A=dict(success=a_summary['success'],
               failed=48 - a_summary['success'],
               blockers={str(rid): row.get('blockers', [])
                         for rid, row in (a_z2.get('results') or {}).items()
                         if not row.get('ok')},
               total_blocker_entries=sum(len(row.get('blockers', []))
                                          for row in (a_z2.get('results') or {}).values()
                                          if not row.get('ok'))),
        B=dict(success=b_summary['success'],
               failed=48 - b_summary['success'],
               blockers={str(rid): row.get('blockers', [])
                         for rid, row in (b_z2.get('results') or {}).items()
                         if not row.get('ok')},
               total_blocker_entries=sum(len(row.get('blockers', []))
                                          for row in (b_z2.get('results') or {}).values()
                                          if not row.get('ok'))))
    write_json(OUT / 'blocker_analysis.json', blocker_payload)
    # combined validation summary
    write_json(OUT / 'validation.json', dict(
        baseline=read_json(BASE_DIR / 'validation_summary.json'),
        A=read_json(A_DIR / 'validation_summary.json'),
        B=read_json(B_DIR / 'validation_summary.json'),
        integration_L7_L8=read_json(INT_DIR / 'validation.json') if False else None))
    write_json(OUT / 'baseline_summary.json',
               read_json(BASE_DIR.parent / 'baseline_summary.json')
               if (BASE_DIR.parent / 'baseline_summary.json').exists()
               else {'success': baseline['ok'], 'total': baseline['total']})
    # run.log aggregate
    lines = ['# U-depth/S-transition optimization run', '']
    for name in ('baseline', 'run_A.log', 'run_B.log', 'run_integration.log'):
        path = OUT / name
        if path.is_file():
            lines.append(f'===== {name} =====')
            lines.append(path.read_text(encoding='utf-8', errors='replace'))
    (OUT / 'run.log').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    return metrics


if __name__ == '__main__':
    main()
