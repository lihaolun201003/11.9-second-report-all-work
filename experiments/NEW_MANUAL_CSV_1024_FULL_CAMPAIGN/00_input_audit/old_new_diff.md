# 旧人工 CSV（10-22）vs 新 section-2 人工 CSV 差异审计

所有数字由 `scripts/s5_old_new_diff.py` 从真实文件计算。Z2 的旧表与新表都使用 legacy row-1 端口标签（或 remap 后的 row-2 标签），因此 Z2 比较统一使用 (connector, column) 行不变身份；Z1 两表都在 row-1 身份空间直接比较。

## 1. 文件清单与 campaign 等价性

| 文件 | 行数 | sha256(前16) | 字节 |
|---|---|---|---|
| z1_old_export | 512 | 74e43d068d584471… | 42952 |
| z2_old_export | 512 | 43d58fd10df16065… | 42440 |
| z1_old_campaign | 512 | 74e43d068d584471… | 42952 |
| z2_old_campaign | 512 | 5e74b26704573680… | 43016 |
| z1_new | 512 | 9d5e0b5e15c4b277… | 42184 |
| z2_new_base | 128 | aae16265a2682944… | 10836 |
| z2_new_expanded | 512 | 90a06c31fd1c300d… | 43336 |
| combined_old | 1024 | 4c425adde0795a96… | 40330 |
| combined_new | 1024 | b66b72c7f47d710c… | 39885 |

- 旧 campaign 输入 `manual_z1_c4_full.csv` 与 10-22 导出**逐字节相同**：True
- 旧 campaign 输入 `manual_z2_c4_full.csv` 是 10-22 z2 导出按 row1→row2 remap 后的版本，连接集合完全一致：True（512 行，layer={'z2': 512}）
- 旧 campaign 合并表 `connectivity_1024.csv` = 旧 z1（1..512）+ 旧 z2 remap（513..1024），已逐条核验一致。

## 2. 顶层连接类别变化

| 平面 | opposite | adjacent | same |
|---|---|---|---|
| Z1 | opposite 264 → 256 | adjacent 184 → 0 | same 64 → 256 |
| Z2 | opposite 8 → 0 | adjacent 312 → 400 | same 192 → 112 |
| 合并 | opposite 272 → 256 | adjacent 496 → 400 | same 256 → 368 |

合并层面：旧表跨边端点 1536 / U 端点 512；新表跨边端点 1312 / U 端点 736。新表把大量跨边连接改成同侧 U 连接（U 端点 +224，跨边端点 -224），与老师"更多同侧 U"的方向一致。

## 3. Z1 差异（旧 512 行 vs 新 512 行）

| 指标 | 数值 |
|---|---|
| 连接集合重合 | 52 / 512 |
| 新表连接被旧表覆盖比例 | 10.16% |
| Jaccard | 0.0535 |
| 相同 route_id 且相同连接 | 0 / 512 |
| 关系标签（同 route_id 位置）转移矩阵 | {'adjacent->opposite': 75, 'adjacent->same': 109, 'opposite->opposite': 163, 'opposite->same': 101, 'same->opposite': 18, 'same->same': 46} |
| 重合连接的 route_id 重排：相同/移动 | 0 / 52 |
| 重排平均绝对 Δroute_id / 最大绝对 Δroute_id | 85.884615 / 435 |
| 重合连接 route_id Spearman 相关 | 0.725775 |
| 重合连接的关系构成 | {'opposite': 20, 'same': 32} |
| C4 轨道（旧） | {'4': 128}，关系 {'adjacent': 46, 'opposite': 66, 'same': 16} |
| C4 轨道（新） | {'4': 128}，关系 {'opposite': 64, 'same': 64} |

Z1 结论：旧表在同一平面内混合了 opposite（264）、adjacent（184）、same（64）；新表只保留 opposite（256）与 same（256），adjacent 全部移出 z1 平面。两表重合的 52 条连接中 {'opposite': 20, 'same': 32}；其余连接全部重构，且 route_id 整体重排（同 route_id 且同连接 0/512）。

## 4. Z2 差异（旧 512 行 vs 新展开 512 行）

| 指标 | 数值 |
|---|---|
| 旧表关系 | {'adjacent': 312, 'opposite': 8, 'same': 192} |
| 新展开表关系 | {'adjacent': 400, 'same': 112} |
| 新表基础行（128 条四元基础连接）关系 | {'adjacent': 100, 'same': 28} |
| 连接集合重合 | 24 / 512 |
| 新表连接被旧表覆盖比例 | 4.69% |
| Jaccard | 0.0240 |
| 相同 route_id 且相同连接 | 0 / 512 |
| 重合连接的关系构成 | {'adjacent': 16, 'same': 8} |
| 重合连接的 route_id 重排：相同/移动 | 0 / 24 |
| C4 轨道（旧） | {'4': 128}，关系 {'adjacent': 78, 'opposite': 2, 'same': 48} |
| C4 轨道（新） | {'4': 128}，关系 {'adjacent': 100, 'same': 28} |

Z2 结论：旧表含 opposite 8 / adjacent 312 / same 192，新展开表为 adjacent 400 / same 112（对应 128 条基础连接 adjacent 100 / same 28）。两表重合 24 条连接（{'adjacent': 16, 'same': 8}）；旧表的 8 条 opposite 在新表中完全不存在，新表的 112 条 same 中只有 8 条来自旧表。注意新 z2 的 512 行是 128 条基础连接 C4 展开的结果，其 route_id 1..512 是展开顺序的临时编号，与旧表 route_id 无对应关系。

## 5. 合并 1024 表差异

| 指标 | 旧 campaign 1024 | 新提案 1024 |
|---|---|---|
| 关系总数 | {'adjacent': 496, 'opposite': 272, 'same': 256} | {'adjacent': 400, 'opposite': 256, 'same': 368} |
| 跨边端点 / U 端点 | 1536 / 512 | 1312 / 736 |
| 按平面关系 | {'z1': {'adjacent': 184, 'opposite': 264, 'same': 64}, 'z2': {'adjacent': 312, 'opposite': 8, 'same': 192}} | {'z1': {'opposite': 256, 'same': 256}, 'z2': {'adjacent': 400, 'same': 112}} |
| 连接集合重合 | — | 76 / 1024 |
| 重合比例（占新表） | — | 7.42% |
| Jaccard | — | 0.0385 |
| 相同 route_id 且相同连接 | — | 0 / 1024 |
| C4 轨道关系构成（旧 256 组） | {'adjacent': 124, 'opposite': 68, 'same': 64} | — |
| C4 轨道关系构成（新 256 组） | — | {'adjacent': 100, 'opposite': 64, 'same': 92} |

## 6. 结论

1. **新 CSV 不是旧 CSV 的修订，而是整体重构**：Z1 仅 52/512、Z2 仅 24/512 连接与旧表重合；route_id 完全重排（同 id 同连接几乎为 0）。
2. **关系构成整体改变**：旧表 z1 含 adjacent，新表把 adjacent 全部放到 z2；新表 U 连接显著增多（合并 U 端点 512 → 736）。
3. **C4 结构**：新旧表在各自平面内都严格 C4 闭环、都是 128 组/平面；但每组的关系构成不同（旧 z1: opposite 66 + adjacent 46 + same 16；新 z1: opposite 64 + same 64；旧 z2: adjacent 78 + same 48 + opposite 2；新 z2: adjacent 100 + same 28）。
4. **旧 campaign 的结果不可复用**：连接集合与编号均不同，必须用新表重跑。
