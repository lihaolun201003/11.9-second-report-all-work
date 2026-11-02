# 自适应 U 型深度 + S 型升降位置联合优化实验报告

- 实验目录：`outputs/manual_c4_new_connectivity/U_DEPTH_TRANSITION_JOINT_OPT/`
- 参考 20 层 checkpoint：`MANUAL_20L_FIXED_ASSIGNMENT_FULL/checkpoints/`
- 目标：不改变 256 条人工 U 的端点、配对、分组、目标层（L2–L5）和 R15/0.08 mm 约束，只通过调整 U 深度和两端 S 型升降位置，提高 48 条有二维几何的 Z2 接口线路的兼容性。
- 生成日期：2026-11-03

## 0. 最终结论

| 指标 | 原始基线 | 实验 A（固定深度） | 实验 B（允许加深） |
|---|---:|---:|---:|
| 人工 U 成功数 | 256 / 256 | **256 / 256** | **256 / 256** |
| Z2 接口成功数 | **12 / 48** | **20 / 48** | **20 / 48** |
| 恢复的 Z2 接口线路 | — | **8 条** | **8 条** |
| 几何违规 | 0 | **0** | **0** |
| 修改 U 数量 | 0 | 33 条唯一 U（47 次接受改动） | 33 条唯一 U（47 次接受改动） |
| 加深 U 数量 | 0 | 0 | **0** |
| 总深度增加 | 0 | 0 | **0 mm** |
| 升降位置变化 | 0 | 平均上升位置后移 **7.51 mm**，平均下降起点后移 **7.32 mm** | 同 A |
| 总 U 路径长度 | 27682.1481 mm | 27682.1481 mm | 27682.1481 mm |
| 计算时间 | 4.05 s（基线复现） | 316.47 s | 541.43 s |

**核心答案：** 仅调整两端 S 型升降位置，可以把 Z2 接口兼容性从 **12/48 提高到 20/48（+8，+66.7% 相对提升）**，且 256 条 U 全部保持合法、0 几何违规。  
**但是：** 实验 B 在允许加深 U 后 **没有找到任何合法的深度改善**（deepened_u = 0，总深度增加 0 mm），B 的实际接受改动集合与 A 完全相同，成功数也相同；因此本数据集上 **“加深 U 能进一步提高 Z2 兼容性”的假设没有得到支持**。

改进来自“把 S 曲线沿原直臂向 U 内部后移”，不是来自深度变化。

---

## 1. 基线复现（不是引用历史数字）

使用同一批数据：

- 人工 U：`checkpoints/z1` 中 256 条 route_id；
- Z2 接口：`z2_assignment_audit.csv` 中 target_layer 为空且原始二维 campaign 有 geometry 的 48 条；
- 世界初始化：仅 256 条人工 U；不加入 L7/L8；Z2 接口路径完全冻结在 z=0.5。

复现结果：

- **12 / 48** 通过，与历史独立实验完全一致；
- 通过 route_id：642, 643, 645, 646, 647, 648, 769, 770, 771, 772, 1017, 1020；
- 36 条失败中 20 条原始二维几何缺失，16 条失败有 blocker；全部失败类型为 `flat_vs_transition`；
- baseline 全量验证：**0 违规**。

baseline 输出：`baseline/z2_results.json`、`baseline/blocker_analysis.json`、`baseline/validation.json`。

---

## 2. 实验 A：固定 U 深度，只调整升降位置

### 2.1 方法

- U 的 XY 路径、arm、目标层完全固定；
- 只搜索 `s_rise`、`s_fall` 两个 S 形过渡位置；
- 对每个候选重新构造真实三维 route（不是平移旧路径），检查：
  - 其他 255 条 U 的同层 D56 + 真实 3D 净空；
  - 候选 U 的自碰撞、R15、板面边界；
  - 对目标 Z2 接口线路的 blocker 数是否下降；
  - 所有 baseline 成功 Z2 是否保持；
- 接受标准：目标 blocker 数下降且不造成 baseline 成功线路回退；严格 world 检查通过才提交；
- 允许多次 pass 的局部冲突驱动搜索。

### 2.2 结果

- **20 / 48**，恢复 8 条：**990, 991, 1018, 1019, 1021, 1022, 1023, 1024**；
- 256 / 256 U 保持成功；
- 0 几何违规；
- 33 条唯一 U 被修改（47 次接受改动，含同一条 U 的多轮微调）；
- 平均上升位置后移 **+7.51 mm**，平均下降起点后移 **+7.32 mm**；
- U 的总路径长度完全不变：**27682.1481 mm**（过渡仍位于同一对直臂/底部上，只改变 S 曲线在路径上的位置）；
- 严格验证 `experiment_A_fixed_depth/validation.json`：全部计数为 0。

### 2.3 为什么 A 能恢复 8 条

恢复的 8 条中 6 条来自单 blocker 的 same-side E/N 接口线路，1 条来自 2-blocker 的 990/991。把 Z1 的 S 曲线从原靠近端口的直臂起点（约 1.2 mm）向 U 内部移动约 7 mm 后，过渡穿过 z=0.5 的位置离开了 Z2 口的近端口轨道，从而释放了 0.08 mm 净空。

