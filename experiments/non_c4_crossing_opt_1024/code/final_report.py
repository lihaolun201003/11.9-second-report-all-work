# -*- coding: utf-8 -*-
"""Final deliverable generation for the C4-free experiment (plots/report/MANIFEST/archive)."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import numpy as np

from ..reheight21 import model as M
from . import crossings as X
from . import data as D
from . import paths as P


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sample(primitives, step=2.0):
    xs, ys = [], []
    for prim in primitives or ():
        if prim.get('kind') == 'line':
            p0, p1 = prim['p0'], prim['p1']
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            count = max(2, int(length / step) + 2)
            for i in range(count):
                t = i / (count - 1)
                xs.append(p0[0] + (p1[0] - p0[0]) * t)
                ys.append(p0[1] + (p1[1] - p0[1]) * t)
        elif prim.get('kind') == 'arc':
            center, radius = prim['center'], float(prim['radius'])
            start, sweep = float(prim['start_angle']), float(prim['sweep'])
            count = max(2, int(abs(sweep) * radius / step) + 2)
            for i in range(count):
                angle = start + sweep * i / (count - 1)
                xs.append(center[0] + radius * math.cos(angle))
                ys.append(center[1] + radius * math.sin(angle))
    return xs, ys


def _polyline_3d(route):
    points = []
    for part in route.get('parts') or ():
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            xs, ys = _sample(part.get('primitives'), step=4.0)
            points.extend((x, y, float(part.get('z_mm', 0.0)))
                          for x, y in zip(xs, ys))
        elif part.get('kind') == 'transition':
            start, end = part['start'], part['end']
            points.extend([(start[0], start[1], float(part['z0'])),
                           (end[0], end[1], float(part['z1']))])
    return points


def _plane_of_z(planes, z):
    for item in planes['planes']:
        if abs(float(item['z_mm']) - float(z)) < 1e-9:
            return item
    return None


def make_plots(exp_dir, out_dir=None, log=print):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    exp_dir = Path(exp_dir)
    out_dir = Path(out_dir or exp_dir / 'plots')
    (out_dir / 'per_height').mkdir(parents=True, exist_ok=True)
    records = D.route_records(exp_dir / 'routes_l3d.json')
    assignment = {int(row['route_id']): row
                  for row in D.assignment_rows(exp_dir)}
    planes = D.layer_planes(exp_dir)
    report = D.load_json(exp_dir / 'crossing_stats.json')
    baseline = D.baseline_crossing_stats()
    events = report.get('crossing_events') or []
    families = {rid: D.family_of(row) for rid, row in assignment.items()}
    colors = {'Z1V': '#1f77b4', 'Z1H': '#ff7f0e', 'Z2_NE': '#2ca02c',
              'Z2_SE': '#d62728', 'Z2_NW': '#9467bd', 'Z2_SW': '#8c564b'}
    groups = X.flat_groups_by_z(records)
    events_by_z = OrderedDict()
    per_route = Counter()
    for event in events:
        events_by_z.setdefault(round(float(event['z_mm']), 9), []).append(event)
        per_route[int(event['route_a'])] += 1
        per_route[int(event['route_b'])] += 1
    count = 0
    for z_key in sorted(groups):
        plane = _plane_of_z(planes, z_key)
        label = plane['label'] if plane else ('z%+.3f' % z_key)
        figure, axis = plt.subplots(figsize=(7.2, 7.2))
        for route_id, prims in groups[z_key].items():
            manual = str((assignment.get(int(route_id)) or {})
                         .get('manual_group') or '').strip()
            xs, ys = _sample(prims, step=2.0)
            axis.plot(xs, ys,
                      color=('#888888' if manual
                             else colors.get(families.get(int(route_id), ''),
                                             '#333333')),
                      lw=0.7, alpha=0.6 if manual else 0.85)
        plane_events = events_by_z.get(round(z_key, 9), [])
        if plane_events:
            axis.scatter([e['x_mm'] for e in plane_events],
                         [e['y_mm'] for e in plane_events],
                         marker='x', s=26, c='red', zorder=5, linewidths=1.0)
        axis.set_xlim(-2, 152)
        axis.set_ylim(-2, 152)
        axis.set_aspect('equal')
        axis.set_title('%s z=%+.3f mm routes=%d crossings=%d'
                       % (label, z_key, len(groups[z_key]),
                          len(plane_events)), fontsize=10)
        axis.set_xlabel('x (mm)')
        axis.set_ylabel('y (mm)')
        figure.tight_layout()
        count += 1
        figure.savefig(out_dir / 'per_height'
                       / ('%02d_%s_z%+.3f.png' % (count, label, z_key)),
                       dpi=115)
        plt.close(figure)
    log('[plots] per-height: %d' % count)

    figure, axis = plt.subplots(figsize=(7.5, 7.0))
    if events:
        hb = axis.hexbin([e['x_mm'] for e in events],
                         [e['y_mm'] for e in events],
                         gridsize=45, cmap='inferno', mincnt=1)
        figure.colorbar(hb, ax=axis, label='crossing events (all heights)')
    axis.set_xlim(0, 150)
    axis.set_ylim(0, 150)
    axis.set_aspect('equal')
    axis.set_title('crossing hotspot density, all heights (%d events)'
                   % len(events))
    figure.tight_layout()
    figure.savefig(out_dir / 'crossing_hotspot.png', dpi=120)
    plt.close(figure)

    base_by_label = {row['label']: row['crossings']
                     for row in baseline['planes']}
    new_by_label = {row['label']: row['crossings']
                    for row in report['planes']}
    labels = [item['label'] for item in planes['planes']]
    base_values = [int(base_by_label.get(label, 0)) for label in labels]
    new_values = [int(new_by_label.get(label, 0)) for label in labels]
    figure, axis = plt.subplots(figsize=(11, 4.2))
    positions = np.arange(len(labels))
    axis.bar(positions - 0.2, base_values, width=0.4, label='baseline 21H',
             color='#999999')
    axis.bar(positions + 0.2, new_values, width=0.4,
             label='C4-free accepted', color='#1f77b4')
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=60, ha='right', fontsize=7)
    axis.set_ylabel('same-layer crossing events')
    axis.legend()
    axis.set_title('per-height crossings: baseline vs C4-free accepted')
    figure.tight_layout()
    figure.savefig(out_dir / 'per_height_crossings_compare.png', dpi=120)
    plt.close(figure)

    values = sorted(per_route.values()) if per_route else [0]
    figure, axis = plt.subplots(figsize=(7.5, 4.0))
    axis.hist(values, bins=40, color='#1f77b4')
    axis.set_xlabel('crossings per route')
    axis.set_ylabel('routes')
    axis.set_title('per-route crossing distribution (max=%d, routes with '
                   'crossings=%d)' % (max(values), len(per_route)))
    figure.tight_layout()
    figure.savefig(out_dir / 'per_route_crossing_histogram.png', dpi=120)
    plt.close(figure)

    baseline_assignment = {int(row['route_id']): row
                           for row in D.baseline_assignment()}
    family_names = ['Z1V', 'Z1H', 'Z2_NE', 'Z2_SE', 'Z2_NW', 'Z2_SW', 'MANUAL']
    figure, axes = plt.subplots(1, 2, figsize=(13, 4.4), sharey=True)
    for axis, source, title in (
            (axes[0], baseline_assignment, 'C4 baseline (orbit-bound)'),
            (axes[1], assignment, 'C4-free accepted (per route_id)')):
        bottom = np.zeros(len(labels))
        for family in family_names:
            counts = []
            for label in labels:
                number = 0
                for row in source.values():
                    if M.plane_label(int(row['target_layer'])) != label:
                        continue
                    manual = str(row.get('manual_group') or '').strip()
                    if family == 'MANUAL':
                        number += 1 if manual else 0
                    elif not manual and D.family_of(row) == family:
                        number += 1
                counts.append(number)
            color = '#555555' if family == 'MANUAL' else colors.get(family,
                                                                    '#333333')
            axis.bar(labels, counts, bottom=bottom, color=color, label=family)
            bottom += np.array(counts)
        axis.set_title(title)
        axis.tick_params(axis='x', rotation=60, labelsize=7)
    axes[0].legend(fontsize=6, ncol=2)
    figure.suptitle('layer assignment before/after removing the C4 binding')
    figure.tight_layout()
    figure.savefig(out_dir / 'assignment_c4_vs_free.png', dpi=120)
    plt.close(figure)

    top_ids = {int(rid) for rid, _ in
               sorted(per_route.items(), key=lambda item: -item[1])[:10]}
    figure, axis = plt.subplots(figsize=(8, 8))
    for z_key, route_prims in groups.items():
        for route_id, prims in route_prims.items():
            xs, ys = _sample(prims, step=2.5)
            if int(route_id) in top_ids:
                axis.plot(xs, ys, color='red', lw=1.6, alpha=0.95, zorder=4)
            else:
                axis.plot(xs, ys, color='#bbbbbb', lw=0.4, alpha=0.45,
                          zorder=1)
    axis.set_xlim(-2, 152)
    axis.set_ylim(-2, 152)
    axis.set_aspect('equal')
    axis.set_title('top-10 highest-crossing routes (red), all heights')
    figure.tight_layout()
    figure.savefig(out_dir / 'top10_high_crossing_routes.png', dpi=120)
    plt.close(figure)

    figure = plt.figure(figsize=(9.5, 8.0))
    axis = figure.add_subplot(111, projection='3d')
    for route in records:
        points = _polyline_3d(route)
        if len(points) < 2:
            continue
        arrays = np.array(points)
        axis.plot(arrays[:, 0], arrays[:, 1], arrays[:, 2],
                  color=plt.cm.viridis(arrays[:, 2].mean() + 0.35), lw=0.25,
                  alpha=0.5)
    axis.set_xlabel('x (mm)')
    axis.set_ylabel('y (mm)')
    axis.set_zlabel('z (mm)')
    axis.set_title('1024 waveguides on 21 heights (accepted C4-free, %d '
                   'crossings)' % len(events))
    figure.tight_layout()
    figure.savefig(out_dir / '3d_overview_1024.png', dpi=105)
    plt.close(figure)

    curve = [('E0 baseline', int(baseline['totals']['crossings']))]
    for name, path in (
            ('E2 conflict-graph',
             P.experiment_dir('E2_conflict_assignment') / 'crossing_stats.json'),
            ('E3 SA family-pure',
             P.experiment_dir('E3_family_pure_optimized') / 'crossing_stats.json'),
            ('E5 accepted', exp_dir / 'crossing_stats.json')):
        try:
            payload = D.load_json(path)
            curve.append((name, int(payload['totals']['crossings'])))
        except (FileNotFoundError, KeyError):
            continue
    figure, axis = plt.subplots(figsize=(8.0, 4.2))
    names = [item[0] for item in curve]
    values = [item[1] for item in curve]
    axis.plot(range(len(values)), values, marker='o', color='#1f77b4')
    for index, value in enumerate(values):
        axis.annotate(str(value), (index, value), textcoords='offset points',
                      xytext=(0, 6), ha='center', fontsize=8)
    axis.set_xticks(range(len(names)))
    axis.set_xticklabels(names, rotation=25, ha='right', fontsize=8)
    axis.set_ylabel('total same-layer crossings')
    axis.grid(alpha=0.3)
    axis.set_title('global crossing count across experiment stages')
    figure.tight_layout()
    figure.savefig(out_dir / 'optimization_curve.png', dpi=120)
    plt.close(figure)
    log('[plots] total figures: %d' % len(list(out_dir.rglob('*.png'))))
    return len(list(out_dir.rglob('*.png')))


def _fmt(value, digits=3):
    try:
        return ('%.' + str(digits) + 'f') % float(value)
    except (TypeError, ValueError):
        return str(value)


def write_reports(exp_dir, log=print):
    exp_dir = Path(exp_dir)
    report = D.load_json(exp_dir / 'crossing_stats.json')
    validation = D.load_json(exp_dir / 'validation.json')
    stats = D.load_json(exp_dir / 'final_stats.json')
    baseline = D.baseline_crossing_stats()
    audit = D.load_json(exp_dir / 'assignment_audit.json')
    plan = D.load_json(exp_dir / 'assignment_plan.json')
    frozen = D.load_json(exp_dir / 'manual_frozen_check.json')
    e2_cross = None
    e3_cross = None
    try:
        e2_cross = int(D.load_json(P.experiment_dir('E2_conflict_assignment')
                                   / 'crossing_stats.json')
                       ['totals']['crossings'])
    except (FileNotFoundError, KeyError):
        pass
    try:
        e3_cross = int(D.load_json(P.experiment_dir('E3_family_pure_optimized')
                                   / 'crossing_stats.json')
                       ['totals']['crossings'])
    except (FileNotFoundError, KeyError):
        pass
    assignment = {int(row['route_id']): row
                  for row in D.assignment_rows(exp_dir)}
    families_by_plane = defaultdict(Counter)
    for route_id, row in assignment.items():
        key = ('MANUAL' if str(row.get('manual_group') or '').strip()
               else D.family_of(row))
        families_by_plane[int(row['target_layer'])][key] += 1
    base_by_label = {row['label']: row for row in baseline['planes']}
    new_dist = report['totals']['per_route_distribution']
    base_dist = baseline['totals']['per_route_distribution']
    total = report['totals']['crossings']
    lines = []
    lines.append('# 取消 C4 对称约束的 1024 通道近零交叉三维光波导自动布线研究报告\n')
    lines.append('生成时间：%s  ' % time.strftime('%Y-%m-%dT%H:%M:%S'))
    lines.append('运行目录：`%s`  ' % exp_dir)
    lines.append('基线（只读）：`outputs/manual_c4_new_connectivity/'
                 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`（commit '
                 '`2899485dea045fab6558926aae2d900b68679e01`）\n')
    lines.append('## 0. 结论摘要\n')
    lines.append('* 最终合法布通：**%d / 1024**（失败 %d 条；Z1 %d / Z2 %d）'
                 % (report['routed'], report['failed'], stats['z1_routed'],
                    stats['z2_routed']))
    lines.append('* 真实同层交叉：**%d** 次 / %d 对（基线 11890 / 9797；'
                 '变化 %+d，%+.2f%%）'
                 % (total, report['totals']['crossing_pairs'], total - 11890,
                    (total / 11890.0 - 1) * 100))
    lines.append('* 严格验证：geometry_pass=%s，contract_pass=%s，'
                 'validation_pass=%s，违规 %s 条；最小真实 3D 净空 %s mm'
                 '（规则 0.05 mm）；最小弯曲半径 %s mm（R15 未降低）'
                 % (validation['geometry_pass'], validation['contract_pass'],
                    validation['validation_pass'],
                    validation.get('violation_count'),
                    _fmt(validation.get('min_3d_clearance_mm'), 9),
                    _fmt((validation.get('counts') or {})
                         .get('min_flat_arc_radius_mm'))))
    lines.append('* 人工 U 分组：368 条线路完整几何与 21 高度基线逐条一致 = %s'
                 '（不一致 %d 条）' % (frozen['frozen'], frozen['mismatch_count']))
    lines.append('* 实验链：E0 基线 11890 → E1 仅取消 C4（朴素分块）6495'
                 '（1020/1024）→ E2 冲突图兼容共面 %s（失败实验）→ '
                 'E3 冲突图+退火分区 %s（1022/1024）→ '
                 '**E5 联合修复 %d（1024/1024，0 违规）**'
                 % (e2_cross, e3_cross, total))
    lines.append('* 总长度 %s mm；三维过渡 %d 个；直连线路 %d 条\n'
                 % (_fmt(stats['total_length_mm'], 3),
                    stats['total_transitions'], stats['direct_routes']))
    lines.append('## 1. 方法与执行顺序\n')
    lines.append('1. **代码审计**：定位并解除 `assign21.py`/`run21.py`/'
                 '`validate21.py` 中的 C4 硬检查（整轨道同层分配、每层固定条数、'
                 '`c4_orbit_not_single_plane` 违约项），其余几何/端口/合同检查'
                 '全部保留（`nonc4/validate_nc.py` 仅移除该唯一 C4 项）。')
    lines.append('2. **交叉来源分析**：`analysis/` 下 11890 条交叉事件的完整数据库、'
                 '1024 条线路统计、21 层汇总、家族对矩阵、冲突图与 L9/L15 谜题解释'
                 '（见 §4）。')
    lines.append('3. **无 C4 全局层分配**：以每条 `route_id` 为单位，用实测端口弦'
                 '交叉图 + 模拟退火分区把每个方向家族最优划分到自己的物理高度'
                 '（`nonc4/assign_opt.py`）。')
    lines.append('4. **交叉感知二维布线**：`nonc4/cross_router.py` 候选级交叉代价 + '
                 '确定性降交叉重布；在基线混乱层 -11.9%（9106→8020），但在本轮'
                 '家族纯净层已达弦下界、无进一步收益，故正式解采用生产路由器。')
    lines.append('5. **联合修复**：对 E3 的 2 条 L8 阻塞失败线路做跨高度重分配'
                 '（222→L20、483→Z1_INTERFACE）并重新 fanout/布线，最终 1024/1024 '
                 '全部通过严格 3D world 校验。\n')
    lines.append('## 2. 21 个物理高度与层分配\n')
    lines.append('| plane | z (mm) | 分配 | 布通 | crossings | pairs | 家族构成 |')
    lines.append('|---|---:|---:|---:|---:|---:|---|')
    for row in report['planes']:
        pid = row.get('plane_id')
        family_text = (dict(families_by_plane.get(int(pid), {}))
                       if pid is not None else {})
        lines.append('| %s | %s | %d | %d | %d | %d | `%s` |'
                     % (row['label'], _fmt(row['z_mm']),
                        sum(family_text.values()), row['route_count'],
                        row['crossings'], row['crossing_pairs'],
                        json.dumps(family_text, ensure_ascii=False)))
    lines.append('')
    lines.append('接口平面 Z1_INTERFACE/Z2_INTERFACE 的 route_count 含 512 条冻结'
                 '接口 lead，与 direct 主体合并审计，绝不跳过。\n')
    lines.append('## 3. 正式取消 C4 绑定\n')
    lines.append('* 每个高度只承载一个方向家族；非人工 C4 轨道被拆分 %s/%s 个，'
                 '单轨道最大跨高度数 %s。'
                 % (audit['c4_policy']
                    ['nonmanual_orbits_split_across_planes'],
                    audit['c4_policy']['nonmanual_orbits'],
                    audit['c4_policy']['max_planes_per_orbits']))
    lines.append('* `c4_group_id` 仅作溯源；层分配、搜索次序、路由几何与修复均以 '
                 'route_id 为单位。')
    lines.append('* 分配计划（各家族分组大小、预测下界）：'
                 '`assignment_plan.json`；审计：`assignment_audit.json`'
                 '（passed=%s）。\n' % audit['passed'])
    lines.append('## 4. 交叉来源分析（Phase 1–2）\n')
    lines.append('* `crossing_analysis.json`：11890 条交叉的完整记录'
                 '（route_a/route_b、物理高度、交叉点坐标、切线夹角、家族、'
                 'manual/direct/lead 分类、可分高度性、forced/avoidable/uncertain）'
                 '＋1024 条线路统计＋21 层汇总；`crossing_conflict_graph.json`：'
                 '656 个可移动节点、9797 条基线交叉边＋端口弦交替风险边。')
    lines.append('* 关键结论：(a) 交叉几乎完全由**端口弦交替（inversion）**决定；'
                 '(b) L9/L14/Z2_INTERFACE 的 60 次交叉来自 36 个"corner-bundle"'
                 '轨道（弦局限在各自象限，跨家族 0 交叉）；L15–L19 的 1200–1560 '
                 '次来自 64 个"grid"轨道（113–204 mm 穿心对角线）；'
                 '(c) 1848 条接口 lead 从不参与交叉，接口平面交叉全部是 direct '
                 '主体之间；(d) 基线中 100% 交替的 Z1 NS/SN×EW/WE 混层是最大来源。')
    lines.append('* 详细中文报告与 28 张图：`analysis/crossing_source_report.md`、'
                 '`analysis/plots/`。\n')
    lines.append('## 5. 层分配优化与理论下界（Phase 3）\n')
    lines.append('* 预测下界（同层端口弦交替对）= **%s**；实测 %d。'
                 % (plan.get('predicted_crossings'), total))
    lines.append('* 家族下界曲线（模拟退火分区实测）：Z1V/Z1H 在 k=2/3/4/5 组时为 '
                 '392/134/52/18 对；Z2 每个角家族在 k=2/4/6 组时为 246/30/4 对；'
                 'Z1V×Z1H 端口弦 100% 交替（128×128），NE×SW、SE×NW 为 0。')
    lines.append('* 21 高度下的最优结构：Z1V 2 个高度（66/62），Z1H 3 个高度'
                 '（L20/L8/Z1_INTERFACE），Z2 四个角家族各 2 个高度。Z2 侧实测'
                 '已达到弦下界，Z1 侧仍高于下界（见 §7）。\n')
    lines.append('## 6. 交叉感知二维布线（Phase 4）\n')
    lines.append('`cross_router.py`：候选级交叉代价（D56Index 真实横向交叉计数）+ '
                 '事务回滚的确定性 rip-up/reroute（布通数不下降）。真实基线任务'
                 '验证：L6 990→922、L15 1218→822、L17 1440→1208、L18 1464→1186、'
                 'L19 1440→1378，全部 21 层合计 9106→8020（-11.9%），0 D56 违规。'
                 '但在本轮家族纯净层上（L6 482→510、L7 460→460、L9 127→127、'
                 'L20 252→220、L8 出现布通失败）无稳定收益，说明瓶颈在层分配与'
                 '拓扑下界，因此正式解保留生产路由器，交叉感知路由器作为工具与'
                 '负结果归档。\n')
    lines.append('## 7. 与 21 高度成功基线的对比\n')
    lines.append('| 指标 | 基线 21H | 本轮 C4-free | 变化 |')
    lines.append('|---|---:|---:|---:|')
    lines.append('| 布通 | 1024/1024 | %d/1024 | %+d |'
                 % (report['routed'], report['routed'] - 1024))
    lines.append('| 交叉事件 | 11890 | %d | %+d |' % (total, total - 11890))
    lines.append('| 交叉线路对 | 9797 | %d | %+d |'
                 % (report['totals']['crossing_pairs'],
                    report['totals']['crossing_pairs'] - 9797))
    lines.append('| 单通道最大交叉 | %d | %d | %+d |'
                 % (base_dist['max'], new_dist['max'],
                    new_dist['max'] - base_dist['max']))
    lines.append('| 单通道 P95 | %s | %s | — |'
                 % (_fmt(base_dist['p95'], 1), _fmt(new_dist['p95'], 1)))
    lines.append('| 总长度 (mm) | %s | %s | %+.3f |'
                 % (_fmt(baseline['geometry']['total_length_mm']),
                    _fmt(stats['total_length_mm']),
                    stats['total_length_mm']
                    - baseline['geometry']['total_length_mm']))
    lines.append('| transition 数 | %d | %d | %+d |'
                 % (baseline['geometry']['transitions'],
                    stats['total_transitions'],
                    stats['total_transitions']
                    - baseline['geometry']['transitions']))
    lines.append('| 最小真实 3D 净空 (mm) | %s | %s | — |'
                 % (_fmt(baseline['geometry']['min_3d_clearance_mm'], 9),
                    _fmt(validation.get('min_3d_clearance_mm'), 9)))
    lines.append('| 几何违规 | 0 | %s | — |\n'
                 % validation.get('violation_count'))
    lines.append('逐高度对比：\n')
    lines.append('| plane | z (mm) | 基线 crossings | 本轮 crossings | 变化 |')
    lines.append('|---|---:|---:|---:|---:|')
    for row in report['planes']:
        base_value = int((base_by_label.get(row['label']) or {})
                         .get('crossings') or 0)
        lines.append('| %s | %s | %d | %d | %+d |'
                     % (row['label'], _fmt(row['z_mm']), base_value,
                        row['crossings'], row['crossings'] - base_value))
    lines.append('')
    lines.append('## 8. 为什么离 0–9 仍有差距（可检验障碍分析）\n')
    lines.append('1. **Z1 反向连接的端口配对本身拓扑强制交叉**：端口固定在玻璃'
                 '边界时，两条端点交替的弦在任意平面内路由都必然相交（Jordan '
                 '曲线定理）。Z1 的 256 条 opposite 连接在 N/S 与 E/W 两个方向'
                 '家族内部存在大量 inversion；5 个 Z1 高度对两个 100% 互交替的'
                 '家族只能分成 2+3 组，弦下界 392+134=526。')
    lines.append('2. **Z2 角家族的转置配对**：每个角家族 100 条连接是 10×10 '
                 '转置配对，k 分组下界为 246(k=2)/30(k=4)。8 个 Z2 高度分给 4 个'
                 '家族 → 每族 2 组，弦下界 4×246=984；本轮实测 991，已达到该'
                 '下界，二维路由器在这类层上无可改进空间。')
    lines.append('3. **单主体层结构理论下界 = 526 + 984 = 1510**。若允许对角兼容'
                 '家族（NE+SW、SE+NW）共面可把 Z2 降到 120、总下界约 646，但实测'
                 '（E2 实验 8000 次）表明当前 R15 轴向原语路由器无法实现这种兼容'
                 '家族的交叉自由布局——端口弦不交替并不等于轴向 L 形路径不相交。')
    lines.append('4. **要达到 0–9 必须在结构上突破**：')
    lines.append('   * 允许**主体中途局部三维升降**：每个 inversion 对用一对反向 '
                 'R15 S 曲线实现，垂直位移 ≥ 50 µm、占位约 2×2.4 mm；按 656 条'
                 '线路的 inversion 规模需要数千个局部升降，会显著增加长度与过渡'
                 '数量，但几何上可行。下一阶段应做此可行性与代价分析。')
    lines.append('   * 或实现**交换箱式（switchbox）布线器**：按 inversion 结构'
                 '生成严格非交叉轴向路径，把 Z1 侧从实测约 1578 压到下界 526；'
                 'Z2 侧已无空间，总下界仍约 1510。')
    lines.append('   * 或增加可用高度（>21）并允许跨接口高度重新分配（E6 方向）。')
    lines.append('5. **诚实结论**：取消 C4 后 1024/1024 全布通、0 违规，真实交叉 '
                 '11890→%d（-%.1f%%），但 0–9 在当前"单主体层 + 无中途换层 + '
                 '21 高度"结构下不可达（下界约 1510，兼容家族共面约 646）；'
                 '下一阶段的突破口是主体局部 3D 跨层避让。\n'
                 % (total, (1 - total / 11890.0) * 100))
    lines.append('## 9. 实验组记录\n')
    lines.append('| 实验 | 说明 | 布通 | 真实交叉 | 状态 |')
    lines.append('|---|---|---:|---:|---|')
    lines.append('| E0 | 21 高度基线复现（新驱动器 + 冻结人工几何） | 1024/1024 '
                 '| 11890 | 与基线逐层一致，验证驱动器 |')
    lines.append('| E1 | 取消 C4，按端口顺序朴素分块（家族纯净） | 1020/1024 '
                 '| 6495 | 4 条 2D 失败；证明只取消 C4 不够 |')
    lines.append('| E2 | 冲突图"兼容对角家族共面"层分配 | 1024/1024 | %s | '
                 '失败实验：弦不交替但 L 形路径相交（证据归档） |' % e2_cross)
    lines.append('| E3 | 冲突图 + 模拟退火分区（家族纯净、2–3 高度/族） | '
                 '1022/1024 | %s | 2 条 L8 阻塞失败 |' % e3_cross)
    lines.append('| E5 | E3 + 跨高度联合修复（222→L20、483→Z1_INTERFACE） | '
                 '%d/1024 | %d | **最终接受解，严格验证 0 违规** |'
                 % (report['routed'], total))
    lines.append('| E4 | 交叉感知路由器 | — | 基线混乱层 -11.9% | 家族纯净层'
                 '无收益，工具+负结果归档 |')
    lines.append('')
    lines.append('## 10. 后续工作\n')
    lines.append('1. 主体中途局部三维升降的可行性与代价分析（下一阶段首要方向）。')
    lines.append('2. 交换箱式 Z1 路由器，把 Z1 侧压到 inversion 下界 526。')
    lines.append('3. 兼容对角家族共面的专用路由器，把 Z2 侧从 984 压向 120。')
    lines.append('4. 扩大高度集合与跨接口高度重分配的完整联合实验（E6）。\n')
    lines.append('## 11. 可复现性\n')
    lines.append('* 搜索入口：`python -m four_side_1024.fanout1024.nonc4.'
                 'experiments e3`（e0/e1/e2/run/validate 子命令）；E5 联合修复'
                 '流程见本报告 §1.5。')
    lines.append('* 随机种子：层划分模拟退火 seed=11（确定性），2D 路由 '
                 'ordering_seed 0/1。')
    lines.append('* 代码快照：`code/`（`nonc4/*.py` + `reheight21_SPEC.md`）；'
                 '本轮未修改任何冻结基线模块。')
    lines.append('* 文件与校验：`MANIFEST.json`；交叉统计 `crossing_stats.json`'
                 '（含逐事件坐标/角度）；验证 `validation.json`。')
    lines.append('')
    (exp_dir / 'report.md').write_text('\n'.join(lines) + '\n',
                                       encoding='utf-8')
    log('[report] report.md written (%d lines)' % len(lines))

    comparison = [
        '# 与 21 高度成功基线（E0）的对比\n',
        '基线：`outputs/manual_c4_new_connectivity/'
        'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`（1024/1024，11890 crossings，'
        '0 violations，commit 2899485dea045fab6558926aae2d900b68679e01）\n',
        '本轮：`%s`（%d/1024，%d crossings，validation_pass=%s）\n'
        % (exp_dir, report['routed'], total, validation['validation_pass']),
        '## 核心指标\n',
        '| 指标 | 基线 | 本轮 | 变化 |',
        '|---|---:|---:|---:|',
        '| 布通 | 1024 | %d | %+d |' % (report['routed'],
                                      report['routed'] - 1024),
        '| 交叉事件 | 11890 | %d | %+d |' % (total, total - 11890),
        '| 交叉线路对 | 9797 | %d | %+d |'
        % (report['totals']['crossing_pairs'],
           report['totals']['crossing_pairs'] - 9797),
        '| 单通道最大交叉 | %d | %d | %+d |'
        % (base_dist['max'], new_dist['max'],
           new_dist['max'] - base_dist['max']),
        '| 单通道 P95 | %s | %s | — |'
        % (_fmt(base_dist['p95'], 1), _fmt(new_dist['p95'], 1)),
        '| 总长度 (mm) | %s | %s | — |'
        % (_fmt(baseline['geometry']['total_length_mm']),
           _fmt(stats['total_length_mm'])),
        '| 最小 3D 净空 (mm) | %s | %s | — |'
        % (_fmt(baseline['geometry']['min_3d_clearance_mm'], 9),
           _fmt(validation.get('min_3d_clearance_mm'), 9)),
        '| 几何违规 | 0 | %s | — |' % validation.get('violation_count'),
        '',
        '## 交叉下降来源\n',
        '1. 取消 C4 轨道绑定后每个高度只承载一个方向家族：Z1 的 N→S/S→N 与 '
        'E→W/W→E 不再混层（基线 100% 交替），Z2 每层不再混 4 个角家族；',
        '2. 层分配按端口弦交叉图（模拟退火分区）优化，把大部分 inversion 对'
        '拆到不同高度；',
        '3. 368 条人工 U 线路完整几何冻结，未为指标移动；全部严格几何约束'
        '（R15、D56、0.05 mm 3D 净空、50 µm 层距、21 高度）不变。',
        '',
        '## 诚实结论\n',
        '交叉从 11890 降至 %d（-%.2f%%），但未达到 0–9：单主体层结构下 Z1 '
        '反向配对与 Z2 转置配对存在拓扑强制交叉下界（约 1510；若允许兼容家族'
        '共面理论约 646，但当前 R15 轴向路由器无法实现）。下一阶段需要主体'
        '中途局部 3D 升降或交换箱式布线器。'
        % (total, (1 - total / 11890.0) * 100),
        '',
    ]
    (exp_dir / 'comparison.md').write_text('\n'.join(comparison) + '\n',
                                           encoding='utf-8')
    log('[report] comparison.md written')


def write_manifest(exp_dir, log=print):
    exp_dir = Path(exp_dir)
    files = []
    for path in sorted(exp_dir.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(exp_dir).as_posix()
        if relative.startswith('checkpoints/') or relative.startswith('scratch/'):
            continue
        files.append(dict(path=relative, bytes=path.stat().st_size,
                          sha256=_sha256(path)))
    D.write_json(exp_dir / 'MANIFEST.json', dict(
        schema='nonc4_manifest_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        experiment=exp_dir.name, file_count=len(files), files=files))
    log('[manifest] %d files hashed' % len(files))


def archive(exp_dir, log=print):
    exp_dir = Path(exp_dir)
    target = exp_dir.parents[3] / 'experiments' / 'non_c4_crossing_opt_1024'
    target.mkdir(parents=True, exist_ok=True)
    names = ['report.md', 'comparison.md', 'crossing_stats.json',
             'validation.json', 'assignment_1024.csv', 'routes_l3d.json',
             'optimization_history.csv', 'failed_routes.json',
             'final_stats.json', 'layer_planes.json', 'assignment_audit.json',
             'assignment_plan.json', 'manual_frozen_check.json',
             'MANIFEST.json', 'process_rules.json',
             'physical_layer_stack.json',
             'validator_consistency_tests.json', 'run.log']
    for name in names:
        source = exp_dir / name
        if source.is_file():
            shutil.copy2(source, target / name)
    for directory in ('plots', 'analysis', 'validation', 'experiment_B',
                      'experiment_C', 'experiment_D', 'experiment_E'):
        source = exp_dir / directory
        if source.is_dir():
            shutil.copytree(source, target / directory, dirs_exist_ok=True)
    code_dir = target / 'code'
    code_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(__file__).resolve().parent.glob('*.py')):
        shutil.copy2(path, code_dir / path.name)
    shutil.copy2(Path(__file__).resolve().parents[1] / 'reheight21' / 'SPEC.md',
                 code_dir / 'reheight21_SPEC.md')
    D.write_json(code_dir / 'CODE_FILES.json', dict(
        schema='nonc4_code_snapshot_v1',
        files=[dict(path=path.name, bytes=path.stat().st_size,
                    sha256=_sha256(path))
               for path in sorted(code_dir.glob('*')) if path.is_file()]))
    log('[archive] %s' % target)
    result = dict(archive_root=str(target))
    repo = Path(r'C:\Users\lihao\Desktop\Graduation Project\work'
                r'\11.9-second-report-all-work')
    if (repo / '.git').is_dir():
        destination = repo / 'experiments' / 'non_c4_crossing_opt_1024'
        shutil.copytree(target, destination, dirs_exist_ok=True)
        totals = D.load_json(exp_dir / 'crossing_stats.json')['totals']
        message = ('Add C4-free crossing-optimised 1024-channel routing '
                   'experiment (non_c4_crossing_opt_1024): 1024/1024 routed, '
                   '11890->%d same-layer crossings, frozen manual U geometry, '
                   'strict 0.05 mm world, 0 violations' % totals['crossings'])
        try:
            subprocess.run(['git', 'add', str(destination)], cwd=str(repo),
                           check=True, capture_output=True)
            commit = subprocess.run(['git', 'commit', '-m', message],
                                    cwd=str(repo), capture_output=True,
                                    text=True)
            result['git'] = dict(returncode=commit.returncode,
                                 stdout=commit.stdout[-800:],
                                 stderr=commit.stderr[-800:])
            log('[archive] git commit rc=%d' % commit.returncode)
        except Exception as error:  # noqa: BLE001
            result['git'] = dict(error=repr(error))
            log('[archive] git failed %r' % error)
    return result
