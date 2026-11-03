# -*- coding: utf-8 -*-
"""Experiment B: rebuild the full 1024 routes on the corrected 18-plane stack
with the 50 um process rule and the real target layers.

This is the clean-room rebuild: empty world, 6 Z1 planes, 12 independent Z2
planes, true negative/positive S transitions, no checkpoint inheritance.
"""
from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from . import bidirectional_50um_assignment as A50
from . import fixed_layer_3d as F3
from .bidirectional_1mm_layer_assignment import CK, V4
from .glass_1mm_process_rules import MIN_3D_CLEARANCE_MM


def main():
    B.setup()
    B.OUT = A50.OUT
    B.PHYSICAL_LAYERS = A50.PHYSICAL_LAYERS
    B.ROUTING_LAYER_IDS = A50.ROUTING_LAYER_IDS
    B.Z1_LAYER_MAP = A50.Z1_LAYER_MAP
    B.Z2_LAYER_MAP = A50.Z2_LAYER_MAP
    B.layer_stack_payload = A50.layer_stack_payload
    out = Path(A50.OUT) / 'experiment_B'
    out.mkdir(parents=True, exist_ok=True)
    if not (Path(A50.OUT) / 'assignment_1024.csv').exists():
        A50.write_assignment(A50.OUT)
    assignment = list(csv.DictReader(open(A50.OUT / 'assignment_1024.csv',
                                          encoding='utf-8-sig')))
    for row in assignment:
        row['physical_layer'] = (None if row['physical_layer'] == ''
                                 else int(row['physical_layer']))
    lifter = B.make_lifter(out, clearance=MIN_3D_CLEARANCE_MM)
    fast = F3.FastClearance(clearance=MIN_3D_CLEARANCE_MM)
    phase_b = json.loads((Path(A50.OUT).parent / 'MANUAL_LAYERS_20L_PROTO/phaseB.json')
                         .read_text(encoding='utf-8'))['results']
    z1_u = OrderedDict((int(k), v) for k, v in sorted(phase_b.items(),
                                                      key=lambda kv: int(kv[0])))
    u_results, u_failures = B.build_z1_u(lifter, z1_u, assignment, fast)
    print(f'[B Z1-U] {len(u_results)}/256 fail={len(u_failures)}', flush=True)
    ck_routes = {int(k): v for k, v in json.loads(
        (CK / 'z1/z1_all_routes.json').read_text(encoding='utf-8')).items()}
    ck_prims = {int(k): v for k, v in json.loads(
        (CK / 'z1/primitives.json').read_text(encoding='utf-8')).items()}
    manual_ids = set(z1_u)
    o_routes = {r: v for r, v in ck_routes.items() if r not in manual_ids}
    o_prims = {r: v for r, v in ck_prims.items() if r not in manual_ids}
    o_results, o_failures = B.build_z1_opposite(lifter, o_routes, o_prims,
                                                assignment, fast)
    print(f'[B Z1-opposite] {len(o_results)}/256 fail={len(o_failures)}', flush=True)
    # Z2 interface first (all 48 available 2D paths fit the empty interface
    # plane), then the high planes.
    zi_results, zi_failures = B.build_z2_interface(lifter, assignment, fast)
    print(f'[B Z2-interface] {len(zi_results)}/68 fail={len(zi_failures)}', flush=True)
    zh_results, zh_failures = B.build_z2_high(lifter, assignment, fast,
                                              max_plans=50)
    print(f'[B Z2-high] {len(zh_results)}/444 fail={len(zh_failures)}', flush=True)
    routed = OrderedDict()
    for group in (u_results, o_results, zi_results, zh_results):
        routed.update(group)
    failures = u_failures + o_failures + zi_failures + zh_failures
    print(f'[B TOTAL] routed={len(routed)}/1024 failures={len(failures)}', flush=True)
    import shutil
    shutil.copy2(A50.OUT / 'assignment_summary.json', out / 'assignment_summary.json')
    payload = B.make_payload(lifter, routed, failures, assignment)
    (out / 'routes_l3d.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    (out / 'failed_routes.json').write_text(
        json.dumps(dict(total=len(failures), failures=failures),
                   ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    ck = out / 'checkpoints'; ck.mkdir(exist_ok=True)
    (ck / 'routes.json').write_text(json.dumps(
        {str(r): info['route'] for r, info in routed.items()},
        ensure_ascii=False, default=str), encoding='utf-8')
    (ck / 'primitives.json').write_text(json.dumps(
        {str(r): info['primitives'] for r, info in routed.items()},
        ensure_ascii=False, default=str), encoding='utf-8')
    (ck / 'build_summary.json').write_text(json.dumps(
        dict(routed=len(routed), failed=len(failures),
             stages=dict(z1_u=len(u_results), z1_opposite=len(o_results),
                         z2_interface=len(zi_results), z2_high=len(zh_results)),
             failures=failures), ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print('[B] saved', out, flush=True)


if __name__ == '__main__':
    main()
