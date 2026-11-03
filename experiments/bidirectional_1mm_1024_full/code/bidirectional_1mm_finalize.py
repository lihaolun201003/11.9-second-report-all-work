# -*- coding: utf-8 -*-
"""Validate and summarize the bidirectional 1 mm 1024-channel run."""
from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from . import manual_20l_assignment as A20
from .bidirectional_1mm_layer_assignment import (
    OUT, PHYSICAL_LAYERS, ROUTING_LAYER_IDS, Z1_MM, Z2_MM, V4,
    glass_geometry_payload, layer_stack_payload)
from ..l3d import validate_l3d as V
from ..v3c4 import lift_cross as LIFT


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')


def layer_of(route):
    for part in route.get('parts') or []:
        if part['kind'] == 'flat' and int(part['layer_id']) != 1:
            return int(part['layer_id']), float(part['z_mm'])
    return None, None


def main():
    out = Path(OUT)
    payload = read_json(out / 'routes_l3d.json')
    records = {int(r['route_id']): r for r in read_json(V4 / 'routes_1024.json')['routes']}
    routes = {int(r['route_id']): r for r in payload['routes']
              if r.get('status') == 'routed'}
    failed = [r for r in payload['routes'] if r.get('status') != 'routed']
    print('routed', len(routes), 'failed', len(failed))
    # update physical assignment for repaired routes
    assign_rows = list(csv.DictReader(open(out / 'assignment_1024.csv',
                                          encoding='utf-8-sig')))
    assign = {int(row['route_id']): row for row in assign_rows}
    for rid, route in routes.items():
        layer, z_mm = layer_of(route)
        row = assign[rid]
        if layer is None:
            row['physical_layer'] = ''
            row['target_z_mm'] = '0.5'
            row['region'] = 'Z2_INTERFACE'
            row['direction'] = 'flat'
        else:
            row['physical_layer'] = str(layer)
            row['target_z_mm'] = str(z_mm)
            row['region'] = ('Z1_DOWN' if layer in (2, 3) else
                             'Z1_MIDDLE' if layer in (4, 5, 6, 7) else
                             'Z2_MIDDLE' if layer == 8 else 'Z2_UP')
            row['direction'] = ('down' if z_mm < 0 else
                                'up' if z_mm > 0 else 'flat')
    fields = list(assign_rows[0])
    with (out / 'assignment_1024.csv').open('w', newline='',
                                            encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(assign_rows)
    # validation
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
    started = time.perf_counter()
    report = V.validate_payload(payload, allow_exploratory=True)
    write_json(out / 'validation.json', report)
    print('validation', report.get('status'), report.get('counts'),
          'geometry_pass', report.get('geometry_pass'))
    # crossings
    entries = defaultdict(list)
    for rid, route in routes.items():
        for part in route.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            entries[round(float(part['z_mm']), 9)].append(
                (rid, [dict(p) for p in part['primitives']]))
    crossings, reports, pairs = LIFT.analyze_planes(entries, log=print,
                                                    compute_positions=False)
    unique_pairs = set()
    for value in pairs.values():
        unique_pairs |= value
    plane_of = {rid: records[rid]['plane'] for rid in routes}
    by_plane = Counter()
    for first, second in unique_pairs:
        by_plane['x'.join(sorted((plane_of.get(first, '?'),
                                   plane_of.get(second, '?'))))] += 1
    crossing_payload = dict(
        count=len(crossings), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(k): v['crossing_pair_count']
                              for k, v in reports.items()},
        point_count_by_height={str(k): v['crossing_count']
                               for k, v in reports.items()},
        by_plane_pair=dict(by_plane),
        remaining_pairs=sorted(unique_pairs),
        crossings=[dict(z=float(v[0]), route_a=int(v[1]), route_b=int(v[2]),
                        x=float(v[3]), y=float(v[4]), angle_deg=float(v[7]))
                   for v in crossings])
    write_json(out / 'crossings_after.json', crossing_payload, indent=None)
    # layer stats
    layer_stats = OrderedDict()
    for layer in sorted(PHYSICAL_LAYERS):
        ids = [rid for rid, row in assign.items()
               if str(row['physical_layer']) == str(layer)]
        routed_ids = [rid for rid in ids if rid in routes]
        z = PHYSICAL_LAYERS[layer]
        layer_stats[str(layer)] = dict(
            layer=layer, z_mm=float(z),
            region=('Z1_DOWN' if z < 0 else 'Z1_MIDDLE' if layer <= 7
                    else 'Z2_MIDDLE' if layer == 8 else 'Z2_UP'),
            assigned=len(ids), routed=len(routed_ids),
            failed=len(ids) - len(routed_ids),
            transitions=sum(int(routes[rid].get('n_transitions') or 0)
                            for rid in routed_ids),
            crossings=reports.get(round(z, 9), {}).get('crossing_pair_count'))
    interface_ids = [rid for rid, row in assign.items()
                     if str(row['physical_layer']) == '']
    layer_stats['interface_z2'] = dict(
        layer=None, z_mm=0.5, region='Z2_INTERFACE',
        assigned=len(interface_ids),
        routed=sum(1 for rid in interface_ids if rid in routes),
        failed=sum(1 for rid in interface_ids if rid not in routes),
        transitions=0,
        crossings=reports.get(0.5, {}).get('crossing_pair_count'))
    write_json(out / 'per_layer_stats.json', layer_stats)
    # final stats
    z1_routed = sum(1 for rid in routes if records[rid]['plane'] == 'z1')
    z2_routed = sum(1 for rid in routes if records[rid]['plane'] == 'z2')
    u_count = sum(1 for rid in routes
                  if assign[rid].get('logical_kind') == 'manual_u')
    region_counts = Counter(row['region'] for row in assign.values())
    routed_region = Counter(assign[rid]['region'] for rid in routes)
    total_len = sum(float(routes[rid].get('length_mm') or 0) for rid in routes)
    transitions = sum(int(routes[rid].get('n_transitions') or 0)
                      for rid in routes)
    counts = dict(report.get('counts') or {})
    stats = report.get('stats') or {}
    z_values = [float(p['z_mm']) for route in routes.values()
                for p in route.get('parts') or [] if p['kind'] == 'flat']
    final = dict(
        schema='bidirectional_1mm_final_stats_v1',
        total=1024, routed=len(routes), failed=1024 - len(routes),
        z1_routed=z1_routed, z1_total=512,
        z2_routed=z2_routed, z2_total=512,
        manual_u_routed=u_count, manual_u_total=256,
        routed_by_region=dict(routed_region),
        assigned_by_region=dict(region_counts),
        physical_layers=len(PHYSICAL_LAYERS),
        glass=glass_geometry_payload(),
        min_routed_z_mm=min(z_values) if z_values else None,
        max_routed_z_mm=max(z_values) if z_values else None,
        z1_down_routes=sum(1 for rid in routes
                           if assign[rid]['region'] == 'Z1_DOWN'),
        z1_middle_routes=sum(1 for rid in routes
                             if assign[rid]['region'] == 'Z1_MIDDLE'),
        z2_middle_routes=sum(1 for rid in routes
                             if assign[rid]['region'] == 'Z2_MIDDLE'),
        z2_up_routes=sum(1 for rid in routes
                         if assign[rid]['region'] == 'Z2_UP'),
        interface_routes=sum(1 for rid in routes
                             if assign[rid]['region'] == 'Z2_INTERFACE'),
        crossings=dict(total_unique_pairs=len(unique_pairs),
                       total_points=len(crossings),
                       by_plane_pair=dict(by_plane),
                       by_height={str(k): v['crossing_pair_count']
                                  for k, v in reports.items()}),
        total_length_mm=round(total_len, 4),
        total_transitions=transitions,
        min_curvature_radius_mm=min(
            [float(v) for v in (stats.get('flat_arc_radius_values') or [])]
            + [15.0]),
        min_3d_clearance_mm=stats.get('min_3d_clearance_mm'),
        validation_status=report.get('status'),
        validation_counts=counts,
        validation_geometry_pass=report.get('geometry_pass'),
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )
    write_json(out / 'final_stats.json', final)
    # failed summary and decisions
    write_json(out / 'failed_routes.json', dict(
        total=len(failed),
        failures=[dict(route_id=int(r['route_id']), plane=records[int(r['route_id'])]['plane'],
                       reason=r.get('reason'), physical_layer=r.get('physical_layer'))
                  for r in failed]))
    with (out / 'route_decisions.csv').open('w', newline='',
                                            encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            'route_id', 'plane', 'status', 'physical_layer', 'z_mm', 'region',
            'direction', 'n_transitions', 'length_mm', 'reason'])
        writer.writeheader()
        for rid in sorted(records):
            route = routes.get(rid)
            row = assign[rid]
            writer.writerow(dict(
                route_id=rid, plane=records[rid]['plane'],
                status='routed' if route else 'failed',
                physical_layer=row['physical_layer'],
                z_mm=row['target_z_mm'], region=row['region'],
                direction=row['direction'],
                n_transitions=(route or {}).get('n_transitions'),
                length_mm=(route or {}).get('length_mm'),
                reason=None if route else next(
                    (r.get('reason') for r in failed
                     if int(r['route_id']) == rid), None)))
    print(json.dumps({k: final[k] for k in
                      ('routed', 'failed', 'z1_routed', 'z2_routed',
                       'manual_u_routed', 'validation_status',
                       'validation_counts', 'min_routed_z_mm',
                       'max_routed_z_mm')}, ensure_ascii=False, indent=1))
    print('crossings', len(unique_pairs), 'by_plane', dict(by_plane))
    return final


if __name__ == '__main__':
    main()
