# -*- coding: utf-8 -*-
"""U-bundle / corner-bottleneck analysis on the new-manual-CSV campaign.

Outputs (under 04_z1_multilayer/ and 11_corner_radius_analysis/):
  * same-side U group statistics (separation, per-side counts, bulge capacity);
  * straight-segment availability vs 3D transition footprint for every layer
    (which U / adjacent / opposite groups can be lifted to which layer);
  * isolation routing test of the still-unrouted groups (empty board, extended
    U bulge family) -> separates 'conflict-limited' from 'template-limited';
  * markdown summary + figures.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def seg_lengths(record):
    lengths = []
    for primitive in record.get('primitives') or []:
        kind = primitive.get('kind')
        if kind == 'line':
            p0 = primitive.get('p0');
            p1 = primitive.get('p1')
            lengths.append(float(math_dist(p0, p1)))
        elif kind in ('arc', 'fillet'):
            try:
                lengths.append(abs(float(primitive['sweep'])) * float(
                    primitive['radius']))
            except Exception:  # noqa: BLE001
                pass
    return lengths


def math_dist(p0, p1):
    import math
    return math.hypot(float(p0[0]) - float(p1[0]),
                      float(p0[1]) - float(p1[1]))


def main():
    patch_conn()
    from four_side_1024.v3c4.lift_cross import transition_geometry
    from four_side_1024.l3d import layers as LL
    selection = CAMPAIGN / 'phase2_2d_selected'
    payload = json.loads((selection / 'routes_1024.json').read_text(
        encoding='utf-8'))
    records = {int(r['route_id']): r for r in payload['routes']}
    topology = CONN.combined_topology()
    groups = {int(g['group_id']): g for g in topology['groups']}
    eps = CONN.endpoints()
    chosen = json.loads((selection / 'selection.json').read_text(
        encoding='utf-8'))
    plane_routed = {plane: info['routed'] for plane, info in
                    chosen['chosen'].items()}
    out_dir = CAMPAIGN / '04_u_bundle_analysis'
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / 'figures'
    fig_dir.mkdir(exist_ok=True)

    # ---- layer heights / footprints -------------------------------------
    heights = {2 + index: round(0.65 + 0.15 * index, 3)
               for index in range(0, 14)}
    base_z = {'z1': 0.0, 'z2': 0.5}
    footprints = {}
    for layer_id, z in heights.items():
        footprints[layer_id] = {}
        for plane, z0 in base_z.items():
            geometry = transition_geometry(z - z0)
            footprints[layer_id][plane] = float(
                geometry.get('footprint_mm') if isinstance(geometry, dict)
                else geometry)

    # ---- straight availability per group --------------------------------
    group_report = {}
    for gid, group in groups.items():
        rid_list = [int(r) for r in group['route_ids']]
        straight = {}
        for rid in rid_list:
            record = records.get(rid)
            if record is None or record.get('status') != 'routed':
                straight[rid] = None
                continue
            lengths = seg_lengths(record)
            straight[rid] = dict(max_straight_mm=round(max(lengths), 3)
                                 if lengths else 0.0)
        ok_layers = []
        if all(value for value in straight.values()):
            min_straight = min(value['max_straight_mm']
                               for value in straight.values())
            for layer_id, z in heights.items():
                footprint = footprints[layer_id][group['plane']]
                if min_straight >= footprint + 1.2 + 0.25:
                    ok_layers.append(layer_id)
        group_report[gid] = dict(
            plane=group['plane'], kind=group['kind'], pair=group['pair'],
            route_ids=rid_list, straight=straight,
            liftable_layers=ok_layers)
    # ---- per-side U statistics -----------------------------------------
    per_side = defaultdict(lambda: dict(groups=0, routes=0, separations=[]))
    for gid, group in groups.items():
        if group['kind'] != 'same':
            continue
        rep = records[int(group['route_ids'][0])]
        side = rep['source_side']
        entry = per_side[side]
        entry['groups'] += 1
        entry['routes'] += 4
        e1 = eps[rep['source_endpoint']]['routing_xy']
        e2 = eps[rep['target_endpoint']]['routing_xy']
        separation = (abs(e1[0] - e2[0]) if side in 'NS'
                      else abs(e1[1] - e2[1]))
        entry['separations'].append(round(float(separation), 3))
    for entry in per_side.values():
        entry['separations'].sort()
        entry['min_separation_mm'] = entry['separations'][0]
        entry['max_separation_mm'] = entry['separations'][-1]
        entry['midline_coverage'] = len(entry['separations'])
    # ---- isolation test of unrouted groups -----------------------------
    from four_side_1024.d56.index import prepare
    from four_side_1024.manual_c4.router import ManualGroupRouter
    from four_side_1024.manual_c4 import router as ROUTER
    from four_side_1024.manual_c4.state import state_for
    extended = [round(0.25 * i, 3) for i in range(0, 561)] + [130.0, 135.0, 140.0]
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = extended
    isolation = []
    try:
        for plane in ('z1', 'z2'):
            plane_groups = [groups[gid] for gid in sorted(groups)
                            if groups[gid]['plane'] == plane]
            failed_groups = [g for g in plane_groups
                             if any(records[int(rid)].get('status') != 'routed'
                                    for rid in g['route_ids'])]
            if not failed_groups:
                continue
            state = state_for(plane, log=lambda *a: None)
            router = ManualGroupRouter(state, plane_groups,
                                       log=lambda *a: None)
            for group in failed_groups:
                results, failure, stats = router.attempt_group(group, 20000)
                isolation.append(dict(
                    plane=plane, group_id=group['group_id'],
                    kind=group['kind'], pair=group['pair'],
                    route_ids=[int(r) for r in group['route_ids']],
                    routed_in_isolation=results is not None,
                    evaluated=(failure or {}).get('evaluated') if results is None
                    else stats.get('evaluated'),
                    rejection_counts=(failure or {}).get('rejection_counts')))
    finally:
        ROUTER.BULGE_LADDER = old_ladder
    iso_success = sum(1 for item in isolation if item['routed_in_isolation'])
    # ---- write -----------------------------------------------------------
    report = dict(
        schema='new_manual_u_bundle_analysis_v1',
        layer_footprints_mm={str(k): v for k, v in footprints.items()},
        per_side_u=dict(per_side),
        group_liftability={str(k): dict(plane=v['plane'], kind=v['kind'],
                                        liftable_layers=v['liftable_layers'])
                           for k, v in group_report.items()},
        isolation=isolation,
        isolation_summary=dict(tested=len(isolation),
                               routed_in_isolation=iso_success,
                               template_or_template_conflict=len(isolation)
                               - iso_success),
        plane_routed=plane_routed)
    (out_dir / 'u_bundle_analysis.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')

    # figures
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for side, entry in sorted(per_side.items()):
        ax.hist(entry['separations'], bins=24, alpha=0.55, label=f'{side} side')
    ax.set_xlabel('same-side U port separation (mm)')
    ax.set_ylabel('C4 U groups')
    ax.set_title('new manual CSV: same-side U separations per board side')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(fig_dir / 'fig01_u_separation_hist.png', dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.6))
    layers = sorted(heights)
    counts = []
    for layer_id in layers:
        count = sum(1 for gid, group in groups.items()
                    if group['kind'] == 'same'
                    and layer_id in group_report[gid]['liftable_layers'])
        counts.append(count)
    ax.bar([f'L{layer_id}' for layer_id in layers], counts, color='#1971c2')
    ax.set_ylabel('U groups liftable (all 4 routes have a straight >= footprint)')
    ax.set_title('same-side U liftability per target layer')
    ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(fig_dir / 'fig02_u_liftability.png', dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.6))
    kinds = Counter(item['kind'] for item in isolation)
    status = Counter('isolated_ok' if item['routed_in_isolation']
                     else 'isolated_fail' for item in isolation)
    labels = sorted(set(kinds))
    ok = [sum(1 for item in isolation
              if item['kind'] == kind and item['routed_in_isolation'])
          for kind in labels]
    fail = [sum(1 for item in isolation
                if item['kind'] == kind and not item['routed_in_isolation'])
            for kind in labels]
    ax.bar(labels, ok, label='routable in isolation (conflict-limited)',
           color='#2f9e44')
    ax.bar(labels, fail, bottom=ok,
           label='not routable even in isolation (template-limited)',
           color='#e03131')
    ax.set_ylabel('unrouted C4 groups')
    ax.set_title('failure classification of the still-unrouted groups')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / 'fig03_isolation_classification.png', dpi=170)
    plt.close(fig)
    print(json.dumps(dict(plane_routed=plane_routed,
                          isolation_summary=report['isolation_summary'],
                          per_side={k: dict(groups=v['groups'],
                                            routes=v['routes'],
                                            min_sep=v['min_separation_mm'],
                                            max_sep=v['max_separation_mm'])
                                    for k, v in per_side.items()}),
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
