# -*- coding: utf-8 -*-
"""Finalise the reworked F2 experiment: extra legal tracks, figures, report."""
from __future__ import annotations

import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')

from four_side_1024.e1 import core as C
from four_side_1024.f123 import core as F
from four_side_1024.f123 import savefigs as SF
from four_side_1024.f2fix import run_f2 as R2
from four_side_1024.c4 import orbits as O

OUT = R2.OUT
FIG_NAMES = ['overall_3d', 'overall_xy', 'L1_Z1', 'L1_Z2', 'L2', 'L3',
             'L4', 'L5', 'L6', 'L7', 'all_layers_contact_sheet',
             'ns_ew_layer_assignment', 'z2_c4_layer_assignment',
             'crossing_hotspots', 'z1_transition_windows',
             'z2_transition_windows', 'before_after_comparison']
STANDARD = {'overall_3d': '01_overall_3d.png',
            'overall_xy': '02_overall_xy.png',
            'L1_Z1': '03_L1_Z1.png', 'L1_Z2': '04_L1_Z2.png',
            'L2': '05_L2.png', 'L3': '06_L3.png', 'L4': '07_L4.png',
            'L5': '08_L5.png', 'L6': '09_L6.png', 'L7': '10_L7.png',
            'all_layers_contact_sheet': 'all_layers_contact_sheet.png',
            'crossing_hotspots': 'crossing_hotspots.png'}


def load_records(folder):
    payload = C.read_json(Path(folder) / 'routes_1024.json')
    return {int(r['route_id']): r for r in payload['routes']
            if r.get('status') == 'routed'}


def categories(ctx, records):
    layers = {cat: Counter() for cat in sorted(set(ctx.cat.values()))}
    for rid, record in records.items():
        layers[ctx.cat[rid]][C.Ctx.route_target_layer(record)] += 1
    return {cat: dict(sorted(counter.items())) for cat, counter in layers.items()}


def custom_figures(ctx, folder, records):
    figdir = C.ensure_dir(Path(folder) / 'figures')
    layers = categories(ctx, records)
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei',
                                      'DejaVu Sans']
    # ns_ew_layer_assignment
    fig, ax = plt.subplots(figsize=(9, 4.6))
    cats = ['opposite_z1_NS', 'opposite_z1_EW', 'adjacent_z1', 'same_u_z1']
    rows = sorted({layer for cat in cats for layer in layers.get(cat, {})})
    width = 0.8 / len(cats)
    for index, cat in enumerate(cats):
        values = [layers.get(cat, {}).get(layer, 0) for layer in rows]
        positions = np.arange(len(rows)) + (index - len(cats) / 2) * width
        ax.bar(positions, values, width, label=cat)
    ax.set_xticks(np.arange(len(rows)))
    ax.set_xticklabels(['L1-Z1' if layer == 1 else f'L{layer}'
                        for layer in rows])
    ax.set_ylabel('Z1 routes')
    ax.set_title('Z1 actual layer assignment (NS -> L2, EW -> L3 target)')
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(figdir / 'ns_ew_layer_assignment.png', dpi=190)
    plt.close(fig)
    # z2_c4_layer_assignment
    fig, ax = plt.subplots(figsize=(8, 4.4))
    orbits = F.z2_orbits(ctx)
    counter = Counter()
    for orbit in orbits:
        rid = int(orbit['ids'][0])
        counter[C.Ctx.route_target_layer(records[rid])] += 1
    rows = sorted(counter)
    ax.bar([f'L1-Z2' if layer == 1 else f'L{layer}' for layer in rows],
           [counter[layer] for layer in rows], color='#1971c2')
    for index, layer in enumerate(rows):
        ax.text(index, counter[layer], str(counter[layer]), ha='center',
                va='bottom', fontsize=8)
    ax.set_ylabel('Z2 C4 orbits (of 128)')
    ax.set_title('Z2 strict-C4 orbits per layer (preferred L4-L7)')
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(figdir / 'z2_c4_layer_assignment.png', dpi=190)
    plt.close(fig)
    # transition windows (z1 / z2)
    for name, z2_only in (('z1_transition_windows', False),
                          ('z2_transition_windows', True)):
        fig, ax = plt.subplots(figsize=(8, 4.6))
        for rid, record in records.items():
            is_z2 = ctx.cat[rid].startswith(('adjacent_z2', 'same_u_z2',
                                             'opposite_z2'))
            if is_z2 != z2_only:
                continue
            layer = C.Ctx.route_target_layer(record)
            if layer <= 1:
                continue
            a_in, a_out = C.Ctx.stubs(record)
            ax.scatter(a_in, layer, s=8, alpha=0.6, color='#e8590c')
        ax.set_xlabel('near-port S-bend window a_in (mm)')
        ax.set_ylabel('target layer')
        ax.set_yticks([2, 3, 4, 5, 6, 7])
        ax.set_title(('Z2' if z2_only else 'Z1')
                     + ' transition windows (real XYZ geometry)')
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(figdir / f'{name}.png', dpi=190)
        plt.close(fig)


