# 交叉来源分析报告（baseline FANOUT_FIRST_21_HEIGHT_REBALANCED_1024）

- 生成时间：2026-11-03T23:08:27
- baseline 目录：`C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\FANOUT_FIRST_21_HEIGHT_REBALANCED_1024`
- routes_l3d.json sha256：`1fe24c977c36c0b24692ee386213e6e870010ac1f0bed5c6b3a1eb4be53119d9`
- 交叉口径：与 `validate21.check_crossings` 完全一致的“同物理高度 strict D56 两两审计”（clearance=0.08 mm、sagitta=0.0005、policy=strict；z=0.0/0.5 的 interface 层自动合并冻结 lead 与 interface-direct body）；**本报告重算结果与基线 crossing_stats.json 逐层逐项一致**：11890 事件 / 9797 交叉对 / 13 个有交叉的高度 / 每路线分布 max=83、p95=60.0、mean=37.63、median=39.0。

## 0. 结论速览

1. 11890 个交叉事件只来自 13 个物理高度；8 个 manual 层（L2-L5、L10-L13）0 交叉，两个 interface 层上 924 条非 direct 路线的 1848 条 lead 与任何东西都不交叉。
2. 632/656 条可动路线参与交叉；368 条 manual 路线 0 交叉（冻结层从未出现交叉）。
3. 交叉的主项是“方向/象限互斥”：Z1 的竖直族 x 水平族端口弦 100% 交替，Z2 的四个角族跨族弦 73% 交替，同族内部只有 ~19-20%。
4. 交叉可分三类：forced=884（仅两个 interface 层的 direct/direct 交替对，Jordan 曲线强制）、avoidable=3868（端口弦不交替，纯 2D 重绕可消除）、uncertain=7138（端口弦交替，需换层）。
5. 异常层 L9/L14/Z2_INTERFACE 的 60 交叉 = 4 族 x 15 阶梯交叉，来自 corner-bundle 轨道块；与 L15-L19 的 1246-1560 差异不是“排列技巧”，而是轨道块不同（角部短弦 vs 全板对角线）。
6. 新 C4-free 分配的交叉下界：baseline 7868 对 -> 保持 C4 轨道同层只能到 ~6584 对 -> 打破 C4、逐路线重分配可到 **724 对**（降 90.8%）。

## 1. 方法与可复现性

- 代码：`analysis/scripts/`，一键复现：`python analysis/scripts/run_all.py`（确定性，无随机种子依赖）。
- 交叉定义：把每条路线的所有 flat 段按物理 z 合并（interface 层自动包含 lead 与 direct body），每层调用 `fslw.validate_fslw.audit_route_pairs(prepared, clearance=0.08, sagitta=0.0005, policy="strict")`，与 `validate21.check_crossings` 的代码路径逐行一致。
- 族定义：`Z1_NS/Z1_SN/Z1_EW/Z1_WE`（Z1-other 256 条 opposite 路线，按源->目标边）、`Z2_EN/Z2_ES/Z2_NW/Z2_SW`（Z2-other 400 条 adjacent 路线）、`Z1-U1..Z2-U4`（8 个冻结 manual U 组）。
- 允许层集合：Z1-other {6,7,20,1001,8}；Z2-other {9,14,15,16,1002,17,18,19}；manual 冻结。
- forced 判定树（同时写入 crossing_analysis.json header）：

```
Classification per crossing pair at its physical height. topology = port_chord_cross: the two routes straight port-to-port chords properly cross (alternating boundary order). (1) forced: both routes are DIRECT interface-body routes on the same interface height. Their entire path is one flat at that height attached to the two boundary ports, so two such flats with alternating ports must intersect on that disk (Jordan curve); the only escape is to convert one route into a 2-transition route (move it off the interface). (2) avoidable: port_chord_cross == false. A crossing-aware 2D router could separate the pair on the SAME height (the baseline layerwise router does no crossing avoidance), so the crossing is a routing-policy artefact. (3) uncertain: port_chord_cross == true for two non-direct routes. Their flat bodies start at interior stub ends (0.25 mm interface lead + R15 S-transition footprint, 2.4-5.1 mm inside the port), so boundary alternation does NOT by itself prove a forced same-height crossing; it shows the pair cannot be separated by an order-preserving 2D fan-out and most likely needs height separation, hence uncertain. separable_by_height = at least one partner is a movable route whose flat at this height is its body (moving that route to another allowed plane removes the same-height contact). A pinned interface lead of a non-direct route can never be moved by re-layering.
```

## 2. Q1-Q6 逐题回答

