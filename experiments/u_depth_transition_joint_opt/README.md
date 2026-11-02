# 自适应 U 型深度 + S 型升降位置联合优化实验

- 日期：2026-11-03
- 基线：`MANUAL_20L_FIXED_ASSIGNMENT_FULL` 的 256 条人工 U（L2–L5）checkpoint
- 目标：不改变 256 条 U 的真实端点、配对、分组、目标层、R15、0.08 mm 净空和 150×150 mm 板面，只优化 `(U 深度 d, 上升位置 s_rise, 下降位置 s_fall)`，观察 48 条有二维几何的 Z2 接口线路的成功数是否改善。

## 核心结果

| 指标 | 原始基线 | 实验 A（固定深度） | 实验 B（允许加深） |
|---|---:|---:|---:|
| 人工 U 成功 | 256 / 256 | 256 / 256 | 256 / 256 |
| Z2 接口成功 | **12 / 48** | **20 / 48** | **20 / 48** |
| 恢复 Z2 线路 | — | 990, 991, 1018, 1019, 1021, 1022, 1023, 1024 | 同 A |
| 几何违规 | 0 | 0 | 0 |
| 修改 U | 0 | 33 唯一 U / 47 次改动 | 同 A |
| 加深 U | 0 | 0 | **0** |
| 总深度增加 | 0 | 0 | **0 mm** |
| 平均上升/下降位置后移 | 0 | +7.51 mm / +7.32 mm | 同 A |
| 总 U 路径长度 | 27682.1481 mm | 27682.1481 mm | 27682.1481 mm |
| 计算时间 | 4.05 s（复现） | 316.47 s | 541.43 s |

**结论：**
- 仅移动两端 S 型过渡位置（A）可把 Z2 接口兼容性从 12/48 提升到 20/48，全部 256 条 U 合法、0 违规。
- 允许加深 U（B）没有找到任何合法深度改善；`deepened_u=0`，B 实际接受的改动与 A 完全相同。深度假设在本数据集/本搜索预算下未获支持。
- 12 条同端口共轨 same-side Z2 线路（1001–1012）在不改变 Z1 U 的 XY 路径时无法通过深度/过渡位置解决；必须做 XY 侧向偏移或端口行分离设计。

## L7/L8 集成（A 方案）

| 指标 | 结果 |
|---|---:|
| 优化 U | 256 / 256 |
| 加入 L7/L8 前 Z2 接口 | 20 / 48 |
| L7/L8 直接加入成功 | **137 / 255** |
| 加入后 Z2 接口 | **16 / 48**（丢失 647, 769, 770, 771） |
| 集成验证违规 | 0 |

原始完整 Z1（511 条）固定后 Z2 接口为 0/48；本集成把 Z2 接口提高到 16/48，但 L7/L8 只恢复 137/255，属于“接口兼容性提升、L7/L8 数量下降”的折中，不能作为 1024 全量改善结论。

详细分析见 [`report.md`](report.md) 与 [`comparison.md`](comparison.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `baseline/` | 256 U + 48 Z2 接口基线（12/48，0 违规），含 blocker/validation |
| `experiment_A_fixed_depth/` | A：U 几何、改动 CSV、Z2 结果、0 违规验证 |
| `experiment_B_adaptive_depth/` | B：同 baseline 的加深搜索；0 条加深，成功与 A 相同 |
| `integration_L7_L8/` | A 方案 + L7/L8 集成；137/255，Z2 16/48，0 违规 |
| `optimization_summary.json` | baseline/A/B/integration 汇总指标 |
| `route_changes.csv` | A/B 逐次 U 改动 |
| `u_depth_changes.csv` | B 深度变化（本实验为空） |
| `transition_position_changes.csv` | A/B 升降位置变化 |
| `z2_recovered_routes.csv` | 8 条恢复线路及 baseline blocker |
| `blocker_analysis.json` | baseline/A/B blocker 对比 |
| `validation.json` | baseline/A/B/integration 验证汇总（均 0 违规） |
| `plots/` | 10 张真实数据图（原始/A/B 3D、深度/过渡对比、嵌套组、z=0.5 穿越、Z2 恢复、冲突局部、A/B 指标） |
| `plots/manifest.json` | 图数据来源与渲染状态 |
| `run_A.log` / `run_B.log` / `run_integration.log` / `run.log` | 运行日志 |
| `code/` | 本轮新增/修改代码副本 |

## 复现

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"

.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode baseline
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode A --max-seconds 600
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_depth_transition_optimizer --mode B --max-seconds 600
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_finalize
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_extra
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_integration A
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_plots --data-dir outputs\manual_c4_new_connectivity\U_DEPTH_TRANSITION_JOINT_OPT
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.u_opt_report --data-dir outputs\manual_c4_new_connectivity\U_DEPTH_TRANSITION_JOINT_OPT
```

## 代码说明

- `u_depth_transition_optimizer.py`：加载 256 U、嵌套关系、目标层；参数化深度与两端 S 位置；真实 3D 检查；局部冲突驱动搜索；支持 A/B 和组级回退。
- `u_opt_integration.py`：A 优化 U + Z2 接口 + 现有 L7/L8 的真实 3D 集成检查。
- `u_opt_finalize.py` / `u_opt_extra.py`：汇总 CSV/JSON、补全 baseline 元数据。
- `u_opt_plots.py` 10 张真实数据图；`u_opt_report.py` 纯 JSON 报告生成器。
- `fixed_layer_3d.py`：本实验复用的固定层 3D 构造器（新增 `check_plane` 开关）。
- 未修改 checkpoint、原始配对、目标层、R15、0.08 mm 净空；未删除任何 U。
