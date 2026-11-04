# G4 失败原因分析（SPEC_G4.md 第 6 节 8+ 类）

- 生成时间: 2026-11-04 19:50:38
- 归档根: `experiments\xyz_joint_g4_1024`
- 数据来源: 各臂 `failed_attempts.json` / `strategy_stats.json` / `budget_ledger.json` / `config.json` （全部来自真实臂产物，未使用搜索中间候选图）
- 结论口径: **所有失败分类都是“搜索侧未找到/未接受”，不是“严格证明无解”**；本报告不做下界证明，也不声称任何目标不可达。

## 1. 数据源与可用性

| 臂 | 状态 | 失败尝试数 | 尝试原因合计 | strategy 原因合计 | 合并口径合计 | ok（非失败） | budget_ledger | 说明 |
|---|---|---|---|---|---|---|---|---|
| `C0` | 已产出 | 0 | 0 | 5302 | 5302 | 0 | 有 | C0 既有引擎续跑（无新自由度的公平对照） |
| `G4a` | 已产出 | 69 | 69 | 215 | 215 | 29 | 有 | G4a 原八组固定成员、组级 XY+Z 重造 |
| `G4b` | 已产出 | 309 | 309 | 850 | 850 | 11 | 有 | G4b 人工 U 动态重分组 |
| `G4c_frozen` | 已产出 | 835 | 835 | 872 | 872 | 0 | 有 | G4c-frozen 人工 U 冻结、非人工线路联合让路 ALNS |
| `G4c_free` | 已产出 | 818 | 818 | 850 | 850 | 0 | 有 | G4c-free 人工 U 解冻（可作目标/阻挡者） |
| `G4d` | 已产出 | 2 | 2 | 2 | 2 | 0 | 有 | G4d 全部 1024 条大邻域全局优化 |
| `best_valid` | 已产出 | 0 | 0 | 0 | 0 | 0 | 无 | best_valid |
| `chain/02_link_G4c` | 已产出 | 173 | 173 | 186 | 186 | 0 | 有 | chain |
| `chain/03_link_G4d` | 已产出 | 318 | 318 | 349 | 349 | 0 | 有 | chain |

计数口径：同一失败尝试可能同时出现在 `failed_attempts.json`（逐条，最多 2000 条）与 `strategy_stats.json` 的原因直方图中；本报告对**每个大类取两来源的 max 值**（`max(per-attempt, per-strategy-histogram)`），避免重复计数，并保留两列原始合计。`ok` 记录表示“尝试未失败”（臂为完整性写入），**不计入失败分类**。

## 2. 失败原因分类（SPEC 第 6 节定义）

| 原因 key | 定义 | 本轮计数 | 性质 |
|---|---|---|---|
| `no_legal_xy_corridor` | 目标高度上找不到满足严格 D56 / R15 / 引线约束的平面 XY 路径 | 1563 | 搜索侧未找到（不构成无解证明） |
| `target_height_occupied` | 目标物理高度已被其它 body 线路占用（同高度 D56 无法放置） | 60 | 搜索侧未找到（不构成无解证明） |
| `r15_geometry_rejected` | R15 几何原语无法组装（圆弧 / 双弧 S 过渡 / 引线几何被拒） | 0 | 搜索侧未找到（不构成无解证明） |
| `transition_3d_conflict` | 三维 S 过渡与其它层线路 / 过渡的 3D 中心线净空 < 0.05 mm | 364 | 搜索侧未找到（不构成无解证明） |
| `lead_below_minimum` | 端口引线长度低于下限，路线几何不可用 | 0 | 搜索侧未找到（不构成无解证明） |
| `joint_rebuild_failed` | 联合事务（多线 rip+plan+place）无法全体同时合法，整体回滚 | 166 | 搜索侧未找到（不构成无解证明） |
| `legal_but_no_crossing_improvement` | 候选几何合法但没有降低同层交叉（不满足 min_gain，拒绝进入接受流） | 5491 | 合法但无收益（搜索接受流拒绝） |
| `budget_exhausted` | 达到 route_3d_checks / d56_candidate_evals / 墙钟预算上限而停止 | 2 | 预算界（终止条件，不等于无解） |
| `no_current_crossings` | 目标线路当前没有交叉，无需优化 | 958 | 搜索侧未找到（不构成无解证明） |
| `structure_error` | 状态 / 接口 / 数据结构异常导致尝试失败 | 0 | 搜索侧未找到（不构成无解证明） |
| `unclassified` | 未归类的失败原因（保留原始 key，不丢弃） | 22 | 待归类 |

