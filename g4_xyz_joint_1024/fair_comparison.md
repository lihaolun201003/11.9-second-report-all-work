# G4 公平对照报告（C0 / G4a / G4b / G4c-frozen / G4c-free / G4d）

> 自动生成于 2026-11-04 20:01:26，由 `g4/metrics_collect.py` 从各臂**真实产物**汇总。
> 数据来源：`<arm>/best_valid/routes_l3d.json`（几何 + 冻结口径复算）、`<arm>/crossing_stats.json`、`<arm>/summary.json`、`<arm>/validation/validation.json`（独立 Validator）、`<arm>/budget_ledger.json`（真实观测计数器）、`<arm>/config.json`。
> 所有缺失/不可观测字段写 `NA` 或 `null`，绝不估算或伪造。

## 1. 实验设计与公平性契约核查

共同起点：G3 合法最优解 `outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/best_valid`，routes SHA256 = `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`，同层真实交叉 **1322**；共同随机种子 seed = **20261104**。

**主公平轴 = 相同完整几何候选评价预算**：`route_3d_checks` ≤ 30000、`d56_candidate_evals` ≤ 120000（见 `paths.DEFAULT_BUDGET`），全部臂同起点（G3 SHA `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`）、同 seed = 20261104。

墙钟上限按 SPEC `ARM_BUDGETS` 分臂设置：C0/G4a/G4b = 1200s，G4c-frozen/G4c-free = 1800s，G4d = 3600s；各臂实际预算/实际耗时如实记录在下表与 `budget_ledger.json`。**各臂类型不同、墙钟上限不同，但计数预算相同；墙钟不作为唯一公平轴**。若某臂先撞计数预算而停，也照实记录（不补时、不改上限）。

| 臂 | 起点交叉（复算） | 起点 SHA 与 G3 一致 | 起点 SHA256 | seed | 墙钟预算(s) | World检查预算 | D56评价预算 | 实际搜索耗时(s) | 进程总耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| C0 | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1200 | 30000 | 120000 | 1208.8 | 1259.0 |
| G4a | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1200 | 30000 | 120000 | 1018.7 | NA |
| G4b | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1200 | 30000 | 120000 | 1099.8 | NA |
| G4c_frozen | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1800 | 30000 | 120000 | 1847.0 | NA |
| G4c_free | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1800 | 30000 | 120000 | 1840.4 | NA |
| G4d | 1322 | True | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 | 20261104 | 1200 | 30000 | 120000 | 106.3 | NA |

## 2. 主结果对照（所有数值来自真实产物）

| 臂 | 起点交叉 | 终点交叉 | 下降 | 交叉对 | 最大单线交叉 | 有交叉线路 | 变化线路 | 人工U变化 | 中间过渡 | 总长(mm) | 最小3D净空(mm) | 合法(validation) | 违规数 | 交叉来源 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 | 1322 | 1259 | -63 | 1209 | 19 | 578 | 30 | 6 | 64 | 156879.60 | 0.062454 | True | 0 | routes_l3d.json 复算 |
| G4a | 1322 | 1320 | -2 | 1252 | 19 | 586 | 10 | 10 | 72 | 157020.43 | 0.063596 | True | 0 | routes_l3d.json 复算 |
| G4b | 1322 | 1294 | -28 | 1234 | 19 | 582 | 11 | 11 | 72 | 156953.82 | 0.063596 | True | 0 | routes_l3d.json 复算 |
| G4c_frozen | 1322 | 1222 | -100 | 1149 | 19 | 593 | 21 | 0 | 68 | 156770.53 | 0.063596 | True | 0 | routes_l3d.json 复算 |
| G4c_free | 1322 | 1189 | -133 | 1128 | 19 | 594 | 36 | 9 | 70 | 156730.94 | 0.060877 | True | 0 | routes_l3d.json 复算 |
| G4d | 1322 | 1212 | -110 | 1148 | 19 | 593 | 24 | 4 | 70 | 156770.52 | 0.063596 | True | 0 | routes_l3d.json 复算 |

## 2b. B 类链与 exploratory（单列报告，不与 A 类混算）

