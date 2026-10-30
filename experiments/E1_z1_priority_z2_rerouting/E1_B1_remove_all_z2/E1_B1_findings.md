# E1_B1 诊断结果 (DIAGNOSTIC ONLY)

==============================================================================
DIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION
This directory is a Z2-removal diagnostic, not a router solution.
The payload in routes_1024.json intentionally misses Z2 routes and
is saved as "not_validated". Do NOT use it as a deliverable.
==============================================================================

- 保留路线: 512/1024; 移除 Z2 路线 512 条 (这不是合法的 1024 通道方案)
- 29 个 C2 pair-direction 中贪心抬升成功: **29/29** (58 条 Z1 路线); 失败: 0
- 独立窗口模式(pair 两成员各自窗口)合法: **29/29**

## 关键数字 (诊断世界 vs 同保留集合未抬升基线)

| metric | base (same kept set, unlifted) | E1_B1 | delta |
|---|---|---|---|
| unique crossing pairs | 5326 | 6518 | 1192 |
| Z1 (z=0) crossing pairs | 5256 | 4464 | -792 |
| high-layer crossing pairs | 70 | 2054 | 1984 |
| Z1-only subset: Z1 pairs | 5256 | 4464 | -792 |
| Z1-only subset: high pairs | 70 | 2054 | 1984 |
| transitions | 540 | 656 | 116 |
| total length mm | 55258.5691 | 55263.8182 | 5.2491 |

## 抬升窗口 (pair-together, 最近端口合法窗口)

| pair | layer | a_in | a_out | 合法层数 | 候选数 |
|---|---|---|---|---|---|
| 1_EW | L2 | 1.20 | 1.20 | 6 | - |
| 1_NS | L2 | 5.00 | 5.00 | 6 | - |
| 36_EW | L2 | 1.20 | 1.20 | 6 | - |
| 36_NS | L2 | 5.00 | 5.00 | 6 | - |
| 40_EW | L2 | 1.20 | 1.20 | 6 | - |
| 40_NS | L2 | 5.00 | 5.00 | 6 | - |
| 41_EW | L2 | 1.20 | 1.20 | 6 | - |
| 41_NS | L2 | 5.00 | 5.00 | 6 | - |
| 42_EW | L2 | 1.20 | 1.20 | 6 | - |
| 42_NS | L2 | 5.00 | 5.00 | 6 | - |
| 43_EW | L2 | 1.20 | 1.20 | 6 | - |
| 43_NS | L2 | 5.00 | 5.00 | 6 | - |
| 44_EW | L2 | 1.20 | 1.20 | 6 | - |
| 44_NS | L2 | 5.00 | 5.00 | 6 | - |
| 46_EW | L2 | 1.20 | 1.20 | 6 | - |
| 46_NS | L2 | 5.00 | 5.00 | 6 | - |
| 47_EW | L2 | 1.20 | 1.20 | 6 | - |
| 47_NS | L2 | 5.00 | 5.00 | 6 | - |
| 48_EW | L2 | 1.20 | 1.20 | 6 | - |
| 48_NS | L2 | 5.00 | 5.00 | 6 | - |
| 49_EW | L2 | 1.20 | 1.20 | 6 | - |
| 49_NS | L2 | 5.00 | 5.00 | 6 | - |
| 113_NS | L2 | 13.00 | 85.79 | 6 | - |
| 114_NS | L2 | 13.00 | 85.79 | 6 | - |
| 115_NS | L2 | 13.00 | 85.79 | 6 | - |
| 116_NS | L2 | 13.00 | 85.79 | 6 | - |
| 117_NS | L2 | 6.00 | 85.79 | 6 | - |
| 118_NS | L2 | 6.00 | 85.79 | 6 | - |
| 119_NS | L2 | 6.00 | 85.79 | 6 | - |

## 剩余失败原因

- 无: 在去掉相应 Z2 路线后，29/29 pair 均可在当前世界中抬升。

## 交叉伙伴数变化最大的路线

delta = base - new（负 = 新世界交叉伙伴变多，正 = 减少）。

| route | category | base partners | new partners | delta |
|---|---|---|---|---|
| 1 | opposite_z1_NS | 22 | 80 | -58 |
| 212 | opposite_z1_NS | 22 | 80 | -58 |
| 55 | opposite_z1_NS | 22 | 80 | -58 |
| 282 | opposite_z1_NS | 22 | 80 | -58 |
| 59 | opposite_z1_NS | 22 | 80 | -58 |
| 290 | opposite_z1_NS | 22 | 80 | -58 |
| 60 | opposite_z1_NS | 22 | 80 | -58 |
| 292 | opposite_z1_NS | 22 | 80 | -58 |

交叉伙伴减少最多的路线:

| route | category | base partners | new partners | delta |
|---|---|---|---|---|
| 303 | opposite_z1_EW | 36 | 22 | 14 |
| 81 | opposite_z1_EW | 36 | 22 | 14 |
| 305 | opposite_z1_EW | 36 | 22 | 14 |
| 82 | opposite_z1_EW | 36 | 22 | 14 |
| 307 | opposite_z1_EW | 36 | 22 | 14 |

## 说明

- 世界 = baseline 去掉被移除的 Z2 类别；评测 pair 时把该 pair 旧平坦路线从世界中移除（替换语义）。
- 抬升顺序 = 已发布 pair 顺序，贪心接受后立即提交；后续 pair 的合法性检查包含前面已抬升的路线。
- 抬升窗口 = `search.window_grid` 顺序中的第一个合法窗口（按基段长度最短排序，即最近端口窗口），不是按新产生交叉数优化的窗口；高层的残余交叉数因此只反映该选取策略。
- 独立窗口模式为快速检查（每个成员最多 200 个候选、取首个合法窗口，再做两成员 pairwise 检查），不是独立的穷举搜索。
- 本目录为诊断输出，routes_1024.json 未通过 1024 通道校验 (validation.json status=not_validated)。
