# 11.9号第二次汇报的所有工作

本仓库汇总 **2026-11-09 第二次汇报**前后的全部调研工作，包含两套并行完成的调研成果（`deepseek/` 与 `chatgpt/`）、文献库、证据台账、答辩问题库与开题/汇报材料。

> 性质说明：本仓库为本科生毕业设计《1024 通道三维光波导自动布线系统》的调研与写作资料，**不是同行评议出版物**；文中的数据与结论均标注了来源与证据等级，未列来源者不得引用为事实。

---

## 一、目录结构

```
.
├── deepseek/                        # 本次调研（DeepSeek Agent 完成）
│   ├── docs/research/               # ★ 12 个交付文件（详见下表）
│   └── .work/                       # 支撑材料：检索脚本、候选文献池、证据缓存、
│                                    #   核验审计报告、文献 JSON（不含第三方论文原文）
└── chatgpt/                         # 另一套同题调研（ChatGPT 完成，可交叉对照）
    └── docs/research/               # 同类交付文件、图表、脚本、文献目录与检索记录
```

---

## 二、deepseek 交付文件（推荐先读）

| 文件 | 内容 |
|---|---|
| [01_光交换与光纤重排调研.md](deepseek/docs/research/01_光交换与光纤重排调研.md) | OCS 原理/实现技术/网络拓扑、Google Jupiter–Apollo 案例、Fiber Shuffle、玻璃波导对比、应用实例 |
| [02_高带宽内存与处理器互联调研.md](deepseek/docs/research/02_高带宽内存与处理器互联调研.md) | HBM 结构/代际、1024 位接口辨析、GPU/CPU 分层互联、光 I/O/CPO、内存池化正反证据 |
| [03_产业技术与光电子设计自动化.md](deepseek/docs/research/03_产业技术与光电子设计自动化.md) | Corning/Intel、七条技术路线对照、飞秒激光直写工艺、光子 EDA 能力与空白 |
| [04_相关工作对照与创新空间.md](deepseek/docs/research/04_相关工作对照与创新空间.md) | 25 篇直接相关工作对照表、逐篇十问、10 个假设检验、贡献评估与"不可主张"清单 |
| [05_研究意义论证.md](deepseek/docs/research/05_研究意义论证.md) | 研究意义完整论证链：应用需求 → 物理端口 → 连接规模 → 路由复杂度 → 技术选择 → 创新边界 |
| [06_毕业论文第1章绪论初稿.md](deepseek/docs/research/06_毕业论文第1章绪论初稿.md) | 毕业论文第 1 章《绪论》初稿 |
| [07_毕业论文第2章相关理论与关键技术.md](deepseek/docs/research/07_毕业论文第2章相关理论与关键技术.md) | 第 2 章详细提纲 + 段落初稿（34 个编号公式、P-01–P-13 待标定参数表） |
| [08_答辩问题库.md](deepseek/docs/research/08_答辩问题库.md) | 38 个答辩问题，每题含 30 秒回答 / 2 分钟解释 / 证据 / 易错点 / 未验证边界 |
| [09_开题与阶段汇报幻灯片方案.md](deepseek/docs/research/09_开题与阶段汇报幻灯片方案.md) | 23 页正文 + 8 页备用 PPT 方案、24 项图表、逐字稿 |
| [10_参考文献.bib](deepseek/docs/research/10_参考文献.bib) | 223 条文献（169 条 Crossref 元数据生成，54 条官方来源；DOI 已核验） |
| [11_证据台账.md](deepseek/docs/research/11_证据台账.md) | 核心事实台账：可信度分级、反例、推算假设、终检记录 |
| [12_待解决问题清单.md](deepseek/docs/research/12_待解决问题清单.md) | 27 个待解决问题（补文献 / 问导师 / 做实验）与优先级 |

> `chatgpt/docs/research/` 下有另一套同题材料（含 `完整调研报告.html`、`可筛选文献目录.html`、图表与脚本），可与 deepseek 版本交叉比对。

---

## 三、研究方法与质量说明

