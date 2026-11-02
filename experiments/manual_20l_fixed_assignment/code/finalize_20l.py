# -*- coding: utf-8 -*-
"""Assemble, validate and summarise the complete L1-L20 manual-assignment run.

This is the production entry point for the final artifacts:

    python -m four_side_1024.manual_c4_adapt.finalize_20l \
        --z1-dir outputs/.../MANUAL_LAYERS_20L_PROTO_C5R4 \
        --z2-dir outputs/.../MANUAL_LAYERS_20L_PROTO_Z2H \
        --out-dir outputs/.../MANUAL_20L_FIXED_ASSIGNMENT_FULL
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from . import manual_20l_assignment as A
from ..v3c4 import lift_cross as LIFT
from ..l3d import validate_l3d as V

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = (ROOT / 'outputs/manual_c4_new_connectivity'
                    / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected')
DEFAULT_OUT = (ROOT / 'outputs/manual_c4_new_connectivity'
               / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL')


def log(message):
    print(message, flush=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')


def load_routes(directory):
    directory = Path(directory)
    routes = read_json(directory / 'z1_all_routes.json') if (
        directory / 'z1_all_routes.json').exists() else read_json(
        directory / 'routes_20l_partial.json')
    prims = read_json(directory / 'primitives.json') if (
        directory / 'primitives.json').exists() else read_json(
        directory / 'primitives_20l_partial.json')
    return ({int(k): v for k, v in routes.items()},
            {int(k): v for k, v in prims.items()})


def route_high_layer(route):
    for part in route.get('parts') or []:
        if part['kind'] == 'flat' and int(part['layer_id']) != 1:
            return int(part['layer_id'])
    return None


def baseline_records(path):
    raw = read_json(Path(path) / 'routes_1024.json')
    return {int(record['route_id']): record for record in raw['routes']}, raw


def failed_route_record(record, reason):
    out = dict(record)
    out['status'] = 'failed'
    out['reason'] = reason
    out.pop('primitives', None)
    out.pop('parts', None)
    row = int(record.get('source_row') or
              (1 if record.get('plane') == 'z1' else 2))
    source_xy = LIFT._endpoint_xy(record['source_endpoint'])
    target_xy = LIFT._endpoint_xy(record['target_endpoint'])
    out['source_row'] = row
    out['target_row'] = row
    out['start_z_mm'] = 0.0 if row == 1 else 0.5
    out['end_z_mm'] = out['start_z_mm']
    out['source_port'] = dict(xy=[source_xy[0], source_xy[1]],
                              z_mm=out['start_z_mm'], layer_id=1)
    out['target_port'] = dict(xy=[target_xy[0], target_xy[1]],
                              z_mm=out['start_z_mm'], layer_id=1)
    return out


def routed_route_record(record, route):
    out = dict(record)
    out.update(route)
    out['status'] = 'routed'
    out['route_id'] = int(record['route_id'])
    out.pop('reason', None)
    return out


def crossing_breakdown(unique_pairs, plane_of, group_of):
    by_plane = Counter()
    by_bundle = Counter()
    for first, second in unique_pairs:
        planes = tuple(sorted((plane_of.get(first, '?'),
                               plane_of.get(second, '?'))))
        by_plane['x'.join(planes)] += 1
        if (group_of.get(first) is not None
                and group_of.get(first) == group_of.get(second)):
            by_bundle['intra_bundle'] += 1
        else:
            by_bundle['inter_bundle'] += 1
    return dict(by_plane=dict(by_plane), by_bundle=dict(by_bundle))


def build_and_validate(z1_dir, z2_dir, out_dir):
    started = time.perf_counter()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline, _raw = baseline_records(DEFAULT_BASELINE)
    z1_routes, z1_prims = load_routes(z1_dir)
    z2_routes, z2_prims = load_routes(z2_dir)
    log(f'loaded Z1={len(z1_routes)} Z2={len(z2_routes)} routes')
    # assignment
    payload2d = read_json(DEFAULT_BASELINE / 'routes_1024.json')
    manual = A.load_manual_u_mapping()
    rows, assignment_summary = A.build_assignment(payload2d, manual)
    A.write_assignment(out_dir, rows, assignment_summary, payload2d)
    assignment = {row['route_id']: row for row in rows}
    z2_failures = {}
    z2_summary_path = Path(z2_dir) / 'z2_build_summary.json'
    if z2_summary_path.exists():
        z2_summary = read_json(z2_summary_path)
        for item in z2_summary.get('failures') or []:
            z2_failures[int(item['route_id'])] = item.get('reason')
    # assemble all 1024 records
    all_routes = {}
    all_prims = {}
    for rid in sorted(baseline):
        record = baseline[rid]
        if rid in z1_routes:
            all_routes[rid] = z1_routes[rid]
            all_prims[rid] = z1_prims[rid]
        elif rid in z2_routes:
            all_routes[rid] = z2_routes[rid]
            all_prims[rid] = z2_prims[rid]
    log(f'assembled routed routes: {len(all_routes)}')
    records = []
    failed = []
    for rid in sorted(baseline):
        record = baseline[rid]
        if rid in all_routes:
            out = routed_route_record(record, all_routes[rid])
            out['primitives'] = [dict(primitive)
                                 for primitive in all_prims[rid]]
        else:
            reason = z2_failures.get(rid)
            if reason is None:
                if rid in z1_routes:
                    reason = 'z1_not_built'
                elif rid in z2_routes:
                    reason = 'z2_not_built'
                elif record['plane'] == 'z1':
                    reason = 'z1_fixed_layer_unroutable'
                else:
                    reason = ('no_2d_geometry' if not record.get('primitives')
                              else 'z2_fixed_layer_unroutable')
            out = failed_route_record(record, reason)
            failed.append(dict(route_id=rid, plane=record['plane'],
                               relation=record.get('relation'),
                               assigned_layer=assignment[rid]['target_layer'],
                               reason=reason))
        records.append(out)
    routes_payload = dict(
        schema='four_side_1024_v2_l3d_routes_v1',
        experiment='MANUAL_20L_FIXED_ASSIGNMENT_FULL',
        note=('Round-3 deterministic L1-L20 assignment. Z1: 256 manual U on '
              'L2-L5, 128 NS on L7, 128 EW on L8. Z2: source-priority '
              'connector groups on L9-L20; unassigned routes at z=0.5.'),
        topology='V2',
        layer_stack=A.layer_stack_payload(),
        assignment_summary=assignment_summary,
        routes=records,
    )
    write_json(out_dir / 'routes_l3d.json', routes_payload)
    write_json(out_dir / 'failed_routes.json', dict(
        schema='manual_20l_failed_routes_v1',
        total_failed=len(failed), failed=failed))
    # ---- repository validator ------------------------------------------
    V.set_routing_layer_ids(range(2, 21))
    from ..v3c4.inputs import ENDPOINTS
    identity = {'available': True, 'error': None, 'planes': {}}
    for plane in ('z1', 'z2'):
        rr = {}
        for rid, record in baseline.items():
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
    log('running repository 3D validator ...')
    validation = V.validate_payload(routes_payload, allow_exploratory=True)
    write_json(out_dir / 'validation.json', validation)
    log(f'validator: status={validation.get("status")} '
        f'counts={dict(validation.get("counts") or {})}')
    # ---- crossings -------------------------------------------------------
    entries = defaultdict(list)
    for rid, route in all_routes.items():
        for part in route.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            entries[round(float(part['z_mm']), 9)].append(
                (rid, [dict(primitive) for primitive in part['primitives']]))
    crossings, reports, pairs = LIFT.analyze_planes(
        entries, log=log, compute_positions=False)
    unique_pairs = set()
    for plane_pairs in pairs.values():
        unique_pairs |= plane_pairs
    plane_of = {rid: baseline[rid]['plane'] for rid in all_routes}
    group_of = {}
    for group in payload2d.get('rotation_groups') or []:
        for rid in group['route_ids']:
            group_of[int(rid)] = int(group['group_id'])
    breakdown = crossing_breakdown(unique_pairs, plane_of, group_of)
    after_records = [dict(z=float(value[0]), route_a=int(value[1]),
                          route_b=int(value[2]), x=float(value[3]),
                          y=float(value[4]), angle_deg=float(value[7]))
                     for value in crossings]
    crossing_payload = dict(
        count=len(after_records), unique_pair_count=len(unique_pairs),
        pair_count_by_height={str(key): value['crossing_pair_count']
                              for key, value in reports.items()},
        point_count_by_height={str(key): value['crossing_count']
                               for key, value in reports.items()},
        breakdown=breakdown,
        remaining_pairs=sorted(unique_pairs),
        crossings=after_records,
    )
    write_json(out_dir / 'crossings_after.json', crossing_payload, indent=None)
    # ---- per-layer statistics -------------------------------------------
    layer_route_ids = defaultdict(list)
    for row in rows:
        layer = row['target_layer']
        key = 'interface_z2' if (layer is None and row['plane'] == 'z2') else (
            'interface_z1' if layer is None else str(layer))
        layer_route_ids[key].append(row['route_id'])
    layer_stats = OrderedDict()
    routed_layer = {}
    for rid, route in all_routes.items():
        routed_layer[rid] = route_high_layer(route)
    for key in ['1', 'interface_z2'] + [str(layer) for layer in range(2, 21)]:
        ids = layer_route_ids.get(key, [])
        succeeded = [rid for rid in ids if rid in all_routes]
        z_mm = (0.0 if key == 'interface_z1' else
                0.5 if key == 'interface_z2' else
                A.layer_z(int(key)) if key != '1' else 0.0)
        layer_stats[key] = dict(
            layer=None if key == 'interface_z2' else (
                1 if key == '1' else int(key)),
            assigned=len(ids), routed=len(succeeded),
            failed=len(ids) - len(succeeded),
            z_mm=z_mm,
            target_routes=[rid for rid in ids],
            routed_routes=succeeded,
            failed_routes=[rid for rid in ids if rid not in all_routes],
            transitions=sum(1 for rid in succeeded
                            if (all_routes[rid].get('n_transitions') or 0) > 0),
            crossings=reports.get(round(z_mm, 9), {}).get('crossing_pair_count'),
        )
    write_json(out_dir / 'layer_stats.json', layer_stats)
    # ---- final stats -----------------------------------------------------
    z1_routed = sum(1 for rid in all_routes if baseline[rid]['plane'] == 'z1')
    z2_routed = sum(1 for rid in all_routes if baseline[rid]['plane'] == 'z2')
    total_length = sum(float(all_routes[rid].get('length_mm') or 0)
                       for rid in all_routes)
    transitions = sum(int(all_routes[rid].get('n_transitions') or 0)
                      for rid in all_routes)
    counts = dict(validation.get('counts') or {})
    stats = validation.get('stats') or {}
    final_stats = dict(
        schema='manual_20l_final_stats_v1',
        total_connections=1024,
        routed=len(all_routes),
        failed=1024 - len(all_routes),
        z1_routed=z1_routed,
        z1_total=512,
        z2_routed=z2_routed,
        z2_total=512,
        routed_by_plane=dict(Counter(baseline[rid]['plane']
                                     for rid in all_routes)),
        assignment=assignment_summary,
        by_layer=layer_stats,
        crossings=dict(total_unique_pairs=len(unique_pairs),
                       total_crossing_points=len(after_records),
                       by_plane_pair=breakdown['by_plane'],
                       by_bundle=breakdown['by_bundle'],
                       pair_count_by_height=crossing_payload[
                           'pair_count_by_height'],
                       point_count_by_height=crossing_payload[
                           'point_count_by_height']),
        total_length_mm=round(total_length, 4),
        total_transitions=transitions,
        min_curvature_radius_mm=min(
            [float(value) for value in
             (stats.get('flat_arc_radius_values') or [])] + [15.0]),
        validation_status=validation.get('status'),
        validation_counts=counts,
        validation_geometry_pass=validation.get('geometry_pass'),
        validation_exploratory_pass=validation.get('exploratory_pass'),
        min_3d_clearance_mm=stats.get('min_3d_clearance_mm'),
        elapsed_seconds=round(time.perf_counter() - started, 2),
    )
    write_json(out_dir / 'final_stats.json', final_stats)
    # route decisions CSV
    with (out_dir / 'route_decisions.csv').open('w', newline='',
                                                encoding='utf-8-sig') as fh:
        fields = ['route_id', 'plane', 'relation', 'status', 'assigned_layer',
                  'actual_layer', 'n_transitions', 'length_mm', 'reason']
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rid in sorted(baseline):
            route = all_routes.get(rid)
            writer.writerow(dict(
                route_id=rid, plane=baseline[rid]['plane'],
                relation=baseline[rid].get('relation'),
                status='routed' if route else 'failed',
                assigned_layer=assignment[rid]['target_layer'],
                actual_layer=routed_layer.get(rid),
                n_transitions=(route or {}).get('n_transitions'),
                length_mm=(route or {}).get('length_mm'),
                reason=None if route else next(
                    (item['reason'] for item in failed
                     if item['route_id'] == rid), None)))
    log(f'DONE routed={len(all_routes)}/1024 z1={z1_routed}/512 '
        f'z2={z2_routed}/512 crossings={len(unique_pairs)} '
        f'validation={validation.get("status")}')
    return final_stats


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--z1-dir', default=str(
        ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_C5R4'))
    parser.add_argument('--z2-dir', default=str(
        ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO_Z2H'))
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    stats = build_and_validate(args.z1_dir, args.z2_dir, args.out_dir)
    print(json.dumps({key: stats[key] for key in
                      ('routed', 'failed', 'z1_routed', 'z2_routed',
                       'validation_status', 'total_transitions')},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
