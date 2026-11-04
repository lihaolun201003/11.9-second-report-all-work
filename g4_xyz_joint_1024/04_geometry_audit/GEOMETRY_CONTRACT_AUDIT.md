# G4-1 几何口径专项核查报告（G3 best_valid 独立审计）

> 审计对象：`outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/best_valid/`
> `routes_l3d.json` SHA256 = `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`
> （本次审计现场重算，与任务书给定值一致）。
>
> **本报告不引用任何历史 PASS 结论**：全部几何量由本次新增的独立代码从
> `routes_l3d.json` 的原始 `parts` 重新计算；历史 Validator 只作为**被复核对象**
> 重新跑了一遍（见第 5 节）。审计代码：
> [`independent_metrics.py`](../../../four_side_1024/fanout1024/xyzrouter/g4/independent_metrics.py)（独立几何指标）、
> [`contract_audit.py`](../../../four_side_1024/fanout1024/xyzrouter/g4/contract_audit.py)（契约取证/一致性）。
> 数据：`audit_metrics.json`、`min_distance_evidence.json`、`contract_evidence.json`、
> `baseline_revalidation/`、`audit_progress.log`（均在本目录）。

---

## 0. 结论摘要（先给答案）

| 必需量 | 独立复算值 | 判定 |
|---|---:|---|
| `minimum_distance_all_pairs_mm`（全部中心线对，含交叉） | **0.0** | 存在合法同层横穿（详见 2.1），因此全局最小距离本来就必须是 0 |
| `minimum_clearance_non_crossing_mm`（排除合法交叉后） | **0.05** | = 50 µm，恰为层间距阈值，按契约合法（零余量，见 2.2 / 第 7 节） |
| `allowed_crossing_count` | **1322** | 全部 1322 个事件均属允许类别（角度 ≥ 5.332°、真实横穿、窗口合规） |
| `illegal_crossing_count` | **0** | — |
| `clearance_violation_count` | **0** | 同层 2D、不同高度 3D、transition 相关、自净空全部 0 违规 |
| `crossing_exemption_policy` | 见 2.6 | 同层 D56 strict：80 µm 中心线 + 真实横穿豁免（≥ 5°、局部窗口 ≤ 4 mm）；不同高度：\|dz\| ≥ 50 µm；transition：真 3D ≥ 50 µm |

**独立复核结论**：全部通过 —— 1024/1024 布通、1322 同层交叉、1253 唯一交叉对、最大单路交叉 19、
368 条人工 U、R15 无违规（圆弧与 S 段实测半径全部 = 15.000000 mm）、玻璃 150×150×1 边界内、
端口/连接身份零误差、21 个物理高度且相邻间距恒为 0.05 mm；
独立 Validator（`manual_policy='fully_optimizable'`）复跑 **PASS，0 违规**。

**口径/契约矛盾检查**：按仓库内现行代码契约，**无矛盾**（50 µm 不是"所有中心线对无例外"的全局规则，
同层平面对由 80 µm D56 规则 + 既有合法横穿豁免管理）。**但**：若任务书原始物理要求的字面含义是
"任意两条中心线必须无例外 ≥ 50 µm"，则 1322 个合法交叉（距离恰为 0）会构成 1322 个硬违规——
这是**需求级口径差异，必须由项目负责人确认**。本审计**没有新增任何豁免**，所用豁免全部来自
G4 之前就已冻结的 D56 strict 策略（冻结基线本身即有 2409 个交叉并通过同一 Validator）。
详见第 7 节。

---

## 1. 审计方法与独立性

### 1.1 独立性

* 不 import `validate_fslw` / `nonc4.crossings` / `validate21` / `validate_native3d` 来计算任何数值：
  2D 线段/圆弧距离、交点、`transition` 解析 S 曲线、空间网格、同层 D56 strict 复算、
  3D 净空最小化全部由本次新增代码自写。
* 只把项目代码当**数据/定义**使用：`fanout1024.common`（真实 1024 连接表与端口表）、
  `reheight21.model`（21 高度表）；`fsd25d.path3d.transition_samples` 只用于
  **交叉校验**本文的解析 S 曲线公式（最大偏差 1.78×10⁻¹⁵ mm），不参与任何上报数值。
* 历史 `validation.json` / `crossing_stats.json` 仅用于**对账**（第 4、5 节）。

### 1.2 几何模型（直接从 JSON 原语反演）

