# 00_input_audit：新人工连接 CSV（section-2）输入审计

**总体判定：全部通过** （5 个阶段共 98 项检查）。本目录只依赖真实 CSV 与冻结端口模型 `four_side_1024.fslw.ports.build_plane_endpoints()`，所有数字由脚本计算，未人工填写。

## 0. 结论速览

- **Z1（512 行）**：完整、正确。512 条连接、1024 个 z1 端点各用一次、坐标与端口模型最大误差 0.0 mm、C4 严格闭环（128 个四元组）；relation = opposite 256 / same 256。
- **Z2（128 行基础表）**：作为"128 条四元基础连接"完整、自洽；C4 展开后恰好 512 条、1024 个 z2 端点各用一次、闭环 0 缺失；relation = adjacent 400 / same 112。**注意**其 layer/row/channel 标签是遗留的 z1/row-1 写法，必须按文档 remap 到 z2 的 row-2 端口后使用。
- **合并 1024 表**：1024 条连接、2048 个端点各用一次、64 连接器 × 32 孔位全覆盖、256 个 C4 四元组；relation = opposite 256 / adjacent 400 / same 368。
- **老师双端口组要求**：任务书预检的 8×(32 跨边/32 U) + 24×(44 跨边/20 U) 被新 CSV 在"规则 A（同边相邻连接器两两配对）"下**逐组精确复现**（跨边端点 1312、U 端点 736）；老师名义的"每组 48 跨边 + 16 U"**未被满足，且数学上不可能满足**（2048 端点总量与 32×48/32×16 不匹配）。
- **旧 vs 新**：新 CSV 是**整体重构**而非修订——Z1 仅 52/512、Z2 仅 24/512 连接与 10-22 旧表重合；合并表重合 76/1024。旧 campaign 的布线结果不可复用。

## 1. 输入与范围

| 输入 | 行数 | sha256 |
|---|---|---|
| `manual_z1_router/data/exports/manual_z1_c4_full_section2.csv` | 512 | 9d5e0b5e15c4b2774130403c94cc56f91b79584496676cbffb7ee81acf54cfbd |
| `manual_z1_router/data/exports/manual_z2_c4_full_section2.csv` | 128 | aae16265a26829443371dc716001476bb25ab8fd73571bb1f245e218970b3c8a |
| 旧 10-22 `manual_z1_c4_full.csv` | 512 | 74e43d068d5844719ae0f0d5c13ee76fb2523a6846cebbf4e4489f80e8d82ffc |
| 旧 10-22 `manual_z2_c4_full.csv` | 512 | 43d58fd10df16065c0a271ca17b2c31602bbf915f8ac731fd209786b28462f63 |

只读输入，未修改、未覆盖。验证：z1_new=OK，z2_new=OK，z1_old=OK，z2_old=OK，z1_old_campaign=OK，z2_old_campaign=OK，old_combined=OK

冻结端口模型：64 连接器 × (2 行 × 16 列) = 2048 个物理孔；z1 = row 1（z = 0.0 mm）、z2 = row 2（z = 0.5 mm）；连接器节距 9.0 mm、列节距 0.25 mm、行节距 0.5 mm。

## 2. 产物清单

| 文件 | 字节 | sha256 |
|---|---|---|
| csv_integrity.json | 50402 | 8cfb96a2325e84c390de289645a9000a91f1cdb2227f3508cc44a66f15ebf0c3 |
| z2_expanded_512.csv | 43336 | 90a06c31fd1c300d58c4d12e997059e30cfef090edcae5ce8deefb424d8b9c08 |
| z2_c4_expansion.json | 78473 | 34fc30ada4bc329d96e8a4172dac07b1ffb9386cfa07181691d043fbe1c018a3 |
| connectivity_1024_proposed.csv | 39885 | b66b72c7f47d710c83bd752c896f429f6e128b295f888ceb67f1009091517f26 |
| connectivity_1024_proposed_annotated.csv | 91564 | 5b80d99ea22c2a0c8cd1c0960fd15ead49fff4883d7a6148547cc783aa496bec |
| combined_1024_audit.json | 94534 | cf0d937166e6df7df425161813bfa8196e3ecd1443005a4a0f041ca96895555c |
| teacher_coverage.json | 179447 | ebbe32c534b67a37c5d445629f3b5558116c8b230770a9f86c70c00c91896353 |
| teacher_coverage.md | 10037 | b83a6b8775858e75ee3c639185709c621d03fea651bc2541e1f9b56ac1834d30 |
| old_new_diff.json | 18519 | 64dff1532de9dddba9b475891c36d1c9b66c43d39cb980f0ef01f9844e2660c7 |
| old_new_diff.md | 5919 | cc5d2ea434e813f657108faba49c0a0810218b647314e244f336f4aa8681a6df |
| figures/teacher_coverage_groups.png | 88665 | f208599aac3044f8e5bd04cba647ef14e29930802d6cf38b0c3a9f23d37552a9 |
| figures/connector_pairing_map.png | 156260 | ed91f081ee7723a980d1fd774cb843597727451016e110b1192a65189448fda6 |

