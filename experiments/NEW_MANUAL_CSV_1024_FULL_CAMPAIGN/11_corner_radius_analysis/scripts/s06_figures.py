# -*- coding: utf-8 -*-
"""Step 6: PNG figures (dpi=170, Agg).

fig01_spacing_distributions.png : same-side U port separation D, U middle
    straight m = D-2R, adjacent corner distances (a,b) and opposite lateral
    offset delta histograms with the R15 thresholds.
fig02_class_stats.png           : classification statistics (global by relation,
    per corner, and cross-tab with the phase-2 2D routing outcome).
fig03_corner_<CORNER>.png       : four corner local zooms (all ports of the 16
    corner connectors + all their connections drawn with the real R15 template
    geometry, annotated with the R15 margins) plus a full-board overview.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Arc, Patch, Rectangle

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corner_lib as L  # noqa: E402

OUT = L.OUT
DATA = L.DATA
FIG = OUT / 'figures'
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 170

R = L.R
TWO_R = L.TWO_R
REL_COLOR = {'same': '#1f77b4', 'adjacent': '#ff7f0e', 'opposite': '#2ca02c'}
REL_CN = {'same': '同边 U (same)', 'adjacent': '邻边 L (adjacent)',
          'opposite': '对边 S (opposite)'}
CLASS_ORDER = ['not_limited', 'pure90_template_limited',
               'conflict_needs_joint_search', 'rigid_template_conflict',
               'same_u_family_capacity_limited', 'lift_limited',
               'radius_limited_2d']
CLASS_CN = {
    'not_limited': '不受限',
    'pure90_template_limited': '仅纯90°模板受限\n(需 short-S 双弧)',
    'conflict_needs_joint_search': '模板存在但冲突\n(需联合搜索)',
    'rigid_template_conflict': '单弧L刚性冲突\n(需复合模板/换层)',
    'same_u_family_capacity_limited': '同边U族容量不足\n(4条深度轨道)',
    'lift_limited': '垂直S升降受限',
    'radius_limited_2d': 'R15 几何不可行',
}
CLASS_COLOR = {
    'not_limited': '#8c8c8c',
    'pure90_template_limited': '#ffbb78',
    'conflict_needs_joint_search': '#aec7e8',
    'rigid_template_conflict': '#c5b0d5',
    'same_u_family_capacity_limited': '#d62728',
    'lift_limited': '#bcbd22',
    'radius_limited_2d': '#000000',
}


def arc_points(prim, step=0.15):
    radius = float(prim['radius'])
    sweep = float(prim['sweep'])
    center = prim['center']
    start = float(prim['start_angle'])
    n = max(3, int(math.ceil(abs(sweep) * radius / step)) + 1)
    angles = start + np.linspace(0.0, sweep, n)
    return (center[0] + radius * np.cos(angles),
            center[1] + radius * np.sin(angles))


def draw_template(ax, template, **kwargs):
    for prim in template['primitives']:
        if prim['kind'] == 'line':
            ax.plot([prim['p0'][0], prim['p1'][0]],
                    [prim['p0'][1], prim['p1'][1]], **kwargs)
        else:
            x, y = arc_points(prim)
            ax.plot(x, y, **kwargs)


# ---------------------------------------------------------------------------
# fig01 spacing distributions
# ---------------------------------------------------------------------------
def fig_spacing(analysis):
    recs = analysis['connections']
    same = [r for r in recs if r['relation'] == 'same']
    adj = [r for r in recs if r['relation'] == 'adjacent']
    opp = [r for r in recs if r['relation'] == 'opposite']
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.0))
    fig.suptitle('R=15 mm 几何模板必要条件的端口间距分布（1024 条真实连接）',
                 fontsize=14, y=0.985)

    ax = axes[0][0]
    same_d = [r['same']['separation_D_mm'] for r in same]
    ax.hist(same_d, bins=np.arange(25, 140, 2.5), color=REL_COLOR['same'],
            edgecolor='white', linewidth=0.4)
    ax.axvline(TWO_R, color='#d62728', linestyle='--', linewidth=1.6,
               label=f'2R = {TWO_R:g} mm (U 模板下限)')
    ax.axvline(R, color='#ff7f0e', linestyle=':', linewidth=1.4,
               label=f'R = {R:g} mm')
    ax.set_xlim(10, 140)
    ax.set_xlabel('同侧两端点沿边间距 D (mm)')
    ax.set_ylabel('连接数')
    ax.set_title(f'(a) 同边 same 连接 D 分布（n={len(same)}，'
                 f'min={min(same_d):g}，<2R：0 条）')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[0][1]
    middle = [r['same']['middle_straight_mm'] for r in same]
    ax.hist(middle, bins=np.arange(0, 110, 2.5), color='#4c78a8',
            edgecolor='white', linewidth=0.4)
    ax.axvline(0.0, color='#d62728', linestyle='--', linewidth=1.6,
               label='m = 0：两弧相切（m<0 弧重叠，不可行）')
    ax.set_xlabel('U 型模板中间直线 m = D − 2R (mm)')
    ax.set_ylabel('连接数')
    ax.set_title(f'(b) U 型中间直线长度（min={min(middle):g} mm，'
                 f'median={np.median(middle):g} mm）')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1][0]
    min_corner = [min(r['adjacent']['a_source_to_corner_mm'],
                      r['adjacent']['b_target_to_corner_mm']) for r in adj]
    ax.hist(min_corner, bins=np.arange(20, 150, 2.5), color=REL_COLOR['adjacent'],
            edgecolor='white', linewidth=0.4)
    ax.axvline(R, color='#d62728', linestyle='--', linewidth=1.6,
               label='R = 15 mm（两端口到共用角点都需 ≥R）')
    ax.set_xlabel('邻边连接两端点到共用角点的最小距离 min(a,b) (mm)')
    ax.set_ylabel('连接数')
    ax.set_xlim(10, 150)
    ax.set_title(f'(c) 邻边 adjacent 单弧 L 条件（n={len(adj)}，'
                 f'min={min(min_corner):g}，直段 min={min(min_corner) - R:g} mm）')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1][1]
    deltas = [r['opposite']['delta_mm'] for r in opp]
    counts = Counter(round(d, 6) for d in deltas)
    values = sorted(counts)
    colors = ['#2ca02c' if (v <= 1e-9 or v >= TWO_R - 1e-9) else '#ffbb78'
              for v in values]
    ax.bar(values, [counts[v] for v in values], width=2.0, color=colors,
           edgecolor='white', linewidth=0.5)
    for v in values:
        ax.text(v, counts[v] + 0.7, str(counts[v]), ha='center', fontsize=7.5)
    ax.axvline(TWO_R, color='#d62728', linestyle='--', linewidth=1.6,
               label='δ = 2R = 30 mm')
    ax.set_xlim(-3, 66)
    ax.set_ylim(0, 66)
    ax.set_xlabel('对边连接横向偏移 δ (mm)')
    ax.set_ylabel('连接数')
    ax.set_title(f'(d) 对边 opposite 横向偏移分布（n={len(opp)}，'
                 f'δ<2R：{sum(1 for d in deltas if 1e-9 < d < TWO_R)} 条需 short-S）')
    handles = [Patch(color='#2ca02c', label='δ=0 直连 / δ≥2R 两个90°弧(+直线)'),
               Patch(color='#ffbb78', label='0<δ<2R：双弧 short-S (θ<90°)'),
               Line2D([], [], color='#d62728', ls='--', label='δ = 2R = 30 mm')]
    ax.legend(handles=handles, fontsize=7.5)
    ax.grid(alpha=0.25)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path = FIG / 'fig01_spacing_distributions.png'
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# fig02 classification statistics
# ---------------------------------------------------------------------------
def fig_classes(analysis, corner):
    recs = analysis['connections']
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 6.4),
                             gridspec_kw={'width_ratios': [1.15, 1.0, 1.0]})
    fig.suptitle('R=15 mm 模板可行性判定统计（1024 条连接 / 四角 16 连接器）',
                 fontsize=14, y=0.99)

    # (a) global stacked by relation
    ax = axes[0]
    relations = ['same', 'adjacent', 'opposite']
    bottom = np.zeros(len(relations))
    for cls in CLASS_ORDER:
        values = np.array([
            sum(1 for r in recs if r['relation'] == rel and
                r['judgement']['class_'] == cls) for rel in relations])
        if values.sum() == 0:
            continue
        ax.bar(range(len(relations)), values, bottom=bottom, width=0.62,
               color=CLASS_COLOR[cls], edgecolor='white',
               label=CLASS_CN[cls].replace('\n', ' '))
        bottom += values
    for i, rel in enumerate(relations):
        total = sum(1 for r in recs if r['relation'] == rel)
        ax.text(i, total + 8, f'n={total}', ha='center', fontsize=9)
    ax.set_xticks(range(len(relations)))
    ax.set_xticklabels([REL_CN[r] for r in relations], fontsize=8.5)
    ax.set_ylabel('连接数')
    ax.set_title('(a) 全板 1024 条按关系×判定类别')
    ax.set_ylim(0, 480)
    ax.grid(axis='y', alpha=0.25)

    # (b) per corner
    ax = axes[1]
    corners = ['NE', 'SE', 'SW', 'NW']
    bottom = np.zeros(len(corners))
    for cls in CLASS_ORDER:
        values = np.array([
            corner['corners'][c]['judgement_counts'].get(cls, 0)
            for c in corners])
        if values.sum() == 0:
            continue
        ax.bar(range(len(corners)), values, bottom=bottom, width=0.62,
               color=CLASS_COLOR[cls], edgecolor='white')
        bottom += values
    for i, c in enumerate(corners):
        ax.text(i, bottom[i] + 4, f'{int(bottom[i])}',
                ha='center', fontsize=8.5)
    ax.set_xticks(range(len(corners)))
    ax.set_xticklabels([f'{c} 角\n136–150 mm 端口区' for c in corners],
                       fontsize=8)
    ax.set_ylabel('连接数（每角接触 4 连接器的连接）')
    ax.set_title('(b) 四角局部判定（每角 128 条）')
    ax.set_ylim(0, 150)
    ax.grid(axis='y', alpha=0.25)

    # (c) phase-2 outcome x class
    ax = axes[2]
    outcome = analysis.get('two_d_routing_evidence', {}).get('summary', {})
    classes = [c for c in CLASS_ORDER if c not in ('radius_limited_2d',)]
    routed = []
    failed = []
    for cls in classes:
        routed.append(sum(1 for r in recs if r['judgement']['class_'] == cls
                          and r.get('phase2_2d_status') == 'routed'))
        failed.append(sum(1 for r in recs if r['judgement']['class_'] == cls
                          and r.get('phase2_2d_status') == 'failed'))
    x = np.arange(len(classes))
    ax.bar(x, routed, width=0.62, color='#54a24b', label='phase-2 2D 已布通')
    ax.bar(x, failed, bottom=routed, width=0.62, color='#e45756',
           label='phase-2 2D 失败')
    for i in range(len(classes)):
        if routed[i] + failed[i]:
            ax.text(i, routed[i] + failed[i] + 12,
                    f'{failed[i]}/{routed[i] + failed[i]}',
                    ha='center', fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([CLASS_CN[c].replace('\n', ' ') for c in classes],
                       fontsize=6.8, rotation=18, ha='right')
    ax.set_ylabel('连接数')
    ax.set_title('(c) 判定类别 × 已完成的 phase-2 2D 布线结果\n'
                 f'(共布通 {outcome.get("total_routed", "?")}，'
                 f'失败 {outcome.get("total_failed", "?")})')
    ax.legend(fontsize=8)
    ax.set_ylim(0, 520)
    ax.grid(axis='y', alpha=0.25)

    class_handles = [Patch(color=CLASS_COLOR[c], label=CLASS_CN[c].replace('\n', ' '))
                     for c in CLASS_ORDER
                     if c != 'radius_limited_2d'
                     or any(r['judgement']['class_'] == c for r in recs)]
    fig.legend(handles=class_handles, loc='lower center', ncol=4,
               fontsize=8.2, framealpha=0.95)
    fig.tight_layout(rect=(0, 0.10, 1, 0.94))
    path = FIG / 'fig02_class_stats.png'
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# fig03 corner zooms
# ---------------------------------------------------------------------------
CORNER_VIEW = {
    'NE': dict(local=(92.0, 152.0, 92.0, 152.0), bank=(124.0, 151.0, 124.0, 151.0)),
    'SE': dict(local=(92.0, 152.0, -2.0, 58.0), bank=(124.0, 151.0, -1.0, 26.0)),
    'SW': dict(local=(-2.0, 58.0, -2.0, 58.0), bank=(-1.0, 26.0, -1.0, 26.0)),
    'NW': dict(local=(-2.0, 58.0, 92.0, 152.0), bank=(-1.0, 26.0, 124.0, 151.0)),
}


def fig_corner(analysis, corner_name, corner_json, templates, records, eps):
    spec = corner_json['corners'][corner_name]
    view = CORNER_VIEW[corner_name]
    fig, axes = plt.subplots(1, 3, figsize=(20.0, 6.9),
                             gridspec_kw={'width_ratios': [1.0, 1.15, 1.0]})
    corner_ids = {e['route_id'] for e in spec['connections']}
    fig.suptitle(f'四角专项：{corner_name} 角（连接器 '
                 f'{", ".join(spec["corner_connector_set"])}）'
                 f' — R=15 mm 模板几何与半径余量（本角 {len(corner_ids)} 条连接）',
                 fontsize=13.0, y=0.985)

    # ---------------- (a) overview
    ax = axes[0]
    ax.set_aspect('equal')
    ax.add_patch(Rectangle((0, 0), 150, 150, fill=False, edgecolor='k', lw=1.2))
    for rid, template in templates.items():
        rid = int(rid)
        rec = records[rid]
        if rid in corner_ids:
            draw_template(ax, template, color=REL_COLOR[rec['relation']],
                          lw=0.7, alpha=0.8)
        else:
            draw_template(ax, template, color='#c8c8c8', lw=0.15, alpha=0.30)
    x0, x1, y0, y1 = view['local']
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                           edgecolor='#d62728', lw=1.3, ls='--'))
    bx0, bx1, by0, by1 = view['bank']
    ax.add_patch(Rectangle((bx0, by0), bx1 - bx0, by1 - by0, fill=False,
                           edgecolor='#7f7f7f', lw=1.0, ls=':'))
    for connector in spec['corner_connector_set']:
        xs, ys = [], []
        for eid, ep in eps.items():
            if ep['connector'] == connector and ep['plane'] == 'z1':
                xs.append(ep['routing_xy'][0])
                ys.append(ep['routing_xy'][1])
        ax.plot(xs, ys, 's', ms=1.4, color='k')
    ax.set_xlim(-3, 153)
    ax.set_ylim(-3, 153)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title('(a) 全板：本角连接（彩色）\n红虚线 = 局部放大窗，灰点线 = 端口区')
    handles = [Line2D([], [], color=REL_COLOR[r], lw=1.6, label=REL_CN[r])
               for r in ('same', 'adjacent', 'opposite')]
    handles.append(Line2D([], [], color='#c8c8c8', lw=0.8,
                          label='其余 896 条模板（灰）'))
    ax.legend(handles=handles, fontsize=7.0, loc='upper left', framealpha=0.9)
    ax.grid(alpha=0.2)

    # ---------------- (b) local window
    ax = axes[1]
    ax.set_aspect('equal')
    ax.add_patch(Rectangle((0, 0), 150, 150, fill=False, edgecolor='k', lw=0.8))
    for entry in spec['connections']:
        rid = entry['route_id']
        rec = records[rid]
        draw_template(ax, templates[str(rid)],
                      color=REL_COLOR[rec['relation']],
                      lw=1.0 if rec['relation'] == 'same' else 0.85,
                      alpha=0.65)
    x0, x1, y0, y1 = view['local']
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title(f'(b) 局部放大 {x1 - x0:g}×{y1 - y0:g} mm：本角全部连接模板\n'
                 f'（R15 模板真实几何，弧半径=15 mm）')
    ax.grid(alpha=0.2)
    handles = [Line2D([], [], color=REL_COLOR[r], lw=1.8, label=REL_CN[r])
               for r in ('same', 'adjacent', 'opposite')]
    ax.legend(handles=handles, fontsize=7.2, loc='lower left', framealpha=0.9)

    # ---------------- (c) connector port bank detail
    ax = axes[2]
    ax.set_aspect('equal')
    for entry in spec['connections']:
        rid = entry['route_id']
        rec = records[rid]
        draw_template(ax, templates[str(rid)],
                      color=REL_COLOR[rec['relation']],
                      lw=1.2 if rec['relation'] == 'same' else 1.0,
                      alpha=0.75)
    for connector in spec['corner_connector_set']:
        xs, ys = [], []
        for eid, ep in eps.items():
            if ep['connector'] == connector and ep['plane'] == 'z1':
                xs.append(ep['routing_xy'][0])
                ys.append(ep['routing_xy'][1])
        ax.plot(xs, ys, 's', ms=4.0, color='k', zorder=5)
        cx, cy = float(np.mean(xs)), float(np.mean(ys))
        side = connector[0]
        if side == 'N':
            label_xy = (cx, cy - 3.2)
        elif side == 'S':
            label_xy = (cx, cy + 3.2)
        elif side == 'E':
            label_xy = (cx - 3.2, cy)
        else:
            label_xy = (cx + 3.2, cy)
        ax.annotate(connector, xy=(cx, cy), xytext=label_xy,
                    fontsize=9, color='k', fontweight='bold',
                    ha='center', va='center',
                    bbox=dict(boxstyle='round,pad=0.16', fc='white',
                              ec='0.5', alpha=0.9))
    ccx, ccy = spec['corner_xy']
    ax.plot([ccx], [ccy], marker='*', ms=15, color='#d62728', zorder=6)
    bx0, bx1, by0, by1 = view['bank']
    ax.set_xlim(bx0, bx1)
    ax.set_ylim(by0, by1)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title('(c) 端口区细节：4 个连接器 × 16 列（列距 0.25 mm）\n'
                 '每列 = 1 个 row1 孔 + 1 个 row2 孔（z=0 / 0.5 mm）')
    ax.grid(alpha=0.25)

    # ---------------- bottom statistics strip
    mins = spec['min_margins_mm']
    jc = spec['judgement_counts']
    stats = (
        f'[本角余量] U: m=D−2R ≥ {mins["same"]} mm ｜ '
        f'邻边 L: min(a,b)−R ≥ {mins["adjacent"]} mm ｜ '
        f'对边 S: min δ 余量 {mins["opposite"]} mm    '
        f'[判定] R15 不可行 {jc.get("radius_limited_2d", 0)} 条 ｜ '
        f'仅纯90°模板受限 {jc.get("pure90_template_limited", 0)} 条 ｜ '
        f'同边U族容量 {jc.get("same_u_family_capacity_limited", 0)} 条 ｜ '
        f'单弧L刚性冲突 {jc.get("rigid_template_conflict", 0)} 条 ｜ '
        f'模板存在但需联合搜索 {jc.get("conflict_needs_joint_search", 0)} 条 ｜ '
        f'phase-2 2D 失败 {spec.get("phase2_failed_connections", "?")} 条'
    )
    fig.text(0.5, 0.012, stats, ha='center', va='bottom', fontsize=8.4,
             family='Microsoft YaHei',
             bbox=dict(boxstyle='round,pad=0.3', fc='#fffbe6', ec='0.5',
                       alpha=0.95))

    fig.tight_layout(rect=(0, 0.045, 1, 0.95))
    path = FIG / f'fig03_corner_{corner_name}.png'
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def main():
    eps = L.load_endpoints()
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
    templates = json.loads((DATA / 'geometry_1024.json').read_text(
        encoding='utf-8'))['templates']
    records = {r['route_id']: r for r in analysis['connections']}

    produced = []
    produced.append(str(fig_spacing(analysis)))
    produced.append(str(fig_classes(analysis, corner)))
    for name in ('NE', 'SE', 'SW', 'NW'):
        produced.append(str(fig_corner(analysis, name, corner, templates,
                                       records, eps)))
    print('\n'.join(produced))


if __name__ == '__main__':
    main()
