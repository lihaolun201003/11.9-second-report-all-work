# -*- coding: utf-8 -*-
"""Build the complete 1024-channel bidirectional 1 mm experiment.

Phase order
-----------
1. 256 Z1 manual U's, rebuilt for the new physical layers (negative + middle).
2. 255 Z1 opposite-side routes on the two middle planes.
3. 48 Z2 interface routes on z=0.5.
4. 444 high Z2 routes on the three upper planes 0.58/0.66/0.74.

All routes are constructed with the frozen R15 S-curve geometry and checked in
the true-XYZ world.  No route is labelled into a layer: its z coordinates are
built from the physical layer table.
"""
from __future__ import annotations

import csv
import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from . import compare_15L as M
from . import fixed_layer_3d as F3
from . import manual_20l_assignment as A20
from . import manual_u_geometry as UGEOM
from .bidirectional_1mm_layer_assignment import (
    CK, OUT, PHYSICAL_LAYERS, ROUTING_LAYER_IDS, V4,
    Z1_LAYER_MAP, Z2_LAYER_MAP, Z1_MM, Z2_MM, layer_stack_payload,
    layer_z)
from .run_full_campaign import CAMPAIGN_V4
from ..r15 import profile_r15
from ..v3c4 import lift_cross as LIFT


def log(message):
    print(message, flush=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')


def setup():
    M.install_extended_stack_builder()
    profile_r15.apply()


def make_lifter(out_dir, clearance=0.08):
    heights = [float(PHYSICAL_LAYERS[layer]) for layer in ROUTING_LAYER_IDS]
    lifter = LIFT.CrossingLifter(v4_root=V4, out_dir=out_dir, heights=heights,
                                 clearance=float(clearance), log=log)
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    return lifter


def add_existing(lifter, route, primitives, row):
    rid = int(route['route_id'])
    lifter.world.add_route(route)
    lifter.lifted[rid] = route
    lifter.primitives[rid] = [dict(p) for p in primitives]
    lifter.base_routes[rid] = LIFT.flat_route(rid,
                                              'z1' if row == 1 else 'z2',
                                              primitives, row=row)
    return route


def build_z1_u(lifter, phase_b, assignment, fast):
    results = OrderedDict()
    failures = []
    ordered = sorted(phase_b.items(),
                     key=lambda kv: -int(Z1_LAYER_MAP[int(kv[1]['layer'])]))
    for index, (rid_text, row) in enumerate(ordered, 1):
        rid = int(rid_text)
        old_layer = int(row['layer'])
        physical = Z1_LAYER_MAP[old_layer]
        record = read_json(V4 / 'routes_1024.json')
        # record lookup is done by caller via lifter.records
        record = lifter.records[rid]
        geom = None
        primitives = row['primitives']
        route, reason, plan = F3.try_fixed_route(
            lifter, record, 1, primitives, physical, fast=fast, mode='u',
            max_plans=80, window_positions=5, check_plane=True)
        if route is None:
            failures.append(dict(route_id=rid, phase='z1_manual_u',
                                 reason=reason))
        else:
            results[rid] = dict(route=route, primitives=primitives,
                                physical_layer=physical)
            fast.add_route(route)
        if index % 32 == 0:
            log(f'[Z1-U] {index}/256 ok={len(results)} fail={len(failures)}')
    return results, failures


def build_z1_opposite(lifter, checkpoint_routes, checkpoint_prims,
                      assignment, fast):
    results = OrderedDict()
    failures = []
    rows = [rid for rid, route in checkpoint_routes.items()
            if rid not in {int(k) for k in []}]
    # deeper target plane first: the transition from z=0 to a deeper plane
    # must not pass through a shallower plane that was placed first
    ordered_ids = []
    for rid in sorted(checkpoint_routes):
        route = checkpoint_routes[rid]
        layer_seq = route.get('layer_sequence') or []
        if len(layer_seq) >= 2 and int(layer_seq[1]) in (7, 8):
            ordered_ids.append((Z1_LAYER_MAP[int(layer_seq[1])], rid))
    ordered_ids.sort()
    for index, (physical, rid) in enumerate(ordered_ids, 1):
        route = checkpoint_routes[rid]
        layer_seq = route.get('layer_sequence') or []
        logical = int(layer_seq[1])
        if logical not in (7, 8):
            continue
        physical = Z1_LAYER_MAP[logical]
        prims = checkpoint_prims.get(rid)
        if not prims:
            failures.append(dict(route_id=rid, phase='z1_opposite',
                                 reason='no_2d_geometry'))
            continue
        record = lifter.records[rid]
        built, reason, plan = F3.try_fixed_route(
            lifter, record, 1, prims, physical, fast=fast, mode='all',
            max_plans=60, window_positions=5, check_plane=True)
        if built is None:
            failures.append(dict(route_id=rid, phase='z1_opposite',
                                 reason=reason, logical_layer=logical))
        else:
            results[rid] = dict(route=built, primitives=prims,
                                physical_layer=physical)
            fast.add_route(built)
        if index % 32 == 0:
            log(f'[Z1-opposite] scanned={index} ok={len(results)} '
                f'fail={len(failures)}')
    return results, failures


def build_z2_interface(lifter, assignment, fast):
    results = OrderedDict()
    failures = []
    records = lifter.records
    ids = [int(row['route_id']) for row in assignment
           if row['plane'] == 'z2' and row['physical_layer'] is None]
    for rid in sorted(ids):
        record = records[rid]
        prims = record.get('primitives') if record.get('status') == 'routed' else None
        if not prims:
            failures.append(dict(route_id=rid, phase='z2_interface',
                                 reason='no_2d_geometry'))
            continue
        flat = LIFT.flat_route(rid, 'z2', prims, row=2)
        violations = lifter.world.check_route(flat, check_self=False)
        if violations:
            failures.append(dict(route_id=rid, phase='z2_interface',
                                 reason='world:' + str(violations[0].get('kind'))))
            continue
        add_existing(lifter, flat, prims, 2)
        fast.add_route(flat)
        results[rid] = dict(route=flat, primitives=prims,
                            physical_layer=None)
    log(f'[Z2-interface] ok={len(results)} fail={len(failures)}')
    return results, failures


def build_z2_high(lifter, assignment, fast, max_plans=60):
    results = OrderedDict()
    failures = []
    records = lifter.records
    ids = [int(row['route_id']) for row in assignment
           if row['plane'] == 'z2' and row['physical_layer'] is not None]
    ids.sort(key=lambda rid: (
        abs(float(PHYSICAL_LAYERS[next(
            int(row['physical_layer']) for row in assignment
            if int(row['route_id']) == rid)]) - 0.5), rid))
    started = time.perf_counter()
    for index, rid in enumerate(ids, 1):
        row = next(row for row in assignment if int(row['route_id']) == rid)
        physical = int(row['physical_layer'])
        record = records[rid]
        prims = record.get('primitives') if record.get('status') == 'routed' else None
        if not prims:
            failures.append(dict(route_id=rid, phase='z2_high',
                                 reason='no_2d_geometry', physical_layer=physical))
            continue
        # same-side routes may have only one straight window; use the real U
        built, reason, plan = F3.try_fixed_route(
            lifter, record, 2, prims, physical, fast=fast, mode='all',
            max_plans=max_plans, window_positions=5, check_plane=True)
        if built is None:
            failures.append(dict(route_id=rid, phase='z2_high',
                                 reason=reason, physical_layer=physical))
        else:
            results[rid] = dict(route=built, primitives=prims,
                                physical_layer=physical)
            fast.add_route(built)
        if index % 32 == 0:
            log(f'[Z2-high] {index}/{len(ids)} ok={len(results)} '
                f'fail={len(failures)} ({time.perf_counter()-started:.1f}s)')
    return results, failures


def make_payload(lifter, routed, failures, assignment):
    records = lifter.records
    routed_map = {int(rid): info for rid, info in routed.items()}
    payload_routes = []
    for rid in sorted(records):
        record = records[rid]
        if rid in routed_map:
            info = routed_map[rid]
            out = dict(record)
            out.update(info['route'])
            out['status'] = 'routed'
            out['route_id'] = rid
            out['primitives'] = [dict(p) for p in info['primitives']]
            out['physical_layer'] = info['physical_layer']
            out.pop('reason', None)
            row = int(record.get('source_row') or
                      (1 if record.get('plane') == 'z1' else 2))
            if 'source_port' not in out:
                xy = LIFT._endpoint_xy(record['source_endpoint'])
                out['source_port'] = dict(xy=[xy[0], xy[1]],
                                          z_mm=Z1_MM if row == 1 else Z2_MM,
                                          layer_id=1)
            if 'target_port' not in out:
                xy = LIFT._endpoint_xy(record['target_endpoint'])
                out['target_port'] = dict(xy=[xy[0], xy[1]],
                                          z_mm=Z1_MM if row == 1 else Z2_MM,
                                          layer_id=1)
            payload_routes.append(out)
        else:
            out = dict(record)
            out['status'] = 'failed'
            out['reason'] = next(
                (item['reason'] for item in failures
                 if int(item['route_id']) == rid), 'not_attempted')
            out.pop('parts', None)
            out.pop('primitives', None)
            row = int(record.get('source_row') or
                      (1 if record.get('plane') == 'z1' else 2))
            out['source_row'] = row
            out['target_row'] = row
            out['start_z_mm'] = Z1_MM if row == 1 else Z2_MM
            out['end_z_mm'] = out['start_z_mm']
            xy = LIFT._endpoint_xy(record['source_endpoint'])
            out['source_port'] = dict(xy=[xy[0], xy[1]],
                                      z_mm=out['start_z_mm'], layer_id=1)
            xy = LIFT._endpoint_xy(record['target_endpoint'])
            out['target_port'] = dict(xy=[xy[0], xy[1]],
                                      z_mm=out['start_z_mm'], layer_id=1)
            payload_routes.append(out)
    return dict(
        schema='four_side_1024_v2_l3d_routes_v1',
        experiment='BIDIRECTIONAL_1MM_1024_FULL',
        note='bidirectional 1 mm glass; Z1 down/middle, Z2 interface/up',
        topology='V2',
        layer_stack=layer_stack_payload(),
        assignment_summary=read_json(OUT / 'assignment_summary.json')
        if (OUT / 'assignment_summary.json').exists() else {},
        routes=payload_routes)


def main():
    setup()
    out_dir = Path(OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / 'checkpoints'
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # assignment must already exist
    if not (out_dir / 'assignment_1024.csv').exists():
        from .bidirectional_1mm_layer_assignment import write_assignment
        write_assignment(out_dir)
    assignment = list(csv.DictReader(open(out_dir / 'assignment_1024.csv',
                                          encoding='utf-8-sig')))
    for row in assignment:
        if row['physical_layer'] == '':
            row['physical_layer'] = None
        else:
            row['physical_layer'] = int(row['physical_layer'])
    lifter = make_lifter(out_dir)
    fast = F3.FastClearance()
    # Order: local manual U's first (they were all feasible in isolation),
    # then the opposite edges, then high Z2 (without interface routes), and
    # finally the small interface set.  This is order v3.
    ckpt = CK
    ck_routes = {int(k): v for k, v in read_json(ckpt / 'z1/z1_all_routes.json').items()}
    ck_prims = {int(k): v for k, v in read_json(ckpt / 'z1/primitives.json').items()}
    phase_b = read_json(OUT.parent / 'MANUAL_LAYERS_20L_PROTO/phaseB.json')['results']
    manual_ids = {int(k) for k in phase_b}
    z1_u = OrderedDict()
    for rid_text, row in sorted(phase_b.items(), key=lambda kv: int(kv[0])):
        z1_u[int(rid_text)] = row
    u_results, u_failures = build_z1_u(lifter, z1_u, assignment, fast)
    log(f'[Phase Z1-U] routed={len(u_results)}/256 fail={len(u_failures)}')
    ck_opposite_routes = {rid: route for rid, route in ck_routes.items()
                          if rid not in manual_ids}
    ck_opposite_prims = {rid: prims for rid, prims in ck_prims.items()
                         if rid not in manual_ids}
    o_results, o_failures = build_z1_opposite(lifter, ck_opposite_routes,
                                              ck_opposite_prims, assignment, fast)
    log(f'[Phase Z1-opposite] routed={len(o_results)}/256 fail={len(o_failures)}')
    # Z2 interface first (its 48 available 2D paths are all feasible on the
    # empty z=0.5 plane), then fill the upper planes with high Z2 routes.
    zi_results, zi_failures = build_z2_interface(lifter, assignment, fast)
    log(f'[Phase Z2-interface] routed={len(zi_results)}/68 fail={len(zi_failures)}')
    zh_results, zh_failures = build_z2_high(lifter, assignment, fast)
    log(f'[Phase Z2-high] routed={len(zh_results)}/444 fail={len(zh_failures)}')
    routed = OrderedDict()
    for group in (u_results, o_results, zi_results, zh_results):
        routed.update(group)
    failures = u_failures + o_failures + zi_failures + zh_failures
    log(f'[TOTAL] routed={len(routed)}/1024 failures={len(failures)}')
    payload = make_payload(lifter, routed, failures, assignment)
    write_json(out_dir / 'routes_l3d.json', payload)
    write_json(out_dir / 'failed_routes.json', dict(
        total=len(failures), failures=failures))
    # checkpoints
    write_json(ckpt_dir / 'routes.json',
               {str(rid): info['route'] for rid, info in routed.items()})
    write_json(ckpt_dir / 'primitives.json',
               {str(rid): info['primitives'] for rid, info in routed.items()})
    write_json(ckpt_dir / 'build_summary.json', dict(
        routed=len(routed), failed=len(failures),
        stages=dict(z1_u=len(u_results), z1_opposite=len(o_results),
                    z2_interface=len(zi_results), z2_high=len(zh_results)),
        failures=failures))
    for name, group in (('z1_u', u_results), ('z1_opposite', o_results),
                        ('z2_interface', zi_results), ('z2_high', zh_results)):
        write_json(ckpt_dir / f'{name}.json',
                   {str(rid): info['route'] for rid, info in group.items()})
    log(f'[DONE] payload written {out_dir / "routes_l3d.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
