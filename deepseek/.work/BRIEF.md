# 共享调研 BRIEF（所有子任务必读）

## 0. 项目背景
本科毕业设计：《1024 通道三维光波导自动布线系统》。技术路线：飞秒激光直写玻璃内部三维光波导（fs-laser direct writing, FsDLW），目标是构建可处理 1024 条光波导连接、带最小间距/最小弯曲半径/交叉规避约束、可评估损耗/串扰/加工时间、可输出加工路径的自动布线软件系统。
本次任务**不是**开发系统，而是产出一套可用于毕业论文第 1 章、第 2 章、开题与答辩的**可追溯调研文档**。

核心必须回答：为什么做、有什么用、为什么选这项技术、现有工作做到哪里、我们究竟解决什么问题。
**禁止**预设"本项目优于已有技术"，**禁止**预设"1024 通道就是创新点"。

## 1. 工作目录与文件
- 工作根目录：`/Users/lihaolun/Desktop/第二次汇报/reseach/deepseek`
- 最终文件目录：`docs/research/`
- 共享工具与缓存：`.work/`（`lib.py` 文献 API 工具；`candidates.json` + `enriched.json` 已抓取的候选文献池；`refs_pool.md` 候选清单；`pages/` 已抓页面文本）

## 2. 风格与诚实性规则（最重要）
1. 结论必须来自可验证证据或明确标注的推理。无法访问全文时写"**仅有题录/摘要，全文未获取**"，绝不能根据摘要虚构实验数据。
2. 区分：**真实案例**（有公开出处）/ **自行构造的研究示例**（须标"本文构造的示例，非真实部署"）/ **待验证假设**。
3. 行业数字必须给出来源 + 访问日期；学术数字给 DOI + 页码/图号/章节（能定位就定位，不能定位写"摘要"）。
4. 不把"未检索到"写成"没有研究"；不把"可能应用"写成"已经应用"；不把"仿真目标"写成"已加工"；不把"理论估算"写成"实验测试"。
5. 不伪造 DOI、作者、年份、期刊、卷期页码。每一条参考文献都要经过 Crossref（`https://api.crossref.org/works/<doi>`）或 OpenAlex（`https://api.openalex.org/works/https://doi.org/<doi>`）核对。
6. 中文正式学术语体，原创归纳，不整段翻译拼接。所有英文引文若直接引用须加引号并标注来源。
7. 禁止用博客/自媒体/百科作为学术依据；厂商官网、JEDEC/OCP/CXL 标准组织、IEEE/Optica/Nature/ACM/SPIE 论文优先。
8. 对所有数量级比较，必须统一单位并说明测量条件（波长、器件尺寸、测量方法），不得把不同定义的指标直接比较。

## 3. 已核验的关键事实（可直接引用，不需要重复查）

### 3.1 OCS / Jupiter（已读全文，PDF: research.google pubtools/6752.pdf）
- 文献：L. Poutievski et al., "Jupiter Evolving: Transforming Google's Datacenter Network via Optical Circuit Switches and Software-Defined Networking", ACM SIGCOMM 2022, DOI 10.1145/3544216.3544265.
- 十年演进：5× 速率与容量、capex −30%、功耗 −41%；Clos → 机器聚合块（aggregation block）之间的 direct-connect 拓扑；新增 DCNI（datacenter interconnection）光层，用 MEMS OCS + 集中式 SDN。
- 60% 流量走源-目的聚合块直连路径，其余多经一跳，平均块级路径长度 1.4。
- OCS 使 fabric 重构比"patch panel 互连的 Clos"快 3×。
- Palomar OCS：136×136 无阻塞、任意输入到输出双射；2D 光纤准直器阵列（N×N 光纤阵列 + 2D 透镜阵列）+ 两组 2D MEMS 反射镜阵列；插入损耗在全排列下典型 <2 dB；回波损耗典型 −46 dB（规格 < −38 dB）。
- 用光环形器（circulator）把 Tx/Rx 波分复用到一根光纤，使所需 OCS 端口数与光纤根数减半（代价是双向电路）。
- DCNI 机架最多 8 台 OCS；fabric 可从每机架 1 台（1/8 填充）起步，扩容时倍增 OCS；扩容需要**人工光纤倒换（manual fiber moves）**，设计上把倒换限制在机架内以降低人工作业。
- DCNI 分 1/8→1/4→1/2→满配 三个增量阶段部署；聚合块可"半配"光模块、后续 radix 升级。
- 目标架构 capex 为基线 Clos 的 70%（计及 OCS 摊销后实际 62%–70%）。
- Apollo：另有 OFC 2023 论文 "Apollo: Large-Scale Deployment of Optical Circuit Switching for Datacenter Networking", DOI 10.1364/OFC.2023.M2G.1（另有 10.23919/OFC49934.2023.10116374）。**全文未获取，细节需再查**，引用时注明。

