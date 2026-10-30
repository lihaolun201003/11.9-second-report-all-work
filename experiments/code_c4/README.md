# C4 实验代码（严格四元旋转对称多层三维布线）

本目录只收录 **C4-SYMMETRIC 实验新增的代码模块**，与仓库中 `experiments/code_z1/`、
`experiments/code_e1/` 的约定一致：完整工程仍在本地
`OpticalWaveguideRouter2D/four_side_1024/`，此处给出可直接对照的 C4 模块源文件。

## 模块说明

| 文件 | 作用 |
|---|---|
| `layers.py` | C4 层栈：Z1=0、Z2=0.5、L2=0.65 起 0.15 mm 间距到 **L13=2.30**；`stack_payload(max_layer)`、`layer_z()`、S 型升降足迹/几何、13 层冻结验证器包装 |
| `orbits.py` | 256 个 C4 轨道（连接表 group 即轨道）：旋转映射/方向（forward/reversed）、精确旋转基元、旋转一致的窗口映射 `member_windows`（反向时 a_in/a_out 互换）、轨道构建 `build_orbit`、结构性直线窗口枚举、平铺基线、布局组装 |
| `engine.py` | 精确增量交叉引擎：预计算 1024 条冻结 2D 链之间 91,536 个交点事件；按物理高度唯一化求和，与 E1 `core.audit` 口径一致（合法布局逐次校验 0 差异）；13 层碰撞世界 `make_world` |
| `optimize.py` | 轨道级贪心优化：候选层/窗口生成、以"同层 D56 + 0.08 mm 三维净空 + 自净空 + 四元内部净空"为合法性、以精确全局唯一交叉下降为接受条件；支持 utility 迁移（先清空阻挡 Z1 走廊的 Z2 长臂）与顺序构造式多遍 |
| `validate.py` | **独立严格 C4 验证器**（任务书 §4.3）：轨道完整性、端口旋转、层/升降段/几何对称、最大 XYZ 偏差；`validate_layout` / `validate_file`；可独立审计任意 1024 路布局 |
| `plots.py` | C4 科学可视化：每组 10 张强制图（01–10，含四元组展示与旋转重合验证、逐层 contact sheet、C4 审计图）+ 4 张层数对比汇总图 |
| `run_c4.py` | 实验驱动：C4-BASE + 7/9/11/13 层优化、冻结验证器修复（回退违规轨道直到 violations=0）、完整产物落盘、best_solution、comparison、汇总图 |
| `report_c4.py` | 报告生成（experiment_report.md 与 docs/reports 技术报告同源） |

## 关键几何定义

- 旋转：`R(x, y, z) = (150 - y, x, z)`，绕板中心 (75,75)，**z 不变**；R⁴ = 恒等。
- 轨道窗口一致性：若 `R^k(rep)` 与成员的实际走向相反，成员窗口取 `(a_out, a_in)`；
  这样四元的真实三维中心线严格旋转等价（实测偏差 ~1e-13 mm）。
- 交叉统计：每个物理高度上按"无序路线对"唯一化后求和；交叉事件与唯一对分别统计。

## 依赖

复用工程既有模块（未重复）：`four_side_1024/e1/core.py`（数据/构建/审计/合法性）、
`four_side_1024/l3d/world.py`、`four_side_1024/fslw/validate_fslw.py`、
`four_side_1024/fsd25d/world25d.py`、`four_side_1024/d56/index.py`、
`four_side_1024/v3c4/lift_cross.py`、`four_side_1024/manual_c4/z1_multilayer_150um.py`。

## 复现入口（工程根目录，Python 3.10）

```bash
python -m four_side_1024.c4.run_c4                 # 全部层数实验（7/9/11/13）
python -m four_side_1024.c4.run_c4 --layers 13     # 单层数
python -m four_side_1024.c4.report_c4              # 报告
python four_side_1024/c4/validate.py <routes_1024.json> --out-dir <dir>   # 独立 C4 审计
```

> 说明：低交叉候选可能包含少量使冻结验证器三维净空略低于阈值的路线（其稠密采样
> 比快速碰撞世界更严格）；`run_c4.repair_frozen` 以"整轨道回退到接口平铺"的方式
> 修复到 violations = 0，回退清单保存在 `summary.json` 的
> `repair_reverted_orbit_ids` 中。