| 对象 | 表示 | 距离评估 |
|---|---|---|
| `flat` part | `line`（精确线段）/`arc`（精确圆弧，圆心+半径+起角+扫角），高度 `z` 恒定 | 闭式解析：line-line / line-arc / arc-arc 精确最近距离；线-弧、弧-弧的驻点（"连接向量同时垂直于两切线"）与端点候选全部枚举 |
| `transition` part | 精确双圆弧 S 曲线（R=15，垂直平面内）：`u(φ)=R sinφ, w(φ)=z0+sign·R(1−cosφ)`，后半段镜像；按弧长参数化解析求点 | 对 flat：一维精确最小化（黄金分割，容差 1e-10）；对 transition：粗采样 1-Lipschitz 下界 + 嵌套黄金分割精化 |

### 1.3 数值误差上界（实测 + 理论）

| 量 | 误差上界 | 实测证据 |
|---|---|---|
| flat–flat 2D/3D 距离 | ≤ 1×10⁻¹² mm（闭式） | 独立数值解算器交叉校验 3721 对，**最大偏差 2.84×10⁻¹⁴ mm** |
| flat–transition 3D 最小距离 | ≤ 1×10⁻⁸ mm | 黄金分割 80 次迭代，s 容差 <1e-10 |
| transition–transition 3D | ≤ 1×10⁻⁶ mm | 粗采样步长 0.05 mm（Lipschitz 下界）+ 6 轮坐标精化 |
| 交叉点 | ≤ 1×10⁻⁹ mm | 解析二次/圆圆求交；1322 个事件的交点残差实测 **0.0** |
| 同层窗口/净空 | 采样步长 0.005 mm | 扫描 1016 个 2D 候选对/1253 个交叉对，未发现未覆盖近区 |

### 1.4 候选对生成（保证不漏）

7,917 条曲线（flat line 4,203 / flat arc 1,788 / transition 1,926）→ 2D 空间网格
（cell 1.0 mm，每个对象按 bbox 外扩 0.2 mm 栅格化，22,309 个非空 cell）。
**完整性论证**：任意一对 3D 距离 < 0.2 mm 的曲线，其 2D 投影距离也 < 0.2 mm，
因而必落在同一 cell（外扩 0.2 mm 的 bbox 保证），故候选集（跨路线 507,601 对）必然包含
所有净空/交叉相关事件；上报的全局最小值若 ≤0.2 mm 即为真全局最小值。

---

## 2. 六个必需量逐条回答

### 2.1 `minimum_distance_all_pairs_mm` = **0.0**

* 语义：全部同层/跨层中心线对的 3D 距离，**包含**允许的同层横穿。
* 结果：**0.0**。因为 D56 允许同层真实横穿，1322 个交叉事件的中心线距离恰为 0；
  这不是"净空违规"，是契约内的合法横穿（见 2.3/2.6）。
* 最快证据（`min_distance_evidence.json` → `minimum_distance_all_pairs.evidence`）：

| 字段 | 值 |
|---|---|
| 类型 | same-physical-height flat/flat legal transverse crossing |
| route pair | **17 / 129** |
| 物理高度 | z = **−0.350000 mm**（L2 层，两者同一物理平面） |
| 交点 | (x, y) = (**119.351967, 93.965181**) mm |
| 交叉角 | **75.2234°**（≥ 5° 合法下限） |
| 独立验证 | 两条路线的 2D 原语在交点处精确相交，交点残差 0.0 |

### 2.2 `minimum_clearance_non_crossing_mm` = **0.05**（分口径明细）

"排除合法交叉后"分三类分别复算（每一类都独立求最小值并给出证据）：

| 类别 | 最小净空 | 证据 | 阈值 | 判定 |
|---|---:|---|---:|---|
| **3D / 不同物理高度 flat–flat 对** | **0.050000000** | route 515 (z=0.55) vs route 623 (z=0.60)：dz=0.05，**XY 距离 = 0.0** ⇒ 3D 距离 = 0.05 | ≥0.05（由 \|dz\| 保证） | 合法（零余量） |
| **3D / transition vs flat** | **0.063593135** | route 711 的 transition（z: 0.5→0.15）vs route 472 的 flat（z=0.15），最近点 (133.875, 145.59054, 0.19490) | ≥0.05 | 合法 |
| **3D / transition vs transition** | **0.100000000** | route 333（z: 0→0.2）vs route 832（z: 0.5→0.3），最近点 (3.708323, 27.375, 0.200) | ≥0.05 | 合法 |
| **同层 2D / 非交叉对** | **0.086853441** | z=−0.05 平面 route 166 vs route 431 | ≥0.08（D56） | 合法 |
| 自净空（同一路线，\|Δs\|>1 mm） | 未发现 <1.0 mm 的自接近 | 全板 1024 条，逐路线 cKDTree 扫描 | ≥0.05 | 合法 |