1. **文献核验**：所有 DOI 均通过 Crossref API（`api.crossref.org/works/<doi>`）逐条核对标题/作者/年份/卷期页；无法获取全文的条目一律标注"仅摘要 / 仅题录"。
2. **证据分级**：A=全文/标准原文/官方规格；B=官方页面要点或论文摘要；C=本文推算或估算（写明假设）；D=仅题录、不得引用数值。
3. **关键修正**（已闭环）：HBM 带宽换算的 TB/s 与 Tb/s 混用；自动布线规模事实；失效 DOI；证据边界越界表述。
4. **诚实性约定**：未完成实验写"尚未验证"；"未检索到"不写成"不存在"；不把计划写成已完成；不以通道数本身作为创新点。

---

## 四、未上传文件说明

出于体积与版权考虑，以下文件未纳入本公开仓库（均为**可再生成的中间产物或第三方版权材料**，非调研成果）：

- `chatgpt/docs/research/.venv/`：Python 工具环境；
- `deepseek/.work/{cache,pages,rw_pages}/`：检索缓存与抓取页面；
- 两套目录下的第三方论文 PDF / 提取全文（`.pdf`、`.txt`）；
- `chatgpt/docs/research/sources/raw/` 与 sources 内的 PDF/TXT/HTML 原文。

如需完整原始资料，请在本地对应目录查看。

---

## 五、主要参考文献（节选）

- Poutievski et al., *Jupiter Evolving*, ACM SIGCOMM 2022, DOI: 10.1145/3544216.3544265
- Brusberg et al., *Optical Design and Applications for Ion-Exchanged Glass Waveguide Circuits*, IEEE TCPMT 2025, DOI: 10.1109/TCPMT.2025.3526500
- Yeary et al., *Co-packaged Optics on Glass Substrates for 102.4 Tb/s Data Center Switches*, IEEE ECTC 2023, DOI: 10.1109/ECTC51909.2023.00046
- Ling, Yuan & Yoo, *Low-Loss Three-Dimensional Fan-in/Fan-out Devices for Multi-Core Fiber Integration*, OFC 2021, DOI: 10.1364/OFC.2021.Th1A.37
- Zhou et al., *LiDAR / LiDAR 2.0*, DOI: 10.1145/3698364.3705355 / 10.1109/TCAD.2025.3624197
- JEDEC, *HBM4 (JESD270-4)* 2025 与 *SPHBM4 (JESD330-4)* 2026

完整文献库见 [10_参考文献.bib](deepseek/docs/research/10_参考文献.bib)。

---

---

## 六、1024 通道三维布线实验数据（2026-10-30 补充）

新增 `experiments/auto_u_bundle_hybrid/`：仅收录 2026-10-30 开始的「Hybrid 基线上自动 U 分组 + 自动层分配」实验数据（此前的 Structured/Spatial/Hybrid 等方案数据不在此仓库）：

- [Auto U 实验说明](experiments/auto_u_bundle_hybrid/README.md)：自动分组 + 自动层分配实验；代码在 `experiments/auto_u_bundle_hybrid/code/`；主结果 `routes_1024.json`（1024 条完整 XYZ）、`validation.json`、`summary.json`、`comparison.json`、8 个层分配变体与逐层图。

关键结论（诚实版）：

- 自动 k-means 分组（k=4）精确复现手动 BUNDLES 的 4 个 U 束（20–35 / 144–159 / 160–175 / 176–191）；
- 自动层搜索最优解回到 L3/L3/L4/L5，1024/1024，全局唯一交叉 **12,960，与 Hybrid H 持平**，`PASS`；总长 98,736.09 mm（比 Hybrid +716.16 mm）；
- 贪心初解 14,104，其他层排列均为 13,080；未找到优于 Hybrid 的自动分层；
- 手动 Spatial U 的 12,824 来自 V2 基线（U 层 L2/L2/L3/L4），与 Hybrid 基线不可直接比较，且该层分配在 Hybrid 基线上不可行。

> 数据来源：`OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/`；仅上传结果、代码与图件，不改变本地实验输出。

