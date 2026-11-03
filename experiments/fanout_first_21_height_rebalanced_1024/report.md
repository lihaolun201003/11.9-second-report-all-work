# 21 路由高度重平衡 1024 通道 3D 布线实验报告

生成时间：2026-11-03T22:07:20  
运行目录：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`  
Baseline（只读）：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024`  
实验类型：21-routing-height rebalanced (19 body planes ids 2..20 + 2 interface-body planes 1001/1002)  

## 结论摘要

* 最终合法布通：**1024 / 1024**（失败 0 条；Z1 512/512，Z2 512/512）
* 路由高度：**21 个**（19 个 body plane ids 2..20 + 2 个 interface-body plane 1001/1002；min pitch 0.050000 mm）；100 条接口直连线路（52 @ z=0.0，48 @ z=0.5，0 transition），其余 924 条各 2 个 transition → **1848 个 transition**
* 同层交叉总数：**11890**（pairs 9797），baseline 为 18108（pairs 15913）→ 变化 -6218.000（-34.34%）
* Z1 五个 other 高度（L6/L7/L20/Z1_INTERFACE/L8）合计 4510 交叉，baseline L6+L7 = 10894 → 变化 -6384.000
* 独立验证：geometry_pass=是，contract_pass=是，validation_pass=是，violations=0；min 3D clearance（实测）0.100699741 mm （规则 0.05 mm，min radius 15 mm）
* 长度：总长 **157484.193 mm**（baseline 156893.005 mm，+591.188 mm）；最长单线 283.188 mm；transition 总长 5775.225 mm
* GitHub commit：<<<GITHUB_COMMIT_URL_21>>>

## 1. 实验设计：21 个路由高度（SPEC.md §1）

19 个 body plane（ids 2..20）+ 2 个可布线的 interface-body plane（1001 = Z1_INTERFACE z=0.0，1002 = Z2_INTERFACE z=0.5，均承载完整二维 body）；总共 21 个路由高度，相邻高度差 >= 0.05 mm。`layer_id` 不与 z 单调：新 plane L20 的 id=20 但 z=-0.05（位于 L7 之上、Z1_INTERFACE 之下）。

| plane | z (mm) | kind | role | 分配 | 布通 | 直连 | manual | 交叉 |
|---|---|---|---|---|---|---|---|---|
| L2 (z=-0.35) | -0.35 | body | manual 固定 | 64 | 64 | 0 | 64 | 0 |
| L3 (z=-0.30) | -0.30 | body | manual 固定 | 64 | 64 | 0 | 64 | 0 |
| L4 (z=-0.25) | -0.25 | body | manual 固定 | 64 | 64 | 0 | 64 | 0 |
| L5 (z=-0.20) | -0.20 | body | manual 固定 | 64 | 64 | 0 | 64 | 0 |
| L6 (z=-0.15) | -0.15 | body | other | 52 | 52 | 0 | 0 | 986 |
| L7 (z=-0.10) | -0.10 | body | other | 52 | 52 | 0 | 0 | 928 |
| L20 (z=-0.05) | -0.05 | body | other | 52 | 52 | 0 | 0 | 964 |
| Z1_INTERFACE (z=+0.00) | +0.00 | interface_body | interface-body 直连 | 52 | 52 | 52 | 0 | 896 |
| L8 (z=+0.05) | +0.05 | body | other | 48 | 48 | 0 | 0 | 736 |
| L9 (z=+0.10) | +0.10 | body | other | 48 | 48 | 0 | 0 | 60 |
| L10 (z=+0.15) | +0.15 | body | manual 固定 | 16 | 16 | 0 | 16 | 0 |
| L11 (z=+0.20) | +0.20 | body | manual 固定 | 16 | 16 | 0 | 16 | 0 |
| L12 (z=+0.25) | +0.25 | body | manual 固定 | 40 | 40 | 0 | 40 | 0 |
| L13 (z=+0.30) | +0.30 | body | manual 固定 | 40 | 40 | 0 | 40 | 0 |
| L14 (z=+0.35) | +0.35 | body | other | 48 | 48 | 0 | 0 | 60 |
| L15 (z=+0.40) | +0.40 | body | other | 48 | 48 | 0 | 0 | 1246 |
| L16 (z=+0.45) | +0.45 | body | other | 52 | 52 | 0 | 0 | 1478 |
| Z2_INTERFACE (z=+0.50) | +0.50 | interface_body | interface-body 直连 | 48 | 48 | 48 | 0 | 60 |
| L17 (z=+0.55) | +0.55 | body | other | 52 | 52 | 0 | 0 | 1560 |
| L18 (z=+0.60) | +0.60 | body | other | 52 | 52 | 0 | 0 | 1476 |
| L19 (z=+0.65) | +0.65 | body | other | 52 | 52 | 0 | 0 | 1440 |