* **汇总值 = 0.05**，来源是"不同物理高度 flat 对"：层间距恰为 0.05 mm 且两 flat 在 XY 上相交，
  这是 50 µm 层间距模型下的**理论下限**（3D 距离 ≥ |dz| ≥ 0.05 mm），不是新的违规。
* 关键对照：历史报告里的"最小 3D 净空 0.06359585 mm"**只是 transition 相关口径**
  （`validate21.measure_min_3d_clearance` 只扫 transition-vs-flat 与 transition-vs-transition，
  `validate21.py:1544`），**不包含** flat–flat 跨高度对。历史口径与本报告的 0.05/0.063593 并不矛盾，
  而是**两个不同集合**的最小值。
* 交叉核对：本报告的同层最小非交叉 0.086853441 mm 与冻结 strict 审计
  （`validation.json`：`min_non_crossing_centerline_mm = 0.086853441`）**逐位一致**。

### 2.3 `allowed_crossing_count` = **1322**（全部属于允许类别）

独立复算流程（不复用历史交叉代码）：

1. 把 2950 个 flat part 按**物理高度 z** 分组（同一 z 的接口引线/接口直连体合并，
   与 `nonc4/crossings.py:80-103`、`validate21.py:1683-1717` 的冻结口径一致）；
2. 在 21 个高度内对 2D 原语做精确求交（line-line / line-arc / arc-arc），
   合并 1e-6 mm 内重合的交点为 1 个事件；
3. 逐事件判定：**真实横穿**（|sin θ| ≥ sin 5°）、交点位于双方路线链内部
   （距链端点 > 1e-7 mm）、无共线重叠、无单原语对双交点、无窗口重叠、
   局部窗口半宽 ≤ 4 mm、窗口外距离 ≥ 0.08−1e-7 mm。

复算结果：

| 指标 | 独立复算 | 历史 `crossing_stats.json` | 一致性 |
|---|---:|---:|---|
| 交叉事件数 | **1322** | 1322 | ✅ |
| 唯一交叉线路对 | **1253** | 1253 | ✅ |
| 非法交叉事件 | **0** | — | ✅ |
| 事件级逐点匹配（route pair + 交点 ±1e-4 mm） | **1322/1322 = 100%** | — | ✅ 角度最大差 0.0° |
| 逐高度交叉数 | 21 个高度逐一相等 | — | ✅ 无差异 |
| 交叉角范围 | **5.33239° – 90.0°** | — | 全部 ≥ 5° |
| 最大单路交叉 | **19**（route 640） | 19 | ✅ |
| 有交叉的路线数 / 高度数 | 588 / 18 | 588 / 18 | ✅ |

补充：1322 个交叉分布在 18 个物理高度（z=−0.30/−0.25/−0.20 三个高度无交叉）；
同层最小非交叉距离 0.086853441 mm > 0.08 mm，说明"每个近区都被合法窗口覆盖，窗口外无欠距"。

### 2.4 `illegal_crossing_count` = **0**

非法交叉的独立判据（与 D56 strict 同义的几何条件）：相切/近平行（角度 < 5°）、端点触及、
共线重叠、同原语对双交点、豁免窗口过长（>4 mm）或窗口互相重叠、窗口外净空不足。
逐事件扫描 1253 个交叉路线对：上述 7 类条件**全部为 0**。因此非法交叉数 = **0**。

### 2.5 `clearance_violation_count` = **0**

按四类分别独立统计（阈值取契约值）：

| 类别 | 判据 | 被检对象数 | 违规数 |
|---|---|---:|---:|
| 同层 2D 净空 | 非交叉对 2D 中心线 < 0.08 mm；交叉对窗口外 < 0.08−1e-7 | 1253 个交叉对 + 全部 2D 候选对 | **0** |
| 不同物理高度 flat–flat | 3D 距离 < 0.05 mm（实际由 \|dz\|≥0.05 保证） | 424,340 对 | **0** |
| transition vs flat | 真 3D 距离 < 0.05 mm | 50,150 对（其中 71 对精确精化） | **0** |
| transition vs transition | 真 3D 距离 < 0.05 mm | 10,997 对（其中 9 对精确精化） | **0** |
| 自净空 | 3D 距离 < 0.05 mm（\|Δs\|>1 mm） | 1024 条路线 | **0** |

### 2.6 `crossing_exemption_policy`（D56 允许交叉的实际条件）

**适用几何对象**：同一**物理高度 z** 上的 flat–flat 对（分组键就是真实 z，不是 layer_id；
接口引线/接口直连体因 z 相同而合并审计）。