---

*整理日期：2026-10-28（2026-10-30 补充实验数据）*

---

## 七、Z1 多层 / 边缘 / 拓扑优化实验数据（2026-10-30 补充）

新增以下实验目录（均基于 150 µm 层栈：Z1=0、Z2=0.5、L2=0.65 起、层距 0.15 mm）：

- [z1_multilayer_150um](experiments/z1_multilayer_150um/README.md)：5L 基线 + 5/7/9/11L Z1 优化；五组均 1024/1024、3D violations=0。全局交叉：5L 基线 13,920；5L 优化 12,000；7L 11,984；9L 12,360；11L 12,240。
- [z1_edge_optimization](experiments/z1_edge_optimization/experiment_report.md)：7L 边缘交叉专项；全局 11,984→6,078（−40.9%），Z1 10,976→5,256（−52.1%），Z1 横纵 5,888→1,092。
- [z1_topology_global_7L](experiments/z1_topology_global_7L/experiment_report.md)：7L 全局层分配 + 邻边拓扑 A/B/C/D 实验；四组均未找到优于 6,078 的合法方案，最佳仍为 6,078（1024/1024、violations=0）。结果诚实记录：邻边 0.125 mm 引出段无法容纳 ≥6.2 mm 的 S 升降，直接抬层产生违规；替代多段圆弧拓扑在板边/R15/端口切向下未找到合法解。
- `experiments/code_z1/`：新增实验代码（150 µm 层栈、交叉溯源、联合重布、多层验证器副本）。

> 说明：以上均为真实重新生成的 1024 条 XYZ 结果，不是只改层标签；验证状态为 `exploratory_only`（层高仍为未确认仿真参数）。

---

## 八、E1：Z1 优先抬升 + Z2 协同避让 + L6/L7 资源利用实验（2026-10-31 补充）

新增 `experiments/E1_z1_priority_z2_rerouting/`：在 `z1_topology_global_7L` 的
**6,078** 基线之上，按 E1-A / E1-B / E1-C / E1-D 四组实验验证
「Z1 优先占位 + Z2 部分路线让到 L6/L7 + 接入段缩短」。

- 说明文档：[experiment_report.md](experiments/E1_z1_priority_z2_rerouting/experiment_report.md)；
  技术报告 [E1_z1_priority_z2_rerouting.md](docs/reports/E1_z1_priority_z2_rerouting.md)；
  代码 [experiments/code_e1/](experiments/code_e1/README.md)。
- 每个正式完整方案均含 `routes_1024.json`（真实 XYZ）、`summary.json`、
  `validation.json`、`per_route.csv`、`per_layer.csv` 与 `figures/`；
  诊断组（E1-B1/B2）在目录、文件名、图件标题与 `validation.json`（`not_validated`）
  中均明确标注 **DIAGNOSTIC ONLY**，不作为 1024 通道成果。

| 组 | 说明 | 全局唯一交叉 | Z1 | Z2 | 高层 | L6/L7 | violations |
|---|---|---:|---:|---:|---:|---|---:|
| BASE | 上一轮最优 | 6,078 | 5,256 | 752 | 70 | 0/0 | 0 |
| C1 | 只调 Z1（Z2 原样） | 5,286 | 4,464 | 752 | 70 | 0/0 | 0 |
| C2 | Z1 优先 + Z2 单线让路 | 5,286 | 4,464 | 752 | 70 | 0/0 | 0 |
| C3 | Z1 优先 + Z2 线束让路 + Z1 窗口再优化 | 3,850 | 2,608 | 752 | 490 | 128/0 | 0 |
| D2 | BASE + 已抬升 Z1 非对称窗口 | 4,670 | 3,400 | 752 | 518 | 0/0 | 0 |
| D3 | 在 C3 上再优化（收敛，0/228 条净收益） | 3,850 | 2,608 | 752 | 490 | 128/0 | 0 |
| **D3+Z2 retune（best）** | C3 + 8 条 Z2 对边波导重开窗 48→15 mm | **3,594** | **2,608** | **240** | 746 | **128/0** | **0** |

