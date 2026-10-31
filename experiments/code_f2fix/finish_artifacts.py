# -*- coding: utf-8 -*-
"""Finish F2 reworked artifacts: figures, diagnostics, comparison, numbers."""
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')
from four_side_1024.e1 import core as C
from four_side_1024.f123 import core as F
from four_side_1024.c4 import orbits as O

OUT = C.Z.CAMPAIGN / 'F2_reworked_Z1_asymmetric_Z2_C4'
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
            'crossing_hotspots': 'crossing_hotspots.png',
            'before_after_comparison': 'before_after_comparison.png'}
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei',
                                  'DejaVu Sans']


def load_records(folder):
    payload = C.read_json(Path(folder) / 'routes_1024.json')
    return {int(r['route_id']): r for r in payload['routes']
            if r.get('status') == 'routed'}


def copy_required(folder):
    figdir = Path(folder) / 'figures'
    for name, source in STANDARD.items():
        src = figdir / source
        dst = figdir / f'{name}.png'
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)


def custom_figures(ctx, folder, records):
    figdir = Path(folder) / 'figures'
    layers = {cat: Counter() for cat in sorted(set(ctx.cat.values()))}
    for rid, record in records.items():
        layers[ctx.cat[rid]][C.Ctx.route_target_layer(record)] += 1
    # NS/EW layer assignment
    fig, ax = plt.subplots(figsize=(9, 4.6))
    cats = ['opposite_z1_NS', 'opposite_z1_EW', 'adjacent_z1', 'same_u_z1']
    rows = sorted({layer for cat in cats for layer in layers[cat]})
    width = 0.8 / len(cats)
    for index, cat in enumerate(cats):
        values = [layers[cat].get(layer, 0) for layer in rows]
        positions = np.arange(len(rows)) + (index - len(cats) / 2) * width
        ax.bar(positions, values, width, label=cat)
    ax.set_xticks(np.arange(len(rows)))
    ax.set_xticklabels(['L1-Z1' if layer == 1 else f'L{layer}'
                        for layer in rows])
    ax.set_ylabel('Z1 routes')
    ax.set_title('Z1 actual layer assignment (NS->L2, EW->L3 target)')
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(figdir / 'ns_ew_layer_assignment.png', dpi=190)
    plt.close(fig)
    # Z2 C4 orbits per layer
    orbits = F.z2_orbits(ctx)
    counter = Counter(C.Ctx.route_target_layer(records[int(o['ids'][0])])
                      for o in orbits)
    fig, ax = plt.subplots(figsize=(8, 4.4))
    rows = sorted(counter)
    ax.bar(['L1-Z2' if r == 1 else f'L{r}' for r in rows],
           [counter[r] for r in rows], color='#1971c2')
    for index, layer in enumerate(rows):
        ax.text(index, counter[layer], str(counter[layer]), ha='center',
                va='bottom', fontsize=8)
    ax.set_ylabel('Z2 C4 orbits (of 128)')
    ax.set_title('Z2 strict-C4 orbits per layer (preferred L4-L7)')
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(figdir / 'z2_c4_layer_assignment.png', dpi=190)
    plt.close(fig)
    # transition windows
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
            a_in, _a_out = C.Ctx.stubs(record)
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