**实际条件（代码即契约，逐条引用）**：

| # | 条件 | 代码证据 | 实测 |
|---|---|---|---|
| 1 | 同层判据 = D56 2D 中心线净空 **0.08 mm**（宽 0.05 + 边距 0.03） | `four_side_1024/fanout1024/common.py:52-54`；`four_side_1024/fslw/config.py:12-14`；`four_side_1024/fanout1024/nonc4/crossings.py:29` | 同层非交叉最小 0.086853 mm > 0.08 |
| 2 | 交叉审计用 **strict** 策略（不是 legacy/exact） | `four_side_1024/fanout1024/nonc4/crossings.py:127`；`four_side_1024/d56/index.py:116,235`；`four_side_1024/l3d/world.py:46`；`four_side_1024/fanout1024/xyzrouter/world_adapter.py:42` | — |
| 3 | **角度下限 5°**：只豁免真实横穿，\|sin θ\| < sin 5° 记 `tangent_touch` 违规 | `four_side_1024/fslw/config.py:23`（`MIN_CROSS_ANGLE_DEG=5.0`）；`four_side_1024/fslw/validate_fslw.py:71,118`（`STRICT_SINE_MIN = sin(5°)`）；判定逻辑 `validate_fslw.py:1406-1412` | 实测角度范围 **5.33239°–90.0°**；仅 11 个事件 <10°（最小 5.332°），无 < 5° |
| 4 | 交点必须位于**双方路线链内部**（距端点 > 1e-7 mm），否则 `endpoint_touch` 违规 | `validate_fslw.py:101`(`ENDPOINT_TOUCH_TOL=1e-7`)、`1413-1420` | 0 个端点触及 |
| 5 | 不允许共线重叠（`overlap`）、单原语对双交点（`double_cross`）、同对两次交叉窗口重叠 | `validate_fslw.py:1380-1389, 1436-1448, 1562-1574` | 0 |
| 6 | **豁免窗口只限局部**：半宽 h\* 由真实线/弧几何解出（到交叉伙伴距离达到 0.08 mm 处）+2·sagitta(0.001 mm)，且必须 ≤ `STRICT_MAX_HALF_WINDOW=4.0 mm`，否则 `crossing_window_excessive` | `validate_fslw.py:104-122`（策略说明）、`:116`（4.0 mm 上限）、`:1335-1595`（`_evaluate_pair_strict` 求解/判定）；`fslw/config.py:22`（sagitta 0.0005） | 实测**最大窗口半宽 0.8624 mm** ≪ 4 mm |
| 7 | 窗口之外必须保持 **0.08 − 1e-7 mm** 净空（不能靠"整段原语豁免"） | `validate_fslw.py:116-121, 1576-1594` | 独立稠密扫描（步长 0.005 mm）：无未覆盖近区，0 spacing 违规 |
| 8 | 不同物理高度：**\|dz\| ≥ 0.05 mm 即合法**，XY 重叠本身不算违规 | `four_side_1024/fanout1024/common.py:309-310`；`four_side_1024/l3d/world.py:224-240`（`flat_cross_plane_too_close`，仅 `1e-9 < dz < clearance` 时违规；现行调用 clearance=0.05） | 21 高度间距全为 0.05；跨高度 flat 对最小 3D=0.05，0 违规 |
| 9 | transition 相关对象：**真 3D 中心线距离 ≥ 0.05 mm**，无交叉豁免 | `common.py:311`；`four_side_1024/fsd25d/world25d.py:320,450`（`transition_vs_flat` / `transition_vs_transition`）；`reheight21/validate21.py:1372` 显式 `World(stack, clearance=MIN_3D_CLEARANCE_MM)` | trans-flat 最小 0.063593、trans-trans 最小 0.1，0 违规 |

**结论**：1322 个交叉 = 1322 个满足上表 1–7 全部条件的"真实横穿"；豁免是**原有冻结 D56 strict 策略**的一部分，
不是本轮/G4 新增（冻结基线 `baseline_authoritative` 本身就有 2409 个交叉，且用同一 Validator 判 PASS）。

---

## 3. 50 µm 净空到底适用于哪些几何对象？