与 baseline 18 层的 layer 映射差异（来自 `assignment_diff_vs_baseline.json`）：

| 字段 | 值 |
|---|---|
| routes | 1024 |
| changed_plane | 604 |
| unchanged_plane | 420 |
| changed_z | 820 |
| direction_flip_routes | 200 |
| direct_routes | 100 |
| manual_unchanged | true |

关键变化：Z1 侧由 baseline 的 60 µm 间距压缩到 50 µm（L2..L7、L20、Z1_INTERFACE、L8 共 9 个高度分布在 -0.35..+0.05）；Z2 人工层 L10..L13 的 id/z/成员完全不变；Z2 other 按旧层→新 plane 映射整体搬迁；100 条线路改为界面直连（0 transition）。

## 2. 方法与流程（A–E）

* A 层模型 + 1024 分配：1024 行、1024 个唯一 route_id、21 个高度、min pitch 0.050000 mm、direct={'total': 100, 'z1': 52, 'z2': 48, 'planes': [1001, 1002]}、transition={'routes': 924, 'endpoint_transitions': 1848}
* B fanout：对 924 条非直连线路的 1848 个端点规划 R15 S 曲线；100 条直连线路不生成任何 transition（fanout 记录 direct 端点）
* C 逐层二维：21 个高度全部独立布线（interface plane 的初始 D56 障碍包含同高度 frozen leads）
* D 3D 组装 + fresh world 校验：assembled=1024，world_valid=1024，world_violations=0
* E 联合修复：2 次迭代（见下），最终只把通过严格 3D world 校验的线路计入布通

| iteration | 2D routed | assembled | world valid | violations | assembly failures | lead repair | budget |
|---|---|---|---|---|---|---|---|
| 1 | 1021 | 1021 | 1021 | 0 | 3 | False | 600 |
| 2 | 1024 | 1024 | 1024 | 0 | 0 | True | 1200 |

独立验证由 `validate21.py` 完成：从 `layer_planes.json` 重建新的 `l3d.world.World(model stack, clearance=0.05)`，按 route_id 顺序逐条 `check_route(check_self=True)`，并独立检查结构/端口位姿、direct route 结构、R15 真实 3D 曲率、玻璃边界、21 个物理高度的严格 D56（interface 平面合并 leads + direct bodies）、端口覆盖/恒等、assignment、50/49 µm 一致性等。

**初始二维 pass 与 transient failure（如实记录，三个来源分开）**

* Lead 冻结说明中描述的初始 C pass：1023/1024，1 条 `candidate_budget_exhausted`，crossings_total 11865；该次 `experiment_C/` 目录已被后续运行覆盖，不在磁盘上。
* 磁盘上可核对的 `checkpoints/stage_C_2d.json`（accepted run 的初始 2D pass）：1021/1024，failed=3，elapsed=6.87 s；interface planes 1001/1002 均为全布通（52/52, 48/48）。
* `experiment_C/` 当前内容已被 layer2d owner 在 accepted E 之后改进重跑（ordering_seed=16，1024/1024，crossings_total 11848），并非 `routes_l3d.json` 所基于的状态；最终以 validator 对 `routes_l3d.json` 的结果为准。

E 的迭代记录（`experiment_E/summary.json`）：iteration 1: 2D 1021, assembled 1021, world_valid 1021, budget 600；iteration 2: 2D 1024, assembled 1024, world_valid 1024, budget 1200。即初始 2D pass 的 transient failure（candidate budget 耗尽）在 E 重跑（per-route candidate budget=1200）中恢复为 1024/1024；**最终 accepted routes_l3d.json 只包含通过严格 3D world 校验的线路，validator 0 违规——从未接受任何非法线路。**

