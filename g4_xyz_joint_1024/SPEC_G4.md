# G4 — 人工 U 动态重分组与大邻域 XY+Z 联合三维重布（SPEC / 写入契约）

本文件是本轮 G4 实验的**唯一契约**。所有 teammate 的代码与产物必须遵守；接口改动先改本文件。

## 0. 目标（来自任务书）

在**不降低任何物理约束、不删连接、不改交叉口径**的前提下，从核验过的 G3 最佳合法解
（1024/1024，同层真实交叉 **1322**，唯一交叉对 1253，368 条人工 U，Rmin=15mm）出发：

| 实验 | 内容 | 目标 |
|---|---|---|
| **G4a** | 保留原八组与成员归属，**重新设计整组 XY+Z**（组主体高度可换、组内 XY 走廊重造） | 证明 XY 投影真实变化、组级迁移成功率 |
| **G4b** | 取消八组固定成员，**人工 U 动态重分组**（单条迁移/交换/拆分/重组 + 全几何重造） | 真实分组变化 + 几何变化 |
| **G4c** | **人工 U 与阻挡线路联合让路**（多线路事务、邻域 8/16/32/64、ALNS/Ruin-Recreate/Beam） | 突破单线局部重布瓶颈 |
| **G4d** | **全部 1024 条线路**参与的大邻域全局优化（动态高冲突子图、多重建顺序、多随机种子） | 继续压低交叉 |

挑战目标：1322 → 1200 → 1000 → 800 → 500 → 100 → 0–9。达不到目标必须如实报告负结果。

## 1. 不可改变的不变量（任何候选/最终解）

* 玻璃 150×150×1 mm；玻璃 z ∈ [−0.35, +0.65]；Z1 接口 z=0，Z2 接口 z=0.5。
* 1024 条连接完整；route_id / 端口身份 / 连接关系 / plane / source/target 身份不可变。
* 21 个物理高度（19 body + 2 interface），相邻间距 ≥0.05 mm；flat z 必须是模型高度。
* Rmin = 15 mm：所有圆弧恰为 R15，真 3D 采样曲率 ≥ 1/15。
* 同层严格 D56（0.05 波导宽 + 0.03 边距 = 0.08 mm 中心线；合法横向交叉按 strict 口径豁免）。
* 不同物理高度/transition 的真 3D 中心线净空 ≥ 0.05 mm。
* 不允许瞬间跳层；每条路线必须由 line / R15 arc / R15 双弧 S 过渡原语精确组装。
* **禁止**修改 Validator / World / D56 代码、提高容差、改变交叉统计口径、删减连接。
* 任何非法几何不得进入 `best_valid/`。
* 保留 G3 原始合法解（`outputs/.../XYZ_JOINT_G123_1024/best_valid/`）绝不覆盖。

## 2. 共同起点（只读）

```
outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/best_valid/
    routes_l3d.json  SHA256 = 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077
    1322 crossings / 1253 pairs / 1024 routed
```

身份/人工 U 合同校验用权威 2409 基线（只读）：
`outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/baseline_authoritative/`。

## 3. 共享引擎（Lead 提供，禁止修改）

包：`four_side_1024/fanout1024/xyzrouter/g4/`

| 文件 | 作用 |
|---|---|
| `paths.py` | 归档根 `experiments/xyz_joint_g4_1024/`、起终点、臂目录、种子、预算、`load_start()`、JSON/CSV/SHA IO |
| `ledger.py` | `Ledger`：`route_3d_checks / d56_candidate_evals / transactions / world_builds / valid_candidates / rejected_3d / accepted_transactions / accepted_changes / gain / validator_runs / rolled_back / wall_seconds` |
| `joint_world.py` | `JointWorld`（候选生成 `plan_candidates/plan_forced/plan_best`、真 3D World 增量维护、`replace_one`、`maybe_rebuild_world`、crossing 冲突图）；`Transaction`（`rip`/`plan`/`place`/`finish`/`abort`，整组一次性精确验收或整体回滚） |
| `artifacts.py` | `flush()` 标准产物、`lightweight_snapshot()`、`BestTracker`、`write_ledger/history/config`、`run_validation()`（子进程跑独立 Validator） |
| `arm_base.py` | `ArmSpec`/`ArmContext`（统一起点加载、检查点保存/恢复、final 保存）、`manual_route_ids/manual_groups/group_height_map/height_label` |