### Q1. Where do the 11890 same-height crossings physically come from?

Only 13 of the 21 routing heights produce crossings. The 4 manual-U heights L2-L5 and the 4 manual Z2 heights L10-L13 are completely crossing-free and no crossing involves an interface lead. Crossing mass by group: Z1 movable heights (L6,L7,L20,L8,Z1_INTERFACE) = 4510 events (37.9%), the 5 grid Z2 heights (L15-L19) = 7200 events (60.6%), the 3 corner Z2 heights (L9,L14,Z2_INTERFACE) = 180 events (1.5%). Per height: L2(z=-0.35)=0; L3(z=-0.30)=0; L4(z=-0.25)=0; L5(z=-0.20)=0; L6(z=-0.15)=986; L7(z=-0.10)=928; L20(z=-0.05)=964; Z1_INTERFACE(z=+0.00)=896; L8(z=+0.05)=736; L9(z=+0.10)=60; L10(z=+0.15)=0; L11(z=+0.20)=0; L12(z=+0.25)=0; L13(z=+0.30)=0; L14(z=+0.35)=60; L15(z=+0.40)=1246; L16(z=+0.45)=1478; Z2_INTERFACE(z=+0.50)=60; L17(z=+0.55)=1560; L18(z=+0.60)=1476; L19(z=+0.65)=1440.

### Q2. Which route families / family pairs generate the crossings and what is the per-route distribution?

All 11890 events belong to movable non-manual routes (manual routes: 0 events, all on the frozen manual heights). 632 of the 656 movable routes are involved, 24 are crossing-free (all on L9/L14/Z2_INTERFACE). Per-route distribution over the 632 involved routes: max 83, p95 60.0, mean 37.63, median 39.0, min 1; over all 1024 routes the mean is 23.22 (392 routes have zero crossings).

**交叉最多的 10 条路线：**

| 名次 | route_id | 族 | 基线层 | 交叉数 | 长度(mm) |
|---|---|---|---|---|---|
| 1 | 522 | Z2_ES | L17 | 83 | 273.9 |
| 2 | 520 | Z2_SW | L17 | 72 | 223.2 |
| 3 | 765 | Z2_EN | L15 | 72 | 199.9 |
| 4 | 541 | Z2_EN | L17 | 71 | 273.9 |
| 5 | 537 | Z2_EN | L17 | 69 | 283.2 |
| 6 | 540 | Z2_SW | L17 | 69 | 223.2 |
| 7 | 536 | Z2_SW | L17 | 68 | 246.2 |
| 8 | 564 | Z2_SW | L17 | 68 | 213.9 |
| 9 | 571 | Z2_NW | L18 | 68 | 195.4 |
| 10 | 538 | Z2_ES | L17 | 67 | 223.2 |

**交叉最多的 10 个路线对：** 609-612(Z2_EN/Z2_SW, 4次), 4-167(Z1_SN/Z1_WE, 3次), 5-168(Z1_NS/Z1_WE, 3次), 6-168(Z1_SN/Z1_WE, 3次), 7-167(Z1_SN/Z1_WE, 3次), 8-164(Z1_NS/Z1_WE, 3次), 8-168(Z1_NS/Z1_WE, 3次), 12-150(Z1_NS/Z1_EW, 3次), 12-159(Z1_NS/Z1_EW, 3次), 13-145(Z1_SN/Z1_EW, 3次)

### Q3. Why do L9/L14/Z2_INTERFACE have only 60 crossings when L15/L16/L19 have 1246-1476 with the same 12 orbits x 4 families composition?

All compared planes hold exactly 12 C4 orbits x 4 families = 48 routes, but they hold DIFFERENT orbit blocks of the frozen Z2-other pairing. L9/L14/Z2_INTERFACE carry orbits 233-244 / 221-232 / 209-220, i.e. the 36 "corner-bundle" orbits (E connectors 3-8 x S connectors 9-14): every route is a short 60-90 mm chord that stays inside one board quadrant and the four families live in four disjoint corners, so cross-family chords cannot meet; only the two port rows of the same family interact. L15-L19 carry orbits 129-192, the 64 "grid" orbits (E connectors 1-8 x N connectors 1-8): every route is a 150-220 mm diagonal from one board edge to another, all families share the board centre, 83-86% of all route pairs actually cross and 56-59% of them have alternating ports. The 60 crossings are therefore not a lucky permutation: they are exactly 4 families x 15 staircase crossings of two shifted port rows inside one corner.

### Q4. How many crossings are topologically forced, how many are avoidable by 2D re-pathing, and how many need height separation?

