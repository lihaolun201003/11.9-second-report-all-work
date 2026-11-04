# G4 实验总表与逐高度分布（comparison）

- 生成时间: 2026-11-04 20:10:13
- 共同起点: G3 best_valid，routes SHA256 `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`，1322 交叉
- 数据来源: 各臂真实 `routes_l3d.json` / `crossing_stats.json` / `summary.json` / `validation/validation.json` / `budget_ledger.json`；未完成项写“进行中/未完成”。

## 1. 总表（真实接受解）

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

> 说明：G3 起点行唯一交叉对 1253、最大单路 19、含交叉线路 588 来自 `crossing_stats.json` totals 与 G4-1 独立复核；G4 最终最佳解行的预算是“多个臂的累计搜索”，不单独列。

**B 类 warm-start / 探索性运行（非正式臂，不计入公平对照，不能与上面同起点臂比较增量）**

| 运行目录 | 起点交叉 | 终止交叉 | Δ | Validator | 说明 |
|---|---|---|---|---|---|
| 06b_G4d_warm_from_1189 | 1189 | 1189 | 0 | PASS | B 类 warm-start（起点 = best_valid 的 1189 交叉），非正式臂，不能与同起点臂比较增量 |

## 2. 逐物理高度交叉分布（21 高度 × 各臂）

| # | 高度 | z (mm) | G3 | C0 | G4a | G4b | G4c-frz | G4c-free | G4d | G4 best |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | L2 | -0.35 | 17 | 18 | 17 | 17 | 0 | 0 | 0 | 0 |
| 2 | L3 | -0.30 | 0 | 0 | 0 | 0 | 24 | 24 | 21 | 26 |
| 3 | L4 | -0.25 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 | L5 | -0.20 | 0 | 0 | 0 | 0 | 4 | 4 | 4 | 4 |
| 5 | L6 | -0.15 | 96 | 91 | 96 | 96 | 88 | 88 | 88 | 88 |
| 6 | L7 | -0.10 | 54 | 45 | 54 | 54 | 47 | 50 | 50 | 50 |
| 7 | L20 | -0.05 | 44 | 39 | 44 | 44 | 44 | 44 | 44 | 44 |
| 8 | Z1_INTERFACE | +0.00 | 82 | 91 | 82 | 82 | 82 | 82 | 82 | 82 |
| 9 | L8 | +0.05 | 79 | 70 | 79 | 79 | 68 | 68 | 70 | 66 |
| 10 | L9 | +0.10 | 109 | 109 | 109 | 107 | 109 | 109 | 107 | 109 |
| 11 | L10 | +0.15 | 84 | 71 | 84 | 74 | 47 | 52 | 58 | 52 |
| 12 | L11 | +0.20 | 55 | 41 | 55 | 41 | 55 | 43 | 43 | 43 |
| 13 | L12 | +0.25 | 9 | 7 | 7 | 7 | 41 | 37 | 38 | 33 |
| 14 | L13 | +0.30 | 12 | 12 | 12 | 10 | 36 | 38 | 36 | 38 |
| 15 | L14 | +0.35 | 99 | 99 | 99 | 105 | 81 | 81 | 81 | 81 |
| 16 | L15 | +0.40 | 81 | 73 | 81 | 79 | 81 | 77 | 77 | 77 |
| 17 | L16 | +0.45 | 79 | 75 | 79 | 79 | 79 | 67 | 79 | 67 |
| 18 | Z2_INTERFACE | +0.50 | 130 | 130 | 130 | 130 | 130 | 130 | 130 | 130 |
| 19 | L17 | +0.55 | 109 | 107 | 109 | 109 | 82 | 64 | 82 | 64 |
| 20 | L18 | +0.60 | 92 | 92 | 92 | 92 | 63 | 72 | 63 | 72 |
| 21 | L19 | +0.65 | 91 | 89 | 91 | 89 | 61 | 59 | 59 | 59 |

> 每格为该物理高度上的真实交叉事件数（来自各臂 `crossing_stats.json` 的 `planes`）；`NA` = 该臂产物未完成或不含逐高度统计。

## 3. 合法性与独立验收

| 实验 | Validator | 违规数 | 记录 SHA 与解一致 | 验收文件 |
|---|---|---|---|---|
| G3 起点 | PASS | 0 | 是 | `outputs\manual_c4_new_connectivity\XYZ_JOINT_G123_1024\best_valid\validation\validation.json` |
| C0 既有引擎续跑（无新自由度） | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\01_arm_C0\validation\validation.json` |
| G4a 八组固定 + 组级 XY+Z 重造 | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\02_arm_G4a\validation\validation.json` |
| G4b 人工 U 动态重分组 | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\03_arm_G4b\validation\validation.json` |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\04_arm_G4c_frozen\validation\validation.json` |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\05_arm_G4c_free\validation\validation.json` |
| G4d 全部 1024 条大邻域全局优化 | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\06_arm_G4d\validation\validation.json` |
| **G4 最终最佳合法解** | PASS | 0 | 是 | `experiments\xyz_joint_g4_1024\07_best_valid\validation\validation.json` |

独立几何口径审计（G4-1，引用不复算）：`experiments\xyz_joint_g4_1024\00_baseline_audit\GEOMETRY_CONTRACT_AUDIT.md`；最小非交叉净空 0.05 mm、非法交叉 0、净空违规 0。

## 4. 预算与公平性（真实共享引擎计数）