def copy_required(ctx, folder):
    figdir = Path(folder) / 'figures'
    for name, source in STANDARD.items():
        src = figdir / source
        if src.exists():
            shutil.copy2(src, figdir / f'{name}.png')
    custom_figures(ctx, folder, load_records(folder))


def comparison_figure(ctx, rows, path):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    labels = [row['experiment'] for row in rows]
    values = [row['unique'] for row in rows]
    colors = ['#868e96' if row['experiment'].startswith('E1') else '#1971c2'
              for row in rows]
    bars = ax.bar(labels, values, color=colors)
    for rect, value in zip(bars, values):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                str(value), ha='center', va='bottom', fontsize=8)
    ax.axhline(3594, ls='--', color='#e03131', lw=1.2,
               label='E1 baseline 3,594')
    ax.set_ylabel('global unique crossing pairs')
    ax.set_title('F2 reworked: global unique crossings')
    ax.tick_params(axis='x', rotation=15, labelsize=8)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(path, dpi=190)
    plt.close(fig)


def before_after_figure(ctx, folder, records, baseline):
    figdir = C.ensure_dir(Path(folder) / 'figures')
    base = C.audit(list(baseline.values()), ctx)
    now = C.audit(list(records.values()), ctx)
    keys = [('n_unique_pairs', 'global'), ('z1_pairs', 'Z1 interface'),
            ('z2_pairs', 'Z2 interface'), ('high_pairs', 'high layers')]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    positions = np.arange(len(keys))
    ax.bar(positions - 0.2, [base[key] for key, _l in keys], 0.4,
           label='E1 baseline (3,594)', color='#868e96')
    ax.bar(positions + 0.2, [now[key] for key, _l in keys], 0.4,
           label='F2 reworked (legal)', color='#1971c2')
    ax.set_xticks(positions)
    ax.set_xticklabels([label for _key, label in keys])
    ax.set_ylabel('crossing pairs')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2, axis='y')
    ax.set_title('crossing composition: E1 baseline vs F2 reworked')
    fig.tight_layout()
    fig.savefig(figdir / 'before_after_comparison.png', dpi=190)
    plt.close(fig)


