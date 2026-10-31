# -*- coding: utf-8 -*-
"""Finalise campaign (records-based, fast): comparison, best solution, figures."""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4 import lift_cross_run as LCR  # noqa: E402
from four_side_1024.l3d import validate_l3d_multi as V  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.v3c4.profile import apply as apply_profile  # noqa: E402

apply_profile()
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
LAYER_COUNTS = [5, 7, 9, 11, 13, 15]
BOARD = 150.0


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def layer_zs(count):
    return [round(0.65 + 0.15 * index, 3) for index in range(count - 1)]


def flat_points(part):
    points = []
    for primitive in part.get('primitives') or []:
        sampled = LCR._sample_primitive(primitive, step_deg=1.0)
        if sampled is None:
            continue
        for point in sampled:
            points.append([float(point[0]), float(point[1]), float(part['z_mm'])])
    return points


def transition_points(part, step=0.02):
    """Exact two-arc S-curve polyline (frozen validator model)."""
    model = V._TransitionPart(
        index=0,
        from_layer=part.get('from_layer') or 1,
        to_layer=part.get('to_layer') or 2,
        z0=float(part['z0']), z1=float(part['z1']),
        radius=float(part.get('radius_mm') or 15.0),
        start=part['start'], direction=part['direction'])
    points = model.samples3d(step)
    return [[float(point[0]), float(point[1]), float(point[2])]
            for point in np.asarray(points, dtype=float)]


def route_polyline(record):
    points = []
    for part in record.get('parts') or []:
        if part.get('kind') == 'flat':
            sampled = flat_points(part)
        else:
            try:
                sampled = transition_points(part)
            except Exception:  # noqa: BLE001
                sampled = []
        if not sampled:
            continue
        if points and sampled:
            points.extend(sampled[1:])
        else:
            points.extend(sampled)
    return points


def point_to_samples(points, samples):
    from scipy.spatial import cKDTree
    if len(samples) < 2:
        return 999.0
    distance, _index = cKDTree(samples).query(np.asarray(points))
    return float(np.max(distance))


def z2_c4_audit(records):
    patch_conn()
    topology = CONN.combined_topology()
    z2_groups = [g for g in topology['groups'] if g['plane'] == 'z2']
    by_rid = {int(record['route_id']): record for record in records}
    polylines = {}
    for rid, record in by_rid.items():
        if record.get('status') == 'routed':
            polylines[rid] = route_polyline(record)
    layer_errors = transition_errors = geometry_errors = incomplete = 0
    failed = []
    max_dev = 0.0
    for group in z2_groups:
        rids = [int(rid) for rid in group['route_ids']]
        if any(rid not in polylines for rid in rids):
            incomplete += 1
            failed.append(dict(group_id=group['group_id'], reason='incomplete'))
            continue
        layers = [tuple(sorted({round(float(part['z_mm']), 6)
                                for part in by_rid[rid].get('parts') or []
                                if part.get('kind') == 'flat'})) for rid in rids]
        if len(set(layers)) != 1:
            layer_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='layer_mismatch'))
            continue
        trans = [sum(1 for part in by_rid[rid].get('parts') or []
                     if part.get('kind') == 'transition') for rid in rids]
        if len(set(trans)) != 1:
            transition_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='transition_count_mismatch'))
            continue
        rep = np.asarray(polylines[rids[0]])
        group_dev = 0.0
        for k in (1, 2, 3):
            member = np.asarray(polylines[rids[k]])
            rotated = rep.copy()
            for _ in range(k):
                rotated = np.stack([BOARD - rotated[:, 1], rotated[:, 0],
                                    rotated[:, 2]], axis=1)
            group_dev = max(group_dev, point_to_samples(rotated, member))
        max_dev = max(max_dev, group_dev)
        if group_dev > 0.01:
            geometry_errors += 1
            failed.append(dict(group_id=group['group_id'],
                               reason='geometry_deviation',
                               deviation_mm=round(group_dev, 9)))
    return dict(schema='new_manual_z2_strict_c4_validation_v1',
                scope='Z2 subsystem (Z1 kept C4 as well)',
                total_routes=len([rid for rid in polylines
                                  if rid in {int(r) for g in z2_groups
                                             for r in g['route_ids']}]),
                total_orbits=len(z2_groups),
                complete_orbits=len(z2_groups) - incomplete,
                incomplete_orbits=incomplete,
                layer_symmetry_errors=layer_errors,
                transition_symmetry_errors=transition_errors,
                geometry_symmetry_errors=geometry_errors,
                maximum_xyz_deviation_mm=max_dev,
                failed_orbits=failed,
                symmetry_pass=(layer_errors == 0 and transition_errors == 0
                               and geometry_errors == 0))


