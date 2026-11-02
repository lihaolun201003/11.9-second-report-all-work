# 修订版 Z2 CSV 的 1024 通道实验（1000/1024 新纪录）

> 本报告由 `make_report_z2rev.py` 从真实运行产物自动生成。输入 CSV 已由用户在
> 2026-11-02 更新（Z2 方向修正）；本轮不改动该 CSV 的任何连接关系，只做端口
> row1→row2 映射与严谨性校验。

## 一、结论摘要

- 修订版 Z2 输入校验通过：512 行已是 C4 展开表、1024 个 z2 端口各用一次、
  相邻 400 + 同侧 U 112、C4 闭环 0 缺失；与 Z1（未变）合并后 1024 连接 /
  2048 端点 / 256 个 C4 组，冻结校验 35 项全过。
- **2D 严格 C4 布线：1000/1024**（Z1 512/512，Z2 **488/512**），
  **旧版为 992/1024**；Z2 修复轮比旧版多布通 2 个 C4 组（8 条）。
- **15L 三维层扫：1000/1024，violations = 0**，全局唯一交叉 **78836** 对
  （旧版 992/1024 时为 75794 对）。
- Z2 严格 C4 三维审计：**PASS**（122 个完整四元组，6 组不完整；
  最大 XYZ 偏差 4.0194366942304644e-14 mm）。
- 相对 2D 基线的交叉降低率：新版 0.352（旧版 0.3508）——
  抬升效率没有变差；交叉绝对值更高是因为多布通 8 条且 2D 布局本身不同。

| 指标 | 旧版 Z2（sha `aae16265a2682944…`） | 修订版 Z2（sha `3229c1378d621b2c…`） |
|---|---:|---:|
| Z2 2D 布通 | 480/512 | **488/512** |
| 合计 2D 布通 | 992/1024 | **1000/1024** |
| 2D 唯一交叉对 | 116,748 | **121656** |
| 15L 三维布通 | 992/1024 | **1000/1024** |
| 15L violations | 0 | **0** |
| 15L 全局唯一交叉 | 75794 | **78836** |
| Z2 严格 C4（3D） | PASS（120 组） | **PASS（122 组完整）** |
| 剩余失败 C4 组 | 8 | **6** |

## 二、输入变更与审计

- 用户更新后的 Z2 CSV：512 行（adjacent 400 + same 112），仍是 row-1 端口标签；
  sha256 `3229c1378d621b2c69ec5249da983ab252bf8edfb6caa660cb60a71c20f8ccbc`。
- 与旧版 Z2 的关系：**无向连接集合完全相同**（已验证 512 条连接逐一匹配），
  差异是 **256/512 行的 source/target 方向被显式给出**（旧版由脚本按端点字典序
  规范化）。布线对方向敏感（起点/终点切向与模板帧不同），因此布局变化显著。
- Z1 CSV 未变：sha256 `9d5e0b5e15c4b2774130403c94cc56f91b79584496676cbffb7ee81acf54cfbd`。
- 处理：Z2 每个端口做 row1→row2 映射（同一物理孔位、z=0.5），保留用户方向；
  与 Z1（z=0）合并为 `connectivity_1024.csv`（sha256
  `6e1b5fb9187b0caab2019015b32c951faa867e723530572e30bc08b38bc747df`）。
- 校验明细：
- z1 route_id 1..512 unique: PASS
- z1 uses all 1024 z1 ports exactly once: PASS
- z2 revised CSV is already C4-expanded (512 rows): PASS
- z2 rows convert to row-2 ports: PASS
- z2 uses all 1024 z2 ports exactly once: PASS
- z2 relation composition (adjacent 400 + same 112): PASS
- z2 revised C4 closure (0 missing at 90/180/270): PASS
- 拓扑：1024 连接、
  256 个 C4 组、
  relation {'opposite': 256, 'same': 368, 'adjacent': 400}、
  C4 闭环 {'90deg': 0, '180deg': 0, '270deg': 0}。

## 三、2D 严格 C4 布线（phase-2）

