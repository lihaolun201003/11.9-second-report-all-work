# -*- coding: utf-8 -*-
"""Validate corrected 50 um model and revalidate the old 12-layer A/B payloads."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import bidirectional_50um_assignment as A50
from . import glass_1mm_process_rules as RULES
from ..l3d import validate_l3d as V
from ..v3c4 import lift_cross as LIFT


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def set_new_rules():
    V.CLEARANCE_MM = RULES.MIN_3D_CLEARANCE_MM


def identity_payload(records):
    from ..v3c4.inputs import ENDPOINTS
    identity = {'available': True, 'error': None, 'planes': {}}
    for plane in ('z1', 'z2'):
        rr = {}
        for rid, rec in records.items():
            if rec.get('plane') != plane:
                continue
            rr[rid] = dict(route_id=rid,
                           source_endpoint=rec['source_endpoint'],
                           target_endpoint=rec['target_endpoint'],
                           source_side=rec['source_side'],
                           target_side=rec['target_side'],
                           source_row=int(rec['source_row']),
                           target_row=int(rec['target_row']),
                           relation=rec['relation'], pair=rec['pair'])
        identity['planes'][plane] = {'routes': rr, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity


def validate_payload(payload_path, out_dir, layer_max=19, assignment=None):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    set_new_rules()
    payload = read(payload_path)
    records = {int(r['route_id']): r for r in read(
        A50.V4 / 'routes_1024.json')['routes']}
    routes = {int(r['route_id']): r for r in payload['routes']
              if r.get('status') == 'routed'}
    failed = [r for r in payload['routes'] if r.get('status') != 'routed']
    V.set_routing_layer_ids(range(2, layer_max + 1))
    identity_payload(records)
    report = V.validate_payload(payload, allow_exploratory=True)
    (out / 'validation.json').write_text(
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
    (out / 'crossings_after.json').write_text(json.dumps(dict(
        count=len(crossings), unique_pair_count=len(unique),
        by_plane_pair=dict(by_plane),
        pair_count_by_height={str(k): v['crossing_pair_count']
                              for k, v in reports.items()},
        remaining_pairs=sorted(unique)), default=str), encoding='utf-8')
    # per-layer stats if assignment given
    per_layer = {}
    if assignment is not None:
        assign = {int(r['route_id']): r for r in csv.DictReader(
            open(assignment, encoding='utf-8-sig'))}
        for layer in sorted(A50.PHYSICAL_LAYERS):
            ids = [rid for rid, row in assign.items()
                   if str(row['physical_layer']) == str(layer)]
            per_layer[str(layer)] = dict(
                z_mm=A50.PHYSICAL_LAYERS[layer], assigned=len(ids),
                routed=sum(rid in routes for rid in ids),
                failed=sum(rid not in routes for rid in ids),
                crossings=(reports.get(round(A50.PHYSICAL_LAYERS[layer], 9), {})
                           .get('crossing_pair_count')))
        (out / 'per_layer_stats.json').write_text(
            json.dumps(per_layer, ensure_ascii=False, indent=1), encoding='utf-8')
    counts = report.get('counts') or {}
    stats = report.get('stats') or {}
    final = dict(
        routed=len(routes), failed=len(failed),
        z1_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z1'),
        z2_routed=sum(1 for rid in routes if records[rid]['plane'] == 'z2'),
        manual_u_routed=sum(1 for rid in routes
                            if (assignment is None or
                                next((r['logical_kind'] for r in csv.DictReader(
                                    open(assignment, encoding='utf-8-sig'))
                                    if int(r['route_id']) == rid), None) == 'manual_u')),
        validation_status=report.get('status'),
        validation_counts=counts,
        geometry_pass=report.get('geometry_pass'),
        min_3d_clearance_mm=stats.get('min_3d_clearance_mm'),
        total_length_mm=round(sum(float(r.get('length_mm') or 0)
                                  for r in routes.values()), 4),
        total_transitions=sum(int(r.get('n_transitions') or 0)
                              for r in routes.values()),
        crossings=dict(unique=len(unique), by_plane=dict(by_plane)),
        failed_reasons=dict(Counter(str(r.get('reason')) for r in failed)),
        process_rules=RULES.rules_payload(),
    )
    (out / 'final_stats.json').write_text(
        json.dumps(final, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print('validated', len(routes), 'violations', counts.get('violations'),
          'geometry', report.get('geometry_pass'), 'min', stats.get('min_3d_clearance_mm'),
          'crossings', len(unique))
    return report, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('payload')
    ap.add_argument('out')
    ap.add_argument('--layers', type=int, default=19)
    ap.add_argument('--assignment', default=None)
    args = ap.parse_args()
    validate_payload(args.payload, args.out, args.layers, args.assignment)


if __name__ == '__main__':
    main()