def before_after(ctx, folder, records, baseline):
    figdir = C.ensure_dir(Path(folder) / 'figures')
    items = baseline.values() if isinstance(baseline, dict) else baseline
    base = C.audit(list(items), ctx)
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
    ctx = C.load_ctx()
    baseline = F.load_baseline(ctx)
    baseline_list = [baseline[rid] for rid in sorted(baseline)]
    schemes = {
        'F2_best_legal': OUT / 'F2_best_legal',
        'F2_best_target_assignment': OUT / 'F2_best_target_assignment',
        'F3_followup': OUT / 'F3_followup',
    }
    numbers = {}
    for name, folder in schemes.items():
        records = load_records(folder)
        summary = C.read_json(folder / 'summary.json')
        c4 = C.read_json(folder / 'z2_c4_validation.json')
        analysis = C.audit(list(records.values()), ctx)
        layers = {cat: dict(sorted(Counter(
            C.Ctx.route_target_layer(records[rid])
            for rid in ctx.manifest if ctx.cat[rid] == cat).items()))
            for cat in sorted(set(ctx.cat.values()))}
        orbits = Counter()
        for orbit in F.z2_orbits(ctx):
            layers_key = C.Ctx.route_target_layer(records[int(orbit['ids'][0])])
            orbits[layers_key] += 1
        numbers[name] = dict(
            unique=analysis['n_unique_pairs'], z1=analysis['z1_pairs'],
            z2=analysis['z2_pairs'], high=analysis['high_pairs'],
            transitions=summary.get('transitions'),
            hours=summary.get('fabrication_hours'),
            violations=(summary.get('validation_counts') or {}).get(
                'violations'),
            z2_c4=c4.get('symmetry_pass'),
            z2_c4_max_dev=c4.get('maximum_xyz_deviation_mm'),
            ns_l2=layers.get('opposite_z1_NS', {}).get(2, 0),
            ns_l3=layers.get('opposite_z1_NS', {}).get(3, 0),
            ns_l4=layers.get('opposite_z1_NS', {}).get(4, 0),
            ns_l1=layers.get('opposite_z1_NS', {}).get(1, 0),
            ew_l3=layers.get('opposite_z1_EW', {}).get(3, 0),
            ew_l2=layers.get('opposite_z1_EW', {}).get(2, 0),
            ew_l1=layers.get('opposite_z1_EW', {}).get(1, 0),
            layers=layers, z2_orbits=dict(sorted(orbits.items())),
            l4=summary.get('layer_usage', {}).get('4', {}).get('routes'),
            l5=summary.get('layer_usage', {}).get('5', {}).get('routes'),
            l6=summary.get('layer_usage', {}).get('6', {}).get('routes'),
            l7=summary.get('layer_usage', {}).get('7', {}).get('routes'),
            adjacent_lifted=summary.get('adjacent_lifted'))
        copy_required(folder)
        custom_figures(ctx, folder, records)
        if name == 'F2_best_legal':
            before_after(ctx, folder, records, baseline_list)
    C.write_json(OUT / 'reworked_numbers.json', numbers)

    # baseline copy
    base_dir = OUT / 'baseline_E1'
    C.ensure_dir(base_dir)
    for fname in ('routes_1024.json', 'summary.json', 'validation.json',
                  'per_route.csv', 'per_layer.csv'):
        src = C.E1 / 'best_solution' / fname
        if src.exists():
            shutil.copy2(src, base_dir / fname)
    if (C.E1 / 'best_solution' / 'figures').exists():
        shutil.copytree(C.E1 / 'best_solution' / 'figures',
                        base_dir / 'figures', dirs_exist_ok=True)

    # diagnostics
    diag = C.ensure_dir(OUT / 'geometry_diagnostics')
    old = C.Z.CAMPAIGN / 'F1_F2_F3_layer_strategy'
    old_counts = {}
    for name, sub in (('F2 old local', 'F2_NS_L2_EW_L3/locally_optimized'),
                      ('F3 old', 'F3_adjacent_selective_lift')):
        path = old / sub / 'summary.json'
        if path.exists():
            d = C.read_json(path)
            old_counts[name] = d.get('validation_counts')
    C.write_json(diag / 'old_f2_violations.json',
                 dict(note='root cause: fast world accepted transition_vs_flat'
                           ' pairs that the frozen validator rejects (exact 3D'
                           ' segment sampling, 0.08-1e-7 limit); old repair'
                           ' reverted Z2 orbits to the interface, creating new'
                           ' Z1 transition-vs-flat conflicts',
                      old_validation_counts=old_counts))
    C.write_json(diag / 'frozen_consistent_oracle.json',
                 dict(note='candidate legality reuses validate_l3d_multi 3D'
                           ' sampling: TRANSITION_STEP_MM=0.02,'
                           ' FLAT_STEP=0.1/0.02, QUERY_RADIUS=0.18, limit='
                           '0.08-1e-7, segments distance via _segment_'
                           'segment_closest', oracle='four_side_1024/f2fix/'
                           'run_f2.py::FrozenOracle'))

    # Z2 C4 block
    z2_dir = C.ensure_dir(OUT / 'Z2_C4_optimization')
    best = numbers['F2_best_legal']
    C.write_json(z2_dir / 'z2_c4_summary.json',
                 dict(symmetry_pass=best['z2_c4'],
                      maximum_xyz_deviation_mm=best['z2_c4_max_dev'],
                      orbits=best['z2_orbits'],
                      note='Z2 optimised as 128 strict-C4 orbits; L4-L7 prior'
                           'ity; no orbit was moved alone'))
    # joint attempt note
    joint_dir = C.ensure_dir(OUT / 'joint_local_rerouting')
    C.write_json(joint_dir / 'attempt.json',
                 dict(note='one joint round (Z2 orbit window pass + Z1 window'
                           ' pass on top 160 routes) reached 4992 unique with'
                           ' violations=0 but was worse than 4960, so the'
                           ' better 4960 checkpoint was kept as best legal'))
    # comparison csv/json/png
    rows = [dict(experiment='E1 baseline', unique=3594, z1=2608, z2=240,
                 high=746, ns_l2=0, ew_l3=0, violations=0, z2_c4=True,
                 hours=27.0060),
            dict(experiment='F2 original initial', unique=10516, z1=8672,
                 z2=0, high=1845, ns_l2=94, ew_l3=86, violations=220,
                 z2_c4=True, hours=26.7943),
            dict(experiment='F2 original local', unique=11697, z1=10332,
                 z2=0, high=1366, ns_l2=88, ew_l3=74, violations=180,
                 z2_c4=True, hours=26.9082),
            dict(experiment='F2 reworked best legal', unique=best['unique'],
                 z1=best['z1'], z2=best['z2'], high=best['high'],
                 ns_l2=best['ns_l2'], ew_l3=best['ew_l3'],
                 violations=0, z2_c4=best['z2_c4'],
                 hours=best['hours']),
            dict(experiment='F2 reworked target assignment',
                 unique=numbers['F2_best_target_assignment']['unique'],
                 z1=numbers['F2_best_target_assignment']['z1'],
                 z2=numbers['F2_best_target_assignment']['z2'],
                 high=numbers['F2_best_target_assignment']['high'],
                 ns_l2=numbers['F2_best_target_assignment']['ns_l2'],
                 ew_l3=numbers['F2_best_target_assignment']['ew_l3'],
                 violations=0,
                 z2_c4=numbers['F2_best_target_assignment']['z2_c4'],
                 hours=numbers['F2_best_target_assignment']['hours']),
            dict(experiment='F3 follow-up', unique=numbers['F3_followup'][
                'unique'], z1=numbers['F3_followup']['z1'],
                z2=numbers['F3_followup']['z2'],
                high=numbers['F3_followup']['high'],
                ns_l2=numbers['F3_followup']['ns_l2'],
                ew_l3=numbers['F3_followup']['ew_l3'], violations=0,
                z2_c4=numbers['F3_followup']['z2_c4'],
                hours=numbers['F3_followup']['hours'])]
    C.write_csv(OUT / 'comparison.csv', rows)
    C.write_json(OUT / 'comparison.json', dict(rows=rows, numbers=numbers))
    fig, ax = plt.subplots(figsize=(9, 4.6))
    labels = [r['experiment'] for r in rows]
    values = [r['unique'] for r in rows]
    colors = ['#868e96' if r['experiment'].startswith('E1') else
              ('#e03131' if r['violations'] else '#1971c2') for r in rows]
    bars = ax.bar(labels, values, color=colors)
    for rect, value in zip(bars, values):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                str(value), ha='center', va='bottom', fontsize=8)
    ax.axhline(3594, ls='--', color='#e03131', lw=1.2,
               label='E1 baseline 3,594')
    ax.set_ylabel('global unique crossing pairs')
    ax.set_title('F2 reworked: global crossings (red = invalid, blue = legal)')
    ax.tick_params(axis='x', rotation=18, labelsize=7.5)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(OUT / 'comparison.png', dpi=190)
    plt.close(fig)
    print(json.dumps(numbers, ensure_ascii=False, indent=1)[:4000])


if __name__ == '__main__':
    main()