| 行类 | arm | 起点交叉 | 终点交叉 | 增量 | 交叉对 | 变化线路 | 人工U变化 | 最小3D净空(mm) | validation | 违规 | 墙钟(s) | World检查 | D56评价 | 事务/尝试 | 有效候选 | 起点/来源 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B_chain | chain_link1 | 1322 | 1294 | -28 | 1234 | 11 | 11 | 0.063596 | True | 0 | 1099.8 | NA | NA | NA | NA | G4b |
| B_chain | chain_link2 | 1294 | 1204 | -90 | 1143 | 18 | 3 | 0.060877 | True | 0 | 740.5 | 2136 | 17436 | 155 | 1344 | G4c_free |
| B_chain | chain_link2b | 1294 | 1189 | -105 | 1128 | 41 | 14 | 0.060877 | True | 0 | 0.0 | NA | NA | NA | NA | G4c_free |
| B_chain | chain_link3 | 1189 | 1185 | -4 | 1124 | 2 | 0 | 0.060877 | True | 0 | 1230.0 | 4915 | 34893 | 218 | 3868 | G4d |
| B_chain | chain_link06b | 1189 | 1189 | 0 | 1128 | 0 | 0 | 0.060877 | True | 0 | 1061.4 | 4003 | 29196 | 184 | 3107 | G4d_warm |
| exploratory | E1 | 1322 | 1226 | -96 | 1159 | 14 | 1 | NA | not_run | NA | 606.4 | 2502 | 14952 | 4 | 1280 | E1 |
| exploratory | E2 | 1201 | 1191 | -10 | 1129 | 2 | 0 | NA | not_run | NA | 308.2 | 1356 | 8352 | 2 | 683 | E2 |
| exploratory | E1b | 1226 | 1226 | 0 | 1159 | 0 | 0 | NA | not_run | NA | 128.4 | 334 | 2328 | 8 | 334 | E1b |

* **B 类（`class=B_chain`）**：继承链，起点是上一链段/继承的最佳合法检查点，不是 G3 共同起点，**不参与 A 类同起点对照的归因**。`chain_link1`=best(G4a,G4b) 检查点（1294，继承自 A 类 G4b）；`chain_link2`=G4c 从 1294 重跑（1204，对照）；`chain_link2b`=继承的**最佳 G4c 检查点**（1189，来自 A 类 G4c_free 臂，不是重跑值）；`chain_link3`=G4d 从 1189 起（**1185**）；`chain_link06b`=g4-core 的平行 warm-start（seed 20261105，1189）。
* **exploratory（`class=exploratory`）**：非正式臂探索（E1=1226、E2=1191、E1b=1226 未改善），只引用其 best_valid 真实 routes 复算，无独立 validation 的如实标 `not_run`，**不计入 A 类对照**。

## 2c. 最终最佳合法解（07_best_valid）

* 路径：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\07_best_valid`
* **1185 交叉 / 1124 唯一交叉对 / 1024 路由**；routes SHA256 = `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`
* 独立 Validator：`validation_pass=True`，`violations=0`
* 来源：`chain_link3_G4d`（B 类链 link3，从 A 类最佳 G4c_free 1189 继承再降 4；归因规则见 §6，链的累计收益不得全归因最后算法）
* FINAL_AUDIT：`all_checks_pass=True`、`validator_pass=True`、最低非交叉净空 0.05 mm、违规 0；状态文件 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\00_baseline_audit\FINAL_AUDIT\final_audit_status.json`

## 3. 预算账本（实际用量，非估算）

| 臂 | World几何检查次数 | World预算利用率 | D56候选评价次数 | D56预算利用率 | D56 proxy*（仅记录，非公平轴） | 事务/尝试 | 有效候选数 | 接受变化数 | Validator次数 | 搜索墙钟(s) | 墙钟利用率 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 | 2324 | 7.7 | null（不可观测） | NA | 175816 | 1542 | 2204 | 31 | 1 | 1208.8 | 100.7 |
| G4a | 6208 | 20.7 | 43004 | 35.8 | NA | 95 | 5275 | 10 | 0 | 1018.7 | 84.9 |
| G4b | 1538 | 5.1 | 11552 | 9.6 | NA | 320 | 1198 | 11 | 0 | 1099.8 | 91.7 |
| G4c_frozen | 7106 | 23.7 | 64342 | 53.6 | NA | 254 | 4506 | 21 | 1 | 1847.0 | 102.6 |
| G4c_free | 6851 | 22.8 | 63433 | 52.9 | NA | 274 | 4313 | 47 | 1 | 1840.4 | 102.2 |
| G4d | 4400 | 14.7 | 35815 | 29.8 | NA | 254 | 3039 | 24 | 1 | 106.3 | 8.9 |

\* `D56 proxy` 列：C0 的真实但**口径不同**的代理观测（`d56.index.D56Index.evaluate` 实际调用次数），仅作信息记录，**不进入公平预算判定**；其它臂该列为 NA。

