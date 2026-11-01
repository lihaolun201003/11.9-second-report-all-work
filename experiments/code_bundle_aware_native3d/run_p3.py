# -*- coding: utf-8 -*-
"""P3 campaign: native 3D A* prototype on the eight still-unrouted Z2 orbits.

Runs the XYZ search against the full 3D obstacle cloud of the best 15-layer
layout (1024-route reference), for the representative connection of every failed
C4 orbit.  Reports how many of them admit a search-generated 3D corridor and
records the XYZ decisions (layer sequence / turns) so native search is clearly
distinguished from 2D+lift.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.v3c4.profile import apply as apply_profile  # noqa: E402
apply_profile()

from four_side_1024.bundle3d import native_search as NS  # noqa: E402
from four_side_1024.fslw import config as FS  # noqa: E402
from four_side_1024.fslw import validate_fslw as V2D  # noqa: E402
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
BEST_3D = OLD / 'best_solution/routes_l3d.json'
P3_DIR = CAMPAIGN / '03_native3d'
FIGS = CAMPAIGN / 'figures'
FAILED_ORBITS = [154, 156, 158, 214, 246, 249, 250, 254]
CLEARANCE = 0.08


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def primitive_samples(primitives):
    points = []
    dirs = []
    ok = True
    previous_end = None
    radius_ok = True
    for item in primitives:
        if item[0] == 'line':
            samples = NS.sample_line(tuple(item[1]), tuple(item[2]))
            start, end = tuple(item[1]), tuple(item[2])
        elif item[0] == 'transition':
            samples = NS.sample_line(tuple(item[1]), tuple(item[2]))
            start, end = tuple(item[1]), tuple(item[2])
        else:
            _kind, start, end, direction, angle, samples = item
            start, end = tuple(start), tuple(end)
            samples = [(float(x), float(y)) for x, y in samples]
            radius_ok = radius_ok and abs(angle) <= math.pi / 2.0 + 1e-9
        if previous_end is not None:
            if math.hypot(previous_end[0] - start[0],
                          previous_end[1] - start[1]) > 1e-6:
                ok = False
        previous_end = end
        for index, (x, y) in enumerate(samples):
            if index + 1 < len(samples):
                dx = samples[index + 1][0] - x
                dy = samples[index + 1][1] - y
            else:
                dx = end[0] - x
                dy = end[1] - y
            norm = math.hypot(dx, dy) or 1.0
            points.append((x, y, NS.INTERFACE_Z))
            dirs.append((dx / norm, dy / norm))
    return points, dirs, ok, radius_ok, previous_end


def validate_native(record, source_ep, target_ep, obstacles):
    primitives = [list(item) for item in record['dock_primitives']]
    points, dirs, continuous, radius_ok, last_end = primitive_samples(primitives)
    start_xy = tuple(float(v) for v in source_ep['routing_xy'])
    target_xy = tuple(float(v) for v in target_ep['routing_xy'])
    inside = all(0.0 <= x <= NS.BOARD and 0.0 <= y <= NS.BOARD
                 for x, y, _z in points)
    clearance = obstacles.min_distance(points) if points else 0.0
    parallel_clear = bool(obstacles.clear(points, dirs)) if points else False
    endpoint_ok = (last_end is not None
                   and math.hypot(last_end[0] - target_xy[0],
                                  last_end[1] - target_xy[1]) < 1e-6)
    first_start = (tuple(primitives[0][1]) if primitives else None)
    start_ok = (first_start is not None
                and math.hypot(first_start[0] - start_xy[0],
                               first_start[1] - start_xy[1]) < 1e-6)
    length = sum(math.hypot(item[2][0] - item[1][0], item[2][1] - item[1][1])
                 if item[0] in ('line', 'transition')
                 else NS.RADIUS * abs(float(item[4]))
                 for item in primitives)
    # frozen fslw single-route geometry check on the XY projection
    frozen_primitives = []
    for item in primitives:
        if item[0] in ('line', 'transition'):
            start_xy = (float(item[1][0]), float(item[1][1]))
            end_xy = (float(item[2][0]), float(item[2][1]))
            if math.hypot(end_xy[0] - start_xy[0],
                          end_xy[1] - start_xy[1]) < 1e-6:
                continue
            frozen_primitives.append(dict(
                kind='line', p0=[start_xy[0], start_xy[1]],
                p1=[end_xy[0], end_xy[1]]))
            continue
        _kind, start, end, direction, angle, samples = item
        start = (float(start[0]), float(start[1]))
        end = (float(end[0]), float(end[1]))
        if math.hypot(end[0] - start[0], end[1] - start[1]) < 1e-6:
            continue
        chord = (end[0] - start[0], end[1] - start[1])
        chord_length = math.hypot(*chord)
        if chord_length < 1e-9:
            continue
        chord_dir = (chord[0] / chord_length, chord[1] / chord_length)
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        height = NS.RADIUS * math.cos(float(angle) / 2.0)
        left_normal = (-chord_dir[1], chord_dir[0])
        center = (mid[0] + direction * height * left_normal[0],
                  mid[1] + direction * height * left_normal[1])
        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        sweep = direction * float(angle)
        p1 = [end[0], end[1]]
        frozen_primitives.append(dict(
            kind='arc', p0=[start[0], start[1]], p1=p1,
            center=[center[0], center[1]], radius=NS.RADIUS,
            start_angle=start_angle, sweep=sweep))
    frozen_pass = False
    frozen_errors = []
    try:
        frozen = V2D.check_route_primitives(
            frozen_primitives, source=source_ep, target=target_ep,
            width=FS.WIDTH_MM, radius=FS.RADIUS_MM, board=FS.BOARD_MM,
            clearance=FS.CLEARANCE_MM)
        frozen_pass = bool(frozen['passed'])
        frozen_errors = list(frozen['errors'])[:6]
    except Exception as exc:  # noqa: BLE001
        frozen_errors = [f'validator_error:{exc}']
    passed = bool(continuous and radius_ok and inside and endpoint_ok
                  and start_ok and frozen_pass)
    return dict(passed=passed, continuous=continuous, radius_ok=radius_ok,
                inside_board=inside, start_endpoint_ok=start_ok,
                target_endpoint_ok=endpoint_ok,
                parallel_clearance_ok=parallel_clear,
                min_obstacle_distance_mm=round(float(clearance), 6),
                frozen_2d_validator_pass=frozen_pass,
                frozen_2d_validator_errors=frozen_errors,
                xy_length_mm=round(float(length), 3))


def main():
    patch_conn()
    P3_DIR.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    topology = CONN.combined_topology()
    groups = {int(group['group_id']): group for group in topology['groups']}
    endpoints = CONN.endpoints()
    obstacles, payload = NS.build_obstacles(BEST_3D)
    search = NS.NativeSearch(obstacles, obstacles.heights,
                             interface_z=NS.INTERFACE_Z)
    print(f'[p3] obstacle cloud: {len(obstacles.points)} 3D points, '
          f'layers={sorted(obstacles.heights)}', flush=True)
    results = []
    for group_id in FAILED_ORBITS:
        group = groups[group_id]
        record = next(row for row in topology['routes']
                      if int(row['route_id']) == int(group['route_ids'][0]))
        source_ep = endpoints[record['source_endpoint']]
        target_ep = endpoints[record['target_endpoint']]
        start_xy = tuple(float(v) for v in source_ep['routing_xy'])
        target_xy = tuple(float(v) for v in target_ep['routing_xy'])
        start_heading = tuple(int(round(float(v))) for v in source_ep['inward'])
        target_heading = tuple(int(round(-float(v)))
                               for v in target_ep['inward'])
        result = search.search(start_xy, start_heading, target_xy,
                               target_heading, expansions_limit=80000,
                               time_limit=25.0)
        row = dict(group_id=group_id, kind=group['kind'],
                   pair=group.get('pair'),
                   route_id=int(record['route_id']),
                   source_endpoint=record['source_endpoint'],
                   target_endpoint=record['target_endpoint'],
                   found=bool(result['found']),
                   expansions=result['expansions'],
                   search_seconds=result['seconds'],
                   native_reason=result.get('reason'))
        if result['found']:
            primitives = result['primitives']
            serialized = []
            for item in primitives:
                if item[0] == 'line':
                    serialized.append(['line', list(item[1]), list(item[2])])
                elif item[0] == 'transition':
                    serialized.append([
                        'transition', list(item[1]), list(item[2]),
                        float(item[3]), float(item[4])])
                else:
                    serialized.append([
                        'arc', list(item[1]), list(item[2]), int(item[3]),
                        float(item[4]),
                        [[float(x), float(y)] for x, y in item[5]]])
            row['dock_primitives'] = serialized
            row['corridor_cells'] = result['corridor'][:4000]
            row['layers_used'] = result['layers_used']
            row['corridor_high_layer_states'] = sum(
                1 for state in result['corridor'] if int(state[2]) != 1)
            row['transitions'] = 0
            row['validation'] = validate_native(row, source_ep, target_ep,
                                                obstacles)
        results.append(row)
        print(f'[p3] orbit {group_id} ({group["kind"]}): found='
              f'{row["found"]} expansions={row["expansions"]} '
              f'validation={(row.get("validation") or {}).get("passed")}',
              flush=True)
    found = sum(1 for row in results if row['found'])
    validated = sum(1 for row in results
                    if (row.get('validation') or {}).get('passed'))
    summary = dict(schema='bundle3d_native3d_summary_v1',
                   tested=len(results), found=found, validated=validated,
                   failure_analysis=[dict(group_id=row['group_id'],
                                          kind=row['kind'],
                                          found=row['found'],
                                          reason=row.get('native_reason'))
                                     for row in results],
                   native_paths_with_high_layer=sum(
                       1 for row in results
                       if row.get('corridor_high_layer_states')),
                   note=('Prototype: XYZ search corridor generated by A* with '
                         '3D obstacle cloud; last-mile port docking uses frozen '
                         'R15 straight/S/L/U templates (explicitly measured). '
                         'The final 1024 layout is NOT produced by this search.'))
    (P3_DIR / 'native_search_results.json').write_text(
        json.dumps(dict(schema='bundle3d_native3d_prototype_v1',
                        obstacle_cloud_points=len(obstacles.points),
                        results=results), ensure_ascii=False, indent=1,
                   default=str), encoding='utf-8')
    (P3_DIR / 'native_search_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    # figure: obstacle cloud XY + native paths
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.2, 8.2))
    sample = obstacles.points[::20]
    ax.scatter(sample[:, 0], sample[:, 1], s=0.3, c='#ced4da', alpha=0.4,
               label='3D obstacle cloud (15L layout)')
    colors = plt.cm.tab10(np.linspace(0, 1, max(1, len(results))))
    for color, row in zip(colors, results):
        if not row['found']:
            continue
        points = []
        for item in row['dock_primitives']:
            if item[0] in ('line', 'transition'):
                points.extend(NS.sample_line(tuple(item[1]), tuple(item[2])))
            else:
                points.extend([[float(x), float(y)] for x, y in item[5]])
        points = np.asarray(points)
        if len(points):
            ax.plot(points[:, 0], points[:, 1], lw=1.4, color=color,
                    label=f"orbit {row['group_id']} ({row['kind']})")
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title('native 3D search prototype paths (XY projection)')
    ax.legend(fontsize=6, loc='upper right')
    fig.tight_layout()
    fig.savefig(FIGS / 'fig10_native3d_prototype.png', dpi=175)
    plt.close(fig)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)


if __name__ == '__main__':
    main()