| 几何对象 | 规则 | 代码依据 | 本次实测 |
|---|---|---|---|
| **21 个物理高度的层间距** | 相邻高度 ≥ **0.05 mm** | `common.py:50`；`reheight21/model.py:100` | 21 个高度，相邻间距 **恒为 0.05 mm**（min=max=0.05） |
| **不同物理高度的 flat–flat 对** | \|dz\| ≥ 0.05 mm 即合法；此时 3D 距离 ≥ \|dz\| ≥ 0.05；**XY 重叠不算违规** | `common.py:309-310`；`l3d/world.py:224-240`；`fsd25d/world25d.py:9-11` | 最小 3D = **0.05**（route 515/623，z=0.55/0.60，XY 相交） |
| **任何涉及 transition 的对**（transition–flat、transition–transition） | **真 3D 中心线距离 ≥ 0.05 mm**，无豁免 | `common.py:311`；`world25d.py:320,450`；`validate21.py:1372` | trans–flat **0.063593135**；trans–trans **0.1** |
| **单条路线的自净空** | 3D 距离 ≥ 0.05 mm（排除 \|Δs\|≤1 mm 的局部邻域） | `world25d.py:540-569`（`self_clearance_violations`） | 未发现任何 <1.0 mm 的自接近 |

**不适用**（必须明确区分，否则会误判）：

| 几何对象 | 实际规则 | 依据 |
|---|---|---|
| **同一物理高度的 flat–flat 对** | **2D D56 规则**：0.05 宽 + 0.03 边距 = **0.08 mm 中心线净空**，且**合法横穿豁免**（≥5°，局部窗口） | `common.py:52-54,304-305`；`fslw/config.py:12-14`；`nonc4/crossings.py:29,127` |
| **80 µm 全局净空** | **明确不恢复**为全局 3D 规则（历史遗留值，仅活在同层 2D 规则里） | `common.py:57`（`LEGACY_GLOBAL_CLEARANCE_MM = 0.08  # NEVER restored as a global 3D rule`） |

因此："50 µm"在本项目里是**两件事**：(a) 21 高度的最小层间距，(b) 不共面/含 transition 对象的真 3D 净空；
同层平面对从来用的是 80 µm 2D + 横穿豁免。**不存在"所有中心线对无例外 ≥50 µm"的代码契约**。

---

## 4. 独立复核清单（任务书要求项）

| 复核项 | 独立复算结果 | 判定 |
|---|---|---|
| 布通 1024/1024 | `routed=1024, failed=0`；SHA256 与任务书一致 | ✅ |
| 同层交叉 1322 | 精确求交复算 = 1322（事件级 100% 匹配 `crossing_stats.json`，角度差 0.0°） | ✅ |
| 唯一交叉对 1253 | 复算 = 1253 | ✅ |
| 最大单路交叉 | **19**（route 640；有交叉路线 588 条，p95=11，均值 4.50） | ✅ |
| 368 条人工 U（`manual_group` 非空） | assignment_1024.csv 共 1024 行，**368** 条人工；Z1-U1..U4 各 64、Z2-U1 16 / U2 16 / U3 40 / U4 40；全部路线存在 | ✅ |
| R15 无违规 | flat 圆弧 **1788 段全部 R=15.000000000**；transition **1926 段全部 R=15**；`theta/footprint/length/end` 与解析公式误差全为 **0.0**；解析 S 曲线与生成器交叉校验最大偏差 **1.78×10⁻¹⁵ mm** | ✅ |
| 玻璃 150×150×1 边界 | 1,363,582 个中心线采样点：x∈[−1.8×10⁻¹⁰, 150.0000000001]、y∈[0,150]、z∈[−0.35, 0.65]；越界采样 0；最小中心线边距 −1.8×10⁻¹⁰ mm（端口恰在板边，属探索性中心线模型已知性质）；最小"边距−半宽" = −0.025 mm（见第 8 节局限） | ✅（中心线模型） |
| 端口 / 连接身份 | 1024 条唯一连接；源/目标端点、plane、row/side 与真实表 0 不匹配；路径起点/终点 XY 误差 0 / 4.1×10⁻¹⁰ mm，z 误差 0；端口方向点积 = 1 | ✅ |
| 21 个物理高度 | 实际使用高度集合与 `reheight21.model.PLANE_IDS` 的 21 个 z **完全一致**；相邻间距恒 0.05 mm | ✅ |
| 结构连续性 | 6,893 个几何连接点（原语级；其中部件级 3,852 个）：最大位置间隙 **4.95×10⁻¹⁰ mm**、最大切向夹角 **2.11×10⁻⁸ rad**、最大 z 间隙 0 | ✅ |
| 总路径长度 | 156,996.320802 mm（与历史 summary 一致） | ✅ |
| 方向/换层统计 | transition 1,926；中途换层 72 / excursion 36（Validator 计数，见第 5 节） | ✅ |

---

## 5. 独立 Validator 复跑（G3 best_valid）