计数器口径说明：`route_3d_checks`、`d56_candidate_evals`、`xy_candidates_generated`、`valid_candidates`、`accepted_changes`、`gain`、`validator_runs` 为跨臂同口径；C0 的 `transactions` / `accepted_transactions` / `no_candidate` 是**旧引擎单线路**语义（G4 臂为多线路联合事务语义），只在 `budget_ledger.csv` 记录、**不作直接比较**；`wall_seconds` 由各臂账本真实记录，C0 为纯搜索循环耗时，另列 `process_seconds` 交叉核对。

### 3.1 关于 C0 的 D56 计数（重要，不得冒充同预算）

* C0 使用**现有 G3 优化器**继续搜索（单线 XY+Z 重规划，**不增加任何自由度**）。该旧引擎把每次 XY 候选的严格 D56 评价封装在 `layer2d`／`local_reroute` 内部，**没有接入共享 `g4.ledger.Ledger`**，因此 C0 的 `d56_candidate_evals` 按 SPEC_G4 §3.2 显式写为 `null`，**不是 0，也不是估算值**。
* C0 的 `route_3d_checks` 是真实观测：每调用一次 `world_adapter.RouteWorld.evaluate_candidate` 记 1 次（即对真 3D World 做一次完整单线路几何检查），与 G4 引擎同口径，可作为公平预算轴。
* C0 的账本另附**真实但口径不同**的代理观测 `d56_index_evaluate_calls_proxy`（`d56.index.D56Index.evaluate` 实际调用次数），仅作信息记录；G4 引擎的 `d56_candidate_evals` 采用"每次 `plan_candidates` 记账 `d56_top`"的记账口径，两者不可直接比较，**不用于公平预算结论**。
* 因此 C0 与 G4 各臂的可比预算轴为：`route_3d_checks`（同口径真实计数）、墙钟耗时、Validator 次数、有效候选数；`d56_candidate_evals` 维度对 C0 不可比。

## 4. 公平性说明

1. **同起点**：见 §1 的起点 SHA256 列；每臂 `config.json` 记录`start_dir` / `start_sha256` / `seed` / `budget`（实际值）。
2. **同预算**：每臂同时受 `route_3d_checks`、`d56_candidate_evals` 上限与真实墙钟约束；报告的是**实际用量**（§3），不是迭代次数。
3. **实际耗时**：§1/§3 报告搜索墙钟；进程总耗时/Validator 耗时见 §1 与`experiment_matrix.csv` 的附加列。
4. **World 检测次数 / Validator 次数 / 有效候选数**：均在 §3 真实报告。Validator 以**独立子进程**运行冻结 `validate_xyz`，`manual_policy=fully_optimizable`，每臂至少 1 次；`validation/validation.json` 的 `routes_file_sha256` 必须等于该臂 `best_valid/routes_l3d.json` 的 SHA256，否则标记 `validation_stale`。
5. **负结果如实报告**：未达到 1200/1000 等挑战目标时不做粉饰，保留最低交叉数与瓶颈分析（见 10_reports/）。
6. **墙钟/账本口径提示**：G4d A 类臂经历一次进程中断后 `--resume` 完成，其账本 `wall_seconds`（106.3s）只覆盖恢复后的最后一段搜索，不是全部墙钟；A 类比较以**计数预算**为主公平轴，墙钟差异如实列出、并注明该恢复情况（不补造未记录的耗时）。
7. **排除的非正式目录**：`_debug*`、`_probe`、`_aborted*`、`_lead_explore*`、`arm_probe*`、`arm_timing` 等不作为正式臂；E1/E2/E1b 仅作为 exploratory 行引用其 best_valid（无独立 validation 的标 `not_run`）。

### 4.1 独立验收一致性核查

| 臂 | validation_pass | 违规数 | validation SHA 与 best_valid 一致 | Validator | validation 耗时(s) | 复核交叉差（validation − 复算） | crossing_stats 与复算差 | 状态 |
|---|---|---|---|---|---|---|---|---|
| C0 | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 26.8 | 0 | 0 | complete |
| G4a | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 24.7 | 0 | 0 | complete |
| G4b | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 25.2 | 0 | 0 | complete |
| G4c_frozen | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 24.7 | 0 | 0 | complete |
| G4c_free | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 24.9 | 0 | 0 | complete |
| G4d | True | 0 | True | four_side_1024.fanout1024.xyzrouter.validate_xyz | 23.8 | 0 | 0 | complete |

## 5. 逐高度交叉分布摘要

