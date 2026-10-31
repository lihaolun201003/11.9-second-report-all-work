# -*- coding: utf-8 -*-
"""F1/F2/F3 saving, assignment audit and extra figures."""
from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from four_side_1024.e1 import core as C
from four_side_1024.e1 import plots as P
from four_side_1024.e1 import layering as L
from four_side_1024.f123 import core as F

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
LAYER_COLORS = {0.0: '#1f6fd6', 0.5: '#e07b1a', 0.65: '#2f9e44',
                0.8: '#7048e8', 0.95: '#e03131', 1.1: '#0c8599',
                1.25: '#f08c00', 1.4: '#c2255c'}


def layer_z(layer):
    return 0.0 if layer == 1 else C.Z.layer_z(layer)


def _category_layers(ctx, records):
    out = defaultdict(Counter)
    for rid, record in records.items():
        out[ctx.cat[rid]][C.Ctx.route_target_layer(record)] += 1
    return out


def assignment_rows(ctx, records, plan=None, z2_plan=None):
    rows = []
    for rid in sorted(records):
        record = records[rid]
        cat = ctx.cat[rid]
        expected = None
        if plan and rid in plan:
            expected = int(plan[rid])
        elif z2_plan and rid in z2_plan:
            expected = int(z2_plan[rid])
        layer = C.Ctx.route_target_layer(record)
        head, tail = C.Ctx.stubs(record) if layer > 1 else (0.0, 0.0)
        rows.append(dict(route_id=rid, category=cat,
                         expected_layer=expected if expected is not None else '',
                         actual_layer=layer,
                         moved_from_expected=(expected is not None
                                              and layer != expected),
                         base_stub_in_mm=round(head, 3),
                         base_stub_out_mm=round(tail, 3),
                         length_mm=round(float(record.get('length_mm') or 0), 4)))
    return rows


def crossing_sources(analysis):
    rows = []
    for z, info in sorted(analysis['per_height'].items()):
        for key, pairs in sorted((info.get('breakdown') or {}).items()):
            a, _, b = key.partition(' x ')
            rows.append(dict(z_mm=z, category_a=a, category_b=b,
                             unique_crossing_pairs=pairs,
                             crossing_events=0))
    # events by category pair
    counts = Counter()
    for event in analysis['events']:
        counts[(round(event['z'], 6), tuple(sorted((event['cat_a'],
                                                    event['cat_b']))))] += 1
    for row in rows:
        row['crossing_events'] = counts.get(
            (row['z_mm'], (row['category_a'], row['category_b'])), 0)
    return rows


def assignment_summary(ctx, records, plan=None):
    layers = _category_layers(ctx, records)
    summary = {}
    for cat, counter in sorted(layers.items()):
        summary[cat] = dict(sorted(counter.items()))
    expected = {}
    if plan:
        for rid, layer in plan.items():
            cat = ctx.cat[rid]
            expected.setdefault(cat, Counter())[int(layer)] += 1
    return dict(actual=summary,
                expected={cat: dict(c) for cat, c in expected.items()})