命令（本次新建的复跑脚本，输出在本目录 `baseline_revalidation/`）：

```powershell
cd <project root>
.\.venv\Scripts\python.exe experiments\xyz_joint_g4_1024\00_baseline_audit\tools\run_baseline_revalidation.py
# 等价于:
#   four_side_1024.fanout1024.xyzrouter.validate_xyz.validate_xyz(
#       run_dir = outputs/.../XYZ_JOINT_G123_1024/best_valid,
#       baseline_dir = experiments/xyz_joint_g123_1024/baseline_authoritative,
#       out_dir = experiments/xyz_joint_g4_1024/00_baseline_audit/baseline_revalidation,
#       manual_policy = 'fully_optimizable')
```

结果（`baseline_revalidation/validation.json`、`revalidation_summary.json`）：

| 项目 | 值 |
|---|---|
| `validation_pass` | **true** |
| `violation_count` / `violation_total` | **0 / 0** |
| `manual_policy` / `policy_violations` | `fully_optimizable` / **0** |
| 各检查违规 | coverage / structure / native_metadata / radius / glass / clearance / ports / crossings / manual_frozen / model / synthetic **全部 0** |
| 交叉 | 1322 events / 1253 pairs / 0 violations / 21 heights |
| 3D 净空（历史口径） | `min_3d_clearance_mm = 0.063595846`，`lower_bound = 0.05`，0 violations |
| 同层最小非交叉 | **0.086853441 mm** |
| 人工 U 契约 | 368 条，0 mismatch |
| 运行时长 | 18.7 s（含独立最小净空扫描 + 7 个合成一致性测试全 PASS） |

> 说明：Validator 的 `0.063595846` 与本次独立精化的 `0.063593135` 相差 2.71×10⁻⁶ mm，
> 原因是历史扫描把 transition 离散成 0.02 mm 折线（`TRANSITION_SCAN_STEP_MM`），
> 折线距离是真实距离的**上界**；本次黄金分割精化值更紧。两者都 ≥ 0.05 mm，结论不变。

---

## 6. 为什么"1322 次交叉 + 0 几何违规"可以自洽

关键在于两条规则作用在**互不相交的对集合**上：

| 对集合 | 适用规则 | 允许距离 0？ | 依据 |
|---|---|---|---|
| 同一物理高度 flat–flat | 2D **D56 0.08 mm** + 合法横穿豁免 | ✅ 允许（仅在局部窗口内） | `nonc4/crossings.py:29,127`；`validate_fslw.py:104-122` |
| 不同物理高度 flat–flat | \|dz\| ≥ **0.05 mm**，XY 重叠合法 | ❌ 不可能为 0（\|dz\|≥0.05） | `common.py:309`；`l3d/world.py:224-240` |
| 任何涉及 transition 的对 | 真 3D ≥ **0.05 mm**，无豁免 | ❌ 不可能为 0 | `common.py:311`；`world25d.py:320,450` |

因此 1322 个距离为 0 的交叉**全部落在第一类集合**，而 50 µm 3D 规则只作用于第二、三类集合——
50 µm 规则"看不到"这 1322 个交叉，二者不冲突。只要这 1322 个交叉本身满足 D56 横穿条件
（本次独立复核：角度 5.332°–90°、真实横穿、窗口 ≤0.8624 mm、窗口外 ≥0.08 mm），
就应当是 0 违规。**独立复算的四类净空最小值**（0.05 / 0.063593 / 0.1 / 0.086853）分别
不违反各自的阈值，正是该自洽性的定量证据。

---

## 7. 与历史结论的对照、口径差异与风险（重要，请勿略过）

### 7.1 一致点（独立复算与历史 PASS 相互印证）

| 指标 | 历史 / 冻结结果 | 本次独立复算 | 一致 |
|---|---:|---:|---|
| 交叉事件 / 唯一对 | 1322 / 1253 | 1322 / 1253（逐点 100% 匹配） | ✅ |
| 最大单路交叉 | 19 | 19 | ✅ |
| 同层最小非交叉中心线 | 0.086853441 | **0.086853441** | ✅ 逐位一致 |
| 人工 U 契约 | 368 / 0 mismatch | 368 / 0 mismatch | ✅ |
| R15 | 无违规 | 全部 15.000000 / 0 误差 | ✅ |
| 21 高度最小间距 | 0.05 | 0.05 | ✅ |
| 独立 Validator | PASS（历史） | PASS（本次重跑，0 违规） | ✅ |

### 7.2 口径差异（不是矛盾，但必须写明）

