# -*- coding: utf-8 -*-
"""Round 2: 12 independent Z2 physical target planes and 6 Z1 planes.

This is the *candidate* maximum-layer stack used for Experiment A.  The
geometry is deliberately packed at 0.05 mm pitch; whether every route pair can
actually satisfy the 0.08 mm true-3D clearance is decided by the validator, not
by assuming 0.05 pitch is free.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/manual_c4_new_connectivity/BIDIRECTIONAL_1MM_TARGET_FIRST_1024'
V4 = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected'
ASSIGN_OLD = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_20L_FIXED_ASSIGNMENT_FULL/assignment_1024.json'

GLASS_THICKNESS_MM = 1.0
Z_MIN_MM = -0.36
Z_MAX_MM = 0.64
Z1_MM = 0.0
Z2_MM = 0.5
MIN_LAYER_PITCH_MM = 0.05
MIN_3D_CLEARANCE_MM = 0.08

# 6 Z1 planes (2 down U groups, 2 middle U groups, 2 middle opposite)
# 12 Z2 planes (9 middle + 3 up), each logical group gets its own z.
PHYSICAL_LAYERS = OrderedDict([
    (2, -0.35), (3, -0.30), (4, -0.25), (5, -0.20),   # Z1 U
    (6, -0.15), (7, -0.10),                            # Z1 opposite
    (8, 0.08), (9, 0.13), (10, 0.18), (11, 0.23),
    (12, 0.28), (13, 0.33), (14, 0.38), (15, 0.43),
    (16, 0.48),                                        # Z2 middle (down)
    (17, 0.53), (18, 0.58), (19, 0.63),               # Z2 up
])
ROUTING_LAYER_IDS = tuple(PHYSICAL_LAYERS)
Z1_LAYER_MAP = {2: 2, 3: 3, 4: 4, 5: 5, 7: 6, 8: 7}
Z2_LAYER_MAP = {old: 8 + (old - 9) for old in range(9, 21)}
Z2_GROUP_LAYER = {f'L{old}': 8 + (old - 9) for old in range(9, 21)}


def layer_stack_payload():
    allowed = [1] + list(ROUTING_LAYER_IDS)
    layers = {'1': dict(layer_id=1, layer_type='interface',
                        physical_z_mm=None,
                        interface_rows={'z1': Z1_MM, 'z2': Z2_MM},
                        allowed_transitions=allowed)}
    for layer_id, z_mm in PHYSICAL_LAYERS.items():
        layers[str(layer_id)] = dict(layer_id=int(layer_id),
                                     layer_type='routing',
                                     physical_z_mm=float(z_mm),
                                     interface_rows={},
                                     allowed_transitions=allowed)
    return dict(schema='four_side_1024_v2_l3d_layer_stack_v1',
                provenance='unconfirmed_simulation',
                formal_acceptance_allowed=False,
                note=('round2 candidate: 6 Z1 planes + 12 independent Z2 '
                      'planes at 0.05 mm pitch; 1 mm glass'),
                interface_layer=1, max_layer=max(ROUTING_LAYER_IDS),
                layers=layers,
                routing_heights_mm={str(k): float(v) for k, v in PHYSICAL_LAYERS.items()})


def glass_geometry_payload():
    return dict(
        schema='bidirectional_1mm_round2_glass_v1',
        glass_thickness_mm=GLASS_THICKNESS_MM,
        z_min_mm=Z_MIN_MM, z_max_mm=Z_MAX_MM,
        z1_interface_mm=Z1_MM, z2_interface_mm=Z2_MM,
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
        min_3d_clearance_mm=MIN_3D_CLEARANCE_MM,
        physical_layers={str(k): float(v) for k, v in PHYSICAL_LAYERS.items()},
        routing_layer_count=len(PHYSICAL_LAYERS),
        z2_independent_plane_count=12,
        z1_plane_count=6,
        actual_min_layer_gap_mm=min(
            b - a for a, b in zip(sorted(PHYSICAL_LAYERS.values()),
                                 sorted(PHYSICAL_LAYERS.values())[1:])),
        lower_margin_mm=round(min(PHYSICAL_LAYERS.values()) - Z_MIN_MM, 6),
        upper_margin_mm=round(Z_MAX_MM - max(PHYSICAL_LAYERS.values()), 6),
        note='round2 candidate: surface margins only 10/10 um; not a process confirmation')


def build_assignment():
    old = {int(r['route_id']): r for r in
           json.loads(ASSIGN_OLD.read_text(encoding='utf-8'))['rows']}
    records = json.loads((V4 / 'routes_1024.json').read_text(encoding='utf-8'))['routes']
    rows = []
    for record in sorted(records, key=lambda r: int(r['route_id'])):
        rid = int(record['route_id'])
        src = old[rid]
        old_layer = src.get('target_layer')
        if record['plane'] == 'z1':
            if src['kind'] == 'manual_u':
                physical = Z1_LAYER_MAP[int(src['old_manual_layer']) + 1]
                region = 'Z1_DOWN' if physical <= 3 else 'Z1_MIDDLE'
            elif src['kind'] == 'z1_opposite_ns':
                physical = Z1_LAYER_MAP[7]; region = 'Z1_MIDDLE'
            else:
                physical = Z1_LAYER_MAP[8]; region = 'Z1_MIDDLE'
            direction = 'down' if PHYSICAL_LAYERS[physical] < Z1_MM else 'up'
            interface = 'z1'
        else:
            old_layer = src.get('target_layer')
            if old_layer is None:
                physical = None; region = 'Z2_INTERFACE'; direction = 'flat'
            else:
                physical = Z2_LAYER_MAP[int(old_layer)]
                region = ('Z2_MIDDLE' if PHYSICAL_LAYERS[physical] < Z2_MM
                          else 'Z2_UP')
                direction = 'down' if PHYSICAL_LAYERS[physical] < Z2_MM else 'up'
            interface = 'z2'
        rows.append(dict(route_id=rid, plane=record['plane'],
                         logical_kind=src['kind'],
                         logical_layer=old_layer,
                         physical_layer=physical,
                         target_z_mm=(Z2_MM if physical is None
                                      else PHYSICAL_LAYERS[physical]),
                         interface=interface, region=region,
                         direction=direction,
                         source_endpoint=record['source_endpoint'],
                         target_endpoint=record['target_endpoint'],
                         source_side=record['source_side'],
                         target_side=record['target_side'],
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
    (out / 'glass_geometry.json').write_text(
        json.dumps(glass_geometry_payload(), ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'physical_layer_stack.json').write_text(
        json.dumps(layer_stack_payload(), ensure_ascii=False, indent=1), encoding='utf-8')
    with (out / 'assignment_1024.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    counts = Counter((r['plane'], r['region']) for r in rows)
    summary = dict(total=len(rows), z1=sum(r['plane'] == 'z1' for r in rows),
                   z2=sum(r['plane'] == 'z2' for r in rows),
                   by_region={f'{k[0]}:{k[1]}': v for k, v in counts.items()},
                   z2_independent_planes=12,
                   z2_planes=[8 + i for i in range(12)])
    (out / 'assignment_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    # logical mapping table
    with (out / 'logical_to_physical_layers.csv').open('w', newline='',
                                                       encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['plane', 'logical_layer', 'physical_layer', 'z_mm', 'region'])
        for old in range(2, 9):
            if old in Z1_LAYER_MAP:
                p = Z1_LAYER_MAP[old]
                w.writerow(['z1', old, p, PHYSICAL_LAYERS[p],
                            'Z1_DOWN' if p <= 3 else 'Z1_MIDDLE'])
        for old in range(9, 21):
            p = Z2_LAYER_MAP[old]
            w.writerow(['z2', old, p, PHYSICAL_LAYERS[p],
                        'Z2_MIDDLE' if p <= 16 else 'Z2_UP'])
    return rows, summary


if __name__ == '__main__':
    rows, summary = write_assignment()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