## 3. 各阶段结果

### 3.1 CSV 完整性（`csv_integrity.json`）

| 检查对象 | 行数 | relation 统计 | 端点 | xy 最大误差(mm) | 检查结果 |
|---|---|---|---|---|---|
| Z1 section-2 | 512 | {'opposite': 256, 'same': 256} | 1024 唯一 | 0.0 | 38 项检查中 0 错误 |
| Z2 section-2（base） | 128 | {'adjacent': 100, 'same': 28} | 256 唯一（1/4 子集） | 0.0 | 2 条 legacy 标签警告（非错误） |

Z1 额外核验：header 19 列、UTF-8 BOM、CRLF、route_id 1..512、channel=column、layer=z1、全部端点属于 z1 平面、relation 与两侧一致、无重复连接、C4 闭环（{'90deg': 0, '180deg': 0, '270deg': 0}）、轨道直方图 {'4': 128}。

### 3.2 Z2 C4 展开（`z2_c4_expansion.json` + `z2_expanded_512.csv`）

| 指标 | 结果 |
|---|---|
| 基础连接数 → 展开连接数 | 128 → 512 |
| 每条基础连接的四元组数 | {'4': 128} |
| 展开端点 | 1024（全部 z2 row-2 端口，各用一次） |
| relation | {'adjacent': 400, 'same': 112} |
| C4 闭环（90/180/270） | {'90deg': 0, '180deg': 0, '270deg': 0} |
| 与独立 campaign 构建的展开表连接集合一致 | True |
| row1→row2 remap 与旋转可交换 | 是 |

说明：Z2 的 128 行 CSV 使用遗留 row-1 端口 id（layer=z1、row=1、channel=1..16），脚本先按"同连接器同列、row 1→row 2"映射到物理 z2 端口，再做真实 C4 旋转；映射与旋转可交换，两种顺序结果一致。

### 3.3 合并 1024（`combined_1024_audit.json` + `connectivity_1024_proposed.csv`）

| 指标 | 结果 |
|---|---|
| 连接 / 端点 | 1024 / 2048 |
| 端点是否各用一次 | True |
| 连接器 × 孔位 | 64 × 32（全部覆盖） |
| 按平面 relation | {'z1': {'opposite': 256, 'same': 256}, 'z2': {'adjacent': 400, 'same': 112}} |
| relation 合计 | {'adjacent': 400, 'opposite': 256, 'same': 368} |
| 跨边 / U 端点 | 1312 / 736 |
| C4 组 | 256（{'z1': 128, 'z2': 128}），类型 {'adjacent': 100, 'opposite': 64, 'same': 92} |
| 闭环 | {'90deg': 0, '180deg': 0, '270deg': 0} |
| 与 campaign builder 的 connectivity_1024 连接集合一致 | True |
| route_id 编号 | expanded z2 route_id 1..512 (base route_id ascending, C4 phase 0/90/180/270) + 512 -> 513..1024 |

主文件 `connectivity_1024_proposed.csv` 使用与工程 V3/V4 拓扑表相同的 12 列 schema；另附 `connectivity_1024_proposed_annotated.csv`（19 列原 schema + plane + pair，共 21 列）。

### 3.4 老师要求 vs 实际拓扑（`teacher_coverage.json` / `teacher_coverage.md`）

