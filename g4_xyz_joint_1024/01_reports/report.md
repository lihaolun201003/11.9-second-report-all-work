# G4 最终报告：人工 U 动态重分组与大邻域 XY+Z 联合三维重布（1024）

- 生成时间: 2026-11-04 20:10:14
- 归档根: `experiments\xyz_joint_g4_1024`
- 任务契约: `SPEC_G4.md`
- 起点（只读，未被覆盖）: `outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/best_valid`，routes SHA256 `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`，1024/1024 布通、1322 交叉
- 最终最佳合法解: `experiments\xyz_joint_g4_1024\07_best_valid`（SHA256 `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`）

## 0. 结论速览（先给答案）

| 必答项 | 结论 | 证据 |
|---|---|---|
| **1024/1024 是否保持** | 是 | 最终解 `routes_l3d.json` routes=1024、failed=0；身份/端口/连接由独立 Validator 复核 |
| **几何是否合法** | 是 | 冻结独立 Validator（`manual_policy=fully_optimizable`）：PASS，violations=0，SHA 与解一致=是（`experiments\xyz_joint_g4_1024\07_best_valid\validation\validation.json`） |
| **最低交叉降到多少** | **1185**（G3 起点 1322，Δ=-137，-10.4%） | 最终解 `crossing_stats.json` totals，逐层复核见 `09_plots/G4_best_1185/G4_best_LAYERS.md` |
| **挑战目标（1200/1000/800/500/100/9/0）** | ≤1200 达到、≤1000 未达、≤800 未达、≤500 未达、≤100 未达、≤9 未达、≤0 未达 | 最高达成目标 ≤1200 |
| **是否严格证明最优/无解** | **否** | 本轮只报告“在给定引擎/算法/预算下达到的最低交叉”，无下界证明、无穷举覆盖证明 |

> 一句话结论：在**不降低任何物理约束、不删连接、不改交叉口径**的前提下，G4 从 G3 的 1322 交叉出发，最终接受解为 **1185 交叉**（-10.4%），未达成 1000 突破目标；所有臂/最终解均通过冻结独立 Validator。

## 1. 起点基线与独立几何口径审计（G4-1）

G3 起点的几何口径由独立审计（geometry-auditor，**不复用历史 PASS 结论**）重新计算，详见 [`../00_baseline_audit/GEOMETRY_CONTRACT_AUDIT.md`](../00_baseline_audit/GEOMETRY_CONTRACT_AUDIT.md) 与 `audit_metrics.json`。

### 1.1 六个必需量（独立复算值，直接引用）

| 必需量 | 值 | 说明 |
|---|---|---|
| `minimum_distance_all_pairs_mm` | 0.0 | 全部中心线对（含合法横穿）的 3D 最小距离 |
| `minimum_clearance_non_crossing_mm` | 0.05 | 排除合法横穿后的全板最小净空 |
| `allowed_crossing_count` | 1322 | 允许类交叉事件数 |
| `illegal_crossing_count` | 0 | 非法交叉数 |
| `clearance_violation_count` | 0 | 净空违规数 |
| `crossing_exemption_policy` | 同层 D56 strict 80 µm + 真实横穿豁免（角 ≥ 5°、窗口半宽 ≤ 4 mm）；不同高度 |dz| ≥ 0.05 mm；transition 真 3D ≥ 0.05 mm | 交叉豁免口径（D56 strict + 横穿局部窗口） |

### 1.2 口径必须写清的三个事实

1. **“最小 3D 净空 0.063596 mm”只覆盖 transition 相关对**（`validate21.measure_min_3d_clearance` 口径，只量 transition-vs-flat 与 transition-vs-transition），**不是全板最小值**。全板“不同物理高度 flat 对”的最小 3D 距离 = **0.05 mm**（相邻层间距恰为 0.05 mm、且存在 XY 相交的相邻层 flat 对，例如 route 515/623），**零余量但按契约合法**。
2. **“1322 交叉 + 0 几何违规”自洽的原因**：两条规则作用于**不相交的对集合**——同层 flat/flat 对只受 D56 strict 2D 0.08 mm + 既有真实横穿豁免（冻结基线自带 2409 交叉并通过同一 Validator，非 G4 新增豁免）约束；不同物理高度对受 |dz| ≥ 0.05 mm 约束（3D 距离必然 ≥ 0.05，永远不会“看到”这 1322 个交叉）；涉及 transition 的对受真 3D ≥ 0.05 mm 约束且无横穿豁免。因此 1322 个合法横穿不会转化为净空违规。
3. **运行时净空为 0.05 mm，但代码默认值仍是历史 0.08 mm**：`l3d/world.py` 默认 `clearance=None` 会退化为 `fslw.config.CLEARANCE_MM = 0.08`；现行 Validator/路由器全部**显式传 0.05**（`reheight21/validate21.py`、`xyzrouter/world_adapter.py`）。本报告引用 50 µm 时均指**运行时显式 0.05 mm 口径**，`0.08` 只是历史默认值/文档遗留。