forced=884, avoidable (same-height 2D re-pathing suffices)=3868, uncertain (port chords alternate, so order-preserving 2D separation is impossible and another height is needed)=7138. The forced class is the alternating-port direct-body/direct-body contacts on the two interface heights: 824 events on Z1_INTERFACE and 60 on Z2_INTERFACE. Both routes are then a single flat attached to two boundary ports at that height, so alternating ports make the intersection unavoidable while both stay direct (Jordan curve); the only escape is to convert one route into a 2-transition route. Crossing angle histogram: 15-45deg=665, 45-90deg=10809, 5-15deg=416 (mean 77.33 deg). separable_by_height is true for all 11890 events by the definition (every event has at least one movable body flat), but the binding constraint is topological, not immovability.

**forced 示例（interface 层 direct/direct）：**

- route 109 (Z1_NS) x route 114 (Z1_SN) @ Z1_INTERFACE (42.625, 20.820), 63.3 deg
- route 109 (Z1_NS) x route 115 (Z1_NS) @ Z1_INTERFACE (42.625, 136.481), 64.3 deg
- route 109 (Z1_NS) x route 116 (Z1_SN) @ Z1_INTERFACE (42.625, 17.947), 65.4 deg
- route 109 (Z1_NS) x route 122 (Z1_SN) @ Z1_INTERFACE (42.625, 15.000), 90.0 deg

**avoidable 示例（端口弦不交替，2D 重绕即可分开）：**

- route 2 (Z1_NS) x route 4 (Z1_SN) @ L6 (6.375, 142.913), 14.8 deg
- route 2 (Z1_NS) x route 4 (Z1_SN) @ L6 (14.625, 26.528), 63.3 deg
- route 2 (Z1_NS) x route 5 (Z1_NS) @ L6 (6.625, 142.070), 18.2 deg
- route 2 (Z1_NS) x route 5 (Z1_NS) @ L6 (14.590, 126.608), 58.1 deg

**uncertain 示例（端口弦交替、只能换层）：**

- route 1 (Z1_NS) x route 137 (Z1_WE) @ L6
- route 1 (Z1_NS) x route 138 (Z1_EW) @ L6
- route 1 (Z1_NS) x route 139 (Z1_WE) @ L6

### Q5. Do fan-out / interface leads and lead-space conflicts cause the crossings?

No. The 460 Z1 + 464 Z2 non-direct routes contribute 1848 fixed 0.25 mm radial interface leads (2 per route) and none of them crosses anything: lead-involved events = 0. Every interface-height event (956) is a direct-body/direct-body contact between the 52 / 48 interface-direct routes. Fan-out pressure is therefore a DENSITY problem on the interface heights (512 route footprints on one height, the most congested height of the stack, min non-crossing centreline 0.105 mm), not a lead-crossing problem.

### Q6. Which families can share a layer with zero/low crossings, and how should the 256 Z1 / 400 Z2 movable routes be distributed over the allowed planes?

Plane-sharing risk is the port-chord alternation rate (an alternating pair cannot share a height without a crossing). Z1 group: every vertical x horizontal family pair alternates on 100% of its pairs (Z1_NS x Z1_WE 100%; Z1_EW x Z1_NS 100%; Z1_SN x Z1_WE 100%; Z1_EW x Z1_SN 100%; Z1_EW x Z1_WE 19%; Z1_NS x Z1_SN 19%), while within-family alternation is small (Z1_EW 0.193; Z1_NS 0.191; Z1_SN 0.196; Z1_WE 0.193). Z2 group: the four corner families alternate on ~73% of cross pairs (Z2_EN x Z2_ES 73%; Z2_EN x Z2_NW 73%; Z2_ES x Z2_SW 73%; Z2_NW x Z2_SW 73%), within-family rates Z2_EN 0.204; Z2_ES 0.204; Z2_NW 0.204; Z2_SW 0.204, but the route-level pairing matters more than the family label: the 36 corner-bundle orbits (short chords inside one quadrant) alternate only inside their own family, while the 64 grid orbits (150-220 mm diagonals) alternate with almost everything. Baseline topology conflicts = 7868 pairs. Best computed re-assignment (C_greedy_c4_free) = 724 pairs (C4-free per-route greedy); the C4-orbit-respecting orbit greedy gives 6584 pairs; Z1 vertical/horizontal family separation alone gives 5173 pairs. Recommended distribution: IF the C4-orbit-on-one-plane rule is dropped (that is what the C4-free experiment buys) use the per-route greedy distribution Z1 {6:57,7:57,8:60,1001:60,20:22} and Z2 {9:51,14:51,15:51,16:51,1002:49,17:49,18:49,19:49} - about 105 routes become interface-direct, close to the baseline 100. If the C4 orbits must stay whole the floor stays ~6584, because every orbit mixes vertical and horizontal Z1 routes; the best orbit-respecting fallback is the Z1 vertical/horizontal split plus the Z2 corner/grid split. In both cases keep ~50-60 routes per height and let the crossing-aware 2D router remove the remaining non-alternating events.

