# -*- coding: utf-8 -*-
"""Finalise the new-manual-CSV campaign: layer comparison, best solution, figures.

Reads the layer-sweep outputs (02_layer_sweep/L*/lift), writes:
  * comparison.csv/json/png of the 5L..15L layer study;
  * best_solution/ with routes_l3d.json, summary, validation, per-route/per-layer
    CSVs, Z2 strict-C4 audit and the mandatory figures;
  * per-layer XY figures + overall 2D/3D + crossing hotspot for each formal
    candidate.
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
from matplotlib.collections import LineCollection

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.l3d import validate_l3d_multi as V  # noqa: E402
from four_side_1024.l3d import layers as LL  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
LAYER_COUNTS = [5, 7, 9, 11, 13, 15]


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def layer_zs(count):
    return [round(0.65 + 0.15 * index, 3) for index in range(count - 1)]


def build_stack(count):
    LL.ROUTING_LAYER_IDS = tuple(range(2, int(count) + 1))
    return LL.build_stack('new_manual_sweep', heights={
        int(index) + 2: value for index, value in enumerate(layer_zs(count))})


def build_port_identity():
    """Identity block expected by the frozen l3d validator parser."""
    payload = load_json(CAMPAIGN / 'phase2_2d_selected/routes_1024.json')
    eps = CONN.endpoints()
    planes = {plane: {'routes': {}, 'endpoints': eps}
              for plane in ('z1', 'z2')}
    for record in payload['routes']:
        plane = record.get('plane')
        if plane not in planes:
            continue
        rid = int(record['route_id'])
        planes[plane]['routes'][rid] = dict(
            route_id=rid,
            source_endpoint=record['source_endpoint'],
            target_endpoint=record['target_endpoint'],
            source_side=record['source_side'],
            target_side=record['target_side'],
            source_row=int(record['source_row']),
            target_row=int(record['target_row']),
            relation=record['relation'], pair=record['pair'])
    return {'available': True, 'error': None, 'planes': planes}


def parse_routes(records, stack, identity):
    geoms = {}
    report = V._Report()
    for record in records:
        if record.get('status') != 'routed':
            continue
        try:
            geoms[int(record['route_id'])] = V._parse_route(
                record, stack, identity, report)
        except Exception:  # noqa: BLE001
            continue
    return geoms


def sample_route(geom, transition_step=V.TRANSITION_STEP_MM):
    """Full 3D polyline of a parsed route (flat + transition samples)."""
    points = []
    for part in geom.parts:
        sampled = part.samples3d(V.FLAT_LINE_STEP_MM, V.FLAT_ARC_STEP_MM) \
            if part.kind == 'flat' else part.samples3d(transition_step)
        sampled = np.asarray(sampled, dtype=float)
        if len(sampled):
            if points:
                points.extend(sampled[1:])
            else:
                points.extend(sampled)
    return np.asarray(points)


def orbit_children(groups, z2_rids):
    """Map each z2 route id to its C4 group."""
    out = {}
    for group in groups:
        if group['plane'] != 'z2':
            continue
        for rid in group['route_ids']:
            out[int(rid)] = int(group['group_id'])
    return out


def _point_to_polyline_distance(points, polyline):
    """Distance from each point to the nearest sample of a dense polyline."""
    from scipy.spatial import cKDTree
    tree = cKDTree(polyline)
    distance, _index = tree.query(points)
    return distance


def z2_c4_audit(geoms, records, groups, board=150.0):
    z2_orbits = [g for g in groups if g['plane'] == 'z2']
    layer_errors = 0
    transition_errors = 0
    geometry_errors = 0
    incomplete = 0
    failed = []
    max_dev = 0.0
    for group in z2_orbits:
        rids = [int(r) for r in group['route_ids']]
        available = [rid for rid in rids if rid in geoms]
        if len(available) != 4:
            incomplete += 1
            failed.append(dict(group_id=group['group_id'], reason='missing'))
            continue
        heights = []
        for rid in rids:
            geom = geoms[rid]
            heights.append(tuple(sorted({round(float(part.z_mm), 6)
                                        for part in geom.flat_parts})))
        if len(set(heights)) != 1:
            layer_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='layer_mismatch',
                               heights=heights))
            continue
        transitions = [len(geoms[rid].transitions) for rid in rids]
        if len(set(transitions)) != 1:
            transition_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='transition_count_mismatch',
                               transitions=transitions))
            continue
        rep = rids[0]
        rep_points = np.asarray(geoms[rep].samples3d_uniform(0.02), dtype=float)
        group_dev = 0.0
        for k in (1, 2, 3):
            member_points = np.asarray(
                geoms[rids[k]].samples3d_uniform(0.02), dtype=float)
            rotated = rep_points.copy()
            for _ in range(k):
                rotated = np.stack([board - rotated[:, 1], rotated[:, 0],
                                    rotated[:, 2]], axis=1)
            if len(member_points) < 2:
                group_dev = float('inf')
                break
            distance = _point_to_polyline_distance(rotated, member_points)
            group_dev = max(group_dev, float(np.max(distance)))
        if group_dev > 0.02:
            geometry_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='geometry_deviation',
                               deviation_mm=round(group_dev, 6)))
        max_dev = max(max_dev, group_dev)
    total_routes = sum(1 for rid in geoms if rid in
                       {int(r) for g in z2_orbits for r in g['route_ids']})
    return dict(schema='new_manual_z2_strict_c4_validation_v1',
                scope='Z2 subsystem (Z1 kept C4 as well in this campaign)',
                total_routes=total_routes, total_orbits=len(z2_orbits),
                incomplete_orbits=incomplete,
                complete_orbits=len(z2_orbits) - incomplete,
                layer_symmetry_errors=layer_errors,
                transition_symmetry_errors=transition_errors,
                geometry_symmetry_errors=geometry_errors,
                maximum_xyz_deviation_mm=max_dev,
                failed_orbits=failed,
                symmetry_pass=(layer_errors == 0 and transition_errors == 0
                               and geometry_errors == 0))


def figure_overall_3d(geoms, path, title):
    fig = plt.figure(figsize=(10, 8.2))
    ax = fig.add_subplot(111, projection='3d')
    for rid, geom in geoms.items():
        points = sample_route(geom)
        if len(points) < 2:
            continue
        color = plt.cm.viridis((points[0, 2] - 0.0) / 2.6)
        ax.plot(points[:, 0], points[:, 1], points[:, 2], color=color,
                lw=0.25, alpha=0.35)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_zlabel('z (mm)')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_overall_xy(geoms, path, title):
    fig, ax = plt.subplots(figsize=(8.2, 8.2))
    segments = []
    colors = []
    for rid, geom in geoms.items():
        points = sample_route(geom)
        if len(points) < 2:
            continue
        for index in range(len(points) - 1):
            segments.append([points[index, :2], points[index + 1, :2]])
            colors.append(plt.cm.viridis(
                (points[index, 2] - 0.0) / 2.6))
    collection = LineCollection(segments, colors=colors, linewidths=0.25,
                                alpha=0.5)
    ax.add_collection(collection)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_layer(geoms, z, path, title):
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    segments = []
    for rid, geom in geoms.items():
        for part in geom.flat_parts:
            if abs(float(part.z_mm) - z) > 1e-6:
                continue
            points = part.samples3d(V.FLAT_LINE_STEP_MM, V.FLAT_ARC_STEP_MM)
            points = np.asarray(points, dtype=float)
            for index in range(len(points) - 1):
                segments.append([points[index, :2], points[index + 1, :2]])
    if segments:
        ax.add_collection(LineCollection(segments, linewidths=0.5,
                                         alpha=0.7, colors='#1971c2'))
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.grid(alpha=0.15)
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def figure_crossings(crossings, path, title):
    fig, ax = plt.subplots(figsize=(8.0, 7.4))
    if crossings:
        xs = [item.get('x') for item in crossings]
        ys = [item.get('y') for item in crossings]
        ax.hexbin(xs, ys, gridsize=45, cmap='Reds', mincnt=1)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=175)
    plt.close(fig)


def main():
    patch_conn()
    topology = CONN.combined_topology()
    groups = topology['groups']
    identity = build_port_identity()
    rows = []
    for count in LAYER_COUNTS:
        folder = CAMPAIGN / '02_layer_sweep' / f'L{count}' / 'lift'
        required = ('routes_l3d.json', 'validation.json',
                    'crossings_after.json')
        if not all((folder / name).exists() for name in required):
            print('skip incomplete', folder)
            continue
        payload = load_json(folder / 'routes_l3d.json')
        validation = load_json(folder / 'validation.json')
        summary = load_json(folder / 'summary.json', {})
        crossings = load_json(folder / 'crossings_after.json')
        records = payload['routes']
        stack = build_stack(count)
        geoms = parse_routes(records, stack, identity)
        z2_c4 = z2_c4_audit(geoms, records, groups)
        routed = sum(1 for record in records if record.get('status') == 'routed')
        layer_counts = Counter()
        for geom in geoms.values():
            used = sorted({round(float(part.z_mm), 6)
                           for part in geom.flat_parts})
            if len(used) <= 1:
                layer_counts[used[0] if used else 0.0] += 1
            for z in used:
                layer_counts[z] += 1
        # per route / per layer
        per_route = []
        for record in records:
            rid = int(record['route_id'])
            geom = geoms.get(rid)
            if geom is None:
                per_route.append(dict(route_id=rid, plane=record.get('plane'),
                                      status=record.get('status'),
                                      transitions=0, length_mm=0.0))
                continue
            flat_z = sorted({round(float(part.z_mm), 6)
                             for part in geom.flat_parts})
            per_route.append(dict(
                route_id=rid, plane=record.get('plane'), status='routed',
                transitions=len(geom.transitions),
                length_mm=round(float(geom.total_length), 4),
                min_z=flat_z[0], max_z=flat_z[-1],
                layers=';'.join(str(z) for z in flat_z)))
        per_layer = []
        for z in sorted(layer_counts):
            routes = sum(1 for geom in geoms.values()
                         if any(abs(float(part.z_mm) - z) < 1e-6
                                for part in geom.flat_parts))
            segments = sum(1 for geom in geoms.values()
                           for part in geom.flat_parts
                           if abs(float(part.z_mm) - z) < 1e-6)
            per_layer.append(dict(z_mm=z, routes=routes, segments=segments))
        # comparison row
        counts = dict(validation.get('counts') or {})
        row = dict(layer_count=count, layer_heights_mm=layer_zs(count),
                   routed=routed,
                   failed=len(records) - routed,
                   violations=counts.get('violations'),
                   curvature_violations=counts.get('curvature_violations'),
                   clearance_violations=counts.get('clearance_violations'),
                   validation_status=validation.get('status'),
                   exploratory_pass=validation.get('exploratory_pass'),
                   unique_crossing_pairs=crossings.get('unique_pair_count'),
                   crossing_points=crossings.get('count'),
                   pairs_by_height=crossings.get('pair_count_by_height'),
                   new_high_layer_pairs=len(crossings.get('new_high_layer_pairs') or []),
                   transitions=sum(item['transitions'] for item in per_route),
                   xyz_length_mm=round(sum(item['length_mm'] for item in per_route), 3),
                   fabrication_hours=round(sum(item['length_mm'] for item in per_route) / 3600.0, 4),
                   layer_route_counts={str(k): v for k, v in sorted(layer_counts.items())},
                   z2_c4=z2_c4)
        rows.append(row)
        # artefacts for formal candidates
        out = CAMPAIGN / '02_layer_sweep' / f'L{count}'
        import csv
        with (out / 'per_route.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(per_route[0].keys()))
            writer.writeheader()
            writer.writerows(per_route)
        with (out / 'per_layer.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(per_layer[0].keys()))
            writer.writeheader()
            writer.writerows(per_layer)
        (out / 'z2_c4_validation.json').write_text(
            json.dumps(z2_c4, ensure_ascii=False, indent=1), encoding='utf-8')
        (out / 'layer_row.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        fig_dir = out / 'figures'
        fig_dir.mkdir(exist_ok=True)
        figure_overall_3d(geoms, fig_dir / 'overall_3d.png',
                          f'new manual CSV, {count}L: overall 3D '
                          f'({routed}/1024 routed)')
        figure_overall_xy(geoms, fig_dir / 'overall_2d.png',
                          f'new manual CSV, {count}L: overall XY')
        figure_crossings(crossings.get('crossings') or [],
                         fig_dir / 'crossing_hotspots.png',
                         f'{count}L: crossing hotspots (unique pairs='
                         f'{crossings.get("unique_pair_count")})')
        for z in sorted(layer_counts):
            figure_layer(geoms, z, fig_dir / f'layer_z{z:.2f}.png',
                         f'{count}L physical layer z={z} mm')
        print(f'[finalise] L{count}: routed={routed} violations='
              f'{counts.get("violations")} pairs='
              f'{crossings.get("unique_pair_count")} '
              f'z2c4={z2_c4["symmetry_pass"]}', flush=True)
    # comparison / best
    if not rows:
        raise SystemExit('no layer sweep results found')
    rows.sort(key=lambda item: item['layer_count'])
    import csv
    with (CAMPAIGN / 'comparison.csv').open('w', encoding='utf-8', newline='') as handle:
        fields = ['layer_count', 'routed', 'failed', 'violations',
                  'unique_crossing_pairs', 'transitions', 'fabrication_hours',
                  'z2_c4_symmetry_pass']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(
                layer_count=row['layer_count'], routed=row['routed'],
                failed=row['failed'], violations=row['violations'],
                unique_crossing_pairs=row['unique_crossing_pairs'],
                transitions=row['transitions'],
                fabrication_hours=row['fabrication_hours'],
                z2_c4_symmetry_pass=row['z2_c4']['symmetry_pass']))
    (CAMPAIGN / 'comparison.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    xs = [row['layer_count'] for row in rows]
    axes[0].plot(xs, [row['unique_crossing_pairs'] for row in rows],
                 marker='o', color='#1971c2')
    axes[0].set_xlabel('layer count (L2..Ln)')
    axes[0].set_ylabel('unique crossing pairs')
    axes[0].set_title('global unique crossings vs layer count')
    axes[0].grid(alpha=0.2)
    axes[1].plot(xs, [row['fabrication_hours'] for row in rows],
                 marker='s', color='#e8590c')
    axes[1].set_xlabel('layer count (L2..Ln)')
    axes[1].set_ylabel('ideal fabrication time (h)')
    axes[1].set_title('XYZ length / fabrication time vs layer count')
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(CAMPAIGN / 'comparison.png', dpi=180)
    plt.close(fig)
    # best: fully-routed first, then fewest violations, then fewest pairs
    candidates = [row for row in rows if row['routed'] == 1024
                  and row['violations'] == 0]
    if not candidates:
        candidates = [row for row in rows if row['violations'] == 0] or rows
    best = min(candidates, key=lambda row: row['unique_crossing_pairs'])
    (CAMPAIGN / 'best_solution').mkdir(exist_ok=True)
    src = CAMPAIGN / '02_layer_sweep' / f'L{best["layer_count"]}'
    import shutil
    for name in ('per_route.csv', 'per_layer.csv', 'z2_c4_validation.json',
                 'layer_row.json'):
        shutil.copyfile(src / name, CAMPAIGN / 'best_solution' / name)
    for name in ('routes_l3d.json', 'summary.json', 'validation.json',
                 'crossings_after.json', 'layer_stack.json'):
        if (src / 'lift' / name).exists():
            shutil.copyfile(src / 'lift' / name,
                            CAMPAIGN / 'best_solution' / name)
    if (src / 'figures').exists():
        shutil.copytree(src / 'figures', CAMPAIGN / 'best_solution' / 'figures',
                        dirs_exist_ok=True)
    (CAMPAIGN / 'best_solution' / 'BEST_SOURCE.json').write_text(
        json.dumps(dict(source_experiment=f'L{best["layer_count"]}',
                        best=best), ensure_ascii=False, indent=1,
                   default=str), encoding='utf-8')
    print('[finalise] best layer count:', best['layer_count'],
          'pairs:', best['unique_crossing_pairs'])


if __name__ == '__main__':
    main()
