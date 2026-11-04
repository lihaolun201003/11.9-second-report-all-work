# G4 实验归档：人工 U 动态重分组与大邻域 XY+Z 联合三维重布（1024 通道）

本目录是 **G4 实验**的公开交付集（报告 / 证据 / 最终解 / 逐层图 / 代码 / 校验），
是本地完整归档 `experiments/xyz_joint_g4_1024/`（850 文件 / 274.8 MB / SHA256 全量清单）
的可读子集。本地完整归档的 SHA256 清单见 [`LOCAL_FULL_ARCHIVE_MANIFEST.json`](LOCAL_FULL_ARCHIVE_MANIFEST.json)；
本目录实际包含文件的 SHA256 清单见 [`MANIFEST_REPO.json`](MANIFEST_REPO.json)。

## 一、结论速览

| 必答项 | 结论 |
|---|---|
| 1024/1024 是否保持 | **是**：1024 条全部布通、0 failed，端口/连接/身份独立复核 0 错配 |
| 几何是否合法 | **是**：冻结独立 Validator `PASS`（violations=0，SHA 匹配）+ 独立 `FINAL_AUDIT` 16/16 检查全过 |
| 最低交叉 | **1185**（唯一交叉对 **1124**）；G3 起点 1322/1253 → **−137 / −10.4%**；相对冻结 pre-G4 基线 2409/2010 → **−1224 / −50.8%** |
| 挑战目标 | ≤1200 达成；≤1000 / ≤800 / ≤500 / ≤100 / ≤9 / 0 **未达成**（如实报告） |

最终解：[`03_best_valid/`](03_best_valid/)（routes SHA256 `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`，
来源 B 类链 link3，从 A 类最佳 G4c-free 1189 继承再 −4）。

## 二、实验矩阵（全部独立 Validator PASS）

| 实验 | 起点→终点交叉 | Δ | 唯一对 |
|---|---|---|---|
| G3 起点（只读） | 1322 | 0 | 1253 |
| C0 既有引擎续跑（无新自由度） | 1322→1259 | −63 | 1209 |
| G4a 固定八组 + 组级 XY+Z 重造 | 1322→1320 | −2 | 1252 |
| G4b 人工 U 动态重分组 | 1322→1294 | −28 | 1234 |
| G4c-frozen 人工 U 冻结 + 联合让路 | 1322→1222 | −100 | 1149 |
| **G4c-free 人工 U 解冻 + 联合让路** | 1322→**1189** | −133 | 1128 |
| G4d 全 1024 条大邻域全局优化 | 1322→1212 | −110 | 1148 |
| **B 类最终 best（链 link3）** | 1189→**1185** | −4 | 1124 |

详表：[`experiment_matrix.csv`](experiment_matrix.csv)、[`budget_ledger.csv`](budget_ledger.csv)、
[`metrics.csv`](metrics.csv)、[`fair_comparison.md`](fair_comparison.md)。

## 三、目录结构

```
g4_xyz_joint_1024/
├── README.md                        本文件
├── SPEC_G4.md                       G4 实验契约（不变量/预算/验收/产物）
├── report.md                        最终实验报告（结论/矩阵/六问/失败分析/逐层统计）
├── fair_comparison.md               公平对照报告（预算账本/归因说明）
├── experiment_matrix.csv            实验矩阵（15 行：A 类/B 类链/exploratory/final）
├── budget_ledger.csv                预算账本长表（真实计数，C0 d56=null 说明）
├── metrics.csv                      21 物理高度 × 各臂交叉分布
├── 01_reports/                      comparison / answers / failure_analysis / metrics_summary
├── 02_tables/                       公平对照与逐层统计
├── 03_best_valid/                   最终最佳合法解（routes/assignment/crossing_stats/validation）
├── 04_geometry_audit/               几何口径核查 + 正式 FINAL_AUDIT（6 必需量 + 独立 Validator）
├── 05_figures/                      G3 基线 21 层 / G4 best 21 层 / G3-vs-G4 对照 / 迁移 / 预算曲线 / 失败分析
├── 06_arms/                         6 个 A 类臂 + 1 个 B 类 warm-start 的关键产物与独立验收
├── 07_chain/                        B 类逐步优化链摘要与各链段独立验收
├── 08_code/                         G4 代码快照（g4 包全部 .py + SPEC）
├── LOCAL_FULL_ARCHIVE_MANIFEST.json 本地完整归档（850 文件）的 SHA256 清单
└── MANIFEST_REPO.json               本目录实际包含文件的 SHA256 清单
```

## 四、关键几何口径（独立复算，不复用历史 PASS）

| 必需量 | 值 |
|---|---|
| `minimum_distance_all_pairs_mm` | 0.0（合法同层横穿处） |
| `minimum_clearance_non_crossing_mm` | 0.05（跨高度 flat 对=层间距阈值，按 |dz|≥0.05 合法）；transition-vs-flat 0.060874260；同层 2D 非交叉 0.086853441 |
| `allowed_crossing_count` | 1185（D56 strict 允许类，角度 5.33°–90°） |
| `illegal_crossing_count` | 0 |
| `clearance_violation_count` | 0 |
| `crossing_exemption_policy` | 同层 D56 strict 80µm + ≥5° 局部横穿豁免；不同高度 |dz|≥0.05；transition 真 3D ≥0.05 |

历史“最小 3D 净空 0.063596 mm”只覆盖 transition 相关对；全板跨高度最小值实为 0.05 mm 零余量。

## 五、说明与局限

* 所有正式接受解均经**独立冻结 Validator**（`manual_policy=fully_optimizable`，与 G3 同款）验收；
  `best_valid` 只在事务整组验收且交叉严格下降后更新；非法几何从不进入 `best_valid`。
* 本地完整归档含每臂 `checkpoints/` 与各链段完整 routes 副本（未上传，避免重复）；
  报告中所有数字均来自真实接受解，未做推算。
* 未达成 1000 挑战目标：接口层 212 条 direct-body×direct-body 交叉为当前候选族下的结构性下限；
  neighborhood 16/32/64 阶段收益极低（88% 的收益来自 exact-delta 高度迁移 sweep）；
  当前结果（1185）为给定引擎/预算下的局部最优，**不是**数学最优性证明。
* 本目录为毕业设计实验资料，不是同行评议出版物。