- **E1-A 诊断**：29 个回退 C2 对（58 条波导）**并非被 Z2 硬性封死**——细网格
  （L2–L7 × 多升降起点/下降起点，成对与单条两种模式）下 **29/29 存在合法抬升窗口**，
  纯几何不可行 = 0。BASE 回退是旧优化器 a 网格止于 55.0 mm 的分辨率假象
  （例如 1_EW 的合法窗口为 55.2–57.7 ∪ 61.7–66.2，仅差 0.2 mm 被漏掉）。
  旧窗口处阻挡以 Z2 相邻共线长臂为主：Z2-only 23/29、Z1+Z2 混合 6/29；
  共 144 条不同 Z2 路线参与阻挡（108 adjacent + 32 same_U + 4 opposite），
  完整候选/阻挡清单共 9,570 行（含全部阻挡 route_id 与冲突 XYZ）。
- **E1-B（仅诊断）**：移除全部 Z2 后 29/29 对可抬升，Z1 交叉 5,256→4,464（−792），
  但高层 70→2,054（+1,984）；只移除可移动 Z2 得到**完全相同**的 −792。
  → **可移动 Z2 不是障碍**；固定相邻 Z2 长臂只是把合法窗口压到 44–66 mm 的窄走廊，
  也不是硬墙。真正的限制是旧网格分辨率 + 行程拉长后的高层交叉。
- **E1-C（完整 1024）**：C3 把 128 条与 Z1 直线共线的 Z2 相邻/对边长臂清空到 L6
  （L6 该层独立复核交叉 = 0），11 个 EW 对在 a=1.6 早抬升到 L2，19 个 NS 对窗口缩短；
  6,078 → **3,850（−2,228，−36.7%）**，1024/1024、violations=0。
- **E1-D**：206 条已抬升 Z1 路线承担全部 3,680 邻边相关交叉（2,276 直线接入段 +
  1,404 圆弧）；D2 非对称窗口把 6,078→4,670（−23.2%，邻边直线 2,276→932）；
  D3 在 C3 上 0/228 条再获净收益（已收敛，诚实负结果）；Z2 重开窗扩展把 best 降到
  **3,594（−2,484，−40.9%）**，加工时间 27.0060 h（1 mm/s），L6=128 / L7=0，
  1024/1024、violations=0。
- **诚实边界**：层高仍为未确认仿真参数，验证状态一律 `exploratory_only`；
  交叉定义、R15、0.08 mm 净空与端口契约均未放宽；3,594 的改善来自层分配与升降窗口，
  **不改变拓扑、不改变连接表**。剩余限制为端口共线 + S 型升降模板刚性 + L3 U 线束
  高层代价；继续下降需要端口非平面 3D 复合转向或相邻边拓扑重构。

> 数据来源：本地 `OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/z1_multilayer_150um/E1_z1_priority_z2_rerouting/`；
> 仓库仅收录结果、代码与图件，不改变本地实验输出；`_e1a_diagnosis_cache.pkl` 等
> 可再生成缓存未上传。

---

## 九、C4-SYMMETRIC：1024 通道严格四元旋转对称多层三维布线（2026-10-31 补充）

新增 `experiments/c4_symmetric_multilayer/`：在 **严格 C4 旋转对称**约束下
（`R(x,y,z) = (150-y, x, z)`，z 不变，256 个连接 group 即 256 个 C4 轨道），
把布线层数作为可优化变量（7 / 9 / 11 / 13 层），联合优化四元组层分配、
S 型升降窗口与 Z1/Z2 协同避让。

- 说明文档：[experiment_report.md](experiments/c4_symmetric_multilayer/experiment_report.md)；
  技术报告 [c4_symmetric_multilayer.md](docs/reports/c4_symmetric_multilayer.md)；
  代码 [experiments/code_c4/](experiments/code_c4/README.md)。