## 3. 严格独立验证结果（validate21.py）

| 检查项 | 违规数 |
|---|---|
| structure（结构/连续性/端口位姿/direct vs transition 结构） | 0 |
| radius（flat arc 恰 15 mm；transition 真实 3D 曲率 ≥15-1e-6） | 0 |
| glass（x,y∈[0,150]，z∈[-0.35,+0.65]） | 0 |
| clearance（fresh World，0.05 mm，route-id 顺序） | 0 |
| ports（1024 唯一 id、512/512、端口对=真实数据） | 0 |
| assignment（21 heights、min pitch、C4 orbit、manual fixed） | n/a |
| crossings（21 个物理高度严格 D56；interface 平面合并审计） | 0 |
| model（layer_planes vs SPEC） | n/a |

* geometry_pass=是，contract_pass=是，validation_pass=是，violations=0，consistency tests 11 项全部通过=是
* routes_l3d.json sha256：`1fe24c977c36c0b24692ee386213e6e870010ac1f0bed5c6b3a1eb4be53119d9`
* min 3D clearance（实测）= 0.100699741 mm；含层间距保证的下限 = 0.050000 mm；router 验收规则 = 0.05 mm
* flat arcs = 1672，最小半径 15.000 mm；transition 采样最小真实 3D 半径 14.999999980 mm
* 同层交叉总 11890 / pairs 9797；审计的高度数 21/21；min non-crossing same-plane centreline 0.080748117 mm

## 4. 交叉统计（21 个高度，含 interface 平面）

严格 D56（width 0.05 + edge gap 0.03 = 0.08 mm，合法横向交叉保留）逐物理高度审计；`Z1_INTERFACE`/`Z2_INTERFACE` 平面把 frozen interface leads 与 interface-direct bodies 合并进同一个审计，绝不跳过。交叉数只是几何代理指标，不代表光学串扰/损耗。

对应图（`plots/`，共 28 张）：21 张逐高度二维图 `plots/per_height/01_L2_z-0.350.png` … `plots/per_height/21_L19_z+0.650.png`（按 z 顺序，含 plane label/z/routed-assigned/port 方向/manual 分组/交叉标记）；对比图 `plots/02_layer_stack_comparison.png`、`plots/03_z1_other_comparison.png`、`plots/04_crossings_per_plane.png`、`plots/05_total_crossings.png`、`plots/06_path_length_distribution.png`、`plots/07_3d_all_routes.png`、`plots/08_interface_direct_zoom.png`。

| plane | z (mm) | kind | 分配 | 布通 | crossings | pairs | min 非交叉中心线 (mm) | violations |
|---|---|---|---|---|---|---|---|---|
| L2 (z=-0.35) | -0.35 | body | 64 | 64 | 0 | 0 | 0.323234 | 0 |
| L3 (z=-0.30) | -0.30 | body | 64 | 64 | 0 | 0 | 0.321954 | 0 |
| L4 (z=-0.25) | -0.25 | body | 64 | 64 | 0 | 0 | 0.322358 | 0 |
| L5 (z=-0.20) | -0.20 | body | 64 | 64 | 0 | 0 | 0.322807 | 0 |
| L6 (z=-0.15) | -0.15 | body | 52 | 52 | 986 | 874 | 0.080748 | 0 |
| L7 (z=-0.10) | -0.10 | body | 52 | 52 | 928 | 866 | 0.303069 | 0 |
| L20 (z=-0.05) | -0.05 | body | 52 | 52 | 964 | 886 | 0.105024 | 0 |
| Z1_INTERFACE (z=+0.00) | +0.00 | interface_body | 52 | 52 | 896 | 860 | 0.105024 | 0 |
| L8 (z=+0.05) | +0.05 | body | 48 | 48 | 736 | 696 | 0.177599 | 0 |
| L9 (z=+0.10) | +0.10 | body | 48 | 48 | 60 | 60 | 2.707696 | 0 |
| L10 (z=+0.15) | +0.15 | body | 16 | 16 | 0 | 0 | 0.323234 | 0 |
| L11 (z=+0.20) | +0.20 | body | 16 | 16 | 0 | 0 | 0.321954 | 0 |
| L12 (z=+0.25) | +0.25 | body | 40 | 40 | 0 | 0 | 0.322358 | 0 |
| L13 (z=+0.30) | +0.30 | body | 40 | 40 | 0 | 0 | 0.322807 | 0 |
| L14 (z=+0.35) | +0.35 | body | 48 | 48 | 60 | 60 | 2.707696 | 0 |
| L15 (z=+0.40) | +0.40 | body | 48 | 48 | 1246 | 954 | 0.435775 | 0 |
| L16 (z=+0.45) | +0.45 | body | 52 | 52 | 1478 | 1131 | 2.707696 | 0 |
| Z2_INTERFACE (z=+0.50) | +0.50 | interface_body | 48 | 48 | 60 | 60 | 2.707696 | 0 |
| L17 (z=+0.55) | +0.55 | body | 52 | 52 | 1560 | 1143 | 1.809682 | 0 |
| L18 (z=+0.60) | +0.60 | body | 52 | 52 | 1476 | 1105 | 0.838659 | 0 |
| L19 (z=+0.65) | +0.65 | body | 52 | 52 | 1440 | 1102 | 2.707696 | 0 |