## 3. 每层交叉表（21 个物理高度）

| 层 | 类型 | z (mm) | 本层路线 | 交叉事件 | 交叉对 | 弦交叉对(拓扑风险) | 交叉率 | forced | uncertain | avoidable | 主要族构成 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L2 | body | -0.35 | 64 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z1-U1:64 |
| L3 | body | -0.30 | 64 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z1-U2:64 |
| L4 | body | -0.25 | 64 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z1-U3:64 |
| L5 | body | -0.20 | 64 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z1-U4:64 |
| L6 | body | -0.15 | 52 | 986 | 874 | 816 | 65.9% | 0 | 870 | 116 | Z1_EW:13, Z1_NS:17, Z1_SN:9, Z1_WE:13 |
| L7 | body | -0.10 | 52 | 928 | 866 | 836 | 65.3% | 0 | 860 | 68 | Z1_EW:13, Z1_NS:14, Z1_SN:12, Z1_WE:13 |
| L20 | body | -0.05 | 52 | 964 | 886 | 832 | 66.8% | 0 | 856 | 108 | Z1_EW:13, Z1_NS:13, Z1_SN:13, Z1_WE:13 |
| Z1_INTERFACE | interface_body | +0.00 | 52 | 896 | 860 | 824 | 64.9% | 824 | 0 | 72 | Z1_EW:13, Z1_NS:13, Z1_SN:13, Z1_WE:13 |
| L8 | body | +0.05 | 48 | 736 | 696 | 656 | 61.7% | 0 | 656 | 80 | Z1_EW:12, Z1_NS:12, Z1_SN:12, Z1_WE:12 |
| L9 | body | +0.10 | 48 | 60 | 60 | 60 | 5.3% | 0 | 60 | 0 | Z2_EN:12, Z2_ES:12, Z2_NW:12, Z2_SW:12 |
| L10 | body | +0.15 | 16 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z2-U1:16 |
| L11 | body | +0.20 | 16 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z2-U2:16 |
| L12 | body | +0.25 | 40 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z2-U3:40 |
| L13 | body | +0.30 | 40 | 0 | 0 | 0 | 0.0% | 0 | 0 | 0 | Z2-U4:40 |
| L14 | body | +0.35 | 48 | 60 | 60 | 60 | 5.3% | 0 | 60 | 0 | Z2_EN:12, Z2_ES:12, Z2_NW:12, Z2_SW:12 |
| L15 | body | +0.40 | 48 | 1246 | 954 | 664 | 84.6% | 0 | 666 | 580 | Z2_EN:12, Z2_ES:12, Z2_NW:12, Z2_SW:12 |
| L16 | body | +0.45 | 52 | 1478 | 1131 | 784 | 85.3% | 0 | 784 | 694 | Z2_EN:13, Z2_ES:13, Z2_NW:13, Z2_SW:13 |
| Z2_INTERFACE | interface_body | +0.50 | 48 | 60 | 60 | 60 | 5.3% | 60 | 0 | 0 | Z2_EN:12, Z2_ES:12, Z2_NW:12, Z2_SW:12 |
| L17 | body | +0.55 | 52 | 1560 | 1143 | 776 | 86.2% | 0 | 826 | 734 | Z2_EN:13, Z2_ES:13, Z2_NW:13, Z2_SW:13 |
| L18 | body | +0.60 | 52 | 1476 | 1105 | 736 | 83.3% | 0 | 736 | 740 | Z2_EN:13, Z2_ES:13, Z2_NW:13, Z2_SW:13 |
| L19 | body | +0.65 | 52 | 1440 | 1102 | 764 | 83.1% | 0 | 764 | 676 | Z2_EN:13, Z2_ES:13, Z2_NW:13, Z2_SW:13 |

## 4. 族对交叉矩阵

完整 16x16 矩阵（行=族 A，列=族 B，事件数，`.` 表示 0）：

