# -*- coding: utf-8 -*-
"""Plots for the bidirectional 1 mm 1024-channel experiment (real geometry)."""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from .bidirectional_1mm_layer_assignment import OUT, PHYSICAL_LAYERS, Z1_MM, Z2_MM
from ..fsd25d.path3d import transition_samples

ROUTES = OUT / 'routes_l3d.json'
ASSIGN = OUT / 'assignment_1024.csv'
FINAL = OUT / 'final_stats.json'
CROSS = OUT / 'crossings_after.json'
PLOTS = OUT / 'plots'

COLORS = {
    'Z1_U': '#1f77b4', 'Z1_OPP': '#4c78a8', 'Z1_DOWN': '#2b6cb0',
    'Z1_MIDDLE': '#63b3ed', 'Z2_INTERFACE': '#d69e2e',
    'Z2_MIDDLE': '#ed8936', 'Z2_UP': '#c53030',
    'old': '#9ca3af', 'new': '#2f855a',
}


def setup_font():
    candidates = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC', 'FangSong',
                  'KaiTi', 'DejaVu Sans']
    for name in candidates:
        try:
            matplotlib.font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams['font.sans-serif'] = [name]
            plt.rcParams['axes.unicode_minus'] = False
            return name
        except Exception:
            continue
    plt.rcParams['axes.unicode_minus'] = False
    return None


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_data():
    payload = read_json(ROUTES)
    routes = {int(r['route_id']): r for r in payload['routes']
              if r.get('status') == 'routed'}
    failed = [r for r in payload['routes'] if r.get('status') != 'routed']
    rows = list(__import__('csv').DictReader(open(ASSIGN, encoding='utf-8-sig')))
    assign = {int(r['route_id']): r for r in rows}
    return routes, failed, assign


def sample_flat(primitives):
    points = []
    for prim in primitives:
        if prim['kind'] == 'line':
            points.extend([prim['p0'], prim['p1']])
        else:
            center = prim['center']
            radius = prim['radius']
            a0 = prim.get('start_angle', prim.get('a0', 0.0))
            sweep = prim.get('sweep', prim.get('a1', 0.0) - a0)
            n = max(4, int(abs(sweep) * radius / 0.5) + 2)
            for k in range(n + 1):
                angle = a0 + sweep * k / n
                points.append([center[0] + radius * math.cos(angle),
                               center[1] + radius * math.sin(angle)])
    return points


def route_lines(route):
    out = []
    for part in route.get('parts') or []:
        if part['kind'] == 'flat':
            pts = sample_flat(part.get('primitives') or [])
            z = float(part['z_mm'])
            out.append(([[p[0], p[1], z] for p in pts],
                        float(z), int(part['layer_id'])))
        elif part['kind'] == 'transition':
            if part.get('z0') is None or part.get('z1') is None:
                continue
            try:
                samples = transition_samples(part)
            except Exception:
                p0 = part.get('start') or [0, 0]
                p1 = part.get('end') or p0
                samples = [[p0[0] + (p1[0] - p0[0]) * t,
                            p0[1] + (p1[1] - p0[1]) * t,
                            part['z0'] + (part['z1'] - part['z0']) * t]
                           for t in (0, 0.5, 1)]
            if len(samples) >= 2:
                out.append(([[p[0], p[1], p[2]] for p in samples],
                            float(part['z0']), int(part['from_layer'])))
    return out


def add_3d(ax, routes, ids, color_fn, alpha=0.35, lw=0.6):
    for rid in ids:
        route = routes[rid]
        for pts, z0, layer in route_lines(route):
            if len(pts) < 2:
                continue
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    [p[2] for p in pts], color=color_fn(rid, layer, z0),
                    alpha=alpha, lw=lw)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_zlim(-0.25, 0.75)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_zlabel('z (mm)')


def save(fig, name, manifest, title):
    path = PLOTS / name
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    manifest.append(dict(file=name, title=title, status='rendered'))
    print('[plot]', name, title, flush=True)


