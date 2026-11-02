# -*- coding: utf-8 -*-
"""Authoritative L1-L20 manual layer assignment for the 1024 channels.

This module implements the round-3 fixed assignment exactly as specified by the
graduation-project task.  It is descriptive and deterministic: it never changes
an endpoint pairing, a C4 rotation group or a manual nesting order.

Layer model (the only authority for this experiment)::

    L1 interface rows: z1 = 0.00 mm, z2 = 0.50 mm
    L2 .. L20        : z(L) = 0.65 + 0.15 * (L - 2) mm
    L6               : reserved, no new routes

Z1 (512 connections):
    256 manual same-side U's  -> L2, L3, L4, L5  (64 each)
    128 N<->S opposite        -> L7
    128 E<->W opposite        -> L8

Z2 (512 connections):
    connector groups          -> L9 .. L20 (symmetric pairs)
    source endpoint hit wins; target hit only if source does not hit
    both hits on different layers -> source wins and the route is flagged
    no hit -> remains on the z = 0.50 mm interface plane
"""
from __future__ import annotations

import csv
import json
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V4_ROOT = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected')
MANUAL_CSV = (ROOT / 'manual_z1_router/data/exports/人工分组'
              / 'z1_z2_manual_u_assignment_v2_640.csv')
DEFAULT_OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
               / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL')

#: L1..L20 physical model.  ``purpose`` is documentation only.
LAYER_TABLE = OrderedDict([
    (1, dict(z_mm=0.0, layer_type='interface', purpose='Z1 interface plane')),
    (2, dict(z_mm=0.65, layer_type='routing',
             purpose='Z1 manual U, north-south first group')),
    (3, dict(z_mm=0.80, layer_type='routing',
             purpose='Z1 manual U, north-south second group')),
    (4, dict(z_mm=0.95, layer_type='routing',
             purpose='Z1 manual U, east-west first group')),
    (5, dict(z_mm=1.10, layer_type='routing',
             purpose='Z1 manual U, east-west second group')),
    (6, dict(z_mm=1.25, layer_type='routing',
             purpose='reserved (reserved for future use; no new routes)')),
    (7, dict(z_mm=1.40, layer_type='routing',
             purpose='Z1 north-south opposite-side connections')),
    (8, dict(z_mm=1.55, layer_type='routing',
             purpose='Z1 east-west opposite-side connections')),
    (9, dict(z_mm=1.70, layer_type='routing',
             purpose='Z2 north-south connectors 03/14')),
    (10, dict(z_mm=1.85, layer_type='routing',
              purpose='Z2 north-south connectors 04/13')),
    (11, dict(z_mm=2.00, layer_type='routing',
              purpose='Z2 north-south connectors 05/12')),
    (12, dict(z_mm=2.15, layer_type='routing',
              purpose='Z2 north-south connectors 06/11')),
    (13, dict(z_mm=2.30, layer_type='routing',
              purpose='Z2 north-south connectors 07/10')),
    (14, dict(z_mm=2.45, layer_type='routing',
              purpose='Z2 north-south connectors 08/09')),
    (15, dict(z_mm=2.60, layer_type='routing',
              purpose='Z2 east-west connectors 03/14')),
    (16, dict(z_mm=2.75, layer_type='routing',
              purpose='Z2 east-west connectors 04/13')),
    (17, dict(z_mm=2.90, layer_type='routing',
              purpose='Z2 east-west connectors 05/12')),
    (18, dict(z_mm=3.05, layer_type='routing',
              purpose='Z2 east-west connectors 06/11')),
    (19, dict(z_mm=3.20, layer_type='routing',
              purpose='Z2 east-west connectors 07/10')),
    (20, dict(z_mm=3.35, layer_type='routing',
              purpose='Z2 east-west connectors 08/09')),
])
ROUTING_LAYERS = tuple(range(2, 21))
INTERFACE_Z = {'z1': 0.0, 'z2': 0.5}
RESERVED_LAYERS = (6,)

#: The old 640-CSV manual layers (L1..L4) shift by exactly one layer.
MANUAL_OLD_TO_NEW = {1: 2, 2: 3, 3: 4, 4: 5}
MANUAL_LAYERS = (2, 3, 4, 5)

