# 人工 U 型几何修复：真实深/浅嵌套 U 的生成与验证报告

**日期**：2026-11-02
**任务**：修复"人工 U 型几何没有真正生成"的问题——不再对冻结二维路径做局部抬升，而是按真实端点重新生成 R15 深/浅嵌套 U。
**输出目录**：`outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_COMPARISON_FIXED/`（未覆盖 GitHub 提交 `b926212` 的旧产物 `MANUAL_GROUP_15L_COMPARISON/`）
**运行**：`python -m four_side_1024.manual_c4_adapt.compare_15L --phase1-only`（人工阶段 202 s，一次性运行，无参数扫描）

---

## 1. 修改了哪些文件、哪些函数

### 新增 `four_side_1024/manual_c4_adapt/manual_u_geometry.py`

| 函数 | 作用 |
|---|---|
| `build_manual_u_geometry(source, target, side, arm_mm=...)` | 用真实端点坐标 + 所在边 + R15 构造一条真实的 U 型几何：直线 + 两段精确 R15 四分之一圆弧 + 底边直线；`arm_mm` 为每条直臂长度，U 深度 = `R + arm`；端点坐标不改动；检查端口位姿、切线连续、板面边界、弧半径严格 = 15 mm。返回 `ok / primitives / depth_mm / arm_mm / bottom_straight_mm / length_mm / radius_mm / errors`，不可行时只返回具体失败原因，不生成假路径。 |
| `nesting_plan(items, arm_min_mm, depth_step_mm)` | 由同层同侧全部真实端点区间的**包含关系**计算嵌套：每条线路的包含数 `contains` 与所在链的最大嵌套数 `chain_k`；外层（包含别人多的）取更深的 U，内层取更浅的 U；互不包含的区间互不影响，可复用深度。`manual_group_order` 只作排序/诊断，不作为数值深度。 |
| `measure_min_clearance`, `interval_of` | 报告用的中心线距离测量与区间工具。 |

### 修改 `four_side_1024/manual_c4_adapt/compare_15L.py`

| 函数 | 修改内容 |
|---|---|
| `load_manual_connections()`（新增） | 从 640 CSV 读入 256 条明确标记人工线路的**真实端点坐标**、所在边、目标层、`manual_group`、`manual_group_order`、`u_pair`；与 section2 拓扑的 layout 记录核对。 |
| `_window_candidates()`（重写） | 输入改为**新生成的 U 型 primitives**（不再读冻结二维链）。只在 U 的直线臂上找升降 S 曲线窗口（必要时可用底边直线作 fallback）；同时执行冻结的过渡-平面净空检查，以及"界面平面 z=0 交叉点 free-zone"检查（抬升 S 曲线的低段不能落在别的线路的 2D 交叉点上，否则该 2D 合法交叉会变成立体冲突）。 |
| `force_manual_route()`（重写） | 流程改为：新 U 几何 → `_window_candidates()` → `LIFT.lift_route()` 生成目标层真实 3D 路径 → `lifter.world.check_route()` 三维校验 → **只有合法才提交**。提交时同步更新 `world`、`lifter.primitives`、`lifter.base_routes`、`lifter.lifted`；失败只返回具体原因，不再静默回退。 |
| `run_manual()`（重写） | 先用一次 `world.rebuild()` 移除**全部 256 条**人工线路旧几何（包括 L1 的 64 条平面 U）；按 L1→L2→L3→L4、每层按侧、内侧按嵌套顺序逐条生成并提交；L1 为平面 U，L2–L4 为真实抬升。提交后重算交叉状态、冻结人工 C4 组、旧算法从 L5 起继续；若人工阶段不完整则**不启动** 1024 通道实验。 |
| 新增辅助 | `_arm_requirement`（每层所需最小直臂）、`_arm_candidates`（嵌套目标优先的深度阶梯）、`_layer_z`（L1=0.0）、`build_manual_us`（人工阶段主循环）、`_flat_clearance_on_plane`、`_transition_clearance_to_planes`、`_plot_manual_layers`（每层布线图）、`_run_old_algorithm`（原算法 L5–L15，逻辑不变）。 |
| 对比与入口 | `baseline_metrics()` 增加 `routed_ids`；`compare()` 增加共同成功路线集合的公平对比；修复 `render_table()` 的集合运算 bug；`main()` 增加 `--phase1-only`；输出目录改为 `MANUAL_GROUP_15L_COMPARISON_FIXED`。 |

### 新增 `four_side_1024/manual_c4_adapt/phase1_metrics.py`
人工阶段后处理：每层布通数、U 深度、严格嵌套数、实际最小同层净空（手工 U 之间、采样 0.5 µm 弦高）、过渡位置、失败原因分类。

---

## 2. L1–L4 实际各布通多少条

| 层 | 目标 | 实际布通 | 说明 |
|---|---:|---:|---|
| L1 (z=0) | 64 | **64 / 64** | 全部为重新生成的真实平面 U（非冻结路径），N 32 + S 32 |
| L2 (z=0.65) | 64 | **0 / 64** | 所有抬升位置与冻结平面冲突 |
| L3 (z=0.80) | 64 | **0 / 64** | 同上 |
| L4 (z=0.95) | 64 | **2 / 64** | 仅 W/E 各 1 条找到合法抬升（深度 31.64 mm，rise=3.7 / fall=97.764 mm） |
| **合计** | **256** | **66 / 256** | 人工阶段不完整 |