def main():
    font = setup_font()
    PLOTS.mkdir(parents=True, exist_ok=True)
    routes, failed, assign = load_data()
    final = read_json(FINAL)
    old = read_json(OUT.parent / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/final_stats.json')
    manifest = []

    def region(rid):
        return assign[rid]['region']

    def plane_color(rid, layer, z0):
        if routes[rid]['plane'] == 'z1':
            return COLORS['Z1_DOWN'] if layer in (2, 3) else COLORS['Z1_OPP']
        if layer == 1:
            return COLORS['Z2_INTERFACE']
        return COLORS['Z2_UP'] if layer >= 9 else COLORS['Z2_MIDDLE']

    # 01 cross section at x = 75 mm (real intersections)
    fig, ax = plt.subplots(figsize=(13, 6))
    for rid, route in routes.items():
        color = plane_color(rid, int(assign[rid]['physical_layer'] or 1), 0)
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                pts = sample_flat(part.get('primitives') or [])
                z = float(part['z_mm'])
                for a, b in zip(pts, pts[1:]):
                    if (a[0] - 75) * (b[0] - 75) <= 0 and abs(b[0] - a[0]) > 1e-9:
                        t = (75 - a[0]) / (b[0] - a[0])
                        ax.plot([a[1] + t * (b[1] - a[1])], [z], '.',
                                color=color, ms=1.2, alpha=.35)
            elif part['kind'] == 'transition':
                try:
                    pts = transition_samples(part)
                except Exception:
                    continue
                for a, b in zip(pts, pts[1:]):
                    if (a[0] - 75) * (b[0] - 75) <= 0 and abs(b[0] - a[0]) > 1e-9:
                        t = (75 - a[0]) / (b[0] - a[0])
                        ax.plot([a[1] + t * (b[1] - a[1])],
                                [a[2] + t * (b[2] - a[2])], '.',
                                color=color, ms=1.2, alpha=.35)
    for z, label in ((Z1_MM, 'Z1 interface z=0'), (Z2_MM, 'Z2 interface z=0.5')):
        ax.axhline(z, color='black', ls='--', lw=.8)
        ax.text(2, z + .015, label, fontsize=8)
    ax.set_ylim(-0.25, .75)
    ax.set_xlabel('y (mm)')
    ax.set_ylabel('z (mm)')
    ax.set_title('图1 真实三维截面：1 mm 玻璃内 x=75 mm 处的波导中心线交点')
    save(fig, '01_cross_section_x75.png', manifest,
         '1 mm glass true 3D cross-section')

    # 02 physical layer stack
    fig, ax = plt.subplots(figsize=(11, 7))
    for layer, z in PHYSICAL_LAYERS.items():
        color = ('#2b6cb0' if z < 0 else '#63b3ed' if layer <= 7
                 else '#ed8936' if layer == 8 else '#c53030')
        ax.axhline(z, color=color, lw=5, alpha=.8)
        ax.text(-0.8, z, f'L{layer}  z={z:+.2f} mm', va='center', ha='right',
                fontsize=8)
    ax.axhline(Z1_MM, color='black', ls='--', lw=1.2)
    ax.axhline(Z2_MM, color='black', ls='--', lw=1.2)
    ax.text(11, Z1_MM + .01, 'Z1 interface z=0', fontsize=8)
    ax.text(11, Z2_MM + .01, 'Z2 interface z=0.5', fontsize=8)
    ax.axhline(-0.25, color='gray', lw=1)
    ax.axhline(0.75, color='gray', lw=1)
    ax.text(1, -.265, 'glass bottom z=-0.25', fontsize=8)
    ax.text(1, .755, 'glass top z=+0.75', fontsize=8)
    ax.set_xlim(-1, 20)
    ax.set_ylim(-0.28, .78)
    ax.set_yticks([])
    ax.set_title('图2 1 mm 玻璃物理层堆栈（10 个路由层 + 接口层）')
    save(fig, '02_physical_layer_stack.png', manifest,
         'physical layer stack')

    def overview(name, title, ids, color_fn):
        fig = plt.figure(figsize=(13, 10))
        ax = fig.add_subplot(111, projection='3d')
        add_3d(ax, routes, ids, color_fn)
        ax.set_title(title)
        save(fig, name, manifest, title)

    z1_ids = [rid for rid in routes if routes[rid]['plane'] == 'z1']
    z2_ids = [rid for rid in routes if routes[rid]['plane'] == 'z2']
    u_ids = [rid for rid in routes if assign[rid]['logical_kind'] == 'manual_u']
    down_ids = [rid for rid in z1_ids if assign[rid]['region'] == 'Z1_DOWN']
    up_ids = [rid for rid in z2_ids if assign[rid]['region'] == 'Z2_UP']
    # 03 Z1 down
    overview('03_z1_down_3d.png',
             '图3 Z1 向下布线三维总览（128 条真实负 z 过渡）',
             down_ids,
             lambda rid, layer, z0: COLORS['Z1_DOWN'])
    # 04 Z2 up
    overview('04_z2_up_3d.png',
             '图4 Z2 向上布线三维总览（182 条真实正 z 过渡）',
             up_ids,
             lambda rid, layer, z0: COLORS['Z2_UP'])
    # 05 middle region
    middle_ids = [rid for rid in routes if assign[rid]['region'] in
                  ('Z1_MIDDLE', 'Z2_MIDDLE', 'Z2_INTERFACE')]
    overview('05_middle_region_3d.png',
             f'图5 中间 z=0..0.5 区域实际使用（{len(middle_ids)} 条）',
             middle_ids, plane_color)
    # 06 U shapes
    overview('06_manual_u_3d.png',
             f'图6 256 条人工 U 的新三维形状（实际 {len(u_ids)} 条）',
             u_ids, lambda rid, layer, z0: COLORS['Z1_U'])
    # 07 Z1 NS/EW map top view
    fig, ax = plt.subplots(figsize=(11, 11))
    for rid in z1_ids:
        if assign[rid]['logical_kind'] not in ('z1_opposite_ns',
                                               'z1_opposite_ew'):
            continue
        layer = int(assign[rid]['physical_layer'])
        color = '#1f77b4' if assign[rid]['logical_kind'].endswith('ns') else '#ff7f0e'
        for part in routes[rid].get('parts') or []:
            if part['kind'] != 'flat':
                continue
            pts = sample_flat(part.get('primitives') or [])
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color,
                    lw=.45, alpha=.5)
    ax.set_xlim(0, 150); ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)'); ax.set_ylabel('y (mm)')
    ax.set_title('图7 Z1 相对边分层：蓝=南北逻辑组(L6)，橙=东西逻辑组(L7)')
    save(fig, '07_z1_opposite_layers.png', manifest,
         'Z1 opposite side layer map')
    # 08 Z2 groups vs layers (routed only)
    fig, ax = plt.subplots(figsize=(12, 6))
    groups = sorted({assign[rid].get('c4_group_id') for rid in z2_ids
                     if assign[rid].get('c4_group_id')})
    layers = sorted(PHYSICAL_LAYERS)
    matrix = [[0] * len(layers) for _ in groups]
    for rid in z2_ids:
        group = assign[rid].get('c4_group_id')
        if group not in groups:
            continue
        layer = assign[rid]['physical_layer']
        if not layer:
            continue
        matrix[groups.index(group)][layers.index(int(layer))] += 1
    im = ax.imshow(matrix, aspect='auto', cmap='YlOrRd')
    ax.set_xticks(range(len(layers)))
    ax.set_xticklabels([f'L{x}\n{PHYSICAL_LAYERS[x]:+.2f}' for x in layers])
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels([str(g) for g in groups])
    for i in range(len(groups)):
        for j in range(len(layers)):
            if matrix[i][j]:
                ax.text(j, i, matrix[i][j], ha='center', va='center',
                        fontsize=7)
    ax.set_title('图8 Z2 逻辑组与实际物理层对应（已布通线路计数）')
    fig.colorbar(im, ax=ax, label='routed count')
    save(fig, '08_z2_groups_layers.png', manifest,
         'Z2 logical groups vs physical layers')
    # 09 complete overview
    overview('09_all_1024_3d.png',
             f'图9 完整 1024 条线路三维总览（已布通 {len(routes)} 条）',
             list(routes), plane_color)
    # 10 per-layer 2D
    n = len(PHYSICAL_LAYERS)
    cols = 3
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(15, 4.2 * rows))
    axes = axes.ravel()
    for i, layer in enumerate(sorted(PHYSICAL_LAYERS)):
        ax = axes[i]
        ids = [rid for rid in routes if assign[rid]['physical_layer'] == str(layer)]
        for rid in ids:
            for part in routes[rid].get('parts') or []:
                if part['kind'] != 'flat':
                    continue
                pts = sample_flat(part.get('primitives') or [])
                ax.plot([p[0] for p in pts], [p[1] for p in pts],
                        lw=.35, alpha=.55)
        ax.set_xlim(0, 150); ax.set_ylim(0, 150)
        ax.set_aspect('equal')
        ax.set_title(f'L{layer} z={PHYSICAL_LAYERS[layer]:+.2f} mm, '
                     f'{len(ids)} 条', fontsize=9)
        ax.grid(alpha=.15)
    for j in range(n, len(axes)):
        axes[j].axis('off')
    fig.suptitle('图10 各物理层二维布线图（真实平面几何）', fontsize=14)
    fig.tight_layout()
    save(fig, '10_per_layer_2d.png', manifest,
         'per-layer 2D routing')
    # 11 interface zoom
    fig = plt.figure(figsize=(13, 10))
    ax = fig.add_subplot(111, projection='3d')
    zoom_ids = [rid for rid in routes if routes[rid]['plane'] == 'z1'
                and assign[rid]['logical_kind'] == 'manual_u'][:80]
    zoom_ids += [rid for rid in routes if routes[rid]['plane'] == 'z2'
                 and assign[rid]['region'] == 'Z2_UP'][:40]
    add_3d(ax, routes, zoom_ids, plane_color)
    ax.set_title('图11 Z1/Z2 接口附近升降段放大（真实 R15 过渡样本）')
    save(fig, '11_interface_transition_zoom.png', manifest,
         'interface transition zoom')
    # 12 old/new comparison
    common_old = None
    try:
        old_routes = read_json(OUT.parent / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL/routes_l3d.json')
        old_ids = {int(r['route_id']) for r in old_routes['routes']
                   if r.get('status') == 'routed'}
        new_ids = set(routes)
        common = old_ids & new_ids
        old_cross = read_json(OUT.parent /
                              'MANUAL_20L_FIXED_ASSIGNMENT_FULL/crossings_after.json')
        old_common = sum(1 for a, b in old_cross['remaining_pairs']
                         if a in common and b in common)
        new_cross = read_json(CROSS)
        new_common = sum(1 for a, b in new_cross['remaining_pairs']
                         if a in common and b in common)
        common_old = (len(common), old_common, new_common)
    except Exception as error:
        print('[plot] comparison fallback', error)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    labels = ['old 20L', 'new 1mm']
    routed = [old.get('routed'), final.get('routed')]
    axes[0].bar(labels, routed, color=[COLORS['old'], COLORS['new']])
    for i, value in enumerate(routed):
        axes[0].text(i, value + 8, str(value), ha='center')
    axes[0].set_ylabel('routed channels')
    axes[0].set_title('布通数：673 → 735')
    if common_old:
        axes[1].bar(['old common', 'new common'],
                    [common_old[1], common_old[2]],
                    color=[COLORS['old'], COLORS['new']])
        axes[1].set_title(f'共同 {common_old[0]} 条线路的交叉数')
        axes[1].set_ylabel('unique crossing pairs')
    else:
        axes[1].bar(['old total', 'new total'],
                    [old.get('crossings', {}).get('total_unique_pairs', 0),
                     final.get('crossings', {}).get('total_unique_pairs', 0)],
                    color=[COLORS['old'], COLORS['new']])
        axes[1].set_title('总交叉数')
    fig.suptitle('图12 新旧单向/双向方案对比（交叉数同时给出共同成功集合口径）')
    save(fig, '12_old_new_comparison.png', manifest, 'old/new comparison')
    (PLOTS / 'manifest.json').write_text(
        json.dumps(dict(figures=manifest, font=font), ensure_ascii=False,
                   indent=1), encoding='utf-8')
    print('[plots] done', len(manifest), flush=True)


if __name__ == '__main__':
    main()
