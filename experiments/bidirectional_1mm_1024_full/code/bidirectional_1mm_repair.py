# -*- coding: utf-8 -*-
"""Phase-5 repair: retry failed routes on alternative physical layers.

The assignment rule is allowed to pick a legal candidate physical layer from
the same side/group.  A route keeps its original endpoints, topology, R15 and
clearance; only the physical target layer may change if the original layer is
blocked.  Every accepted route goes through the strict 3D world check.
"""
from __future__ import annotations

import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from . import fixed_layer_3d as F3
from . import bidirectional_1mm_builder as B
from .bidirectional_1mm_layer_assignment import OUT, ROUTING_LAYER_IDS


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    path = Path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                               default=str), encoding='utf-8')


def main():
    B.setup()
    out = Path(OUT)
    ckpt = out / 'checkpoints'
    summary = read_json(ckpt / 'build_summary.json')
    routes = {int(k): v for k, v in read_json(ckpt / 'routes.json').items()}
    prims = {int(k): v for k, v in read_json(ckpt / 'primitives.json').items()}
    assignment = list(__import__('csv').DictReader(open(
        out / 'assignment_1024.csv', encoding='utf-8-sig')))
    for row in assignment:
        row['physical_layer'] = (None if row['physical_layer'] == ''
                                 else int(row['physical_layer']))
    assign_by_id = {int(row['route_id']): row for row in assignment}
    lifter = B.make_lifter(out)
    fast = F3.FastClearance()
    for rid, route in routes.items():
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = [dict(p) for p in prims[rid]]
        lifter.base_routes[rid] = route
        fast.add_route(route)
    failures = list(summary.get('failures') or [])
    repaired = []
    still = []
    started = time.perf_counter()
    for index, failure in enumerate(failures, 1):
        rid = int(failure['route_id'])
        phase = failure.get('phase')
        if phase not in ('z1_opposite', 'z2_high'):
            still.append(failure)
            continue
        record = lifter.records[rid]
        prims_route = record.get('primitives')
        if not prims_route:
            still.append(failure)
            continue
        current = (assign_by_id[rid]['physical_layer']
                   if assign_by_id[rid]['physical_layer'] is not None else 0)
        if phase == 'z1_opposite':
            layer_choices = [6, 7]
        else:
            layer_choices = [8, 9, 10, 11]
        # try the original physical layer first, then alternatives
        ordered = [current] + [layer for layer in layer_choices
                               if layer != current]
        accepted = None
        for layer in ordered:
            if layer is None or int(layer) not in ROUTING_LAYER_IDS:
                continue
            built, reason, plan = F3.try_fixed_route(
                lifter, record, 1 if phase == 'z1_opposite' else 2,
                prims_route, int(layer), fast=fast, mode='all',
                max_plans=40, window_positions=5, check_plane=True)
            if built is not None:
                accepted = (built, layer)
                fast.add_route(built)
                break
        if accepted is None:
            still.append(failure)
            continue
        route, layer = accepted
        routes[rid] = route
        prims[rid] = [dict(p) for p in prims_route]
        assign_by_id[rid]['physical_layer'] = int(layer)
        repaired.append(dict(route_id=rid, phase=phase, new_layer=int(layer)))
        if index % 20 == 0:
            print(f'[repair] {index}/{len(failures)} repaired={len(repaired)} '
                  f'still={len(still)} ({time.perf_counter()-started:.0f}s)',
                  flush=True)
    print(f'[repair] repaired={len(repaired)} still={len(still)}', flush=True)
    routed = OrderedDict()
    for rid, route in routes.items():
        routed[rid] = dict(route=route, primitives=prims[rid],
                           physical_layer=assign_by_id[rid]['physical_layer'])
    payload = B.make_payload(lifter, routed, still, assignment)
    write_json(out / 'routes_l3d.json', payload)
    write_json(out / 'failed_routes.json', dict(total=len(still), failures=still))
    write_json(ckpt / 'routes.json', {str(rid): route for rid, route in routes.items()})
    write_json(ckpt / 'primitives.json', {str(rid): prims[rid] for rid in prims})
    write_json(ckpt / 'build_summary.json', dict(
        routed=len(routes), failed=len(still),
        stages=summary.get('stages'), failures=still))
    write_json(out / 'repair_summary.json', dict(
        repaired=len(repaired), still=len(still),
        repaired_routes=repaired,
        elapsed=time.perf_counter()-started))
    print('[repair] saved', out / 'routes_l3d.json', flush=True)


if __name__ == '__main__':
    main()
