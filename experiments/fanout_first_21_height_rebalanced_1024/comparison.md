# 21 路由高度 vs baseline 18 层：对比报告

生成时间：2026-11-03T22:13:18  
新实验：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`  
Baseline（只读）：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024`  

## 0. 结论先行

* 两个实验都在各自约束下达到 **1024/1024**，独立 validator 0 违规。
* 新方案使用 **21 个路由高度**（19 body planes + 2 interface-body planes），baseline 为 18 层。
* 同层交叉总数 **11890 vs 18108** （-6218.000，−34.34%）；crossing pairs 9797 vs 15913。
* Z1-other 五个高度合计 4510 vs baseline L6+L7 10894（-6384.000）。
* 交叉数只是几何代理指标；没有光学损耗/串扰结论。
* 初始二维 pass 的 transient failure（如实记录）：Lead 冻结说明记录的初始 C pass 为 1023/1024（1 条 candidate_budget_exhausted，crossings_total 11865；该次 experiment_C 目录已被覆盖）；磁盘 `checkpoints/stage_C_2d.json` 记录的 accepted-run 初始 2D pass 为 1021/1024（failed=3，budget=600）。E 重跑（budget=1200）后恢复为 1024/1024；最终 routes_l3d.json 只含通过严格 3D world 校验的线路，0 违规。 注：experiment_C/ 当前内容已被 layer2d owner 在 accepted E 之后改进重跑（**1024/1024, 0 failed**，seed=16，budget=600，initial-C crossings 11848；seeds 0/1/2/15 为 1023/1024（Lead 报告，如实记录）；interface planes 52/52 + 48/48 full，与同高度 frozen leads 合并审计为 892 / 60 个合法交叉、0 D56 conflict），这是改进后的 initial-C layout，不是 routes_l3d.json 所基于的状态；**权威最终结果仍是 accepted E 的 routes_l3d.json：1024/1024，validator crossings 11890/9797**。

## 1. 用户要求的对比表

| 指标 | baseline 18 层 | 新 21 高度 |
|---|---|---|
| 成功 | 1024/1024 | 1024/1024 |
| 路由高度数 | 18 | 21（19 body + 2 interface-body） |
| 接口直连线路 | 0 | 100（52 @ 1001, 48 @ 1002） |
| 端点 transitions | 2048 | 1848 |
| 同层交叉总数 | 18108 | 11890 |
| 同层交叉 pairs | 15913 | 9797 |
| Z1-other 交叉（L6/L7 vs 5 高度） | L6=5610, L7=5284 | L6/L7/L20/Z1_INTERFACE/L8 = 986/928/964/896/736 |
| Z2-other 8 高度交叉合计 | 7214 | 7380（+166.000） |
| per-route crossing max/p95/mean | 106 / 96.000 / 57.30 | 83 / 60.000 / 37.63 |
| 总长度 (mm) | 156893.005 | 157484.193（+591.188 mm，+0.3768%） |
| 最长单线 (mm) | 282.314 | 283.188 |
| transition 总长 (mm) | 6394.117 | 5775.225 |
| min 3D clearance (mm) | 0.149965866 | 0.100699741 |
| min radius (mm) | 15.0 | 15.000 |
| validator 违规数 | 0 | 0 |

## 2. 逐平面交叉数据（baseline vs new，按几何高度对齐）

| 新 plane | z (mm) | baseline crossings | new crossings | delta | 分配 | 布通 |
|---|---|---|---|---|---|---|
| L2 (z=-0.35) | -0.35 | 0 | 0 | +0 | 64 | 64 |
| L3 (z=-0.30) | -0.30 | — | 0 | — | 64 | 64 |
| L4 (z=-0.25) | -0.25 | — | 0 | — | 64 | 64 |
| L5 (z=-0.20) | -0.20 | — | 0 | — | 64 | 64 |
| L6 (z=-0.15) | -0.15 | — | 986 | — | 52 | 52 |
| L7 (z=-0.10) | -0.10 | — | 928 | — | 52 | 52 |
| L20 (z=-0.05) | -0.05 | 5284 | 964 | -4320 | 52 | 52 |
| Z1_INTERFACE (z=+0.00) | +0.00 | 0 | 896 | +896 | 52 | 52 |
| L8 (z=+0.05) | +0.05 | 60 | 736 | +676 | 48 | 48 |
| L9 (z=+0.10) | +0.10 | 60 | 60 | +0 | 48 | 48 |
| L10 (z=+0.15) | +0.15 | 0 | 0 | +0 | 16 | 16 |
| L11 (z=+0.20) | +0.20 | 0 | 0 | +0 | 16 | 16 |
| L12 (z=+0.25) | +0.25 | 0 | 0 | +0 | 40 | 40 |
| L13 (z=+0.30) | +0.30 | 0 | 0 | +0 | 40 | 40 |
| L14 (z=+0.35) | +0.35 | 1216 | 60 | -1156 | 48 | 48 |
| L15 (z=+0.40) | +0.40 | 1480 | 1246 | -234 | 48 | 48 |
| L16 (z=+0.45) | +0.45 | 1440 | 1478 | +38 | 52 | 52 |
| Z2_INTERFACE (z=+0.50) | +0.50 | 0 | 60 | +60 | 48 | 48 |
| L17 (z=+0.55) | +0.55 | 1458 | 1560 | +102 | 52 | 52 |
| L18 (z=+0.60) | +0.60 | 1440 | 1476 | +36 | 52 | 52 |
| L19 (z=+0.65) | +0.65 | 60 | 1440 | +1380 | 52 | 52 |

