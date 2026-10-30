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