A 的逐条改动和升降位置变化见：

- `experiment_A_fixed_depth/route_changes.csv`
- `experiment_A_fixed_depth/transition_position_changes.csv`
- `experiment_A_fixed_depth/u_parameters.json`

---

## 3. 实验 B：允许加深 U 的联合搜索

### 3.1 方法

- 与 A 完全相同的 baseline、48 条 Z2、同一 R15/0.08 mm 约束和可比较的候选预算；
- 先尝试原深度下的升降位置；
- 再允许 `Δd >= 0`，深度步长 0.25 mm、0.5、1.0、2.0、4.0、8.0 mm；
- 为保持嵌套关系，加深一条内部 U 时尝试把它的整条外层嵌套链一起加深（group move）；
- 每个候选都重新构造实际 U 几何，重新做真实 3D 检查；绝不通过平移旧 Z 或降低约束实现“加深”。

### 3.2 结果（负结果）

- **20 / 48**，与 A 完全相同的 8 条恢复；
- **deepened_u = 0**，**total_depth_increase = 0 mm**；
- 47 次接受改动与 A 的 33 条唯一 U / 47 次改动**完全相同**（`same_change_set_as_A = true`）；
- 0 几何违规；
- 搜索候选 5137 个（A 为 4493 个），运行 541.43 s（A 316.47 s）；
- `u_depth_changes.csv` 只有表头，没有数据行。

### 3.3 为什么没有加深成功

B 的组级加深在预算内没有找到同时满足以下条件的候选：

1. **嵌套链联动后仍满足同层 U 间净空**：内部 U 加深必须联动外层链，外层链整体移动后容易与相邻 U 或相邻层 U 的直臂/底部冲突；
2. **U 主体的 0.08 mm 净空和 R15**：加深会改变两侧直臂长度和底部位置，新的底部/圆弧与同层其他嵌套 U 的间隙不满足要求；
3. **对 Z2 的改善**：即使某条 U 加深 0.25 mm 且 U-U 合法，目标 Z2 的 blocker 数也没有下降（典型是 1001 与 U182 组：候选距离仍为 0.073 mm），因此不能接受；
4. 更大的加深步长在 U-U/嵌套合法性阶段就被拒绝。

因此 B 退化为 A 的“固定深度升降位置搜索”，没有产生额外的 Z2 恢复。

---

## 4. 逐条恢复清单与 blocker 变化

| Z2 route_id | baseline blockers | A/B 恢复 | 最终 blocker 数 |
|---|---|---:|---:|
| 990 | 78, 86 | 是 | 0 |
| 991 | 352, 376 | 是 | 0 |
| 1018 | 22 | 是 | 0 |
| 1019 | 190 | 是 | 0 |
| 1021 | 197 | 是 | 0 |
| 1022 | 24 | 是 | 0 |
| 1023 | 196 | 是 | 0 |
| 1024 | 195 | 是 | 0 |

A 之后仍有 28 条失败，主要分成三类：

| 失败类型 | 条数 | 代表 | 剩余 blocker 数 |
|---|---:|---|---:|
| 同一端口 XY 轨道（Z1 U 与 Z2 same-side U 共用） | 12 | 1001–1012 | 各 1 |
| 整层/多层 U 过渡同时阻挡 | 6 | 609, 610, 611, 612, 641, 644 | 30–77 |
| 2–5 个局部 blocker | 10 | 977–992 | 1–5 |

**关键物理原因：** 一部分 Z2 same-side 接口线路（例如 1001 E02→E15）与 Z1 人工 U（如 U182）使用完全相同的两个 row 端口 XY；两条 U 的直臂在 XY 上完全重合，仅 z 相差 0.5 mm。Z1 的 S 曲线无论放在直臂的哪个位置，都在同一条 XY 轨道上穿过 z=0.5，因此必然与 Z2 共线；加深 U 只增加沿内法向的深度，不改变这条 near-port 轨道的 y/x 位置，也无法解决。要解决这类线路，必须允许 Z2 或 Z1 的 **XY 侧向偏移**，这超出本实验“固定 Z1 U XY 路径”的变量范围。

---

## 5. L7/L8 集成验证（A 方案）

在 A 的 256 条优化 U + 20 条 Z2 接口成功线路基础上，重新加入现有 255 条 L7/L8 相对边线路：

- L7 南北 127 条、L8 东西 128 条，共 255 条候选；
- 不改变指定层号；
- 只做现有 route 的真实 3D 冲突检查；未对冲突的 L7/L8 做强制 XY 重路由（因此 137 是“现有几何直接加入”的下界，不是重路由上限）。

结果：

| 指标 | 结果 |
|---|---:|
| U 成功 | 256 / 256 |
| 加入前 Z2 接口成功 | 20 / 48 |
| L7/L8 直接加入成功 | **137 / 255** |
| 加入后 Z2 接口成功 | **16 / 48** |
| 丢失的 Z2 线路 | 647, 769, 770, 771 |
| 集成验证违规 | **0** |

