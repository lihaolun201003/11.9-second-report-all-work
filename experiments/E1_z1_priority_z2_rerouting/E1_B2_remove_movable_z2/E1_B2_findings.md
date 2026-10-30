# E1_B2 诊断结果 (DIAGNOSTIC ONLY)

==============================================================================
DIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION
This directory is a Z2-removal diagnostic, not a router solution.
The payload in routes_1024.json intentionally misses Z2 routes and
is saved as "not_validated". Do NOT use it as a deliverable.
==============================================================================

- 保留路线: 824/1024; 移除 Z2 路线 200 条 (这不是合法的 1024 通道方案)
- 29 个 C2 pair-direction 中贪心抬升成功: **28/29** (56 条 Z1 路线); 失败: 1
- 独立窗口模式(pair 两成员各自窗口)合法: **13/29**

## 关键数字 (诊断世界 vs 同保留集合未抬升基线)

| metric | base (same kept set, unlifted) | E1_B2 | delta |
|---|---|---|---|
| unique crossing pairs | 5326 | 4838 | -488 |
| Z1 (z=0) crossing pairs | 5256 | 4464 | -792 |
| high-layer crossing pairs | 70 | 374 | 304 |
| Z1-only subset: Z1 pairs | 5256 | 4464 | -792 |
| Z1-only subset: high pairs | 70 | 374 | 304 |
| transitions | 540 | 652 | 112 |
| total length mm | 79701.896 | 79709.2422 | 7.3462 |

## 抬升窗口 (pair-together, 最近端口合法窗口)

| pair | layer | a_in | a_out | 合法层数 | 候选数 |
|---|---|---|---|---|---|
| 1_EW | L2 | 56.00 | 56.00 | 6 | - |
| 1_NS | L2 | 59.00 | 59.00 | 6 | - |
| 36_EW | L2 | 64.00 | 64.00 | 6 | - |
| 36_NS | L2 | 65.00 | 65.00 | 6 | - |
| 40_EW | L2 | 62.00 | 62.00 | 6 | - |
| 40_NS | L2 | 60.00 | 60.00 | 6 | - |
| 41_EW | L2 | 64.00 | 64.00 | 6 | - |
| 41_NS | L2 | 54.00 | 54.00 | 6 | - |
| 42_EW | L3 | 54.00 | 54.00 | 5 | - |
| 42_NS | L2 | 61.00 | 61.00 | 6 | - |
| 43_EW | L3 | 62.00 | 62.00 | 5 | - |
| 43_NS | L2 | 61.00 | 61.00 | 6 | - |
| 44_EW | L3 | 62.00 | 62.00 | 5 | - |
| 44_NS | L2 | 62.00 | 62.00 | 6 | - |
| 46_EW | L3 | 63.00 | 63.00 | 4 | - |
| 46_NS | L5 | 63.00 | 63.00 | 2 | - |
| 47_EW | L3 | 63.00 | 63.00 | 2 | - |
| 47_NS | L5 | 63.00 | 63.00 | 2 | - |
| 48_EW | L2 | 63.00 | 63.00 | 3 | - |
| 48_NS | L5 | 63.00 | 63.00 | 2 | - |
| 49_EW | L2 | 52.00 | 52.00 | 5 | - |
| 113_NS | L4 | 60.00 | 60.00 | 4 | - |
| 114_NS | L4 | 56.00 | 56.00 | 4 | - |
| 115_NS | L5 | 54.00 | 54.00 | 3 | - |
| 116_NS | L4 | 60.00 | 60.00 | 4 | - |
| 117_NS | L5 | 44.00 | 44.00 | 3 | - |
| 118_NS | L5 | 44.00 | 44.00 | 3 | - |
| 119_NS | L5 | 46.00 | 46.00 | 3 | - |

## 剩余失败原因

- 49_NS: {'z1_route_conflict': 40, 'not_diagnosed': 733} (来源 {'mixed': 40})

## 交叉伙伴数变化最大的路线

delta = base - new（负 = 新世界交叉伙伴变多，正 = 减少）。

| route | category | base partners | new partners | delta |
|---|---|---|---|---|
| 60 | opposite_z1_NS | 22 | 38 | -16 |
| 292 | opposite_z1_NS | 22 | 38 | -16 |
| 70 | opposite_z1_EW | 0 | 14 | -14 |
| 283 | opposite_z1_EW | 0 | 14 | -14 |
| 56 | opposite_z1_NS | 0 | 10 | -10 |
| 284 | opposite_z1_NS | 0 | 10 | -10 |
| 57 | opposite_z1_NS | 0 | 10 | -10 |
| 286 | opposite_z1_NS | 0 | 10 | -10 |

交叉伙伴减少最多的路线:

| route | category | base partners | new partners | delta |
|---|---|---|---|---|
| 297 | opposite_z1_EW | 36 | 4 | 32 |
| 79 | opposite_z1_EW | 36 | 4 | 32 |
| 301 | opposite_z1_EW | 36 | 4 | 32 |
| 80 | opposite_z1_EW | 36 | 4 | 32 |
| 303 | opposite_z1_EW | 36 | 4 | 32 |

## 说明

- 世界 = baseline 去掉被移除的 Z2 类别；评测 pair 时把该 pair 旧平坦路线从世界中移除（替换语义）。
- 抬升顺序 = 已发布 pair 顺序，贪心接受后立即提交；后续 pair 的合法性检查包含前面已抬升的路线。
- 抬升窗口 = `search.window_grid` 顺序中的第一个合法窗口（按基段长度最短排序，即最近端口窗口），不是按新产生交叉数优化的窗口；高层的残余交叉数因此只反映该选取策略。
- 独立窗口模式为快速检查（每个成员最多 200 个候选、取首个合法窗口，再做两成员 pairwise 检查），不是独立的穷举搜索。
- 本目录为诊断输出，routes_1024.json 未通过 1024 通道校验 (validation.json status=not_validated)。
