# 修正 50 μm 规则后的 1 mm 玻璃 1024 通道双向布线实验

- 日期：2026-11-03
- 前序：`bidirectional_1mm_target_first_1024`（旧规则 801/1024）
- 本轮目录：`experiments/bidirectional_1mm_50um_corrected_full/`
- 核心：删除未经确认的全局 80 μm 净空硬门槛；按已确认的 **1 mm 玻璃、Z1=0、Z2=0.5、50 μm 最小层距、上下双向** 重新验证与重建。

## 结果摘要

| 指标 | 旧 12 层 A | 旧 12 层 B | 旧合法 C（旧规则） | 新 B（18 层重建） | 新 C（最终） |
|---|---:|---:|---:|---:|---:|
| 布通 | 644 | 726 | 801 | **723** | **809** |
| Z1 | 379 | 395 | 447 | 391 | **416** |
| Z2 | 265 | 331 | 354 | 332 | **393** |
| 人工 U | 247 | 247 | 256 | **256** | **256** |
| Z2 独立目标层 | 12 | 12 | 4 | **12** | **12** |
| 最小层距 | 50 μm | 50 μm | 80 μm | 50 μm | 50 μm |
| 新规则违规 | 9957 | 11777 | 0（旧规则） | **0** | **0** |
| 最小净空 | — | — | 0.08786 | 0.052673907 | 0.052673907 |
| 唯一交叉 | 7314 | 9952 | 14860 | 9122 | 11798 |
| 总长度 mm | 93751.54 | 107091.02 | 119454.65 | 108960.60 | 122367.92 |

**最终合法结果：809/1024，Z1 416，Z2 393，人工 U 256/256，Z2 接口 48/48，0 违规，最小真实 3D 净空 0.052673907 mm。**

旧 80 μm 规则下 330916/388276 个违规，在新 50 μm 规则下分别降到 9957/11777；但旧 12 层栈的 `.48/.53` 距 Z2 接口仅 20/30 μm，仍不合格，因此旧 A/B 仍不是合法结果。

## 新默认规则

- 不同物理平面：`|dz| >= 0.05 mm` 合法；XY 重合不再因跨层非法。
- 同一物理平面：使用原有二维 D56/受控交叉规则，不把旧全局 80 μm 混入同层。
- 过渡 vs 其他波导：真实 3D 距离 `<0.05 mm` 才拒绝；真实穿透仍非法。
- 物理层栈：每个相邻路由层/接口平面间距 `>=0.05 mm`。
- 旧 80 μm 仅保留为 `legacy_80um` 复现模式。

同时修复在线 world：`CrossingLifter` 现在把 clearance 传给 `World`，并在 `World.check_route` 中在线检查不同平面的层距；最终 validator 与在线 world 对 50/49 μm 边界一致。

## 目录

| 路径 | 内容 |
|---|---|
| `process_rules.json` | 本轮工艺规则 |
| `clearance_rule_audit.md` | 0.08/0.05 使用点分类与修复审计 |
| `validator_consistency_tests.json` | 最小几何测试（50/49/60/80 μm 等） |
| `old_A_revalidation.json` / `old_B_revalidation.json` | 旧 A/B 不改几何的 80→50 μm 重新验证 |
| `glass_geometry.json` / `physical_layer_stack.json` | 1 mm、18 主体层（6 Z1 + 12 Z2） |
| `experiment_A/` | 旧 A 重新验证 |
| `experiment_B/` | 18 层从空 world 重建：723/1024，0 违规 |
| `experiment_C/` | B + R15 目标层恢复：809/1024，0 违规 |
| `routes_l3d.json` / `failed_routes.json` / `validation.json` | 最终 C |
| `final_stats.json` / `per_layer_stats.json` / `crossings_after.json` | 最终统计 |
| `route_change_audit.csv` / `reroute_summary.json` | B→C 变化与 86 条恢复 |
| `plots/01..15` | 18 层截面、50 μm XY 重合合法实例、规则对照、A/B/C、809 条总览 |
| `checkpoints/` / `run.log` | checkpoint 与日志 |

## 代码

- `glass_1mm_process_rules.py`
- `bidirectional_50um_assignment.py`
- `bidirectional_50um_experiment_b.py` / `_experiment_c.py`
- `bidirectional_50um_validate.py` / `_finalize.py` / `_tests.py` / `_plots.py`
- `target_layer_router.py`
- `bidirectional_1mm_builder.py` / `bidirectional_1mm_layer_assignment.py`
- `code/l3d/validate_l3d.py`、`code/l3d/world.py`、`code/v3c4/lift_cross.py`

## 复现

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_assignment
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_tests
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_experiment_b
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_validate outputs\...\experiment_B\routes_l3d.json outputs\...\experiment_B --assignment outputs\...\assignment_1024.csv
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_experiment_c
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_validate outputs\...\experiment_C\routes_l3d.json outputs\...\experiment_C --assignment outputs\...\assignment_1024.csv
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_finalize
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.bidirectional_50um_plots
```

所有结果 `exploratory_only`；未改端点/配对/分组，未降低 R15，未突破 1 mm。
