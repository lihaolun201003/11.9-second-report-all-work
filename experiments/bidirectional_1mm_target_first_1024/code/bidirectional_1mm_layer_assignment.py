# -*- coding: utf-8 -*-
"""Bidirectional 1 mm glass layer model and 1024-channel assignment.

Physical model
--------------
* glass: z in [-0.25, +0.75] mm (1.00 mm total, configurable bounds)
* Z1 interface row at z = 0.00, Z2 interface row at z = 0.50
* MIN_LAYER_PITCH = 0.05 mm (process limit, not the 3D clearance)
* MIN_3D_CLEARANCE = 0.08 mm (unchanged strict centre-line rule)

Z1 routes are biased to negative z; Z2 routes are biased to positive z above
0.5.  The 0..0.5 mm middle region is used by Z1 because it has only two
comfortable negative layers inside a symmetric 0.25 mm lower half.  The chosen
physical layers are deliberately spaced by >= 0.08 mm so that two full-width
waveguides on neighbouring planes never satisfy 0.08 mm by z alone; XY
separation is therefore never assumed away, and exact 0.08 gaps only occur
between a routing layer and an interface row.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
       / 'BIDIRECTIONAL_1MM_1024_FULL')
V4 = (ROOT / 'outputs/manual_c4_new_connectivity'
      / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected')
CK = (ROOT / 'outputs/manual_c4_new_connectivity'
      / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/checkpoints')

GLASS_THICKNESS_MM = 1.0
Z_MIN_MM = -0.25
Z_MAX_MM = 0.75
Z1_MM = 0.0
Z2_MM = 0.5
MIN_LAYER_PITCH_MM = 0.05
MIN_3D_CLEARANCE_MM = 0.08

#: physical routing layers (layer_id -> z).  L1 is the two-row interface layer.
#: The 0.08 gaps between L2/L3 and L8/L9/L10 are intentional: a 0.08 vertical
#: offset alone is exactly the clearance, so the real 3D checker still decides.
PHYSICAL_LAYERS = OrderedDict([
    (2, -0.18),   # Z1 manual U group 1: downward
    (3, -0.09),   # Z1 manual U group 2: downward
    (4, 0.08),    # Z1 manual U group 3: middle
    (5, 0.16),    # Z1 manual U group 4: middle
    (6, 0.24),    # Z1 N-S opposite edges
    (7, 0.32),    # Z1 E-W opposite edges
    (8, 0.42),    # Z2 logical groups: middle, below the Z2 interface
    (9, 0.58),    # Z2 logical groups: upward
    (10, 0.66),   # Z2 logical groups: upward
    (11, 0.74),   # Z2 logical groups: upward
])
ROUTING_LAYER_IDS = tuple(PHYSICAL_LAYERS)

#: Z1 logical group -> physical layer.
Z1_LAYER_MAP = {2: 2, 3: 3, 4: 4, 5: 5,   # manual U, old 20L L2-L5
                7: 6, 8: 7}               # opposite NS / EW
#: Z2 old logical layer -> physical layer (four upper/middle planes).
Z2_LAYER_MAP = {9: 8, 10: 9, 11: 10, 12: 11,
                13: 8, 14: 9, 15: 10, 16: 11,
                17: 8, 18: 9, 19: 10, 20: 11}


def layer_z(layer_id):
    layer_id = int(layer_id)
    if layer_id == 1:
        raise ValueError('L1 is the interface layer; specify z1/z2 row')
    return float(PHYSICAL_LAYERS[layer_id])


def layer_stack_payload():
    allowed = [1] + list(ROUTING_LAYER_IDS)
    layers = {
        '1': dict(layer_id=1, layer_type='interface', physical_z_mm=None,
                  interface_rows={'z1': Z1_MM, 'z2': Z2_MM},
                  allowed_transitions=allowed)}
    for layer_id, z_mm in PHYSICAL_LAYERS.items():
        layers[str(layer_id)] = dict(
            layer_id=int(layer_id), layer_type='routing',
            physical_z_mm=float(z_mm), interface_rows={},
            allowed_transitions=allowed)
    return dict(
        schema='four_side_1024_v2_l3d_layer_stack_v1',
        provenance='unconfirmed_simulation',
        formal_acceptance_allowed=False,
        note=('bidirectional 1 mm glass: z in [-0.25, 0.75], Z1=0, '
              'Z2=0.5, minimum layer pitch 0.05 mm, 3D clearance 0.08 mm'),
        interface_layer=1,
        max_layer=max(ROUTING_LAYER_IDS),
        layers=layers,
        routing_heights_mm={str(layer_id): float(z_mm)
                            for layer_id, z_mm in PHYSICAL_LAYERS.items()})


def glass_geometry_payload():
    heights = [float(z) for z in PHYSICAL_LAYERS.values()]
    return dict(
        schema='bidirectional_1mm_glass_v1',
        glass_thickness_mm=GLASS_THICKNESS_MM,
        z_min_mm=Z_MIN_MM, z_max_mm=Z_MAX_MM,
        z1_interface_mm=Z1_MM, z2_interface_mm=Z2_MM,
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
        min_3d_clearance_mm=MIN_3D_CLEARANCE_MM,
        routing_layer_count=len(PHYSICAL_LAYERS),
        physical_layers={str(k): float(v) for k, v in PHYSICAL_LAYERS.items()},
        physical_plane_zs=sorted([Z1_MM, Z2_MM] + heights),
        actual_min_layer_gap_mm=min(
            [(b - a) for a, b in zip(sorted([Z1_MM, Z2_MM] + heights),
                                    sorted([Z1_MM, Z2_MM] + heights)[1:])]),
        lower_margin_mm=round(min(heights) - Z_MIN_MM, 6),
        upper_margin_mm=round(Z_MAX_MM - max(heights), 6),
        z1_downward_space_mm=Z1_MM - Z_MIN_MM,
        z2_upward_space_mm=Z_MAX_MM - Z2_MM,
        note=('symmetric baseline; the 0.25 mm lower/upper halves are '
              'simulation assumptions, not confirmed interface-to-surface '
              'process dimensions'))


def load_inputs():
    manual = json.loads((ROOT / 'outputs/manual_c4_new_connectivity'
                         / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/assignment_1024.json')
                        .read_text(encoding='utf-8'))['rows']
    audit = {str(row['route_id']): row for row in manual}
    payload = json.loads((V4 / 'routes_1024.json').read_text(encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    return audit, records


def build_assignment():
    """Return (rows, summary) for all 1024 connections in the 1 mm model."""
    audit, records = load_inputs()
    rows = []
    for rid in sorted(records):
        record = records[rid]
        logical = audit[str(rid)]
        old_layer = logical.get('target_layer')
        if record['plane'] == 'z1':
            if logical['kind'] == 'manual_u':
                old_manual_layer = int(logical['old_manual_layer'])
                physical = Z1_LAYER_MAP[old_manual_layer + 1]
                region = 'Z1_DOWN' if physical <= 3 else 'Z1_MIDDLE'
            elif logical['kind'] == 'z1_opposite_ns':
                physical = Z1_LAYER_MAP[7]
                region = 'Z1_MIDDLE'
            elif logical['kind'] == 'z1_opposite_ew':
                physical = Z1_LAYER_MAP[8]
                region = 'Z1_MIDDLE'
            else:
                raise ValueError(logical)
            direction = 'down' if PHYSICAL_LAYERS[physical] < Z1_MM else 'up'
            interface = 'z1'
        else:
            if old_layer is None:
                physical = None
                region = 'Z2_INTERFACE'
                direction = 'flat'
            else:
                physical = Z2_LAYER_MAP[int(old_layer)]
                region = 'Z2_UP'
                direction = 'up'
            interface = 'z2'
        rows.append(dict(
            route_id=int(rid), plane=record['plane'], relation=record.get('relation'),
            logical_kind=logical['kind'], logical_layer=old_layer,
            physical_layer=physical,
            target_z_mm=(Z2_MM if physical is None
                         else PHYSICAL_LAYERS[physical]),
            interface=interface, region=region, direction=direction,
            source_endpoint=record['source_endpoint'],
            target_endpoint=record['target_endpoint'],
            source_side=record['source_side'], target_side=record['target_side'],
            c4_group_id=logical.get('c4_group_id'),
            source_connector=logical.get('source_connector'),
            target_connector=logical.get('target_connector'),
            dual_conflict=logical.get('dual_endpoint_layer_conflict'),
            old_manual_layer=logical.get('old_manual_layer'),
            manual_group=logical.get('manual_group'),
            manual_order=logical.get('manual_order'),
            baseline_status=record.get('status'),
        ))
    by_region = Counter(row['region'] for row in rows)
    by_layer = Counter(row['physical_layer'] for row in rows)
    return rows, dict(total=len(rows), by_region=dict(by_region),
                      by_layer={str(k): v for k, v in by_layer.items()},
                      z1=sum(1 for r in rows if r['plane'] == 'z1'),
                      z2=sum(1 for r in rows if r['plane'] == 'z2'))


def write_assignment(out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, summary = build_assignment()
    (out_dir / 'glass_geometry.json').write_text(
        json.dumps(glass_geometry_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    (out_dir / 'physical_layer_stack.json').write_text(
        json.dumps(layer_stack_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    fields = list(rows[0])
    with (out_dir / 'assignment_1024.csv').open('w', newline='',
                                                encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (out_dir / 'logical_to_physical_layers.csv').open(
            'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['plane', 'logical_layers', 'physical_layer',
                         'z_mm', 'region', 'note'])
        for plane in ('z1', 'z2'):
            if plane == 'z1':
                mapping = [('manual U L2-L5 -> physical 2-5',
                            '2,3,4,5', '-0.18,-0.09,0.09,0.18'),
                           ('opposite NS -> physical 6', '7', '0.27'),
                           ('opposite EW -> physical 7', '8', '0.36')]
            else:
                mapping = []
                for old in range(9, 21):
                    mapping.append((f'Z2 logical L{old}', str(old),
                                    f'{Z2_LAYER_MAP[old]}',
                                    f'{PHYSICAL_LAYERS[Z2_LAYER_MAP[old]]}'))
            for item in mapping:
                if plane == 'z1':
                    writer.writerow([plane, item[0], item[1], item[2], '', ''])
                else:
                    writer.writerow([plane, item[0], item[2], item[3],
                                     'Z2_UP', ''])
    (out_dir / 'assignment_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return rows, summary


if __name__ == '__main__':
    rows, summary = write_assignment()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('glass', json.dumps(glass_geometry_payload(), ensure_ascii=False,
                              indent=1))