| | Z1_NS | Z1_SN | Z1_EW | Z1_WE | Z2_EN | Z2_ES | Z2_NW | Z2_SW | Z1-U1 | Z1-U2 | Z1-U3 | Z1-U4 | Z2-U1 | Z2-U2 | Z2-U3 | Z2-U4 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z1_NS | 135 | 344 | 909 | 917 | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1_SN | 344 | 95 | 774 | 766 | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1_EW | 909 | 774 | 117 | 352 | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1_WE | 917 | 766 | 352 | 101 | . | . | . | . | . | . | . | . | . | . | . | . |
| Z2_EN | . | . | . | . | 236 | 844 | 838 | 1592 | . | . | . | . | . | . | . | . |
| Z2_ES | . | . | . | . | 844 | 222 | 1528 | 824 | . | . | . | . | . | . | . | . |
| Z2_NW | . | . | . | . | 838 | 1528 | 238 | 822 | . | . | . | . | . | . | . | . |
| Z2_SW | . | . | . | . | 1592 | 824 | 822 | 236 | . | . | . | . | . | . | . | . |
| Z1-U1 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1-U2 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1-U3 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z1-U4 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z2-U1 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z2-U2 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z2-U3 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |
| Z2-U4 | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . | . |

前 26 个族对（按事件数排序）：

| 族 A | 族 B | 交叉事件 | 主要发生层 |
|---|---|---|---|
| Z2_EN | Z2_SW | 1592 | 17:338, 19:338, 16:336 |
| Z2_ES | Z2_NW | 1528 | 16:338, 19:338, 18:334 |
| Z1_NS | Z1_WE | 917 | 6:241, 7:192, 20:171 |
| Z1_EW | Z1_NS | 909 | 6:235, 7:190, 20:171 |
| Z2_EN | Z2_ES | 844 | 17:193, 16:169, 18:169 |
| Z2_EN | Z2_NW | 838 | 17:185, 16:169, 18:169 |
| Z2_ES | Z2_SW | 824 | 17:173, 16:169, 18:169 |
| Z2_NW | Z2_SW | 822 | 17:171, 16:169, 18:169 |
| Z1_EW | Z1_SN | 774 | 20:171, 1001:169, 7:159 |
| Z1_SN | Z1_WE | 766 | 20:171, 1001:169, 7:159 |
| Z1_EW | Z1_WE | 352 | 20:88, 6:76, 1001:72 |
| Z1_NS | Z1_SN | 344 | 20:88, 1001:72, 6:69 |
| Z2_NW | Z2_NW | 238 | 17:87, 18:35, 16:27 |
| Z2_EN | Z2_EN | 236 | 18:57, 15:44, 16:37 |
| Z2_SW | Z2_SW | 236 | 17:61, 18:49, 16:37 |
| Z2_ES | Z2_ES | 222 | 17:73, 18:33, 16:27 |
| Z1_NS | Z1_NS | 135 | 6:43, 7:35, 20:25 |
| Z1_EW | Z1_EW | 117 | 6:29, 7:29, 20:27 |
| Z1_WE | Z1_WE | 101 | 20:25, 6:23, 7:21 |
| Z1_SN | Z1_SN | 95 | 20:27, 7:20, 1001:19 |

## 5. 关键异常：L9/L14/Z2_INTERFACE（60）vs L15-L19（1246-1560）

### 5.1 三组同构成层的关键数字

| 层 | z (mm) | 路线数 | C4 轨道块 | 轨道 id | 弦交叉率 | 弦长中位数(mm) | 交叉事件 | 同族交叉 | 跨族交叉 |
|---|---|---|---|---|---|---|---|---|---|
| L9 | +0.10 | 48 | 12 | 233-244 | 5.3% | 83.2 | 60 | 60 | 0 |
| L14 | +0.35 | 48 | 12 | 221-232 | 5.3% | 69.2 | 60 | 60 | 0 |
| Z2_INTERFACE | +0.50 | 48 | 12 | 209-220 | 5.3% | 57.5 | 60 | 60 | 0 |
| L15 | +0.40 | 48 | 12 | 181-192 | 58.9% | 132.9 | 1246 | 110 | 1136 |
| L16 | +0.45 | 52 | 13 | 155-167 | 59.1% | 178.4 | 1478 | 128 | 1350 |
| L17 | +0.55 | 52 | 13 | 129-141 | 58.5% | 159.5 | 1560 | 252 | 1308 |
| L18 | +0.60 | 52 | 13 | 142-154 | 55.5% | 145.4 | 1476 | 174 | 1302 |
| L19 | +0.65 | 52 | 13 | 168-180 | 57.6% | 172.5 | 1440 | 88 | 1352 |

