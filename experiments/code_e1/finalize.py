# -*- coding: utf-8 -*-
"""Finalize: add the mandatory z1_blocking_routes figure where missing."""
import sys, json
from collections import Counter
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C
from four_side_1024.e1 import layering as L
from four_side_1024.e1 import search as S
from four_side_1024.e1 import plots as P

GROUPS = ['E1_C1_z1_only', 'E1_C2_z2_local', 'E1_C3_z2_bundle',
          'E1_D_early_lift/D2_baseline_asymmetric',
          'E1_D_early_lift/D3_e1c_best',
          'E1_D_early_lift/D3_e1c_best/z2_retune_extension']


def main():
    ctx = C.load_ctx()
    movers = L.collinear_z2_movers(ctx)
    structural = sorted(movers)
    print(f'structural collinear Z2 blockers: {len(structural)}')
    for group in GROUPS:
        folder = C.E1 / group
        summary = folder / 'summary.json'
        if not summary.exists():
            print(f'skip {group}: no summary')
            continue
        payload = C.read_json(folder / 'routes_1024.json')
        records = [r for r in payload['routes'] if r.get('status') == 'routed']
        blocking_rows = [dict(route_id=rid, category=ctx.cat[rid],
                              plane=ctx.plane_of(rid),
                              label=ctx.label(rid))
                         for rid in structural]
        path = P.z1_blocking_figure(folder, ctx, blocking_rows, records,
                                    f'{group} (structural Z2 collinear blockers)')
        print('wrote', path)


if __name__ == '__main__':
    main()
