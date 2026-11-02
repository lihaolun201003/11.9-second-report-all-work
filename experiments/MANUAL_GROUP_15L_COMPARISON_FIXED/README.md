# 修复版：人工 U 型几何的真实生成与验证（L1–L4）

**日期**：2026-11-02

## 目的

上一版（[MANUAL_GROUP_15L_COMPARISON](../MANUAL_GROUP_15L_COMPARISON/)）是在冻结二维路径上做局部抬升，192 条人工 U 中只有 16 条成功。本版**不再复用冻结二维路径**：按 640 CSV 的真实端点、所在边、人工组/嵌套顺序和目标层，用 R15 圆弧 + 直线重新生成真正的深/浅嵌套 U，再验证其三维合法性。旧产物未被覆盖。

## 代码修改

- 新增 [`experiments/code_manual_group_15l_fix/manual_u_geometry.py`](../code_manual_group_15l_fix/manual_u_geometry.py)：`build_manual_u_geometry()`（真实端点 → 直线 + 精确 R15 四分之一圆弧 + 底边；深度 = R + 直臂；端点不动、切线连续、板面内）、`nesting_plan()`（由端点区间包含关系定嵌套：外层更深、内层更浅）。
- 重写 [`experiments/code_manual_group_15l_fix/compare_15L.py`](../code_manual_group_15l_fix/compare_15L.py) 中的 `_window_candidates()`（输入改为新 U 型 primitives）、`force_manual_route()`（新几何 → 升降窗口 → 真实 3D 路径 → 冻结 world 校验 → 只有合法才提交，删除静默回退）、`run_manual()`（先移除全部 256 条旧几何含 L1，再按 L1→L4 逐条生成；人工阶段不完整则停止）。
- 后处理/出图：`phase1_metrics.py`、`plot_l1_nesting.py`。

## 人工阶段结果（202 秒，单次运行）

| 层 | 目标 | 实际布通 | 说明 |
|---|---:|---:|---|
| L1 (z=0) | 64 | **64 / 64** | 真实嵌套 U：深度 15.25–23.0 mm，严格嵌套 64/64，U 间最小净空 0.25 mm |
| L2 (z=0.65) | 64 | **0 / 64** | 所有抬升位置与冻结 z1/z2 平面冲突 |
| L3 (z=0.80) | 64 | **0 / 64** | 同上 |
| L4 (z=0.95) | 64 | **2 / 64** | 仅 W/E 各 1 条（深度 31.64 mm，rise=3.7 / fall=97.76） |
| 合计 | 256 | **66 / 256** | 人工阶段不完整 |

**真实几何冲突**：Z1 界面平面（z=0）被 256 条冻结 opposite 线路占据（如 route 138 = y=144.375 整条横线），Z2 平面（z=0.5）被 480 条冻结线路占据；抬升 S 曲线需要约 1.8 mm 无交叉低段与 0.08 mm 三维净空，但候选位置最近距离仅 0.043–0.084 mm（低于冻结阈值 0.081/0.091）。代表例 L2/route 65：6 种 U 深度（直臂 12.36→24 mm）、330 个位置全部失败。因此按验收顺序（人工阶段完整才跑 1024）**本轮未启动 1024 通道实验**，没有新的总交叉数对比。

## 目录内容

```
MANUAL_GROUP_15L_COMPARISON_FIXED/
├── README.md              # 本文件
├── report.md              # 完整修复报告（修改文件/函数、结果、冲突、结论）
├── manual_phase1.json     # 256 条逐条结果：深度/嵌套/过渡位置/失败原因
├── phase1_metrics.json    # 每层汇总/最小净空/失败分类
├── phase1.log             # 人工阶段完整日志
└── plots_manual/
    ├── manual_layer_L1.png             # L1：64/64 真实嵌套 U
    ├── manual_layer_L1_nesting_zoom.png# L1 按深度着色的嵌套证明图
    ├── manual_layer_L2.png             # L2：0/64（失败位置红叉）
    ├── manual_layer_L3.png             # L3：0/64
    └── manual_layer_L4.png             # L4：2/64
```

## 复现

```powershell
Set-Location -LiteralPath '<project root>'
$env:PYTHONPATH = (Get-Location).Path
& '.venv\Scripts\python.exe' -m four_side_1024.manual_c4_adapt.compare_15L --phase1-only
& '.venv\Scripts\python.exe' -m four_side_1024.manual_c4_adapt.phase1_metrics
```