完整 21 个物理高度（19 body + 2 interface）× 各臂的交叉分布见 `metrics.csv`（tidy 格式：`row_type=plane`，`metric=crossings/crossing_pairs/routes`）。下表给出各臂"交叉最集中的前 5 个高度"。

* **C0**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L9(z=0.1): 109 交叉/107 对/55 线路；L17(z=0.55): 107 交叉/102 对/52 线路；L14(z=0.35): 99 交叉/99 对/48 线路；L18(z=0.6): 92 交叉/92 对/47 线路
* **G4a**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L9(z=0.1): 109 交叉/107 对/55 线路；L17(z=0.55): 109 交叉/103 对/53 线路；L14(z=0.35): 99 交叉/99 对/48 线路；L6(z=-0.15): 96 交叉/93 对/58 线路
* **G4b**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L17(z=0.55): 109 交叉/103 对/53 线路；L9(z=0.1): 107 交叉/106 对/54 线路；L14(z=0.35): 105 交叉/102 对/49 线路；L6(z=-0.15): 96 交叉/93 对/58 线路
* **G4c_frozen**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L9(z=0.1): 109 交叉/107 对/55 线路；L6(z=-0.15): 88 交叉/85 对/56 线路；Z1_INTERFACE(z=0): 82 交叉/77 对/512 线路；L17(z=0.55): 82 交叉/76 对/51 线路
* **G4c_free**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L9(z=0.1): 109 交叉/107 对/55 线路；L6(z=-0.15): 88 交叉/85 对/57 线路；Z1_INTERFACE(z=0): 82 交叉/77 对/512 线路；L14(z=0.35): 81 交叉/81 对/47 线路
* **G4d**（来源：routes_l3d.json 复算）：Z2_INTERFACE(z=0.5): 130 交叉/126 对/512 线路；L9(z=0.1): 107 交叉/106 对/54 线路；L6(z=-0.15): 88 交叉/85 对/57 线路；Z1_INTERFACE(z=0): 82 交叉/77 对/512 线路；L17(z=0.55): 82 交叉/76 对/51 线路

## 6. 逐步优化链（08_progressive_chain）

| 环节 | 来源臂/检查点 | 本段起点交叉 | 本段终点交叉 | 本段增量收益 | 本段预算 | 本段实际耗时(s) | 种子 | 终点 SHA256 |
|---|---|---|---|---|---|---|---|---|
| G3 公共起点 | G3 | 1322 | 1322 | 0 | {'route_3d_checks': 0, 'd56_candidate_evals': 0, 'wall_seconds': 0.0} | 0.0 | 20261104 | 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 |
| best(G4a, G4b) 检查点 | G4b | 1322 | 1294 | -28 | {'route_3d_checks': 30000, 'd56_candidate_evals': 120000, 'wall_seconds': 1200.0} | 1099.8 | 20261104 | c72b245a240fce27dc7e1b8d41d0b432e1986d133c9c90051d097949f40a91c1 |
| 链段 G4c 重跑（从 link1 1294 起） | G4c_free | 1294 | 1204 | -90 | {'route_3d_checks': 30000, 'd56_candidate_evals': 120000, 'wall_seconds': 700.0} | 740.5 | 20261104 | 252bbfd2c712e59e6337d6ce531f63bfcca45bf68ae585bc7be24fed33c9aef3 |
| 最佳 G4c 检查点（来自 A 类 G4c_free 臂） | G4c_free | 1294 | 1189 | -105 | {} | 0.0 | 20261104 | ce7ca9a9210a5206db9753294d3e0d1dea88c0ec892a13de512fecb16c0e390e |
| 链段 G4d（从 1189 最佳 G4c 检查点起） | G4d | 1189 | 1185 | -4 | {'route_3d_checks': 30000, 'd56_candidate_evals': 120000, 'wall_seconds': 1200.0} | 1230.0 | 20261104 | a0bf4c705014ce33c08ab908bf41991c9c65fb51a46e1016faa3d9af3634110e |
| G4d warm-start（06b，seed 20261105，B 类平行探索） | G4d_warm | 1189 | 1189 | 0 | {} | 0.0 | 20261105 | ce7ca9a9210a5206db9753294d3e0d1dea88c0ec892a13de512fecb16c0e390e |

注意：链的**累计收益 = 各段增量收益之和**，不得把链的累计收益全部归因于最后一个算法；每段收益只归因于该段所用臂/检查点起点。

逐步优化链属 **B 类（继承链）补充结果**，其起点是上一链段的最佳合法检查点，**不与 A 类"同起点同预算独立对照"混在一起归因**；A 类对照见 §1/§2/§3。链每段预算按链段实际配置记录（G4c 链段 700s、G4d 链段 1000/1200s，与正式臂预算不同，已逐段注明）。