G3 起点的独立 Validator 复跑：**PASS**，violations=0，记录 SHA 与起点解一致=是（`experiments\xyz_joint_g4_1024\00_baseline_audit\baseline_revalidation\validation.json`）。

### 1.3 最终解的独立复算（正式终验 FINAL_AUDIT）

- 记录：`experiments\xyz_joint_g4_1024\00_baseline_audit\FINAL_AUDIT`（摘要 `experiments\xyz_joint_g4_1024\00_baseline_audit\FINAL_AUDIT\FINAL_AUDIT_SUMMARY.md`）
- 被审计解：`experiments\xyz_joint_g4_1024\07_best_valid`，routes SHA256 `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`
- 校验：all_checks_pass=True，validator_pass=True，skipped=[]，elapsed=31.7 s
- 六必需量：minimum_distance_all_pairs=0、minimum_clearance_non_crossing=0.05、allowed_crossing_count=1185、illegal=0、clearance_violation=0


## 2. 实验设计与公平性

| 实验 | 可动线路 | 高度自由度 | XY 自由度 | 搜索机制 |
|---|---|---|---|---|
| C0 | 全部 1024 | 单线迁移 | 单线走廊重造 | 沿用 G3 既有优化器（不新增自由度，公平对照） |
| G4a | 368 人工 U（组固定） | 每组统一主体高度可换 | 组内 XY 全重造 | 组级事务 + 组高度枚举 |
| G4b | 368 人工 U | 单条迁移/交换/拆分/重组 | 全重造 | 动态分组事务 |
| G4c-frozen | 非人工线路（人工 U 冻结） | 非人工可迁移 | 全重造 | 联合让路 ALNS，邻域 8/16/32/64 |
| G4c-free | 全部（人工 U 可作目标/阻挡者） | 全部 | 全重造 | 同上 |
| G4d | 全部 1024 | 全部 | 全部 | 全局大邻域 ALNS / Ruin-Recreate，多重建顺序、多 seed |

- 共同起点/种子: G3 best_valid（SHA `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`）、seed=20261104；
- 同起点公平对照臂: C0、G4a、G4b、G4c_frozen、G4c_free、G4d
- 公平性: 受 `route_3d_checks` / `d56_candidate_evals` / 墙钟三重预算约束（名义预算：C0/G4a/G4b 1200 s，G4c 1800 s，G4d 2400-3600 s，见 `g4/paths.py` 与各臂 `config.json`）；实际用量以 `budget_ledger.json` 真实计数为准（见 `comparison.md` §4）。
- 验收: 每臂最佳解由**独立子进程**冻结 Validator （`manual_policy=fully_optimizable`）验收；best_valid 只在事务整组验收且交叉严格下降后更新。

## 3. 各臂结果（真实接受解）

