# 人工分组（L1–L4）与旧 15L 基线：完整 1024 通道对照 + 逐层布线图

**日期**：2026-11-02

## 1. 目的与规则

- 连接拓扑：`experiments/manual_routing_csv/` 的两份 `section2.csv`（z1 512 + z2 512 = **1024 条**）。
- 人工分组依据：`人工分组/z1_z2_manual_u_assignment_v2_640.csv`（640 条元数据）。
- **L1–L4 严格按人工分组执行**（仅明确标记 `manual_fixed_u` 且层号 L1–L4 的 256 条）；**L5–L15 沿用原布线算法**（跨层抬升 crossing-lift）；不得重新分组或修改连接关系。
- 层模型（150 µm 层距）：Z1 = 0.0 mm、Z2 = 0.5 mm；L2 = 0.65、L3 = 0.80、L4 = 0.95、L5 = 1.10 mm，此后每层 +0.15 mm，L15 = 2.60 mm。
- 只运行了这一次完整对照：未做参数扫描、未重跑历史实验、未开发新算法；R=15 / 净空由冻结验证器检查，合法设计交叉不算违规。

## 2. 关键结果（对比表）

| 指标 | 原 15L 基线（旧算法 L2–L15） | 人工分组（L1–L4 人工 + L5–L15 旧算法） | 变化 |
|---|---:|---:|---:|
| 布通条数 | 992 / 1024 | 992 / 1024 | +0 |
| **全局唯一交叉对数** | **75,794** | **74,626** | **−1,168（−1.54%）** |
| 交叉点总数 | 95,628 | 94,276 | −1,352 |
| Z1×Z1 唯一交叉对 | 48,524 | 46,822 | −1,702 |
| Z2×Z2 唯一交叉对 | 27,162 | 27,696 | +534 |
| Z1×Z2 混合唯一交叉对 | 108 | 108 | 0 |
| 束内（同 C4 组）唯一交叉对 | 614 | 596 | −18 |
| 束间唯一交叉对 | 75,180 | 74,030 | −1,150 |
| 举升组数 / 抬升路线数 | 48 / 192 | 53 / 220 | +5 / +28 |
| 验证违规数 | 0 | 0 | — |

两次运行使用**完全相同的冻结 2D 布局**（`NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected/routes_1024.json`，992 条、同一 2D 几何），只有 3D 层分配不同，因此上表本身就是相同路线集合上的公平对比。

## 3. 人工分组实际执行情况（如实）

- 256 条人工记录（L1 64 / L2 64 / L3 64 / L4 64）中，**L1 的 64 条**本身位于接口层平面；L2–L4 共 192 条中只有 **16 条（L4）** 抬升成功，**176 条失败**并保留在接口层平面。
- 失败原因：`no_transition_window` 108（现有 2D 布局中 U 型直线臂短于 6.2–6.5 mm 的 R15 抬升 S 曲线+安全区）；`world:transition_vs_flat` 68（z1 抬升穿过 Z2 接口平面 z=0.5 mm，与同列 z2 波导真实三维净空冲突）。
- 交叉下降的归因：−1,168 对并非全部来自 16 条人工抬升；主要来自 64 个人工组被冻结后旧算法把抬升预算改分配到其它组（51 组/220 条 vs 基线 48 组/192 条）。
- 验证：冻结验证器 `violations = 0`、`geometry_pass = True`；`status=invalid_stack` 仅因验证器层栈 schema 白名单只认 L2–L5（15 层探索性层栈的记账限制，不是几何违规）。

## 4. 目录内容

```
MANUAL_GROUP_15L_COMPARISON/
├── comparison.md / comparison.json   # 对比表（同上）
├── summary.json                      # 交叉/层/人工执行/验证统计
├── validation.json                   # 冻结验证器结果（violations=0）
├── manual_records.json               # 16 条人工抬升记录 + 176 条失败原因
├── lift_plans.json                   # 人工组冻结 + 旧算法 51 个抬升组
├── layer_stack.json                  # L1–L15 150 µm 层栈
├── per_layer_view_summary.json       # 逐层路线数/端点统计
├── routes_l3d.json                   # 本次方案 1024 条三维路线（992 routed）
├── crossings_after.json              # 全局交叉明细（与基线同一定义）
├── figures/
│   ├── layer_contact_sheet_all.png   # 全部 16 个物理平面拼图
│   ├── layer_contact_sheet_high.png  # L4–L15 拼图
│   └── layer_contact_sheet_interface.png  # L1 两行拼图
└── plots/
    ├── 01_before_after_xy.png        # 基线 vs 人工分组 XY 总览
    ├── 02_3d_full.png                # 15L 三维整体布线
    ├── 03_layers.png                 # 分层视图
    ├── 04_early_climb_zoom.png       # 抬升段局部放大
    └── per_layer/                    # 每层单独布线图（16 张）
        layer_z0.00.png  (L1 Z1 行, 512 条)
        layer_z0.50.png  (L1 Z2 行, 480 条)
        layer_z0.65.png  (L2, 0 条 — 本方案 L2/L3 为空层)
        layer_z0.80.png  (L3, 0 条)
        layer_z0.95.png  (L4, 16 条人工抬升)
        layer_z1.10.png … layer_z2.60.png (L5–L15)
```

逐层统计：L1(Z1) 512 / L1(Z2) 480 / L2 0 / L3 0 / L4 16 / L5 32 / L6 16 / L7 24 / L8 28 / L9 24 / L10 8 / L11 12 / L12 20 / L13 8 / L14 12 / L15 20（路线数，含该层有 flat 的路线）。

## 5. 复现

代码见 [`experiments/code_manual_group_15l/`](../code_manual_group_15l/)：

```powershell
Set-Location -LiteralPath '<project root>'
$env:PYTHONPATH = (Get-Location).Path
& '.venv\Scripts\python.exe' -m four_side_1024.manual_c4_adapt.compare_15L
# 逐层图（复用 campaign 冻结算图器）：
& '.venv\Scripts\python.exe' four_side_1024\manual_c4_adapt\make_per_layer_views.py
& '.venv\Scripts\python.exe' four_side_1024\manual_c4_adapt\make_all_layer_views.py
```

报告：`docs/reports/manual_group_15L_comparison.md`。
