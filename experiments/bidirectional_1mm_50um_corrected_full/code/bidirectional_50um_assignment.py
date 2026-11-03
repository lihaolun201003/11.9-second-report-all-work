# -*- coding: utf-8 -*-
"""Corrected 18-plane (6 Z1 + 12 independent Z2) 1 mm layer model."""
from __future__ import annotations

import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path

from . import glass_1mm_process_rules as RULES

ROOT = Path(__file__).resolve().parents[2]
OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
       / 'BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL')
V4 = (ROOT / 'outputs/manual_c4_new_connectivity'
      / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected')
OLD_ASSIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
              / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/assignment_1024.json')

Z_MIN_MM = -0.35
Z_MAX_MM = 0.65
PHYSICAL_LAYERS = OrderedDict([
    (2, -0.35), (3, -0.29), (4, -0.23), (5, -0.17),   # Z1 manual U
    (6, -0.11), (7, -0.05),                            # Z1 opposite
    (8, 0.05), (9, 0.10), (10, 0.15), (11, 0.20),
    (12, 0.25), (13, 0.30), (14, 0.35), (15, 0.40),
    (16, 0.45), (17, 0.55), (18, 0.60), (19, 0.65),   # Z2 12 independent
])
ROUTING_LAYER_IDS = tuple(PHYSICAL_LAYERS)
Z1_LAYER_MAP = {2: 2, 3: 3, 4: 4, 5: 5, 7: 6, 8: 7}
Z2_LAYER_MAP = {old: 8 + (old - 9) for old in range(9, 21)}


def layer_stack_payload():
    allowed = [1] + list(ROUTING_LAYER_IDS)
    layers = {'1': dict(layer_id=1, layer_type='interface',
                        physical_z_mm=None,
                        interface_rows={'z1': RULES.Z1_MM,
                                        'z2': RULES.Z2_MM},
                        allowed_transitions=allowed)}
    for lid, z in PHYSICAL_LAYERS.items():
        layers[str(lid)] = dict(layer_id=lid, layer_type='routing',
                                physical_z_mm=z,
                                interface_rows={},
                                allowed_transitions=allowed)
    return dict(schema='four_side_1024_v2_l3d_layer_stack_v1',
                provenance='unconfirmed_simulation',
                formal_acceptance_allowed=False,
                note=('corrected 50um rule: 6 Z1 + 12 independent Z2 '
                      'planes at 0.05 mm pitch'),
                interface_layer=1, max_layer=max(ROUTING_LAYER_IDS),
                layers=layers,
                routing_heights_mm={str(k): float(v)
                                    for k, v in PHYSICAL_LAYERS.items()})


def glass_geometry_payload():
    heights = sorted(PHYSICAL_LAYERS.values())
    return dict(schema='bidirectional_1mm_corrected_glass_v1',
                glass_thickness_mm=RULES.GLASS_THICKNESS_MM,
                z_min_mm=Z_MIN_MM, z_max_mm=Z_MAX_MM,
                z1_interface_mm=RULES.Z1_MM,
                z2_interface_mm=RULES.Z2_MM,
                min_layer_pitch_mm=RULES.MIN_LAYER_PITCH_MM,
                min_3d_clearance_mm=RULES.MIN_3D_CLEARANCE_MM,
                routing_layer_count=len(PHYSICAL_LAYERS),
                z1_plane_count=6, z2_independent_plane_count=12,
                physical_layers={str(k): float(v)
                                 for k, v in PHYSICAL_LAYERS.items()},
                actual_min_layer_gap_mm=min(
                    b - a for a, b in zip(heights, heights[1:])),
                nearest_z1_layer_gap_mm=abs(heights[0] - RULES.Z1_MM)
                if heights[0] > RULES.Z1_MM else min(
                    abs(z - RULES.Z1_MM) for z in heights),
                nearest_z2_layer_gap_mm=min(
                    abs(z - RULES.Z2_MM) for z in heights),
                lower_margin_mm=round(heights[0] - Z_MIN_MM, 6),
                upper_margin_mm=round(Z_MAX_MM - heights[-1], 6),
                note='confirmed inputs: 1 mm glass, 50 um layer pitch, bidirectional')


def build_assignment():
    old = {int(r['route_id']): r for r in
           json.loads(OLD_ASSIGN.read_text(encoding='utf-8'))['rows']}
    records = json.loads((V4 / 'routes_1024.json').read_text(
        encoding='utf-8'))['routes']
    rows = []
    for rec in sorted(records, key=lambda r: int(r['route_id'])):
        rid = int(rec['route_id'])
        src = old[rid]
        if rec['plane'] == 'z1':
            if src['kind'] == 'manual_u':
                physical = Z1_LAYER_MAP[int(src['old_manual_layer']) + 1]
            elif src['kind'] == 'z1_opposite_ns':
                physical = Z1_LAYER_MAP[7]
            else:
                physical = Z1_LAYER_MAP[8]
            region = 'Z1_DOWN'
            direction = 'down'
            interface = 'z1'
        else:
            old_layer = src.get('target_layer')
            if old_layer is None:
                physical = None; region = 'Z2_INTERFACE'; direction = 'flat'
            else:
                physical = Z2_LAYER_MAP[int(old_layer)]
                region = ('Z2_MIDDLE' if PHYSICAL_LAYERS[physical] < RULES.Z2_MM
                          else 'Z2_UP')
                direction = ('down' if PHYSICAL_LAYERS[physical] < RULES.Z2_MM
                             else 'up')
            interface = 'z2'
        rows.append(dict(route_id=rid, plane=rec['plane'],
                         logical_kind=src['kind'], logical_layer=old_layer
                         if rec['plane'] == 'z2' else src.get('target_layer'),
                         physical_layer=physical,
                         target_z_mm=(RULES.Z2_MM if physical is None
                                      else PHYSICAL_LAYERS[physical]),
                         interface=interface, region=region,
                         direction=direction,
                         source_endpoint=rec['source_endpoint'],
                         target_endpoint=rec['target_endpoint'],
                         source_side=rec['source_side'],
                         target_side=rec['target_side'],
                         c4_group_id=src.get('c4_group_id'),
                         source_connector=src.get('source_connector'),
                         target_connector=src.get('target_connector'),
                         dual_conflict=src.get('dual_endpoint_layer_conflict'),
                         old_manual_layer=src.get('old_manual_layer'),
                         manual_group=src.get('manual_group'),
                         manual_order=src.get('manual_order')))
    return rows


def write_assignment(out=OUT):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    rows = build_assignment()
    (out / 'process_rules.json').write_text(
        json.dumps(RULES.rules_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    (out / 'glass_geometry.json').write_text(
        json.dumps(glass_geometry_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    (out / 'physical_layer_stack.json').write_text(
        json.dumps(layer_stack_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    with (out / 'assignment_1024.csv').open('w', newline='',
                                            encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    with (out / 'logical_to_physical_layers.csv').open(
            'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['plane', 'logical_layer', 'physical_layer', 'z_mm',
                    'region', 'direction'])
        for old_l in range(2, 9):
            if old_l in Z1_LAYER_MAP:
                p = Z1_LAYER_MAP[old_l]
                w.writerow(['z1', old_l, p, PHYSICAL_LAYERS[p], 'Z1_DOWN',
                            'down'])
        for old_l in range(9, 21):
            p = Z2_LAYER_MAP[old_l]
            region = ('Z2_MIDDLE' if PHYSICAL_LAYERS[p] < RULES.Z2_MM
                      else 'Z2_UP')
            w.writerow(['z2', old_l, p, PHYSICAL_LAYERS[p], region,
                        'down' if region == 'Z2_MIDDLE' else 'up'])
    summary = dict(total=len(rows),
                   z1=sum(r['plane'] == 'z1' for r in rows),
                   z2=sum(r['plane'] == 'z2' for r in rows),
                   by_region=dict(Counter(
                       f"{r['plane']}:{r['region']}" for r in rows)),
                   z2_independent_planes=12)
    (out / 'assignment_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return rows, summary


if __name__ == '__main__':
    rows, summary = write_assignment()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
