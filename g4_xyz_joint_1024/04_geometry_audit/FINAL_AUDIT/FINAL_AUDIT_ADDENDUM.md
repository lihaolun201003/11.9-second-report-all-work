# G4 最终最佳解 · 独立第三方终验附页（FINAL_AUDIT_ADDENDUM）

> 对象：`experiments/xyz_joint_g4_1024/07_best_valid/`
> `routes_l3d.json` SHA256 = **`b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`**
> （本次审计现场重算，与 Lead 给定值一致）
> 生成方式：`tools/run_final_audit.py`（独立几何复算 + 6 必需量 + 独立 Validator 复跑）
> + `tools/compare_final_vs_baselines.py`（三方口径对比）；端到端 31.7 s。
> 本附页为 `FINAL_AUDIT_SUMMARY.md` 的详细补充，两份文件均基于 **07_best_valid 的真实文件**。

## 0. 一行结论

**G4 最终解 1024/1024、R15/玻璃/端口/21 高度全部合规，独立复算 1185 交叉 / 1124 唯一对 / 非法 0 / 净空违规 0，独立 Validator 复跑 PASS（violations=0，policy_violations=0，SHA 匹配），相对 G3 −137 交叉、相对冻结 pre-G4 基线 −1224 交叉；人工 U 为 `fully_optimizable`（G3 同款，非 frozen），368 条标签/连接身份零错配。**

## 1. 六个必需量（独立几何复算）

| 必需量 | 值 | 说明 |
|---|---:|---|
| `minimum_distance_all_pairs_mm` | **0.0** | 存在 1185 个合法同层横穿 ⇒ 全局最小必为 0 |
| `minimum_clearance_non_crossing_mm` | **0.05** | 不同物理高度 flat 对，恰为 21 高度层间距（阈值处零余量，按 `|dz|≥0.05` 契约合法） |
| `allowed_crossing_count` | **1185** | 全部为允许的真实横穿；事件级与 `crossing_stats.json` 100% 匹配（角度差 0.0°） |
| `illegal_crossing_count` | **0** | 角度/内点/无重叠/无双交点/窗口 ≤0.8624 mm < 4 mm 全合规 |
| `clearance_violation_count` | **0** | 同层 2D / 跨高度 flat / trans-flat / trans-trans / 自净空 全部 0 |
| `crossing_exemption_policy` | 同基线 | 同层 D56 strict 80 µm + ≥5° 局部横穿豁免；不同高度 `|dz|≥0.05`；transition 真 3D ≥0.05 |

3D 净空分口径（独立复算；括号内为冻结 Validator 折线口径）：

| 类别 | 最小净空 | 证据 / 备注 |
|---|---:|---|
| flat–flat 不同物理高度 | **0.050000** | route 515 (z=0.55) vs 623 (z=0.60)，dz=0.05 且 XY 相交 ⇒ 3D=0.05（层间距下限，合法） |
| transition vs flat | **0.060874260**（Validator 0.060877381） | route 803 transition(z:0.15→0.5) vs route 697 flat(z=0.10)，点 (63.125, 7.087179, 0.160829)；本次为该板全局最紧 3D 净空，≥0.05 无违规 |
| transition vs transition | **0.100000** | route 155 vs 635，点 (90.375, 146.291677, 0.200) |
| 自净空 | 1 mm 搜索内无自接近 | 1024 条路线逐条 cKDTree 扫描，0 违规 |

## 2. 三方交叉口径对比（G3 vs G4-best vs 冻结 pre-G4 基线）

**口径完全一致**：flat 按物理 z 分组 + 冻结 strict D56 2D 审计（0.080 mm 中心线 + ≥5° 局部横穿豁免，窗口 ≤4 mm）。
三列均由本次审计用同一独立算法重算（冻结基线列亦为本次重算，非引用历史 PASS）。

| 指标 | 冻结 pre-G4 基线 | G3 best_valid | **G4 最终 best_valid** | G4 vs 冻结 | G4 vs G3 |
|---|---:|---:|---:|---:|---:|
| routes SHA256（前 12 位） | `36c57ad9eff5` | `711cf910d5c7` | **`b74ae51185ed`** | — | — |
| 交叉事件 | 2409 | 1322 | **1185** | **−1224** | **−137** |
| 唯一交叉对 | 2010 | 1253 | **1124** | **−886** | **−129** |
| 非法交叉 | 0 | 0 | **0** | — | — |
| 最大单路交叉 | 34 | 19 | **19** | −15 | 0 |
| 有交叉的物理高度数 | 13 | 18 | **19** | +6 | +1 |
| 交叉角范围 | 5.0748°–90° | 5.3324°–90° | **5.3324°–90°** | — | 同 |
| 实测最大豁免窗口半宽 | 0.9062 mm | 0.8624 mm | **0.8624 mm** | — | 同 |
| 同层最小非交叉中心线 | 0.102948361 | 0.086853441 | **0.086853441** | — | 同 |
| trans–flat 最小 3D（独立） | 0.067302769 | 0.063593135 | **0.060874260** | ↓ | ↓ |
| trans–trans 最小 3D（独立） | 0.101527795 | 0.1 | **0.1** | — | — |

