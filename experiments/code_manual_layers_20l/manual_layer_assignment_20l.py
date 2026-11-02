# -*- coding: utf-8 -*-
"""Deterministic L1-L20 manual layer assignment (round 3).

Rules implemented exactly as specified:

* Z1: L1-L4 = 256 manual same-side U's (already validated, fixed);
  L6 = 128 N<->S connections; L7 = 128 E<->W connections; L5 unused.
* Z2: L8-L19 by connector groups (symmetric pairings); L20 unused; all other
  Z2 connections stay on the original z=0.5 interface plane.
  Endpoint rule: source connector hit wins; else target hit; if both hit and
  disagree, source wins and the record is flagged
  ``dual_endpoint_layer_conflict``; if neither hits -> interface plane (None).
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: physical routing-layer heights (L2..L20), L2 = 0.65 mm, +0.15 mm per layer
LAYER_HEIGHTS = OrderedDict((layer, round(0.65 + 0.15 * (layer - 2), 2))
                            for layer in range(2, 21))
#: interface rows
INTERFACE_Z = {'z1': 0.0, 'z2': 0.5}

#: Z2 connector-group -> layer (north-south six layers, then east-west six)
CONNECTOR_LAYERS = OrderedDict([
    (8, ('N03', 'N14', 'S03', 'S14')),
    (9, ('N04', 'N13', 'S04', 'S13')),
    (10, ('N05', 'N12', 'S05', 'S12')),
    (11, ('N06', 'N11', 'S06', 'S11')),
    (12, ('N07', 'N10', 'S07', 'S10')),
    (13, ('N08', 'N09', 'S08', 'S09')),
    (14, ('E03', 'E14', 'W03', 'W14')),
    (15, ('E04', 'E13', 'W04', 'W13')),
    (16, ('E05', 'E12', 'W05', 'W12')),
    (17, ('E06', 'E11', 'W06', 'W11')),
    (18, ('E07', 'E10', 'W07', 'W10')),
    (19, ('E08', 'E09', 'W08', 'W09')),
])
CONNECTOR_TO_LAYER = {connector: layer
                       for layer, connectors in CONNECTOR_LAYERS.items()
                       for connector in connectors}


def connector_of(port_id):
    """'N03:1:16' -> 'N03'."""
    return str(port_id).split(':')[0].strip().upper()


def z1_manual_layer(record):
    """L1-L4 manual U layer (from the 640 CSV mapping already validated)."""
    return int(record['manual_layer'])


def z1_fixed_layer(record):
    """L6 for N<->S, L7 for E<->W, None if not a Z1 opposite connection."""
    if record.get('relation') != 'opposite':
        return None
    sides = {record.get('source_side'), record.get('target_side')}
    if sides == {'N', 'S'}:
        return 6
    if sides == {'E', 'W'}:
        return 7
    return None


def z2_layer_assignment(record):
    """Deterministic Z2 layer from the connector groups (rules 1-4)."""
    source = connector_of(record.get('source_endpoint'))
    target = connector_of(record.get('target_endpoint'))
    source_layer = CONNECTOR_TO_LAYER.get(source)
    target_layer = CONNECTOR_TO_LAYER.get(target)
    conflict = None
    if source_layer is not None:
        layer = source_layer
        if target_layer is not None and target_layer != source_layer:
            conflict = 'dual_endpoint_layer_conflict'
    elif target_layer is not None:
        layer = target_layer
    else:
        layer = None
    return layer, dict(source_connector=source, target_connector=target,
                       source_layer=source_layer, target_layer=target_layer,
                       conflict=conflict)


def build_assignment(payload, manual_connections):
    """Full deterministic audit table for the 1024 connections."""
    manual_ids = set(manual_connections)
    rows = []
    for record in payload['routes']:
        rid = int(record['route_id'])
        plane = record['plane']
        if rid in manual_ids:
            layer = int(manual_connections[rid]['layer'])
            kind = 'manual_u'
            note = dict(source_connector=connector_of(record['source_endpoint']),
                        target_connector=connector_of(record['target_endpoint']),
                        conflict=None)
        elif plane == 'z1':
            layer = z1_fixed_layer(record)
            kind = 'z1_fixed' if layer else 'z1_interface'
            note = dict(source_connector=connector_of(record['source_endpoint']),
                        target_connector=connector_of(record['target_endpoint']),
                        conflict=None)
        else:
            layer, note = z2_layer_assignment(record)
            if layer is not None:
                kind = 'z2_fixed'
            elif record.get('relation') == 'same':
                kind = 'z2_interface_same'
            else:
                kind = 'z2_interface'
        rows.append(dict(route_id=rid, plane=plane, kind=kind,
                         layer=layer,
                         relation=record.get('relation'),
                         source_endpoint=record.get('source_endpoint'),
                         target_endpoint=record.get('target_endpoint'),
                         **note))
    # audit: every connection exactly once
    ids = [row['route_id'] for row in rows]
    audit = dict(
        total=len(rows), unique=len(set(ids)),
        duplicates=[rid for rid, count in Counter(ids).items() if count > 1],
        missing=[rid for rid in set(range(1, 1025)) if rid not in set(ids)],
        by_layer={str(layer): sum(1 for row in rows if row['layer'] == layer)
                  for layer in [None] + list(range(1, 21))},
        dual_conflicts=[row['route_id'] for row in rows
                        if row.get('conflict')],
        by_kind=dict(Counter(row['kind'] for row in rows)),
    )
    return rows, audit


def write_assignment(out_dir, rows, audit):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'z2_layer_audit.json').write_text(
        json.dumps(dict(audit=audit, rows=[row for row in rows
                                           if row['plane'] == 'z2']),
                   ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'layer_assignment_1024.json').write_text(
        json.dumps(dict(audit=audit, rows=rows), ensure_ascii=False, indent=1),
        encoding='utf-8')
    lines = ['route_id,plane,kind,layer,relation,source_endpoint,'
             'target_endpoint,source_connector,target_connector,conflict']
    for row in rows:
        lines.append(','.join(str(row.get(key, '')) for key in
                              ('route_id', 'plane', 'kind', 'layer', 'relation',
                               'source_endpoint', 'target_endpoint',
                               'source_connector', 'target_connector',
                               'conflict')))
    (out / 'layer_assignment_1024.csv').write_text('\n'.join(lines) + '\n',
                                                   encoding='utf-8')
    return out