def figure_overall_3d(records, path, title):
    fig = plt.figure(figsize=(10, 8.2))
    ax = fig.add_subplot(111, projection='3d')
    for record in records:
        if record.get('status') != 'routed':
            continue
        points = np.asarray(route_polyline(record))
        if len(points) < 2:
            continue
        ax.plot(points[:, 0], points[:, 1], points[:, 2],
                color=plt.cm.viridis(np.clip(points[0, 2] / 2.6, 0, 1)),
                lw=0.25, alpha=0.4)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_zlabel('z (mm)')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_overall_2d(records, path, title):
    fig, ax = plt.subplots(figsize=(8.2, 8.2))
    segments = []
    colors = []
    for record in records:
        if record.get('status') != 'routed':
            continue
        points = np.asarray(route_polyline(record))
        if len(points) < 2:
            continue
        for index in range(len(points) - 1):
            segments.append([points[index, :2], points[index + 1, :2]])
            colors.append(plt.cm.viridis(np.clip(points[index, 2] / 2.6, 0, 1)))
    if segments:
        ax.add_collection(LineCollection(segments, colors=colors,
                                         linewidths=0.25, alpha=0.5))
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_layer(records, z, path, title):
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    segments = []
    for record in records:
        if record.get('status') != 'routed':
            continue
        for part in record.get('parts') or []:
            if part.get('kind') != 'flat':
                continue
            if abs(float(part['z_mm']) - z) > 1e-6:
                continue
            points = np.asarray(flat_points(part))
            for index in range(len(points) - 1):
                segments.append([points[index, :2], points[index + 1, :2]])
    if segments:
        ax.add_collection(LineCollection(segments, linewidths=0.5,
                                         alpha=0.75, colors='#1971c2'))
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
    xs = [item.get('x') for item in crossings if item.get('x') is not None]
    ys = [item.get('y') for item in crossings if item.get('y') is not None]
    if xs:
        ax.hexbin(xs, ys, gridsize=45, cmap='Reds', mincnt=1)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=175)
    plt.close(fig)