**接口直连专项（52 + 48 条 direct bodies vs 同高度 leads，单独统计）**

| interface plane | routes | direct bodies | audit routes | crossings | pairs | direct/lead 分类 | min 非交叉 (mm) |
|---|---|---|---|---|---|---|---|
| Z1_INTERFACE (z=+0.00) | 52 | 52 | 512 | 896 | 860 | {"direct_direct": 896, "direct_lead": 0, "lead_non_direct": 0} | 0.105024 |
| Z2_INTERFACE (z=+0.50) | 48 | 48 | 512 | 60 | 60 | {"direct_direct": 60, "direct_lead": 0, "lead_non_direct": 0} | 2.707696 |

全部 21 个高度的 per-route 交叉分布（1024 条线路）：有交叉线路 632 条，max 83，p95 60.000，mean 37.627，median 39.000。

Z1 五个 other 高度对比（baseline 只有 L6/L7 两个 Z1-other 高度）：

| 新 plane | z (mm) | 分配 | 布通 | crossings | pairs |
|---|---|---|---|---|---|
| L6 (z=-0.15) | -0.15 | 52 | 52 | 986 | 874 |
| L7 (z=-0.10) | -0.10 | 52 | 52 | 928 | 866 |
| L20 (z=-0.05) | -0.05 | 52 | 52 | 964 | 886 |
| Z1_INTERFACE (z=+0.00) | +0.00 | 52 | 52 | 896 | 860 |
| L8 (z=+0.05) | +0.05 | 48 | 48 | 736 | 696 |

* baseline L6 交叉 5610，L7 5284，合计 10894
* 新 Z1 五个 other 高度合计 4510 交叉，变化 -6384.000（-58.60%）

## 5. 与 baseline 18 层实验的对比

| 指标 | baseline 18 层（1024/1024） | 新 21 高度（1024/1024） |
|---|---|---|
| 成功 | 1024/1024（100.00%） | 1024/1024（100.00%） |
| 路由高度 | 18 个（18 body） | 21 个（19 body + 2 interface-body） |
| 接口直连线路 | 0 | 100（52 + 48） |
| transitions | 2048 | 1848 |
| totals crossings | 18108 | 11890（-6218.000） |
| crossing pairs | 15913 | 9797（-6116.000） |
| Z1-other heights 交叉 | L6+L7=10894 | 5 heights=4510（-6384.000） |
| Z2-other 8 个高度交叉合计 | 7214 | 7380（+166.000） |
| per-route crossing (max/p95/mean) | max 106 / p95 96.000 / mean 57.30 | max 83 / p95 60.000 / mean 37.63 |
| 总长度 (mm) | 156893.005 | 157484.193（+591.188 mm，+0.3768%） |
| 最长单线 (mm) | 282.314 | 283.188（+0.874） |
| transition 总长 (mm) | 6394.117 | 5775.225 |
| min 3D clearance (mm) | 0.149965866 | 0.100699741 |
| min radius (mm) | 15.0 | 15.000 |
| validator 违规数 | 0 | 0 |

