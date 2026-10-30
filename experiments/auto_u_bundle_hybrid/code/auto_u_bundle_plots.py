# -*- coding: utf-8 -*-
"""Routing figures for the automatic U group/layer experiment (new output only)."""
from __future__ import annotations

import json
from pathlib import Path

from . import spatial_u_bundle_plots as SP

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity'
OUT = CAMPAIGN / 'auto_u_bundle_hybrid'
HYBRID = CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json'
FIGDIR = OUT / 'figures'

COLORS = {0: '#1f6fd6', 1: '#2f9e44', 2: '#7048e8', 3: '#e03131'}
NAMES = {0: '簇0 组20–35', 1: '簇1 组144–159',
         2: '簇2 组160–175', 3: '簇3 组176–191'}
LAYER_Z = {2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5}
LAYER_LABEL = {0.0: 'L1-z1 (z=0.0)', 0.5: 'L1-z2 (z=0.5)',
               1.0: 'L2 (z=1.0)', 1.5: 'L3 (z=1.5)',
               2.0: 'L4 (z=2.0)', 2.5: 'L5 (z=2.5)'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load():
    auto = read(OUT / 'routes_1024.json')
    before = read(HYBRID)
    assign = read(OUT / 'auto_assignment.json')
    clusters = {int(c['cluster_id']): dict(groups=[int(g) for g in c['groups']])
                for c in assign['clusters']}
    assignment = {int(k): int(v) for k, v in assign['assignment'].items()}
    # route -> cluster / target layer
    rid_cluster = {}
    for cid, c in clusters.items():
        for gid in c['groups']:
            for rid in read(CAMPAIGN / 'inputs/connectivity_1024.json')['groups'][0]['route_ids']:
                pass
    # use connectivity groups directly
    conn = read(CAMPAIGN / 'inputs/connectivity_1024.json')
    groups = {int(g['group_id']): g for g in conn['groups']}
    for cid, c in clusters.items():
        for gid in c['groups']:
            for rid in groups[gid]['route_ids']:
                rid_cluster[int(rid)] = cid
    return auto, before, clusters, assignment, rid_cluster


def draw_route(ax, record, color=None, highlight_z=None,
               linewidth=0.45, alpha=0.55):
    if color is None:
        SP.draw_route(ax, record, linewidth=linewidth, alpha=alpha)
    else:
        SP.draw_route(ax, record, highlight_color=color,
                      z_highlight=highlight_z, linewidth=linewidth,
                      alpha=alpha)


def whole(ax, records, rid_cluster, assignment, title):
    from matplotlib.lines import Line2D
    SP._draw_reference(ax, 0.0)
    for record in records:
        rid = int(record['route_id'])
        cid = rid_cluster.get(rid)
        if cid is None:
            draw_route(ax, record, linewidth=0.4, alpha=0.5)
        else:
            draw_route(ax, record, COLORS[cid],
                       highlight_z=LAYER_Z[assignment[cid]],
                       linewidth=0.5, alpha=0.65)
    handles = [Line2D([0], [0], color=COLORS[c], lw=2.2,
                      label=f'{NAMES[c]} → L{assignment[c]}')
               for c in sorted(COLORS)]
    handles += [Line2D([0], [0], color='#777777', lw=1.0, label='非 U 路线'),
                Line2D([0], [0], color='#8c8c8c', lw=1.4, label='升降 S 曲线')]
    ax.legend(handles=handles, loc='upper right', fontsize=7.2, framealpha=0.85)
    SP._decorate(ax, title)


def layer(ax, records, rid_cluster, assignment, z_mm, title):
    from matplotlib.lines import Line2D
    SP._draw_reference(ax, z_mm, color=SP.LAYER_COLORS.get(z_mm, '#999999'),
                       alpha=0.05)
    total = highlighted = 0
    for record in records:
        if not SP.uses_layer(record, z_mm):
            continue
        total += 1
        rid = int(record['route_id'])
        cid = rid_cluster.get(rid)
        if cid is not None and LAYER_Z[assignment[cid]] == z_mm:
            highlighted += 1
            draw_route(ax, record, COLORS[cid], highlight_z=z_mm,
                       linewidth=0.55, alpha=0.6)
        else:
            draw_route(ax, record, linewidth=0.32, alpha=0.28)
    handles = []
    for c in sorted(COLORS):
        if LAYER_Z[assignment[c]] == z_mm:
            handles.append(Line2D([0], [0], color=COLORS[c], lw=2.3,
                                  label=f'{NAMES[c]}（目标层）'))
    if not handles:
        handles.append(Line2D([0], [0], color='#777777', lw=1,
                              label='该层无 U 目标簇'))
    handles.append(Line2D([0], [0], color='#999999', lw=1, alpha=0.5,
                          label='其他路线（该层水平段）'))
    ax.legend(handles=handles, loc='upper right', fontsize=7.2, framealpha=0.85)
    SP._decorate(ax, f'{title}\n该层水平传播 {total} 条（高亮目标 U {highlighted} 条）')


def bundles(ax, records, rid_cluster, assignment, title):
    from matplotlib.lines import Line2D
    SP._draw_reference(ax, 0.0)
    for record in records:
        rid = int(record['route_id'])
        cid = rid_cluster.get(rid)
        if cid is None:
            continue
        draw_route(ax, record, COLORS[cid],
                   highlight_z=LAYER_Z[assignment[cid]],
                   linewidth=0.65, alpha=0.65)
    handles = [Line2D([0], [0], color=COLORS[c], lw=2.4,
                      label=f'{NAMES[c]} → L{assignment[c]}（{LAYER_Z[assignment[c]]} mm）')
               for c in sorted(COLORS)]
    handles.append(Line2D([0], [0], color='#8c8c8c', lw=1.4,
                          label='升降 S 曲线（R=15 mm）'))
    ax.legend(handles=handles, loc='upper right', fontsize=7.2, framealpha=0.85)
    SP._decorate(ax, title)


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    FIGDIR.mkdir(parents=True, exist_ok=True)
    auto, before, clusters, assignment, rid_cluster = load()
    before_records = [r for r in before['routes'] if r.get('status') == 'routed']
    auto_records = [r for r in auto['routes'] if r.get('status') == 'routed']
    print('records', len(before_records), len(auto_records))

    # 01/02 whole-board before/after
    for name, records, title, src in (
            ('01_before_3d', before_records,
             '优化前：Hybrid H（1024/1024，12,960 唯一交叉对）',
             'hybrid_c2_c4_directional/H/routes_1024.json'),
            ('02_after_3d', auto_records,
             '自动 U 分组/分层结果（1024/1024，12,960 唯一交叉对）',
             'auto_u_bundle_hybrid/routes_1024.json')):
        fig = plt.figure(figsize=SP.FIGSIZE)
        ax = fig.add_subplot(111, projection='3d')
        fig.subplots_adjust(left=0.01, right=0.99, bottom=0.045, top=0.885)
        whole(ax, records, rid_cluster, assignment, title)
        fig.text(0.5, 0.015, f'数据来源：{src}（仅可视化，未重新布线）',
                 ha='center', va='center', fontsize=8, color='#666666')
        SP._save(fig, FIGDIR / name)
        plt.close(fig)
        print('wrote', name)

    # per-layer figures
    layer_specs = [('03_L1_z1', 0.0, 'L1-z1（row1 接口层）'),
                   ('04_L1_z2', 0.5, 'L1-z2（row2 接口层）'),
                   ('05_L2', 1.0, 'L2（自动 U 目标层之一）'),
                   ('06_L3', 1.5, 'L3（自动 U 目标层）'),
                   ('07_L4', 2.0, 'L4（自动 U 目标层）'),
                   ('08_L5', 2.5, 'L5（自动 U 目标层）')]
    for name, z, title in layer_specs:
        fig = plt.figure(figsize=SP.FIGSIZE)
        ax = fig.add_subplot(111, projection='3d')
        fig.subplots_adjust(left=0.01, right=0.99, bottom=0.045, top=0.885)
        layer(ax, auto_records, rid_cluster, assignment, z, title)
        SP._save(fig, FIGDIR / name)
        plt.close(fig)
        print('wrote', name)

    # only U bundles, 3D
    fig = plt.figure(figsize=SP.FIGSIZE)
    ax = fig.add_subplot(111, projection='3d')
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.045, top=0.885)
    bundles(ax, auto_records, rid_cluster, assignment,
            '自动分组后的 4 个 U 线束（共 64 个四元组 / 256 条）')
    SP._save(fig, FIGDIR / '09_u_bundles_3d')
    plt.close(fig)
    print('wrote 09_u_bundles_3d')

    # dense region zoom (before / after), same window
    fig = plt.figure(figsize=(15.4, 8.6))
    for i, (records, title) in enumerate((
            (before_records, '优化前 Hybrid H：U 固定在 L3/L4/L5'),
            (auto_records, '自动分组/层分配：U 分组不变，层由搜索决定'))):
        ax = fig.add_subplot(1, 2, i + 1, projection='3d')
        SP._draw_reference(ax, 0.0)
        for record in records:
            rid = int(record['route_id'])
            cid = rid_cluster.get(rid)
            if cid is not None:
                draw_route(ax, record, COLORS[cid],
                           highlight_z=LAYER_Z[assignment[cid]],
                           linewidth=0.55, alpha=0.75)
            else:
                draw_route(ax, record, linewidth=0.35, alpha=0.22)
        ax.set_xlim(40.0, 110.0)
        ax.set_ylim(40.0, 110.0)
        ax.set_zlim(-0.05, 2.6)
        ax.set_xlabel('x (mm)')
        ax.set_ylabel('y (mm)')
        ax.set_zlabel('z (mm)')
        ax.view_init(**SP.VIEW)
        ax.set_box_aspect((1.0, 1.0, 0.45))
        ax.set_title(title, fontsize=10.5, pad=8)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.04, top=0.92, wspace=0.05)
    SP._save(fig, FIGDIR / '10_dense_region_zoom')
    plt.close(fig)
    print('wrote 10_dense_region_zoom')
    print('figures written to', FIGDIR)


if __name__ == '__main__':
    main()
