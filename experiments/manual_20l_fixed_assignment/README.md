# 2026-11-03 最终 L1–L20 人工指定分层实验（MANUAL_20L_FIXED_ASSIGNMENT_FULL）

本目录是第三轮“人工优先”实验的最终归档，基于 `OpticalWaveguideRouter2D` 项目实际运行结果。

## 一、结果摘要

| 指标 | 结果 |
|---|---:|
| 总连接数 | 1024 |
| 成功布通 | **673 / 1024 (65.7%)** |
| Z1 成功 | **511 / 512** |
| Z2 成功 | **162 / 512** |
| Z1 人工 U 到 L2–L5 | **256 / 256（64/64/64/64）** |
| Z1 南北相对边到 L7 | **127 / 128** |
| Z1 东西相对边到 L8 | **128 / 128** |
| Z2 到 L9–L20 | **162 / 444** |
| Z2 接口面 z=0.5 | **0 / 68** |
| 真实三维验证违规 | **0** |
| 全局唯一交叉对 | **4357** |
| Z1×Z1 / Z2×Z2 / Z1×Z2 | 3805 / 552 / 0 |
| 最小三维净空 | 0.08003 mm |
| 最小曲率半径 | 15.0 mm |

结论：20 层定义、256 条人工 U 真实抬升、L7/L8 相对边主体均已完成并通过真实三维验证；Z2 高层利用不足，主要瓶颈是 Z1/Z2 共用端口 XY 轨道在 z=0.5 平面的真实三维冲突，以及固定 Z1 先布导致 Z2 的 R15 逃逸空间不足。

**交叉数 4357 低于 75794，但不能据此宣称改善**：成功线路从 992 降到 673。共同成功集（673 条）上旧基线 52104 → 本轮 4357，per-route 77.42 → 6.47；仍需同时报告成功率下降。

详细分析见 [`report.md`](report.md) 与 [`comparison.md`](comparison.md)。

## 二、目录内容

| 路径 | 内容 |
|---|---|
| `report.md` | 完整实验报告（层定义修正、人工 U 重建、L7/L8、Z2 分层、验证、交叉、失败分析、复现） |
| `comparison.md` | 旧 15L 基线 / 上一轮 15L 人工优先 / 本轮 L1–L20 三组对照（含共同成功集口径） |
| `layer_stack.json` | L1–L20 权威层栈（L2=0.65, 步距 0.15, L20=3.35） |
| `z1_assignment_audit.csv` / `z2_assignment_audit.csv` | 1024 条连接的逐条目标层审计（含 296 条双端层冲突） |
| `routes_l3d.json` | 1024 条记录（673 routed + 351 failed）的真实三维几何 |
| `failed_routes.json` | 351 条失败线路及原因 |
| `validation.json` | 仓库完整 3D 验证器结果（0 违规） |
| `crossings_after.json` | 4357 唯一交叉对 / 4950 交叉点及逐层统计 |
| `final_stats.json` / `layer_stats.json` | 全局与逐层指标 |
| `route_decisions.csv` | 逐条 routed/failed、目标层、实际层、长度 |
| `plots/per_layer/` | L1(z1)、L1(z2)、L2–L20 共 21 张逐层图（含空 L6，显式标注 0 routes） |
| `plots/layer_contact_sheet.png` | 21 层拼图总览 |
| `plots/thematic/` | 11 张专题图（人工 U、L2–L5 对比、L7/L8、Z2 L9–L20、接口残余、完整 3D、过渡放大、逐层柱状图、新旧交叉对比） |
| `checkpoints/z1/` | 最终 511 条 Z1 route/primitives 几何 checkpoint |
| `checkpoints/z2/` | 最终全部已布通 route/primitives checkpoint（含 Z1，finalize 会取 plane=z2） |
| `code/` | 本轮新增/修改的核心代码与从零重跑脚本 |
| `analysis/z2_order_experiment_REPORT.md` | 独立 Z2 顺序/策略对照实验（Z1-first vs Z2-first、接口面空平面可行性等） |

## 三、复现

```powershell
cd "C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D"

# 1) 权威层分配
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.manual_20l_assignment

# 2) 从 checkpoint 重新组装、验证、交叉统计
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.finalize_20l `
  --z1-dir outputs\manual_c4_new_connectivity\MANUAL_20L_FIXED_ASSIGNMENT_FULL\checkpoints\z1 `
  --z2-dir outputs\manual_c4_new_connectivity\MANUAL_20L_FIXED_ASSIGNMENT_FULL\checkpoints\z2

# 3) 逐层图 / 专题图 / report.md / comparison.md
.\.venv\Scripts\python.exe -m four_side_1024.manual_c4_adapt.plots_20l `
  --out-dir outputs\manual_c4_new_connectivity\MANUAL_20L_FIXED_ASSIGNMENT_FULL
```

完整从零重跑的脚本链保存在 `code/pipeline_scripts/`：

1. `proto_phaseB.py`：256 条人工 U 隔离构造（L2–L5）。
2. `proto_phaseC5.py`：Z1 相对边基础构造。
3. `repair_z1.py` → `repair_210.py` → `repair_all_z1.py` → `repair_final_z1.py`：验证器驱动的 Z1 局部重建链，最终 511/512、0 违规。
4. `build_z2_high.py`：Z2 高层固定层构造（162/444）。
5. `finalize_20l.py`：最终组装 / 完整验证 / 交叉统计。
6. `plots_20l.py`：逐层与专题出图、报告生成。

## 四、关键代码修改

- 新增 `manual_20l_assignment.py`：L1–L20 权威层表、Z1 256 人工 U 旧 L1–L4→新 L2–L5 映射、L7/L8 分类、Z2 连接器分组与源端优先规则、`z1_assignment_audit.csv` / `z2_assignment_audit.csv`。
- 新增 `fixed_layer_3d.py`：先定目标层再生成真实 S 曲线/直臂/主体；R15 过渡窗口；真实三维近似准入 + 仓库严格验证器最终门禁；`ApproxClearance` 快速空间索引。
- 修改 `four_side_1024/l3d/validate_l3d.py`：新增 `set_routing_layer_ids()` / `reset_routing_layer_ids()`，将验证器路由层集合从固定 L2–L5 扩展为可配置 L2–L20（默认行为不变）。归档副本：`code/validate_l3d_modified.py`。
- 新增 `finalize_20l.py`：组装 1024 条 payload、标记失败、运行完整验证器、按物理高度统计交叉、输出所有最终 JSON/CSV。
- 新增 `plots_20l.py` / `report_20l.py`：21 个物理平面的逐层图（空层显式 0 routes）、11 张专题图、报告。
- 修正旧版问题：L1 的 64 条人工 U 不再作为 z=0 平面 U；256 条全部重建真实升降段；L7/L8 严格按本轮层号；L20 进入层栈、路径构造、验证器和出图；失败线路不进入 routed 集合。

## 五、诚实性说明

- 351 条失败线路全部保留失败原因，没有通过降低 R15 / 0.08 mm 净空、回退接口层或缩小层间距计入成功。
- 验证器最终 0 违规；成功线路均有真实 three-D parts 和真实 z 高度。
- 本实验的层高 provenance 为 `unconfirmed_simulation`，验证器状态为 `exploratory_only`；不是正式工艺验收。
