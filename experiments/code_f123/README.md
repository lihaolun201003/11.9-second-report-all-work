# F1/F2/F3 实验代码（1024 通道分层策略，Z2 严格 C4）

本目录收录 F1/F2/F3 实验新增的代码模块；完整工程仍在本地
`OpticalWaveguideRouter2D/four_side_1024/`。

| 文件 | 作用 |
|---|---|
| `core.py` | 数据加载（E1 基线 / 平铺布局）、带安全裕量的碰撞世界、逐条 Z1 分层构造、Z2 严格 C4 轨道优化（整四元组、反向成员窗口映射）、精确增量交叉 delta、Z2 独立 C4 验收、冻结验证器修复 |
| `run_f123.py` | F1 / F2（初始 + 局部优化）/ F3 实验驱动、方案保存、comparison、best_solution |
| `savefigs.py` | 保存 routes/summary/validation/z2_c4_validation/per_route/per_layer/crossing_sources/assignment_table 与 22 张图件（含 ns_ew_layer_separation、adjacent_routes_before_after、corner_routes_zoom） |
| `report_f123.py` | 自动报告生成 |

## 关键约定

- Z1 不对称：邻边/NS/EW 可独立选择目标层、S 型升降窗口（起终点可不对称）。
- Z2 严格四元对称：以连接表 group 为轨道（128 个），整轨道联合调整层与窗口；
  若成员方向参数化相反，自动交换起终点升降窗口，保证四条真实几何互为 90° 旋转副本。
- 交叉统计沿用 E1 严格口径（同物理高度上按无序路线对唯一化后求和）。
- 冻结验证器（`four_side_1024/fslw/validate_fslw.py`）为最终验收；未通过的方案如实
  记录 violations，不做假。

## 复现（工程根目录，Python 3.10）

```bash
python -m four_side_1024.f123.run_f123      # F1/F2/F3 全流程
python -m four_side_1024.f123.report_f123   # 报告
```