逐平面交叉对比（baseline z 与 new plane 按几何高度对齐；新平面多的 L20/Z1_INTERFACE 等没有 baseline 对应项，标为 —）：

| 新 plane | z (mm) | baseline crossings | new crossings | delta |
|---|---|---|---|---|
| L2 (z=-0.35) | -0.35 | 0 | 0 | +0 |
| L3 (z=-0.30) | -0.30 | — | 0 | — |
| L4 (z=-0.25) | -0.25 | — | 0 | — |
| L5 (z=-0.20) | -0.20 | — | 0 | — |
| L6 (z=-0.15) | -0.15 | — | 986 | — |
| L7 (z=-0.10) | -0.10 | — | 928 | — |
| L20 (z=-0.05) | -0.05 | 5284 | 964 | -4320 |
| Z1_INTERFACE (z=+0.00) | +0.00 | 0 | 896 | +896 |
| L8 (z=+0.05) | +0.05 | 60 | 736 | +676 |
| L9 (z=+0.10) | +0.10 | 60 | 60 | +0 |
| L10 (z=+0.15) | +0.15 | 0 | 0 | +0 |
| L11 (z=+0.20) | +0.20 | 0 | 0 | +0 |
| L12 (z=+0.25) | +0.25 | 0 | 0 | +0 |
| L13 (z=+0.30) | +0.30 | 0 | 0 | +0 |
| L14 (z=+0.35) | +0.35 | 1216 | 60 | -1156 |
| L15 (z=+0.40) | +0.40 | 1480 | 1246 | -234 |
| L16 (z=+0.45) | +0.45 | 1440 | 1478 | +38 |
| Z2_INTERFACE (z=+0.50) | +0.50 | 0 | 60 | +60 |
| L17 (z=+0.55) | +0.55 | 1458 | 1560 | +102 |
| L18 (z=+0.60) | +0.60 | 1440 | 1476 | +36 |
| L19 (z=+0.65) | +0.65 | 60 | 1440 | +1380 |

总交叉从 18108 降到 11890，减少 6218 （−34.34%）。主要来自 Z1 侧：baseline L6/L7 两个高度承担 10894 交叉，新方案把这部分流量分散到 L6/L7/L20/Z1_INTERFACE/L8 五个高度后合计 4510。

**Z2 侧的变化（诚实说明）**：Z2-other 的 8 个高度交叉合计 7380 vs baseline 7214（+166.000，即 Z2 侧反而略有上升），具体为 L9=60、L14=60、L15=1246、L16=1478、Z2_INTERFACE=60、L17=1560、L18=1476、L19=1440。原因是 Z2 other 线路按 old→new plane 整体搬迁（old L8→9, L9→14, L14→15, L15→16, L16→17, L17→18, L18→19, L19→1002），各平面的交叉数变化混合了“线路搬迁”效应。因此**总交叉下降完全来自 Z1-other 的重分配**：Z1-other −6384，Z2-other +166.000，合计 -6218.000。

## 6. Cost / benefit 讨论

* **收益**：
  1. 1024/1024 全部布通（与 baseline 相同），且在 21 个高度上全部有分配与布通（21/21 个平面 routed=assigned）。
  2. 同层交叉总数 11890 vs baseline 18108（几何代理指标），Z1-other 五个高度合计显著低于 baseline L6+L7。
  3. Z2 人工 U 的 L10..L13 完全未动（id/z/成员不变），保证与 baseline 的可比性。
* **代价/风险**：
  1. 多了一个 body plane（L20 id=20 z=-0.05，id 与 z 非单调），层栈更复杂；Z1 间距从 60 µm 压到 50 µm，50 µm 是输入条件，工艺余量未验证。
  2. 总长度 157484.193 mm，比 baseline 增加 +591.188 mm（+0.3768%），最长单线 283.188 mm（baseline 282.314 mm）。
  3. transition 数 1848 vs baseline 2048（100 条 direct 线路 0 transition），transition 总长 5775.225 mm vs baseline 6394.117 mm。
  4. min 3D clearance 从 0.149965866 mm 降到 0.100699741 mm（仍 ≥0.05 mm 规则）。
  5. RRR/联合修复迭代 2 次；运行时间见 run.log/tests.log。