1. **"最小 3D 净空 0.06359585"只覆盖 transition 相关对**。
   `validate21.measure_min_3d_clearance`（`validate21.py:1544-1652`）只量
   transition-vs-flat 与 transition-vs-transition；flat–flat 跨高度对被**结构性排除**
   （它们由层间距 ≥0.05 保证）。本报告的"3D 不同物理高度最小 = 0.05"（flat 对，由 0.05 层间距给出）
   才是"3D 不同物理高度对"的完整最小值。引用历史数字时必须标注口径，否则会被误读为
   "全板 3D 最小净空 0.0636"。
2. **0.05 mm 阈值处余量为 0**：层间距恒为 0.05 mm，且确实存在 XY 相交的相邻层 flat 对
   （route 515/623），所以"3D 不同高度最小净空"精确等于阈值 0.05 mm。
   按契约合法（\|dz\| ≥ 0.05 即合法），但这意味着**没有任何向下余量**；
   若未来工艺把 50 µm 改成 60 µm，该板将立即出现大量违规。
3. **代码默认值与现行调用不一致（文档级风险）**：
   `four_side_1024/l3d/world.py:79` 的 `World(..., clearance=None)` 会退化为
   `fslw.config.CLEARANCE_MM = 0.08 mm`（80 µm 历史值），其模块 docstring（`l3d/world.py:9-11`）
   与 `fsd25d/world25d.py:3-11` 也仍写着 "≥0.08 mm / 层间 ≥0.125 mm" 的旧模型描述。
   **现行 Validator/路由器全部显式传 0.05 mm**：
   `reheight21/validate21.py:1372`（`World(stack, clearance=MIN_3D_CLEARANCE_MM)`）、
   `xyzrouter/world_adapter.py:31`（`CLEARANCE_MM = 0.05`）。
   即：真实判定口径是 50 µm，但**默认参数/文档仍是 80 µm 历史值**——这是口径一致性的真实风险点，
   建议在最终报告中引用 50 µm 时同时注明"运行时显式传参 0.05，默认值 0.08 为历史遗留"。
   本次审计全部按**现行显式 0.05 mm 口径**判定。
4. **玻璃边距负值**：最小"边距−半宽" = −0.025 mm（端口中心线恰在 150 mm 板边）。
   这是探索性中心线模型的已知性质（`common.py:317-321` 的 `unconfirmed` 块明确
   "surface_process_margin not verified; the boundary waveguides only satisfy the current
   exploratory centreline model"），**不是本次发现的几何违规**，但**不能**宣称满足制造约束。

### 7.3 矛盾分析（任务书要求）

* **按仓库内现行代码契约：无矛盾。** 50 µm 不是全局规则；同层 80 µm + 横穿豁免是原契约。
* **若任务书原始物理要求 = "所有中心线对无例外 ≥ 50 µm"：存在矛盾**——
  1322 个合法交叉的中心线距离恰为 0，将全部变成硬违规。此时需要的是
  **需求级裁决**（是否保留同层横穿豁免），而不是几何修复；本审计**不自行扩大或新增豁免**，
  也**不隐瞒**该口径差异。
* 本次审计确认**未新增豁免**：所用豁免来自 G4 之前冻结的 D56 strict 策略
  （`d56/index.py:116,235`；`world.py:46`），冻结基线自带 2409 个交叉且用同一 Validator 判 PASS。

---

## 8. 局限性与不可宣称事项

1. **仅中心线几何模型**：光学串扰、弯曲损耗、交叉损耗均未验证
   （`fslw/config.py:32-34`：`CROSSING_LOSS status=unknown_uncalibrated`；
   `common.py:317-321` unconfirmed 块）。1322 只是**几何计数**，不是光学可行性结论。
2. **未验证制造约束**：无工艺 bias、侧壁角、折射率剖面、表面工艺余量、连接器外壳干涉
   （`fslw/config.py:46` `CONNECTOR_PITCH_STATUS` 未解决）；玻璃 1 mm 厚度与连接器安装方向为假设值
   （`fslw/config.py:55-58` `MANUFACTURING_CLAIM`）。
3. **21 高度为探索性层栈**（`reheight21/model.py` 与 `layer_stack` payload 均标
   `provenance=unconfirmed_simulation / formal_acceptance_allowed=false`）。
4. 本审计只证明"该结果满足当前探索性中心线几何契约"，**不得**表述为"满足全部制造约束"。

---

## 9. 交付物与复现

