# -*- coding: utf-8 -*-
"""Add the missing baseline/integration metadata files expected by the report."""
import csv, json
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
OUT = ROOT / 'outputs/manual_c4_new_connectivity/U_DEPTH_TRANSITION_JOINT_OPT'
BASE = OUT / 'baseline'
INT = OUT / 'integration_L7_L8'
from four_side_1024.manual_c4_adapt import u_depth_transition_optimizer as OPT


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def write_json(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str),
                       encoding='utf-8')


def empty_csv(path, fields):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()


def main():
    OPT.setup_environment()
    params = OPT.load_manual_u_params()
    base_z2 = read_json(BASE / 'z2_results.json')
    base_val = read_json(BASE / 'validation_summary.json')
    base_params = {}
    for rid, param in params.items():
        base_params[str(rid)] = dict(
            route_id=rid, layer=param.layer, side=param.side,
            group=param.group, original_arm_mm=param.arm_mm,
            current_arm_mm=param.arm_mm,
            current_depth_mm=param.arm_mm + OPT.UGEOM.PROFILE_RADIUS_MM,
            current_rise_start=param.rise_start,
            current_fall_start=param.fall_start)
    write_json(BASE / 'u_parameters.json', base_params)
    write_json(BASE / 'summary.json', dict(
        mode='baseline', total_interface=len(base_z2['success_ids']) +
        len(base_z2['failed_ids']),
        baseline_success=base_z2['ok'], success=base_z2['ok'],
        recovered=0, candidates=0, changed_u=0, deepened_u=0,
        total_depth_increase_mm=0.0, changes=[],
        validation_status=base_val.get('status'),
        validation_counts=base_val.get('counts')))
    empty_csv(BASE / 'route_changes.csv',
              ['route_id', 'old_arm_mm', 'new_arm_mm', 'old_depth_mm',
               'new_depth_mm', 'old_rise', 'new_rise', 'old_fall', 'new_fall',
               'old_fall_tail', 'new_fall_tail', 'recovered_z2', 'budget_index'])
    empty_csv(BASE / 'u_depth_changes.csv',
              ['route_id', 'old_depth_mm', 'new_depth_mm', 'delta_depth_mm',
               'new_arm_mm'])
    empty_csv(BASE / 'transition_position_changes.csv',
              ['route_id', 'old_rise', 'new_rise', 'rise_delta',
               'old_fall_start', 'new_fall_start', 'fall_delta',
               'new_fall_tail'])
    int_val = read_json(INT / 'validation.json')
    write_json(INT / 'validation_summary.json', dict(
        status=int_val.get('status'),
        geometry_pass=int_val.get('geometry_pass'),
        counts=int_val.get('counts')))
    # top-level validation: replace None integration field
    val = read_json(OUT / 'validation.json')
    val['integration_L7_L8'] = read_json(INT / 'validation_summary.json')
    write_json(OUT / 'validation.json', val)
    print('baseline/integration metadata completed')


if __name__ == '__main__':
    main()