| 项目 | 数值 |
|---|---|
| 老师名义目标（每组） | 48 跨边孔 + 16 同侧 U 孔（32 组） |
| 名义目标总量 / 实际总量 | 1536/512 端点 → 实际 1312/736 |
| 任务书预检 | 8 组 × (32 跨边 + 32 U) + 24 组 × (44 跨边 + 20 U) |
| 推荐配对规则 A | 同边相邻连接器两两配对：每条边 (01,02),(03,04),...,(15,16) |
| 规则 A 结果 | 角部组 8 组 (32/32)，其他组 24 组 (44/20)，逐组复现预检：True |
| 每角部组数 | {'NW': 2, 'NE': 2, 'SW': 2, 'SE': 2} |
| 规则 A 配对总距离 | 288.0 mm （= 32×9 mm 理论下界，唯一最小距离匹配） |
| 与 48/16 的偏差（总体） | 跨边 -224 端点、U +224 端点 |

推导要点：每个连接器 32 孔全部使用；16 个端部连接器（每边 01/02/15/16）跨边端点恰为 16，48 个中部连接器（03..14）恰为 22；因此 2 连接器组的跨边孔只可能为 32/38/44。预检要求 8 组 32 + 24 组 44 ⇒ 任何组都不得跨类配对 ⇒ 必然"端部-端部、中部-中部"。在该约束下规则 A（同边相邻两两配对）唯一地使配对总距离最小（288 mm），并逐组复现预检。**仅凭计数无法唯一确定绝对配对**：规则 E（每角 2 组跨边配对）同样复现计数且同样位于角部，但配对距离更大（351.76 mm）；规则 D（同边镜像）计数也吻合但 8 个 32/32 组横跨整条边，与"角部"定位矛盾；规则 B 产生 38 端点的组，不能复现预检。

### 3.5 旧 vs 新（`old_new_diff.json` / `old_new_diff.md`）

| 指标 | Z1 | Z2 | 合并 1024 |
|---|---|---|---|
| 旧表 relation | {'adjacent': 184, 'opposite': 264, 'same': 64} | {'adjacent': 312, 'opposite': 8, 'same': 192} | {'adjacent': 496, 'opposite': 272, 'same': 256} |
| 新表 relation | {'opposite': 256, 'same': 256} | {'adjacent': 400, 'same': 112} | {'adjacent': 400, 'opposite': 256, 'same': 368} |
| 连接集合重合 / 512（或 /1024） | 52 | 24 | 76 |
| Jaccard | 0.053498 | 0.024 | 0.03854 |
| 相同 route_id 且相同连接（/512 或 /1024） | 0 | 0 | 0 |

旧 campaign 的输入本身已核验：其 `manual_z1_c4_full.csv` 与 10-22 导出一致，其 `manual_z2_c4_full.csv` 是 10-22 z2 导出的 row1→row2 remap 版本；旧合并表 = 旧 z1 + 旧 z2 remap。新旧表关系构成不同（旧合并表 opposite 272 / adjacent 496 / same 256；新表 opposite 256 / adjacent 400 / same 368），新表 U 端点由 512 增至 736。

## 4. "新人工连接 CSV 是否完整正确"的明确结论

**Z1 `manual_z1_c4_full_section2.csv`：完整且正确。**512 行、19 列 schema、BOM+CRLF、route_id 1..512、layer=z1、row=1、channel=column，1024 个端点 = z1 平面全部 1024 孔且各用一次，坐标与冻结模型误差 0 mm，relation 与两侧一致，无重复连接，C4 严格闭环（{'4': 128}）。可直接作为 z1 平面输入。

**Z2 `manual_z2_c4_full_section2.csv`：作为"128 条 C4 基础连接"完整且自洽，但不是可直接使用的物理 z2 表。**它能且仅能展开为 512 条 z2 连接：每条基础连接产生 4 条互异旋转副本、128 个轨道互不相交、展开后 1024 个 z2 端点各用一次、C4 闭环 0 缺失、relation = adjacent 400 / same 112 与预期一致。**不一致之处（属于标签/格式层面，已量化）**：（a）文件里 layer=z1、row=1、channel=1..16、端口 id 是 row-1 身份，与"z2 平面"的物理定义不符——必须先做 row1→row2 remap（脚本已验证该 remap 与旋转可交换，两种顺序结果相同）；（b）route_id 不连续且不是 1..128（实际取值 34..270 共 128 个），说明它是更大设计文件中的 128 条轨道代表，不是独立完整文件；（c）若把该 CSV 当作 512 行 z2 表直接使用会失败（行数、layer、row 都不符）。

