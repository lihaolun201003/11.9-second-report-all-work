# Auto U 层分配变体：实验图与指标

每个变体目录下：

- `routes_1024.json`：该层分配对应的 1024 条完整 XYZ
- `summary.json`：指标 + 分配
- `figures/02_after_3d.png`：整体三维
- `figures/03_L1_z1.png` … `08_L5.png`：逐层图
- `figures/09_u_bundles_3d.png`：仅 4 个 U 簇（按层着色）
- `<name>_contact_2x3.png`：六层拼图（L1-z1/L1-z2/L2/L3/L4/L5）

## 变体总表

| 变体 | 簇层分配（簇0/1/2/3） | 全局唯一交叉 | 升降 | 总长 (mm) | min3D | 说明 |
|---|---|---:|---:|---:|---:|---|
| **best** | **L3 / L3 / L4 / L5** | **12,960** | 784 | 98,736.09 | 0.0917 | 层搜索最优，与 Hybrid 持平 |
| **greedy** | L2 / L3 / L3 / L3 | 14,104 | 784 | 98,422.03 | 0.0917 | 贪心初解（未做层搜索），三簇同层产生 U-U 交叉 |
| alt c0L2 c1L3 c2L4 c3L5 | L2 / L3 / L4 / L5 | 13,080 | 784 | 98,606.96 | 0.0917 | 其他排列 |
| alt c0L2 c1L3 c2L5 c3L4 | L2 / L3 / L5 / L4 | 13,080 | 784 | 98,606.96 | 0.0917 | 其他排列 |
| alt c0L2 c1L4 c2L3 c3L5 | L2 / L4 / L3 / L5 | 13,080 | 784 | 98,006.96 | 0.0917 | 其他排列 |
| alt c0L2 c1L4 c2L5 c3L3 | L2 / L4 / L5 / L3 | 13,080 | 784 | 98,606.96 | 0.0917 | 其他排列 |
| alt c0L2 c1L5 c2L3 c3L4 | L2 / L5 / L3 / L4 | 13,080 | 784 | 98,004.56 | 0.0917 | 其他排列 |
| alt c0L2 c1L5 c2L4 c3L3 | L2 / L5 / L4 / L3 | 13,080 | 784 | 98,194.96 | 0.0917 | 其他排列 |

对照：Hybrid H 基线 12,960 交叉 / 784 升降 / 98,019.93 mm；手动 Spatial U（V2 基线）12,824 / 824 / 98,539.01 mm（不同基线，仅参考）。

## 图

- best：[整体](best/figures/02_after_3d.png) · [L1-z1](best/figures/03_L1_z1.png) · [L1-z2](best/figures/04_L1_z2.png) · [L2](best/figures/05_L2.png) · [L3](best/figures/06_L3.png) · [L4](best/figures/07_L4.png) · [L5](best/figures/08_L5.png) · [U 线束](best/figures/09_u_bundles_3d.png) · [六层拼图](best/best_contact_2x3.png)
- greedy：[整体](greedy/figures/02_after_3d.png) · [六层拼图](greedy/greedy_contact_2x3.png)
- 六个 alt 变体：各目录下同名 `figures/` 与 `*_contact_2x3.png`

生成脚本：`four_side_1024/manual_c4/auto_u_variant_plots.py`；数据由 `run_auto_u_bundle_hybrid.evaluate` 重新装配并审计，未改动旧代码/旧结果。
