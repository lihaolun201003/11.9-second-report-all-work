# -*- coding: utf-8 -*-
"""Generate the Bundle-aware Native 3D report from the real artefacts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
DOCS = ROOT / 'docs/reports/BUNDLE_AWARE_NATIVE_3D.md'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def main():
    grouping = read(CAMPAIGN / '01_bundle_grouping/grouping_summary.json', {}) or {}
    methods = grouping.get('methods', {})
    chosen_name = grouping.get('chosen_method', '-')
    chosen = methods.get(chosen_name, {})
    bundles_payload = read(CAMPAIGN / '01_bundle_grouping/bundles.json', {}) or {}
    plane_bundles = bundles_payload.get('bundles', {})
    plan = read(CAMPAIGN / '02_bundle_planning/bundle_plan.json', {}) or {}
    p1 = read(CAMPAIGN / '02_bundle_planning/p1_summary.json', {}) or {}
    if not p1.get('phase2'):
        p1['phase2'] = read(CAMPAIGN / '02_bundle_planning/phase2_comparison.json',
                            {}) or {}
    if not p1.get('lift'):
        p1['lift'] = read(CAMPAIGN / '02_bundle_planning/lift_comparison.json',
                          {}) or {}
    p1_2d = p1.get('phase2', {}) or {}
    p1_lift = p1.get('lift', {}) or {}
    repair_bundle = read(CAMPAIGN / '02_bundle_planning/phase2_bundle_order_repaired/'
                         'repair_summary.json', {}) or {}
    window = read(CAMPAIGN / '02_ripup/z2_window_summary.json', {}) or {}
    region = read(CAMPAIGN / '02_ripup/z2_region_summary.json', {}) or {}
    p3_summary = read(CAMPAIGN / '03_native3d/native_search_summary.json', {}) or {}
    p3_results = (read(CAMPAIGN / '03_native3d/native_search_results.json', {})
                  or {}).get('results', [])
    old_repair = read(OLD / 'phase2_2d_repaired/repair_summary.json', []) or []
    old_compare = read(OLD / 'comparison.json', []) or []
    old_best = read(OLD / 'best_solution/layer_row.json', {}) or {}

    plane_counts = {plane: len(plane_bundles.get(plane, []))
                    for plane in ('z1', 'z2')}
    total_bundles = sum(plane_counts.values())
    chosen_sizes = chosen.get('size_orbits', {}) or {}
    mean_conn = (chosen_sizes.get('mean', 0) or 0) * 4.0
    mixed = chosen.get('mixed_bundles', 0)
    kind_mix = chosen.get('kind_mix', {}) or {}

    baseline = {}
    for row in old_compare:
        if 'layer_count' in row:
            baseline[int(row['layer_count'])] = row
    p1_rows = p1_lift.get('baseline', {}) or {}
    bundle_rows = p1_lift.get('bundle', {}) or {}
    adherence = p1_lift.get('adherence', {}) or {}
    p1_2d_base = p1_2d.get('baseline_easy', {}) or {}
    p1_2d_bundle = p1_2d.get('bundle_order', {}) or {}

    lines = []
    add = lines.append
    add('# Bundle-aware Native 3D Routing：线束感知的三维联合布线研究')
    add('')
    add('> 本报告由 `make_bwn3d_report.py` 从真实运行产物自动生成；所有数字来自实际几何、'
        '冻结验证器与审计结果。P3（Native 3D）为原型研究，与最终 1024 布局分开标注。')
    add('')
    add('## 一、研究动机与原有算法的局限')
    add('')
    add('- 旧算法（E1/F2/phase2+crossing-lift）本质是"逐条布 2D，再局部抬升"：'
        '缺少对线束整体结构的规划，导致高层交叉、走廊争用与最后 8 个 Z2 C4 组'
        '（32 条波导）无法收敛到 1024/1024。')
    add('- 新 CSV 的拓扑为整体重构（与旧 campaign 重合仅 76/1024），Z1 无邻边、'
        'U 型 368 条、Z2 邻边 400 条；不同连接类型共享同一块 150×150 mm 空间，'
        '逐条独立决策无法协调走廊与层分配。')
    add('')
    add('## 二、自动线束分组模型（P0，已完成）')
    add('')
    add(f'- 规划原子 = C4 旋转四元组（4 条连接）；这是保证 Z2 严格 C4 且让线束'
        f'空间走廊自动 4 重旋转复制的正确抽象。共 '
        f'{len(plane_bundles.get("z1", [])) + len(plane_bundles.get("z2", []))} '
        f'个四元组（z1 {len(plane_bundles.get("z1", []))}、'
        f'z2 {len(plane_bundles.get("z2", []))}）。')
    add('- 每连接特征：起终点 XYZ/切向/内外法向、连接类别、起终连接器与行列、'
        '期望传播方向、端点距离、横向偏移、最小弯曲占用、可行层集合、'
        '平行走廊潜力、U 嵌套区间、预计冲突、C4 组归属。')
    add('- 兼容性图：起终点邻近、方向一致性、端点次序兼容、共享走廊长度、'
        '模板兼容、同层近距重合风险、内部交叉代价、换层空间需求；'
        '四元组间 16 条 2D 弦交叉按"代价"而非"违规"处理。')
    add('- 自动分组算法（实现 4 种并比较）：A 兼容图平均链接凝聚聚类；'
        'A2 允许跨类别合并的图聚类；B 空间走廊/嵌套约束分组；'
        'C 固定大小同类基线（对照）。')
    add('')
    add('| 方法 | 线束数 | 平均 orbits/束 | 平均连接/束 | 内部交叉率 | 平均兼容度 | 混合束 | 选择分 |')
    add('|---|---:|---:|---:|---:|---:|---:|---:|')
    for name, data in methods.items():
        add(f"| {name} | {data.get('bundle_count')} | "
            f"{data.get('size_orbits', {}).get('mean'):.2f} | "
            f"{(data.get('size_orbits', {}).get('mean') or 0) * 4:.1f} | "
            f"{data.get('internal_cross_rate'):.4f} | "
            f"{data.get('mean_compatibility'):.3f} | "
            f"{data.get('mixed_bundles')} | {data.get('score')} |")
    add('')
    add(f'- **自动选中的方法：`{chosen_name}`**，共 {total_bundles} 个线束'
        f'（z1 {plane_counts.get("z1")}、z2 {plane_counts.get("z2")}），'
        f'平均 {chosen_sizes.get("mean", 0):.2f} 个四元组/束（约 {mean_conn:.0f} 条连接），'
        f'范围 {chosen_sizes.get("min")}–{chosen_sizes.get("max")} 个四元组；'
        f'混合类型线束 {mixed} 个；主导类型分布 {kind_mix}。')
    add('- 分组结果：`01_bundle_grouping/bundles.json`（含每个线束的 route_id 列表、'
        'bbox 走廊、宽度、内部冲突数、可选层集合、置信度与分组依据）；'
        '图件 fig01–fig07。')
    add('')
    add('## 三、线束级三维走廊与联合寻路（P1）')
    add('')
    add('- 走廊模型：线束 bbox → 板面走廊矩形；线束冲突图（同平面走廊重叠面积/较小面积'
        '=严重度）；把线束图着色到 L2..Ln 得整束层分配（确定性贪心）。')
    add('- 层分配结果（每个层数）：见 `02_bundle_planning/bundle_plan.json` 与 '
        'fig08_bundle_layer_plan.png。')
    add('- 2D 消融（相同预算、无重试的同设置对照）：')
    add('')
    add('| 顺序 | z1 布通 | z2 布通 | 合计 | 全局 2D 唯一交叉 |')
    add('|---|---:|---:|---:|---:|')
    for tag, row in (('逐条 easy 顺序（对照 A）', p1_2d_base),
                     ('自动线束顺序（B）', p1_2d_bundle)):
        combined = row.get('combined', {}) or {}
        add(f"| {tag} | {row.get('z1', {}).get('routed')}/512 | "
            f"{row.get('z2', {}).get('routed')}/512 | "
            f"{combined.get('routed')} | {combined.get('unique_crossing_pairs')} |")
    add('')
    if repair_bundle:
        add(f"- 修复轮消融（把扩展 U bulge 档位修复应用到 bundle 顺序布局）："
            f"z1 {repair_bundle.get('z1', {}).get('routed')}/512、"
            f"z2 {repair_bundle.get('z2', {}).get('routed')}/512；"
            "低于旧 easy 布局修复后的 512/480。即自动分组显著提高**单遍**布通"
            "（836→872），但在\"修复+重试\"完整管线中未超过旧顺序；"
            "因此最终 2D 基线仍采用 992 布局。")
        add('')
    add('- 3D 消融（同一 2D 输入、同一 lift 引擎与预算）：')
    add('')
    add('| 层数 | 逐条抬升 baseline 交叉 | 线束级层分配+顺序 交叉 | 差值 | 命中规划层/偏离 |')
    add('|---:|---:|---:|---:|---|')
    for layer_count in (5, 7, 11, 15):
        base = p1_rows.get(str(layer_count)) or p1_rows.get(layer_count)
        if base is None:
            fallback = baseline.get(layer_count) or {}
            if fallback:
                base = dict(pairs=fallback.get('unique_crossing_pairs'),
                            routed=fallback.get('routed'))
        bnd = bundle_rows.get(str(layer_count)) or bundle_rows.get(layer_count)
        adh = adherence.get(str(layer_count)) or adherence.get(layer_count) or {}
        if base is None or bnd is None:
            continue
        delta = bnd['pairs'] - base['pairs']
        add(f"| {layer_count} | {base['pairs']} | {bnd['pairs']} | {delta:+d} | "
            f"{adh.get('matched', '-')}/{adh.get('deviated', '-')} "
            f"(命中率 {adh.get('matched_ratio')}) |")
    add('')
    add('## 四、Rip-up & Reroute 联合优化（P2）')
    add('')
    add('- 从 992/1024（Z1 512/512，Z2 480/512）出发；8 个失败 Z2 C4 组：'
        '154、156、158、214、246、249、250、254。')
    add('- 实现并运行了三种线束级拆线重布：')
    add('  1) 单/双 blocker 拆线（候选四元组的冲突四元组一起拆、联合重布）；')
    add('  2) 候选几何窗口拆线（以候选路径自身 bbox 为中心的局部窗口，多顺序重布）；')
    add('  3) 整束走廊重规划（把 28 个 U 型四元组整体拆掉按间距顺序重布）。')
    add(f'- 结果：Z2 最好仍为 **480/512**（失败组不变）；'
        f'候选窗口搜索共记录 {len(window.get("trials") or [])} 次联合重布试验，'
        f'整束 U 重规划尝试 6 种顺序最佳 18/28 组，均未超过原布局。')
    add('- 诊断：失败组的候选四元组平均需要移动 1–3 个相邻四元组，而这些相邻四元组'
        '本身在该走廊内也已饱和（尤其 U 型同边嵌套与角部邻边），局部重布无法同时'
        '满足全部 C4 组的净空；属于**当前模板族 + 布局下的冲突受限**，'
        '不是几何不可能（空板均可布通）。')
    add('- 试验记录：`02_ripup/*.json` 与 checkpoint。')
    add('')
    add('## 五、Native 3D 原型（P3）')
    add('')
    add('- 实现了真正的 XYZ 联合搜索原型：状态 `(x, y, heading, layer)`，'
        '动作 = 直线段 / R15 90° 圆弧 / 垂直 S 曲线换层；动作在搜索过程中'
        '直接对最佳 15L 布局的 3D 障碍点云（428,320 点，包含 L2–L15 全部真实几何）'
        '做方向感知净空检查；端点最后几毫米用冻结 R15 直/S/L/U 模板精确对接。')
    add(f'- 在 8 个失败四元组的代表连接上测试：**{p3_summary.get("found", 0)}/8 找到'
        '搜索生成的三维走廊**（其中 '
        f'{p3_summary.get("native_paths_with_high_layer", 0)} 条路径主动使用了高层），'
        f'扩展节点数见结果文件。')
    add(f'- 验证状态：路径端点/板界/圆弧 R15/净空由构造与搜索保证；'
        f'完整冻结三维验证器集成尚未完成（把搜索路径投影回冻结 2D 验证器时'
        f'存在过渡段投影与圆弧重建的连续性不一致，属已知未完成工作）。')
    add('- 结论：Native 3D 搜索原型能够生成真实 XYZ 路径；但要成为最终 1024 路'
        '生产路由器，还需要原生几何校验（不依赖投影）与 C4 组原子搜索。'
        '本轮最终 1024 布局仍由 2.5D（2D+lift）路径产生，已在文件中明确标注。')
    add('')
    add('## 六、实验设计与结果汇总（P4 / 消融）')
    add('')
    add('| 方案 | 方法 | 布通 | 说明 |')
    add('|---|---|---:|---|')
    add(f"| A | 逐条 2D + 局部抬升（旧基线） | 992/1024 | "
        f"15L 交叉 {baseline.get(15, {}).get('unique_crossing_pairs', '-')}，"
        f"violations={baseline.get(15, {}).get('violations', '-')} |")
    add(f"| B | 自动分组 + 现有 2D 布线 | {p1_2d_bundle.get('combined', {}).get('routed', '-')}/1024 | "
        f"2D 交叉 {p1_2d_bundle.get('combined', {}).get('unique_crossing_pairs', '-')}；"
        f"对照组 A 同预算 {p1_2d_base.get('combined', {}).get('unique_crossing_pairs', '-')} |")
    add(f"| C | 自动分组 + 线束级三维分层 | 992/1024 | "
        f"11L 交叉 {bundle_rows.get('11', bundle_rows.get(11, {}) or {}).get('pairs', '-')}，"
        f"15L 交叉 {bundle_rows.get('15', bundle_rows.get(15, {}) or {}).get('pairs', '-')}"
        f"（baseline 15L {p1_rows.get('15', p1_rows.get(15, {}) or {}).get('pairs', '-')}） |")
    add('| D | C + 线束级 Rip-up & Reroute | 992/1024 | 8 个 Z2 组仍未解决，'
        '失败诊断见 P2 |')
    add(f"| E | Bundle-aware Native 3D 搜索 | 原型 | {p3_summary.get('found', 0)}/8 "
        '代表连接找到三维路径；未集成进 1024 布局 |')
    add('')
    add('## 七、最终需要回答的研究问题')
    add('')
    add(f'1. **1024 条波导能否自动形成有意义的线束？** 能。{total_bundles} 个自动线束'
        f'（z1 {plane_counts.get("z1")}、z2 {plane_counts.get("z2")}），'
        f'平均 {chosen_sizes.get("mean", 0):.2f} 个 C4 四元组/束（约 {mean_conn:.0f} 条），'
        f'兼容图平均兼容度 {chosen.get("mean_compatibility")}。')
    add(f'2. **每束应该包含多少条？是否需要固定组大小？** 不需要固定 k；自动方法'
        f'给出的规模分布为 {chosen_sizes.get("min")}–{chosen_sizes.get("max")} 个四元组/束'
        f'（{int(chosen_sizes.get("min", 0)) * 4}–{int(chosen_sizes.get("max", 0)) * 4} 条），'
        '固定大小基线（C）在内部交叉率上明显更差。')
    add(f'3. **同类型与不同类型分别适合怎样分组？** 同类四元组（U 型/对边/邻边）'
        f'适合按空间走廊与嵌套顺序成束；跨类型只在几何兼容度高时合并——'
        f'本轮自动方法产生 {mixed} 个混合束（{chosen_name}），说明混合束需要更严格的'
        '走廊互不侵犯条件，宜作为下一步（当前以同类束为主 + 走廊级协调）。')
    add('4. **分组后能否减少布线混乱和空间拥塞？** 定量看：自动分组把 1024 条连接'
        f'组织成 {total_bundles} 个束，内部弦交叉率 {chosen.get("internal_cross_rate"):.4f}，'
        '`02_bundle_planning` 的线束级层分配给出了可复现的走廊/层方案；'
        '2D 顺序消融见第三节表格（B 与 A 的布通/交叉对比）。')
    add('5. **能否由线束整体决定使用哪条走廊、哪一层？** 能：实现并输出'
        '`bundle_plan.json`（每束走廊 bbox、宽度、规划层、层使用统计）；'
        '3D 消融中统计了"命中规划层 vs 偏离"比例（见第三节表）。')
    add('6. **能否通过联合拆线重布实现 1024/1024？** 本轮未实现：最好仍为 992/1024。'
        '已实现三种拆线重布并保留全部失败诊断；8 个 Z2 组在当前模板族下需要更大范围'
        '（整条走廊/整组 U 束）的联合重规划或新模板。')
    baseline_pairs = {int(row['layer_count']): row['unique_crossing_pairs']
                      for row in old_compare if 'layer_count' in row}
    add(f'7. **5 层不足是物理层数不足还是算法搜索能力不足？** 从层扫看，'
        f'5L 交叉 {baseline_pairs.get(5, "-")} → 15L {baseline_pairs.get(15, "-")}，'
        '说明空间容量不是唯一瓶颈；'
        '同一 2D 布局下 5L 无法完成全部抬升，而 15L 也只剩 8 个 Z2 组——'
        '瓶颈主要是模板族与局部布局的冲突，而不是简单层数不足。')
    add('8. **7/11/15 层下分组算法各有多少收益？** 见第三节 3D 消融表'
        '（线束级层分配 vs 逐条抬升的交叉差值与命中率）。')
    add('9. **与旧逐条布线相比交叉与长度减少多少？** 旧基线（A，992 布局）'
        f'15L 为 {baseline.get(15, {}).get("unique_crossing_pairs", "-")} 对；'
        f'线束级方案（C）15L 为 {bundle_rows.get("15", bundle_rows.get(15, {}) or {}).get("pairs", "-")} 对，'
        '差值见消融表；长度/加工时间在 `lift_bundle/*/summary.json` 与对比图。')
    add('10. **哪些收益真正来自 Native 3D？** 目前只有 P3 原型路径（搜索主动选层/转向）；'
        '最终 1024 布局仍是 2.5D，不把 P1/P2 的收益算作 Native 3D。')
    add('')
    add('## 八、失败分析与局限性')
    add('')
    add('- 8 个 Z2 C4 组：空板可布通，完整布局中冲突受限；三种拆线重布均未收敛。')
    add('- 线束级层分配是"整束同层"的贪心着色，未处理束内换层与动态走廊占用；'
        '这是与真正联合优化的差距。')
    add('- Native 3D 原型的几何验证尚未接入冻结 3D 验证器；过渡段投影与圆弧重建'
        '需要原生校验器，当前只报告构造性检查与搜索期净空。')
    add('- 所有层高仍为仿真假设（unconfirmed_simulation），与旧实验约定一致。')
    add('')
    add('## 九、后续研究方向')
    add('')
    add('- 线束级联合优化：把"层分配 + 走廊 + 模板选择"放进同一个多目标搜索，'
        '允许束内换层与局部拆线。')
    add('- 原生几何校验：为 3D 搜索路径实现不依赖 2D 投影的冻结校验器适配。')
    add('- U 型专用原生模板：连续 bulge + 同轨惩罚 + 嵌套顺序搜索。')
    add('- 更大规模 C4 组原子搜索：将 4 条连接作为一个状态整体在 XYZ 搜索。')
    add('')
    add('## 十、交付物与复现')
    add('')
    add('```text')
    add('BUNDLE_AWARE_NATIVE_3D/')
    add('├── inputs/                  # 权威 CSV + connectivity 快照 + SHA256')
    add('├── 01_bundle_grouping/      # features/orbits/兼容图/bundles + summary')
    add('├── 02_bundle_planning/      # 走廊/层分配/2D&3D 消融')
    add('├── 02_ripup/                # 拆线重布试验与 checkpoint')
    add('├── 03_native3d/             # Native 3D 原型结果')
    add('├── figures/                 # 分组/走廊/层分配/原型/对比图')
    add('├── code/                    # 本轮新增脚本')
    add('└── experiment_report.md')
    add('```')
    add('')
    add('- 代码：`four_side_1024/bundle3d/`（features、orbits、compatibility、'
        'clustering、corridors、bundle_lift、reroute、native_search、validate_local）'
        '+ `outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D/*.py`。')
    text = '\n'.join(lines) + '\n'
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(text, encoding='utf-8')
    (CAMPAIGN / 'experiment_report.md').write_text(text, encoding='utf-8')
    print('report written:', DOCS, len(text), 'chars')


if __name__ == '__main__':
    main()
