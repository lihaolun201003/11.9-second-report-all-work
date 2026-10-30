# Z1 边缘交叉专项优化报告（7 层 / 150 µm 层栈）

## 1. 目标与方法

在现有 7 层结果（`z1_multilayer_150um/optimized_7L`，全局 11,984、Z1 10,976、Z2 1,008）上，先用实际事件审计回答“交叉由什么构成”，再做联合分层重布，目标是在**不增加层数**的前提下显著降低全局真实交叉。

固定参数：Z1=0、Z2=0.5、L2=0.65 起、层距 0.15、R=15、净空 0.08、写速 1 mm/s。

## 2. 交叉溯源结果

审计方法：读取 1024 条 `routes_1024.json`，对 z=0 每个 flat 条目做 strict fslw 审计；每条升起路线包含前/后两段 Z1 base stub，因此共 736 个平面条目、512 条路线。

- 唯一交叉路线对：**10,976**
- 事件：**11,488**

| 类别 | 唯一对 | 事件 | 份额 |
|---|---:|---:|---:|
| 邻边–对边 | 4,576 | 4,576 | 41.7% |
| 对边–对边 | 5,888 | 5,888 | 53.6% |
| 对边–同侧 | 512 | 1,024 | 4.7% |
| 邻边–邻边 / 邻边–同侧 / 同侧–同侧 | 0 | 0 | 0 |

邻边相关的 4,576 对全部为“邻边 × 对边”：

| 邻边侧几何段 | 事件 |
|---|---:|
| 圆弧 × 直线 | 2,300 |
| 直线 × 直线（接入段） | 2,276 |

区域：port_lead 1,976；edge_lead 2,600；central_trunk 0。即邻边问题全部在端口/边缘区。

逐事件字段：route_a/b、relation_a/b、category、x/y/z、geom_a/b、region、到最近几何段距离，见 `analysis_old_7L/z1_crossings.csv`；统计表见 `analysis_old_7L/z1_crossing_category_table.csv`。

## 3. 邻边整条抬升的可行性验证

邻边 2D 路径结构：R=15 的 90° 圆弧 + 两端各 0.125 mm 直线引入段（例：N 端口 x=15.125 到 W 端口 y=134.875，圆弧直接覆盖 15 mm 转角）。

因此：

- 一次 S 升降 footprint：Z1→L2 约 6.2 mm、Z1→L7 约 9.1 mm；两次升降需要至少 12.4–18.1 mm 连续直线；
- 邻边可用直线仅 0.125 mm，S 段只能落到圆弧上；
- 实测将 Z2 邻边 76/78 组抬到 L6/L7 时，出现 388 个 violations（geometry 320、curvature 48、clearance 20），并在 L6 新增 2,048 对高层交叉，全局升至 13,072。

结论：**在现有邻边 2D 拓扑下，整条邻边路线无法合法抬层**；要抬邻边必须改 2D 拓扑（增加额外圆弧/引入段或改变端口逃逸），本轮没有把这种新拓扑强加到 1024 通道上。

## 4. 联合重布（本轮实际采用）

从旧 7L 结果出发：

1. 把 8 条 Z2 对边从 L2=0.65 移到 L4=0.95，释放 L2 端口窗口；
2. Z1 的 66 个 EW C2 对 → L2=0.65；66 个 NS C2 对 → L3=0.80；
3. 每对 S 起点从 a=1.2 mm 起重新搜索（网格 1.2/1.8/2.5/3.5/5/7/10/15/22/30/40/55 mm），并允许换层重试；
4. 邻边、U、Z2 对边保持基线几何并作为固定障碍；
5. 生成 1024 条真实 XYZ，执行完整 3D 验证与同平面交叉审计。

## 5. 结果

| 指标 | 旧 7L | 联合 7L | 变化 |
|---|---:|---:|---:|
| 全局唯一交叉 | 11,984 | **6,078** | −4,906（−40.9%） |
| Z1（z=0） | 10,976 | **5,256** | −5,720（−52.1%） |
| Z1 横纵 | 5,888 | **1,092** | −4,796（−81.5%） |
| Z2（z=0.5） | 1,008 | 752 | −256（−25.4%） |
| 邻边相关 | 4,576 | 3,680 | −896（−19.6%） |
| 邻边圆弧相关 | 2,300 | 1,404 | −896（−39.0%） |
| 邻边接入段直线 | 2,276 | 2,276 | 0 |
| 对边–对边 | 5,888 | 1,064 | −4,824（−82.0%） |
| 对边–同侧 | 512 | 512 | 0 |
| 升降 | 848 | 940 | +92 |
| 总长 (mm) | 97,203.70 | 97,205.18 | +1.48 |
| 加工时间 (h) | 27.0010 | 27.0014 | +0.0004 |
| 布通 | 1024/1024 | 1024/1024 | — |
| violations | 0 | 0 | exploratory PASS |

关键：对边–对边交叉从 5,888 降到 1,064；Z1 横纵从 5,888 降到 1,092。邻边相关下降主要来自圆弧段（2,300→1,404）；**接入段直线 2,276 对未下降**，这是邻边 0.125 mm 引出段与 Z1 base stub 的接口级交叉，必须通过改邻边 2D 拓扑解决。

## 6. 图件与数据

根目录：`outputs/manual_c4_new_connectivity/z1_multilayer_150um/z1_edge_optimization/`

- `optimized_7L_joint/routes_1024.json`：1024 条完整 XYZ
- `optimized_7L_joint/summary.json`、`validation.json`
- `optimized_7L_joint/per_route.csv`、`per_layer.csv`
- `optimized_7L_joint/figures/`：
  - `01_overall_3d.png`、`02_overall_xy.png`
  - `03_L1_Z1.png`、`04_L1_Z2.png`、`05_L2.png` … `10_L7.png`
  - `all_layers_contact_sheet.png`
  - `z1_before_after.png`
  - `adjacent_routes_and_crossings.png`
  - `adjacent_crossing_hotspots.png`
  - `transitions_3d.png`
  - `z1_category_heatmap_*.png`
- `analysis_old_7L/`、`analysis_new_7L_joint/`：逐事件 CSV/JSON/热力图
- `crossing_source_table.csv`、`comparison.csv`、`comparison.png`
- `experiment_report.md`

脚本：
- `four_side_1024/manual_c4/z1_edge_analysis.py`
- `four_side_1024/manual_c4/z1_edge_optimizer.py`
- `four_side_1024/manual_c4/z1_multilayer_plots.py`

## 7. 局限

- 层高仍为 `unconfirmed_simulation`，验证为 exploratory，不是正式工艺验收。
- 本轮只完成 7L 联合重布；9/11 层未重新优化（旧 9/11 结果保留，不作为本轮结论）。
- 邻边整条抬层未完成：受 0.125 mm 引入段限制，需要改邻边 2D 拓扑；剩余邻边接入段 2,276 对是下一步重点。
- 交叉减少来自真实的 Z2 对边移层 + Z1 早升降，不是只改层标签；所有 1024 条均重新生成 XYZ 并通过 validation=0。