低交叉组 = L9/L14/Z2_INTERFACE；高交叉组 = L15/L16/L17/L18/L19。低交叉组每层 12 个 C4 轨道/48 条路线，高交叉组每层 12-13 个轨道/48-52 条路线（每轨道 4 个族），但**承载的轨道块完全不同**：低交叉组 = 轨道 209-244（corner-bundle），高交叉组 = 轨道 129-192（grid）。

### 5.2 为什么定是 60 而不是 0：端口配对（permutation）结构

**L9（z=+0.10）Z2_ES 族的 12 条路线按端口行分组：**

- E07 行（6 条）：route_ids = 929, 933, 937, 941, 945, 949，目标端口 = S09, S10, S11, S12, S13, S14
- E08 行（6 条）：route_ids = 953, 957, 961, 965, 969, 973，目标端口 = S09, S10, S11, S12, S13, S14

**L14（z=+0.35）Z2_ES 族的 12 条路线按端口行分组：**

- E05 行（6 条）：route_ids = 881, 885, 889, 893, 897, 901，目标端口 = S09, S10, S11, S12, S13, S14
- E06 行（6 条）：route_ids = 905, 909, 913, 917, 921, 925，目标端口 = S09, S10, S11, S12, S13, S14

**Z2_INTERFACE（z=+0.50）Z2_ES 族的 12 条路线按端口行分组：**

- E03 行（6 条）：route_ids = 833, 837, 841, 845, 849, 853，目标端口 = S09, S10, S11, S12, S13, S14
- E04 行（6 条）：route_ids = 857, 861, 865, 869, 873, 877，目标端口 = S09, S10, S11, S12, S13, S14

每一行 6 条弦在行内是**单调配对**（E 侧 y 递减、S 侧 x 递增，顺序相反），所以行内 0 交叉；两行之间由于整行在 E 侧平移了 9 mm、目标 S 侧只平移 0.25 mm，交叉数 = 满足 i<j 的端口对数量 = 5+4+3+2+1 = **15/族**，4 族 = 60。这正是 L9/L14/Z2_INTERFACE 的全部交叉事件（实测这 3 层同族交叉=全部、跨族交叉=0）。

**L9 的 12 条 Z2_ES 弦（真实 route id / 端点 / 坐标 / 弦长）：**

| route_id | 轨道 | 源端口 | 目标端口 | 源坐标 | 目标坐标 | 弦长(mm) | 该层交叉数 |
|---|---|---|---|---|---|---|---|
| 929 | 233 | E07:2:14 | S09:2:4 | (150.000, 62.875) | (78.375, 0.000) | 95.31 | 5 |
| 933 | 234 | E07:2:13 | S10:2:4 | (150.000, 62.625) | (87.375, 0.000) | 88.56 | 4 |
| 937 | 235 | E07:2:12 | S11:2:4 | (150.000, 62.375) | (96.375, 0.000) | 82.26 | 3 |
| 941 | 236 | E07:2:11 | S12:2:4 | (150.000, 62.125) | (105.375, 0.000) | 76.49 | 2 |
| 945 | 237 | E07:2:10 | S13:2:4 | (150.000, 61.875) | (114.375, 0.000) | 71.40 | 1 |
| 949 | 238 | E07:2:9 | S14:2:4 | (150.000, 61.625) | (123.375, 0.000) | 67.13 | 0 |
| 953 | 239 | E08:2:14 | S09:2:3 | (150.000, 71.875) | (78.125, 0.000) | 101.65 | 0 |
| 957 | 240 | E08:2:13 | S10:2:3 | (150.000, 71.625) | (87.125, 0.000) | 95.31 | 1 |
| 961 | 241 | E08:2:12 | S11:2:3 | (150.000, 71.375) | (96.125, 0.000) | 89.42 | 2 |
| 965 | 242 | E08:2:11 | S12:2:3 | (150.000, 71.125) | (105.125, 0.000) | 84.10 | 3 |
| 969 | 243 | E08:2:10 | S13:2:3 | (150.000, 70.875) | (114.125, 0.000) | 79.44 | 4 |
| 973 | 244 | E08:2:9 | S14:2:3 | (150.000, 70.625) | (123.125, 0.000) | 75.57 | 5 |

**对照 L15 的 12 条 Z2_EN 弦：**

