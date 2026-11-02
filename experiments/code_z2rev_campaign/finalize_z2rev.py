# -*- coding: utf-8 -*-
"""Finalize the revised-Z2 campaign: Z2 C4 audit, layer usage, comparison, best dir."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
NEW_LIFT = CAMPAIGN / '02_layer_sweep/L15/lift'
OLD_ROW = OLD / 'best_solution/layer_row.json'
OLD_COMPARE = OLD / 'comparison.json'
NEW_PHASE2 = CAMPAIGN / 'phase2_summary.json'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def main():
    payload = read(NEW_LIFT / 'routes_l3d.json')
    records = payload['routes']
    routed = [record for record in records
              if record.get('status') == 'routed']
    layer_counts = Counter()
    layer_routes = Counter()
    for record in routed:
        zs = sorted({round(float(part['z_mm']), 6)
                     for part in record.get('parts') or []
                     if part.get('kind') == 'flat'})
        for z in zs:
            layer_counts[z] += 1
    # --- Z2 strict C4 audit (records-based; reuse previous campaign helper) --
    spec = importlib.util.spec_from_file_location(
        'old_finalize2', OLD / 'finalize2.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CAMPAIGN = CAMPAIGN
    module.OLD = OLD
    module.patch_conn()
    z2_c4 = module.z2_c4_audit(records)
    (NEW_LIFT / 'z2_c4_validation.json').write_text(
        json.dumps(z2_c4, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')

    # --- comparison -------------------------------------------------------
    new_summary = read(NEW_LIFT / 'summary.json') or {}
    new_crossings = read(NEW_LIFT / 'crossings_after.json') or {}
    new_validation = read(NEW_LIFT / 'validation.json') or {}
    old_row = read(OLD_ROW) or {}
    phase2 = read(NEW_PHASE2) or {}
    combined = phase2.get('combined') or {}
    plane_crossings = combined.get('plane_crossings') or {}
    pairs_2d = sum(item.get('crossing_pair_count', 0)
                   for item in plane_crossings.values()) if plane_crossings else None
    old_compare = read(OLD_COMPARE) or []
    old15 = next((row for row in old_compare
                  if int(row.get('layer_count', 0)) == 15), {})
    comparison = dict(
        schema='z2rev_campaign_comparison_v1',
        z2_csv=dict(new_sha=read(CAMPAIGN / 'build_inputs_report.json', {})
                    .get('source_z2', {}).get('sha256'),
                    old_sha=read(OLD / 'build_inputs_report.json', {})
                    .get('source_z2', {}).get('sha256')),
        two_d=dict(new_routed=combined.get('routed'),
                   new_pairs=pairs_2d,
                   new_validation=combined.get('validation_passed'),
                   old_routed=992, old_pairs=116748,
                   z2_routed=phase2.get('z2_repair', {}).get('routed')),
        three_d_15l=dict(
            new_routed=new_summary.get('routed_after'),
            new_pairs=new_crossings.get('unique_pair_count'),
            new_violations=(new_validation.get('counts') or {}).get('violations'),
            new_lifted_groups=new_summary.get('lifted_groups'),
            new_transitions=new_summary.get('transitions'),
            old_routed=old_row.get('routed'),
            old_pairs=old_row.get('unique_crossing_pairs'),
            old_violations=old_row.get('violations')),
        layer_usage={str(key): value for key, value in sorted(layer_counts.items())},
        z2_c4=dict(symmetry_pass=z2_c4.get('symmetry_pass'),
                   complete_orbits=z2_c4.get('complete_orbits'),
                   incomplete_orbits=z2_c4.get('incomplete_orbits'),
                   max_deviation_mm=z2_c4.get('maximum_xyz_deviation_mm')),
    )
    old_pairs = old_row.get('unique_crossing_pairs') or old15.get(
        'unique_crossing_pairs')
    if pairs_2d and old_pairs:
        comparison['reduction_ratio'] = dict(
            new=round(1 - comparison['three_d_15l']['new_pairs'] / pairs_2d, 4),
            old=round(1 - old_pairs / 116748, 4))
    (CAMPAIGN / 'comparison_z2rev.json').write_text(
        json.dumps(comparison, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')

    # --- best solution copy ----------------------------------------------
    best = CAMPAIGN / 'best_solution'
    best.mkdir(exist_ok=True)
    for name in ('routes_l3d.json', 'validation.json', 'summary.json',
                 'crossings_after.json', 'layer_stack.json', 'lift_plans.json'):
        source = NEW_LIFT / name
        if source.exists():
            shutil.copyfile(source, best / name)
    shutil.copyfile(NEW_LIFT / 'z2_c4_validation.json',
                    best / 'z2_c4_validation.json')
    (best / 'layer_row.json').write_text(
        json.dumps(dict(layer_count=15,
                        routed=new_summary.get('routed_after'),
                        violations=(new_validation.get('counts') or {}).get(
                            'violations'),
                        unique_crossing_pairs=new_crossings.get(
                            'unique_pair_count'),
                        lifted_groups=new_summary.get('lifted_groups'),
                        transitions=new_summary.get('transitions'),
                        layer_route_counts={str(key): value
                                            for key, value in sorted(
                                                layer_counts.items())},
                        z2_c4=comparison['z2_c4']),
                   ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(comparison, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