链中采用 SPEC B 类允许的"继承最佳合法检查点"：`02b` 链段的 **1189 来自 A 类正式臂 G4c_free 的 best_valid**，不是链段重跑值；链段重跑值（1204）保留在 `02_link_G4c` 作对照。`06b`（`06b_G4d_warm_from_1189`）是 g4-core 用 seed 20261105 的平行 B 类 warm-start 探索；两条不同 seed 的 B 类探索最终取最优合法者，均如实列出。`experiment_matrix.csv` 中 B 类行为 `chain_link2 / chain_link2b / chain_link3 / chain_link06b`（`class=B_chain`），不与 A 类混算。

## 7. 数据来源与缺失字段说明

* `experiment_matrix.csv`：A 类同起点臂（`class=A_independent`，6 行）+ B 类链段行（`class=B_chain`：chain_link1/chain_link2/chain_link2b/chain_link3/chain_link06b）+ exploratory 行（`class=exploratory`：E1/E2/E1b），每行按 SPEC 字段 + 诊断附加列（`status`、`crossing_source`、`validation_sha_match`、复算差等）。B 类/exploratory 单独标注，**不参与 A 类同起点对照的归因**。
* `budget_ledger.csv`：每臂 × 每计数器一行（长表），`kind=used/cap/utilization_pct/proxy`，含 C0 的 `null` 说明行。
* `metrics.csv`：21 个物理高度 × 各臂列（tidy 长表，`row_type=plane` 为逐高度分布，`row_type=global` 为全局指标）；A 类 6 臂列 + B 类/exploratory 列均已标注。
* 缺失/不可观测一律 `NA`（数值）或 `null`（明确不可观测的计数器），并在本文件说明原因，不做任何估算。

### 7.1 各臂状态

* `C0`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\01_arm_C0`
* `G4a`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\02_arm_G4a`
* `G4b`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\03_arm_G4b`
* `G4c_frozen`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\04_arm_G4c_frozen`
* `G4c_free`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\05_arm_G4c_free`
* `G4d`：complete；目录 `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\experiments\xyz_joint_g4_1024\06_arm_G4d`


## 8. 终版注记（Lead 要求补充）

1. **G4d A 类臂（06_arm_G4d）因外部误杀分两次 session 运行**：session1 运行 1242.7s 到 1212（中途被外部误杀，best_valid=1212 来自 checkpoint step_00023），session2 用 --resume 运行 111.6s 补完 stage 64/96 并跑独立 Validator；因此矩阵/账本中的 wall_seconds=106.3s **仅为 session2（恢复段）**，**总搜索墙钟 ≈ 1354s**（1242.7+111.6）；其 ledger 
oute_3d_checks=4400、d56_candidate_evals=35815 为**含 checkpoint 恢复的累计值**。A 类公平比较以**计数预算**为主公平轴，墙钟差异如实列出、不补造未记录耗时。
2. **exploratory 起点/关系**：E2 起点为 E1 的 1201 快照（_lead_explore_migrate2/start_1201）；E1b 为 E2 的继续探索（_lead_explore_direct）。E1/E2/E1b 均为 exploratory（非正式臂），无独立 validation 的如实标 
ot_run，**不计入 A 类对照**。
3. **文件重跑说明**：本文件与 experiment_matrix.csv 于 2026-11-04 20:01 由 g4-runner 重跑（同 15 行；修正 exploratory 起点字段：E2 start_crossings 由 NA→1201、E1b 由 NA→1226，其余数值不变）。MANIFEST 需按当前文件 SHA256 重算。

<!-- g4-report-notes -->
## 后记（g4-report 补充注记，不改动上述 G4-4 原始内容）

1. **G4d A 类臂计时**：该臂因外部误杀分两次 session 运行（1242.7 s + 111.6 s
   ≈ **1354 s** 搜索墙钟）；本文件与 `budget_ledger.json` 中的 wall 字段为
   session 2 的值，不能当作该臂总搜索时间。报告中预算表已并列 `run.log` 实测。
2. **E1/E2/E1b 为 exploratory，非正式臂**：起点分别为 G3（1322）与
   1200–1201 的链检查点，不计入任何正式臂的收益或公平对照；仅说明“精确高度
   重分配”这一自由度有潜力，需下一轮形式化为正式臂。
3. 2026-11-04 20:08:44 由 `g4/report_g4.py` 追加；G4-4 原始内容与数据未修改。
