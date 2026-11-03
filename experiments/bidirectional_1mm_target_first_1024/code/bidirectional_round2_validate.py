# -*- coding: utf-8 -*-
"""Validate a round-2 route payload with its 1 mm physical layer stack."""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import manual_20l_assignment as A20
from .bidirectional_round2_assignment import (
    OUT, PHYSICAL_LAYERS, ROUTING_LAYER_IDS, V4, glass_geometry_payload,
    layer_stack_payload)
from ..l3d import validate_l3d as V
from ..v3c4 import lift_cross as LIFT


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate(payload_path, out_dir):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    payload = read_json(payload_path)
    records = {int(r['route_id']): r for r in read_json(V4 / 'routes_1024.json')['routes']}
    routes = {int(r['route_id']): r for r in payload['routes']
              if r.get('status') == 'routed'}
    failed = [r for r in payload['routes'] if r.get('status') != 'routed']
    V.set_routing_layer_ids(range(2, max(ROUTING_LAYER_IDS) + 1))
    from ..v3c4.inputs import ENDPOINTS
    identity = {'available': True, 'error': None, 'planes': {}}
    for plane in ('z1', 'z2'):
        rr = {}
        for rid, record in records.items():
            if record.get('plane') != plane:
                continue
            rr[rid] = dict(route_id=rid,
                           source_endpoint=record['source_endpoint'],
                           target_endpoint=record['target_endpoint'],
                           source_side=record['source_side'],
                           target_side=record['target_side'],
                           source_row=int(record['source_row']),
                           target_row=int(record['target_row']),
                           relation=record['relation'], pair=record['pair'])
        identity['planes'][plane] = {'routes': rr, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity
    report = V.validate_payload(payload, allow_exploratory=True)
    (out_dir / 'validation.json').write_text(
        json.dumps(report, ensure_ascii=False, default=str), encoding='utf-8')
    # crossings
    entries = defaultdict(list)
    for rid, route in routes.items():
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                entries[round(float(part['z_mm']), 9)].append(
                    (rid, [dict(p) for p in part['primitives']]))
    crossings, reports, pairs = LIFT.analyze_planes(entries, log=None,
                                                    compute_positions=False)
    unique = set()
    for value in pairs.values():
        unique |= value
    plane_of = {rid: records[rid]['plane'] for rid in routes}
    by_plane = Counter()
    for a, b in unique:
        by_plane['x'.join(sorted((plane_of.get(a, '?'), plane_of.get(b, '?'))))] += 1
    (out_dir / 'crossings_after.json').write_text(json.dumps(dict(
        count=len(crossings), unique_pair_count=len(unique),
        by_plane_pair=dict(by_plane),
        pair_count_by_height={str(k): v['crossing_pair_count'] for k, v in reports.items()},
        remaining_pairs=sorted(unique)), default=str), encoding='utf-8')
    # layer stats
    assign = {int(r['route_id']): r for r in
              csv.DictReader(open(OUT / 'assignment_1024.csv', encoding='utf-8-sig'))}
    layer_stats = {}
    for layer, z in sorted(PHYSICAL_LAYERS.items()):
        ids = [rid for rid, row in assign.items()
               if str(row['physical_layer']) == str(layer)]
        layer_stats[str(layer)] = dict(
            z_mm=z, assigned=len(ids),
            routed=sum(rid in routes for rid in ids),
            failed=sum(rid not in routes for rid in ids),
            crossings=reports.get(round(z, 9), {}).get('crossing_pair_count'))
    (out_dir / 'per_layer_stats.json').write_text(
        json.dumps(layer_stats, ensure_ascii=False, indent=1), encoding='utf-8')
    counts = report.get('counts') or {}
    final = dict(routed=len(routes), failed=1024 - len(routes),
                 z1_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z1'),
                 z2_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z2'),
                 manual_u_routed=sum(1 for rid in routes
                                     if assign[rid]['logical_kind'] == 'manual_u'),
                 validation_status=report.get('status'),
                 validation_counts=counts,
                 geometry_pass=report.get('geometry_pass'),
                 z2_independent_planes=12,
                 crossings=dict(unique=len(unique), by_plane=dict(by_plane)),
                 min_3d_clearance_mm=(report.get('stats') or {}).get('min_3d_clearance_mm'),
                 total_length_mm=round(sum(float(r.get('length_mm') or 0)
                                           for r in routes.values()), 4),
                 failed_reasons=Counter(str(r.get('reason')) for r in failed))
    (out_dir / 'final_stats.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    print('validation', counts, 'geometry', report.get('geometry_pass'),
          'routed', len(routes), 'z2', final['z2_routed'])
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('payload')
    ap.add_argument('out')
    args = ap.parse_args()
    validate(args.payload, args.out)