def main():
    rows = []
    for count in LAYER_COUNTS:
        folder = CAMPAIGN / '02_layer_sweep' / f'L{count}' / 'lift'
        payload = read_json(folder / 'routes_l3d.json')
        validation = read_json(folder / 'validation.json')
        crossings = read_json(folder / 'crossings_after.json')
        if payload is None or validation is None or crossings is None:
            print('skip', count)
            continue
        records = payload['routes']
        routed = [record for record in records
                  if record.get('status') == 'routed']
        heights = layer_zs(count)
        physical = [0.0, 0.5] + heights
        per_route = []
        layer_counts = Counter()
        for record in records:
            rid = int(record['route_id'])
            if record.get('status') != 'routed':
                per_route.append(dict(route_id=rid, plane=record.get('plane'),
                                      status=record.get('status'),
                                      transitions=0, length_mm=0.0,
                                      min_z=0.0, max_z=0.0, layers=''))
                continue
            parts = record.get('parts') or []
            flat_z = sorted({round(float(part['z_mm']), 6)
                             for part in parts if part.get('kind') == 'flat'})
            trans = sum(1 for part in parts if part.get('kind') == 'transition')
            length = float(record.get('length_mm') or 0.0)
            per_route.append(dict(route_id=rid, plane=record.get('plane'),
                                  status='routed', transitions=trans,
                                  length_mm=round(length, 4),
                                  min_z=flat_z[0] if flat_z else 0.0,
                                  max_z=flat_z[-1] if flat_z else 0.0,
                                  layers=';'.join(str(z) for z in flat_z)))
            for z in flat_z:
                layer_counts[z] += 1
        per_layer = []
        for z in physical:
            routes = sum(1 for record in records
                         if record.get('status') == 'routed'
                         and any(abs(float(part['z_mm']) - z) < 1e-6
                                 for part in record.get('parts') or []
                                 if part.get('kind') == 'flat'))
            segments = sum(1 for record in records
                           if record.get('status') == 'routed'
                           for part in record.get('parts') or []
                           if part.get('kind') == 'flat'
                           and abs(float(part['z_mm']) - z) < 1e-6)
            per_layer.append(dict(z_mm=z, routes=routes, segments=segments))
        z2_c4 = z2_c4_audit(records)
        total_length = sum(item['length_mm'] for item in per_route)
        transitions = sum(item['transitions'] for item in per_route)
        counts = dict(validation.get('counts') or {})
        row = dict(layer_count=count, layer_heights_mm=heights,
                   routed=len(routed), failed=len(records) - len(routed),
                   violations=counts.get('violations'),
                   curvature_violations=counts.get('curvature_violations'),
                   clearance_violations=counts.get('clearance_violations'),
                   unique_crossing_pairs=crossings.get('unique_pair_count'),
                   crossing_points=crossings.get('count'),
                   new_high_layer_pairs=len(crossings.get('new_high_layer_pairs') or []),
                   transitions=transitions,
                   xyz_length_mm=round(total_length, 3),
                   fabrication_hours=round(total_length / 3600.0, 4),
                   layer_route_counts={str(k): v for k, v in sorted(layer_counts.items())},
                   z2_c4=z2_c4)
        rows.append(row)
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
            json.dumps(z2_c4, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        (out / 'layer_row.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        fig_dir = out / 'figures'
        fig_dir.mkdir(exist_ok=True)
        figure_overall_3d(records, fig_dir / 'overall_3d.png',
                          f'{count}L overall 3D ({len(routed)}/1024 routed)')
        figure_overall_2d(records, fig_dir / 'overall_2d.png',
                          f'{count}L overall XY')
        figure_crossings(crossings.get('crossings') or [],
                         fig_dir / 'crossing_hotspots.png',
                         f'{count}L crossing hotspots '
                         f'({crossings.get("unique_pair_count")} pairs)')
        for z in physical:
            figure_layer(records, z, fig_dir / f'layer_z{z:.2f}.png',
                         f'{count}L physical layer z={z} mm')
        print(f'[finalise2] L{count}: routed={len(routed)} '
              f'violations={row["violations"]} pairs='
              f'{row["unique_crossing_pairs"]} transitions='
              f'{row["transitions"]} z2c4={z2_c4["symmetry_pass"]} '
              f'incomplete_orbits={z2_c4["incomplete_orbits"]}', flush=True)
    rows.sort(key=lambda row: row['layer_count'])
    import csv
    with (CAMPAIGN / 'comparison.csv').open('w', encoding='utf-8',
                                            newline='') as handle:
        fields = ['layer_count', 'routed', 'failed', 'violations',
                  'unique_crossing_pairs', 'transitions', 'fabrication_hours',
                  'z2_c4_symmetry_pass']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(layer_count=row['layer_count'],
                                 routed=row['routed'], failed=row['failed'],
                                 violations=row['violations'],
                                 unique_crossing_pairs=row[
                                     'unique_crossing_pairs'],
                                 transitions=row['transitions'],
                                 fabrication_hours=row['fabrication_hours'],
                                 z2_c4_symmetry_pass=row['z2_c4'][
                                     'symmetry_pass']))
    (CAMPAIGN / 'comparison.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))
    xs = [row['layer_count'] for row in rows]
    axes[0].plot(xs, [row['unique_crossing_pairs'] for row in rows],
                 marker='o', color='#1971c2')
    axes[0].set_xlabel('layer count (L2..Ln)')
    axes[0].set_ylabel('global unique crossing pairs')
    axes[0].set_title('unique crossings vs layer count')
    axes[0].grid(alpha=0.2)
    axes[1].plot(xs, [row['fabrication_hours'] for row in rows],
                 marker='s', color='#e8590c')
    axes[1].set_xlabel('layer count (L2..Ln)')
    axes[1].set_ylabel('ideal fabrication time (h)')
    axes[1].set_title('XYZ length / time vs layer count')
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(CAMPAIGN / 'comparison.png', dpi=180)
    plt.close(fig)
    candidates = [row for row in rows if row['violations'] == 0]
    best = min(candidates, key=lambda row: row['unique_crossing_pairs'])
    best_dir = CAMPAIGN / 'best_solution'
    if best_dir.exists():
        shutil.rmtree(best_dir)
    best_dir.mkdir(parents=True, exist_ok=True)
    src = CAMPAIGN / '02_layer_sweep' / f'L{best["layer_count"]}'
    for name in ('per_route.csv', 'per_layer.csv', 'z2_c4_validation.json',
                 'layer_row.json', 'figures'):
        source = src / name
        target = best_dir / name
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.exists():
            shutil.copyfile(source, target)
    for name in ('routes_l3d.json', 'validation.json', 'crossings_after.json',
                 'layer_stack.json', 'lift_plans.json'):
        source = src / 'lift' / name
        if source.exists():
            shutil.copyfile(source, best_dir / name)
    (best_dir / 'BEST_SOURCE.json').write_text(
        json.dumps(dict(source_experiment=f'L{best["layer_count"]}', best=best),
                   ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print('[finalise2] best layer count:', best['layer_count'],
          'pairs:', best['unique_crossing_pairs'])


if __name__ == '__main__':
    main()