补充证据：

* **独立复算 = Validator = run 自带 validation.json，三方一致**：1185 events / 1124 pairs；
  `validation/validation.json` 的 `routes_file_sha256` 与本次审计 SHA 相同、`validation_pass=true`、
  `violation_count=0`、`min_3d_clearance=0.060877381`、`min_non_crossing=0.086853441`。
* 逐高度交叉数（z: 冻结 / G3 / G4）：

  | z (mm) | −0.35 | −0.30 | −0.25 | −0.20 | −0.15 | −0.10 | −0.05 | 0.00 | 0.05 | 0.10 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
  | 冻结 | 0 | 0 | 0 | 0 | 423 | 412 | 204 | 226 | 171 | 116 |
  | G3 | 17 | 0 | 0 | 0 | 96 | 54 | 44 | 82 | 79 | 109 |
  | **G4** | **0** | **26** | 0 | **4** | **88** | **50** | **44** | **82** | **66** | **109** |

  | z (mm) | 0.15 | 0.20 | 0.25 | 0.30 | 0.35 | 0.40 | 0.45 | 0.50 | 0.55 | 0.60 | 0.65 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
  | 冻结 | 0 | 0 | 0 | 0 | 119 | 127 | 119 | 119 | 127 | 119 | 127 |
  | G3 | 84 | 55 | 9 | 12 | 99 | 81 | 79 | 130 | 109 | 92 | 91 |
  | **G4** | **52** | **43** | **33** | **38** | **81** | **77** | **67** | **130** | **64** | **72** | **59** |

* 辅助快照说明：`05_arm_G4c_free/best_valid` 在预演（19:10）之后文件被更新过：
  预演快照 SHA `ed72cec3…` = 1190/1129，当前快照 SHA `ce7ca9a9…` = **1189/1128**（与 Lead 所述 1189 一致）；
  最终 07_best_valid（`b74ae511…`）在其基础上再降 4 → **1185/1124**，与 Lead 数字一致。

## 3. 人工 U 迁移统计（`manual_group` 标签保留 / 合同 = fully_optimizable）

| 项目 | 结果 |
|---|---|
| 人工 U 路线数 | **368**（Z1-U1..U4 各 64；Z2-U1 16 / U2 16 / U3 40 / U4 40） |
| `manual_group` 标签 vs 冻结基线 | **全部保留，0 条错配**（逐 route_id 比对） |
| 合同 | **`fully_optimizable`（G3 同款，不是 frozen）**；Validator 输出 manual_policy=fully_optimizable、368 条 manual 0 mismatch、policy_violations=0 |
| 人工 U flat 高度集合 vs **冻结 pre-G4 基线** | **59 条**不同（G3 阶段已迁移大部分，G4 继续优化） |
| 人工 U flat 高度集合 vs **G3** | **7 条**不同 |
| 全板（1024）flat 高度集合 vs 冻结 / vs G3 | 168 条 / 29 条不同 |
| run 自带 `manual_u_changes.json`（相对 G3 起点） | 368 条对照，其中 `geometry_changed=true` 9 条、layer/z 变化 7 条 → 与本次独立统计的"vs G3 7 条"一致 |
| 迁移示例（vs 冻结） | route 49/51/52/53/54/55/56：{−0.35, 0} → {−0.20, 0}；route 57/58：→ {−0.25, 0} |
| 迁移示例（vs G3） | route 303：G3 {0, 0.25} → G4 {−0.35, 0}；route 799/803：G3 {0.5, 0.55} → G4 {0.15, 0.5}；route 807/811：G3 {0.3, 0.5} → G4 {0.25, 0.5} |

**最终报告建议原话**："人工 U 的 `manual_group` 标签与连接身份全部保留（368 条，0 错配），
但人工 U 几何在 G4 中按 `fully_optimizable` 合同允许优化（与 G3 相同），**不是 frozen**。"

## 4. R15 / 玻璃 / 端口 / 连续性 / 结构摘要

| 检查项 | 独立复算结果 |
|---|---|
| R15 flat 圆弧 | **1,798 段，半径全部 = 15.000000 mm**（min=max=15.0，违规 0） |
| R15 transition | **1,924 段，半径全部 = 15**；`theta/footprint/length/end` 与解析公式误差 **0**；解析 S 曲线 vs 生成器最大偏差 **1.78×10⁻¹⁵ mm** |
| 玻璃 150×150×1 | 独立 **1,374,474** 采样点（Validator 自身采样 1,073,098，口径不同但均无越界）；x∈[−1.8×10⁻¹⁰, 150.0000000001]、y∈[0,150]、z∈[−0.35, 0.65]；越界采样 **0**；最小中心线边距 −1.8×10⁻¹⁰ mm（端口恰在板边，探索性中心线模型已知性质）；"边距−半宽" = −0.025 mm（见限制） |
| 端口 / 连接身份 | 1024 条唯一连接；源/目标端点、plane、row/side 与真实表 0 不匹配；路径起点/终点 XY 误差 0 / 4.1×10⁻¹⁰ mm，z 误差 0 |
| 21 个物理高度 | 与 21-height 模型完全一致，相邻间距 **恒 0.05 mm** |
| 结构连续性 | 6,908 个几何连接点（部件级 3,848）：最大位置间隙 **4.95×10⁻¹⁰ mm**、最大切向夹角 **2.11×10⁻⁸ rad**、z 间隙 0 |
| 结构统计 | transitions 1,924 / mid-transitions 70 / excursions 35 / flat arcs 1,798 / 总长 **156,735.562044 mm** |
| 交叉分类 | 1,185 事件全部为合法真实横穿（角度 5.33239°–90°，最小角 ≥5°，窗口外净空 ≥0.08−1e-7） |

