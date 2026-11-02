# 修订版 Z2 CSV 战役代码（1000/1024）

本目录收录"用户更新 Z2 CSV（方向显式化）后重新跑 1024 通道实验"的可复现代码。

| 文件 | 作用 |
|---|---|
| `build_inputs_z2rev.py` | 读取修订版 Z1/Z2 CSV：Z1 直接使用；Z2 是 512 行已 C4 展开表（row-1 标签），做 row1→row2 端口映射并**保留用户显式方向**；校验端口唯一性/关系组成/C4 闭环；合并 1024 连接并跑冻结 35 项输入校验 |
| `run_phase2_z2rev.py` | Z2 2D 严格 C4 布线（easy 顺序 + R&R/重试）+ 扩展 U bulge 修复轮；Z1 复用已验证 512/512 布局；合并为 1024 2D 布局 |
| `run_layer_sweep_z2rev.py` | 15L 三维层扫（冻结 lift 引擎 + 冻结 3D 验证器，L2=0.65 mm、+0.15 mm/层） |
| `finalize_z2rev.py` | Z2 严格 C4 三维审计、层使用统计、旧/新对比汇总、best_solution 归档 |
| `make_figures_z2rev.py` | 总体 2D/3D、交叉热点、逐层图、逐路线/逐层 CSV、旧vs新对比图 |
| `make_layer_views_z2rev.py` | 16 个物理层带标注视图 + 高层/接口层拼版 |
| `make_report_z2rev.py` | 生成技术报告与 README 章节 |

## 运行顺序（项目根目录，Python 3.10）

```bash
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/build_inputs_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_phase2_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_layer_sweep_z2rev.py 15 480
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/finalize_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/make_figures_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/make_report_z2rev.py
```

## 结果（本版本）

- 2D：1000/1024（Z1 512/512、Z2 488/512），冻结 2D 审计 + 严格 C4 审计 PASS；
  剩余 6 个 Z2 C4 组（170、176、210、245、247、249）。
- 15L 3D：1000/1024，violations=0，全局唯一交叉 78,836 对，
  Z2 严格 C4 PASS（122 个完整四元组，最大 XYZ 偏差 4×10⁻¹⁴ mm）。
- 旧实验 `NEW_MANUAL_CSV_1024_FULL_CAMPAIGN`（992/1024）未被覆盖。