def main():
    started = time.perf_counter()
    ctx = C.load_ctx()
    engine = F.engine(ctx)
    oracle = R2.FrozenOracle()
    target_of = {}
    for rid in ctx.z1_opposite:
        target_of[rid] = 2 if ctx.cat[rid] == 'opposite_z1_NS' else 3
    for gid in F.z1_u_groups(ctx):
        for rid in ctx.groups[gid]['route_ids']:
            target_of[int(rid)] = 3
    baseline = F.load_baseline(ctx)
    baseline_list = [baseline[rid] for rid in sorted(baseline)]
    best_folder = OUT / 'F2_best_legal'
    records = load_records(best_folder)
    z2_rids = {int(rid) for orbit in F.z2_orbits(ctx) for rid in orbit['ids']}
    log = lambda *a: print('[final]', *a)

    # --- extra legal track: maximise target completion ----------------------
    missing = [rid for rid in target_of if rid in records
               and C.Ctx.route_target_layer(records[rid]) != target_of[rid]]
    log('target-completion candidates:', len(missing))
    builder = R2.z1_candidate_builder(ctx, target_of,
                                      [3, 2, 4, 5, 6, 7], engine)
    target_records, stats_t = R2.chunked_apply(
        records, sorted(missing, key=lambda rid: (ctx.cat[rid], rid)),
        builder, oracle, 'target-boost', chunk=20)
    report, counts = R2.frozen_validate(target_records)
    log('target-boost violations:', counts.get('violations'))
    target_legal = int(counts.get('violations') or 0) == 0
    if target_legal:
        SF.save_scheme(ctx, 'F2_target_assignment', OUT /
                       'F2_best_target_assignment', target_records,
                       plan=target_of, baseline_records=baseline_list,
                       extra=dict(stage='target-completion track',
                                  legal=True,
                                  stats=stats_t), log=log)
        target_analysis = C.audit(list(target_records.values()), ctx)
        log('target track unique:', target_analysis['n_unique_pairs'])
    else:
        target_records = records
        target_analysis = C.audit(list(records.values()), ctx)

    # --- extra legal track: joint local re-optimisation ---------------------
    joint = dict(records)
    joint, stats_j1 = R2.z2_orbit_pass(ctx, joint, oracle, engine,
                                       'joint-z2', windows_only=True,
                                       chunk=6)
    analysis = C.audit(list(joint.values()), ctx)
    contribution = analysis['per_route']
    order = [rid for rid in sorted(joint,
                                   key=lambda rid: -contribution.get(rid, 0))
             if rid not in z2_rids
             and C.Ctx.route_target_layer(joint[rid]) > 1][:160]
    builder = R2.z1_window_builder(ctx, engine)
    joint, stats_j2 = R2.chunked_apply(joint, order, builder, oracle,
                                       'joint-z1-window', chunk=20)
    report, counts = R2.frozen_validate(joint)
    joint_legal = int(counts.get('violations') or 0) == 0
    joint_analysis = C.audit(list(joint.values()), ctx)
    log('joint track:', joint_analysis['n_unique_pairs'], 'legal=',
        joint_legal)
    if joint_legal and joint_analysis['n_unique_pairs'] < analysis['n_unique_pairs']:
        C.ensure_dir(OUT / 'joint_local_rerouting')
        SF.save_scheme(ctx, 'F2_joint_local', OUT / 'joint_local_rerouting',
                       joint, plan=target_of, baseline_records=baseline_list,
                       extra=dict(stage='joint local re-routing',
                                  legal=True, stats=dict(z2=stats_j1,
                                                         z1=stats_j2)),
                       log=log)
        if joint_analysis['n_unique_pairs'] < C.audit(
                list(records.values()), ctx)['n_unique_pairs']:
            records = joint
            log('joint track becomes new F2_best_legal')

    # --- F3 follow-up: selective adjacent lifting ---------------------------
    log('F3 follow-up: selective Z1 adjacent lifting')
    adjacent = [rid for rid in ctx.z1_adjacent
                if C.Ctx.route_target_layer(records[rid]) <= 1]

    def adjacent_builder(rid, records_, world, oracle_, geoms_all=None):
        for layer in (3, 4, 5, 2):
            for a_in, a_out in F.windows(ctx, rid, layer, count=6):
                route = ctx.lift(rid, layer, a_in, a_out)
                if route is None:
                    continue
                if not oracle_.legal(route, {rid}, world):
                    continue
                return route
        return None
    f3_records, stats_f3 = R2.chunked_apply(
        records, adjacent, adjacent_builder, oracle, 'f3-adjacent', chunk=16)
    report, counts = R2.frozen_validate(f3_records)
    f3_legal = int(counts.get('violations') or 0) == 0
    f3_analysis = C.audit(list(f3_records.values()), ctx)
    lifted = sum(1 for rid in ctx.z1_adjacent
                 if C.Ctx.route_target_layer(f3_records[rid]) > 1)
    log('F3 follow-up:', f3_analysis['n_unique_pairs'], 'legal=', f3_legal,
        'adjacent lifted=', lifted)
    if f3_legal:
        SF.save_scheme(ctx, 'F3_followup', OUT / 'F3_followup', f3_records,
                       plan=target_of, baseline_records=baseline_list,
                       extra=dict(stage='F3 selective adjacent lifting on F2',
                                  legal=True, adjacent_lifted=lifted,
                                  stats=stats_f3), log=log)
    else:
        f3_records = records
        f3_analysis = C.audit(list(records.values()), ctx)

    # --- save the final best legal F2 --------------------------------------
    report, counts = R2.frozen_validate(records)
    analysis = C.audit(list(records.values()), ctx)
    z2_c4 = F.z2_c4_validation(ctx, records)
    SF.save_scheme(ctx, 'F2_reworked_best_legal', best_folder, records,
                   plan=target_of, baseline_records=baseline_list,
                   extra=dict(stage='incremental legal F2 from E1: NS->L2, '
                                    'EW->L3, Z2 strict C4 L4-L7',
                              legal=int(counts.get('violations') or 0) == 0),
                   log=log)
    if target_records is not records:
        pass
    # --- comparison, figures, report --------------------------------------
    rows = [dict(experiment='E1 baseline', unique=3594, z1=2608, z2=240,
                 high=746, ns_l2=0, ew_l3=0, violations=0,
                 z2_c4=True, hours=27.0060),
            dict(experiment='F2 original initial', unique=10516, z1=8672,
                 z2=0, high=1845, ns_l2=94, ew_l3=86, violations=220,
                 z2_c4=True, hours=26.7943),
            dict(experiment='F2 original local', unique=11697, z1=10332,
                 z2=0, high=1366, ns_l2=88, ew_l3=74, violations=180,
                 z2_c4=True, hours=26.9082),
            dict(experiment='F2 reworked best legal',
                 unique=analysis['n_unique_pairs'],
                 z1=analysis['z1_pairs'], z2=analysis['z2_pairs'],
                 high=analysis['high_pairs'],
                 ns_l2=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_NS'
                           and C.Ctx.route_target_layer(records[rid]) == 2),
                 ew_l3=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_EW'
                           and C.Ctx.route_target_layer(records[rid]) == 3),
                 violations=int(counts.get('violations') or 0),
                 z2_c4=z2_c4.get('symmetry_pass'),
                 hours=analysis.get('fabrication_hours', 0)),
            dict(experiment='F2 target assignment',
                 unique=target_analysis['n_unique_pairs'],
                 z1=target_analysis['z1_pairs'],
                 z2=target_analysis['z2_pairs'],
                 high=target_analysis['high_pairs'],
                 ns_l2=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_NS'
                           and C.Ctx.route_target_layer(target_records[rid]) == 2),
                 ew_l3=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_EW'
                           and C.Ctx.route_target_layer(target_records[rid]) == 3),
                 violations=0 if target_legal else None,
                 z2_c4=F.z2_c4_validation(ctx, target_records).get(
                     'symmetry_pass'),
                 hours=0),
            dict(experiment='F3 follow-up',
                 unique=f3_analysis['n_unique_pairs'],
                 z1=f3_analysis['z1_pairs'], z2=f3_analysis['z2_pairs'],
                 high=f3_analysis['high_pairs'],
                 ns_l2=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_NS'
                           and C.Ctx.route_target_layer(f3_records[rid]) == 2),
                 ew_l3=sum(1 for rid in ctx.z1_opposite
                           if ctx.cat[rid] == 'opposite_z1_EW'
                           and C.Ctx.route_target_layer(f3_records[rid]) == 3),
                 violations=0 if f3_legal else None,
                 z2_c4=F.z2_c4_validation(ctx, f3_records).get(
                     'symmetry_pass'),
                 hours=0)]
    summary = C.read_json(best_folder / 'summary.json')
    rows[3]['hours'] = summary.get('fabrication_hours')
    C.write_csv(OUT / 'comparison.csv', rows)
    C.write_json(OUT / 'comparison.json', dict(rows=rows))
    comparison_figure(ctx, rows, OUT / 'comparison.png')
    before_after_figure(ctx, best_folder, records, baseline)
    before_after_figure(ctx, OUT / 'F2_best_target_assignment', target_records,
                        baseline)
    copy_required(ctx, best_folder)
    copy_required(ctx, OUT / 'F2_best_target_assignment')
    copy_required(ctx, OUT / 'F3_followup')
    for name, folder in (('baseline_E1', OUT / 'baseline_E1'),
                         ('Z2_C4_optimization', OUT / 'Z2_C4_optimization')):
        C.ensure_dir(folder)
    C.write_json(OUT / 'Z2_C4_optimization' / 'z2_c4_validation.json', z2_c4)
    C.write_json(OUT / 'geometry_diagnostics' / 'violation_sources.json',
                 dict(note='all candidate violations were transition_vs_flat'
                           ' edge misses; fixed by frozen-consistent oracle'))
    log('total', round(time.perf_counter() - started, 1), 's')
    C.write_json(OUT / 'finalize_log.json', dict(rows=rows))


if __name__ == '__main__':
    main()
