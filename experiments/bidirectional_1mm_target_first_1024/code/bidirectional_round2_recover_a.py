# -*- coding: utf-8 -*-
"""Experiment B: 12-Z2-plane allocation + target-layer R15 reroute."""
from __future__ import annotations

import csv
import json
import time
from collections import OrderedDict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from . import bidirectional_round2_assignment as R2
from . import target_layer_router as TR
from .bidirectional_1mm_layer_assignment import V4
from ..d56.frames import build_frames
from ..v3c4 import lift_cross as LIFT
from ..v3c4.inputs import ENDPOINTS


def main():
    B.setup()
    B.OUT = R2.OUT
    B.PHYSICAL_LAYERS = R2.PHYSICAL_LAYERS
    B.ROUTING_LAYER_IDS = R2.ROUTING_LAYER_IDS
    B.Z1_LAYER_MAP = R2.Z1_LAYER_MAP
    B.Z2_LAYER_MAP = R2.Z2_LAYER_MAP
    B.layer_stack_payload = R2.layer_stack_payload
    a_dir = Path(R2.OUT) / 'experiment_A'
    exp = Path(R2.OUT) / 'experiment_B'
    exp.mkdir(parents=True, exist_ok=True)
    assign = {int(r['route_id']): r for r in csv.DictReader(
        open(R2.OUT / 'assignment_1024.csv', encoding='utf-8-sig'))}
    lifter = B.make_lifter(exp)
    routes = {int(k): v for k, v in json.load(open(
        a_dir / 'checkpoints/routes.json', encoding='utf-8')).items()}
    prims = {int(k): v for k, v in json.load(open(
        a_dir / 'checkpoints/primitives.json', encoding='utf-8')).items()}
    for rid, route in routes.items():
        lifter.world.add_route(route)
        lifter.lifted[rid] = route
        lifter.primitives[rid] = prims[rid]
        lifter.base_routes[rid] = route
    failures = json.load(open(a_dir / 'failed_routes.json', encoding='utf-8'))['failures']
    frames = {}
    for rid, record in lifter.records.items():
        try:
            frames.update(build_frames([record], ENDPOINTS))
        except Exception:
            pass
    recovered, still = [], []
    started = time.perf_counter()
    for index, failure in enumerate(failures, 1):
        rid = int(failure['route_id'])
        record = lifter.records[rid]
        row = 1 if record['plane'] == 'z1' else 2
        if record['plane'] == 'z1':
            choices = [6, 7]
        elif assign[rid]['physical_layer'] == '':
            choices = [None]
        else:
            base = int(assign[rid]['physical_layer'])
            choices = [base] + [x for x in range(8, 20) if x != base]
        accepted = None
        if row == 2 and choices == [None]:
            if rid in frames:
                for p2 in TR.candidate_paths(frames[rid], radius=15.0, count=8):
                    flat = LIFT.flat_route(rid, 'z2', p2, row=2)
                    if not lifter.world.check_route(flat, check_self=False):
                        lifter.world.add_route(flat)
                        lifter.lifted[rid] = flat
                        lifter.primitives[rid] = p2
                        lifter.base_routes[rid] = flat
                        accepted = (flat, None)
                        break
        elif rid in frames:
            for layer in choices[:5]:
                route, reason = TR.try_route(lifter, record, row, int(layer),
                                             frames[rid], max_candidates=8,
                                             max_plans=30)
                if route is not None:
                    accepted = (route, layer)
                    break
        if accepted:
            route, layer = accepted
            if layer is not None:
                assign[rid]['physical_layer'] = str(layer)
            recovered.append(dict(route_id=rid, old_reason=failure.get('reason'),
                                  new_layer=layer))
        else:
            still.append(failure)
        if index % 10 == 0:
            print(f'[B] {index}/{len(failures)} recovered={len(recovered)} '
                  f'still={len(still)} ({time.perf_counter()-started:.0f}s)', flush=True)
    print(f'[B] recovered={len(recovered)} still={len(still)}', flush=True)
    routed = OrderedDict()
    for rid in routes:
        layer = assign[rid]['physical_layer']
        routed[rid] = dict(route=routes[rid], primitives=prims[rid],
                           physical_layer=(None if layer == '' else int(layer)))
    for item in recovered:
        rid = item['route_id']
        routed[rid] = dict(route=lifter.lifted[rid], primitives=lifter.primitives[rid],
                           physical_layer=item['new_layer'])
    assignment_rows = list(csv.DictReader(open(R2.OUT / 'assignment_1024.csv',
                                                encoding='utf-8-sig')))
    for row in assignment_rows:
        if row['physical_layer'] == '':
            row['physical_layer'] = None
        else:
            row['physical_layer'] = int(row['physical_layer'])
    import shutil
    shutil.copy2(R2.OUT / 'assignment_summary.json', exp / 'assignment_summary.json')
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
    print('[B] saved', exp, flush=True)


if __name__ == '__main__':
    main()