### 3.2 玻璃波导 / 1024 通道（关键对照工作）
- L. Brusberg et al. (Corning), "Optical Design and Applications for Ion-Exchanged Glass Waveguide Circuits", IEEE Trans. Components, Packaging and Manufacturing Technology, vol.15, no.8, pp.1614–1624, Aug. 2025, DOI 10.1109/TCPMT.2025.3526500.
  - 摘要（OpenAlex 获取，IEEE 全文未获取）：玻璃尺寸稳定/平整，利于 CPO 高精度光对准；热银离子交换（IOX）~350 °C 在玻璃芯层制作波导；新玻璃组分使波导在 85 °C 以上工作 5 年不退化；传播损耗仅 **0.034 dB/cm**；评估了交叉、高密度间距、紧弯曲、高光功率、偏振依赖；演示了 fiber-to-chip 玻璃波导桥、多芯扇出、**optical waveguide shuffle**、以及 **over 1024 waveguide interconnects** 的 CPO 光波导电路。
  - 这是"1024 通道玻璃波导 Shuffle 已被演示"的直接证据（但为 IOX 平面工艺，非飞秒直写三维）。
- J. Li, C. Cao, Y. Qiu, C. Kuang, X. Liu, "Optical Waveguides Fabricated via Femtosecond Direct Laser Writing: Processes, Materials, and Devices", Advanced Materials Technologies, 8(18), 2023, DOI 10.1002/admt.202300620. 综述：损耗类型与测量方法、两种加工机制、材料与器件；摘要可获取。
- F. Yu, L. Ma, L. Bai, J. Xiong, M. Xu, X. Chen, Z. He, "Fully-assembled low-loss fan-in/fan-out device by laser direct writing for coupled-core fiber", Optics & Laser Technology, vol.194, 114521, 2026, DOI 10.1016/j.optlastec.2025.114521. **摘要与全文均未获取（Elsevier 403）**：只能作为"飞秒直写制作多芯光纤扇入扇出器件"的题录证据，具体损耗数字不得引用。

### 3.3 HBM / 互联 / 标准
- JEDEC HBM4 标准 JESD270-4，2025-04-16 发布（官方新闻稿 URL: https://www.jedec.org/news/pressreleases/jedec%C2%AE-and-industry-leaders-collaborate-release-jesd270-4-hbm4-standard-advancing）：
  - 2048-bit 接口、最高 8 Gb/s → 单堆栈带宽最高 2 TB/s；
  - 每堆栈独立通道 16（HBM3）→ 32（每通道 2 个伪通道）；
  - VDDQ 0.7/0.75/0.8/0.9 V、VDDC 1.0/1.05 V；
  - 4/8/12/16-high 堆叠，24 Gb 或 32 Gb die，最高 64 GB（32 Gb 16-high）；
  - Directed Refresh Management；与 HBM3 控制器后向兼容。
- Intel OCI chiplet（Intel Newsroom, 2024-08-26, Hot Chips 2024, https://www.intel.com/content/www/us/en/newsroom/news/hot-chips-2024-ai-architectural-expertise.html，经 r.jina.ai 获取正文）：
  - 首个完全集成的 optical compute interconnect chiplet，与 Intel CPU 共封装并跑真实数据；
  - **64 通道 × 32 Gb/s 每方向**，最长 100 m 光纤；即每方向 2 Tb/s、双向 4 Tb/s（Electronic Design 标题亦为 "64 Optical Channels that Deliver 4 Tb/s"）；
  - 目标：AI 基础设施更高带宽/更低功耗/更长距离，含 coherent memory expansion 与 resource disaggregation。
- NVIDIA NVLink 官方规格页（https://www.nvidia.com/en-us/data-center/nvlink/，2026-10-28 访问）：
  - NVLink 4：900 GB/s/GPU，18 links/GPU，8-GPU domain，聚合 7.2 TB/s；
  - NVLink 5：1,800 GB/s/GPU，18 links/GPU，72-GPU domain（NVL72），聚合 130 TB/s；
  - NVLink 6：3,000 GB/s/GPU，36 links/GPU，NVL72 聚合 216 TB/s（官方标注 preliminary）。
- CXL 综述：D. Das Sharma et al., "An Introduction to the Compute Express Link (CXL) Interconnect", ACM Computing Surveys, 2024, DOI 10.1145/3669900（Microsoft Research 页面确认摘要，覆盖 CXL 1.0/2.0/3.0）。
- Synopsys 于 2025-07-17 完成对 Ansys 的收购（Synopsys 官方新闻稿 https://news.synopsys.com/2025-07-17-Synopsys-Completes-Acquisition-of-Ansys；交易 2024-01-16 宣布）。
- Ansys 于 2021 年收购 Zemax（2021-08-30 宣布，"Ansys to Acquire Zemax Pursuant to Definitive Acquisition Agreement"；**完成日期需核**）。

