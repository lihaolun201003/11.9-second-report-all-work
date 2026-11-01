# -*- coding: utf-8 -*-
"""P0 campaign: automatic bundle grouping of the 1024 new-manual connections.

Outputs (under outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/):
  inputs/                  snapshot of authoritative CSVs + connectivity table
  inputs/SHA256SUMS.txt
  01_bundle_grouping/      features, compatibility graph, bundles (3 methods),
                           summary + figures
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4.profile import apply as apply_profile  # noqa: E402
apply_profile()

from four_side_1024.bundle3d import (  # noqa: E402
    build_features, build_orbits, build_graph,
    graph_clustering, corridor_clustering, kind_pure_clustering,
    evaluate_bundles)
from four_side_1024.bundle3d import visualize as VZ  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402

OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'BUNDLE_AWARE_NATIVE_3D')
GROUP_DIR = CAMPAIGN / '01_bundle_grouping'
FIGS = CAMPAIGN / 'figures'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def snapshot_inputs():
    inputs = CAMPAIGN / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    source_files = [
        (ROOT / 'manual_z1_router/data/exports/manual_z1_c4_full_section2.csv',
         'manual_z1_c4_full_section2.csv'),
        (ROOT / 'manual_z1_router/data/exports/manual_z2_c4_full_section2.csv',
         'manual_z2_c4_full_section2.csv'),
        (OLD / 'inputs/connectivity_1024.csv', 'connectivity_1024.csv'),
        (OLD / 'inputs/connectivity_1024.json', 'connectivity_1024.json'),
        (OLD / 'phase2_2d_selected/routes_1024.json',
         'baseline_2d_routes_992.json'),
    ]
    sums = []
    for source, name in source_files:
        target = inputs / name
        if not target.exists():
            shutil.copyfile(source, target)
        sums.append(f'{sha256(target)}  {name}')
    (inputs / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n',
                                           encoding='utf-8')
    return dict(files=[line.split('  ')[1] for line in sums],
                sha256=[line.split('  ')[0] for line in sums])


def score_method(summary):
    """Selection score for the automatic grouping (higher is better)."""
    size = summary['size_orbits']['mean']
    size_penalty = min(1.0, abs(size - 10.0) / 10.0)
    count_ok = 1.0 if 12 <= summary['bundle_count'] <= 64 else 0.0
    return (0.35 * (1.0 - min(1.0, summary['internal_cross_rate'] * 4.0))
            + 0.25 * summary['mean_compatibility']
            + 0.20 * (1.0 - size_penalty)
            + 0.20 * count_ok)


def main():
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    GROUP_DIR.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    input_snapshot = snapshot_inputs()
    patch_conn()
    topology = CONN.combined_topology()
    routes = topology['routes']
    groups = topology['groups']
    endpoints = CONN.endpoints()
    features, group_of_route, c4_groups = build_features(
        CONN, endpoints, routes, groups)
    orbits = build_orbits(features, group_of_route, c4_groups)
    adjacency, edges = build_graph(orbits)
    planes = ('z1', 'z2')
    methods = {}
    raw = {}
    method_fns = {
        'graph_clustering_A': lambda plane: graph_clustering(
            orbits, adjacency, plane),
        'graph_mixed_A2': lambda plane: graph_clustering(
            orbits, adjacency, plane, tau=0.40),
        'corridor_clustering_B': lambda plane: corridor_clustering(
            orbits, adjacency, plane),
        'kind_pure_baseline_C': lambda plane: kind_pure_clustering(
            orbits, plane, size=8),
    }
    for method_name, fn in method_fns.items():
        bundles_by_plane = {}
        summaries = {}
        metric_rows = {}
        for plane in planes:
            clusters = fn(plane)
            rows, summary = evaluate_bundles(orbits, clusters, adjacency, plane)
            bundles_by_plane[plane] = rows
            metric_rows[plane] = rows
            summaries[plane] = summary
        combined = dict(
            plane_summaries=summaries,
            bundle_count=sum(summary['bundle_count']
                             for summary in summaries.values()),
            total_connections=sum(summary['total_connections']
                                  for summary in summaries.values()),
            internal_cross_rate=float(sum(
                summaries[plane]['internal_cross_rate']
                * summaries[plane]['internal_cross_pairs']
                for plane in planes)
                / max(1, sum(summaries[plane]['internal_cross_pairs']
                             for plane in planes)
                      or 1)),
            mean_compatibility=float(sum(
                summaries[plane]['mean_compatibility']
                for plane in planes) / len(planes)),
            size_orbits=dict(
                mean=float(sum(summaries[plane]['size_orbits']['mean']
                               for plane in planes) / len(planes)),
                min=min(summaries[plane]['size_orbits']['min']
                        for plane in planes),
                max=max(summaries[plane]['size_orbits']['max']
                        for plane in planes)),
            kind_mix=dict(Counter(
                kind for plane in planes
                for kind, count in summaries[plane]['kind_mix'].items()
                for _ in range(count))),
            mixed_bundles=sum(summaries[plane]['mixed_bundles']
                              for plane in planes),
        )
        combined['score'] = round(score_method(combined), 4)
        methods[method_name] = combined
        raw[method_name] = bundles_by_plane
        print(f'[p0] {method_name}: bundles={combined["bundle_count"]} '
              f'mean_size={combined["size_orbits"]["mean"]:.2f} '
              f'cross_rate={combined["internal_cross_rate"]:.4f} '
              f'compat={combined["mean_compatibility"]:.3f} '
              f'mixed={combined["mixed_bundles"]} '
              f'score={combined["score"]}', flush=True)
    automatic = {name: value for name, value in methods.items()
                 if not name.startswith('kind_pure')}
    chosen_name = max(automatic, key=lambda name: automatic[name]['score'])
    for bundle in (raw[chosen_name][plane] for plane in planes):
        for row in bundle:
            row['layer_options'] = list(range(2, 16))
            row['min_corridor_width_mm'] = round(
                row['lateral_span_mm'] + 2.0 * (0.08 + 0.25), 3)
            row['confidence'] = row['mean_compatibility']
            row['grouping_basis'] = (
                'weighted geometric compatibility graph (endpoint proximity, '
                'direction, shared corridor span, order compatibility, port '
                'adjacency, crossing cost) + bundle-first ordering')
    methods[chosen_name]['selected'] = True
    chosen = raw[chosen_name]
    chosen_summary = methods[chosen_name]
    print(f'[p0] chosen automatic method: {chosen_name}', flush=True)

    # --- write artefacts ------------------------------------------------
    (GROUP_DIR / 'features.json').write_text(
        json.dumps(dict(schema='bundle3d_route_features_v1',
                        features=features), ensure_ascii=False, indent=1,
                   default=str), encoding='utf-8')
    orbit_payload = []
    for orbit in orbits:
        orbit = dict(orbit)
        orbit['members'] = [
            dict(route_id=member['route_id'], family=member['family'],
                 source_endpoint=member['source_endpoint'],
                 target_endpoint=member['target_endpoint'],
                 start_xy=member['start_xy'], end_xy=member['end_xy'],
                 lateral_coord=member['lateral_coord'],
                 separation_mm=member['separation_mm'],
                 los_dir=member['los_dir'])
            for member in orbit['members']]
        orbit_payload.append(orbit)
    (GROUP_DIR / 'orbits.json').write_text(
        json.dumps(dict(schema='bundle3d_orbits_v1', orbits=orbit_payload),
                   ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    (GROUP_DIR / 'compatibility_edges.json').write_text(
        json.dumps(dict(schema='bundle3d_compatibility_graph_v1',
                        node_count=len(orbits), edge_count=len(edges),
                        top_edges=edges[:5000]), ensure_ascii=False, indent=1),
        encoding='utf-8')
    (GROUP_DIR / 'bundles.json').write_text(
        json.dumps(dict(
            schema='bundle3d_bundles_v1',
            node_definition='C4 rotation orbit (4 connections) - bundles are C4-closed',
            input_snapshot=input_snapshot,
            chosen_method=chosen_name,
            methods=methods,
            bundles={plane: chosen[plane] for plane in planes},
        ), ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    summary_payload = dict(
        schema='bundle3d_grouping_summary_v1',
        input_snapshot=input_snapshot,
        connections=len(features),
        orbits=len(orbits),
        edges=len(edges),
        methods=methods,
        chosen_method=chosen_name,
        chosen=chosen_summary,
        answers=dict(
            q1_can_form_bundles=True,
            q2_bundle_size=dict(mean_orbits=chosen_summary['size_orbits']['mean'],
                                mean_connections=chosen_summary['size_orbits']['mean'] * 4,
                                fixed_size_required=False,
                                range_orbits=[chosen_summary['size_orbits']['min'],
                                              chosen_summary['size_orbits']['max']]),
            q3_kind_grouping=dict(
                note='both same-kind and mixed bundles exist; selection scored '
                     'by internal crossing rate + order + corridor affinity',
                mixed_bundles=chosen_summary['mixed_bundles'],
                dominant_kind_mix=chosen_summary['kind_mix']),
        ),
    )
    (GROUP_DIR / 'grouping_summary.json').write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')

    # --- figures --------------------------------------------------------
    VZ.figure_topology_raw(features, FIGS / 'fig01_topology_raw.png')
    VZ.figure_bundle_grouping(
        orbits, {plane: chosen[plane] for plane in planes},
        FIGS / 'fig02_bundle_grouping_final.png',
        title_suffix=f' ({chosen_name})')
    VZ.figure_bundle_representatives(
        orbits, {plane: chosen[plane] for plane in planes},
        FIGS / 'fig02c_bundle_representatives.png')
    VZ.figure_bundle_corridors(
        orbits, {plane: chosen[plane] for plane in planes},
        FIGS / 'fig03_bundle_corridors.png')
    VZ.figure_bundle_zoom(
        orbits, {plane: chosen[plane] for plane in planes},
        FIGS / 'fig04_bundle_zoom.png')
    VZ.figure_compatibility_heatmap(
        orbits, adjacency, {plane: chosen[plane] for plane in planes},
        FIGS / 'fig05_compatibility_heatmap.png')
    VZ.figure_bundle_stats(methods, FIGS / 'fig06_bundle_stats.png')
    VZ.figure_bundle_kind_mix(
        {plane: chosen[plane] for plane in planes},
        FIGS / 'fig07_bundle_kind_mix.png')
    for method_name in methods:
        if method_name == chosen_name:
            continue
        VZ.figure_bundle_grouping(
            orbits, {plane: raw[method_name][plane] for plane in planes},
            FIGS / f'fig02b_{method_name}.png', title_suffix=f' ({method_name})')
    print(json.dumps(dict(chosen=chosen_name,
                          methods={name: dict(bundle_count=value['bundle_count'],
                                              mean_size=value['size_orbits']['mean'],
                                              cross_rate=round(value['internal_cross_rate'], 4),
                                              score=value['score'])
                                   for name, value in methods.items()}),
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
