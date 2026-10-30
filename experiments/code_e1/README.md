# E1 实验代码（Z1 优先抬升 + Z2 协同避让）

本目录只收录 **E1 实验新增的代码模块**，与仓库中 `experiments/code_z1/` 的约定一致：
完整工程仍在本地 `OpticalWaveguideRouter2D/`，此处给出可直接对照的 E1 模块源文件。

## 模块说明

| 文件 | 作用 |
|---|---|
| `core.py` | E1 共享核心：数据加载（1024 连接/基线路由）、Z1/Z2 路线分类、S 型升降构建、结构合法性（`World.check_structure`）、全部遮挡/violation 采集与分类、逐物理层严格交叉审计、实验产物落盘 |
| `search.py` | 候选窗口搜索：**只在既有 2D 链的结构性直线区间内**枚举 `(a_in, a_out)`（`_straight_start_windows`），单条/成对/独立三种模式，失败候选记录全部阻挡 route_id |
| `plots.py` | 强制图件生成（01–10 逐层图、contact sheet、before/after、hotspot、transition 图、四边局部放大、Z1/Z2 transition 近失图等），全部来自真实 XYZ |
| `layering.py` | E1-C 分层引擎：共线 Z2 长臂识别、Z2 线束清空到 L6/L7、Z1 C2 对按方向分离（EW→L2、NS→L3）重抬升 |
| `refine.py` | E1-D 精确增量窗口优化器（对任意 1024 路布局做 `(a_in,a_out)` 贪心再优化；接受条件为世界合法且全量唯一交叉不增加） |
| `run_e1a.py` | E1-A：29 个回退 C2 对的阻挡来源诊断（9,570 条候选记录，9,571 行 CSV） |
| `run_e1b.py` | E1-B1/B2：移除全部 Z2 / 只移除可移动 Z2 的诊断实验（仅诊断，标注 not_validated） |
| `run_e1c.py` | E1-C：C1（只调 Z1）/ C2（Z2 单线让路）完整 1024 路实验 |
| `run_e1d.py` | E1-D：D1 接入段分析、D2 非对称窗口、D3 在 E1-C 最优上微调 + Z2 重开窗扩展 |
| `c3_build.py` | E1-C3 实际生成脚本：共线 Z2 长臂清空到 L6 → 29 对净收益短窗口 → `refine.refine` 收敛 |
| `c3_repair.py` | E1-C3 修复脚本：冻结验证器逐轮找 violations 并把相关路线回退到 BASE 几何，直到 violations=0 |
| `verify_z2retune.py` | Lead 独立复核脚本：路由集合/端口身份/逐层交叉/冻结验证器四重校验 best_solution 的来源 |
| `prepare.py` `compare.py` `report.py` `finalize.py` `verify_artifacts.py` | 基线复现、对照表/总图、报告生成、图件补齐与产物验收 |

## 依赖

E1 模块复用工程内既有模块（未在本目录重复）：`four_side_1024/manual_c4/z1_multilayer_150um.py`、
`hybrid_c2_c4.py`、`structured_layer_routing.py`、`four_side_1024/v3c4/lift_cross.py`、
`four_side_1024/fsd25d/path3d.py`、`four_side_1024/l3d/world.py`、
`four_side_1024/fslw/validate_fslw.py`、`four_side_1024/fsd25d/world25d.py`、
`four_side_1024/d56/index.py`。`code_z1/` 中已包含其中与 Z1 相关的主要文件。

## 复现入口（工程根目录，Python 3.10）

```bash
python -m four_side_1024.e1.prepare          # 复现 BASE 指标 6,078 与全套基线图
python -m four_side_1024.e1.run_e1a          # E1-A 阻挡诊断
python -m four_side_1024.e1.run_e1b          # E1-B1/B2 诊断
python -m four_side_1024.e1.run_e1c c1       # E1-C1（c2 为 C2）
python scratch_e1/c3_final_v2.py             # E1-C3（清空共线 Z2 → 短窗口 → refine）
python scratch_e1/repair_c3b.py              # E1-C3 验证器回退修复（violations → 0）
python -m four_side_1024.e1.run_e1d          # E1-D D1/D2（D3 需先有 E1-C 结果）
python scratch_e1/verify_z2retune.py         # 复核 D3+Z2retune 扩展（3,594）
python -m four_side_1024.e1.compare          # comparison.csv/png + best_solution
python -m four_side_1024.e1.report           # 实验报告
```
