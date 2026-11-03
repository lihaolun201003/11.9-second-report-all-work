# 1 mm 玻璃双向 1024 通道三维布线实验

- 日期：2026-11-03
- 物理模型：玻璃总厚度 **1.000 mm**，`z_min=-0.25`、`z_max=+0.75`；Z1 接口 z=0，Z2 接口 z=0.5 不变。
- 工艺最小层距 `0.05 mm`，真实 3D 净空仍为 **0.08 mm**，R15 不变。
- 实际布层：10 个路由物理层（L2–L11），Z1 2 层向下、2 层人工 U + 2 层相对边在中间；Z2 1 层中间 + 3 层向上 + 接口层。
- 全部 1024 条线路实际重建并放入同一个真实 3D world，使用严格验证器；不是层号重标或理论容量计算。

## 最终结果

| 指标 | 旧 20 层单向 | 新 1 mm 双向 |
|---|---:|---:|
| 玻璃厚度/高度跨度 | 3.35 mm | **1.00 mm** |
| 物理路由层 | 20 | 10 |
| 最小层距 | 150 μm | 80 μm（允许下限 50 μm） |
| Z1 布通 | 511/512 | **430/512** |
| Z2 布通 | 162/512 | **305/512** |
| 总布通 | 673/1024 | **735/1024（+62）** |
| 人工 U | 256/256 | **256/256** |
| Z2 接口 48 条 | 0/48 | **48/48** |
| 几何违规 | 0 | **0** |
| 最小 3D 净空 | 0.0800278 mm | **0.0878648 mm** |
| Z1×Z2 交叉 | 0 | **0** |
| 总唯一交叉 | 4357 | 12108 |
| 共同 548 条交叉 | 2197 | **4201（未降低）** |
| 实际 z 范围 | 0..3.35 | **−0.18..+0.74** |

**结论：** 1 mm 内可以重新容纳全部 1024 条拓扑，总布通从 673 提升到 735（+9.2%），Z2 从 162 提升到 305（+143），Z2 接口从 0/48 恢复到 48/48，Z1×Z2 交叉保持 0，0 几何违规。但 Z1 从 511 降到 430（−81），且共同成功集合交叉从 2197 升到 4201；不能宣称全面提升或降低交叉。

## 目录

| 路径 | 内容 |
|---|---|
| `glass_geometry.json` | 1 mm 玻璃边界、接口、层距、净空、实际层高 |
| `physical_layer_stack.json` | L1–L11 物理层栈 |
| `logical_to_physical_layers.csv` | 逻辑层到物理层的映射与布通统计 |
| `assignment_1024.csv` | 全部 1024 条线路的最终物理层/区域/方向 |
| `routes_l3d.json` | 735 条成功线路的真实三维几何 |
| `failed_routes.json` | 289 条失败线路及原因 |
| `validation.json` | 严格三维验证（0 违规） |
| `crossings_after.json` | 全部唯一交叉与逐层统计 |
| `per_layer_stats.json` | 每个物理层分配/布通/交叉 |
| `final_stats.json` | 最终汇总指标 |
| `route_decisions.csv` | 逐线路决定与状态 |
| `repair_summary.json` | Phase 5 重分配修复 31 条明细 |
| `report.md` / `comparison.md` | 完整报告与新旧对照 |
| `plots/` | 12 张真实几何图 + `manifest.json` |
| `checkpoints/` | 构建 checkpoint（路线、原语、阶段结果） |
| `run.log` | 组合运行日志 |

## 关键实现

- `bidirectional_1mm_layer_assignment.py`：10 个物理层、Z1/Z2 逻辑组映射。
- `bidirectional_1mm_builder.py`：负 z 和正 z 的真实 S 过渡重建，逐条通过 `ClearanceWorld3D`。
- `bidirectional_1mm_repair.py`：失败线路在合法物理层间有界重分配；不改端点/拓扑/R15/净空。
- `bidirectional_1mm_finalize.py`：严格验证、交叉、逐层统计。
- `bidirectional_1mm_plots.py`：12 张图。
- `code/l3d/validate_l3d.py`：修正跨平面 flat-flat 净空检查为真实 3D `hypot(2d,dz)`，这是本实验 50 μm/负 z 模型能正确验证的关键。
- 未降低 0.08 mm 净空、未改 R15、未改端点/配对/逻辑分组、未用层号代替真实 z。

## 复现

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_1mm_layer_assignment
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_1mm_builder
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_1mm_repair
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_1mm_finalize
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_1mm_plots
```

验证状态：`exploratory_only`（接口距玻璃表面实际位置尚未确认）。
