# -*- coding: utf-8 -*-
"""Recover failed routes by new R15 target-layer XY bodies (legal fallback)."""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import OrderedDict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from . import fixed_layer_3d as F3
from . import target_layer_router as TR
from .bidirectional_1mm_layer_assignment import OUT as BASE_OUT, V4
from ..d56.frames import build_frames
from ..v3c4.inputs import ENDPOINTS


def main():
    B.setup()
    out = Path(BASE_OUT).parent / 'BIDIRECTIONAL_1MM_TARGET_FIRST_1024'
    exp = out / 'experiment_C'
    exp.mkdir(parents=True, exist_ok=True)
    assign = {int(r['route_id']): r for r in csv.DictReader(
        open(BASE_OUT / 'assignment_1024.csv', encoding='utf-8-sig'))}
    lifter = B.make_lifter(exp)
    routes = {int(k): v for k, v in json.load(open(
        BASE_OUT / 'checkpoints/routes.json', encoding='utf-8')).items()}
    prims = {int(k): v for k, v in json.load(open(
        BASE_OUT / 'checkpoints/primitives.json', encoding='utf-8')).items()}
    for rid, route in routes.items():
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = prims[rid]
        lifter.base_routes[rid] = route
    failures = json.load(open(BASE_OUT / 'failed_routes.json', encoding='utf-8'))['failures']
    frames = {}
    for rid, record in lifter.records.items():
        try:
            frames.update(build_frames([record], ENDPOINTS))
        except Exception:
            pass
    recovered = []
    still = []
    started = time.perf_counter()
    for index, failure in enumerate(failures, 1):
        rid = int(failure['route_id'])
        record = lifter.records[rid]
        row = 1 if record['plane'] == 'z1' else 2
        assigned = assign[rid]
        if record['plane'] == 'z1':
            choices = [6, 7]
        elif assigned['physical_layer'] == '':
            choices = [None]
        else:
            layer = int(assigned['physical_layer'])
            choices = [layer] + ([8, 9, 10, 11] if layer >= 8 else [])
        accepted = None
        if row == 2 and choices == [None]:
            # interface: try flat R15 L path directly on z=0.5
            if rid in frames:
                for prims2 in list(TR.candidate_paths(frames[rid], radius=15.0,
                                                      count=10)):
                    flat = __import__('four_side_1024.v3c4.lift_cross',
                                      fromlist=['flat_route']).flat_route(
                        rid, 'z2', prims2, row=2)
                    violations = lifter.world.check_route(flat, check_self=False)
                    if not violations:
                        lifter.world.add_route(flat)
                        lifter.lifted[rid] = flat
                        lifter.primitives[rid] = prims2
                        lifter.base_routes[rid] = flat
                        accepted = (flat, None, prims2)
                        break
        elif rid in frames:
            for layer in choices:
                if layer is None:
                    continue
                route, reason = TR.try_route(
                    lifter, record, row, int(layer), frames[rid],
                    max_candidates=10, max_plans=40)
                if route is not None:
                    accepted = (route, layer, None)
                    break
        if accepted:
            route, layer, p2 = accepted
            if layer is not None:
                assign[rid]['physical_layer'] = str(layer)
            recovered.append(dict(route_id=rid, old_reason=failure.get('reason'),
                                  new_layer=layer))
        else:
            still.append(failure)
        if index % 10 == 0:
            print(f'[C] {index}/{len(failures)} recovered={len(recovered)} '
                  f'still={len(still)} ({time.perf_counter()-started:.0f}s)',
                  flush=True)
    print(f'[C] recovered={len(recovered)} still={len(still)}', flush=True)
    routed = OrderedDict()
    for rid in routes:
        routed[rid] = dict(route=routes[rid], primitives=prims[rid],
                           physical_layer=(None if assign[rid]['physical_layer'] == ''
                                           else int(assign[rid]['physical_layer'])))
    for item in recovered:
        rid = item['route_id']
        routed[rid] = dict(route=lifter.lifted[rid], primitives=lifter.primitives[rid],
                           physical_layer=item['new_layer'])
    # ensure assignment physical layers updated for payload
    assignment_rows = list(csv.DictReader(open(BASE_OUT / 'assignment_1024.csv',
                                                encoding='utf-8-sig')))
    for row in assignment_rows:
        rid = int(row['route_id'])
        if row['physical_layer'] == '':
            row['physical_layer'] = None
        else:
            row['physical_layer'] = int(row['physical_layer'])
    import shutil
    shutil.copy2(BASE_OUT / 'assignment_summary.json', exp / 'assignment_summary.json')
    payload = B.make_payload(lifter, routed, still, assignment_rows)
    (exp / 'routes_l3d.json').write_text(json.dumps(payload, ensure_ascii=False,
                                                    default=str), encoding='utf-8')
    (exp / 'failed_routes.json').write_text(json.dumps(
        dict(total=len(still), failures=still), ensure_ascii=False,
        default=str, indent=1), encoding='utf-8')
    (exp / 'recover_summary.json').write_text(json.dumps(
        dict(recovered=len(recovered), still=len(still),
             recovered_routes=recovered), ensure_ascii=False, indent=1,
        default=str), encoding='utf-8')
    (exp / 'checkpoints').mkdir(exist_ok=True)
    (exp / 'checkpoints/routes.json').write_text(json.dumps(
        {str(r): info['route'] for r, info in routed.items()},
        ensure_ascii=False, default=str), encoding='utf-8')
    print('[C] saved', exp, flush=True)


if __name__ == '__main__':
    main()