| route_id | 轨道 | 源端口 | 目标端口 | 弦长(mm) | 该层交叉数 |
|---|---|---|---|---|---|
| 721 | 181 | E05:2:7 | N07:2:5 | 139.32 | 4 |
| 725 | 182 | E06:2:7 | N07:2:6 | 132.37 | 5 |
| 729 | 183 | E07:2:7 | N07:2:7 | 125.69 | 6 |
| 733 | 184 | E08:2:7 | N07:2:8 | 119.31 | 7 |
| 737 | 185 | E01:2:8 | N08:2:1 | 164.21 | 4 |
| 741 | 186 | E02:2:8 | N08:2:2 | 156.32 | 4 |
| 745 | 187 | E03:2:8 | N08:2:3 | 148.57 | 4 |
| 749 | 188 | E04:2:8 | N08:2:4 | 140.96 | 4 |
| 753 | 189 | E05:2:8 | N08:2:5 | 133.53 | 3 |
| 757 | 190 | E06:2:8 | N08:2:6 | 126.30 | 2 |
| 761 | 191 | E07:2:8 | N08:2:7 | 119.31 | 1 |
| 765 | 192 | E08:2:8 | N08:2:8 | 112.61 | 0 |

结论：L9/L14/Z2_INTERFACE 低交叉**不是**因为排列巧妙，而是因为这些轨道块本身是"角部短弦"：4 个族分别落在 4 个角（跨族弦不相交，跨族交叉 = 0），只有同族两行之间的阶梯交叉（每族 15）。L15-L19 承载的 "grid" 轨道块是 150-220 mm 的长对角线，4 个族全部穿过板中心，跨族交叉占 91-93%，所以 1246-1560。由此可见：“混合层可以近乎无交叉”这个说法**只对 corner-bundle 轨道块成立**；对 grid 轨道块，同层混放必然高交叉，必须靠重新分配（把互斥对拆到不同层）或跨层绕行解决。

## 6. 诚实分类：(A) 拓扑强制 / (B) 2D 重绕可避免 / (C) fanout、lead 空间冲突

### (A) 拓扑强制（forced，884 事件）

- 只发生在两个 interface 物理高度，且只发生在 **direct/direct** 路线对之间：这两类路线的整条路径就是一层 flat，两端直接连到边界端口，没有 lead、没有 transition；当两条这样的 flat 的 4 个边界端口沿板边界交替时，两条弧线在圆盘内必然相交（Jordan 曲线），**只要两条路线都保持 direct 就不可消除**。baseline 中 Z1_INTERFACE 有 824 个、Z2_INTERFACE 有 60 个这样的交替 direct/direct 交叉对。
- 严格说明：这里的“夹点”是边界端口 + 无 transition 的整层 flat。对非 direct 路线，主体 flat 的两端在端口内侧 2.4-5.1 mm（0.25 mm lead + R15 S 过渡的 footprint），属于内部点，**边界交替本身不能证明同层交叉必然发生**，所以这类只判 uncertain（见下）。
- manual 路线（368 条）全部冻结在 8 个 manual 层，manual 层 0 交叉，所以没有任何“冻结导致的强制交叉”。

### (B) 2D 重绕可避免（avoidable，3868 事件）

- 端口弦**不**交替的交叉对：理论上可以由 crossing-aware 2D 路由器在同一层内绕开，baseline 的 layerwise 2D 布线完全不做交叉规避，所以这些交叉是布线策略造成的，不是几何必然。
- 数量上以 L15-L19 最明显：这些层的 954-1143 个交叉对里有 290-369 对属此类（580-740 个事件），来自长对角线主体在 clearance/R15 约束下产生的弯折。

### (C) fanout / lead 空间冲突

- 实测 **lead 与任何几何都不交叉**：924 条非 direct 路线在两个 interface 层共有 1848 条 lead，总共 0 交叉事件；interface 层的所有交叉都是 52/48 条 interface-direct 主体的 direct/direct 接触。
- fanout 压力表现为“密度”而不是“交叉”：interface 层一个物理高度上叠了 512 条路线的痕迹（1848 条 lead + 52/48 条 direct body），是全叠层最拥塞的高度；baseline 在该层的非交叉中心线最小间距为 0.105 mm（Z1）/2.71 mm（Z2），仍在 0.08 mm 规则之上。
- 因此 lead/fanout 不是本数据集交叉的来源；接口层的风险是“把更多路线改成 direct 会让 direct/direct 强制交叉快速上升”，分配时应限制 interface 层 direct 路线数量（baseline 100 条已产生 884 个 forced 交叉）。

## 7. 新 C4-free 层分配建议（含定量下界）