* **诚实结论**：交叉总数确实下降了（−34.34%），但这是几何代理指标；没有光学损耗结论。Z1 侧的收益主要来自把 L6/L7 的流量分散到 5 个高度；interface-direct 线路把部分交叉转移到了 Z1/Z2 界面高度（它们与同高度 leads 合并且 0 违规），这部分交叉在 baseline 中不存在（baseline 的界面高度只有 leads）。

## 7. 失败线路与耗时

本轮 **0 条失败线路**：1024/1024 全部通过严格 3D world 校验与独立 validator。

* 联合修复迭代次数：2；iterations 记录见 `experiment_E/summary.json` 与 `routes_l3d.json` 的 `joint_repair_history`。
* 运行时间/日志：`run.log`（21h run）与 `tests.log`（模块自测 + baseline regression 证据）。

## 8. 可复现性证据（tests.log）

`RUN_DIR/tests.log`（12357 bytes，sha256 `759cfb9028a96146e333b261f9bec14b824099c2926b450ae733035e6bd4c2ed`）收集了模块自测与 baseline regression 输出：tests_data / tests_fanout / tests_layer2d / tests_assign21 / tests_validate21（+ tests_plots21 若存在），以及 18 层 baseline regression（18108 crossings / L6 5610 / L7 5284 / min clearance 0.149965866 / 2048 transitions）。

## 9. 局限与注意事项（必须与数字一起阅读）

* 21 个路由高度（19 个 body plane + 2 个 interface-body plane）中，50 µm 层间距（min pitch 0.05 mm）是本轮确认的几何输入；光学串扰、波导损耗、写入/光刻制造公差与工艺余量均未验证，本报告只做几何口径的统计。
* 交叉数只是几何代理指标（geometric proxy），不是光学串扰/损耗结论；没有给出任何玻导损耗或交叉损耗的数值。
* Z1 侧从 baseline 的 60 µm 间距压缩到 50 µm 间距（L6/L7 之外新增 L20 与 Z1_INTERFACE 直连层）；planar 层间距 50 µm 是外部输入条件，其工艺可实现性未在本轮验证。
* 界面上直连的 100 条线路（52 @ Z1_INTERFACE z=0.0，48 @ Z2_INTERFACE z=0.5）只满足探索性的中心线几何模型；其与同高度 frozen leads 的 D56 strict 0.08 mm 间距通过独立审计，但端口处波导边缘仍会到达玻璃边界（中心线余量 0，半宽 0.025 mm 在板外），表面工艺/切割余量未验证。
* R15 是几何约束而非损耗标定值；transition 的 true-3D 曲率由 validator 独立采样复核。
* 21 层带来的 3D 间距下限仍是 0.05 mm；没有恢复 80 µm 全局间距。
* 本轮 1024/1024 布通、0 违规；失败线路如实保留在本报告中（本轮为 0）。若其他轮次出现失败，同样不会隐藏。

## 10. 关键输出文件

* `routes_l3d.json`
* `failed_routes.json`
* `validation.json`
* `validator_consistency_tests.json`
* `crossing_stats.json`
* `final_stats.json`
* `final_stats_run_all.json`
* `report.md`
* `comparison.md`
* `tests.log`
* `layer_planes.json`
* `assignment_1024.csv`
* `assignment_audit.json`
* `assignment_diff_vs_baseline.md`
* `physical_layer_stack.json`
* `process_rules.json`
* `fanout_selected.json`
* `fanout_validation.json`
* `layerwise_routes/routes.json`
* `layerwise_endpoints/endpoints.json`
* `experiment_A/`
* `experiment_B/`
* `experiment_C/`
* `experiment_D/`
* `experiment_E/`
* `plots/`
* `code/ (archive)`
* `MANIFEST.json (archive)`