**合并 1024 表：完整且正确。**Z1 512 + Z2 展开 512 = 1024 条，2048 个端点各用一次、64 连接器各 32 孔全部覆盖、256 个严格 C4 四元组（每平面 128）、relation 合计 {'adjacent': 400, 'opposite': 256, 'same': 368}。与本 campaign 独立构建的 `inputs/connectivity_1024.csv` 连接集合逐条一致（仅 z2 的 route_id 顺序由各自展开排序决定，可在合并阶段统一）。

**仍需注意的不一致/风险（如实列出）**：

1. **Z2 遗留标签**：layer=z1/row=1/channel=1..16 与物理 z2 平面不符，使用方必须按 row1→row2 remap；若误解为 z1 输入会与 Z1 端点冲突（256 个原始 id 与 Z1 身份空间重合）。
2. **老师名义 48/16 未满足且不可满足**：新 CSV 的实际配比是任务书预检的 8×32/32 + 24×44/20；若老师要求"每组 48 跨边 + 16 U"作为硬指标，则任何 32 组划分都无法由当前 1312 跨边 / 736 U 端点实现。
3. **双端口组配对无法由 CSV 唯一确定**：CSV 没有编码分组；预检计数只强制"端部-端部、中部-中部"，具体配对需按几何选择。推荐规则 A（同边相邻）与"每角 2 组、最小配对距离"一致；规则 E 是另一种满足计数的角部跨边方案。
4. **route_id 仅临时**：`z2_expanded_512.csv` 的 1..512 与 `connectivity_1024_proposed.csv` 中 z2 的 513..1024 是本次审计的确定性临时编号（基础 route_id 升序 + C4 相位 0/90/180/270），与 campaign builder 的展开排序可能不同（连接集合一致）。
5. **新旧表几乎无重合**：旧 campaign 的结果、图、编号均不可直接复用，需用新 1024 表重跑。

## 5. 复现

从项目根目录运行（Windows PowerShell）：

```powershell
.\.venv\Scripts\python.exe "outputs\manual_c4_new_connectivity\NEW_MANUAL_CSV_1024_FULL_CAMPAIGN\00_input_audit\scripts\run_all.py"
```

`scripts/` 内容：`common.py`（共享端口模型/旋转/CSV 工具）、`s1_csv_integrity.py`、`s2_z2_expansion.py`、`s3_combined.py`、`s4_teacher_coverage.py`、`s5_old_new_diff.py`、`s6_readme.py`、`run_all.py`。

## 6. 环境

- Python 3.10.11（`.venv`）；matplotlib 3.10.9，Agg 后端，PNG dpi=170。
- 端口模型只读：`four_side_1024.fslw.ports.build_plane_endpoints()`。
- 所有输入 CSV 以只读方式打开；本审计未修改任何原始 CSV、未覆盖任何旧实验目录。

## 7. 目录内容

```
00_input_audit/
├─ README.md                          # 本文件
├─ csv_integrity.json                 # 阶段 1
├─ z2_expanded_512.csv                # 阶段 2 展开表（19 列，物理 z2 row-2）
├─ z2_c4_expansion.json               # 阶段 2
├─ connectivity_1024_proposed.csv     # 阶段 3 合并表（12 列 V3/V4 schema）
├─ connectivity_1024_proposed_annotated.csv  # 阶段 3（21 列）
├─ combined_1024_audit.json           # 阶段 3
├─ teacher_coverage.json / .md        # 阶段 4
├─ old_new_diff.json / .md            # 阶段 5
├─ figures/
│  ├─ teacher_coverage_groups.png     # 32 组柱状图（dpi=170）
│  └─ connector_pairing_map.png       # 连接器配对图（真实坐标，dpi=170）
└─ scripts/                           # 全部可复现脚本
```
