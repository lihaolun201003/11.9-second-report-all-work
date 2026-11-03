# 1024 通道双向第二轮：12 独立 Z2 目标层 + 目标层驱动 R15 重布

- 日期：2026-11-03
- 前一实验：`bidirectional_1mm_1024_full`（735/1024，Z1 430，Z2 305，0 违规）
- 本轮目录：`experiments/bidirectional_1mm_target_first_1024/`
- 关键原则：人工分组 → 真实目标物理层 → 起点过渡 → 目标层 XY 重布 → 终点过渡 → 完整 3D 验证。

## 结果摘要

| 指标 | 旧 20L | 第一轮 4 层 Z2 | A：12 层冻结 XY | B：12 层 + 目标重布 | C：合法 4 层 + 目标重布 |
|---|---:|---:|---:|---:|---:|
| 总布通 | 673 | 735 | 644 | 726 | **801** |
| Z1 | 511 | 430 | 379 | 395 | **447** |
| Z2 | 162 | 305 | 265 | 331 | **354** |
| 人工 U | 256 | 256 | 247 | 247 | **256** |
| Z2 接口 48 | 0 | 48 | 48 | 48 | **48** |
| Z2 独立目标层 | — | 4 | **12** | **12** | 4 |
| 几何违规 | 0 | 0 | **330916** | **388276** | **0** |
| 最小净空 | 0.08003 | 0.08786 | 违规 | 违规 | **0.0878648** |
| 唯一交叉 | 4357 | 12108 | 7314 | 9952 | 14860 |
| 总长度 | 99814.67 | 109550.57 | 93751.54 | 107091.02 | 119454.65 |

**结论：**
- 12 个独立 Z2 物理层（L8–L19，50 μm 间距）已真实建立并运行；A 330916、B 388276 个真实 3D clearance 违规，`geometry_pass=false`。12 个高度本身不等于合法。
- 目标层 R15 重布有效：B 比 A 多 82 条，C 比第一轮多 66 条。
- 最终合法结果是 **C：801/1024，Z1 447，Z2 354，人工 U 256/256，接口 48/48，0 违规**；12 独立层方案未被宣称成功。
- C 没有丢失第一轮 735 条中的任何一条；恢复 66 条，主要来自原 transition/flat 冲突（53 条）。

## 目录

| 路径 | 内容 |
|---|---|
| `experiment_A/` | 12 个独立 Z2 层 + 冻结旧 XY；644 条，330916 违规 |
| `experiment_B/` | 同一 18 层栈 + R15 目标层重布；726 条，388276 违规 |
| `experiment_C/` | 合法 4 层 Z2 栈 + R15 目标层重布；801 条，0 违规 |
| `routes_l3d.json` / `failed_routes.json` | 最终 C 的 3D 路线与失败线路 |
| `validation.json` | 最终 C 严格验证（0 违规） |
| `final_stats.json` | 最终 C 汇总 |
| `per_layer_stats.json` | 最终 C 逐层统计 |
| `crossings_after.json` | 最终 C 交叉 |
| `assignment_1024.csv` | 最终 C 的实际物理层分配 |
| `logical_to_physical_layers.csv` | 逻辑层/物理层最终映射 |
| `route_change_audit.csv` | 735→801 的逐线路变化 |
| `reroute_summary.json` | C 恢复 66 条明细 |
| `layer_allocation_audit.json` | A/B/C 层数与合法性审计 |
| `glass_geometry.json` / `physical_layer_stack.json` | 最终 C 的 1 mm 物理模型（4 个 Z2 层） |
| `plots/` | 15 张图（12 主图 + 12 层候选/合法、A/B/C、恢复分类） |
| `checkpoints/` | 最终 C checkpoint |
| `report.md` / `comparison.md` | 完整报告与对照 |

## 代码

- `bidirectional_round2_assignment.py`：12 个 Z2 独立候选层 + 6 个 Z1 层。
- `bidirectional_round2_experiment_a.py`：A。
- `bidirectional_round2_recover_a.py`：B。
- `target_layer_router.py`：R15 的 L/opposite 目标层候选 + 联合过渡搜索。
- `bidirectional_round2_recover.py`：C。
- `bidirectional_round2_validate.py` / `_validate_c.py`：A/B 与 C 的严格验证。
- `bidirectional_round2_finalize.py` / `_metadata.py`：审计、统计、最终装配。
- `bidirectional_round2_plots.py`：图。
- `bidirectional_1mm_builder.py` / `bidirectional_1mm_layer_assignment.py`：第一轮合法 4 层基座。
- `code/l3d/validate_l3d.py`：真实 3D `hypot(2d,dz)` 跨平面净空验证。

## 复现

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_assignment
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_experiment_a
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_validate outputs\...\experiment_A\routes_l3d.json outputs\...\experiment_A
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_recover_a
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_recover
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_validate_c
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_finalize
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_metadata
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_round2_plots
```

所有结果 `exploratory_only`；未改端点/配对/分组，未降低 R15/0.08 mm，未突破 1 mm。
