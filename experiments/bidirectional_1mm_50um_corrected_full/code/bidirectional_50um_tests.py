# -*- coding: utf-8 -*-
"""Minimal geometry tests for the corrected 50 um process rules."""
from __future__ import annotations

import json
from pathlib import Path

from . import glass_1mm_process_rules as RULES
from ..l3d.world import World


class _MaxStack:
    def __init__(self, heights):
        self.heights = heights

    def z_for_layer(self, layer_id):
        return self.heights[int(layer_id)]


def _line(x0, y0, x1, y1):
    return {'kind': 'line', 'p0': [x0, y0], 'p1': [x1, y1], 'layer': 0}


def _flat_route(rid, z, layer=2):
    prims = [_line(0, 0, 20, 0)]
    return World.flat_route(rid, 'z1', prims, z, layer_id=layer, row=1)


def main():
    out = Path(RULES.__file__).resolve().parents[2] / (
        'outputs/manual_c4_new_connectivity/'
        'BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL')
    out.mkdir(parents=True, exist_ok=True)
    results = []
    # 50 um gap: flat planes with identical XY must be legal
    world = World(_MaxStack({2: 0.20, 3: 0.25}), clearance=RULES.MIN_3D_CLEARANCE_MM)
    world.add_route(_flat_route(1, 0.20, 2))
    v = world.check_route(_flat_route(2, 0.25, 3), check_self=False)
    results.append(dict(case='gap_50um_xy_overlap', expected='legal',
                        world_violations=len(v), pass_=not v))
    # 49 um gap: must be rejected by the online layer-gap check
    world = World(_MaxStack({2: 0.20, 3: 0.249}), clearance=RULES.MIN_3D_CLEARANCE_MM)
    world.add_route(_flat_route(3, 0.20, 2))
    v = world.check_route(_flat_route(4, 0.249, 3), check_self=False)
    results.append(dict(case='gap_49um_xy_overlap', expected='illegal',
                        world_violations=len(v), pass_=bool(v)))
    # 60/80 um gaps: legal
    for gap in (0.060, 0.080):
        world = World(_MaxStack({2: 0.20, 3: 0.20 + gap}),
                      clearance=RULES.MIN_3D_CLEARANCE_MM)
        world.add_route(_flat_route(5, 0.20, 2))
        v = world.check_route(_flat_route(6, 0.20 + gap, 3), check_self=False)
        results.append(dict(case=f'gap_{int(gap*1000)}um_xy_overlap',
                            expected='legal', world_violations=len(v),
                            pass_=not v))
    # total thickness / layer bounds
    heights = [-0.35, -0.29, -0.23, -0.17, -0.11, -0.05,
               0.05, 0.10, 0.15, 0.20, 0.25, 0.30,
               0.35, 0.40, 0.45, 0.55, 0.60, 0.65]
    gaps = [b - a for a, b in zip(heights, heights[1:])]
    results.append(dict(case='18_layer_min_gap', expected='>=0.05',
                        min_gap=min(gaps), pass_=min(gaps) >= 0.05 - 1e-9))
    results.append(dict(case='glass_thickness', expected='1.0',
                        value=0.65 - (-0.35),
                        pass_=abs((0.65 - (-0.35)) - 1.0) < 1e-9))
    payload = dict(schema='validator_consistency_tests_v1',
                   mode=RULES.PROCESS_MODE,
                   rules=RULES.rules_payload(),
                   results=results,
                   all_pass=all(item['pass_'] for item in results))
    (out / 'validator_consistency_tests.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