合计失败计数：**8626**（其中未归类 22）

## 3. 分臂 × 原因计数

| 臂 | `no_legal_xy_corridor` | `target_height_occupied` | `transition_3d_conflict` | `joint_rebuild_failed` | `legal_but_no_crossing_improvement` | `budget_exhausted` | `no_current_crossings` | `unclassified` | 合计 |
|---|---|---|---|---|---|---|---|---|---|
| C0 | 1160 | 0 | 236 | 0 | 3022 | 2 | 878 | 4 | 5302 |
| G4a | 45 | 6 | 20 | 56 | 88 | 0 | 0 | 0 | 215 |
| G4b | 234 | 0 | 108 | 110 | 398 | 0 | 0 | 0 | 850 |
| G4c_frozen | 34 | 16 | 0 | 0 | 785 | 0 | 27 | 10 | 872 |
| G4c_free | 34 | 16 | 0 | 0 | 775 | 0 | 19 | 6 | 850 |
| G4d | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 |
| best_valid | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| chain/02_link_G4c | 18 | 5 | 0 | 0 | 155 | 0 | 8 | 0 | 186 |
| chain/03_link_G4d | 38 | 17 | 0 | 0 | 266 | 0 | 26 | 2 | 349 |

## 4. “算法找不到解” vs “严格证明无解”

| 判据 | 本轮证据 |
|---|---|
| 算法在预算内找不到合法/更优候选 | **是**（上表全部计数）|
| 严格无解证明（下界 / 穷举覆盖）| **否**：无任何下界证明，不声称不可达 |
| 是否可断言“该目标在更长时间下也无解” | **否**：预算耗尽（`budget_exhausted`）只说明本轮预算边界 |

因此任何“达不到目标”的表述必须写成：*在给定共享引擎、算法族与预算下未达到*，而不是“无解”。

## 5. 预算耗尽证据（budget_ledger 真实计数）

| 臂 | route_3d_checks | d56_candidate_evals | wall_seconds | 预算上限 | 是否触顶 |
|---|---|---|---|---|---|
| C0 | 2324 | None | 1208.76 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1200.0 | 是（wall_seconds） |
| G4a | 6208 | 43004 | 1018.74 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1200.0 | 否 |
| G4b | 1538 | 11552 | 1099.82 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1200.0 | 否 |
| G4c_frozen | 7106 | 64342 | 1847.02 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1800.0 | 是（wall_seconds） |
| G4c_free | 6851 | 63433 | 1840.36 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1800.0 | 是（wall_seconds） |
| G4d | 4400 | 35815 | 106.3 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1200.0 | 否 |
| chain/02_link_G4c | 2136 | 17436 | 740.52 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=700.0 | 是（wall_seconds） |
| chain/03_link_G4d | 4915 | 34893 | 1229.96 | route_3d_checks=30000, d56_candidate_evals=120000, wall_seconds=1200.0 | 是（wall_seconds） |

## 6. 解读（负结果如实保留）

按计数排序的失败主因：
- `legal_but_no_crossing_improvement`（候选几何合法但没有降低同层交叉（不满足 min_gain，拒绝进入接受流））：5491 次
- `no_legal_xy_corridor`（目标高度上找不到满足严格 D56 / R15 / 引线约束的平面 XY 路径）：1563 次
- `no_current_crossings`（目标线路当前没有交叉，无需优化）：958 次
- `transition_3d_conflict`（三维 S 过渡与其它层线路 / 过渡的 3D 中心线净空 < 0.05 mm）：364 次
- `joint_rebuild_failed`（联合事务（多线 rip+plan+place）无法全体同时合法，整体回滚）：166 次
- `target_height_occupied`（目标物理高度已被其它 body 线路占用（同高度 D56 无法放置））：60 次
- `unclassified`（未归类的失败原因（保留原始 key，不丢弃））：22 次
- `budget_exhausted`（达到 route_3d_checks / d56_candidate_evals / 墙钟预算上限而停止）：2 次

## 7. 后续需要的数据（若某类计数为 0）

- 臂结束后确认 `failed_attempts.json` 的 `count` 与 `strategy_stats.json` 的 `reasons` 均已写入；
- 若 `strategy_stats.json` 使用自定义 reason key，需在 `failure_analysis.py` 的 `ALIASES` 中补充映射（当前未归类计数会保留在 `unclassified`，不会丢失数据）。