每层单独布线图：`MANUAL_GROUP_15L_COMPARISON_FIXED/plots_manual/manual_layer_L1.png … L4.png`。

## 3. 是否真正形成了深浅嵌套 U 型

- **L1：是。** 64 条全部满足严格嵌套规则（`strict_nesting = 64/64`，无一条需要偏离嵌套深度）：
  - U 深度 15.25 – 23.0 mm（直臂 0.25 – 8.0 mm），每个同侧 32 条构成完整嵌套链，外层更深、内层更浅，嵌套步长 0.25 mm；
  - 全部为直线 + 精确 R15 圆弧（半径审计无偏差、切线连续、端点坐标未改）；
  - 全部通过冻结三维 world 校验（`check_route` 无违规）；手工 U 之间实测最小中心线间距 **0.25 mm**（即嵌套步长，无人工线路之间的交叉），与冻结非人工线路的交叉为 90° 合法设计交叉。
- **L2–L4：否（大量失败）。** 这些层的新 U 几何本身可生成，但无法合法抬升，原因见第 4 节。

## 4. 有哪些真实几何冲突

抬升失败不是"搜索没找到"，而是冻结布局给出真实约束：

1. **Z1 界面平面（z = 0 mm）被 256 条冻结 opposite 线路占据。** 新 U 的直臂是直线，会在固定弧长位置穿过这些线路（例如 `route 138` 是 y = 144.375 mm 的整条横线，`route 137`、`route 86`、`route 376` 等类似）。抬升 S 曲线的低段需要约 1.8 mm 无交叉带（否则 2D 合法 90° 交叉变成 S 曲线与平线的立体冲突），但每段直臂被这些横线切成更短的段。
2. **Z2 接口平面（z = 0.5 mm）同样被 480 条冻结线路占据。** S 曲线穿过 z = 0.5 时，横向必须离 z2 线路 ≥ 0.08 mm；实测所有候选位置最近距离仅 **0.043 – 0.084 mm**，低于冻结验证器阈值（segment 0.081 / point 0.091）。
3. **代表性证据（L2 / N 侧 route 65）**：尝试 6 种 U 深度（直臂 12.36 → 24 mm，共 330 个候选抬升位置）全部失败：
   - 与 `route 138`（z1，y=144.375）在 (63.375, 144.37, z≈0.07) 处距离 0.0689 mm；
   - 与 `route 638`（z2，z=0.5）在 (63.375, 142.67, z=0.427) 处距离 0.0839 mm。
   加深 U 后新增的直臂段仍被其它冻结线路切断，无法获得 1.8 mm 净空带。
4. **失败原因汇总**（`phase1_metrics.json`）：
   - `arms:no_transition_window + any:all_placements_conflict` 等组合；
   - 具体 blocker 线路：z1 侧 137、138、86、376；z2 侧 618、619、626、627、637、682、986、987 等；另有 `flat_same_plane_conflict`（低段平线与冻结线路同层冲突）。
5. **L4 的 2 条成功**说明并非全不可行：W/E 侧各 1 条（route 348、350）在深度 31.64 mm、rise=3.7 / fall=97.764 mm 处找到合法抬升；但它们不属于严格嵌套深度（`strict = 0/2`，为了避开阻挡才加深）。

## 5. 完整方案是否能够执行

**不能。** 256 条人工 U 中只执行了 66 条（L1 64 条 + L4 2 条），L2/L3 完全为 0；按任务规定的验收顺序（人工几何阶段完整通过才跑 1024），**本轮没有启动 1024 通道实验**，因此没有新的总交叉数 / 与 75,794 的对比数字。

需要说明：在"只允许人工 256 条使用人工分组、其余 768 条冻结/旧算法、不得重布连接关系"的约束下，z1→L2/L3/L4 的抬升通道被冻结的 256 条 z1 opposite 线路与 480 条 z2 线路物理封死；这不是靠继续搜索深度或过渡位置能解决的（已尝试到 24 mm 深度/330 个位置）。若要让 L2–L4 全部执行，必须（不属于本轮范围）：重布 768 条非人工线路、或把人工 U 作为 2D 主布线约束重新布线、或为抬升预留走廊。

## 6. 如果完成 1024 通道实验，交叉数降低多少

**本轮无法给出**：人工阶段 66/256 未通过验收门槛，按任务要求未启动完整 1024 实验，因此没有可比较的总交叉数。已实现的 66 条人工 U 全部通过冻结验证器（R15/净空/同层/三维），未产生伪造成本。

## 7. 复现与产物

```powershell
Set-Location -LiteralPath 'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D'
$env:PYTHONPATH = (Get-Location).Path
& '.venv\Scripts\python.exe' -m four_side_1024.manual_c4_adapt.compare_15L --phase1-only
& '.venv\Scripts\python.exe' -m four_side_1024.manual_c4_adapt.phase1_metrics
```

```
outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_COMPARISON_FIXED/
├── phase1.log               # 人工阶段完整日志（202 s）
├── manual_phase1.json       # 256 条逐条结果：深度/嵌套/过渡位置/失败原因
├── phase1_metrics.json      # 每层汇总/最小净空/失败分类
└── plots_manual/
    ├── manual_layer_L1.png  # 64/64 真实嵌套 U
    ├── manual_layer_L2.png  # 0/64（失败位置标红叉）
    ├── manual_layer_L3.png
    └── manual_layer_L4.png  # 2/64
```

注：GitHub 提交 `b926212` 的旧产物（`MANUAL_GROUP_15L_COMPARISON/`）未被覆盖。