| 实验 | 终止交叉 | Δ vs 1322 | 降幅 | 唯一交叉对 | 最大单路交叉 | 含交叉线路 | Validator | 违规数 | route_3d_checks | d56_evals | 搜索墙钟(s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G3 起点 | 1322 | 0 | 0.0% | 1253 | 19 | 588 | PASS（独立复跑） | 0 | - | - | - |
| C0 既有引擎续跑（无新自由度） | 1259 | -63 | -4.8% | 1209 | 19 | 578 | PASS | 0 | 2324 | null（不可观测） | 1208.76 |
| G4a 八组固定 + 组级 XY+Z 重造 | 1320 | -2 | -0.2% | 1252 | 19 | 586 | PASS | 0 | 6208 | 43004 | 1018.74 |
| G4b 人工 U 动态重分组 | 1294 | -28 | -2.1% | 1234 | 19 | 582 | PASS | 0 | 1538 | 11552 | 1099.82 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 1222 | -100 | -7.6% | 1149 | 19 | 593 | PASS | 0 | 7106 | 64342 | 1847.02 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 1189 | -133 | -10.1% | 1128 | 19 | 594 | PASS | 0 | 6851 | 63433 | 1840.36 |
| G4d 全部 1024 条大邻域全局优化 | 1212 | -110 | -8.3% | 1148 | 19 | 593 | PASS | 0 | 4400 | 35815 | 1758（run.log 实测；ledger=106.3 被覆盖） |
| **G4 最终最佳合法解** | 1185 | -137 | -10.4% | 1124 | 19 | 593 | PASS | 0 | - | - | - |

- `C0 既有引擎续跑（无新自由度）`：终止交叉 1259（Δ=-63），来源 `experiments\xyz_joint_g4_1024\01_arm_C0`
- `G4a 八组固定 + 组级 XY+Z 重造`：终止交叉 1320（Δ=-2），来源 `experiments\xyz_joint_g4_1024\02_arm_G4a`
- `G4b 人工 U 动态重分组`：终止交叉 1294（Δ=-28），来源 `experiments\xyz_joint_g4_1024\03_arm_G4b`
- `G4c-frozen 人工 U 冻结 + 联合让路 ALNS`：终止交叉 1222（Δ=-100），来源 `experiments\xyz_joint_g4_1024\04_arm_G4c_frozen`
- `G4c-free 人工 U 解冻 + 联合让路 ALNS`：终止交叉 1189（Δ=-133），来源 `experiments\xyz_joint_g4_1024\05_arm_G4c_free`
- `G4d 全部 1024 条大邻域全局优化`：终止交叉 1212（Δ=-110），来源 `experiments\xyz_joint_g4_1024\06_arm_G4d`

**G4a 组级迁移与“可动集合上界”证据（真实几何，`group_migration.json`）**：被接受的整体组迁移 0、部分迁移 0；人工 U 主体高度改变 1/368 条；body XY 签名改变 10 条；起点交叉分解 manual-manual 2 / manual-non 107 / non-manual 1213；该臂移动集合的解析下界 1213（臂自报，只对 G4a 的移动集合成立，**不是全局下界**）。

**重要负结果（如实保留）**：既有引擎对照臂 C0 在同一墙钟预算下终止于 **1259**，优于人工 U 臂 G4a **1320** / G4b **1294**。这不是“分组方案更差”的证据，而是**可动集合不同**：C0 可动 1024 条（656 条非人工线路），G4a/G4b 只能动 368 条人工 U、其解析下界 1213。任何跨臂比较都必须先看可动集合（见 `comparison.md` §1 注）。

**B 类 warm-start / 探索性运行（非正式臂，不计入公平对照）**：06b_G4d_warm_from_1189 1189→1189（Validator PASS）

> 这些运行从更优检查点 warm-start（起点 ≠ 1322），其收益包含继承收益，不能与同起点臂直接比较，也不用于六问归因。

> **G4d A 类臂计时说明（Lead 确认）**：该臂因外部误杀分两次 session 运行（1242.7 s + 111.6 s ≈ **1354 s** 搜索墙钟）；`budget_ledger` 与矩阵中的 wall 字段是 session 2 的值，不能当作该臂总搜索时间（本报告预算表已并列 run.log 实测）。

## 4. 六问回答（摘要）

完整回答与证据表见 [`10_reports/answers.md`](answers.md)。

1. **原八组人工 U 是否存在更优分组？** — 存在更优分组：G4b 1294 vs G4a 1320（-26）
2. **XY 重构是否解除高度可达性限制？** — 真实几何显示 7 条人工 U 高度改变、8 条人工 U XY 改变，且最终解通过独立 Validator
3. **解冻人工 U 与大邻域搜索分别贡献多少收益？** — 人工 U 解冻边际收益 +33 交叉（G4c-frozen 1222 → G4c-free 1189）；大邻域收益见 C0 1259 → frozen 1222
4. **哪些线路阻碍进一步下降？** — 最受阻线路 route 640（19 交叉，人工组 -，Z2_INTERFACE）；剩余交叉集中在 Z2_INTERFACE、L9、L6 等高度
5. **是否突破 1000？** — 否（1185 ≥ 1000）
6. **下一轮最值得扩大的搜索自由度？** — 见 `answers.md` 问题 6 的排序建议：扩大跨分量联合事务邻域、针对交叉最集中高度的走廊重造、多 seed/预算扩展

## 5. 逐层可视化与逐高度统计（G4-5 核心交付）

| 目录/文件 | 内容 |
|---|---|
| `09_plots/G3_baseline/` | G3 基线 21 个物理高度的独立 XY 图 + 21 层总览拼图 + 逐层统计（JSON/CSV/Markdown） |
| `09_plots/G4_best_1185/` | G4 最终最佳解（1185 交叉）21 层独立 XY 图 + 拼图 + 逐层统计 |
| `09_plots/G3_vs_G4/` | G3 vs G4 逐层对照图（21 张，before/after 并排）+ 逐高度明细 CSV |
| `09_plots/G4a_arm/`、`G3_vs_G4a/`、`G4a_migration/`、`G4a_modifications/` | G4a 臂（1320）的 21 层图、逐层对照、人工 U 迁移与 XY+Z 修改量 |
| `09_plots/G4b_arm/`、`G3_vs_G4b/`、`G4b_migration/`、`G4b_modifications/` | G4b 臂（1294）的同类产物 |
| `09_plots/C0_arm/`、`G3_vs_C0/`、`C0_modifications/` | C0 对照臂（1259）的同类产物 |
| `09_plots/manual_u_migration/` | 人工 U 原八组 → 新几何族群迁移矩阵与表格 |
| `09_plots/modifications/` | XY+Z 修改量统计图（分类、长度变化、高度变化）与 per-route CSV |
| `09_plots/budget/` | 交叉随评价预算/墙钟下降曲线 + 预算柱状图 |
| `09_plots/failure_analysis/` | 失败原因分类图 |

每层独立图区分：**真实平面直线**（非人工蓝 / 人工红）、**R15 圆弧**（青 / 橙，实测半径恒为 15.000000 mm）、**三维过渡段足迹投影**（紫色虚线，来自真实 S 曲线采样）、**真实交叉点**（红 ×，来自 `crossing_stats.json` 且 z 精确匹配到该层）。逐层统计字段：主体线路数、同层真实交叉、唯一交叉线路对、原人工 U 数、当前分组数（按该层真实主体线路的 `manual_group` 集合）、平均/最大单路线交叉、该层参与的中途换层数、拥堵区（×/15 mm 块）与空闲走廊（无线路网格块）。

### 5.1 交叉最集中的物理高度（G3 → G4 best，真实事件数）

| 高度 | z (mm) | G3 交叉 | G4 best 交叉 | Δ | G4 best 主体线路 |
|---|---|---|---|---|---|
| Z2_INTERFACE | +0.50 | 130 | 130 | +0 | 512 |
| L9 | +0.10 | 109 | 109 | +0 | 55 |
| L17 | +0.55 | 109 | 64 | -45 | 47 |
| L14 | +0.35 | 99 | 81 | -18 | 47 |
| L6 | -0.15 | 96 | 88 | -8 | 57 |
| L18 | +0.60 | 92 | 72 | -20 | 47 |
| L19 | +0.65 | 91 | 59 | -32 | 48 |
| L10 | +0.15 | 84 | 52 | -32 | 25 |
| Z1_INTERFACE | +0.00 | 82 | 82 | +0 | 512 |
| L15 | +0.40 | 81 | 77 | -4 | 50 |
| L8 | +0.05 | 79 | 66 | -13 | 39 |
| L16 | +0.45 | 79 | 67 | -12 | 46 |
| L11 | +0.20 | 55 | 43 | -12 | 38 |
| L7 | -0.10 | 54 | 50 | -4 | 53 |
| L20 | -0.05 | 44 | 44 | +0 | 45 |
| L2 | -0.35 | 17 | 0 | -17 | 35 |
| L13 | +0.30 | 12 | 38 | +26 | 50 |
| L12 | +0.25 | 9 | 33 | +24 | 52 |
| L3 | -0.30 | 0 | 26 | +26 | 68 |
| L5 | -0.20 | 0 | 4 | +4 | 89 |

> 该表直接来自两个接受解的 `crossing_stats.json` `planes`（逐高度计数，已与事件逐点核对）；完整 21 高度视图见 `09_plots/G3_vs_G4/G3_vs_G4_per_height.csv`。

### 5.2 交叉结构分解（Lead 补充分析，**探索性，非正式臂**）

数据来源（只读引用，不重新计算）：`experiments\xyz_joint_g4_1024\10_reports\lead_crossing_structure.json`、`experiments\xyz_joint_g4_1024\10_reports\lead_interface_analysis.json`、`experiments\xyz_joint_g4_1024\10_reports\lead_component_probe.json`、`experiments\xyz_joint_g4_1024\10_reports\lead_migration_probe.json`；探索脚本结果：`experiments\xyz_joint_g4_1024\10_reports\lead_explore_migrate.json`、`experiments\xyz_joint_g4_1024\10_reports\lead_explore_direct.json`。

| 交叉类别（G3 起点 1322） | 数量 |
|---|---|
| manual-manual | 2 |
| manual-nonmanual | 107 |
| nonmanual-nonmanual | 1213 |

- **接口层结构性下限**：Z1_INTERFACE + Z2_INTERFACE 合计 **212** 交叉（Z1_INTERFACE=82、Z2_INTERFACE=130）。Lead 分析判定这是 direct-body×direct-body 的**结构性下限**；本轮 `direct_plane_recreate` 8 次尝试（z=0.0 四种顺序、z=0.5 四种顺序，分别放置 44/53 条）**gain 全部 = 0、全部回滚**，说明仅重排接口平面无法消除这些交叉。
- 交叉冲突图：1253 条边 / 588 个线路节点 / 38 个连通分量，最大分量 32 条线路，最大度 19；分量大小前 8 = 32、28、28、27、26、26、25、25。
- 交叉角分布（度）：60-90°: 850、30-60°: 368、15-30°: 46、5-15°: 58。
- Lead 探索 E1（exact-delta 高度重分配，**exploratory, not a formal arm**）：探索状态 1322→**1226**（accepted 4 次变化，606.4 s）；该数字**不是正式臂成绩**，仅说明该自由度有潜力，需下一轮形式化为正式臂。
- Lead 探索（interface direct_plane_recreate，**exploratory, not a formal arm**）：8 次尝试，gain 集合 = [0, 0, 0, 0, 0, 0, 0, 0]，最终仍为 1226。
- Lead 探索 E2（exact-delta 高度重分配第二组，**exploratory, not a formal arm**）：最终探索状态 **1191**（accepted 2 次变化）；该数字不是正式臂成绩。
- **E1/E2/E1b 系列均为 exploratory, not a formal arm**：起点分别为 G3（1322）与 1200–1201 链检查点，不计入任何正式臂的收益表；仅用于说明“精确高度重分配”这一自由度有潜力，需下一轮形式化为正式臂。

### 5.3 交叉收益的阶段归属（真实 stage 统计）

| 实验 | 阶段 | 机制 | 尝试 | 接受 | 收益 | 收益占比 | 用时(s) |
|---|---|---|---|---|---|---|---|
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | -1 | greedy migration sweep（无邻域） | 720 | 20 | 97 | 97% | 750.1 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 0 | neighbourhood 8 | 32 | 0 | 0 | 0% | 241.4 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 1 | neighbourhood 16 | 44 | 1 | 3 | 3% | 255.9 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 2 | neighbourhood 32 | 38 | 0 | 0 | 0% | 278.1 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 3 | neighbourhood 64 | 22 | 0 | 0 | 0% | 269.1 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | -1 | greedy migration sweep（无邻域） | 720 | 28 | 121 | 91% | 750 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 0 | neighbourhood 8 | 26 | 4 | 11 | 8.3% | 236.8 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 1 | neighbourhood 16 | 40 | 0 | 0 | 0% | 254.3 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 2 | neighbourhood 32 | 38 | 0 | 0 | 0% | 275.1 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 3 | neighbourhood 64 | 27 | 1 | 1 | 0.8% | 271.3 |

- `G4c_frozen`：总收益 100 中 **97（97%）来自 greedy migration sweep**；邻域阶段收益：neighbourhood 8 = 0、neighbourhood 16 = 3、neighbourhood 32 = 0、neighbourhood 64 = 0。
- `G4c_free`：总收益 133 中 **121（91%）来自 greedy migration sweep**；邻域阶段收益：neighbourhood 8 = 11、neighbourhood 16 = 0、neighbourhood 32 = 0、neighbourhood 64 = 1。

> 负结果如实保留：大邻域 16/32/64 阶段在本轮预算下几乎没有收益，收益主要来自对高冲突线路的 greedy migration sweep。这说明当前瓶颈已不在“小邻域选择”，而在**可动集合与结构性下限**（人工 U 可动集合上界 1213、接口 212 结构下限）。

### 5.4 渐进链收益拆分（`experiments\xyz_joint_g4_1024\08_progressive_chain\progressive_chain.json`）

| 环节 | 来源臂 | 起点交叉 | 终点交叉 | 本段收益 | 本段墙钟(s) | Validator |
|---|---|---|---|---|---|---|
| G3 公共起点 | G3 | 1322 | 1322 | 0 | 0 | 进行中/未完成 |
| best(G4a, G4b) 检查点 | G4b | 1322 | 1294 | -28 | 1099.8 | PASS |
| 链段 G4c 重跑（从 link1 1294 起） | G4c_free | 1294 | 1204 | -90 | 740.5 | PASS |
| 最佳 G4c 检查点（来自 A 类 G4c_free 臂） | G4c_free | 1294 | 1189 | -105 | 0 | PASS |
| 链段 G4d（从 1189 最佳 G4c 检查点起） | G4d | 1189 | 1185 | -4 | 1230 | PASS |
| G4d warm-start（06b，seed 20261105，B 类平行探索） | G4d_warm | 1189 | 1189 | 0 | 0 | PASS |

> 链的累计收益 = 各段收益之和；**不得把链的累计收益全部归因于最后一个算法/臂**（SPEC 第 4 节）。

## 6. 失败原因分析摘要

完整分类计数见 [`10_reports/failure_analysis.md`](failure_analysis.md)。按真实臂产物计数：

- `legal_but_no_crossing_improvement`：5491 次
- `no_legal_xy_corridor`：1563 次
- `no_current_crossings`：958 次
- `transition_3d_conflict`：364 次
- `joint_rebuild_failed`：166 次
- `target_height_occupied`：60 次
- `unclassified`：22 次
- `budget_exhausted`：2 次

所有失败分类都只表示**“在给定算法与预算下未找到/未接受”**，不构成任何目标的严格无解证明；本轮未做下界/穷举覆盖证明。

## 7. 负结果、局限与不可宣称事项

- **负结果如实保留**：若最终交叉仍 >1000/1200，则相应挑战目标未达成；不粉饰、不以“近似/等效”替代真实交叉计数。
- **未证明最优/无解**：本轮只报告在给定共享引擎、算法族与预算下达到的结果；无下界证明。
- **仅中心线几何模型**：光学串扰、弯曲/交叉损耗未验证（`fslw/config.py` 中交叉损耗状态为 unknown_uncalibrated）；1322 等数字是**几何计数**，不是光学可行性或制造可行性结论。
- **制造约束未验证**：无工艺 bias、侧壁角、折射率剖面、表面工艺余量、连接器外壳干涉；连接器安装方向与 1 mm 玻璃厚度为假设值。
- **21 高度为探索性层栈**（provenance=unconfirmed_simulation），不得表述为“满足全部制造约束”。
- **G4a 组级换层负结果**：被接受的整组迁移 0 / 部分组迁移 0，仅 1 条人工 U 真实换高，交叉只下降 -137；臂自报“仅动人工 U”解析下界 1213（非全局下界）→ 原八组固定分组下，组级换层几乎不可行。
- **几何口径差异（需求级风险）**：若任务书把 50 µm 理解为“任意两条中心线无例外”，则 1322 个合法同层横穿（距离 0）会与字面要求冲突；本报告按仓库现行冻结契约（D56 strict + 横穿豁免）判定，且**未新增任何豁免**。该口径差异需项目负责人确认（见 G4-1 审计 §7.3）。

## 8. 归档、MANIFEST 与 GitHub 状态（如实）

- `MANIFEST.json`：850 个文件、262.11 MB，SHA256 校验 通过
- `code/` 代码快照：25 个文件（g4 包全部 .py + SPEC_G4.md），快照与源文件哈希一致=是
- Git：仓库=否，GitHub remote=无，分支=-，结论=not a git working tree
- **本归档为本地归档**：未配置 GitHub remote，未执行 commit/push；完整性由本地 SHA256 MANIFEST 与 `code/SHA256.json` 保证。

复现命令见归档根 `README.md`；校验命令：`python -m four_side_1024.fanout1024.xyzrouter.g4.archive_g4 --verify-only`。

