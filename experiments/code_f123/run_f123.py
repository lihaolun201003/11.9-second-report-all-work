# -*- coding: utf-8 -*-
"""F1/F2/F3 layer-strategy experiment driver.

F1: Z1 adjacent + NS stay on the interface, EW -> L2; Z2 optimised independently.
F2: Z1 adjacent stay, NS -> L2, EW -> L3; Z2 optimised independently; then joint
    local micro-tuning (both the strict preset result and the locally optimised
    result are kept).
F3: from the F2 result, selectively lift the Z1 adjacent arcs that own a legal
    straight window (largest / highest-contribution first), then re-tune Z2 and
    the Z1 windows.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.f123 import core as F
from four_side_1024.f123 import savefigs as SF

OUT = F.OUT
LOG_LINES = []


def log(*args):
    text = ' '.join(str(a) for a in args)
    LOG_LINES.append(text)
    print(text, flush=True)


def z1_plan(ctx, mapping):
    """{rid: layer} for the movable Z1 routes (opposite by direction + U)."""
    plan = {}
    for rid in ctx.z1_opposite:
        cat = ctx.cat[rid]
        if cat.endswith('_EW'):
            plan[rid] = int(mapping['EW'])
        else:
            plan[rid] = int(mapping['NS'])
    for gid in F.z1_u_groups(ctx):
        for rid in ctx.groups[gid]['route_ids']:
            plan[int(rid)] = int(mapping.get('U', 1))
    return plan


def z2_units(ctx, records):
    units = []
    for rid in ctx.z2_adjacent:
        units.append(dict(rids=[rid], kind='adjacent_z2', label=f'route:{rid}'))
    for gid in F.z2_u_groups(ctx):
        rids = [int(r) for r in ctx.groups[gid]['route_ids']]
        units.append(dict(rids=rids, kind='same_u_z2', label=f'U:{gid}'))
    for gid in F.z2_opposite_groups(ctx):
        rids = [int(r) for r in ctx.groups[gid]['route_ids']]
        units.append(dict(rids=rids, kind='opposite_z2', label=f'opp:{gid}'))
    return units


def z1_units(ctx):
    units = []
    for rid in ctx.z1_opposite:
        units.append(dict(rids=[rid], kind=ctx.cat[rid], label=f'route:{rid}'))
    for gid in F.z1_u_groups(ctx):
        rids = [int(r) for r in ctx.groups[gid]['route_ids']]
        units.append(dict(rids=rids, kind='same_u_z1', label=f'U:{gid}'))
    return units


def adjacent_units(ctx, records):
    """Z1 adjacent routes that own at least one legal straight window."""
    units = []
    plan = []
    for rid in ctx.z1_adjacent:
        for layer in (3, 4, 5, 2, 6, 7):
            grid = F.windows(ctx, rid, layer, count=4)
            if grid:
                plan.append((rid, layer))
                break
    rids = [rid for rid, _layer in plan]
    for rid in rids:
        units.append(dict(rids=[rid], kind='adjacent_z1', label=f'route:{rid}'))
    return units



def e1_z2_base(ctx, baseline):
    """Interface-flat Z1 + the validated E1 Z2 geometry (a legal scaffold)."""
    z2_rids = {rid for rid in ctx.manifest
               if ctx.cat[rid].startswith(('adjacent_z2', 'same_u_z2',
                                           'opposite_z2'))}
    out = {}
    for rid in ctx.manifest:
        out[rid] = baseline[rid] if rid in z2_rids else ctx.flat(rid)
    return out


def run_scheme_stage(ctx, eng, records, z2_targeted=True, local_rounds=0,
                     log_prefix=''):
    """Z2 optimisation (strict C4 orbits) + optional local joint micro-tuning."""
    z2_orbits = F.z2_orbits(ctx)
    z2_rids = {int(rid) for orbit in z2_orbits for rid in orbit['ids']}
    z1_only = {rid: record for rid, record in records.items()
               if rid not in z2_rids}
    world = F.make_world(z1_only)
    records, analysis = F.optimize_z2_orbits(
        ctx, eng, records, z2_orbits, world, log=log,
        layer_pool=(2, 3, 4, 5, 6, 7), pass_name=f'{log_prefix}z2-c4-pass1',
        world_mode='fresh')
    # --- local joint micro-tuning (Z1 asymmetric window/layer refinement) ---
    for rnd in range(local_rounds):
        # window-only refinement keeps the prescribed layer strategy intact
        world = F.make_world(records)
        records, _ = F.optimize_units(
            ctx, eng, records, z1_units(ctx), world, log=log,
            layer_pool=(), pass_name=f'{log_prefix}z1-window-{rnd}',
            world_mode='existing')
        z1_only = {rid: record for rid, record in records.items()
                   if rid not in z2_rids}
        world = F.make_world(z1_only)
        records, _ = F.optimize_z2_orbits(
            ctx, eng, records, z2_orbits, world, log=log,
            layer_pool=(2, 3, 4, 5, 6, 7),
            pass_name=f'{log_prefix}z2-c4-refine-{rnd}', world_mode='fresh')
    records, report, reverted = F.repair(ctx, records, log=log,
                                         max_rounds=6)
    analysis = C.audit(list(records.values()), ctx)
    log(f'[{log_prefix}done] unique={analysis["n_unique_pairs"]} '
        f'reverted={len(reverted)}')
    return records, analysis, reverted


def scheme_row(name, summary, kind='experiment'):
    return dict(experiment=name, kind=kind,
                unique_crossing_pairs=summary['unique_crossing_pairs'],
                z1_crossing_pairs=summary['z1_crossing_pairs'],
                z2_crossing_pairs=summary['z2_crossing_pairs'],
                high_layer_crossing_pairs=summary['high_layer_crossing_pairs'],
                transitions=summary['transitions'],
                fabrication_hours=summary['fabrication_hours'],
                total_length_mm=summary['total_length_mm'],
                violations=(summary.get('validation_counts') or {}).get(
                    'violations'),
                routed=summary.get('routed'))


def main():
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = C.load_ctx()
    eng = F.engine(ctx)
    baseline = F.load_baseline(ctx)
    baseline_list = [baseline[rid] for rid in sorted(baseline)]
    base_analysis = C.audit(baseline_list, ctx)
    log(f'[baseline] E1 best unique={base_analysis["n_unique_pairs"]}')
    rows = [dict(experiment='E1 baseline', kind='baseline',
                 unique_crossing_pairs=base_analysis['n_unique_pairs'],
                 z1_crossing_pairs=base_analysis['z1_pairs'],
                 z2_crossing_pairs=base_analysis['z2_pairs'],
                 high_layer_crossing_pairs=base_analysis['high_pairs'],
                 transitions=F.C.bar(baseline_list)['transitions'],
                 fabrication_hours=F.C.bar(baseline_list)['fabrication_hours'],
                 total_length_mm=F.C.bar(baseline_list)['total_length_mm'],
                 violations=0, routed=1024)]
    # copy E1 baseline artefacts
    base_dir = OUT / 'baseline_E1'
    if not (base_dir / 'routes_1024.json').exists():
        C.ensure_dir(base_dir)
        for name in ('routes_1024.json', 'summary.json', 'validation.json',
                     'per_route.csv', 'per_layer.csv'):
            source = C.E1 / 'best_solution' / name
            if source.exists():
                shutil.copy2(source, base_dir / name)
        if (C.E1 / 'best_solution' / 'figures').exists():
            shutil.copytree(C.E1 / 'best_solution' / 'figures',
                            base_dir / 'figures', dirs_exist_ok=True)

    # ------------------------------------------------------------------ F1
    log('===== F1: Z1 adjacent+NS on interface, EW -> L2 =====')
    plan1 = z1_plan(ctx, dict(EW=2, NS=1, U=3))
    records1 = e1_z2_base(ctx, baseline)
    records1, assign1 = F.build_z1_phase(ctx, plan1, log=log,
                                        base_records=records1)
    log(f'[F1 z1] {dict(Counter(row["actual_layer"] for row in assign1))}')
    records1, analysis1, reverted1 = run_scheme_stage(
        ctx, eng, records1, local_rounds=1, log_prefix='F1/')
    summary1 = SF.save_scheme(
        ctx, 'F1_NS_Z1_EW_L2', OUT / 'F1_NS_Z1_EW_L2', records1,
        plan=plan1, baseline_records=baseline_list,
        extra=dict(stage='F1: Z1 adjacent+NS on interface, EW->L2; Z2 '
                         'independently optimised', reverted=reverted1,
                   assignment_rows=len(assign1)),
        log=log)
    rows.append(scheme_row('F1', summary1[0]))

    # ------------------------------------------------------------------ F2
    log('===== F2: Z1 adjacent on interface, NS -> L2, EW -> L3 =====')
    plan2 = z1_plan(ctx, dict(EW=3, NS=2, U=3))
    records2 = e1_z2_base(ctx, baseline)
    records2, assign2 = F.build_z1_phase(ctx, plan2, log=log,
                                        base_records=records2)
    log(f'[F2 z1] {dict(Counter(row["actual_layer"] for row in assign2))}')
    records2, analysis2, reverted2 = run_scheme_stage(
        ctx, eng, records2, local_rounds=0, log_prefix='F2-init/')
    summary2 = SF.save_scheme(
        ctx, 'F2_initial_assignment',
        OUT / 'F2_NS_L2_EW_L3' / 'initial_assignment', records2,
        plan=plan2, baseline_records=baseline_list,
        extra=dict(stage='F2 strict preset: adjacent on interface, NS->L2, '
                         'EW->L3; Z2 independently optimised (no joint '
                         'micro-tuning)', reverted=reverted2),
        log=log)
    rows.append(scheme_row('F2 initial', summary2[0]))

    log('===== F2 local joint micro-tuning =====')
    records2b = dict(records2)
    records2b, analysis2b, reverted2b = run_scheme_stage(
        ctx, eng, records2b, local_rounds=0, log_prefix='F2-local/')
    summary2b = SF.save_scheme(
        ctx, 'F2_locally_optimized',
        OUT / 'F2_NS_L2_EW_L3' / 'locally_optimized', records2b,
        plan=plan2, baseline_records=baseline_list,
        extra=dict(stage='F2 + local joint micro-tuning (Z1 windows/layers, '
                         'Z2 re-optimisation)', reverted=reverted2b),
        log=log)
    rows.append(scheme_row('F2 local', summary2b[0]))

    best_records = records2b if (
        analysis2b['n_unique_pairs'] <= analysis2['n_unique_pairs']) else records2

    # ------------------------------------------------------------------ F3
    log('===== F3: selective lifting of large Z1 adjacent arcs =====')
    units = adjacent_units(ctx, best_records)
    log(f'[F3] adjacent routes with a legal straight window: {len(units)}/'
        f'{len(ctx.z1_adjacent)}')
    world = F.make_world({rid: record for rid, record in best_records.items()
                          if ctx.cat[rid] != 'adjacent_z1'
                          and not ctx.cat[rid].startswith(
                              ('adjacent_z2', 'same_u_z2', 'opposite_z2'))})
    records3, analysis3, _ = F.optimize_units(
        ctx, eng, best_records, units, world, log=log,
        layer_pool=(3,), pass_name='F3/adjacent-lift',
        world_mode='fresh')
    records3, analysis3, reverted3 = run_scheme_stage(
        ctx, eng, records3, local_rounds=1, log_prefix='F3/')
    summary3 = SF.save_scheme(
        ctx, 'F3_adjacent_selective_lift',
        OUT / 'F3_adjacent_selective_lift', records3,
        plan=plan2, baseline_records=baseline_list,
        extra=dict(stage='F3: selective Z1 adjacent lifting on top of F2 + '
                         'joint re-tuning', reverted=reverted3),
        log=log)
    rows.append(scheme_row('F3', summary3[0]))

    # ------------------------------------------------------------ finalise
    C.write_csv(OUT / 'comparison.csv', rows)
    C.write_json(OUT / 'comparison.json',
                 dict(rows=rows, runtime_seconds=round(
                     time.perf_counter() - started, 1), log=LOG_LINES[-400:]))
    SF.comparison_figure(OUT, rows)
    valid = [row for row in rows if row.get('violations') == 0
             and row['experiment'] != 'E1 baseline']
    if not valid:
        # no new scheme reached violations=0: keep the validated E1 baseline
        rows_baseline = [row for row in rows
                         if row['experiment'] == 'E1 baseline']
        if rows_baseline:
            valid = rows_baseline
            log('[best] no new valid scheme; E1 baseline kept as reference')
    if valid:
        best = min(valid, key=lambda row: row['unique_crossing_pairs'])
        mapping = {'F1': OUT / 'F1_NS_Z1_EW_L2',
                   'F2 initial': OUT / 'F2_NS_L2_EW_L3' / 'initial_assignment',
                   'F2 local': OUT / 'F2_NS_L2_EW_L3' / 'locally_optimized',
                   'F3': OUT / 'F3_adjacent_selective_lift'}
        src = mapping[best['experiment']]
        dst = OUT / 'best_solution'
        dst.mkdir(parents=True, exist_ok=True)
        for name in ('routes_1024.json', 'summary.json', 'validation.json',
                     'per_route.csv', 'per_layer.csv', 'crossing_sources.csv',
                     'assignment_table.csv'):
            if (src / name).exists():
                shutil.copy2(src / name, dst / name)
        if (src / 'figures').exists():
            shutil.copytree(src / 'figures', dst / 'figures',
                            dirs_exist_ok=True)
        C.write_json(dst / 'BEST_SOURCE.json',
                     dict(source_experiment=best['experiment'],
                          summary=best))
        log(f'[best] {best["experiment"]} unique='
            f'{best["unique_crossing_pairs"]}')
    log(f'[f123] total {time.perf_counter() - started:.0f}s')


if __name__ == '__main__':
    main()
