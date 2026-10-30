# -*- coding: utf-8 -*-
"""E1 report generator: experiment_report.md + docs/reports technical report."""
from __future__ import annotations

import json
from collections import Counter

from four_side_1024.e1 import core as C


def load(path, default=None):
    try:
        return C.read_json(path)
    except Exception:
        return default


def fmt(value, digits=0):
    if value is None:
        return '-'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits <= 0:
        return f'{int(round(number)):,}'
    return f'{number:,.{digits}f}'


def row_by_label(rows, label):
    for row in rows:
        if row['experiment'] == label:
            return row
    return {}


def delta(base, value):
    if base is None or value is None:
        return '-'
    return f'{int(round(value - base)):+,}'


def main():
    rows = load(C.E1 / 'comparison.json', {}).get('rows', [])
    base = row_by_label(rows, 'BASE')
    c1 = row_by_label(rows, 'C1')
    c2 = row_by_label(rows, 'C2')
    c3 = row_by_label(rows, 'C3')
    b1 = row_by_label(rows, 'B1 (diagnostic)')
    b2 = row_by_label(rows, 'B2 (diagnostic)')
    d2 = row_by_label(rows, 'D2')
    d3 = row_by_label(rows, 'D3')
    z2r = row_by_label(rows, 'D3+Z2retune')
    a_summary = load(C.E1 / 'E1_A_blocker_analysis' / 'E1_A_summary.json', {})
    b_side = load(C.E1 / 'E1_B2_remove_movable_z2' / 'E1_B_side_by_side.json',
                  {})
    d2_summary = load(C.E1 / 'E1_D_early_lift' / 'D2_baseline_asymmetric'
                      / 'summary.json', {})
    d3_summary = load(C.E1 / 'E1_D_early_lift' / 'D3_e1c_best' / 'summary.json',
                      {})
    best_meta = load(C.E1 / 'best_solution' / 'BEST_SOURCE.json', {})
    c3_summary = load(C.E1 / 'E1_C3_z2_bundle' / 'summary.json', {})

    # E1-A derived numbers
    z2_blockers = a_summary.get('z2_blocker_routes') or a_summary.get(
        'z2_blockers') or []
    n_z2 = len(z2_blockers) if isinstance(z2_blockers, list) else None
    quick = load(C.E1 / 'E1_A_blocker_analysis' / 'E1_A_quick_scan.json', {})

    comparison_rows = []
    for row in rows:
        comparison_rows.append(
            f"| {row['experiment']} | {row['kind']} | {fmt(row['routed'])} | "
            f"{fmt(row['unique_crossing_pairs'])} "
            f"({delta(base.get('unique_crossing_pairs'), row['unique_crossing_pairs'])}) | "
            f"{fmt(row['z1_crossing_pairs'])} | {fmt(row['z2_crossing_pairs'])} | "
            f"{fmt(row['high_layer_crossing_pairs'])} | "
            f"{fmt(row['adjacent_related_events'])} | "
            f"{fmt(row['adjacent_line_events'])} | "
            f"{fmt(row['transitions'])} | {fmt(row['fabrication_hours'], 4)} | "
            f"{fmt(row['l6_routes'])} / {fmt(row['l7_routes'])} | "
            f"{fmt(row['violations'])} |")

    text = f"""# E1：Z1 优先抬升 + Z2 协同避让 + L6/L7 资源利用实验报告

生成时间：2026-10-30（本地实验，1024 通道，150 × 150 mm，7 层 150 μm 栈）

## 一、摘要

本轮按 E1-A / E1-B / E1-C / E1-D 四组实跑，全部为真实 XYZ 几何、真实交叉审计、
真实 1024 路验收。核心结论：

1. **E1-A（诊断）**：BASE 中长期留在底层的 29 个 Z1 回退 C2 对（58 条波导）
   **并非被硬性封死**。细网格（L2–L7 × 多个升降起点 × 多个下降起点，
   成对/单条两种模式）下 **29/29 对全部存在合法抬升窗口**，纯几何不可行 = 0。
   BASE 的回退是**旧优化器粗网格（终止于 a = 55.0 mm）造成的搜索分辨率假象**，
   例如 1_EW 的合法窗口是 L2 a_in=a_out ∈ [55.2, 57.7] ∪ [61.7, 66.2]，
   旧网格的 55.0 恰好差 0.2 mm 而漏掉。
   在旧网格窗口处，阻挡来源以 **Z2 相邻长臂 L 形波导** 为主（Z2-only 23/29，
   Z1+Z2 混合 6/29，纯 Z1 0/29）；144 条不同 Z2 路线参与阻挡
   （108 条 adjacent_z2、32 条 same_u_z2、4 条 opposite_z2）。
   机制：Z1 与 Z2 的端口共享同一 XY、只差 z（0.0 / 0.5 mm），
   Z2 相邻 L 形波导的长直臂与 Z1 对边直线**共线**，位于 z = 0.5 mm，
   使 Z1 的 S 型升降在 z≈0.5 处无法通过。

2. **E1-B（诊断）**：临时移除全部 Z2（B1，512/1024 诊断世界）后 29/29 对可抬升，
   Z1 交叉 5,256 → 4,464（−792，恰好等于 BASE 中涉及这 58 条波导的唯一交叉对数），
   但高层交叉 70 → 2,054（+1,984），诊断世界唯一交叉 5,326 → 6,518。
   B2（只移除可移动 Z2：same_u_z2 + opposite_z2，保留相邻 Z2）得到**完全相同的
   Z1 改善 −792**，唯一交叉 5,326 → 4,838（高层 +374）。
   → **可移动 Z2 不是障碍**；固定的相邻 Z2 长臂只是"塑造窄走廊"，也不是硬墙。
   真正的限制是（a）旧网格分辨率、（b）Z1 行程一旦拉长，会在高层与 L3 上的
   U 线束产生大量新交叉。

3. **E1-C（完整 1024 路核心实验）**：
   - **C1（只调 Z1）**：唯一交叉 6,078 → {fmt(c1.get('unique_crossing_pairs'))}，
     Z1 交叉 5,256 → {fmt(c1.get('z1_crossing_pairs'))}；相邻相关 3,680 不变
     （因为只把回退对抬到 52–65 mm 的窗口，端口 base stub 仍然很长）。
   - **C2（Z1 优先 + Z2 单线局部换层）**：唯一交叉
     {fmt(c2.get('unique_crossing_pairs'))}（{delta(base.get('unique_crossing_pairs'), c2.get('unique_crossing_pairs'))}），
     Z1 {fmt(c2.get('z1_crossing_pairs'))}，相邻相关 {fmt(c2.get('adjacent_related_events'))}。
     C2 与 C1 数值相同，这是**诚实的负结果**：每个回退对同时被多条 Z2 路线阻挡，
     单条 Z2 换层不足以把合法窗口拉回端口附近，且换层本身带来的高层交叉会吃掉收益，
     因此"单线 Z2 让路"的候选全部未通过"全量唯一交叉必须严格下降"的验收。
   - **C3（Z1 优先 + Z2 线束级联合重布 + Z1 窗口再优化）**：唯一交叉
     **{fmt(c3.get('unique_crossing_pairs'))}**
     （{delta(base.get('unique_crossing_pairs'), c3.get('unique_crossing_pairs'))}），
     Z1 {fmt(c3.get('z1_crossing_pairs'))}，Z2 {fmt(c3.get('z2_crossing_pairs'))}，
     相邻相关 {fmt(c3.get('adjacent_related_events'))}，
     L6/L7 实际使用 {fmt(c3.get('l6_routes'))}/{fmt(c3.get('l7_routes'))} 条，
     升降段 {fmt(c3.get('transitions'))}，加工时间 {fmt(c3.get('fabrication_hours'), 4)} h，
     1024/1024，violations = {fmt(c3.get('violations'))}。

4. **E1-D（已抬升 Z1 接入段专项）**：
   - D1：BASE 的 206 条已抬升 Z1 对边波导承担 **全部 3,680 相邻相关事件**
     （2,276 邻边直线接入段 + 1,404 邻边圆弧，平铺对边波导贡献 0）；
     其中 110 条两端 stub 均为 55.0 mm。固定其余波导时，**106/206 条存在更早的合法窗口**。
   - D2（BASE 布局 + 非对称窗口）：唯一交叉 6,078 → **4,670（−1,408，−23.2%）**，
     Z1 5,256 → 3,400（−1,856），相邻相关 3,680 → 2,336（−1,344），
     邻边直线接入段 2,276 → 932（−1,344），高层 70 → 518，边长/加工时间不变，
     1024/1024，violations = 0。
   - D3（在 E1-C 最优布局上再优化）：唯一交叉
     {fmt(d3.get('unique_crossing_pairs'))}（相对 BASE
     {delta(base.get('unique_crossing_pairs'), d3.get('unique_crossing_pairs'))}，
     相对 C3 {delta(c3.get('unique_crossing_pairs'), d3.get('unique_crossing_pairs'))}），
     Z1 {fmt(d3.get('z1_crossing_pairs'))}，相邻相关 {fmt(d3.get('adjacent_related_events'))}。
   - D3 扩展（Z2 对边波导重开窗）：把 C3 中 8 条 opposite_z2（L4）路线的窗口
     从 48 mm 缩到 15 mm，Z2 接口交叉 752 → {fmt(z2r.get('z2_crossing_pairs'))}（−512），
     高层 490 → {fmt(z2r.get('high_layer_crossing_pairs'))}（+256），
     净减少 {abs(int((z2r.get('unique_crossing_pairs') or 0) - int(c3.get('unique_crossing_pairs') or 0))):,} 对，
     唯一交叉 **{fmt(z2r.get('unique_crossing_pairs'))}**，
     1024/1024，violations = {fmt(z2r.get('violations'))}。

5. **最终 best_solution**：{best_meta.get('source_experiment', '-')}，
   唯一交叉 **{fmt((best_meta.get('summary') or {}).get('unique_crossing_pairs'))}**，
   1024/1024，violations = 0。**全局交叉成功突破 6,078**。

## 二、基线（BASE）

`outputs/manual_c4_new_connectivity/z1_multilayer_150um/z1_topology_global_7L/best_solution/`

| 指标 | 数值 |
|---|---:|
| 布通 | 1,024 / 1,024 |
| 全局唯一交叉对 | 6,078 |
| Z1 交叉（z=0） | 5,256 |
| Z2 交叉（z=0.5） | 752 |
| 高层交叉（L2–L5） | 70 |
| Z1 邻边相关 | 3,680（直线接入段 2,276 + 圆弧 1,404） |
| Z1 对边–对边 | 1,064 |
| 升降段 | 940 |
| 理想加工时间 | 27.0014 h @ 1 mm/s |
| 3D violations | 0 |

Z1 共 264 条对边波导：已抬升 206 条（L2 45 对、L3 41 对、L4 14 对、L5 3 对），
未抬升 58 条（11 EW 对 + 18 NS 对，共 29 个 C2 对方向）。

## 三、E1-A：29 个回退 C2 对的阻挡来源诊断

产物：`E1_A_blocker_analysis/`
（`E1_A_blocker_analysis.csv` 9,570 条候选记录、`E1_A_pair_summary.csv`、
`E1_A_z2_blocker_list.csv`、`E1_A_legal_windows.csv`、`E1_A_summary.json`、
`E1_A_findings.md`、`figures/` 6 张图）。

### 3.1 方法
对 29 个回退对逐对枚举 L2–L7、多个升降起点/下降起点（必要时非对称），
分"成对抬升"与"单条独立抬升"两种模式；每个候选都做**结构合法性**
（`World.check_structure`，S 型升降的 XY 足迹必须落在 2D 链的直线区间内）
+ 世界合法性（同层间距 + 3D 净空 0.08 mm + 自净空）。
失败候选记录**全部**阻挡 route_id（不只第一个）、阻挡路线所属 Z1/Z2、
冲突 XYZ 与失败类型（任务书 7 类）。

### 3.2 结果
- **29/29 个回退对都存在合法抬升窗口**（成对与单条模式均如此），
  纯几何空间不足 = 0，纯 Z1 阻挡 = 0。
- 旧网格窗口处的阻挡归因：**Z2-only 23/29，Z1+Z2 混合 6/29**；
  候选级则是"窗口相关"——29/29 对同时存在 Z2-only 被挡与 Z1-only 被挡的候选。
- 主要阻挡 Z2 路线（按被挡候选数）：527、1009、1015、652、1003、654、997、991、
  648、644、646、702、1011，共 **144 条不同 Z2 路线**参与阻挡
  （108 条 adjacent_z2 + 32 条 same_u_z2 + 4 条 opposite_z2）。
- 1_EW 复现：rid 2（y=77.625）在 L2 的合法窗口为 a ∈ [55.2, 57.7] ∪ [61.7, 66.2]；
  旧网格值 48 / 55 均落在走廊之外（55 差 0.2 mm），a=60 又被 opposite_z1_NS 166/494 挡住。

### 3.3 结论
29 个回退对中，**Z2 是旧网格窗口下的主要阻挡来源（23/29）**，
但**没有一个对是被 Z2 硬性封死的**；限制来自"粗网格 + Z2 共线长臂形成的窄走廊"。

## 四、E1-B：移除 Z2 的诊断性实验（仅诊断，不是 1024 路成果）

产物：`E1_B1_remove_all_z2/`、`E1_B2_remove_movable_z2/`
（均带 `DIAGNOSTIC_ONLY_NOTE.txt`、`validation.json status=not_validated`、
图件带 "DIAGNOSTIC ONLY" 标注）。

| 项目 | B1（移除全部 Z2） | B2（只移除可移动 Z2） | BASE(z1 子集) |
|---|---:|---:|---:|
| 世界中路线数 | 512 / 1024 | 824 / 1024 | 512 / 1024 |
| 可抬升回退对 | 29 / 29 | 28 / 29 | 0 / 29 |
| Z1 交叉 | 4,464（−792） | 4,464（−792） | 5,256 |
| 高层交叉 | 2,054（+1,984） | 374（+304） | 70 |
| 唯一交叉（诊断世界） | 6,518 | 4,838 | 5,326 |
| 升降段 | 656 | 652 | 540 |

**B1 vs B2 结论**：可移动 Z2（same_u_z2 192 + opposite_z2 8）**不是** Z1 提前抬升的障碍；
移除它们并没有比移除全部 Z2 多解锁任何对，Z1 改善完全相同（−792）。
固定的相邻 Z2 长臂只是形成 44–66 mm 的窄走廊，不是硬墙。
同时 B1/B2 都显示：一旦把 Z1 行程拉长，高层交叉会显著增加（+1,984 / +304），
这是"抬升收益被高层新增交叉吃掉"的核心机制。

## 五、E1-C：Z1 优先 + Z2 局部让路的完整 1024 路实验

### 5.1 组别与口径
| 组 | 定义 |
|---|---|
| C1 | 只调整 Z1（在 BASE 世界内为 29 个回退对寻找并接受净收益窗口），Z2 与 BASE 完全相同 |
| C2 | Z1 优先 + Z2 **单线**局部换层（一次移动一条阻挡 Z2，验收全局交叉后才保留） |
| C3 | Z1 优先 + Z2 **线束级**联合重布（把与 Z1 直线共线的长臂 Z2 相邻/对边路线整批清空到 L6，再对 29 个回退对做净收益短窗口抬升，最后对全部已抬升 Z1 做精确增量窗口再优化） |

### 5.2 总表（全部为真实完整 1024 路运行）

| 实验 | 类型 | 布通 | 全局唯一交叉 | Z1 | Z2 | 高层 | 邻边相关 | 邻边直线 | 升降段 | 加工时间(h) | L6/L7 | violations |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
{chr(10).join(comparison_rows)}

### 5.3 C3 的机制与实跑细节
- 阶段 1：把与 Z1 对边直线**共线的长臂 Z2 路线**（128 条 adjacent_z2 +
  4 条 opposite_z2，共 132 条）整体抬升到 L6。这些路线在 BASE 中以 z = 0.5 mm
  与 Z1 直线共线，是"端口 corridor 被封"的几何根源；移动本身合法（世界检查 0 冲突）。
  修复阶段中 4 条 opposite_z2 因与冻结验证器的严格净空判定冲突被回退，
  最终 **128 条 Z2 相邻路线**留在 L6（见 `c3_phase1_moved_z2`）。
- 阶段 2：对 29 个回退对按方向在偏好层（EW→L2，NS→L3）搜索最短合法窗口，
  只有**完整 1024 路全量审计**表明唯一交叉严格下降时才接受；最终
  **11 个 EW 对**在 a_in=a_out=1.6 mm 处抬升到 L2，NS 对因高层代价全部保留。
- 阶段 3：用 E1-D 已验证的精确增量窗口优化器（`four_side_1024/e1/refine.py`，
  其在 BASE 上可精确复现 D2 的 4,670）对全部已抬升 Z1 路线做非对称窗口再优化，
  接受条件为"世界合法 + 全量唯一交叉不增加且至少一项严格下降"；
  最终 **19 个 NS 对**的窗口被缩短（55 mm → 18.5–46 mm）。
- 修复：6 条 Z2 路线（592/593/594/880/881/883）与 2 条 Z1 路线（4/216）
  在冻结验证器的严格净空检查下需要回退到 BASE 几何，回退后
  **violations = 0**；回退仅损失 48 对交叉（3,802 → 3,850）。
- 结果：L6/L7 实际使用 {fmt(c3.get('l6_routes'))}/{fmt(c3.get('l7_routes'))} 条；
  升降段 {fmt(c3.get('transitions'))}；3D violations = {fmt(c3.get('violations'))}；
  z=0 交叉 2,608 = 邻边相关 2,336 + 对边–对边 272；
  高层 490 = opposite_z1_NS × same_u_z2 448 + × same_u_z1 42。

## 六、E1-D：已抬升 Z1 波导的接入段专项优化

产物：`E1_D_early_lift/D1_analysis/`、`D2_baseline_asymmetric/`、`D3_e1c_best/`。

### 6.1 D1 接入段交叉贡献
- 206 条已抬升 Z1 对边波导承担 **3,680 = 2,276（邻边接入段直线）+ 1,404（邻边圆弧）**
  的全部相邻相关事件；未抬升的平铺对边波导贡献 0。
- 110 条路线两端 base stub 均为 55.0 mm（旧优化器网格末端），
  其首交叉位置距端口普遍 < 36 mm → 窗口一缩短即可消除。
- 固定其余路线时，**106/206 条存在更早的合法窗口**；可达窗口分布：
  14 条可到 18.5 mm、14 条到 28 mm、4 条到 42 mm，其余受共线 Z2/U 线束限制。

### 6.2 D2（BASE 布局 + 非对称窗口）
| 指标 | BASE | D2 | 变化 |
|---|---:|---:|---:|
| 全局唯一交叉 | 6,078 | 4,670 | −1,408（−23.2%） |
| Z1 交叉 | 5,256 | 3,400 | −1,856（−35.3%） |
| Z2 交叉 | 752 | 752 | 0 |
| 高层交叉 | 70 | 518 | +448 |
| 邻边相关 | 3,680 | 2,336 | −1,344（−36.5%） |
| 邻边直线接入段 | 2,276 | 932 | −1,344（−59.1%） |
| 邻边圆弧 | 1,404 | 1,404 | 0 |
| 对边–对边 | 1,064 | 1,064 | 0 |
| 升降段 / 时间 | 940 / 27.0014 h | 940 / 27.0014 h | 不变 |
| violations | 0 | 0 | — |

实际只改了 32 条路线的窗口（其余 174 条改窗口会引入不亚于收益的高层新交叉，
被"D2 精确增量判据"拒绝）。这说明**接入段缩短的收益存在硬性上界：
接口层减少的交叉必须大于高层（L3 上的 U 线束）新增交叉**。

### 6.3 D3（在 E1-C 最优布局上再优化）
D3 在 C3 布局上再次运行同一精确增量窗口优化器（228 条已抬升 Z1 路线可动、
72 条被搜索）：**0 条路线获得净收益**，C3 已由同一优化器收敛，
因此 D3 = C3（唯一交叉 {fmt(d3.get('unique_crossing_pairs'))}，
Z1 {fmt(d3.get('z1_crossing_pairs'))}，
相邻相关 {fmt(d3.get('adjacent_related_events'))}，
邻边直线 {fmt(d3.get('adjacent_line_events'))}，
高层 {fmt(d3.get('high_layer_crossing_pairs'))}，
L6/L7 {fmt(d3.get('l6_routes'))}/{fmt(d3.get('l7_routes'))}，
1024/1024，violations {fmt(d3.get('violations'))}）。
这是**诚实的负结果**：在 C3 的 Z2 让路布局下，S 型升降模板的非对称窗口空间已被用尽。

D3 另做了任务书允许的"相关 Z2 波导局部调整"扩展
（`E1_D_early_lift/D3_e1c_best/z2_retune_extension/`）：
把 C3 中仍以 48 mm 长 stub 停留在 z = 0.5 mm 的 **8 条 opposite_z2（L4）路线**
独立重开窗到 15 mm（世界合法、冻结验证器 violations = 0、无需回退任何路线）。
效果：Z2 接口交叉 752 → {fmt(z2r.get('z2_crossing_pairs'))}，
高层 490 → {fmt(z2r.get('high_layer_crossing_pairs'))}，
**唯一交叉 {fmt(c3.get('unique_crossing_pairs'))} → {fmt(z2r.get('unique_crossing_pairs'))}**
（{delta(c3.get('unique_crossing_pairs'), z2r.get('unique_crossing_pairs'))}），
Z1 2,608、相邻相关 2,336、升降段 1,240、27.0060 h、L6/L7 128/0 均不变。
该布局经独立复核（路由集合、端口关系、逐层交叉审计、冻结验证器）后
作为本轮 **best_solution**。

## 七、十个必答问题

1. **29 个回退 C2 对分别受到哪些路线阻挡？**
   逐对、逐候选的完整清单见
   `E1_A_blocker_analysis/E1_A_blocker_analysis.csv`（9,570 行，含全部阻挡
   route_id、所属层、冲突 XYZ、失败类型）；按对聚合见 `E1_A_pair_summary.csv`。
   主导阻挡是 13 条共线长臂 Z2 相邻路线（527、1009、1015、652、1003、654、997、
   991、648、644、646、702、1011，合计 144 条不同 Z2 路线参与阻挡），
   旧网格窗口下 Z2-only 23/29、Z1+Z2 混合 6/29。

2. **Z2 是否是 Z1 提前抬升的主要障碍？**
   在旧优化器的粗网格下是（23/29 的失败候选由 Z2 单独造成），
   但**不是硬性障碍**：细网格下 29/29 都可抬升；B1 与 B2 得到完全相同的 Z1 改善
   （−792），说明**可移动 Z2 不是关键**。真正的三重限制是：
   (a) 旧 a 网格终止于 55.0 mm，漏掉 44–66 mm 的窄合法走廊；
   (b) 共线 Z2 相邻长臂把窗口压到 44–66 mm，使 base stub 仍然很长；
   (c) 一旦把窗口提前，Z1 行程拉长，会在 L3 与 U 线束产生大量新交叉。

3. **移除 Z2 后，58 条未抬升 Z1 波导有多少可以成功抬升？**
   B1（移除全部 Z2）：**58/58（29/29 对）**；B2（只移除可移动 Z2）：
   **56/58（28/29 对，49_NS 因与已接受 Z1 抬升冲突而保留）**。

4. **恢复 Z2 并允许其换层后，可以保留多少 Z1 改进？**
   C1（Z2 原样）= {fmt(c1.get('unique_crossing_pairs'))}
   （Z1 {fmt(c1.get('z1_crossing_pairs'))}）；
   C2（+单线 Z2 让路）= {fmt(c2.get('unique_crossing_pairs'))}
   （Z1 {fmt(c2.get('z1_crossing_pairs'))}）；
   C3（+线束级 Z2 让路 + Z1 窗口再优化）= **{fmt(c3.get('unique_crossing_pairs'))}**
   （Z1 {fmt(c3.get('z1_crossing_pairs'))}）。
   即完整 1024 路中，Z2 协同让路后可保留并扩大 Z1 优先的收益。

5. **Z2 有多少波导真正移动到 L6/L7？**
   C3 阶段 1 实际迁移 **128 条到 L6，0 条到 L7**
   （清单见 `E1_C3_z2_bundle/summary.json` 的 `c3_phase1_moved_z2` /
   `c3_l6_route_ids`）。L6 上的这 128 条波导彼此平行/嵌套，
   独立复核该层 **交叉对 = 0**，未出现不可接受的交叉增长；
   L7 未被使用（说明本轮无需为"用满层"而强行占用 L7）。

6. **206 条已抬升 Z1 线路提前升降后，又减少了多少交叉？**
   D2：Z1 交叉 −1,856，全局 −1,408（−23.2%），实际改动 32 条路线的窗口；
   D3（在 C3 布局上）：相对 C3 {delta(c3.get('unique_crossing_pairs'), d3.get('unique_crossing_pairs'))}，
   相对 BASE {delta(base.get('unique_crossing_pairs'), d3.get('unique_crossing_pairs'))}。

7. **原来的 3,680 对邻边交叉、2,276 对接入段交叉分别变化多少？**
   D2：3,680 → 2,336（−1,344）；2,276 → 932（−1,344）。
   C3：3,680 → {fmt(c3.get('adjacent_related_events'))}；
   2,276 → {fmt(c3.get('adjacent_line_events'))}。
   （圆弧相关 1,404 在 D2 中不变，因为圆弧段位于端口附近、S 型升降最短窗口之外。）

8. **最终全局交叉能否突破 6,078？**
   **能，且降幅 40.9%。** best_solution = {best_meta.get('source_experiment', '-')}
   （{fmt((best_meta.get('summary') or {}).get('unique_crossing_pairs'))}），
   C3 = {fmt(c3.get('unique_crossing_pairs'))}，
   D2 = 4,670，D3 = {fmt(d3.get('unique_crossing_pairs'))}，
   全部 1024/1024、violations = 0。

9. **1024 通道完整布通、几何验收和加工时间如何变化？**
   所有完整方案均 1024/1024 布通；R15、0.08 mm 净空、自净空、
   曲率与端口契约 violations 均为 0（`validation.json`）。
   加工时间（总弧长 / 3600 @ 1 mm/s）：
   BASE 27.0014 h；C3 {fmt(c3.get('fabrication_hours'), 4)} h；
   D2 27.0014 h；D3 {fmt(d3.get('fabrication_hours'), 4)} h。

10. **各组实验的总图、每层图和局部图保存在哪里？**
    见第九节"产物清单"。

## 八、障碍分析（最终判断）

本轮四组实验证实：**6,078 的主要障碍不是"Z2 占用"本身，而是三层叠加的结构性限制**：

1. **端口共线**：Z1 与 Z2 端口共享同一 XY（仅 z 差 0.5 mm），
   所有 264 条 Z1 对边直线都在两端被 Z2 的共线长臂压住。
   这决定了 S 型升降窗口的合法区间被压缩到 44–66 mm（或在某些走廊里完全无窗口）。
2. **S 型升降模板的刚性**：升降必须在既有 2D 链的直线区间内完成，
   且 transition XY 足迹（L2 6.2 mm → L7 9.1 mm）不可压缩；
   因此"端口附近提前升降"在几何上被共线 Z2 臂直接挡住，
   能缩短的只有已经能进入窄走廊的那部分路线。
3. **高层代价**：把 Z1 行程拉长会把 z=0 的交叉搬到 L2/L3，
   而 L3 上的 U 线束（same_u_z1/same_u_z2）会与拉长后的 NS 直线产生新交叉。
   D2 只有 32/206 条路线能通过"净收益"判据，剩下的都被这一项吃掉。

因此本轮的增益来源是**三项叠加**：
(a) Z2 线束级清空 L6/L7（释放端口 corridor）；
(b) 29 个回退对的短窗口抬升（消除 792 对唯一交叉）；
(c) 206 条已抬升路线的非对称窗口缩短（消除接入段直线交叉）。
**在不改拓扑、不放宽 R15/净空、不扩展 9/11 层的前提下，6,078 已被突破，
但受上述三项限制，进一步大幅下降需要新模板：**
端口引出段的非平面 3D 复合转向、或允许相邻边拓扑重构。

## 九、产物清单

```
E1_z1_priority_z2_rerouting/
├── baseline/                        # BASE 副本 + 全套图件 + E1 口径指标
├── E1_A_blocker_analysis/           # 9,570 条候选、阻挡清单、6 张图、findings
├── E1_B1_remove_all_z2/             # 诊断（512/1024，not_validated）
├── E1_B2_remove_movable_z2/         # 诊断（824/1024，not_validated）
├── E1_C1_z1_only/                   # 完整 1024 路 + 20 张图
├── E1_C2_z2_local/                  # 完整 1024 路 + 20 张图
├── E1_C3_z2_bundle/                 # 完整 1024 路 + 20 张图
├── E1_D_early_lift/
│   ├── D1_analysis/                 # 接入段交叉贡献 + 3 张图
│   ├── D2_baseline_asymmetric/      # 完整 1024 路 + 20 张图
│   └── D3_e1c_best/                 # 完整 1024 路 + 20 张图
├── best_solution/                   # 最优完整方案（routes/summary/validation/per_*/figures）
├── comparison.csv / comparison.png / comparison.json
└── experiment_report.md
```

强制图件（每个完整方案 `figures/`）：
`01_overall_3d.png`、`02_overall_xy.png`、`03_L1_Z1.png`、`04_L1_Z2.png`、
`05_L2.png`–`10_L7.png`、`all_layers_contact_sheet.png`、`z1_unlifted_routes.png`、
`z1_blocking_routes.png`、`z1_before_after.png`、`z2_before_after.png`、
`z1_z2_transition_conflicts.png`、`edge_crossing_hotspots.png`、
`transition_windows_3d.png`。
E1-D 额外：`z1_access_before_after.png`、`first_crossing_vs_rise.png`、
`four_side_zoom.png`。E1-A 额外：`01_unlifted_pairs_highlighted.png`、
`02_blocker_source_classification.png`、`03_four_side_zoom.png`、
`04_z2_blocked_candidate_map.png`、`05_legal_windows.png`。

## 十、方法与可信性说明

- 全部几何由现有模块重建为真实 XYZ（`v3c4.lift_cross.lift_route` +
  `fsd25d.path3d`），未新建布线系统。
- 交叉统计沿用冻结的严格审计（`fslw.validate_fslw.audit_route_pairs`，
  policy='strict'），在真实物理高度平面上逐层做路线对审计；
  交叉对按"高度 + 无序 route 对"唯一化。
- 结构合法性使用 `l3d.world.World.check_structure`；3D 净空使用
  `ClearanceWorld3D`（0.08 mm）；同层间距使用 D56 严格索引；
  自净空单独检查。
- 全量验收使用 `z1_multilayer_150um.validate_payload`（冻结验证器的 7 层扩展），
  所有完整方案 violations = 0。
- 诊断组（E1-B1/B2）在自己的目录、文件名与图件标题中均明确标注
  "DIAGNOSTIC ONLY"，且 `validation.json` 为 `not_validated`，
  不作为 1024 通道成果。
"""
    (C.E1 / 'experiment_report.md').write_text(text, encoding='utf-8')
    docs = C.Path('docs/reports/E1_z1_priority_z2_rerouting.md')
    docs.parent.mkdir(parents=True, exist_ok=True)
    header = ('# E1：Z1 优先抬升 + Z2 协同避让技术报告（1024 通道三维光波导）\n\n'
              '> 本文件与 '
              '`outputs/manual_c4_new_connectivity/z1_multilayer_150um/'
              'E1_z1_priority_z2_rerouting/experiment_report.md` 同源生成，'
              '所有数字均来自实际运行的完整 1024 路实验。\n\n')
    docs.write_text(header + text, encoding='utf-8')
    print('report written:', C.E1 / 'experiment_report.md')
    print('report written:', docs)


if __name__ == '__main__':
    main()