#: Z2 symmetric connector groups.  Keys are *new* physical layer ids.
CONNECTOR_LAYERS = OrderedDict([
    (9, ('N03', 'N14', 'S03', 'S14')),
    (10, ('N04', 'N13', 'S04', 'S13')),
    (11, ('N05', 'N12', 'S05', 'S12')),
    (12, ('N06', 'N11', 'S06', 'S11')),
    (13, ('N07', 'N10', 'S07', 'S10')),
    (14, ('N08', 'N09', 'S08', 'S09')),
    (15, ('E03', 'E14', 'W03', 'W14')),
    (16, ('E04', 'E13', 'W04', 'W13')),
    (17, ('E05', 'E12', 'W05', 'W12')),
    (18, ('E06', 'E11', 'W06', 'W11')),
    (19, ('E07', 'E10', 'W07', 'W10')),
    (20, ('E08', 'E09', 'W08', 'W09')),
])
CONNECTOR_TO_LAYER = {connector: layer
                      for layer, connectors in CONNECTOR_LAYERS.items()
                      for connector in connectors}


# ---------------------------------------------------------------------------
# layer helpers
# ---------------------------------------------------------------------------
def layer_z(layer):
    """Physical routing height of L2..L20; L1 needs an interface row."""
    layer = int(layer)
    if layer == 1:
        raise ValueError('L1 is the interface layer; specify a row')
    return float(LAYER_TABLE[layer]['z_mm'])


def route_interface_z(plane):
    return float(INTERFACE_Z[plane])


def layer_stack_payload():
    """Layer stack JSON consumed by the 3D validator (schema kept compatible)."""
    layers = {}
    for layer_id, row in LAYER_TABLE.items():
        if layer_id == 1:
            layers[str(layer_id)] = dict(
                layer_id=1, layer_type='interface', physical_z_mm=None,
                interface_rows={key: float(value)
                                for key, value in INTERFACE_Z.items()},
                allowed_transitions=list(range(1, 21)))
        else:
            layers[str(layer_id)] = dict(
                layer_id=int(layer_id), layer_type='routing',
                physical_z_mm=float(row['z_mm']),
                interface_rows={},
                allowed_transitions=list(range(1, 21)))
    return dict(
        schema='four_side_1024_v2_l3d_layer_stack_v1',
        provenance='unconfirmed_simulation',
        formal_acceptance_allowed=False,
        note=('round-3 manual fixed L1-L20 assignment: L2=0.65 mm, '
              '0.15 mm pitch, L20=3.35 mm; L6 reserved'),
        interface_layer=1,
        max_layer=20,
        layers=layers,
        routing_heights_mm={str(layer): float(row['z_mm'])
                            for layer, row in LAYER_TABLE.items()
                            if layer != 1})


# ---------------------------------------------------------------------------
# manual U mapping
# ---------------------------------------------------------------------------
def connector_of(port_id):
    return str(port_id).split(':')[0].strip().upper()


def load_manual_u_mapping(path=None):
    """Load the 256 Z1 same-side manual U's from the authoritative 640 CSV.

    The old ``assigned_layer`` values L1..L4 are shifted by one to the new
    L2..L5.  The grouping / order / nesting metadata is copied unchanged.
    """
    path = Path(path or MANUAL_CSV)
    raw = path.read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(raw.splitlines()))
    manual = OrderedDict()
    for row in rows:
        if row.get('input_dataset') != 'z1':
            continue
        if row.get('routing_method') != 'manual_fixed_u':
            continue
        old_text = (row.get('assigned_layer') or '').strip().upper()
        if not old_text.startswith('L'):
            raise ValueError(f'manual U row without layer: {row}')
        old_layer = int(old_text[1:])
        if old_layer not in MANUAL_OLD_TO_NEW:
            raise ValueError(f'unexpected old manual layer {old_layer}')
        route_id = int(row['route_id'])
        manual[route_id] = dict(
            route_id=route_id,
            old_layer=old_layer,
            new_layer=MANUAL_OLD_TO_NEW[old_layer],
            manual_group=(row.get('manual_group') or '').strip() or None,
            manual_order=(row.get('manual_group_order') or '').strip() or None,
            u_pair=(row.get('u_pair') or '').strip() or None,
            side=(row.get('source_side') or '').strip().upper(),
            source_port_id=row.get('source_port_id'),
            target_port_id=row.get('target_port_id'),
            source_xy=[float(row['source_x_mm']), float(row['source_y_mm'])],
            target_xy=[float(row['target_x_mm']), float(row['target_y_mm'])],
            csv_sha256=None,  # filled by load_manual_u_mapping report caller
        )
    counts = Counter(row['new_layer'] for row in manual.values())
    if len(manual) != 256 or any(counts[layer] != 64 for layer in MANUAL_LAYERS):
        raise ValueError(f'manual U count invalid: n={len(manual)}, {dict(counts)}')
    return manual


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------
def z1_assign(record, manual):
    rid = int(record['route_id'])
    if rid in manual:
        info = manual[rid]
        return dict(layer=info['new_layer'], kind='manual_u',
                    reason='manual_640_csv_shift_L1-L4_to_L2-L5',
                    old_manual_layer=info['old_layer'],
                    manual_group=info['manual_group'],
                    manual_order=info['manual_order'],
                    u_pair=info['u_pair'])
    if record.get('relation') == 'opposite':
        sides = {record.get('source_side'), record.get('target_side')}
        if sides == {'N', 'S'}:
            return dict(layer=7, kind='z1_opposite_ns',
                        reason='Z1_N<->S_opposite_fixed_L7',
                        old_manual_layer=None, manual_group=None,
                        manual_order=None, u_pair=None)
        if sides == {'E', 'W'}:
            return dict(layer=8, kind='z1_opposite_ew',
                        reason='Z1_E<->W_opposite_fixed_L8',
                        old_manual_layer=None, manual_group=None,
                        manual_order=None, u_pair=None)
    raise ValueError(f'Z1 route {rid} is neither manual U nor opposite: {record}')