- Z1：沿用此前已验证的 512/512 布局（Z1 输入未变）。
- Z2：easy 顺序 + R&R/重试 + 扩展 U bulge 修复轮；phase-2 单遍
  476/512，修复后
  **488/512**（修复轮恢复
  3 个组）。
- 合并 2D：1000/1024，
  validation_passed = True；
  平面 2D 交叉：z1 53500 对、
  z2 68156 对。
- 剩余失败 Z2 C4 组（6 组 / 24 条）：

| group_id | kind | pair | route_ids |
|---|---|---|---:|
| 170 | adjacent | EN | [554, 764, 765, 766] |
| 176 | adjacent | EN | [560, 782, 783, 784] |
| 210 | adjacent | NW | [594, 884, 885, 886] |
| 245 | same | N | [629, 989, 990, 991] |
| 247 | same | N | [631, 995, 996, 997] |
| 249 | same | N | [633, 1001, 1002, 1003] |

## 四、15L 三维层扫结果

- 输入：同一 2D 布局（1000 条），
  层高 L2=0.65 mm、+0.15 mm/层至 L15=2.60 mm；冻结 lift 引擎与 3D 验证器，
  预算 max_groups=300、time_limit=480 s。
- 布通 **1000/1024**；violations
  **0**（曲率/净空/自净空/同层等全部 0）；
  抬升 49 个 C4 组、392 个升降段；
  全局唯一交叉 **78836** 对；交叉点 100200 个。
- 物理层使用（经过该层的 route 数）：{'0.0': 512, '0.5': 488, '0.65': 16, '0.8': 20, '0.95': 20, '1.1': 16, '1.25': 12, '1.4': 12, '1.55': 16, '1.7': 12, '1.85': 16, '2.0': 16, '2.15': 12, '2.3': 16, '2.45': 4, '2.6': 8}
- Z2 严格 C4：PASS — 122 个完整四元组，
  6 组因 2D 未布通不完整，最大偏差
  4.0194366942304644e-14 mm。
- 图件：`best_solution/figures/`（overall_2d/overall_3d、crossing_hotspots、
  16 个物理层 `layer_z*.png`、高层/接口层拼版、旧vs新对比图）。

## 五、与旧版对比分析

- 布通：+8 条（Z2 +2 个 C4 组），总 1000/1024。
- 交叉：15L 绝对交叉 +3042 对，
  但 2D 基线也高（+4908 对），
  相对 2D 降低率几乎相同（0.352 vs 0.3508），说明层抬升策略本身
  没有退化；差异来自更拥挤的 2D 布局。
- 失败组从旧版 8 组（154/156/158/214/246/249/250/254）变为新版
  170, 176, 210, 245, 247, 249；
  仅 249 仍在两个版本中失败，说明方向修正改变了角部/同边 U 的冲突结构。

## 六、复现命令

```bash
# 输入构建（修订版 Z2）
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/build_inputs_z2rev.py
# 2D 布线 + 修复 + 合并
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_phase2_z2rev.py
# 15L 三维层扫
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_layer_sweep_z2rev.py 15 480
# 汇总 / 图件 / 报告
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/finalize_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/make_figures_z2rev.py
```

## 七、文件清单

- `inputs/`：修订版 Z1/Z2 原始 CSV、`connectivity_1024.csv/json`、SHA256SUMS、输入校验。
- `phase2_2d/`、`phase2_2d_repaired/`：2D 布线结果与验证；`phase2_summary.json`。
- `02_layer_sweep/L15/lift/`：15L 三维结果（routes_l3d、validation、summary、crossings、z2 C4 审计）。
- `best_solution/`：最佳合法方案（含全部图件、per_route.csv、per_layer.csv）。
- `comparison_z2rev.json`：旧版/新版对比汇总。

## 八、下一步建议

1. 用 Rip-up & Reroute 针对剩余 6 组（170, 176, 210, 245, 247, 249）
   做局部联合重布，争取 1024/1024。
2. 补跑 5L/7L/11L 层扫，比较不同层数下的合法交叉。
3. 把本轮结果同步到 GitHub 归档（本报告即归档材料）。