| 方案 | 说明 | 同层弦交叉对（下界） | 每层路线数 |
|---|---|---|---|
| A_baseline_21h | frozen baseline assignment of the 21-height run | **7868** | 6:52, 7:52, 8:48, 9:48, 14:48, 15:48, 16:52, 17:52, 18:52, 19:52, 20:52, 1001:52, 1002:48 |
| B_z1_orientation_split | Z1 vertical families (NS/SN, 128 routes) on {6,7}, horizontal families (EW/WE, 128 routes) on {20,1001,8}; Z2 unchanged vs baseline | **5173** | 6:64, 7:64, 8:42, 9:48, 14:48, 15:48, 16:52, 17:52, 18:52, 19:52, 20:43, 1001:43, 1002:48 |
| C_greedy_c4_free | per-route greedy + local search on the alternation graph (4 restarts, best kept), capacity 60 routes/plane for Z1 and 56 for Z2, C4 orbit constraint dropped | **724** | 6:57, 7:57, 8:60, 9:51, 14:51, 15:51, 16:51, 17:49, 18:49, 19:49, 20:22, 1001:60, 1002:49 |
| D_orbit_round_robin_length_sorted | keep each C4 orbit on one plane, sort orbits by chord length and round-robin over the allowed planes (long grid orbits and short corner orbits end up on different planes) | **7896** | 6:52, 7:52, 8:48, 9:52, 14:52, 15:52, 16:52, 17:48, 18:48, 19:48, 20:52, 1001:52, 1002:48 |
| E_orbit_greedy | greedy + local search on the orbit-conflict graph keeping each C4 orbit on a single plane (capacity 60 routes Z1 / 56 Z2) | **6584** | 6:52, 7:52, 8:52, 9:40, 14:44, 15:56, 16:56, 17:56, 18:40, 19:52, 20:52, 1001:48, 1002:56 |

关键判据：**同层弦交叉对 = 端口弦交替（alternating）的路线对**——它们即使由完美的 2D 路由器处理，只要还共用同一物理层，就至少产生一个交叉（baseline 实测交替对 100% 都会交叉）。因此该数量是任何层分配方案的交叉数下界。

- baseline：7868 对（实测 9797 个交叉对 / 11890 事件）。
- 保持 C4 轨道整体同层（orbit greedy）：6584 对 —— C4 约束几乎锁死了优化空间，因为每个 C4 轨道内部同时含竖直族与水平族路线。
- 打破 C4、逐路线重分配（C4-free greedy）：724 对，降低 90.8%。
- 仅对 Z1 做“竖直/水平族分层”（B 方案）：5173 对。

推荐（给新的 C4-free 层分配实验）：
1. **真正允许 C4 轨道被拆开**（这是本分析里唯一的大杠杆：轨道整体同层的下界 ~6584，逐路线重分配可到 ~724）：直接采用 C 方案的分布 Z1 = 6:57, 7:57, 8:60, 20:22, 1001:60、Z2 = 9:51, 14:51, 15:51, 16:51, 17:49, 18:49, 19:49, 1002:49；此时约 105 条路线落在 interface 层成为 direct（baseline 为 100 条）。
2. 如果必须保持 C4 轨道整体同层（回落方案）：Z1 采用竖直/水平族分层、Z2 采用 corner-bundle/grid 分层，并在每个 grid 层内尽量把“长对角线”路线分散；该情形下交叉下界仍在 5000-6600，无法接近 0。
3. 每层控制在 ~50-60 条（C 方案最大 60），保持 baseline 的 0.05 mm 层间距与 0.08 mm 同层规则。
4. interface 层 direct 路线数量控制在 ~100 条量级：direct 路线会带来 Jordan 强制的 direct/direct 交叉（baseline 100 条 direct 产生 884 个 forced 交叉），不宜继续增加。
5. 剩余同层交替对交给 crossing-aware 2D 路由器（新的 cross-router）去消除非交替的交叉，交替对只能靠层分配继续拆分（baseline 实测交替对 100% 都会交叉）。

## 8. 产物清单

- `analysis/crossing_analysis.json`：11890 条完整交叉记录（含 family/category/port_chord_cross/forced_class/reason/separable_by_height）、1024 条 per-route、21 层聚合、16x16 族对矩阵、Q1-Q6 答案、L9/L15 异常证据。
- `analysis/crossing_conflict_graph.json`：656 个可动路线节点 + 基线交叉对与端口弦交替风险对的并集边（含 topology=forced/none/uncertain、chord_angle、bbox_overlap）。
- `analysis/plots/`：21 张逐层几何+交叉点图、全局热点密度图、top-10 路线图、每路线直方图、逐层柱状图、族对矩阵热图、L9 vs L15 对比图、拓扑风险 vs 实测对比图。
- `analysis/analysis_summary_for_lead.md`：给 Lead 的 40 行摘要。
