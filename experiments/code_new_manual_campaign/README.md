# 新人工布线 CSV 战役代码（1024 通道 / 5–15 层 / 严格 C4）

本目录收录 "全新人工布线 CSV → 1024 通道多层实验" 的可复现脚本。工程完整代码仍在
本地 `OpticalWaveguideRouter2D/four_side_1024/`（复用冻结的 2D/3D 引擎与验证器）。

| 文件 | 作用 |
|---|---|
| `build_inputs.py` | 读取两份 section2 CSV：Z1 512 条直接接入；Z2 128 条四元基础做 row1→row2 端口重映射 + C4(90/180/270) 展开为 512 条；合并 1024、写 connectivity_1024.csv/json、input_validation.json 并做 35 项严格校验 |
| `run_phase2_new.py` | phase-2 严格 C4 2D 布线（D56 固定框架 + same-side U 模板，原子四元组提交，冻结 fslw strict 审计）；初始 easy 顺序 |
| `run_phase2_order.py` | 可按不同 group 顺序/预算重跑单平面（用于顺序筛选） |
| `run_phase2_screen.py` | 顺序筛选脚本（same_first / adjacent_first / opposite_first / frame_easy / csv） |
| `repair_phase2.py` | 用扩展的 same-side U bulge 档位（0.25 mm 步进）+ 大预算对失败组做合法修复；修复后 Z1 达到 512/512 |
| `repair_phase2_more.py` | 更细 bulge 档位多轮修复（Z2 补充尝试） |
| `select_phase2.py` | 选每平面最佳布局（含 R15 弧度守卫），合并为 phase2_2d_selected 并写 combine/validation |
| `run_layer_sweep.py` / `run_sweep_selected.py` | 5/7/9/11/13/15 层三维层扫：L2=0.65 mm、+0.15 mm/层；同一 2D 输入、同一 crossing-lift 算法；运行时把 `ROUTING_LAYER_IDS` 动态扩展到 Ln 并同步冻结验证器 |
| `finalize_campaign.py` | 层扫汇总、逐路线/逐层 CSV、层图、总体 2D/3D 图、交叉热点图、Z2 严格 C4 审计、best_solution |
| `analyze_u_bundle.py` | U 型线束统计、层可举升性、失败组隔离测试（区分冲突受限/模板受限） |
| `make_report.py` / `make_github_section.py` | 自动生成技术报告与 GitHub README 章节 |

## 运行顺序（项目根，Python 3.10）

```bash
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/build_inputs.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/run_phase2_new.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/run_phase2_screen.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/repair_phase2.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/select_phase2.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/run_sweep_selected.py 7,9,11,13,15 480
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/finalize_campaign.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/analyze_u_bundle.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/make_report.py
```

## 关键实现注意

- **必须先调用 `four_side_1024.v3c4.profile.apply()`**（在导入/构建几何前），否则
  candext/框架会使用旧默认半径（R40）而不是 R15；本轮修复脚本曾因此产生 R40 弧，
  已通过入口处 apply_profile 修正。
- 层数 > 5 时必须同时扩展三处常量：`lift_cross.LAYER_IDS`、
  `l3d.layers.ROUTING_LAYER_IDS`、`l3d.validate_l3d_multi.ROUTING_LAYER_IDS`
  （最后一个由冻结验证器注释明确要求 caller 动态扩展），否则会出现
  `KeyError(6)` 或 `layers_unexpected:[6,7]`。
- 未布通路线保持 `status=failed` 并记录原因，不参与 3D 层扫结果；不存在“伪造合法”。
