# D0 阻断分析 → Lead 摘要

候选：feasible net≥3 共 5851 个，几何去重后 **5387** 个（350 条路由）+ route 129 全部候选；生产 guard 拒绝 5386、world-clean 1、仅 sampling near-miss 397。

## 四个问题的答案

(i) 被拒候选按**可移动阻断路由数**：guard 口径 1/2/3/4–8/>8 = 111/639/914/2798/924（0 个 = 0）；精确物理硬口径（3D<0.05）= 882/1007/822/1776/215；含冻结 manual(U) 硬阻断 = **1969**（37%）。
(ii) 只需 1–3 条可移动路由 joint rerouting 的比例：**18.4%**（989/5386，guard 口径、无 manual）；硬口径 37.8%（1886/4989）。其中 **293** 个其实没有硬阻断（只差 guard 0.011mm 采样余量）。
(iii) 最高收益 1–3 可移动阻断候选：**route 16 → Z1_INTERFACE**，net=14，guard 阻断 [143, 412, 457]（硬阻断 无；全部 near-miss）。按硬阻断口径最高收益是 route 129 → L8（net=16，仅 1 硬阻断 r120）。
(iv) route 129（net=16）：**7 个目标高度生产 guard 全拒**，直接采纳不可行；物理硬阻断 L4=0（仅 near-miss，精确 0.05mm 已合法）、L8=1（r120）、其余 2–5 条；**r120 挡 6/7 个高度**（L7 flat 在 excursion 起点正上方约 31µm）。

## 机制与建议
- 主因 **transition_vs_flat（>99%）**：一次远距离换层的 S 曲线必须穿过所有中间高度，其它路由在这些高度的 flat 就是硬阻断 → 单次 far S-curve 几乎不可用（支持 staircase/task-9 方向）。
- 目标层 strict-D56（flat_same_plane_conflict）是第二类阻断，数量少。
- 建议：优先 staircase/相邻层多步换层；对 1–3 可移动阻断候选做 joint reroute；对 near-miss-only 加"精确 S 曲线细化"复核（可释放 293 个 1–3 可移动候选 + 397 个 near-miss-only 候选）。

## 产物
- `analysis/blocker_analysis.json`（28.5MB，逐候选）/ `analysis/blocker_analysis_report.md` / `analysis/plots/*.png`
- 模块 `four_side_1024/fanout1024/native3d/blocker_analysis.py`；入口 `scratch/blocker_analyst/scripts/run_blocker_analysis.py`；runtime 145s，两次运行 JSON/PNG 哈希一致（确定性）。

口径：candidate world = 冻结 E5（`crossing_intervals.json` 的 `baseline_dir`）；实验 C 已转 Native 的 55 条路由的 1073 个候选只做 E5 分析。对已接受布局敏感性：4314 个可复核候选中 53.5% 阻断集合不变，Native 世界硬 clean 169 个（E5 295 个）。