| 文件 | 内容 |
|---|---|
| `GEOMETRY_CONTRACT_AUDIT.md` | 本报告（可直接引用进最终报告） |
| [`audit_metrics.json`](audit_metrics.json) | 6 个必需量 + 全部独立复算细节 + 代码证据（file:line）+ 矛盾分析 |
| [`min_distance_evidence.json`](min_distance_evidence.json) | 全局最小距离 0 的证据事件、各口径最小净空证据、数值误差上界 |
| [`independent_metrics.json`](independent_metrics.json) | 独立几何计算的完整原始结果（含 1322 个事件、逐高度计数、距离自校验） |
| [`contract_evidence.json`](contract_evidence.json) | 契约取证（44 条 file:line）、50 µm 适用对象、自洽性论证、矛盾分析 |
| `baseline_revalidation/validation.json`、`revalidation_summary.json`、`validator_consistency_tests.json`、`revalidation_run.log` | 独立 Validator 复跑（PASS，0 违规） |
| [`six_quantities.json`](six_quantities.json) | 6 个必需量的紧凑可引用版本（含 run SHA、16 项检查、Validator 摘要） |
| `audit_progress.log` | 审计进度日志 |
| 代码 | [`g4/independent_metrics.py`](../../../four_side_1024/fanout1024/xyzrouter/g4/independent_metrics.py)、[`g4/contract_audit.py`](../../../four_side_1024/fanout1024/xyzrouter/g4/contract_audit.py)（+ `00_baseline_audit/tools/` 下的复跑/终验/诊断脚本） |

### 9.1 基线复现命令（本报告数值）

```powershell
cd <project root>
# 一次性完成：独立指标 + 6 个必需量 + 契约取证 + 独立 Validator 复跑（约 45–60 s）
.\.venv\Scripts\python.exe -m four_side_1024.fanout1024.xyzrouter.g4.contract_audit `
  --run-dir "outputs\manual_c4_new_connectivity\XYZ_JOINT_G123_1024\best_valid" `
  --out-dir "experiments\xyz_joint_g4_1024\00_baseline_audit" `
  --baseline-dir "experiments\xyz_joint_g123_1024\baseline_authoritative" `
  --manual-policy fully_optimizable --recompute --revalidate `
  --expect-sha256 711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077 `
  --expect-crossings 1322 --expect-pairs 1253 --expect-max-route 19
```

### 9.2 任意 run 复用（G4 终验，Phase 2）

`contract_audit` / `independent_metrics` 均为 `--run-dir` 参数化 CLI；对任意 1024 路线
XYZ run 目录可直接运行（输出 6 个必需量 + 独立复算 + 可选 Validator 复跑）：

```powershell
cd <project root>
# A) 契约审计（可选 --revalidate 同时跑独立 Validator；约 25 s + 20–40 s）
.\.venv\Scripts\python.exe -m four_side_1024.fanout1024.xyzrouter.g4.contract_audit `
  --run-dir <G4 最终 best_valid 目录> `
  --out-dir "experiments\xyz_joint_g4_1024\00_baseline_audit\FINAL_AUDIT" `
  --baseline-dir "experiments\xyz_joint_g123_1024\baseline_authoritative" `
  --manual-policy fully_optimizable --recompute --revalidate

# B) 或一键终验（同上 + 自动生成 FINAL_AUDIT_SUMMARY.md，约 45–90 s）
.\.venv\Scripts\python.exe experiments\xyz_joint_g4_1024\00_baseline_audit\tools\run_final_audit.py `
  --run-dir <G4 最终 best_valid 目录> --label G4_best
```

> CLI 可复用性已验证（只吃 `routes_l3d.json`，assignment/layer_planes 缺失时回退冻结基线）：
> 对冻结的 G1/G2/G3 基线快照（2409 交叉、routes SHA `36c57ad9…`）独立复算得到
> 2409 events / 2010 pairs / 0 illegal / 0 clearance violation，Validator PASS，
> 与历史 `validation.json`、`min_3d_clearance=0.06730354` 一致（见 `cli_smoke/frozen_g123_baseline/`）。
> 无期望值传入时对应检查自动标记为 skipped（`null`），其余硬检查（1024/1024、R15、玻璃、
> 端口身份、21 高度、非法交叉 0、净空违规 0、Validator PASS）照常生效。

**审计结论一句话**：G3 `best_valid` 在**现行探索性中心线契约**下是**合法解**：
1322 次同层交叉全部为允许的真实横穿，非法交叉 0、净空违规 0；但"3D 不同物理高度"的最小净空
恰为 0.05 mm（零余量），且"1322 交叉是否符合原始物理要求"取决于 50 µm 是否被理解为
"所有中心线无例外"的全局规则——该口径差异需项目负责人确认（第 7.3 节）。