def z2_assign(record):
    source = connector_of(record.get('source_endpoint'))
    target = connector_of(record.get('target_endpoint'))
    source_layer = CONNECTOR_TO_LAYER.get(source)
    target_layer = CONNECTOR_TO_LAYER.get(target)
    conflict = False
    if source_layer is not None:
        layer = source_layer
        reason = 'source_connector_group'
        if target_layer is not None and target_layer != source_layer:
            conflict = True
            reason = 'source_connector_group_source_priority'
    elif target_layer is not None:
        layer = target_layer
        reason = 'target_connector_group_source_unmatched'
    else:
        layer = None
        reason = 'no_connector_group_interface_plane'
    return dict(layer=layer, source_connector=source,
                target_connector=target,
                source_suggested_layer=source_layer,
                target_suggested_layer=target_layer,
                assignment_reason=reason,
                dual_endpoint_layer_conflict=bool(conflict))


def build_assignment(payload, manual):
    """Return ``(all_rows, summary)`` for all 1024 connections."""
    records = [record for record in payload['routes']]
    if len(records) != 1024:
        raise ValueError(f'expected 1024 records, got {len(records)}')
    by_id = {int(record['route_id']): record for record in records}
    if set(by_id) != set(range(1, 1025)):
        raise ValueError('route ids are not exactly 1..1024')
    group_of = {}
    for group in payload.get('rotation_groups') or []:
        for rid in group['route_ids']:
            group_of[int(rid)] = int(group['group_id'])
    rows = []
    for rid in sorted(by_id):
        record = by_id[rid]
        plane = record['plane']
        base = dict(
            route_id=rid,
            plane=plane,
            relation=record.get('relation'),
            source_endpoint=record.get('source_endpoint'),
            target_endpoint=record.get('target_endpoint'),
            source_side=record.get('source_side'),
            target_side=record.get('target_side'),
            c4_group_id=group_of.get(rid),
            rotation_phase=record.get('rotation_phase'),
            baseline_status=record.get('status'),
        )
        if plane == 'z1':
            info = z1_assign(record, manual)
            base.update(info)
            base.update(
                source_connector=connector_of(record['source_endpoint']),
                target_connector=connector_of(record['target_endpoint']),
                source_suggested_layer=None,
                target_suggested_layer=None,
                dual_endpoint_layer_conflict=False,
                interface_z_mm=0.0,
            )
        elif plane == 'z2':
            info = z2_assign(record)
            base.update(info)
            base.update(
                kind=('z2_fixed' if info['layer'] is not None
                      else 'z2_interface'),
                old_manual_layer=None, manual_group=None, manual_order=None,
                u_pair=None, interface_z_mm=0.5,
            )
        else:
            raise ValueError(f'unknown plane {plane!r}')
        base['target_z_mm'] = (0.5 if base['layer'] is None
                               else layer_z(base['layer']))
        base['target_layer'] = (None if base['layer'] is None
                                else int(base['layer']))
        rows.append(base)
    # ---- structural checks -------------------------------------------------
    ids = [row['route_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate assignment rows')
    z1 = [row for row in rows if row['plane'] == 'z1']
    z2 = [row for row in rows if row['plane'] == 'z2']
    if len(z1) != 512 or len(z2) != 512:
        raise ValueError(f'plane split wrong: z1={len(z1)}, z2={len(z2)}')
    z1_kinds = Counter(row['kind'] for row in z1)
    if z1_kinds != {'manual_u': 256, 'z1_opposite_ns': 128,
                    'z1_opposite_ew': 128}:
        raise ValueError(f'Z1 assignment kinds wrong: {dict(z1_kinds)}')
    z1_layers = Counter(row['target_layer'] for row in z1)
    expected_z1 = {2: 64, 3: 64, 4: 64, 5: 64, 7: 128, 8: 128}
    if dict(z1_layers) != expected_z1:
        raise ValueError(f'Z1 layer assignment wrong: {dict(z1_layers)}')
    z2_high = [row for row in z2 if row['target_layer'] is not None]
    z2_interface = [row for row in z2 if row['target_layer'] is None]
    conflicts = [row for row in z2 if row['dual_endpoint_layer_conflict']]
    # all C4 members must keep their original connectivity; we only audit the
    # layer spread, because the task explicitly allows per-member layers.
    group_layers = {}
    for row in z2:
        if row['c4_group_id'] is not None:
            group_layers.setdefault(row['c4_group_id'], set()).add(
                row['target_layer'])
    summary = dict(
        schema='manual_20l_assignment_v1',
        total=len(rows),
        z1=dict(total=len(z1), kinds=dict(z1_kinds),
                by_layer={str(key): value for key, value in
                          sorted(z1_layers.items())},
                manual_u=256,
                manual_by_layer={str(layer): sum(
                    1 for row in z1 if row['target_layer'] == layer)
                    for layer in MANUAL_LAYERS},
                opposite_ns=128, opposite_ew=128,
                interface_residual=0),
        z2=dict(total=len(z2), high=len(z2_high),
                interface=len(z2_interface),
                by_layer={str(layer): sum(1 for row in z2
                                          if row['target_layer'] == layer)
                          for layer in list(range(9, 21)) + [None]},
                dual_endpoint_layer_conflicts=len(conflicts),
                conflict_route_ids=sorted(row['route_id']
                                          for row in conflicts)[:200],
                c4_groups=len(group_layers),
                c4_groups_spanning_multiple_layers=sum(
                    1 for layers in group_layers.values() if len(layers) > 1),
                source_priority_used=sum(
                    1 for row in z2
                    if row['assignment_reason'] ==
                    'source_connector_group_source_priority'),
                target_only_assigned=sum(
                    1 for row in z2
                    if row['assignment_reason'] ==
                    'target_connector_group_source_unmatched'),
                interface_residual=len(z2_interface)),
        by_layer={str(layer): sum(1 for row in rows
                                  if row['target_layer'] == layer)
                  for layer in list(range(1, 21)) + [None]},
    )
    return rows, summary


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def _write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields,
                                extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_assignment(out_dir, rows, summary, records_payload=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'layer_stack.json').write_text(
        json.dumps(layer_stack_payload(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    z1 = [row for row in rows if row['plane'] == 'z1']
    z2 = [row for row in rows if row['plane'] == 'z2']
    z1_fields = ['route_id', 'plane', 'kind', 'target_layer', 'target_z_mm',
                 'relation', 'source_endpoint', 'target_endpoint',
                 'source_side', 'target_side', 'source_connector',
                 'target_connector', 'old_manual_layer', 'manual_group',
                 'manual_order', 'u_pair', 'c4_group_id', 'rotation_phase',
                 'assignment_reason', 'baseline_status']
    z2_fields = ['route_id', 'plane', 'kind', 'target_layer', 'target_z_mm',
                 'relation', 'source_endpoint', 'target_endpoint',
                 'source_side', 'target_side', 'source_connector',
                 'target_connector', 'source_suggested_layer',
                 'target_suggested_layer', 'dual_endpoint_layer_conflict',
                 'assignment_reason', 'c4_group_id', 'rotation_phase',
                 'baseline_status']
    _write_csv(out / 'z1_assignment_audit.csv', z1, z1_fields)
    _write_csv(out / 'z2_assignment_audit.csv', z2, z2_fields)
    _write_csv(out / 'assignment_1024.csv', rows,
               list(dict.fromkeys(z1_fields + z2_fields)))
    (out / 'assignment_1024.json').write_text(
        json.dumps(dict(summary=summary, rows=rows), ensure_ascii=False,
                   indent=1), encoding='utf-8')
    (out / 'assignment_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def load_payload(path=None):
    path = Path(path or (V4_ROOT / 'routes_1024.json'))
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    payload = load_payload()
    manual = load_manual_u_mapping()
    rows, summary = build_assignment(payload, manual)
    out = write_assignment(DEFAULT_OUT, rows, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f'written: {out}')


if __name__ == '__main__':
    main()
