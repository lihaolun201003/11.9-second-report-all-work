# Fanout-First + Z2 人工 U 验证 1024 通道 3D 布线实验报告

生成时间：2026-11-03T19:43:06  
运行目录：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024`  
算法：`FANOUT_FIRST_THEN_LAYERWISE_2D`  
工艺模式：`corrected_50um`  

## 结论摘要

* 最终合法完整连接：**1024 / 1024**（失败 0 条，真实 route_id 与原因见第 7 节和 `final_stats.json`）
* 按平面：Z1 布通 512/512，Z2 布通 512/512
* 8 个人工 U 分组：输入 368 条，布通 368 条
* 独立验证：geometry_pass=是，contract_pass=是，validation_pass=是，违规数 0
* 最小真实 3D 中心线间距：0.149966 mm（规则 0.05 mm），最小平面间距下限 0.050000 mm
* GitHub commit：https://github.com/lihaolun201003/11.9-second-report-all-work/commit/7daf5a88d590ffe42c42e22489cdcfc41bf0ef54

## 1. 方法与流程

数据不重新生成：1024 条连接来自原始 V4 数据 `routes_1024.json`（z1=512：256 opposite + 256 same；z2=512：400 adjacent + 112 same），端口坐标来自 `four_side_1024.v3c4.inputs.ENDPOINTS`（2048 个真实端口）。

五个阶段：

1. **A 数据审计 + 1024 分配**：审计 Excel 112 行；用连接器模板匹配真实 Z2 人工 U；把 1024 条分配到 18 个物理层（固定人工层 L2–L5 / L10–L13，其余按 C4 旋转轨道整组分配）。
2. **B 仅 8 个人工组的 fanout**：为 368 条人工 U 的 736 个端口端点规划 R15 垂直过渡（fanout-first）。
3. **C 8 个人工层的逐层 2D 布线**：fanout 落点作为起止位姿，在各自目标层做 R15 二维布线。
4. **D 全部 1024 条 fanout**：人工组 transition 固定不动（不再被挪动），其余端点规划过渡。
5. **E 联合修复 + 逐层 2D + 组装 + 严格 3D 校验**：迭代执行"3D 过渡障碍 → 逐层 2D 重布 → 组装 → 重建 world 校验"，并把每轮的违规位置反馈为下一轮障碍；最终只把**通过严格 3D world 校验**的线路计为布通。

工艺模型（`fanout1024/common.py`，单一口径）：1 mm 玻璃 z∈[-0.35,+0.65]；Z1 界面 z=0、Z2 界面 z=0.5；18 个物理层 L2–L19，最小层间距 50 µm；R15（所有圆弧半径恰为 15 mm，过渡为两段 R=15 圆弧的 S 曲线）；真实 3D 中心线间距 ≥ 0.05 mm；同层二维规则沿用原始 D56（宽度 0.05 + 边缘间隙 0.03 = 0.08 mm，合法的横向交叉保留）。没有恢复 80 µm 全局间距。

独立验证（`validate_final.py`）：从 `routes_l3d.json` 重建一个新的 `l3d.world.World`（clearance=0.05），按 route_id 顺序逐条 `check_route(check_self=True)`；并独立审计结构连续性、端口位姿、R15 真实 3D 曲率、玻璃边界、端口覆盖/恒等性、层分配、50/49 µm 边界一致性、同层 D56 与交叉计数。检查项与计数见第 9 节。

## 2. 问题 1：Excel 的 112 条候选记录是否是真正的 Z2 线路？

**答案：不是。** 这 112 行是按 Z1 平面编号的副本/镜像数据（全部 `layer=z1`、全部 224 个端点端口 plane index 都是 1、全部 route_id 都落在 Z1 的编号范围 ≤512，且 0/112 行的 route_id 与真实同号线路的端点对一致）。最终核实出的真实 Z2 人工 U 是 **112 条**：512 条真实 Z2 连接中有 112 条 same 关系连接满足用户的人工 U 连接器模板，按连接器/同侧/行列通道指纹逐条匹配到真实 route_id（已确认 112 个唯一 route_id，未匹配 0，冲突 0）。

Z2 人工 U 正确 CSV：`z2_manual_u_verified_L10_L13.csv`（112 行，每条一个真实连接）；Z1 人工 U CSV：`z1_manual_u_verified_L2_L5.csv`（256 行）。分组统计：

| 分组 | plane | 固定层 | 输入 | 最终布通 | 失败 |
|---|---|---|---|---|---|
| Z1-U1 | z1 | 2 | 64 | 64 | 0 |
| Z1-U2 | z1 | 3 | 64 | 64 | 0 |
| Z1-U3 | z1 | 4 | 64 | 64 | 0 |
| Z1-U4 | z1 | 5 | 64 | 64 | 0 |
| Z2-U1 | z2 | 10 | 16 | 16 | 0 |
| Z2-U2 | z2 | 11 | 16 | 16 | 0 |
| Z2-U3 | z2 | 12 | 40 | 40 | 0 |
| Z2-U4 | z2 | 13 | 40 | 40 | 0 |

数据审计给出的真实 Z2 人工 U 分组：

| 分组 | 真实 Z2 线路数 | 目标层 | 目标 z (mm) | pattern |
|---|---|---|---|---|
| Z2-U1 | 16 | 10 | 0.15 | NS-first |
| Z2-U2 | 16 | 11 | 0.2 | EW-first |
| Z2-U3 | 40 | 12 | 0.25 | NS-second |
| Z2-U4 | 40 | 13 | 0.3 | EW-second |

独立复现结论：`CONFIRMED: 112/112 Excel rows independently match exactly one true z2 same route (16/16/40/40)`（claimed=112，confirmed=True）。

结论：Excel 原始 112 行**不能**作为 Z2 线路直接使用；真正可用于布线的是按真实 1024 连接核实出来的 112 条 Z2 same 连接（本报告的数据审计结论与 `z2_manual_u_summary.json` 一致）。

## 3. 问题 2：Z1 四组和 Z2 四组的线路，有多少条能在满足 R15 和 50 µm 规则下完成两端升降？

端点升降统计（fanout 阶段，R15 + 真实 3D ≥0.05 mm；人工组在实验 B 单独统计、实验 D 全部 1024 条再统计）：

| fanout 阶段 | 输入线路 | 两端升降都成功 | 端点失败数 | 升降不完整线路 | 成功端点数 |
|---|---|---|---|---|---|
| 实验 B（仅 8 个人工组） | 368 | 368 | 0 | 0 | 736 |
| 实验 D（全部 1024 条） | 1024 | 1024 | 0 | 0 | 2048 |

最终 1024 条成品线路中，端点过渡成功数（每成功线路含 2 个升降端点）：

| 指标 | 数量 |
|---|---|
| 总端点数（1024×2） | 2048 |
| fanout 阶段成功规划的端点数（实验 D） | 2048 |
| 最终成品线路包含的升降端点数 | 2048 |
| 属于最终失败线路的端点数（fanout 已成功，失败在同层 2D body） | 0 |
| 两端升降都成功的最终线路 | 1024 |

注意：fanout 阶段（实验 D）对全部 2048 个端点都成功规划了 R15 过渡；上表“属于最终失败线路的端点”不是 fanout 失败，而是少数线路的 body 2D 布线失败导致其端点没有进入最终成品（见第 7 节瓶颈分类）。

fanout 落点 lead 的最终状态（fanout-first 的关键指标）：

| 指标 | 数值 |
|---|---|
| 初始 fanout 计划（实验 B/D） | {'0.25/0.25': 1024} |
| 联合修复后的最终 lead | {'0.25/0.25': 1023, '8.0/8.0': 1} |
| 最终过渡总数 | 2048 |
| lead 改变过的线路 | route 165（source lead 8 mm / target lead 8 mm） |

说明：final lead state after local joint repair / RRR (fanout_selected.json); experiment_D records the initial all-0.25 mm fanout plan。最终 1024 条中只有 1 条线路的 fanout lead 被联合修复改动，其余线路保持初始 0.25/0.25 mm lead，说明联合修复是局部改动、没有重排整体 fanout。lead 直方图与 `fanout_selected.json` 的逐端点记录一致。

| 分组 | 目标层 | 输入 | 最终布通线路 | 最终过渡数（2×布通） | 目标 z (mm) |
|---|---|---|---|---|---|
| Z1-U1 | 2 | 64 | 64 | 128 | -0.350 |
| Z1-U2 | 3 | 64 | 64 | 128 | -0.290 |
| Z1-U3 | 4 | 64 | 64 | 128 | -0.230 |
| Z1-U4 | 5 | 64 | 64 | 128 | -0.170 |
| Z2-U1 | 10 | 16 | 16 | 32 | 0.150 |
| Z2-U2 | 11 | 16 | 16 | 32 | 0.200 |
| Z2-U3 | 12 | 40 | 40 | 80 | 0.250 |
| Z2-U4 | 13 | 40 | 40 | 80 | 0.300 |

说明：最终只统计成功布通的线路；`experiment_D` 的 fanout 结果给出所有 1024 条的两端过渡成功数，`experiment_B` 单独给出 8 个人工组的过渡成功数（人工组过渡在实验 D/E 中被固定，不再被改动）。R15 由独立验证器按真实 3D 曲率采样复核（见第 8 节）。

## 4. 问题 3：完成升降之后，这八组在各自目标层重新二维布线，分别布通多少条？

| 分组 | 目标层 | 该层 2D 布通 | 该层 2D 失败 | 该层尝试 | 该组输入 |
|---|---|---|---|---|---|
| Z1-U1 | 2 | 64 | 0 | 64 | 64 |
| Z1-U2 | 3 | 64 | 0 | 64 | 64 |
| Z1-U3 | 4 | 64 | 0 | 64 | 64 |
| Z1-U4 | 5 | 64 | 0 | 64 | 64 |
| Z2-U1 | 10 | 16 | 0 | 16 | 16 |
| Z2-U2 | 11 | 16 | 0 | 16 | 16 |
| Z2-U3 | 12 | 40 | 0 | 40 | 40 |
| Z2-U4 | 13 | 40 | 0 | 40 | 40 |

逐层明细（实验 C：8 个人工层；来源 `experiment_C/summary.json`）：

| 层 | 布通 | 失败 | 尝试 |
|---|---|---|---|
| L2 (z=-0.35) | 64 | 0 | 64 |
| L3 (z=-0.29) | 64 | 0 | 64 |
| L4 (z=-0.23) | 64 | 0 | 64 |
| L5 (z=-0.17) | 64 | 0 | 64 |
| L10 (z=+0.15) | 16 | 0 | 16 |
| L11 (z=+0.20) | 16 | 0 | 16 |
| L12 (z=+0.25) | 40 | 0 | 40 |
| L13 (z=+0.30) | 40 | 0 | 40 |

全部 18 层的逐层 2D 结果（最终口径：目标层分配 + `routes_l3d.json` 的 body 层 + `failed_routes.json`；逐层失败以最终失败线路为准，layer2d 内部 RRR 重试的中间失败统计保留在 `final_stats.json` 的 `experiment_e_internal_per_layer` 中）：

| 层 | 布通 | 失败 | 尝试 |
|---|---|---|---|
| L2 (z=-0.35) | 64 | 0 | 64 |
| L3 (z=-0.29) | 64 | 0 | 64 |
| L4 (z=-0.23) | 64 | 0 | 64 |
| L5 (z=-0.17) | 64 | 0 | 64 |
| L6 (z=-0.11) | 128 | 0 | 128 |
| L7 (z=-0.05) | 128 | 0 | 128 |
| L8 (z=+0.05) | 48 | 0 | 48 |
| L9 (z=+0.10) | 48 | 0 | 48 |
| L10 (z=+0.15) | 16 | 0 | 16 |
| L11 (z=+0.20) | 16 | 0 | 16 |
| L12 (z=+0.25) | 40 | 0 | 40 |
| L13 (z=+0.30) | 40 | 0 | 40 |
| L14 (z=+0.35) | 48 | 0 | 48 |
| L15 (z=+0.40) | 52 | 0 | 52 |
| L16 (z=+0.45) | 52 | 0 | 52 |
| L17 (z=+0.55) | 52 | 0 | 52 |
| L18 (z=+0.60) | 52 | 0 | 52 |
| L19 (z=+0.65) | 48 | 0 | 48 |

## 5. 实验 A–E 结果汇总

| 实验 | 输入线路 | 成功/布通 | 失败 | 失败原因 |
|---|---|---|---|---|
| A | 1024 | 27/27 | 0 | 数据审计+分配检查全部通过（status=passed） |
| B | 368 | 368 | 0 | — |
| C | 368 | 368 | 0 | — |
| D | 1024 | 1024 | 0 | — |
| E | 1024 | 1024 | 0 | — |

联合修复（实验 E）迭代历史：

| 迭代 | 组装/尝试线路 | world 合法 | 违规数 | 违规类型 | 未组装/剩余 |
|---|---|---|---|---|---|
| 1 | 1022 | 1022 | 0 | {} | 2 |
| 2 | 1022 | 1022 | 0 | {} | 2 |
| local #1 | 4 | 1024 | None | local_joint_repair | 0 |

修复记录来源：routes_l3d.json joint_repair_history。

## 6. 问题 4：全部 1024 条经过 Fanout-First + Layer-wise 2D + Joint Repair 后，最终合法布通多少条？

**最终合法布通：1024 / 1024**（失败 0 条；Z1 成功 512/512，Z2 成功 512/512）。这里的"成功"指：fanout 两端过渡 + 目标层 2D 布线 + 3D 组装后**通过独立 validator 重建世界的严格 3D 校验**。

人工 U 与其它线路的最终统计：

| 类别 | 输入 | 布通 | 失败 |
|---|---|---|---|
| Z1 人工 U（Z1-U1..U4） | 256 | 256 | 0 |
| Z2 人工 U（Z2-U1..U4） | 112 | 112 | 0 |
| 其它 Z1（opposite，L6/L7） | 256 | 256 | 0 |
| 其它 Z2（adjacent，L8/L9/L14..L19） | 400 | 400 | 0 |

严格验证结果：geometry_pass=是，contract_pass=是，validation_pass=是，违规总数 0；最小 3D 间距 0.149966 mm（规则 0.05 mm）。

GitHub commit：https://github.com/lihaolun201003/11.9-second-report-all-work/commit/7daf5a88d590ffe42c42e22489cdcfc41bf0ef54

失败线路（共 0 条，真实 route_id + 原因；按瓶颈分类见第 7 节）：

（无失败线路）

## 7. 问题 5：如果仍无法实现全部 1024 条，瓶颈主要出在什么环节？（7 类区分）

分类依据：每条失败的真实 `reason`（含 fanout 失败的角色/blocker、layer2d 失败原因、assembly 失败原因、world 校验冲突）映射到以下 7 类；没有把失败统称为"碰撞"。完整 reason 分布同时列在下面。

| 瓶颈类别 | 失败数 | route_id 示例 |
|---|---|---|
| 1) 原始数据及分组问题 | 0 | — |
| 2) 目标物理层分配问题 | 0 | — |
| 3) 三维端口升降问题（fanout 未找到合法过渡） | 0 | — |
| 4) 三维过渡相互冲突（fanout/rip-up 冲突） | 0 | — |
| 5) 二维落点位置不合理（landing/lead/位姿无法衔接） | 0 | — |
| 6) 同层二维自动布线失败（候选不足/D56 冲突） | 0 | — |
| 7) 联合 RRR 搜索能力不足（world 校验/装配仍失败） | 0 | — |

**答案：最终 1024 条全部合法布通，没有未解决的失败线路；因此 7 类瓶颈的"未解决失败数"全部为 0。**

但过程中确实出现过失败并被联合修复（这是"中间失败"，不是最终失败，完整记录见 `routes_l3d.json` 的 `joint_repair_history` 与 `run.log`）：

| 阶段 | 尝试修复/组装 | world 合法 | 剩余失败 | 修复记录 |
|---|---|---|---|---|
| stage E 迭代 1 | 1022 | 1022 | 2 | 0 |
| stage E 迭代 2 | 1022 | 1022 | 2 | 0 |
| 局部联合修复 #1 | 4 | 1024 | 0 | rounds 修复 0; RRR L6:committed |

修复过程解读：stage E 的 2 次迭代最后一轮为 1022/1024 合法、2 条同层二维布线失败；随后局部联合修复（local_joint_repair）L6 整层 RRR 提交（失败 ids [164, 165]） 把剩余 2 条全部收回；最终 1024/1024、剩余 0。因此**中间失败的类别全部是第 6 类（同层二维自动布线失败）**，是第 7 类的"联合 RRR 搜索能力"把它们全部收回；最终 7 类的未解决数均为 0。

逐类说明：

* **1) 原始数据及分组问题**：0 条。数据审计没有发现必须丢弃的线路：1024 条真实连接全部保留，端口对未被重新生成，Excel 的 112 行被核实为 Z1 编号数据并替换为 112 条真实 Z2 线路。
* **2) 目标物理层分配问题**：0 条。assignment_1024.csv 覆盖 1024 条唯一 route_id，512/512 plane，人工组全部落在固定层，没有出现目标层分配缺失。
* **3) 三维端口升降问题（fanout 未找到合法过渡）**：0 条。端口升降阶段在给定 lead/R15/3D 间距下找不到合法过渡候选（fanout_incomplete）。
* **4) 三维过渡相互冲突（fanout/rip-up 冲突）**：0 条。过渡之间或过渡与已固定过渡/其它线路的 true-3D 距离 < 0.05 mm，fanout 的 bounded rip-up 后仍被阻塞（带真实 blocker route_id）。
* **5) 二维落点位置不合理（landing/lead/位姿无法衔接）**：0 条。fanout 落点 A/B 与二维 body 起止位姿/lead 方向无法衔接（装配时 body 起点/终点/切线不匹配）。
* **6) 同层二维自动布线失败（候选不足/D56 冲突）**：0 条。目标层二维自动布线在 D56 strict（0.08 mm 同层中心线）+ 过渡障碍 0.05 mm 下候选耗尽。
* **7) 联合 RRR 搜索能力不足（world 校验/装配仍失败）**：0 条。联合修复多轮迭代后仍被严格 world 校验判违规，或装配失败；属于搜索/修复能力不足，而不是单点几何错误。

## 8. 严格独立验证细节

验证对象：`routes_l3d.json` 中的全部 routed 记录；failed 记录只计数、不当作成功。

| 检查项 | 违规数 |
|---|---|
| structure 结构/连续性/端口位姿 | 0 |
| radius R15（圆弧恰 15 mm；过渡真实 3D 曲率 ≥15-1e-6） | 0 |
| glass 玻璃边界（中心线 x,y∈[0,150]，z∈[-0.35,+0.65]） | 0 |
| clearance 真实 3D 间距（fresh World, 0.05 mm） | 0 |
| ports 端口覆盖/恒等（1024 唯一 id、512/512、端口对=真实数据） | 0 |
| assignment 层分配审计（body 层/z = 分配；人工层不被占用） | 0 |
| crossings 同层 D56（合法横向交叉豁免） | 0 |

| 几何指标 | 数值 |
|---|---|
| 总长度 | 156893.005 mm |
| 过渡总数 | 2048 |
| flat 圆弧总数 / 最小圆弧半径 | 1666 / 15.000000 mm |
| 过渡真实 3D 最小曲率半径 | 14.999999980 mm |
| 最小 3D 间距（实测） | 0.149966 mm |
| 最小 3D 间距（含层间距保证的下限） | 0.050000 mm |
| transition-vs-flat 最小间距 | 0.149966 mm |
| transition-vs-transition 最小间距 | n/a mm |
| 同层合法横向交叉总数 | 18108 |
| 同层交叉对数 | 15913 |
| 玻璃中心线最小余量 | 0.000000 mm |
| 玻璃边缘最小余量（含波导半宽 0.025） | -0.025000 mm |
| validator 自洽测试 | 10/10 通过 |

同层 D56 逐平面结果（合法横向交叉数 / 违规数）：

| 物理平面 | 线路数 | 合法交叉 | 违规 | 最小非交叉中心线 (mm) |
|---|---|---|---|---|
| L2 (z=-0.35) | 64 | 0 | 0 | 0.323234 |
| L3 (z=-0.29) | 64 | 0 | 0 | 0.322031 |
| L4 (z=-0.23) | 64 | 0 | 0 | 0.322531 |
| L5 (z=-0.17) | 64 | 0 | 0 | 0.323105 |
| L6 (z=-0.11) | 128 | 5610 | 0 | 0.105024 |
| L7 (z=-0.05) | 128 | 5284 | 0 | 0.105024 |
| Z1 界面 z=0.00 | 512 | 0 | 0 | n/a |
| L8 (z=+0.05) | 48 | 60 | 0 | 2.707696 |
| L9 (z=+0.10) | 48 | 60 | 0 | 2.707696 |
| L10 (z=+0.15) | 16 | 0 | 0 | 0.323234 |
| L11 (z=+0.20) | 16 | 0 | 0 | 0.321954 |
| L12 (z=+0.25) | 40 | 0 | 0 | 0.322358 |
| L13 (z=+0.30) | 40 | 0 | 0 | 0.322807 |
| L14 (z=+0.35) | 48 | 1216 | 0 | 0.832884 |
| L15 (z=+0.40) | 52 | 1480 | 0 | 2.707696 |
| L16 (z=+0.45) | 52 | 1440 | 0 | 0.213919 |
| Z2 界面 z=0.50 | 512 | 0 | 0 | n/a |
| L17 (z=+0.55) | 52 | 1458 | 0 | 0.251378 |
| L18 (z=+0.60) | 52 | 1440 | 0 | 2.707696 |
| L19 (z=+0.65) | 48 | 60 | 0 | 2.707696 |

validator 自洽测试（50/49 µm 边界，online world 与验证器同一代码路径）：

| 测试 | 通过 | 期望 | 实际 |
|---|---|---|---|
| world_accepts_50um_plane_separation | 是 | True | True |
| validator_accepts_50um_plane_separation | 是 | True | True |
| world_rejects_49um_plane_separation | 是 | True | True |
| world_49um_is_flat_cross_plane_too_close | 是 | True | True |
| validator_rejects_49um_plane_separation | 是 | True | True |
| real_layer_stack_min_pitch_is_50um | 是 | 0.05 | 0.05 |
| validator_rejects_49um_physical_stack | 是 | True | True |
| d56_same_plane_50um_xy_is_illegal | 是 | True | True |
| d56_same_plane_49um_xy_is_illegal | 是 | True | True |
| true_port_table_poses_consistent | 是 | True | True |

## 9. 可复现性与测试证据（`tests.log`）

`RUN_DIR/tests.log`（6670 bytes，sha256 `9c9a1c44157f0a8acc6f42ea628d909ec85c9f52866d2f2c6ab15a3938a3d3f6`）记录了三套模块自测的完整命令与输出，并随本报告的归档一起保存。它是**模块级回归证据**；最终几何验收由 `validate_final.py` 独立完成（见第 8 节）。

模块自测结果：

| 测试套件 | 通过/结果 |
|---|---|
| data/assignment 自测（tests_data.py） | 16 |
| fanout 自测（tests_fanout.py） | 7 |
| 逐层 2D 自测（tests_layer2d.py） | 8 |
| layer2d 集成回归（frozen layout，冻结布局） | 1023/1024 |

layer2d 集成回归逐层结果（冻结布局，含重布后 1023/1024 的已知单层 L6 记录）：

* `integration L2: 64/64 failed=0 0.5s`
* `integration L3: 64/64 failed=0 0.3s`
* `integration L4: 64/64 failed=0 0.5s`
* `integration L5: 64/64 failed=0 0.3s`
* `integration L6: 127/128 failed=1 1.4s`
* `integration L7: 128/128 failed=0 0.7s`
* `integration L8: 48/48 failed=0 0.1s`
* `integration L9: 48/48 failed=0 0.0s`
* `integration L10: 16/16 failed=0 0.1s`
* `integration L11: 16/16 failed=0 0.0s`
* `integration L12: 40/40 failed=0 0.2s`
* `integration L13: 40/40 failed=0 0.2s`
* `integration L14: 48/48 failed=0 0.2s`
* `integration L15: 52/52 failed=0 0.2s`
* `integration L16: 52/52 failed=0 0.4s`
* `integration L17: 52/52 failed=0 0.3s`
* `integration L18: 52/52 failed=0 0.2s`
* `integration L19: 48/48 failed=0 0.1s`

其它关键测试输出：

* `=== fanout1024 data/assignment self-tests ===`
* `=== test session starts ===`
* `=== 7 passed in 54.40s ===`
* `TESTS: 16 passed, 0 failed (of 16)`
* `7 passed in 54.40s`
* `Ran 8 tests in 15.212s`
* `integration total: 1023/1024`

## 10. 局限与注意事项（必须与数字一起阅读）

* 50 µm 层间距（18 层，pitch ≥ 0.05 mm）是本轮确认的工艺输入；但光学串扰、串扰导致的通道代价、以及光刻/写入的制造公差与工艺余量均未验证，本报告只做几何口径的验证，不能作为可制造性结论。
* 没有恢复 80 µm 全局间距。本轮 3D 中心线间距规则是 0.05 mm；0.08 mm 只作为同层二维 D56 中心线规则（宽度 0.05 + 边缘间隙 0.03）保留，不与 3D 规则混用。
* 边界波导（端口位于 150 mm 板边、中心线到板边距离 0~0.025 mm）只满足当前探索性的中心线几何模型；波导边缘会超出玻璃边界（半宽 0.025 mm），表面工艺/切割余量未验证。
* R15 是几何约束而非损耗标定值；弯损/交叉损没有针对该玻璃工艺的标定函数，因此本报告不给出光学损耗结论。
* 物理层 stack 的 provenance 是 unconfirmed_simulation（探索性输入），validator 只报告 exploratory 几何通过，不构成正式工艺验收。
* 失败线路如实保留在 failed_routes.json / final_stats.json 中（真实 route_id + 原因），没有把失败改写成成功，也没有为了通过而放宽任何检查。

## 11. 与上一轮 809/1024 对比

详细对比见 `comparison.md`。**重要：上一轮（BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL）并没有正确处理 Z2 人工 U 分组——它的 assignment 中没有 Z2-U1..U4 任何一行（0 行），且 L10–L13 上有 153 行非人工线路占用；因此上一轮与本轮不是同等约束条件下的算法对比，不能预设本轮的布通率必然超过 809。**

| 指标 | 上一轮 809/1024 | 本轮 1024/1024 |
|---|---|---|
| 最终完整连接 | 809/1024 | 1024/1024 |
| Z1 / Z2 布通 | 416 / 393 | 512 / 512 |
| Z2 人工 U 组是否处理 | 否（0 行 Z2-U*，L10–L13 被非人工线路占用） | 是（112 条真实 Z2 人工 U，16/16/40/40） |
| 验证违规数 | 0 | 0 |
| 最小 3D 间距 | 0.052674 mm | 0.149966 mm |

## 12. 关键输出文件

* `routes_l3d.json`
* `failed_routes.json`
* `validation.json`
* `validator_consistency_tests.json`
* `final_stats.json`
* `final_stats_run_all.json`
* `report.md`
* `comparison.md`
* `assignment_1024.csv`
* `z1_manual_u_verified_L2_L5.csv`
* `z2_manual_u_verified_L10_L13.csv`
* `z2_manual_u_summary.json`
* `input_excel_audit.json`
* `fanout_validation.json`
* `fanout_selected.json`
* `layerwise_routes/routes.json`
* `layerwise_endpoints/endpoints.json`
* `plots/`
* `experiment_A/`
* `experiment_B/`
* `experiment_C/`
* `experiment_D/`
* `experiment_E/`
* `checkpoints/`
* `tests.log`
* `run.log`
* `archive_result.json`
* `code/ (archive)`
* `MANIFEST.json (archive)`

