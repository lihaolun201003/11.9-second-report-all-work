# -*- coding: utf-8 -*-
"""Validate experiment C (legal 4-Z2-plane stack, target-layer recoveries)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from .bidirectional_1mm_layer_assignment import OUT as BASE_OUT, V4
from ..l3d import validate_l3d as V
from ..v3c4 import lift_cross as LIFT


def main():
    out = Path(BASE_OUT).parent / 'BIDIRECTIONAL_1MM_TARGET_FIRST_1024/experiment_C'
    payload = json.load(open(out / 'routes_l3d.json', encoding='utf-8'))
    records = {int(r['route_id']): r for r in json.load(
        open(V4 / 'routes_1024.json', encoding='utf-8'))['routes']}
    routes = {int(r['route_id']): r for r in payload['routes']
              if r.get('status') == 'routed'}
    failed = [r for r in payload['routes'] if r.get('status') != 'routed']
    V.set_routing_layer_ids(range(2, 12))
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
    (out / 'validation.json').write_text(
        json.dumps(report, ensure_ascii=False, default=str), encoding='utf-8')
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
    by_plane = defaultdict(int)
    for a, b in unique:
        by_plane['x'.join(sorted((plane_of.get(a, '?'), plane_of.get(b, '?'))))] += 1
    (out / 'crossings_after.json').write_text(json.dumps(dict(
        count=len(crossings), unique_pair_count=len(unique),
        by_plane_pair=dict(by_plane),
        pair_count_by_height={str(k): v['crossing_pair_count'] for k, v in reports.items()},
        remaining_pairs=sorted(unique)), default=str), encoding='utf-8')
    counts = report.get('counts') or {}
    final = dict(routed=len(routes), failed=len(failed),
                 z1_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z1'),
                 z2_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z2'),
                 manual_u_routed=sum(1 for rid in routes
                                     if json.load(open(BASE_OUT / 'assignment_1024.csv')) if False) if False else None,
                 validation_status=report.get('status'),
                 validation_counts=counts,
                 geometry_pass=report.get('geometry_pass'),
                 crossings=dict(unique=len(unique), by_plane=dict(by_plane)),
                 min_3d_clearance_mm=(report.get('stats') or {}).get('min_3d_clearance_mm'),
                 total_length_mm=round(sum(float(r.get('length_mm') or 0)
                                           for r in routes.values()), 4),
                 failed_reasons=dict())
    # manual U count / assignment from base
    import csv
    assign = {int(r['route_id']): r for r in csv.DictReader(
        open(BASE_OUT / 'assignment_1024.csv', encoding='utf-8-sig'))}
    final['manual_u_routed'] = sum(1 for rid in routes
                                   if assign[rid].get('logical_kind') == 'manual_u')
    (out / 'final_stats.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    print('C validation', counts, 'geometry', report.get('geometry_pass'),
          'routed', len(routes), 'z1', final['z1_routed'],
          'z2', final['z2_routed'])
    print('crossings', len(unique), dict(by_plane))


if __name__ == '__main__':
    main()