- 每组完整方案含 `routes_1024.json`（真实 XYZ）、`summary.json`、`validation.json`、
  `c4_validation.json`（独立 C4 验证器）、`per_route.csv`、`per_layer.csv`、
  `search_log.json`、`figures/`（10 张强制图：01_overall_3d、02_overall_xy、
  03_c4_four_orbits、04_c4_rotation_overlay、05_layer_usage、
  06_all_layers_contact_sheet、07_crossing_hotspots、08_before_after、
  09_transitions_3d、10_c4_validation）。

| 方案 | 层数 | 全局唯一交叉 | 相对 E1(3,594) | Z1 | Z2 | 高层 | 升降段 | 加工时间(h) | C4 通过 | violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| C4-BASE（仅对称、不优化） | 7 | 42,584 | +38,990 | 29,376 | 13,208 | 0 | 0 | 27.0662 | True | 0 |
| C4-7L | 7 | 30,620 | +27,026 | 29,376 | 1,116 | 128 | 784 | 27.0692 | True | 0 |
| **C4-9L（最优）** | 9 | **30,556** | +26,962 | 25,828 | 4,652 | 76 | 456 | 27.0758 | True | 0 |
| C4-11L | 11 | 31,464 | +27,870 | 26,436 | 4,972 | 56 | 432 | 27.0757 | True | 0 |
| C4-13L | 13 | 30,936 | +27,342 | 25,824 | 5,052 | 60 | 440 | 27.0768 | True | 0 |

关键结论（真实运行、真实验证）：

- **E1 最优 3,594 不是严格 C4 的**。独立 C4 验证器审计 E1 best_solution：
  `symmetry_pass = False`，61 / 256 个轨道层分配不一致、64 个轨道升降段参数不一致、
  64 个轨道几何不一致，最大 XYZ 偏差 1.1 mm（全部集中在 z1-opposite 轨道）。
- **严格 C4 的代价是量级性的**：本实现的最优严格 C4 结果为 C4-9L 的 30,556，
  约为 E1 非对称结果的 8.5 倍。原因不是搜索不足，而是约束结构：z1 对边轨道由
  2 条东西向 + 2 条南北向直线组成，C4 要求四条同层；同层时轨道内部必交（4 个），
  两条轨道同层还成组相交（8 个），因此每层交叉随"每层轨道数平方"增长，
  层数收益上限被锁死。
- **层数不是越多越好**：7L=30,620、9L=30,556、11L=31,464、13L=30,936，
  差异仅 ~3%。新增层同时被 Z2 线束与 z1 轨道争夺，且更高层的 S 型升降足迹更大
  （L13 约 11.5 mm），3D 净空约束更紧，抵消了分层收益。
- **抬升轨道数受限**：低交叉搜索候选在冻结验证器的严格三维净空（稠密采样）下
  会出现数百个 marginal clearance 违规，整轨道回退到接口层后 violations=0
  （回退 116–119 / 256 个轨道，清单见各 `summary.json` 的
  `repair_reverted_orbit_ids`）。残余交叉主要来自未抬升的 z1 对边轨道在接口层。
- **邻边波导仍不可整条抬升**：0.125 mm 直线引出段 vs L2 需 6.2 mm（L13 需 11.5 mm）
  S 型足迹，层数增加只会让足迹更大——与 E1 结论一致。
- 全部方案 1024/1024 布通、冻结验证器 violations = 0（contract/port/geometry/
  curvature/clearance/same-plane/self-clearance 全 0），独立 C4 验证器
  `symmetry_pass = True`、最大 XYZ 偏差 ~4e-14 mm；层高仍为
  `unconfirmed_simulation` 研究仿真假设。

> 数据来源：本地 `OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/c4_symmetric_multilayer/`；
> 仓库仅收录结果、代码与图件，不改变本地实验输出。

---

## 十、F1/F2/F3：1024 通道分层策略与邻边专项优化实验（2026-10-31 补充）

新增 `experiments/F1_F2_F3_layer_strategy/`：研究 Z1 对边/邻边的分层策略，以及 Z2
作为独立 512 通道子系统（**严格四元旋转对称，128 个 C4 轨道**）对全局物理交叉的影响。
Z1 不要求四元对称（NS/EW/邻边可独立选层与升降窗口），Z2 严格按四元组整体调整。

