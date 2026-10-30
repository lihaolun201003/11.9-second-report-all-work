# -*- coding: utf-8 -*-
"""C3 final v2: Z2 clearance of the port corridors, then acceptance-greedy
short-window lift of the 29 Z1 C2 pairs, then the validated E1-D refiner."""
import sys, time, json
from collections import Counter
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.e1 import layering as L
from four_side_1024.e1 import refine as R

OUT_DIR = C.E1 / 'E1_C3_z2_bundle'


def main():
    started = time.perf_counter()
    ctx = C.load_ctx()
    by_id = L.records_by_id(ctx.records_base)
    movers = L.collinear_z2_movers(ctx)
    base_analysis = C.audit(ctx.records_base, ctx)

    # ---- phase 1: Z2 clearance -------------------------------------------
    selected = {rid for rid in movers
                if ctx.cat[rid] in ('adjacent_z2', 'opposite_z2_EW',
                                    'opposite_z2_NS')}
    print(f'phase1: {len(selected)} Z2 clearance routes', flush=True)
    cleared_records, moved, failed = L.relocate_z2(
        ctx, ctx.records_base, selected, dest_fn=lambda rid: (6, 7),
        max_candidates=30, time_limit=240, log=print)
    records = cleared_records
    analysis = C.audit(records, ctx)
    print(f'phase1 done: moved={len(moved)} failed={len(failed)} '
          f'unique {base_analysis["n_unique_pairs"]} -> '
          f'{analysis["n_unique_pairs"]}', flush=True)

    # ---- phase 2: lift the 29 flat pairs with accepted deltas -------------
    by_id = L.records_by_id(records)
    accepted = []
    for entry in ctx.unlifted_pairs:
        world = ctx.world([record for record in records
                           if int(record['route_id']) not in entry['rids']])
        picked = None
        for layer in ([2, 4, 5, 6] if entry['key'] == 'EW' else [3, 4, 5, 6]):
            candidates = []
            for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer,
                                              symmetric_only=True):
                routes = ctx.lift_pair(entry, layer, a_in, a_out)
                if routes is None:
                    continue
                if any(S.structure_errors(route) for route in routes):
                    continue
                if any(world.check_route(route) for route in routes):
                    continue
                if C.pairwise_violations(world, routes[0], routes[1]):
                    continue
                candidates.append(dict(layer=layer, a_in=a_in, a_out=a_out,
                                       routes=routes))
                if len(candidates) >= 2:
                    break
            if not candidates:
                continue
            best = None
            for candidate in candidates:
                trial = L.replace(records, candidate['routes'])
                trial_analysis = C.audit(trial, ctx)
                delta = (trial_analysis['n_unique_pairs']
                         - analysis['n_unique_pairs'])
                if best is None or delta < best[0]:
                    best = (delta, candidate, trial_analysis)
            if best[0] < 0:
                delta, candidate, trial_analysis = best
                records = L.replace(records, candidate['routes'])
                analysis = trial_analysis
                picked = dict(pair_id=entry['pair_id'], layer=candidate['layer'],
                              a_in=round(candidate['a_in'], 2),
                              a_out=round(candidate['a_out'], 2), delta=delta)
            break
        if picked:
            accepted.append(picked)
            print(f'  [C3] {entry["pair_id"]} -> L{picked["layer"]} '
                  f'a={picked["a_in"]} delta={picked["delta"]}', flush=True)
        else:
            print(f'  [C3] {entry["pair_id"]} kept flat', flush=True)
    print(f'phase2 done: lifted {len(accepted)}/{len(ctx.unlifted_pairs)} '
          f'unique={analysis["n_unique_pairs"]}', flush=True)

    # ---- phase 3: refiner over all lifted Z1 routes ------------------------
    movable = [rid for rid in ctx.z1_opposite
               if int(rid) in L.records_by_id(records)
               and C.Ctx.route_target_layer(L.records_by_id(records)[rid]) > 1]
    print(f'phase3: refine {len(movable)} lifted Z1 routes', flush=True)
    try:
        refined = R.refine(ctx, records, movable_rids=movable, max_passes=2,
                           log=print)
        records = refined['records']
        changed = refined['changed']
        passes = refined['pass_stats']
        refine_stats = refined.get('stats')
    except Exception as exc:
        print('phase3 refine failed:', repr(exc), flush=True)
        changed, passes, refine_stats = [], [], None

    analysis, stats, usage = L.summarise(ctx, records, 'C3-final')
    print('by height:', L.layer_by_height(analysis), flush=True)
    extra = dict(
        c3_phase1_cleared_z2=len(moved),
        c3_phase1_cleared_z2_ids=sorted(moved),
        c3_phase1_failed_z2=sorted(failed),
        c3_phase1_unique_after_clear=len(records) and None,
        c3_phase2_accepted_pairs=accepted,
        c3_phase2_lifted_pairs=len(accepted),
        c3_phase3_changed=changed,
        c3_phase3_passes=passes,
        c3_phase3_stats=refine_stats,
        z1_stub_total=round(sum(sum(C.Ctx.stubs(r)) for r in records
                                if int(r['route_id']) in set(ctx.z1_opposite)), 3),
        runtime_seconds=round(time.perf_counter() - started, 1),
        ew_layer=2, ns_layer=3,
    )
    summary, report, _ = C.save_experiment(
        'E1_C3_z2_bundle', records, ctx, folder=OUT_DIR, extra=extra,
        note=('C3: Z1 priority + bundle-level Z2 clearance (collinear adjacent/'
              'opposite Z2 routes -> L6), acceptance-greedy short windows for '
              'the 29 flat Z1 pairs, then exact-delta window refinement of all '
              'lifted Z1 routes'))
    print(json.dumps(C.summary_row('C3', summary), ensure_ascii=False, indent=1))
    C.write_json(C.E1 / '_c3_best_path.json',
                 dict(folder=str(OUT_DIR),
                      unique=summary['unique_crossing_pairs'],
                      z1=summary['z1_crossing_pairs'],
                      z2=summary['z2_crossing_pairs'],
                      high=summary['high_layer_crossing_pairs'],
                      violations=summary['validation_counts'].get('violations')))
    print('saved', OUT_DIR)


if __name__ == '__main__':
    main()
