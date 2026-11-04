# 逐步优化链（G3 → best(G4a,G4b) → G4c → G4d）

> 由 `g4/fair_runner.py` 从真实检查点构建，生成于 2026-11-04T20:05:03。
> 共同起点：G3 合法最优解，SHA256 = `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`，交叉 = 1322；seed = 20261104。

## 链段收益表

| 环节 | 本段来源臂 | 本段起点交叉 | 本段终点交叉 | 本段增量收益 | 本段预算 | 本段实际耗时(s) | seed | 终点 SHA256 | 独立验收 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| G3 公共起点 | G3 | 1322 | 1322 | 0 | {"route_3d_checks": 0, "d56_candidate_evals": 0, "wall_seconds": 0.0} | 0.0 | 20261104 | 711cf910d5c75ea7… | None | ok |
| best(G4a, G4b) 检查点 | G4b | 1322 | 1294 | -28 | {"route_3d_checks": 30000, "d56_candidate_evals": 120000, "wall_seconds": 1200.0} | 1099.82 | 20261104 | c72b245a240fce27… | True | ok |
| 链段 G4c 重跑（从 link1 1294 起） | G4c_free | 1294 | 1204 | -90 | {"route_3d_checks": 30000, "d56_candidate_evals": 120000, "wall_seconds": 700.0} | 740.52 | 20261104 | 252bbfd2c712e59e… | True | ok |
| 最佳 G4c 检查点（来自 A 类 G4c_free 臂） | G4c_free | 1294 | 1189 | -105 | NA | 0.0 | 20261104 | ce7ca9a9210a5206… | True | ok |
| 链段 G4d（从 1189 最佳 G4c 检查点起） | G4d | 1189 | 1185 | -4 | {"route_3d_checks": 30000, "d56_candidate_evals": 120000, "wall_seconds": 1200.0} | 1229.96 | 20261104 | a0bf4c705014ce33… | True | ok |
| G4d warm-start（06b，seed 20261105，B 类平行探索） | G4d_warm | 1189 | 1189 | 0 | NA | 0.0 | 20261105 | ce7ca9a9210a5206… | True | ok |

## 归因规则与说明

链的累计收益 = 各段增量收益之和；每段收益只归因于该段所用的臂/检查点起点，不得把链的累计收益全部归因于最后一个算法。pending 环节表示该链段尚未真实运行，不得估算或补造。

* **G3 公共起点**（G3，ok）：所有臂与链的共同起点（已核验 G3 合法最优解，交叉 1322）
* **best(G4a, G4b) 检查点**（G4b，ok）：按独立验收的交叉数选择 G4a/G4b 中更优者作为 G4c 起点
* **链段 G4c 重跑（从 link1 1294 起）**（G4c_free，ok）：从上一链段最佳合法检查点继承的真实运行结果
* **最佳 G4c 检查点（来自 A 类 G4c_free 臂）**（G4c_free，ok）：继承"最佳合法检查点"（SPEC B 类允许）：该 1189 检查点来自 A 类正式臂 G4c_free 的 best_valid（routes/assignment/validation 已复制），不是链段重跑值；链段重跑值见上一链段（仅作对照）。本段不消耗链段搜索预算（0s），其收益 −105 的因果归属注明为"来自 A 类 G4c_free 臂 + link1 起点"。
* **链段 G4d（从 1189 最佳 G4c 检查点起）**（G4d，ok）：从上一链段最佳合法检查点继承的真实运行结果
* **G4d warm-start（06b，seed 20261105，B 类平行探索）**（G4d_warm，ok）：B 类平行 warm-start 探索（与 link3 使用不同 seed=20261105），两条不同 seed 的 B 类探索最终取最优合法者；其起点为 1189（G4c_free best_valid）。