## 3. 接口直连线路专项

| interface plane | z | 分配 | direct bodies | audit routes | crossings | pairs | direct/lead 分类 | min 非交叉 (mm) | violations |
|---|---|---|---|---|---|---|---|---|---|
| Z1_INTERFACE (z=+0.00) | 0.0 | 52 | 52 | 512 | 896 | 860 | {"direct_direct": 896, "direct_lead": 0, "lead_non_direct": 0} | 0.105024 | 0 |
| Z2_INTERFACE (z=+0.50) | 0.5 | 48 | 48 | 512 | 60 | 60 | {"direct_direct": 60, "direct_lead": 0, "lead_non_direct": 0} | 2.707696 | 0 |

这 100 条直连线路与同高度的 frozen interface leads 合并在同一个严格 D56 审计中（绝不跳过）；它们自身的交叉全部为 direct↔direct，direct↔lead 与 lead↔非直连线均没有违规交叉。

## 4. 交叉变化归因（诚实说明）

* Z1 侧：baseline 的 L6+L7 承担 10894 交叉，新方案分散到 L6/L7/L20/Z1_INTERFACE/L8 五个高度合计 4510，净减少 -6384.000。
* Z2 侧：baseline 的 Z2-other 线路集中在 8 个旧平面（合计 7214 交叉）；新方案按 old→new 映射整体搬迁（old L8→9, L9→14, L14→15, L15→16, L16→17, L17→18, L18→19, L19→1002），新 8 个平面合计 7380（+166.000，即 Z2 侧反而略升）。具体：L9=60、L14=60、L15=1246、L16=1478、Z2_INTERFACE=60、L17=1560、L18=1476、L19=1440。
* 接口高度：baseline 的 z=0/z=0.5 只有界面 leads（0 交叉）；新方案在这两个高度增加了 100 条 direct bodies，带来 Z1_INTERFACE 896 + Z2_INTERFACE 60 = 956 交叉（仍 0 违规；全部 direct↔direct，min 非交叉中心线 Z1 0.105024 mm / Z2 2.707696 mm）。
* 总体净变化：-6218.000 crossing（−34.34%），其中 Z1-other -6384.000、Z2-other +166.000、接口 +956；**交叉下降完全来自 Z1-other 的重分配，Z2 侧没有改善（略升）**。这是几何代理指标，不是光学串扰/损耗结论。
* per-route 交叉分布对比：新 max 83 / p95 60 / mean 37.63 / median 39；baseline max/p95/mean = 106 / 96 / 57.30（由 21h validator 的 baseline regression 轨迹测得，见 tests.log）。

## 4.1 图（plots/）

* 21 张逐高度二维图：`plots/per_height/01_L2_z-0.350.png` … `plots/per_height/21_L19_z+0.650.png`（含 plane label / true z / routed-assigned / 端口方向 / manual 分组 / 交叉标记）
* `plots/02_layer_stack_comparison.png`（18 层 vs 21 高度 z-section）
* `plots/03_z1_other_comparison.png`（baseline L6/L7 vs 新 5 个 Z1 高度）
* `plots/04_crossings_per_plane.png`（逐平面交叉柱状对比）
* `plots/05_total_crossings.png`（总交叉对比）
* `plots/06_path_length_distribution.png`（路径长度分布）
* `plots/07_3d_all_routes.png`（1024 条 3D 总览，按 plane 着色）
* `plots/08_interface_direct_zoom.png`（z=0 / z=0.5 界面直连局部放大）

## 5. 文件

* 新实验 validation: `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024/validation.json`
* 完整报告：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024/report.md`
* 详细统计：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024/final_stats.json`、`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024/crossing_stats.json`