**新算法必须使用这些接口**，以保证预算计数与验收口径一致、并可直接横向比较。

### 3.1 联合事务用法（G4c/G4d/组级重布的核心）

```python
jw = JW.JointWorld(state, ledger=ctx.ledger, log=ctx.log)
tx = jw.transaction(rids, note='make_way', min_gain=1)
tx.rip_all()                       # 全部线路从 state + 真 3D World 撤出
for rid in order:                  # 顺序重规划；后面的看到前面已放置的新几何
    cands = tx.plan(rid, cfg)      # 自由高度；或 tx.plan(rid, forced=(layer, z))
    if not cands: tx.abort('no_candidate'); break
    tx.place(rid, cands[0])
result = tx.finish()               # 精确重算受影响高度；gain>=min_gain 才整体接受
# result: accepted / old_total / total / delta / gain / per_plane / reasons
```
* 失败/无收益**整体回滚**（`abort` 或 `finish` 内部回滚），状态与真 3D World 精确恢复（已用 smoke test 验证）。
* 事务内候选的 3D 检查针对“当前事务状态”的真 3D World（非旧几何）。
* `min_gain` 是本事务要求的交叉下降量；不接受“合法但无改善”的事务进入主搜索接受流（可记为 failure reason）。

### 3.2 预算与记账（公平实验核心）

* 每个臂从**同一 G3 起点、同一 seed=20261104** 出发。
* 预算同时约束 `route_3d_checks`、`d56_candidate_evals`（见 `paths.DEFAULT_BUDGET`/`ARM_BUDGETS`）与真实墙钟；臂结束必须写 `budget_ledger.json` 并报告。
* 计数必须由共享引擎真实统计（禁止伪造/估算）；C0 若无法统计 D56 候选数，必须显式写 `null` + 说明。
* 禁止用“同迭代数”冒充同预算。

## 4. 各臂语义（必须精确实现）

| 臂 | 可动线路集合 | 高度自由度 | XY 自由度 | 搜索机制 |
|---|---|---|---|---|
| **C0** | 全部 1024（沿用 G3 引擎） | 单线迁移 | 单线走廊重造 | 既有 `optimizer.Optimizer` 继续跑（不新增自由度） |
| **G4a** | 368 人工 U（分组固定）+ 允许的非人工 | 每组统一主体高度可换 | 组内 XY 全重造、R15 圆弧/引线/过渡可变、同组多线联合 | 组级事务 + 组高度枚举 |
| **G4b** | 368 人工 U | 单条迁移/2–3 条交换/拆分/不同旧组同高度重组 | 全重造 | 动态分组事务/交换邻域 |
| **G4c-frozen** | 非人工线路；**人工 U 完全冻结**（不可作目标、不可被让路移动） | 非人工线路可迁移 | 全重造 | 联合让路 ALNS（含阻挡者）+ 邻域 8/16/32/64 |
| **G4c-free** | 全部（人工 U 可作目标/阻挡者） | 同上 | 同上 | 同上 |
| **G4d** | 全部 1024 | 全部 | 全部 | 全局大邻域 ALNS / Ruin-Recreate，动态高冲突子图，多重建顺序，多 seed 重启 |

注意：G4a 的“分组固定”= 原 `manual_group` 成员集合不变且同组仍共享一个主体高度；允许组内个别线路因几何不可行而留在原高度（必须记录失败原因）。
G4b 的“新分组”必须由**真实主体高度 + 几何**体现，不能只改 `manual_group` 标签；报告需给出原组→新高度/新族群的迁移矩阵。
G4c/G4d 中“人工 U 解冻”仅指几何/高度可动；route_id/端口/连接/`manual_group` 标签仍保留（标签用于统计，不限制几何）。

## 5. 邻域与搜索（G4c/G4d 最低要求）

* 构建 **交叉冲突图**（真实 crossing events，`joint_world.crossing_graph`）与 **三维阻挡图**：
  目标高度占用者（同高度 body 路线）+ 端点过渡区阻挡者（transition 与候选端点走廊冲突）。