- 结果文档：[experiment_report.md](experiments/F1_F2_F3_layer_strategy/experiment_report.md)；
  技术报告 [F1_F2_F3_layer_strategy.md](docs/reports/F1_F2_F3_layer_strategy.md)；
  代码 [experiments/code_f123/](experiments/code_f123/README.md)。
- 每组方案含 `routes_1024.json`（真实 XYZ）、`summary.json`、`validation.json`、
  `z2_c4_validation.json`（Z2 独立严格 C4 验收）、`per_route.csv`、`per_layer.csv`、
  `crossing_sources.csv`、`assignment_table.csv`、`figures/`（22 张：01_overall_3d、
  02_overall_xy、03_L1_Z1 … 10_L7、all_layers_contact_sheet、z1/z2_before_after、
  ns_ew_layer_separation、adjacent_routes_before_after、corner_routes_zoom、
  crossing_hotspots、transition_windows_3d）。

| 方案 | 全局唯一交叉 | Z1 | Z2 | 高层 | 升降段 | 时间(h) | 1024 | violations | Z2 C4 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---|
| E1 基线（参考最优） | **3,594** | 2,608 | 240 | 746 | 1,240 | 27.0060 | 1024/1024 | 0 | — |
| F1：邻边+NS 留 Z1，EW→L2 | 9,192 | 9,044 | 0 | 148 | 950 | 26.8997 | 1024/1024 | 80 | PASS |
| F2 初始：邻边留 Z1，NS→L2，EW→L3 | 10,516 | 8,672 | 0 | 1,845 | 1,128 | 26.7943 | 1024/1024 | 220 | PASS |
| F2 局部优化 | 11,697 | 10,332 | 0 | 1,366 | 1,062 | 26.9082 | 1024/1024 | 180 | PASS |
| F3：F2 + 邻边选择性抬升 | 9,814 | 8,310 | 0 | 1,504 | 1,198 | 26.9509 | 1024/1024 | 240 | PASS |

关键结论（真实运行、逐项验证）：

- **Z2 严格 C4 全部达成**：四个方案 Z2 独立 C4 验证 PASS（128 轨道、最大 XYZ 偏差
  2.84e-14 mm）；Z1 保持非对称，未被判为错误。
- **预设分层实况**（不是只报"执行了"）：F1 EW 132 条中 115 条进入 L2、17 条回退；
  F2 初始 NS 132 条中 94 条进入 L2（33 回退 L1、5 改 L4），EW 132 条中 86 条进入 L3
  （30 回退、13 改 L2、3 改 L6）；F3 最终 94/184 条 Z1 邻边抬升到 L3。
- **Z2 独立优化**：接口层 Z2 交叉 240 → 0（Z2 全部离开接口层），代价是高层交叉上升；
  L4–L7 使用量（F2 局部）：48 / 108 / 148 / 12 条。
- **未突破 E1 3,594**：本轮所有新方案残余 80–240 个三维净空违规（`transition_vs_flat`
  边缘近距 0.06–0.078 mm），未通过冻结验证器最终验收；按任务要求失败结果如实保存，
  未伪造合法几何。E1 3,594 仍是唯一完全合法的最优 1024 通道方案。
- **失败原因**：快速碰撞世界与冻结验证器对 S 型升降段三维净空的稠密采样仍有差距；
  回退式修复会破坏已构造的分层策略并显著增加交叉；单次全量冻结验证约 5 s，
  逐条/逐轨道修复难以在本轮时间预算内收敛到 0 violations。
- 加工时间 26.79–26.95 h（基线 27.0060 h），升降段 950–1,198（基线 1,240）。

> 数据来源：本地 `OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/F1_F2_F3_layer_strategy/`。

---

## 十一、F2 reworked：Z1 非对称 + Z2 严格 C4 的真实联合优化（2026-10-31 补充）

