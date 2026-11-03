# -*- coding: utf-8 -*-
"""Experiment A: 12 independent Z2 planes + frozen old XY paths."""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import OrderedDict
from pathlib import Path

from . import bidirectional_1mm_builder as B
from . import bidirectional_round2_assignment as R2
from . import fixed_layer_3d as F3
from .bidirectional_1mm_layer_assignment import CK, V4
from .run_full_campaign import CAMPAIGN_V4


def main():
    B.setup()
    # monkeypatch the first-round builder to the round-2 stack/maps
    B.OUT = R2.OUT
    B.PHYSICAL_LAYERS = R2.PHYSICAL_LAYERS
    B.ROUTING_LAYER_IDS = R2.ROUTING_LAYER_IDS
    B.Z1_LAYER_MAP = R2.Z1_LAYER_MAP
    B.Z2_LAYER_MAP = R2.Z2_LAYER_MAP
    B.layer_stack_payload = R2.layer_stack_payload
    out = Path(R2.OUT) / 'experiment_A'
    out.mkdir(parents=True, exist_ok=True)
    # assignment must exist at root
    if not (Path(R2.OUT) / 'assignment_1024.csv').exists():
        R2.write_assignment(R2.OUT)
    assignment = list(csv.DictReader(open(R2.OUT / 'assignment_1024.csv',
                                          encoding='utf-8-sig')))
    for row in assignment:
        row['physical_layer'] = (None if row['physical_layer'] == ''
                                 else int(row['physical_layer']))
    lifter = B.make_lifter(out)
    fast = F3.FastClearance()
    phase_b = json.loads((Path(R2.OUT).parent / 'MANUAL_LAYERS_20L_PROTO/phaseB.json')
                         .read_text(encoding='utf-8'))['results']
    z1_u = OrderedDict((int(k), v) for k, v in sorted(phase_b.items(),
                                                      key=lambda kv: int(kv[0])))
    u_results, u_failures = B.build_z1_u(lifter, z1_u, assignment, fast)
    print(f'[A Z1-U] {len(u_results)}/256 fail={len(u_failures)}', flush=True)
    ck_routes = {int(k): v for k, v in json.loads(
        (CK / 'z1/z1_all_routes.json').read_text(encoding='utf-8')).items()}
    ck_prims = {int(k): v for k, v in json.loads(
        (CK / 'z1/primitives.json').read_text(encoding='utf-8')).items()}
    manual_ids = set(z1_u)
    o_routes = {r: v for r, v in ck_routes.items() if r not in manual_ids}
    o_prims = {r: v for r, v in ck_prims.items() if r not in manual_ids}
    o_results, o_failures = B.build_z1_opposite(lifter, o_routes, o_prims,
                                                assignment, fast)
    print(f'[A Z1-opposite] {len(o_results)}/256 fail={len(o_failures)}', flush=True)
    zi_results, zi_failures = B.build_z2_interface(lifter, assignment, fast)
    print(f'[A Z2-interface] {len(zi_results)}/68 fail={len(zi_failures)}', flush=True)
    zh_results, zh_failures = B.build_z2_high(lifter, assignment, fast,
                                              max_plans=60)
    print(f'[A Z2-high] {len(zh_results)}/444 fail={len(zh_failures)}', flush=True)
    routed = OrderedDict()
    for group in (u_results, o_results, zi_results, zh_results):
        routed.update(group)
    failures = u_failures + o_failures + zi_failures + zh_failures
    print(f'[A TOTAL] routed={len(routed)}/1024 failures={len(failures)}', flush=True)
    # payload
    R2.OUT.joinpath('experiment_A').mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(R2.OUT / 'assignment_summary.json',
                 out / 'assignment_summary.json')
    payload = B.make_payload(lifter, routed, failures, assignment)
    (out / 'routes_l3d.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    (out / 'failed_routes.json').write_text(
        json.dumps(dict(total=len(failures), failures=failures),
                   ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    ck = out / 'checkpoints'
    ck.mkdir(exist_ok=True)
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
    print('[A] saved', out, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
