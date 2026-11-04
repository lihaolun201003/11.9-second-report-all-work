# NATIVE_3D_CROSSING_OPT_1024 — 多高度主体（中途换层）布线实验

本目录是“允许光波导主体中途改变高度”的 Native 3D 实验的完整结果，包括 A（单线换层）、B（批量避让）、C（全局优化）三个递进实验。

## 组织

* `experiment_A/` — A0 几何单元测试、A1 真实 1024 通道扫描、A2 单线换层结果（独立 Validator PASS）
* `experiment_B/` — 四策略对比、批量换层结果、候选与失败记录（独立 Validator PASS）
* `experiment_C/` — 全局自动优化最终接受解、逐阶段 checkpoint、历史与换层统计
* 根目录交付：`routes_l3d.json`（最终 1024 条多高度路径）、`crossing_stats.json`（真实同层交叉逐事件记录）、`validation.json`（独立 Validator）、`optimization_history.csv`、`transition_stats.json`、`failed_attempts.json`、`plots/`、`MANIFEST.json`、`report.md`、`comparison.md`
* `analysis/` — 交叉沿路径分布与换层区间可行性分析

## 复现

```
cd OpticalWaveguideRouter2D
.venv\Scripts\python.exe -m four_side_1024.fanout1024.native3d.run_a
.venv\Scripts\python.exe -m four_side_1024.fanout1024.native3d.run_b --sample 30 --batch 80
.venv\Scripts\python.exe -m four_side_1024.fanout1024.native3d.global_optimizer
.venv\Scripts\python.exe -m four_side_1024.fanout1024.native3d.validate_native3d --run-dir <该目录>
```
E5 基线为只读输入：`outputs/manual_c4_new_connectivity/NON_C4_CROSSING_OPT_1024/E5_joint_repair_final`。

