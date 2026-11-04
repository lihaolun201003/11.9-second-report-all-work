# G4 终验报告（G4_best_final）

> 由 `tools/run_final_audit.py` 自动生成；数据取自本目录 JSON。

## 运行对象

| 项目 | 值 |
|---|---|
| run_dir | `experiments\xyz_joint_g4_1024\07_best_valid` |
| routes SHA256 | `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a` |
| route_count / routed / failed | 1024 / 1024 / 0 |
| total length mm | 156735.562044000 |

## 六个必需量（独立复算）

| 必需量 | 值 |
|---|---:|
| minimum_distance_all_pairs_mm | **0.000000000** |
| minimum_clearance_non_crossing_mm | **0.050000000** |
| allowed_crossing_count | **1185** |
| illegal_crossing_count | **0** |
| clearance_violation_count | **0** |
| crossing_exemption_policy | 见 `six_quantities.json` |

## 独立复核项

| 检查 | 结果 |
|---|---:|
| routes_sha256_matches_expected | ✅ |
| routed_1024_of_1024 | ✅ |
| crossings_count_matches_expected | ✅ |
| crossing_pairs_match_expected | ✅ |
| max_crossings_per_route_matches_expected | ✅ |
| crossing_stats_artefact_match | ✅ |
| manual_u_368 | ✅ |
| heights_21 | ✅ |
| min_height_gap_0p05 | ✅ |
| r15_no_violation | ✅ |
| glass_150x150x1_bounds | ✅ |
| ports_and_connection_identity | ✅ |
| structure_continuity | ✅ |
| all_crossings_allowed | ✅ |
| no_clearance_violation | ✅ |
| independent_validator_pass | ✅ |

## 交叉 / R15 / 高度 / 玻璃

| 指标 | 值 |
|---|---:|
| 交叉事件 / 唯一交叉对 | 1185 / 1124 |
| 非法交叉事件 | 0 |
| 交叉角范围 deg | 5.33239 – 90.0 |
| 最大单路交叉 | 19 |
| 同层最小非交叉中心线 mm | 0.086853441 |
| flat 圆弧数 / 最小半径 mm | 1798 / 15.000000000 |
| transition 数 / 半径集合 | 1924 / [15.0] |
| 21 高度 / 匹配模型 / 最小间距 mm | 21 / True / 0.05 |
| 玻璃 x/y 范围 mm | [-1.7857601253520288e-10, 150.0000000000984] / [0.0, 150.0] |
| 玻璃 z 范围 mm | -0.35 – 0.65 |

## 独立 Validator（frozen）

| 项目 | 值 |
|---|---:|
| present / validation_pass | True / True |
| violation_count / policy_violations | 0 / 0 |
| validator 交叉 / 对 / min_3d mm | 1185 / 1124 / 0.060877381 |
| validator 同层最小非交叉 mm | 0.086853441 |
| manual policy | fully_optimizable |

## 3D 净空分口径（独立复算）

| 类别 | 最小净空 mm |
|---|---:|
| flat-flat 不同高度 | 0.050000000 |
| transition vs flat | 0.060874260 |
| transition vs transition | 0.100000000 |
| 自净空 | None（搜索半径 1 mm 内无自接近） |

## 口径结论（与基线一致）

- 同层平面对：D56 strict 2D 80 µm 中心线 + 合法横穿豁免（≥5°，局部窗口 ≤4 mm）。
- 不同物理高度 flat 对：`|dz| ≥ 0.05 mm` 即合法；3D 最小 = 层间距 0.05 mm（零余量，按契约合法）。
- transition 相关对象：真 3D ≥ 0.05 mm，无交叉豁免。
- 若任务书原意为"所有中心线无例外 ≥50 µm"，则合法交叉即为硬违规——属需求级口径确认事项，本审计不新增/不隐藏豁免。

本报告与 `audit_metrics.json`、`six_quantities.json`、`min_distance_evidence.json`、`baseline_revalidation/` 配套使用。