### 3.4 商业产品
- Corning Shuffle Solutions（官方页 https://www.corning.com/optical-communications/asean/en/home/products/shuffle-solutions.html，2026-10-28 访问，经 r.jina.ai）：
  - 属 Corning GlassWorks AI Solutions 产品组合；产品形态：Shuffle Boxes（集中式箱体内重新分配光纤连接）与 Multifiber Shuffle Assemblies（预组织的光纤重排组件）；
  - 面向高密度 AI/HPC 数据中心、spine-leaf 架构；价值主张：减少安装错误、精确映射、节省机架空间、加快部署；
  - 可定制：错开/等长长度、标签、连接器颜色编码。
- 需要补充调研：Corning 具体端口数/密度指标、MPO/MTP 与 MT ferrule 标准（IEC 61754-7）、SENKO/US Conec/Molex/Fujikura 产品、Telescent 机器人光纤配线、Polatis/Calient 等 OCS 厂商的端口规模与指标。

## 4. 可用的检索工具与配方（在本机 curl 可用！）

```bash
cd /Users/lihaolun/Desktop/第二次汇报/reseach/deepseek/.work
# 1) Crossref 按 DOI 核验元数据（标题/作者/年/卷期页）
curl -s "https://api.crossref.org/works/10.1145/3544216.3544265" | python3 -m json.tool | head -60
# 2) Crossref 检索（找论文，rows 最多 20）
curl -s -G "https://api.crossref.org/works" --data-urlencode "query.bibliographic=YOUR QUERY" --data-urlencode "rows=10" --data-urlencode "select=DOI,title,issued,container-title,author,type" | python3 -m json.tool | head -80
# 3) OpenAlex 取摘要/作者/引用数/开放获取链接（支持 | 批量）
curl -s "https://api.openalex.org/works?filter=doi:10.1109/TCPMT.2025.3526500|10.1145/3544216.3544265&select=doi,title,publication_year,authorships,abstract_inverted_index,cited_by_count,primary_location,best_oa_location"
# 4) 取任意网页正文（对 403 的厂商/期刊页有效）；下载 PDF 后用 pypdf 抽文本
curl -s "https://r.jina.ai/https://WWW.EXAMPLE.COM/PAGE" -o /tmp/p.txt
curl -sL "https://xxxx.pdf" -o /tmp/a.pdf && python3 -c "import sys;sys.path.insert(0,'.');import lib;print(lib.pdf_text('/tmp/a.pdf')[:3000])"
# 5) 用本目录 lib.py 一行取摘要字典
python3 -c "import sys;sys.path.insert(0,'.');import lib,json;print(json.dumps(lib.openalex_by_dois(['10.1145/3669900']),ensure_ascii=False)[:1500])"
```
注意：Crossref 对高频请求返回 429，脚本里已内置 8 s 退避；批量查询请在每条间 `sleep 1`。
`r.jina.ai` 是第三方正文抽取代理，只把它当"页面文本"，所有关键数字仍以原始出处（DOI/官网 URL）为准。
已抓取页面文本在 `.work/pages/`，候选文献池在 `.work/candidates.json` / `.work/enriched.json` / `.work/refs_pool.md`。

## 5. 引用格式（统一）
- 正文引用：`[Poutievski et al., 2022]` 或中文作者 `[Brusberg 等, 2025]`；同一文献多个结论可复用同一 key。
- 每个文件末尾必须有 `## 本文件引用文献` 小节，逐条列出：
  `[key] 作者. 题目. 期刊/会议, 年, 卷(期): 页码. DOI/URL. 访问日期. 【核验方式：Crossref/OpenAlex/官方页/全文PDF；全文/摘要/仅题录】`
- 同时在文档写作时把新增文献追加写入 `docs/research/.refs_<你的任务名>.json`，格式：
  ```json
  [{"key":"Poutievski2022","authors":"Poutievski L. et al.","title":"...","venue":"ACM SIGCOMM 2022","year":2022,"doi":"10.1145/3544216.3544265","url":"https://doi.org/10.1145/3544216.3544265","verified":"Crossref+全文PDF","access":"2026-10-28","note":"..."}]
  ```
  （若不方便写 JSON，也要在文档末尾完整给出上述字段，Lead 会统一合并。）

## 6. 交付质量要求
- 中文，Markdown，标题层级清晰；表格用于对比；关键结论加粗。
- 每个结论后紧跟证据标记；推理与证据要分开（用"（推理）"或"【推理】"标注）。
- 商业宣传语不得当作技术事实；厂商指标须注明测试条件未知。
- 目标篇幅按各任务单独给出；宁可信息密度高，不要注水。
- 不确定的内容写进文末"待核实/局限"小节，不要藏进正文当事实。
