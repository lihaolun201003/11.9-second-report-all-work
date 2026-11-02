# 本轮新增/修改代码说明

本目录保存 `OpticalWaveguideRouter2D` 项目中与本轮实验直接相关的代码副本。

## 核心模块

| 文件 | 作用 |
|---|---|
| `manual_20l_assignment.py` | 权威 L1–L20 层表；Z1 256 人工 U 的旧 L1–L4→新 L2–L5 映射；L7/L8 分类；Z2 连接器分组与源端优先分配；生成 `z1_assignment_audit.csv` / `z2_assignment_audit.csv` / `layer_stack.json` |
| `fixed_layer_3d.py` | 固定目标层 3D 路径构造；R15 S 曲线升降窗口；`ApproxClearance` 快速 3D 空间索引；`try_fixed_route` / `fixed_manual_u_search`；先定层再生成几何 |
| `finalize_20l.py` | 组装 1024 条 payload；失败记录；完整验证器；按物理高度交叉统计；`final_stats.json` / `failed_routes.json` / `route_decisions.csv` |
| `plots_20l.py` | 21 个物理平面逐层图（L1 z1、L1 z2、L2–L20；空 L6 显式 0 routes）、接触表、11 张专题图 |
| `report_20l.py` | 纯 JSON 驱动的 `report.md` / `comparison.md` 生成器 |
| `validate_l3d_modified.py` | 修改后的完整验证器副本；新增 `set_routing_layer_ids()` / `reset_routing_layer_ids()`，默认仍是 L2–L5，L1–L20 实验显式激活 L2–L20 |

## 与项目原代码的关系

- 未重写整套路由系统；复用 `fsd25d.path3d`、`v3c4.lift_cross`、`l3d.world`、`d56.index`、`r15.profile_r15`、`manual_u_geometry`、`fslw.validate_fslw`。
- `validate_l3d.py` 的默认常量 `ROUTING_LAYER_IDS=(2,3,4,5)` 保持不变；新增的可配置集合 `ACTIVE_ROUTING_LAYER_IDS` 只在调用 `set_routing_layer_ids(range(2,21))` 时切换，避免破坏旧实验。
- 新增/修改的代码已在最终 `finalize_20l.py` 中组合运行；最终结果见上级目录的 `routes_l3d.json` / `validation.json` / `final_stats.json`。

## pipeline_scripts

从零重跑时的分阶段脚本（对应实验报告第 12 节）：

1. `proto_phaseB.py` — 256 条人工 U（L2–L5），输出 `MANUAL_LAYERS_20L_PROTO`。
2. `proto_phaseC5.py` — Z1 相对边 L7/L8 基础构造，输出 `MANUAL_LAYERS_20L_PROTO_C5`。
3. `repair_210.py` / `repair_z1.py` / `repair_all_z1.py` / `repair_final_z1.py` — 验证器驱动的局部重建链，最终 `MANUAL_LAYERS_20L_PROTO_C5R4`（511/512、0 违规）。
4. `build_z2_high.py` — Z2 L9–L20 高层构造，输出 `MANUAL_LAYERS_20L_PROTO_Z2H`（162/444）。
5. `finalize_20l.py` — 组装并验证 1024 条记录。
6. `plots_20l.py` — 出图与报告。

这些脚本路径沿用开发时目录（`scratch/...`），复现时建议直接用上级目录的 `checkpoints/`；从零重跑需要保证中间目录名一致。