**与原来完整 Z1（511 条）固定后 Z2 接口 0/48 对比：**

- 原完整 Z1：0/48 Z2 接口；
- 本轮 A 优化 U + 20 Z2 + 137 条 L7/L8：16/48 Z2 接口；L7/L8 只恢复了 137/255，少于原始 255。
- 这是“接口兼容性提升，但 L7/L8 主体数量下降”的折中；不能宣称整体 1024 全量改善。
- 加入后 Z2 的 16/48 中，有 4 条原 A 成功线路被 L7/L8 阻挡，说明 L7/L8 过渡与 Z2 接口仍存在不可忽略的冲突；需要联合重排 L7/L8 过渡位置/XY 才能进一步提高。

集成输出：`integration_L7_L8/`，其中 `validation.json` 的 violations=0。

---

## 6. 对照表（任务要求格式）

| 指标 | 原始基线 | 实验 A | 实验 B |
|---|---:|---:|---:|
| 人工 U 成功数 | 256 / 256 | 256 / 256 | 256 / 256 |
| Z2 接口成功数 | 12 / 48 | **20 / 48** | **20 / 48** |
| 几何违规 | 0 | 0 | 0 |
| 修改 U 数量 | 0 | 33 唯一 / 47 次改动 | 33 唯一 / 47 次改动 |
| 加深 U 数量 | 0 | 0 | **0** |
| 总深度增加 | 0 | 0 | **0 mm** |
| 升降位置变化 | 0 | 平均 rise +7.51 mm，fall start +7.32 mm | 同 A |
| 总路径长度 | 27682.1481 mm | 27682.1481 mm | 27682.1481 mm |
| 计算时间 | 4.05 s（基线复现） | 316.47 s | 541.43 s |

A/B 的完整数据见 `optimization_summary.json`、`route_changes.csv`、`u_depth_changes.csv`、`transition_position_changes.csv`、`z2_recovered_routes.csv`。

---

## 7. 可视化

`plots/` 中的 10 张真实数据图：

1. `01_u_baseline_3d.png`：原始 256 条人工 U 三维总览；
2. `02_u_experiment_A_3d.png`：A 的三维总览；
3. `03_u_experiment_B_3d.png`：B 的三维总览；
4. `04_u_depth_xy_comparison.png`：U 深度/过渡变化前后 XY 对比（B 实际深度变化 0，突出显示 33 条过渡位置变化）；
5. `05_u_transition_3d_zoom.png`：代表性 U 的 S 曲线三维前后放大；
6. `06_nested_group_coordinated_change.png`：嵌套 U 组联动调整图；
7. `07_z1_z05_crossing_distribution.png`：Z1 U 穿过 z=0.5 的位置分布（512 个过渡穿越点）；
8. `08_z2_interface_recovery_map.png`：48 条 Z2 接口线路恢复地图；
9. `09_original_conflict_vs_adjusted_3d.png`：原始冲突与调整后局部 3D；
10. `10_experiment_metrics.png`：A/B 成功数、深度增加、路径长度对比。

`plots/manifest.json` 记录每张图的数据来源和渲染状态。

---

## 8. 复现方式

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"

# 基线复现（4 s）
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode baseline

# 实验 A（约 316 s）
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode A --max-seconds 600

# 实验 B（约 541 s）
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode B --max-seconds 600

# 汇总与验证
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_finalize
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_extra

# L7/L8 集成
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_integration A

# 图和报告
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_plots --data-dir outputs\manual_c4_new_connectivity\U_DEPTH_TRANSITION_JOINT_OPT
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_report --data-dir outputs\manual_c4_new_connectivity\U_DEPTH_TRANSITION_JOINT_OPT
```

所有 256 条 U 的原始 checkpoint 未修改；A/B 从同一次 baseline 初始化；B 允许深度但实际没有接受任何深度变化。

---

## 9. 局限与下一步

1. 本实验只优化 48 条有二维几何的 Z2 接口线路；20 条无二维几何的接口线路不在本对照内，不能把 48 的结果外推成 68/68。
2. Z2 的 XY 路径在本轮固定；如果允许 Z2 侧向绕行，A/B 的收益可能不同，但这会改变实验变量，本轮没有做。
3. 12 条同端口共轨 same-side 线路在“保持 Z1 U XY 路径不变”的纪律下无法通过深度/过渡位置解决，需要 XY 侧向偏移或端口 row 分离设计。
4. B 的组级深度搜索是有限的步长/候选预算（0.25–8 mm，最多 4 个 plan/深度），没有做全局嵌套组联合优化；结论仅针对当前搜索预算与这份数据。
5. L7/L8 集成只做了现有几何直接加入与真实三维筛选，没有对 118 条失败 L7/L8 做完整局部 XY 重路由；137/255 是直接加入下界，不是最终上限。
6. 所有结果均为 `exploratory_only` 层高 provenance；几何违规为 0，但不是正式工艺验收。
