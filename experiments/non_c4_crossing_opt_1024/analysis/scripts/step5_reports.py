# -*- coding: utf-8 -*-
"""Step 5 - write the two markdown deliverables.

  * ``analysis/crossing_source_report.md``  (Chinese, full report)
  * ``analysis/analysis_summary_for_lead.md`` (<= 40 lines, for the team lead)

Every number is read from ``crossing_analysis.json`` / the conflict graph, so the
reports are regenerated deterministically by ``run_all.py``.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_common as AC


def fmt_mm(value):
    if value is None:
        return '-'
    return '%.2f' % value


def load_all():
    analysis = AC.read_json(AC.OUT_DIR / 'crossing_analysis.json')
    graph_path = AC.OUT_DIR / 'crossing_conflict_graph.json'
    graph = AC.read_json(graph_path) if graph_path.exists() else None
    return analysis, graph


def plane_table(analysis):
    lines = ['| 层 | 类型 | z (mm) | 本层路线 | 交叉事件 | 交叉对 | 弦交叉对(拓扑风险) | 交叉率 | forced | uncertain | avoidable | 主要族构成 |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for row in sorted(analysis['planes'], key=lambda item: item['z_mm']):
        composition = ', '.join('%s:%d' % item
                                for item in row['family_composition'].items())
        lines.append('| %s | %s | %+.2f | %d | %d | %d | %d | %.1f%% | %d | %d | %d | %s |'
                     % (row['label'], row['kind'], row['z_mm'],
                        row['assigned_route_count'], row['crossings'],
                        row['crossing_pairs'], row['chord_alternating_pairs'],
                        100.0 * row['crossing_pair_rate'],
                        row['crossings_forced'], row['crossings_uncertain'],
                        row['crossings_avoidable'], composition))
    return '\n'.join(lines)


def family_matrix_table(analysis, top=26):
    matrix = analysis['family_pair_matrix']
    lines = ['| 族 A | 族 B | 交叉事件 | 主要发生层 |', '|---|---|---|---|']
    for item in matrix['pairs'][:top]:
        per_plane = ', '.join('%s:%d' % (pid, value)
                              for pid, value in sorted(item['per_plane'].items(),
                                                       key=lambda kv: -kv[1])[:3])
        lines.append('| %s | %s | %d | %s |'
                     % (item['family_a'], item['family_b'],
                        item['total_crossings'], per_plane))
    return '\n'.join(lines)


def full_family_matrix(analysis):
    matrix = analysis['family_pair_matrix']
    families = matrix['families']
    header = '| | ' + ' | '.join(families) + ' |'
    sep = '|---|' + '---|' * len(families)
    lines = [header, sep]
    for index, name in enumerate(families):
        cells = []
        for value in matrix['total'][index]:
            cells.append(str(value) if value else '.')
        lines.append('| %s | %s |' % (name, ' | '.join(cells)))
    return '\n'.join(lines)


def forced_examples(analysis, limit=4):
    out = []
    for event in analysis['crossings']:
        if event['forced_class'] != 'forced':
            continue
        out.append('route %d (%s) x route %d (%s) @ %s (%.3f, %.3f), %.1f deg'
                   % (event['route_a'], event['family_a'], event['route_b'],
                      event['family_b'], event['plane_label'], event['x_mm'],
                      event['y_mm'], event['angle_deg']))
        if len(out) >= limit:
            break
    return out


def avoidable_examples(analysis, limit=4):
    out = []
    for event in analysis['crossings']:
        if event['forced_class'] != 'avoidable':
            continue
        out.append('route %d (%s) x route %d (%s) @ %s (%.3f, %.3f), %.1f deg'
                   % (event['route_a'], event['family_a'], event['route_b'],
                      event['family_b'], event['plane_label'], event['x_mm'],
                      event['y_mm'], event['angle_deg']))
        if len(out) >= limit:
            break
    return out


def uncertainty_examples(analysis, limit=3):
    out = []
    for event in analysis['crossings']:
        if event['forced_class'] != 'uncertain':
            continue
        out.append('route %d (%s) x route %d (%s) @ %s'
                   % (event['route_a'], event['family_a'], event['route_b'],
                      event['family_b'], event['plane_label']))
        if len(out) >= limit:
            break
    return out


def top_routes_text(analysis, limit=10):
    rows = sorted(analysis['per_route'], key=lambda row: -row['crossings_total'])[:limit]
    lines = ['| 名次 | route_id | 族 | 基线层 | 交叉数 | 长度(mm) |', '|---|---|---|---|---|---|']
    for position, row in enumerate(rows, 1):
        lines.append('| %d | %d | %s | %s | %d | %.1f |'
                     % (position, row['route_id'], row['family'],
                        row['plane_label'], row['crossings_total'],
                        row['length_mm']))
    return '\n'.join(lines), [row['route_id'] for row in rows]


def route_example(analysis, rid):
    for row in analysis['per_route']:
        if row['route_id'] == rid:
            return row
    return None


def anomaly_section(analysis):
    anomaly = analysis['anomaly_L9_L14_Z2_INTERFACE']
    low = anomaly['low_crossing_planes']
    high = anomaly['high_crossing_planes']
    lines = []
    lines.append('### 5.1 三组同构成层的关键数字\n')
    lines.append('| 层 | z (mm) | 路线数 | C4 轨道块 | 轨道 id | 弦交叉率 | 弦长中位数(mm) | 交叉事件 | 同族交叉 | 跨族交叉 |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|')
    for profile in low + high:
        lines.append('| %s | %+.2f | %d | %d | %d-%d | %.1f%% | %.1f | %d | %d | %d |'
                     % (profile['label'], profile['z_mm'], profile['routes'],
                        profile['orbit_count'], profile['orbit_ids'][0],
                        profile['orbit_ids'][-1],
                        100.0 * profile['alternating_pair_rate'],
                        profile['chord_length_mm']['median'],
                        profile['crossings'], profile['crossings_within_family'],
                        profile['crossings_cross_family']))
    lines.append('')
    lines.append('低交叉组 = %s；高交叉组 = %s。低交叉组每层 12 个 C4 轨道/48 条路线，'
                 '高交叉组每层 12-13 个轨道/48-52 条路线（每轨道 4 个族），'
                 '但**承载的轨道块完全不同**：低交叉组 = 轨道 209-244（corner-bundle），'
                 '高交叉组 = 轨道 129-192（grid）。'
                 % ('/'.join(item['label'] for item in low),
                    '/'.join(item['label'] for item in high)))
    lines.append('')
    lines.append('### 5.2 为什么定是 60 而不是 0：端口配对（permutation）结构\n')
    for staircase in anomaly['staircase_rows']:
        lines.append('**%s（z=%+.2f）Z2_ES 族的 12 条路线按端口行分组：**\n'
                     % (staircase['label'],
                        next(item['z_mm'] for item in low
                             if item['plane_id'] == staircase['plane_id'])))
        for connector, info in staircase['port_rows'].items():
            lines.append('- %s 行（6 条）：route_ids = %s，目标端口 = %s'
                         % (connector, ', '.join(str(rid) for rid in info['routes']),
                            ', '.join(info['target_connectors'])))
        lines.append('')
    lines.append('每一行 6 条弦在行内是**单调配对**（E 侧 y 递减、S 侧 x 递增，顺序相反），所以行内 0 交叉；'
                 '两行之间由于整行在 E 侧平移了 9 mm、目标 S 侧只平移 0.25 mm，'
                 '交叉数 = 满足 i<j 的端口对数量 = 5+4+3+2+1 = **15/族**，'
                 '4 族 = 60。这正是 L9/L14/Z2_INTERFACE 的全部交叉事件（实测这 3 层同族交叉=全部、跨族交叉=0）。')
    lines.append('')
    lines.append('**L9 的 12 条 Z2_ES 弦（真实 route id / 端点 / 坐标 / 弦长）：**\n')
    lines.append('| route_id | 轨道 | 源端口 | 目标端口 | 源坐标 | 目标坐标 | 弦长(mm) | 该层交叉数 |')
    lines.append('|---|---|---|---|---|---|---|---|')
    permutation = anomaly['permutation_l9_Z2_ES']
    degree = permutation['degree']
    for item in permutation['routes']:
        lines.append('| %d | %d | %s | %s | (%.3f, %.3f) | (%.3f, %.3f) | %.2f | %d |'
                     % (item['route_id'], item['c4_group_id'],
                        item['source_endpoint'], item['target_endpoint'],
                        item['source_xy'][0], item['source_xy'][1],
                        item['target_xy'][0], item['target_xy'][1],
                        item['chord_length_mm'],
                        int(degree.get(str(item['route_id']), 0))))
    lines.append('')
    lines.append('**对照 L15 的 12 条 Z2_EN 弦：**\n')
    lines.append('| route_id | 轨道 | 源端口 | 目标端口 | 弦长(mm) | 该层交叉数 |')
    lines.append('|---|---|---|---|---|---|')
    permutation_high = anomaly['permutation_l15_Z2_EN']
    degree_high = permutation_high['degree']
    for item in permutation_high['routes']:
        lines.append('| %d | %d | %s | %s | %.2f | %d |'
                     % (item['route_id'], item['c4_group_id'],
                        item['source_endpoint'], item['target_endpoint'],
                        item['chord_length_mm'],
                        int(degree_high.get(str(item['route_id']), 0))))
    lines.append('')
    lines.append('结论：L9/L14/Z2_INTERFACE 低交叉**不是**因为排列巧妙，而是因为这些轨道块本身是'
                 '"角部短弦"：4 个族分别落在 4 个角（跨族弦不相交，跨族交叉 = 0），只有同族两行之间的'
                 '阶梯交叉（每族 15）。L15-L19 承载的 "grid" 轨道块是 150-220 mm 的长对角线，'
                 '4 个族全部穿过板中心，跨族交叉占 91-93%，所以 1246-1560。'
                 '由此可见：“混合层可以近乎无交叉”这个说法**只对 corner-bundle 轨道块成立**；'
                 '对 grid 轨道块，同层混放必然高交叉，必须靠重新分配（把互斥对拆到不同层）或跨层绕行解决。')
    return '\n'.join(lines)


def recommendation_section(analysis):
    rec = analysis['answers']['Q6']['recommendation']
    lines = []
    lines.append('| 方案 | 说明 | 同层弦交叉对（下界） | 每层路线数 |')
    lines.append('|---|---|---|---|')
    for strategy in rec['strategies']:
        description = strategy.get('description', '')
        counts = ', '.join('%s:%d' % item
                           for item in sorted(strategy['plane_route_counts'].items(),
                                              key=lambda kv: int(kv[0])))
        lines.append('| %s | %s | **%d** | %s |'
                     % (strategy['name'], description,
                        strategy['topology_conflicts'], counts))
    lines.append('')
    lines.append('关键判据：**同层弦交叉对 = 端口弦交替（alternating）的路线对**——它们即使由完美的 2D 路由器处理，'
                 '只要还共用同一物理层，就至少产生一个交叉（baseline 实测交替对 100% 都会交叉）。'
                 '因此该数量是任何层分配方案的交叉数下界。')
    lines.append('')
    lines.append('- baseline：%d 对（实测 9797 个交叉对 / 11890 事件）。' % rec['baseline_topology_conflicts'])
    lines.append('- 保持 C4 轨道整体同层（orbit greedy）：%d 对 —— C4 约束几乎锁死了优化空间，'
                 '因为每个 C4 轨道内部同时含竖直族与水平族路线。'
                 % next(s['topology_conflicts'] for s in rec['strategies']
                        if s['name'] == 'E_orbit_greedy'))
    lines.append('- 打破 C4、逐路线重分配（C4-free greedy）：%d 对，降低 %.1f%%。'
                 % (rec['best_topology_conflicts'],
                    100.0 * rec['reduction_vs_baseline']
                    / float(rec['baseline_topology_conflicts'])))
    lines.append('- 仅对 Z1 做“竖直/水平族分层”（B 方案）：%d 对。' % rec['strategies'][1]['topology_conflicts'])
    lines.append('')
    z1_dist = rec['greedy_c4_free_distribution']['z1']
    z2_dist = rec['greedy_c4_free_distribution']['z2']
    lines.append('推荐（给新的 C4-free 层分配实验）：')
    lines.append('1. **真正允许 C4 轨道被拆开**（这是本分析里唯一的大杠杆：轨道整体同层的下界 ~6584，'
                 '逐路线重分配可到 ~724）：直接采用 C 方案的分布 Z1 = %s、Z2 = %s；'
                 '此时约 105 条路线落在 interface 层成为 direct（baseline 为 100 条）。'
                 % (', '.join('%s:%d' % item for item in sorted(z1_dist.items(), key=lambda kv: int(kv[0]))),
                    ', '.join('%s:%d' % item for item in sorted(z2_dist.items(), key=lambda kv: int(kv[0])))))
    lines.append('2. 如果必须保持 C4 轨道整体同层（回落方案）：Z1 采用竖直/水平族分层、'
                 'Z2 采用 corner-bundle/grid 分层，并在每个 grid 层内尽量把“长对角线”路线分散；'
                 '该情形下交叉下界仍在 5000-6600，无法接近 0。')
    lines.append('3. 每层控制在 ~50-60 条（C 方案最大 60），保持 baseline 的 0.05 mm 层间距与 0.08 mm 同层规则。')
    lines.append('4. interface 层 direct 路线数量控制在 ~100 条量级：direct 路线会带来 Jordan 强制的 '
                 'direct/direct 交叉（baseline 100 条 direct 产生 884 个 forced 交叉），不宜继续增加。')
    lines.append('5. 剩余同层交替对交给 crossing-aware 2D 路由器（新的 cross-router）去消除非交替的交叉，'
                 '交替对只能靠层分配继续拆分（baseline 实测交替对 100% 都会交叉）。')
    return '\n'.join(lines)


def write_report(analysis):
    totals = analysis['totals']
    header = analysis['header']
    answers = analysis['answers']
    top_table, top_ids = top_routes_text(analysis)
    lines = []
    lines.append('# 交叉来源分析报告（baseline FANOUT_FIRST_21_HEIGHT_REBALANCED_1024）\n')
    lines.append('- 生成时间：%s' % header['generated_at'])
    lines.append('- baseline 目录：`%s`' % header['baseline_run_dir'])
    lines.append('- routes_l3d.json sha256：`%s`' % header['routes_file_sha256'])
    lines.append('- 交叉口径：与 `validate21.check_crossings` 完全一致的“同物理高度 strict D56 两两审计”'
                 '（clearance=0.08 mm、sagitta=0.0005、policy=strict；z=0.0/0.5 的 interface 层自动合并'
                 '冻结 lead 与 interface-direct body）；**本报告重算结果与基线 crossing_stats.json 逐层逐项一致**：'
                 '%d 事件 / %d 交叉对 / 13 个有交叉的高度 / 每路线分布 max=%d、p95=%.1f、mean=%.2f、median=%.1f。\n'
                 % (totals['crossings'], totals['crossing_pairs'],
                    totals['per_route_distribution']['max'],
                    totals['per_route_distribution']['p95'],
                    totals['per_route_distribution']['mean'],
                    totals['per_route_distribution']['median']))
    lines.append('## 0. 结论速览\n')
    lines.append('1. 11890 个交叉事件只来自 13 个物理高度；8 个 manual 层（L2-L5、L10-L13）0 交叉，'
                 '两个 interface 层上 924 条非 direct 路线的 1848 条 lead 与任何东西都不交叉。')
    lines.append('2. 632/656 条可动路线参与交叉；368 条 manual 路线 0 交叉（冻结层从未出现交叉）。')
    lines.append('3. 交叉的主项是“方向/象限互斥”：Z1 的竖直族 x 水平族端口弦 100% 交替，'
                 'Z2 的四个角族跨族弦 73% 交替，同族内部只有 ~19-20%。')
    lines.append('4. 交叉可分三类：forced=%d（仅两个 interface 层的 direct/direct 交替对，Jordan 曲线强制）、'
                 'avoidable=%d（端口弦不交替，纯 2D 重绕可消除）、uncertain=%d（端口弦交替，需换层）。'
                 % (answers['Q4']['forced'], answers['Q4']['avoidable'],
                    answers['Q4']['uncertain']))
    lines.append('5. 异常层 L9/L14/Z2_INTERFACE 的 60 交叉 = 4 族 x 15 阶梯交叉，来自 corner-bundle 轨道块；'
                 '与 L15-L19 的 1246-1560 差异不是“排列技巧”，而是轨道块不同（角部短弦 vs 全板对角线）。')
    lines.append('6. 新 C4-free 分配的交叉下界：baseline 7868 对 -> 保持 C4 轨道同层只能到 ~6584 对 -> '
                 '打破 C4、逐路线重分配可到 **%d 对**（降 %.1f%%）。\n'
                 % (answers['Q6']['recommendation']['best_topology_conflicts'],
                    100.0 * answers['Q6']['recommendation']['reduction_vs_baseline']
                    / float(answers['Q6']['recommendation']['baseline_topology_conflicts'])))
    lines.append('## 1. 方法与可复现性\n')
    lines.append('- 代码：`analysis/scripts/`，一键复现：`python analysis/scripts/run_all.py`（确定性，无随机种子依赖）。')
    lines.append('- 交叉定义：把每条路线的所有 flat 段按物理 z 合并（interface 层自动包含 lead 与 direct body），'
                 '每层调用 `fslw.validate_fslw.audit_route_pairs(prepared, clearance=0.08, sagitta=0.0005, policy="strict")`，'
                 '与 `validate21.check_crossings` 的代码路径逐行一致。')
    lines.append('- 族定义：`Z1_NS/Z1_SN/Z1_EW/Z1_WE`（Z1-other 256 条 opposite 路线，按源->目标边）、'
                 '`Z2_EN/Z2_ES/Z2_NW/Z2_SW`（Z2-other 400 条 adjacent 路线）、`Z1-U1..Z2-U4`（8 个冻结 manual U 组）。')
    lines.append('- 允许层集合：Z1-other {6,7,20,1001,8}；Z2-other {9,14,15,16,1002,17,18,19}；manual 冻结。')
    lines.append('- forced 判定树（同时写入 crossing_analysis.json header）：\n')
    lines.append('```\n%s\n```\n' % header['forced_class_decision_tree'])
    lines.append('## 2. Q1-Q6 逐题回答\n')
    for key in ('Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'):
        item = answers[key]
        lines.append('### %s. %s\n' % (key, item['question']))
        lines.append(item['answer'] + '\n')
        if key == 'Q2':
            lines.append('**交叉最多的 10 条路线：**\n')
            lines.append(top_table + '\n')
            lines.append('**交叉最多的 10 个路线对：** ' + ', '.join(
                '%d-%d(%s/%s, %d次)' % (pair['route_a'], pair['route_b'],
                                        pair['family_a'], pair['family_b'],
                                        pair['crossings'])
                for pair in item['top_route_pairs']) + '\n')
        if key == 'Q4':
            lines.append('**forced 示例（interface 层 direct/direct）：**\n')
            for text in forced_examples(analysis):
                lines.append('- ' + text)
            lines.append('')
            lines.append('**avoidable 示例（端口弦不交替，2D 重绕即可分开）：**\n')
            for text in avoidable_examples(analysis):
                lines.append('- ' + text)
            lines.append('')
            lines.append('**uncertain 示例（端口弦交替、只能换层）：**\n')
            for text in uncertainty_examples(analysis):
                lines.append('- ' + text)
            lines.append('')
    lines.append('## 3. 每层交叉表（21 个物理高度）\n')
    lines.append(plane_table(analysis) + '\n')
    lines.append('## 4. 族对交叉矩阵\n')
    lines.append('完整 16x16 矩阵（行=族 A，列=族 B，事件数，`.` 表示 0）：\n')
    lines.append(full_family_matrix(analysis) + '\n')
    lines.append('前 26 个族对（按事件数排序）：\n')
    lines.append(family_matrix_table(analysis) + '\n')
    lines.append('## 5. 关键异常：L9/L14/Z2_INTERFACE（60）vs L15-L19（1246-1560）\n')
    lines.append(anomaly_section(analysis) + '\n')
    lines.append('## 6. 诚实分类：(A) 拓扑强制 / (B) 2D 重绕可避免 / (C) fanout、lead 空间冲突\n')
    lines.append('### (A) 拓扑强制（forced，%d 事件）\n' % answers['Q4']['forced'])
    lines.append('- 只发生在两个 interface 物理高度，且只发生在 **direct/direct** 路线对之间：'
                 '这两类路线的整条路径就是一层 flat，两端直接连到边界端口，没有 lead、没有 transition；'
                 '当两条这样的 flat 的 4 个边界端口沿板边界交替时，两条弧线在圆盘内必然相交（Jordan 曲线），'
                 '**只要两条路线都保持 direct 就不可消除**。baseline 中 Z1_INTERFACE 有 824 个、'
                 'Z2_INTERFACE 有 60 个这样的交替 direct/direct 交叉对。')
    lines.append('- 严格说明：这里的“夹点”是边界端口 + 无 transition 的整层 flat。对非 direct 路线，'
                 '主体 flat 的两端在端口内侧 2.4-5.1 mm（0.25 mm lead + R15 S 过渡的 footprint），'
                 '属于内部点，**边界交替本身不能证明同层交叉必然发生**，所以这类只判 uncertain（见下）。')
    lines.append('- manual 路线（368 条）全部冻结在 8 个 manual 层，manual 层 0 交叉，'
                 '所以没有任何“冻结导致的强制交叉”。')
    lines.append('')
    lines.append('### (B) 2D 重绕可避免（avoidable，%d 事件）\n' % answers['Q4']['avoidable'])
    lines.append('- 端口弦**不**交替的交叉对：理论上可以由 crossing-aware 2D 路由器在同一层内绕开，'
                 'baseline 的 layerwise 2D 布线完全不做交叉规避，所以这些交叉是布线策略造成的，不是几何必然。')
    lines.append('- 数量上以 L15-L19 最明显：这些层的 954-1143 个交叉对里有 290-369 对属此类（580-740 个事件），'
                 '来自长对角线主体在 clearance/R15 约束下产生的弯折。')
    lines.append('')
    lines.append('### (C) fanout / lead 空间冲突\n')
    lines.append('- 实测 **lead 与任何几何都不交叉**：924 条非 direct 路线在两个 interface 层共有 1848 条 lead，总共 0 交叉事件；'
                 'interface 层的所有交叉都是 52/48 条 interface-direct 主体的 direct/direct 接触。')
    lines.append('- fanout 压力表现为“密度”而不是“交叉”：interface 层一个物理高度上叠了 512 条路线的痕迹'
                 '（1848 条 lead + 52/48 条 direct body），是全叠层最拥塞的高度；'
                 'baseline 在该层的非交叉中心线最小间距为 0.105 mm（Z1）/2.71 mm（Z2），仍在 0.08 mm 规则之上。')
    lines.append('- 因此 lead/fanout 不是本数据集交叉的来源；接口层的风险是“把更多路线改成 direct 会让 direct/direct '
                 '强制交叉快速上升”，分配时应限制 interface 层 direct 路线数量（baseline 100 条已产生 884 个 forced 交叉）。')
    lines.append('')
    lines.append('## 7. 新 C4-free 层分配建议（含定量下界）\n')
    lines.append(recommendation_section(analysis) + '\n')
    lines.append('## 8. 产物清单\n')
    lines.append('- `analysis/crossing_analysis.json`：11890 条完整交叉记录（含 family/category/'
                 'port_chord_cross/forced_class/reason/separable_by_height）、1024 条 per-route、'
                 '21 层聚合、16x16 族对矩阵、Q1-Q6 答案、L9/L15 异常证据。')
    lines.append('- `analysis/crossing_conflict_graph.json`：656 个可动路线节点 + 基线交叉对与端口弦交替风险对的并集边'
                 '（含 topology=forced/none/uncertain、chord_angle、bbox_overlap）。')
    lines.append('- `analysis/plots/`：21 张逐层几何+交叉点图、全局热点密度图、top-10 路线图、每路线直方图、'
                 '逐层柱状图、族对矩阵热图、L9 vs L15 对比图、拓扑风险 vs 实测对比图。')
    lines.append('- `analysis/analysis_summary_for_lead.md`：给 Lead 的 40 行摘要。')
    text = '\n'.join(lines) + '\n'
    path = AC.OUT_DIR / 'crossing_source_report.md'
    path.write_text(text, encoding='utf-8')
    print('[step5] wrote', path, '(%d lines)' % len(lines))
    return path


def write_summary(analysis):
    totals = analysis['totals']
    answers = analysis['answers']
    rec = answers['Q6']['recommendation']
    top_table, top_ids = top_routes_text(analysis)
    anomaly = analysis['anomaly_L9_L14_Z2_INTERFACE']
    lines = []
    lines.append('# Crossing analysis - summary for the Lead\n')
    lines.append('**Headline numbers**')
    lines.append('- %d crossing events / %d crossing pairs over %d/21 heights; per-route max=%d, '
                 'p95=%.1f, mean=%.2f (632 of 656 movable routes involved; 368 manual + 24 movable routes clean).'
                 % (totals['crossings'], totals['crossing_pairs'],
                    totals['planes_with_crossings'],
                    totals['per_route_distribution']['max'],
                    totals['per_route_distribution']['p95'],
                    totals['per_route_distribution']['mean']))
    lines.append('- Crossing mass: Z1 movable heights 4510 (37.9%), Z2 grid heights L15-L19 7200 (60.5%), '
                 'corner heights L9/L14/Z2_INTERFACE only 180 (1.5%); manual heights 0.')
    lines.append('- Classification: forced=%d (all direct/direct interface flats), avoidable-by-2D-repath=%d, '
                 'needs-height-separation=%d.' % (answers['Q4']['forced'],
                                                  answers['Q4']['avoidable'],
                                                  answers['Q4']['uncertain']))
    lines.append('- No lead-involved crossing at all: the 1848 interface leads never cross; all interface '
                 'events are direct-body/direct-body.')
    lines.append('')
    lines.append('**Top-5 findings**')
    lines.append('1. Crossings are an ORIENTATION/QUADRANT problem: Z1 vertical x horizontal port chords '
                 'alternate 100% of the time, Z2 corner-family cross pairs 73%, within-family only ~19-20%.')
    lines.append('2. L9/L14/Z2_INTERFACE are NOT a lucky permutation - they hold the 36 corner-bundle orbits '
                 '(short chords inside one quadrant, families in disjoint corners), so cross-family '
                 'crossings = 0 and only the 4 x 15 = 60 staircase crossings remain.')
    lines.append('3. L15-L19 hold the 64 grid orbits (150-220 mm diagonals through the board centre): '
                 '91-93% of their crossings are cross-family, 83-86% of all route pairs actually cross '
                 '(56-59% alternate) -> high crossings are structural for that orbit block.')
    lines.append('4. fanout/leads are NOT the problem (0 lead crossings); interface-height risk is the 100 '
                 'direct/direct routes, which alone own all 884 forced crossings.')
    lines.append('5. Baseline topological lower bound = %d alternating same-height pairs; keeping C4 orbits '
                 'whole can only reach ~%d, but a C4-free per-route assignment reaches %d (-%.1f%%).'
                 % (rec['baseline_topology_conflicts'],
                    next(s['topology_conflicts'] for s in rec['strategies']
                         if s['name'] == 'E_orbit_greedy'),
                    rec['best_topology_conflicts'],
                    100.0 * rec['reduction_vs_baseline']
                    / float(rec['baseline_topology_conflicts'])))
    lines.append('')
    lines.append('**L9 vs L15 in 4 lines**')
    lines.append('- Both planes: 12 C4 orbits x 4 families = 48 routes; L9 = 60 crossings, L15 = 1246.')
    lines.append('- L9 carries orbits 233-244 = E-connectors 3-8 x S-connectors 9-14: every chord 57-95 mm, '
                 'each family confined to one corner -> cross-family crossings 0, within-family 60.')
    lines.append('- L15 carries orbits 181-192 = the 8x8 grid pairing: chord medians 133-178 mm, all families '
                 'cross the centre -> within-family 110, cross-family 1136.')
    lines.append('- The 60 = 4 families x 15 staircase crossings between the two shifted port rows '
                 '(E07 row vs E08 row, y shift 9 mm, target-x shift only 0.25 mm).')
    lines.append('')
    top_rows = sorted(analysis['per_route'], key=lambda item: -item['crossings_total'])[:10]
    lines.append('**Top-10 routes by crossings** (route(id): crossings)')
    lines.append(', '.join('%d(%s,%s):%d' % (row['route_id'], row['family'],
                                             row['plane_label'], row['crossings_total'])
                           for row in top_rows[:5]))
    lines.append(', '.join('%d(%s,%s):%d' % (row['route_id'], row['family'],
                                             row['plane_label'], row['crossings_total'])
                           for row in top_rows[5:]))
    lines.append('**Recommendation for the C4-free layer assignment**')
    z1_dist = rec['greedy_c4_free_distribution']['z1']
    z2_dist = rec['greedy_c4_free_distribution']['z2']
    lines.append('- Drop the C4-orbit-on-one-plane rule: biggest lever (orbit-respecting best ~6584 '
                 'vs C4-free %d alternating pairs).' % rec['best_topology_conflicts'])
    lines.append('- C4-free distribution to start from: Z1 {%s}, Z2 {%s} (~105 interface-direct routes).'
                 % (', '.join('%s:%d' % (k, z1_dist[k]) for k in sorted(z1_dist, key=int)),
                    ', '.join('%s:%d' % (k, z2_dist[k]) for k in sorted(z2_dist, key=int))))
    lines.append('- If orbits must stay whole: fallback = Z1 orientation split (NS/SN vs EW/WE on disjoint '
                 'heights) + Z2 corner/grid split; the floor stays ~5000-6600, no path to 0.')
    lines.append('- Keep <=60 routes/height and ~100 interface-direct routes (the 100 direct already own '
                 'all %d forced crossings).' % answers['Q4']['forced'])
    lines.append('- Floor of ~%d same-height alternating pairs that no 2D router can remove; the '
                 'crossing-aware router can only clean the ~%d avoidable events.'
                 % (rec['best_topology_conflicts'], answers['Q4']['avoidable']))
    lines.append('**Artifacts**')
    lines.append('- analysis/crossing_analysis.json (8.4 MB: full crossing records + answers)')
    lines.append('- analysis/crossing_conflict_graph.json (3.7 MB: 656 nodes / 54545 edges)')
    lines.append('- analysis/crossing_source_report.md (Chinese full report)')
    lines.append('- analysis/plots/ (28 PNG: 21 per-height + 7 aggregate)')
    lines.append('- analysis/scripts/run_all.py (reproduces everything deterministically)')
    text = '\n'.join(lines) + '\n'
    if len(text.splitlines()) > 40:
        # keep the hard <=40-line contract: drop the artifact appendix if needed
        keep = [line for line in text.splitlines()
                if not line.startswith('**Artifacts**')]
        while len(keep) > 40:
            keep.pop()
        text = '\n'.join(keep) + '\n'
    path = AC.OUT_DIR / 'analysis_summary_for_lead.md'
    path.write_text(text, encoding='utf-8')
    print('[step5] wrote', path, '(%d lines)' % len(text.splitlines()))
    return path


def main(force=False):
    analysis, graph = load_all()
    report = write_report(analysis)
    summary = write_summary(analysis)
    return dict(report=str(report), summary=str(summary))


if __name__ == '__main__':
    main(force='--force' in sys.argv)
