# -*- coding: utf-8 -*-
"""P1 campaign: bundle-level corridor / layer planning vs per-route planning.

Stages:
  --stage 2d : identical-budget overrides of the 2D phase (easy order vs
               automatic bundle order) on the 992/1024 layout;
  --stage 3d : bundle-aware 3D lift (bundle-first order + bundle layer
               preference) for 5/7/11/15 layers, compared to the per-route
               greedy lift of the previous campaign (same 2D input);
  --stage all: both.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4.profile import apply as apply_profile  # noqa: E402
apply_profile()

from four_side_1024.bundle3d import bundle_lift as BL  # noqa: E402
from four_side_1024.bundle3d.corridors import write_bundle_plan  # noqa: E402
from four_side_1024.bundle3d import visualize as VZ  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
PLAN_DIR = CAMPAIGN / '02_bundle_planning'
FIGS = CAMPAIGN / 'figures'
LAYER_COUNTS = [11, 15]  # 5L/7L baseline still available from the previous campaign; bundle-lift runs on 11L/15L for compute budget
PLANES = ['z1', 'z2']


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def load_bundles():
    payload = json.loads((CAMPAIGN / '01_bundle_grouping/bundles.json')
                         .read_text(encoding='utf-8'))
    bundles = payload['bundles']
    if isinstance(bundles, dict):
        return [bundle for plane in PLANES for bundle in bundles.get(plane, [])]
    return bundles


def build_plan(bundles):
    plan = write_bundle_plan(PLAN_DIR / 'bundle_plan.json', PLANES, bundles,
                             LAYER_COUNTS)
    return plan


def bundle_order_for_plane(bundles, plane):
    """Deterministic bundle-first group order for one plane."""
    plane_bundles = [(index, bundle) for index, bundle in enumerate(bundles)
                     if bundle['plane'] == plane]
    kind_rank = {'opposite': 0, 'same': 1, 'adjacent': 2}

    def key(item):
        index, bundle = item
        centre = bundle['bbox']['centre']
        return (kind_rank.get(bundle['dominant_kind'], 9), centre[1], centre[0],
                index)

    order = []
    for index, bundle in sorted(plane_bundles, key=key):
        order.extend(sorted(int(orbit_id) for orbit_id in bundle['orbit_ids']))
    return order


def combine_planes(phase2_dir, tag):
    from four_side_1024.manual_c4 import run2d
    summary = run2d.combine(phase2_dir=phase2_dir, log=print)
    (PLAN_DIR / f'phase2_{tag}_combine.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    return summary


def stage_2d(bundles):
    from four_side_1024.manual_c4 import run2d
    results = {}
    for tag, order_mode, override in (
            ('baseline_easy', 'easy', None),
            ('bundle_order', 'bundle_first', 'override')):
        outcome = {}
        for plane in PLANES:
            out_dir = PLAN_DIR / f'phase2_{tag}' / plane
            started = time.perf_counter()
            if tag == 'bundle_order':
                by_gid = {int(group['group_id']): group
                          for group in CONN.groups_for_plane(plane)}
                order = [by_gid[group_id] for group_id in
                         bundle_order_for_plane(bundles, plane)
                         if group_id in by_gid]
            else:
                order = None
            run2d.run_plane(
                plane, order_mode, 1600, out_dir,
                rr_rounds=0, retry_passes=0, time_limit=700,
                order_override=order)
            routes = json.loads((out_dir / 'routes.json').read_text(
                encoding='utf-8'))
            routed = sum(1 for record in routes['routes']
                         if record.get('status') == 'routed')
            outcome[plane] = dict(routed=routed,
                                  seconds=round(time.perf_counter() - started, 1))
        combined = combine_planes(PLAN_DIR / f'phase2_{tag}', tag)
        crossings = (combined or {}).get('plane_crossings', {})
        pairs = sum(item.get('crossing_pair_count', 0)
                    for item in crossings.values()) if crossings else None
        outcome['combined'] = dict(
            routed=(combined or {}).get('routed'),
            unique_crossing_pairs=pairs,
            plane_crossings=crossings)
        results[tag] = outcome
        print(f'[p1-2d] {tag}: routed={outcome["combined"]["routed"]} '
              f'pairs={pairs} ({outcome})', flush=True)
    (PLAN_DIR / 'phase2_comparison.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    return results


def stage_3d(bundles, plan):
    results = {'baseline': {}, 'bundle': {}, 'adherence': {}}
    selected_2d = OLD / 'phase2_2d_selected'
    for layer_count in LAYER_COUNTS:
        base_lift = OLD / f'02_layer_sweep/L{layer_count}/lift'
        base = BL.read_lift_result(base_lift)
        if base is not None:
            results['baseline'][layer_count] = dict(
                routed=base['routed'], pairs=base['pairs'],
                violations=base['violations'],
                lifted_groups=base['summary'].get('lifted_groups'),
                transitions=base['summary'].get('transitions'))
        # assemble bundle plan for this layer count
        preferred = {}
        for plane in PLANES:
            plane_plan = plan['planes'][plane]['plans'][str(layer_count)]
            for orbit_id, layer_id in plane_plan['orbit_layers'].items():
                preferred[int(orbit_id)] = int(layer_id)
        order = []
        for plane in PLANES:
            order.extend(bundle_order_for_plane(bundles, plane))
        out_dir = PLAN_DIR / f'lift_bundle/L{layer_count}_bundle'
        started = time.perf_counter()
        BL.run_bundle_lift(selected_2d, out_dir, layer_count,
                           preferred_layers=preferred, bundle_order=order,
                           max_groups=300, time_limit=480)
        bundle = BL.read_lift_result(out_dir)
        # adherence: which lifted groups used the planned layer
        plans = json.loads((out_dir / 'lift_plans.json').read_text(
            encoding='utf-8'))
        lifted = plans.get('lifted') or []
        matched = 0
        deviated = 0
        no_pref = 0
        for item in lifted:
            group_id = int(item.get('group_id'))
            want = preferred.get(group_id)
            if want is None:
                no_pref += 1
            elif int(item.get('layer_id')) == int(want):
                matched += 1
            else:
                deviated += 1
        results['bundle'][layer_count] = dict(
            routed=bundle['routed'], pairs=bundle['pairs'],
            violations=bundle['violations'],
            lifted_groups=bundle['summary'].get('lifted_groups'),
            transitions=bundle['summary'].get('transitions'),
            seconds=round(time.perf_counter() - started, 1))
        results['adherence'][layer_count] = dict(
            lifted_groups=len(lifted), matched=matched, deviated=deviated,
            no_preference=no_pref,
            matched_ratio=round(matched / max(1, matched + deviated), 4))
        print(f'[p1-3d] L{layer_count}: baseline={results["baseline"].get(layer_count)} '
              f'bundle={results["bundle"][layer_count]} '
              f'adherence={results["adherence"][layer_count]}', flush=True)
    (PLAN_DIR / 'lift_comparison.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    return results


def figure_layer_plan(plan, bundles):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    counts = LAYER_COUNTS
    fig, axes = plt.subplots(2, len(counts), figsize=(5.6 * len(counts), 10.6))
    layer_colors = BL.PALETTE
    for column, layer_count in enumerate(counts):
        for row, plane in enumerate(PLANES):
            ax = axes[row][column]
            plane_bundles = [(index, bundle) for index, bundle in
                             enumerate(bundles) if bundle['plane'] == plane]
            plan_entries = plan['planes'][plane]['plans'][str(layer_count)]
            assignment = {int(key): value for key, value in
                          plan_entries['bundle_assignment'].items()}
            for index, bundle in plane_bundles:
                box = bundle['bbox']
                layer = assignment.get(index, 2)
                ax.add_patch(Rectangle(
                    (box['min_x'], box['min_y']),
                    max(1.0, box['max_x'] - box['min_x']),
                    max(1.0, box['max_y'] - box['min_y']),
                    fill=True, alpha=0.30,
                    edgecolor=layer_colors.get(layer, '#495057'), lw=1.0))
                ax.text(box['min_x'], box['min_y'], str(index), fontsize=4.5,
                        color='#343a40')
            ax.set_xlim(0, 150)
            ax.set_ylim(0, 150)
            ax.set_aspect('equal')
            ax.set_title(f'{plane} {layer_count}L: bundle -> layer', fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGS / 'fig08_bundle_layer_plan.png', dpi=170)
    plt.close(fig)


def figure_method_comparison(lift_results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    baseline = lift_results.get('baseline', {})
    bundle = lift_results.get('bundle', {})
    counts = [count for count in LAYER_COUNTS
              if count in baseline and count in bundle]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    x = range(len(counts))
    width = 0.36
    axes[0].bar([value - width / 2 for value in x],
                [baseline[count]['pairs'] for count in counts], width,
                label='per-route greedy lift (A)', color='#adb5bd')
    axes[0].bar([value + width / 2 for value in x],
                [bundle[count]['pairs'] for count in counts], width,
                label='bundle-aware lift (C)', color='#1971c2')
    axes[0].set_xticks(list(x), [f'{count}L' for count in counts])
    axes[0].set_ylabel('global unique crossing pairs')
    axes[0].set_title('bundle-level layer planning vs per-route lift')
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.2, axis='y')
    deltas = [bundle[count]['pairs'] - baseline[count]['pairs']
              for count in counts]
    axes[1].bar(list(x), deltas, color=['#2f9e44' if value < 0 else '#e03131'
                                        for value in deltas])
    axes[1].set_xticks(list(x), [f'{count}L' for count in counts])
    axes[1].set_ylabel('crossing pairs delta (C - A)')
    axes[1].set_title('bundle-aware gain per layer count')
    axes[1].grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(FIGS / 'fig09_method_comparison.png', dpi=175)
    plt.close(fig)


def main():
    stage = 'all'
    for argument in sys.argv[1:]:
        if argument.startswith('--stage'):
            stage = argument.split('=')[-1]
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    patch_conn()
    bundles = load_bundles()
    plan = build_plan(bundles)
    summary = {}
    if stage in ('2d', 'all'):
        summary['phase2'] = stage_2d(bundles)
    if stage in ('3d', 'all'):
        summary['lift'] = stage_3d(bundles, plan)
    figure_layer_plan(plan, bundles)
    if 'lift' in summary:
        figure_method_comparison(summary['lift'])
    (PLAN_DIR / 'p1_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