def save_scheme(ctx, name, folder, records, *, plan=None, extra=None,
                baseline_records=None, save_figures=True, log=print):
    folder = Path(folder)
    C.ensure_dir(folder)
    records_list = [records[rid] for rid in sorted(records)]
    summary, report, analysis = C.save_experiment(
        name, records_list, ctx, folder=folder, extra=extra,
        validate=True, log=log)
    summary['assignment'] = assignment_summary(ctx, records, plan)
    # strict-C4 audit of the Z2 subsystem (Z1 is asymmetric by design)
    try:
        z2_c4 = F.z2_c4_validation(ctx, records)
    except Exception as exc:
        log(f'  [z2-c4] validation failed: {exc!r}')
        z2_c4 = dict(symmetry_pass=None, error=repr(exc))
    C.write_json(folder / 'z2_c4_validation.json', z2_c4)
    summary['z2_c4_symmetry_pass'] = z2_c4.get('symmetry_pass')
    summary['z2_c4_maximum_xyz_deviation_mm'] = z2_c4.get(
        'maximum_xyz_deviation_mm')
    summary['z2_c4_errors'] = {
        key: z2_c4.get(key) for key in
        ('orbit_size_errors', 'endpoint_rotation_errors',
         'layer_symmetry_errors', 'transition_symmetry_errors',
         'geometry_symmetry_errors')}
    C.write_json(folder / 'summary.json', summary)
    C.write_csv(folder / 'assignment_table.csv',
                assignment_rows(ctx, records, plan))
    C.write_csv(folder / 'crossing_sources.csv',
                crossing_sources(analysis))
    figures_ok = False
    if save_figures:
        try:
            P.standard_figures(folder, records_list, ctx, name,
                               baseline_records=baseline_records,
                               analysis=analysis)
            figures_ok = True
        except Exception as exc:
            log(f'  [figures] {name} failed: {exc!r}')
        try:
            extra_figures(ctx, folder, records, baseline_records, name)
        except Exception as exc:
            log(f'  [extra-figures] {name} failed: {exc!r}')
    return summary, report, analysis, figures_ok


# ---------------------------------------------------------------------------
# extra outcome figures
# ---------------------------------------------------------------------------
def _style(ax):
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.grid(alpha=0.12)