* 邻域规模 **8/16/32/64 全部测试**（每种至少一个 stage，记录各自收益/成功率/耗时）。
* 至少实现一种：Adaptive LNS（破坏-重建）/ Beam Search over orders / Ruin-and-Recreate。
* 顺序敏感：同一邻域至少尝试 2 种重建顺序（例如“先目标后阻挡者”“先阻挡者后目标”“按交叉数降序”）。
* 可复现：`random.Random(seed + stage)`；记录每个接受的 `(rids, order, min_gain)`。
* 检查点：每 10 分钟或每 50 次接受保存一次；支持 `--resume` 从中断继续。
* best_valid 只在 `state.total` 严格下降且事务已整组验收后更新。

## 6. 失败原因分类（所有臂统一字符串键）

`no_legal_xy_corridor` / `target_height_occupied` / `r15_geometry_rejected` / `transition_3d_conflict` /
`lead_below_minimum` / `joint_rebuild_failed` / `legal_but_no_crossing_improvement` / `budget_exhausted`
（另可加 `no_current_crossings`、`structure_error`）。所有失败尝试进 `failed_attempts.json`（最多 2000 条）。

## 7. 独立验收协议

* 每臂结束（或阶段性最佳）必须用**独立进程**跑冻结 Validator：
  `python -m four_side_1024.fanout1024.xyzrouter.validate_xyz --run-dir <arm>/best_valid --out-dir <arm>/validation --manual-policy fully_optimizable --baseline-dir <baseline_authoritative>`
  → `validation_pass=True, violations=0` 才可称“合法”。
* 最终 best_valid 再跑一次全量 validator + 与 G3 起点的逐 route 几何 diff + 交叉口径复算（`nonc4.crossings`），三份独立证据。
* 报告中必须写清：哪些结论来自真实接受解，哪些只是探索性观察。

## 8. 产物与归档

所有正式实验归档到 `experiments/xyz_joint_g4_1024/`：

```
SPEC_G4.md                    本文件
00_baseline_audit/            几何口径核查 + G3 独立复核（G4-1）
01_arm_C0/ 02_arm_G4a/ 03_arm_G4b/ 04_arm_G4c_frozen/ 05_arm_G4c_free/ 06_arm_G4d/
     routes_l3d.json  assignment_1024.csv  crossing_stats.json  summary.json
     validation/validation.json  SHA256.json  optimization_history.csv
     strategy_stats.json  failed_attempts.json  config.json  budget_ledger.json
     best_valid/  checkpoints/  run.log
07_best_valid/                最终最佳合法解（另存）
08_progressive_chain/         G3→G4a/b→G4c→G4d 链（best checkpoint 继承 + 分阶段收益）
budget_ledger.csv experiment_matrix.csv metrics.csv fair_comparison.md
09_plots/                     21 层逐层图/拼图/对照/迁移图/预算曲线（G4-5）
10_reports/                   report.md comparison.md failure_analysis.md answers.md
code/                         g4 代码快照
MANIFEST.json                 全部文件 SHA256 + 字节数
```

## 9. 写入范围（避免冲突）

| 文件 | Owner |
|---|---|
| `g4/{__init__,paths,ledger,joint_world,artifacts,arm_base}.py`、`SPEC_G4.md` | Lead |
| `g4/{neighborhood,make_way,alns,run_g4c,run_g4d,run_g4_engine}.py` | G4-2（g4-core） |
| `g4/{group_replan,run_g4a,run_g4b}.py` | G4-3（g4-group） |
| `g4/{fair_runner,c0_continue,metrics_collect}.py` | G4-4（g4-runner） |
| `g4/{plots_g4,report_g4,archive_g4,failure_analysis}.py` | G4-5（g4-report） |
| `g4/{contract_audit,independent_metrics}.py` | G4-1（geometry-auditor） |

## 10. 记录要求

* 每个臂写 `run.log`（带时间戳的真实日志）、`strategy_stats.json`（各 stage 的接受/失败原因/邻域规模/顺序）、`budget_ledger.json`。
* 交叉数下降曲线按“真实 route_3d_checks / wall time”两个横轴都记录（G4-5 画图）。
* 负结果必须保留：达不到 1200/1000 时如实报告最低交叉与瓶颈分析。