## 5. 终验检查清单（`audit_metrics.json` → `independent_cross_checks`，16/16 = true，0 skipped）

`routes_sha256_matches_expected`、`routed_1024_of_1024`、`crossings_count_matches_expected`（1185）、
`crossing_pairs_match_expected`（1124）、`max_crossings_per_route_matches_expected`（19）、
`crossing_stats_artefact_match`（事件级 100%）、`manual_u_368`、`heights_21`、`min_height_gap_0p05`、
`r15_no_violation`、`glass_150x150x1_bounds`、`ports_and_connection_identity`、
`structure_continuity`、`all_crossings_allowed`、`no_clearance_violation`、`independent_validator_pass`。

独立 Validator（本目录 `baseline_revalidation/validation.json`）：**PASS，violation_total=0，
policy_violations=0**，12 项检查全 0，7 个合成一致性测试全 PASS。

## 6. 口径结论与限制（与基线报告一致，不得省略）

* **50 µm 的适用对象**：21 高度层间距；不同物理高度 flat 对（`|dz|≥0.05` 即合法，XY 重叠不违规）；
  任何涉及 transition 的对（真 3D ≥0.05）；单路线自净空。**不适用于**同层平面对 —— 后者用 D56 2D
  0.08 mm + 合法横穿豁免；80 µm 全局净空明确不恢复（`common.py:57`）。
* **"1185 交叉 + 0 违规"自洽**：同层规则与跨高度/transition 3D 规则作用于互不相交的对集合；50 µm 规则
  不会"看到"同层交叉；且全部 1185 交叉经独立复核为真实横穿。
* **口径风险（需上位确认）**：若任务书原始物理要求是"所有中心线无例外 ≥50 µm"，则 1185 个合法交叉
  （距离=0）将是硬违规。本审计不新增、也不隐藏任何豁免；该豁免来自 G4 之前冻结的 D56 strict 策略
  （冻结基线本身 2409 交叉且同 Validator PASS）。
* **0.05 mm 层间距零余量**：不同高度 flat 对 3D 最小净空恰为 0.05 mm（=阈值），合法但无向下余量。
* **代码默认值与现行调用差异**：`l3d/world.py` 默认 `clearance=0.08`（历史），现行 Validator/路由器
  全部显式传 0.05（`validate21.py:1372`、`world_adapter.py:31`）；引用 50 µm 时须注明"运行时显式 0.05"。
* **不可宣称事项**：本审计仅证明满足当前**探索性中心线几何契约**；光学串扰/交叉损耗未验证
  （`fslw/config.py` CROSSING_LOSS unknown_uncalibrated）、工艺容差/侧壁/折射率/连接器外壳干涉未验证、
  玻璃 1 mm 厚度与连接器安装方向为假设值、玻璃边距 −0.025 mm 意味着边界波导只满足探索性中心线模型。
  **不得表述为"满足全部制造约束"**。

## 7. 本目录文件

| 文件 | 内容 |
|---|---|
| `FINAL_AUDIT_SUMMARY.md` | 自动生成的终验摘要（一行结论 + 6 量 + 检查表） |
| `FINAL_AUDIT_ADDENDUM.md` | 本附页（三方对比 / 人工 U 迁移 / R15 等详细证据） |
| `audit_metrics.json` | 6 必需量 + 16 项检查 + 代码证据 + 矛盾分析（完整） |
| `six_quantities.json` | 6 必需量紧凑版（含 run SHA、Validator 摘要） |
| `independent_metrics.json` | 独立几何复算原始结果（1185 个事件、逐高度计数、距离自校验） |
| `min_distance_evidence.json` | 全局最小距离 0 证据 + 各口径最小净空证据 + 数值误差上界 |
| `contract_evidence.json` | 契约取证（44 条 file:line）、50 µm 适用对象、自洽性/矛盾分析 |
| `compare_vs_baselines.json` | 三方交叉口径对比 + 人工 U 迁移 + 与 run 自带 validation 交叉核对 |
| `final_audit_status.json` | 终验状态（exit 用） |
| `baseline_revalidation/` | 本次独立 Validator 复跑报告（validation.json + 一致性测试 + 摘要） |