def extra_figures(ctx, folder, records, baseline_records, name):
    figdir = C.ensure_dir(Path(folder) / 'figures')
    layers = _category_layers(ctx, records)
    if isinstance(baseline_records, dict):
        base_layers = _category_layers(ctx, baseline_records)
    elif isinstance(baseline_records, (list, tuple)):
        base_layers = _category_layers(
            ctx, {int(r['route_id']): r for r in baseline_records})
    else:
        base_layers = None

    # 1) NS/EW layer separation
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.0))
    z1_cats = ['opposite_z1_EW', 'opposite_z1_NS']
    z2_cats = ['adjacent_z2', 'same_u_z2', 'opposite_z2_EW', 'opposite_z2_NS']
    for ax, cats, title in ((axes[0], z1_cats, 'Z1 opposite EW / NS'),
                            (axes[1], z2_cats, 'Z2 subsystems')):
        rows = sorted({layer for cat in cats for layer in layers.get(cat, {})})
        width = 0.8 / max(1, len(cats))
        for index, cat in enumerate(cats):
            counter = layers.get(cat, {})
            values = [counter.get(layer, 0) for layer in rows]
            positions = np.arange(len(rows)) + (index - len(cats) / 2) * width
            ax.bar(positions, values, width, label=cat)
        ax.set_xticks(np.arange(len(rows)))
        ax.set_xticklabels([f'L1-Z1' if r == 1 else f'L{r}' for r in rows],
                           rotation=0, fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel('routes')
        ax.legend(fontsize=7)
        ax.grid(alpha=0.2, axis='y')
    fig.suptitle(f'{name}: actual layer assignment (expected vs actual in '
                 f'assignment_table.csv)', fontsize=11)
    P._save(fig, figdir / 'ns_ew_layer_separation.png', dpi=190)

    # 2) adjacent before/after
    base = base_layers.get('adjacent_z1', {}) if base_layers else {}
    now = layers.get('adjacent_z1', {})
    rows = sorted(set(base) | set(now))
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.0))
    positions = np.arange(len(rows))
    axes[0].bar(positions - 0.2, [base.get(r, 0) for r in rows], 0.4,
                label='E1 baseline', color='#868e96')
    axes[0].bar(positions + 0.2, [now.get(r, 0) for r in rows], 0.4,
                label=name, color='#2f9e44')
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(['L1-Z1' if r == 1 else f'L{r}' for r in rows],
                            fontsize=8)
    axes[0].set_ylabel('Z1 adjacent routes')
    axes[0].legend(fontsize=8)
    axes[0].set_title('adjacent route layers (before/after)')
    lifted = {rid for rid, record in records.items()
              if ctx.cat[rid] == 'adjacent_z1'
              and C.Ctx.route_target_layer(record) > 1}
    for rid, record in records.items():
        if ctx.cat[rid] != 'adjacent_z1':
            continue
        z = C.Ctx.route_max_z(record)
        color = '#e03131' if rid in lifted else '#adb5bd'
        width = 1.0 if rid in lifted else 0.35
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or 'primitives' not in part:
                continue
            xs, ys = P.sample_primitives(part['primitives'])
            if len(xs):
                axes[1].plot(xs, ys, color=color, lw=width,
                             alpha=0.85 if rid in lifted else 0.35)
    _style(axes[1])
    axes[1].set_title(f'Z1 adjacent in XY: {len(lifted)} lifted (red) / '
                      f'{len(ctx.z1_adjacent)} total')
    P._save(fig, figdir / 'adjacent_routes_before_after.png', dpi=190)

    # 3) four-corner zoom
    fig, axes = plt.subplots(2, 2, figsize=(12.6, 12.0))
    windows = {'NW corner': (0, 55, 95, 150), 'NE corner': (95, 150, 95, 150),
               'SW corner': (0, 55, 0, 55), 'SE corner': (95, 150, 0, 55)}
    for ax, (label, (x0, x1, y0, y1)) in zip(axes.ravel(), windows.items()):
        for rid, record in records.items():
            if ctx.cat[rid] != 'adjacent_z1':
                continue
            color = '#e03131' if rid in lifted else '#1f6fd6'
            for part in record.get('parts') or []:
                if part['kind'] != 'flat' or 'primitives' not in part:
                    continue
                xs, ys = P.sample_primitives(part['primitives'])
                if len(xs):
                    ax.plot(xs, ys, color=color, lw=0.8, alpha=0.8)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect('equal')
        ax.set_title(f'{label}: Z1 adjacent (red = lifted)', fontsize=9)
        ax.grid(alpha=0.15)
    fig.suptitle(f'{name}: four-corner Z1 adjacent overview '
                 f'({len(lifted)} lifted)', fontsize=11)
    P._save(fig, figdir / 'corner_routes_zoom.png', dpi=190)

    # 4) crossing hotspots alias
    src = figdir / 'edge_crossing_hotspots.png'
    if src.exists():
        shutil.copy2(src, figdir / 'crossing_hotspots.png')
    else:
        fig, ax = plt.subplots(figsize=(7.4, 7.0))
        analysis = C.audit(list(records.values()), ctx)
        events = [e for e in analysis['events'] if e['z'] <= 0.5]
        if events:
            ax.hexbin([e['x'] for e in events], [e['y'] for e in events],
                      gridsize=40, cmap='Reds', mincnt=1)
        _style(ax)
        ax.set_title(f'{name}: interface crossing hotspots')
        P._save(fig, figdir / 'crossing_hotspots.png', dpi=190)


def comparison_figure(folder, rows):
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.4))
    keys = [('unique_crossing_pairs', 'global unique crossing pairs'),
            ('z1_crossing_pairs', 'Z1 interface pairs'),
            ('z2_crossing_pairs', 'Z2 interface pairs'),
            ('fabrication_hours', 'fabrication time (h)')]
    labels = [row['experiment'] for row in rows]
    for ax, (key, title) in zip(axes.ravel(), keys):
        values = [row.get(key) or 0 for row in rows]
        colors = ['#868e96' if row.get('kind') == 'baseline' else '#1971c2'
                  for row in rows]
        bars = ax.bar(labels, values, color=colors)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis='x', rotation=20, labelsize=8)
        ax.grid(alpha=0.2, axis='y')
        for rect, value in zip(bars, values):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(),
                    f'{value:.0f}' if value >= 10 else f'{value:.2f}',
                    ha='center', va='bottom', fontsize=7)
    fig.suptitle('F1/F2/F3 layer-strategy experiments (grey = E1 baseline)',
                 fontsize=12)
    fig.tight_layout()
    path = Path(folder) / 'comparison.png'
    fig.savefig(path, dpi=190, bbox_inches='tight')
    plt.close(fig)
    return path