| 实验 | route_3d_checks | 预算上限 | 利用率 | d56_evals | d56 上限 | 搜索墙钟(s) | 墙钟上限 | 是否触顶 |
|---|---|---|---|---|---|---|---|---|
| C0 既有引擎续跑（无新自由度） | 2324 | 30000 | 7.7% | null（不可观测） | 120000 | 1208.76 | 1200 | 是 |
| G4a 八组固定 + 组级 XY+Z 重造 | 6208 | 30000 | 20.7% | 43004 | 120000 | 1018.74 | 1200 | 否 |
| G4b 人工 U 动态重分组 | 1538 | 30000 | 5.1% | 11552 | 120000 | 1099.82 | 1200 | 否 |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 7106 | 30000 | 23.7% | 64342 | 120000 | 1847.02 | 1800 | 是 |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 6851 | 30000 | 22.8% | 63433 | 120000 | 1840.36 | 1800 | 是 |
| G4d 全部 1024 条大邻域全局优化 | 4400 | 30000 | 14.7% | 35815 | 120000 | 1758（run.log 实测；ledger=106.3 被覆盖） | 1200 | 否 |

> 墙钟主口径为 `budget_ledger.wall_seconds`（搜索循环）；`run.log` 首末时间戳为全过程交叉核对，差异 >50% 时并列显示。G4d 的 ledger 值 106.3 s 在中断/恢复时被覆盖，其 `run.log` 实测约 1758 s，表中按 run.log 显示并标注。
> `d56_candidate_evals` 对 C0 为 `null`（旧引擎未接入共享 Ledger，口径不可比，SPEC 要求显式写 null）；其余臂为共享引擎真实计数。

## 5. 起点与公平性（从各臂 config.json / start_snapshot.json 实测，不引用声明值）

| 实验 | 起点 SHA 与 G3 一致 | 实际加载起点交叉 | seed | 说明 |
|---|---|---|---|---|
| C0 既有引擎续跑（无新自由度） | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |
| G4a 八组固定 + 组级 XY+Z 重造 | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |
| G4b 人工 U 动态重分组 | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |
| G4c-frozen 人工 U 冻结 + 联合让路 ALNS | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |
| G4c-free 人工 U 解冻 + 联合让路 ALNS | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |
| G4d 全部 1024 条大邻域全局优化 | 是 | 1322 | 20261104 | 同一起点（1322 合法基线） |

> 同起点公平对照只使用起点 SHA = G3 SHA 的臂；渐进链臂（如 G4d `tag=formal_chain_from_1248` 之类）的终止交叉包含前序臂收益，**不得把 1322→终止 的全部收益归因于该臂**。链收益拆分见 `08_progressive_chain/progressive_chain.json`。

## 6. 渐进链收益拆分（`experiments\xyz_joint_g4_1024\08_progressive_chain\progressive_chain.json`）

| 环节 | 来源臂 | 起点交叉 | 终点交叉 | 本段收益 | 本段墙钟(s) | Validator |
|---|---|---|---|---|---|---|
| G3 公共起点 | G3 | 1322 | 1322 | 0 | 0 | 进行中/未完成 |
| best(G4a, G4b) 检查点 | G4b | 1322 | 1294 | -28 | 1099.8 | PASS |
| 链段 G4c 重跑（从 link1 1294 起） | G4c_free | 1294 | 1204 | -90 | 740.5 | PASS |
| 最佳 G4c 检查点（来自 A 类 G4c_free 臂） | G4c_free | 1294 | 1189 | -105 | 0 | PASS |
| 链段 G4d（从 1189 最佳 G4c 检查点起） | G4d | 1189 | 1185 | -4 | 1230 | PASS |
| G4d warm-start（06b，seed 20261105，B 类平行探索） | G4d_warm | 1189 | 1189 | 0 | 0 | PASS |

> 链的累计收益 = 各段收益之和；不得把链的累计收益全部归因于最后一个臂/算法。

## 7. 机器可读数据与对照文件

- `experiments/xyz_joint_g4_1024/metrics.csv` / `budget_ledger.csv` / `experiment_matrix.csv` / `fair_comparison.md`（G4-4 采集）
- `experiment_matrix.csv` 生成时间 **2026-11-04 20:01:14**；含最终 best 行（`chain_link3` = **1185**）=是；含 G4c_free `ce7ca9a9…` 记录=是（已与最终报告对账）。
- `experiments/xyz_joint_g4_1024/10_reports/metrics_summary.json`（本报告全部数字的机器可读版本）
- `experiments/xyz_joint_g4_1024/09_plots/G3_vs_G4/G3_vs_G4_per_height.csv`（逐高度 before/after 明细）

## 8. Lead 补充结构分析（**探索性，非正式臂**，不进入任何臂的收益表）

| 项目 | 数值 | 来源 |
|---|---|---|
| 交叉类别 manual-manual / manual-nonmanual / nonmanual-nonmanual | 2 / 107 / 1213 | `experiments\xyz_joint_g4_1024\10_reports\lead_crossing_structure.json` |
| 接口层交叉（结构性下限） | 212（Z1_INTERFACE=82、Z2_INTERFACE=130） | `experiments\xyz_joint_g4_1024\10_reports\lead_crossing_structure.json` |
| E1 exact-delta 高度重分配（探索） | 1322 → **1226** （**exploratory, not a formal arm**） | `experiments\xyz_joint_g4_1024\10_reports\lead_explore_migrate.json` |
| E2 exact-delta 高度重分配（探索） | → **1191** （**exploratory, not a formal arm**） | `experiments\xyz_joint_g4_1024\10_reports\lead_explore_migrate2.json` |
| interface direct_plane_recreate（探索） | 8 次尝试、gain 全部 0、全部回滚；最终 1226 | `experiments\xyz_joint_g4_1024\10_reports\lead_explore_direct.json` |

> 以上为 Lead 的探索性分析（`_lead_explore_*` 为 scratch 目录，未计入正式臂与 MANIFEST 的臂收益）；正式结论只用各臂接受解与独立 Validator 证据。