修复上一轮 F2 的算法问题后重新运行：以 E1 3,594 合法解为起点增量修改目标层，
候选合法性直接复用冻结验证器 `validate_l3d_multi` 的三维几何判据（过渡 0.02 mm、
平铺 0.1/0.02 mm 采样、0.08−1e-7 限值、线段-线段最近距离），分块应用并逐块全量
冻结验证。**首次得到 violations=0 的 F2 目标分层 1024 路布局**，Z2 保持严格 C4。

- 结果文档：[experiment_report.md](experiments/F2_reworked_Z1_asymmetric_Z2_C4/experiment_report.md)；
  技术报告 [F2_reworked_Z1_asymmetric_Z2_C4.md](docs/reports/F2_reworked_Z1_asymmetric_Z2_C4.md)；
  代码 [experiments/code_f2fix/](experiments/code_f2fix/README.md)。

| 方案 | 全局交叉 | Z1 | Z2 | 高层 | NS→L2 | EW→L3 | violations | Z2 C4 | 时间(h) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| E1 baseline | **3,594** | 2,608 | 240 | 746 | — | — | 0 | PASS | 27.0060 |
| 原 F2 initial | 10,516 | 8,672 | 0 | 1,845 | 94 | 86 | 220 | PASS | 26.7943 |
| 原 F2 local | 11,697 | 10,332 | 0 | 1,366 | 88 | 74 | 180 | PASS | 26.9082 |
| **新 F2 最优合法** | **4,960** | 2,343 | 240 | 2,377 | 93/132 | 65/132 | **0** | **PASS** | 27.4057 |
| 新 F2 目标完成优先（合法） | 5,187 | 2,341 | 240 | 2,606 | 99/132 | 114/132 | **0** | **PASS** | 27.4059 |
| 新 F3 follow-up（合法） | 4,960 | 2,343 | 240 | 2,377 | 93/132 | 65/132 | 0 | PASS | 27.4057 |

关键结论（真实运行、冻结验证器实测）：

- **上一轮 80–240 项违规的根因**：快速碰撞世界与冻结验证器对 S 型过渡的三维净空
  判据不一致（过渡按 0.02 mm 稠密采样 + 线段-线段距离、0.08−1e-7 限值）；旧修复把
  Z2 轨道回退接口层，破坏了 Z1 升降已利用的走廊，产生新的 `transition_vs_flat`；
  旧 `e1_z2_base()` 又把 Z1 全部恢复平铺，丢失 E1 成果。
- **本轮修复**：冻结同判据 oracle + 从 E1 增量修改 + 分块应用逐块全量验证（13 块
  全部通过）+ 只改目标层不满足的路线；Z2 以 128 个四元组整体优化并保持严格 C4
  （最大 XYZ 偏差 2.84e-14 mm）；Z1 窗口精修与 Z2 重优化真实执行（记录候选/接受/
  验证次数）。
- **目标完成率**：最优合法解 NS→L2 = 93/132、EW→L3 = 65/132（留在接口层的对边
  路线为 0）；目标完成优先合法解 NS→L2 = 99/132、EW→L3 = 114/132。
- **Z2 四元组层分布（最优合法）**：接口 46、L3 5、L4 8、L5 23、L6 43、L7 3
  （82/128 进入 L4–L7 优先区）。
- **交叉变化**：Z1 接口 2,608→2,343（−265），Z2 接口 240→240，高层 746→2,377
  （+1,631），全局 3,594→4,960（+1,366）；升降段 1,240→1,312，时间 +0.40 h。
- **科学结论**：在 R15 / 0.08 mm / 150 μm 约束下，"NS→L2、EW→L3" 的目标分层策略
  **不优于** E1 实际搜索得到的 "EW→L2、NS→L3" 分配（高层交叉代价过大）。
- **F3**：在合法 F2 上尝试 184 条 Z1 邻边抬升，冻结同判据下 0 条存在合法 S 型窗口
  （0.125 mm 引出段 vs ≥6.2 mm S 型足迹），F3 保持 F2 合法布局、无改善，如实记录。

> 数据来源：本地 `OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/F2_reworked_Z1_asymmetric_Z2_C4/`。

