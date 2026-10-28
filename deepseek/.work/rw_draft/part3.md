## 4. 三类贡献评估（系统/算法/物理）

判断原则：**只有能被对照实验或可复现指标支撑的，才写成贡献；其余写成待验证假设。**

### 4.1 系统类：面向 1024 通道的"连接表→三维路径→损耗评估→加工路径"工具链

| 项目 | 内容 |
|---|---|
| 候选贡献 | 面向玻璃体内 fs 直写三维波导，构建"连接表输入→三维路径生成→间距/弯曲/交叉约束检测→损耗与串扰评估→加工路径（设备坐标序列）输出"的一体化设计系统 |
| 已有证据 | 二维侧：LiDAR 全自动输出无 DRV 的 GDS（446 net，1,204 s；LiDAR 2.0 扩到 8,195 net）【全文】、Huang 512 通道自动布局【摘要】、ToPro 拓扑投影【摘要】证明"大规模自动布线"本身可行；三维侧：Ling 2021 声称自动三维布线（细节未知）【摘要】、Charles 2012 三维约束设计【全文】、Wang 2025 变深度可加工【摘要】证明物理可行性；**但可获取文献中没有任何一篇同时覆盖连接表→三维路径→物理评估→加工路径四环节并达到 10³ 通道** |
| 尚待验证假设 | (i) 四环节集成后能显著降低人工工作量（而非只能跑通）；(ii) 1024 规模下约束检测与损耗评估能在可接受时间内完成；(iii) 输出路径能被真实写入设备直接接受（坐标/速度/顺序可行） |
| 需开展实验 | 选三张结构不同的连接表（置换型 CPO shuffle、MCF 扇出、交叉互连子集），做端到端演示；记录人工干预次数、总耗时、约束违例数、损耗分布；与"人工设计＋通用版图工具"基线对比；用设备实际参数跑小规模并外推 |
| 定性判定 | **工程集成，有条件升级为系统贡献**：条件是把端到端指标做出来；只演示功能不给指标，则只是已有算法与工具的串联 |

### 4.2 算法类：三维曲率约束搜索与可标定物理代价

| 子项 | 已有证据 | 尚待验证假设 | 需开展实验 | 定性 |
|---|---|---|---|---|
| 三维曲率连续搜索（圆弯/欧拉弯/正弦弯族扩展到空间曲线，邻居生成同时查曲率、挠率、间距） | 二维曲率感知 A* 已工程化（LiDAR：按弯曲半径自适应生成邻居、正弦弯实现端口偏移）【全文】；三维连续变深度路径可加工（Wang）【摘要】 | 三维曲线族不导致分支因子爆炸；G2 连续相对"直线+圆弧"能带来可测插损下降 | 加工同一连接的两种路径版本，实测插损差异；算法复杂度与运行时间对照 | **可能构成方法贡献**，需实验 |
| 可标定物理代价函数（弯曲半径—损耗、交叉角—串扰、间距—串扰、深度—像差四组关系参数化） | 工艺文献提供单点数据（Skryabin 0.07 dB/cm、Tan 0.07 dB/cm、Lee/Xiao 1 dB/cm@R=10 mm、Wang 深度像差）【摘要/全文】；LiDAR 给出线性可加形式【全文】 | 各损耗项近似可加（线性可分离）；四个自变量可解耦 | 参数扫描测试结构：半径 5/10/20/30 mm × 交叉角 30°/60°/90° × 间距 50/125/250 µm × 深度分层；留出样本验证 | **最可能成立的方法/建模贡献** |
| 多拓扑适应（拓扑骨架＋几何细化两层解耦） | ToPro 的拓扑投影、PSION+ 的模板优化提供思路【摘要】；LiDAR 跨 PTC 与 WRONoC 两类基准提供弱证据【全文】 | 骨架层跨连接表可复用，性能退化可接受 | 至少三类连接表（置换/扇出/随机稀疏）上的迁移实验，报告性能退化幅度 | **目前证据不足**，属待验证设想 |
| 三维并行化/分层加速 | LiDAR 2.0 分层布线在二维把运行时间降到 246 s【全文】 | 三维分层能否保持可布率 | 分层策略消融实验 | 工程实现，暂不主张创新 |

**判断**：候选一（三维曲率搜索）与候选二（可标定物理代价）可作为**方法贡献**培养，但必须与二维基线做同连接表对照；候选三（多拓扑）目前不宜作为开题主要创新点。

### 4.3 物理类：深度相关损耗、三维交叉/串扰模型、加工时间模型

| 子项 | 已有证据 | 尚待验证假设 | 需开展实验 | 定性 |
|---|---|---|---|---|
| 深度相关损耗模型（球差引起模式失配 → 损耗随深度变化） | Wang 2025 用 SLM 校正球差，3D 与平面 IL 基本持平（1.0 vs 1.2 dB）【摘要】；Charles 2012 指出可用深度受物镜工作距离限制（约 450 µm）【全文】 | 损耗可写成深度的可标定函数；校正后残余效应可建模 | 不同深度直波导/弯曲测试矩阵，拟合深度项 | **可能构成建模贡献**，需实测 |
| 三维交叉损耗与串扰 | 聚合物三维交叉无额外插损/串扰 <−40 dB（Rasel 2019）【摘要】；PLC 跨接总过量损耗 2.7/2.8 dB（Nasu 2005）【摘要】；平面交叉 0.1–1 dB（LiDAR 引用值）【全文】 | 玻璃 fs 直写三维交叉存在最优交叉角；层间交叉与同层交叉机理不同 | 加工不同交叉角/不同垂直间距的交叉阵列，测插损与串扰 | 器件级探索，风险高 |
| 加工时间/写入顺序模型 | Skryabin 写入 1–6 mm/s【全文】；Tan 125 µm/s【摘要】；Charles 深→浅顺序约束【全文】 | 时间可由路径长度、扫描次数、速度、换行开销参数化；相邻写入热影响可忽略或可补偿 | 小规模实测外推；写入顺序对照实验 | **工程集成＋建模**；目前无文献，属本项目可填的空白，但需实测 |
| 层间绝热过渡/交叉角优化等结构 | Weigel 用 3D MMI 转层【摘要】；Wang 连续变深度可写【摘要】 | 绝热过渡在 100–600 µm 深度范围保持单模 | 加工过渡段并测模式相关损耗 | 器件贡献，风险高、周期长 |

**判断**：物理层面的**真实贡献门槛最高**。在未获得本课题组工艺数据前，物理部分只能写成"采用文献参数＋可标定模型"的工程近似；若不做弯曲/交叉/深度/间距测试矩阵，则不能主张物理创新。

### 4.4 三类贡献的边界（哪些只是工程集成）

| 内容 | 定性 | 依据 |
|---|---|---|
| 图形界面、数据模型、连接表解析与校验、GDS/DXF/加工坐标导出、批处理脚本 | **仅工程集成**，不构成学术贡献 | 属软件工程；文献中无对应创新点 |
| 调用现成 A*/Lee 迷宫算法、拆线重布、k-d 树/体素哈希 | **仅工程集成** | 均为既有算法；创新必须体现在三维修正、约束建模或代价函数 |
| 把二维曲率感知 A* 直接扩展到三维网格、换一组参数 | **工程集成**（可能升级为方法贡献） | 取决于是否新增三维曲线族与合法性判据；LiDAR 已给出二维骨架 |
| 三维曲线族＋可标定物理代价＋跨连接表对照实验 | **可能构成方法贡献** | 需对照实验；可获取文献中未见同规模玻璃三维实现 |
| 弯曲—交叉—间距—深度联合损耗模型（含标定） | **可能构成建模贡献** | 现有数据为单点；模型缺失 |
| 层间绝热过渡、交叉角优化等结构设计 | **可能构成器件贡献，风险高** | 需加工与测量，周期长 |
| "首次实现 1024 通道三维自动布线" | **缺乏依据，不可主张** | Corning 已有 1024 通道平面互连；LiDAR 2.0 已有 1,024 net 二维基准；Ling 2021 已声称自动三维布线 |
| "性能优于现有工具" | **缺乏依据，不可主张** | 无同基准对比；SOI 与玻璃平台不可直接比较 |
| "支持任意连接拓扑" | **缺乏依据，不可主张** | 未做跨拓扑迁移实验 |

---

## 5. "空白"的精确表述与差异化定位

### 5.1 可以说的空白（附检索边界）

> "在可获取的公开文献中（OpenAlex/Crossref 检索，截至 2026-10-28），**尚未见到**面向玻璃体内飞秒直写三维波导、以最小间距/最小弯曲半径/交叉规避/写入顺序为约束、并把损耗/串扰评估与加工路径输出集成到同一流程的自动布线工具；现有三维工作或为人工给定的几何（Nasu、Wang、Charles、Rasel），或为未公开细节的自动算法（Ling 2021），或为二维/层化平台（LiDAR、ToPro、Weigel）。"

要点：主语是"可获取的公开文献"；动词是"尚未见到"；限定词是"玻璃体内连续三维 + 四环节集成"。这句话是可辩护的。

### 5.2 不能说的空白（有直接反例）

1. **不能说"没有三维自动布线研究"**：Ling 2021 摘要明确使用 automatic 3D waveguide routing algorithm；Charles 2012 有三维等长几何设计方法；Minz 2006 有三维 SoP 布线算法。
2. **不能说"没有实现 1024 通道器件"**：Brusberg 2025 摘要报告 >1024 波导互连与 shuffle；LiDAR 2.0 有 1,024 net 二维基准；Hipoλaos 有 1024 端口 OPS。
3. **不能说"现有 EDA 做不到三维布线"**：只能写"未检索到公开支持证据"；商业工具（Luceda/KLayout/gdsfactory）的能力边界需按 03 文件的官方文档核实结论表述。
4. **不能说"二维无法完成 1024 通道"**：见 H2 反例。

### 5.3 与四类最近工作的定位差异

| 对照对象 | 它已做到 | 它未做到（据可获取文本） | 本项目的定位 |
|---|---|---|---|
| Corning IOX 玻璃（Brusberg 2025；Grenier 2023；Yeary 2023） | 平面玻璃波导、0.034 dB/cm、>1024 互连、shuffle、CPO 封装兼容、MPO 被动对准 | 2D 平面工艺；摘要未提自动布线；无三维体内几何 | 不做新工艺，做**三维几何的自动设计方法**；与 IOX 平面工艺互补而非替代 |
| LiDAR/LiDAR 2.0（Zhou 等） | 二维单层 PIC 全自动详细布线，8,195 net，输出无 DRV 的 GDS，损耗模型线性可加 | 单层二维、SOI 参数、无深度/写入顺序/加工路径、无玻璃工艺约束 | 借鉴其"曲率感知 A*＋拆线重布＋代价函数"骨架，扩展为**三维 + 玻璃工艺约束 + 加工路径**；必须与其二维基线做同连接表对照 |
| 聚合物三维（Rasel 2018/2019；Weigel 2024） | 三维 cross/层化无交叉路由的物理可行性；损耗/串扰量级 | 器件版图人工给定；无自动布线；材料与玻璃 fs 直写不同 | 证明"三维交叉本身不必然带来大损耗"，为三维布线的代价函数提供经验锚点 |
| Ling 2021（最接近先例） | 摘要级：超快激光直写 + automatic 3D waveguide routing algorithm + 0.3/0.16 dB/cm | 全文不可得：通道数、约束类型、算法通用性、是否处理交叉/串扰均未知 | **必须列为待核实项**；取得全文前不得主张"首次"或"唯一"；若其算法通用，则本项目创新空间压缩为"约束完整性与加工路径集成" |
| Jupiter/Apollo-OCS（Poutievski 2022；Urata 2023） | 生产级 OCS 与 SDN 拓扑工程；固定光纤/波导层仍需人工倒纤与预制 shuffle | 不生成波导几何 | 需求侧证据：连接表来自拓扑工程且随扩容变化，物理层重排仍缺自动化 |

### 5.4 论文/答辩建议表述（三条）

1. **贡献表述**："面向玻璃体内飞秒直写三维波导的固定拓扑布线设计方法与原型系统：将最小间距、最小弯曲半径、交叉规避与写入顺序纳入路径搜索，并提供可标定的损耗/串扰评估与加工路径输出。"（不写"首次"、不写"最优"）
2. **规模表述**："以 1024 条连接作为压力测试规模；该规模与系统级光通道/端口数（10³ 量级）对齐，但 1024 不是某产品的规格。"
3. **对比表述**："与 LiDAR 等二维 PIC 布线器相比，本项目的差异在三维几何与玻璃工艺约束；与 Corning 的平面 IOX 器件相比，本项目差异在自动设计方法与三维自由度，而非工艺与规模。"

---

## 6. 局限与待核实

1. **全文获取率低**：20 篇对照文献中仅 6 篇取得全文（LiDAR/arXiv、LiDAR 2.0/arXiv、Charles 2012/arXiv、Skryabin 2024/arXiv、Zhang 2025/作者版、Jupiter/Google PDF）；其余为摘要（Brusberg、Grenier、Wang、Rasel、Hamamoto、Ling、Condrat、ToPro、Huang、Apollo-OCS、Apollo-EPDA、Li、Yu）；Yu 2026 仅题录。摘要可能省略方法细节与失败案例，本文件对"算法能力"的判断可能偏保守。
2. **Ling 2021 是最大不确定性**：全文不可得（Optica 需订阅）；若其算法已通用，本项目"三维自动布线"的方法创新空间将被显著压缩。
3. **Huang 2020 细节不明**：摘要仅三行；512 通道的算法、约束、是否处理交叉均未知，需取全文核实。
4. **LiDAR 2.0 的 8,195 net 是基准规模、非真实流片版图**：引用时必须写"基准（benchmark）规模"；1,024 net 的 Benes 基准为规则网络，不代表任意置换网表。
5. **平台不可直接比较**：SOI 弯曲半径 5–60 µm、交叉 0.52 dB 与玻璃 fs 直写弯曲半径 10–30 mm、损耗 0.001–1 dB/cm 属不同物理体系；本文件只在"方法结构"层面类比。
6. **检索边界**：未覆盖 CNKI、专利库、厂商内部工具链；"未见"不等于"不存在"。
7. **估算未实测**：H8（计算时间）与 H9（加工时间）的数值均为假设性估算，须用本课题组设备与实测数据替换。
8. **待核实清单**：① Ling 2021 全文；② Huang 2020 全文；③ Brusberg 2025 全文（"是否提及自动布线"）；④ Yu 2026 摘要；⑤ LiDAR 2.0 的 1,024 net Benes 基准细节；⑥ Weigel 2024 层间损耗数据；⑦ Corning 内部是否已有自动布线工具（公开文献无法回答）。

---

## 本文件引用文献

> 以下 38 条均经 Crossref 或 OpenAlex 核对（DOI 于 2026-10-28 逐一解析），凡未获取全文者注明"摘要/仅题录"。访问日期统一 2026-10-28。

[1] [Brusberg2025] L. Brusberg, M. Granados-Baez, R. Schilling, J. A. Holguín-Lerma, J. R. Rodrigues, L. W. Yeary, et al. Optical Design and Applications for Ion-Exchanged Glass Waveguide Circuits. IEEE Transactions on Components, Packaging and Manufacturing Technology, 2025, 15(8): 1614–1624. DOI: 10.1109/TCPMT.2025.3526500.【Crossref+OpenAlex；摘要】

[2] [Li2023] J. Li, C. Cao, Y. Qiu, C. Kuang, X. Liu. Optical Waveguides Fabricated via Femtosecond Direct Laser Writing: Processes, Materials, and Devices. Advanced Materials Technologies, 2023, 8(18). DOI: 10.1002/admt.202300620.【Crossref+OpenAlex；摘要】

[3] [Yu2026] F. Yu, L. Ma, L. Bai, J. Xiong, M. Xu, X. Chen, Z. He. Fully-assembled low-loss fan-in/fan-out device by laser direct writing for coupled-core fiber. Optics & Laser Technology, 2026, 194: 114521（在线 2025）. DOI: 10.1016/j.optlastec.2025.114521.【Crossref；仅题录（摘要/全文未获取）】

[4] [Grenier2023] J. R. Grenier, L. Brusberg, K. A. Wieland, J. Matthies, C. C. Terwilliger. Ultrafast laser processing of glass waveguide substrates for multi-fiber connectivity in co-packaged optics. Advanced Optical Technologies, 2023, 12. DOI: 10.3389/aot.2023.1244009.【Crossref+全文（Frontiers）；全文】

[5] [Wang2025] X. Wang, L. Zhu, Q. Zhang, M. Tang, F. Xiao, X. Wang, et al. Three-dimensional optical waveguides with continuously varying depths inscribed by femtosecond laser. AOPC 2025: Laser Technology and Applications, 2025: 60. DOI: 10.1117/12.3083656.【Crossref+OpenAlex；摘要】

[6] [Skryabin2024] N. N. Skryabin, S. A. Zhuravitskii, I. V. Dyakonov, S. S. Straupe, A. A. Kalinkin, S. P. Kulik. Femtosecond-laser-written low-loss multiscan waveguides in fused silica. Physical Review Applied, 2024, 22(6): 064079. DOI: 10.1103/PhysRevApplied.22.064079.【Crossref+arXiv:2408.06688；全文】

[7] [Rasel2018] M. O. F. Rasel, A. Yamauchi, T. Ishigure. Low-Loss 3-Dimensional Shuffling Graded-Index Polymer Optical Waveguides for Optical Printed Circuit Boards. IEICE Transactions on Electronics, 2018, E101.C(7): 509–517. DOI: 10.1587/transele.E101.C.509.【Crossref+OpenAlex；摘要】

[8] [Rasel2019] M. O. F. Rasel, T. Ishigure. Circular core single-mode 3-dimensional crossover polymer waveguides fabricated with the Mosquito method. Optics Express, 2019, 27(22): 32465. DOI: 10.1364/OE.27.032465.【Crossref+OpenAlex；摘要】

[9] [Hamamoto2018] K. Hamamoto, Y. Hinokuma, S. K. Ghosh, R. Kuwahata, H. Jiang. Shuffle converter using 3D waveguide for MCF/SMF fan-in fan-out configuration toward over 1,000 port count optical matrix switch. OECC 2018, 2018: 1–2. DOI: 10.1109/OECC.2018.8730115.【Crossref+OpenAlex；摘要】

[10] [Ling2021] Y.-C. Ling, S. Yuan, S. J. B. Yoo. Low-Loss Three-Dimensional Fan-in/Fan-out Devices for Multi-Core Fiber Integration. OFC 2021, 2021: Th1A.37. DOI: 10.1364/OFC.2021.Th1A.37.【Crossref+OpenAlex+Optica 摘要页；摘要（全文未获取）】

[11] [Charles2012] N. Charles, N. Jovanovic, S. Gross, P. Stewart, B. R. M. Norris, J. O'Byrne, et al. Design of optically path-length-matched, three-dimensional photonic circuits comprising uniquely routed waveguides. Applied Optics, 2012, 51(27): 6489. DOI: 10.1364/AO.51.006489.【Crossref+arXiv:1209.5144；全文】

[12] [Zhou2025a] H. Zhou, K. Zhu, J. Gu. LiDAR: Automated Curvy Waveguide Detailed Routing for Large-Scale Photonic Integrated Circuits. ISPD 2025, 2025: 64–72. DOI: 10.1145/3698364.3705355.【Crossref+arXiv:2410.01260；全文】

[13] [Zhou2025b] H. Zhou, H. Yang, Z. Yin, N. W. Gangi, Z. Huang, H. M. Ren, et al. LiDAR 2.0: Hierarchical Curvy Waveguide Detailed Routing for Large-Scale Photonic Integrated Circuits. IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems, 2026, 45(6): 2664–2678（2025 在线）. DOI: 10.1109/TCAD.2025.3624197.【Crossref+arXiv:2505.17239；全文】

[14] [Zhou2025c] H. Zhou, H. Yang, N. W. Gangi, Z. Huang, H. M. Ren, J. Gu. Apollo: Automated Routing-Informed Placement for Large-Scale Photonic Integrated Circuits. ICCAD 2025, 2025: 1–9. DOI: 10.1109/ICCAD66269.2025.11240728.【Crossref+OpenAlex；摘要】

[15] [Condrat2014] C. Condrat, P. Kalla, S. Blair. Crossing-Aware Channel Routing for Integrated Optics. IEEE TCAD, 2014, 33(6): 814–825. DOI: 10.1109/TCAD.2014.2317575.【Crossref+OpenAlex；摘要】

[16] [Zheng2021] Z. Zheng, M. Li, T.-M. Tseng, U. Schlichtmann. ToPro: A Topology Projector and Waveguide Router for Wavelength-Routed Optical Networks-on-Chip. ICCAD 2021, 2021: 1–9. DOI: 10.1109/ICCAD51958.2021.9643451.【Crossref+全文（TUM mediatum）；全文】

[17] [Zhang2025] Z. Zhang, D. Colle, W. Tavernier, M. Pickavet. A Zero-Crossing Optical Waveguide Routing Method. Journal of Lightwave Technology, 2025, 43(10): 4881–4894. DOI: 10.1109/JLT.2025.3539231.【Crossref+作者版全文；全文】

[18] [Huang2020] Z. Huang, L. Ma, W. Kuang, Y. Shi, Z. He. Automatic high-density polymer waveguide layout for on-board high-speed optical interconnect. OECC 2020, 2020: 1–3. DOI: 10.1109/OECC48412.2020.9273659.【Crossref+OpenAlex；摘要】

[19] [Poutievski2022] L. Poutievski, O. Mashayekhi, J. S. Ong, A. Singh, M. Tariq, R. Wang, et al. Jupiter Evolving: Transforming Google's Datacenter Network via Optical Circuit Switches and Software-Defined Networking. ACM SIGCOMM 2022, 2022: 66–85. DOI: 10.1145/3544216.3544265.【Crossref+全文 PDF；全文】

[20] [Urata2023] R. Urata, H. Liu, K. Yasumura, E. Mao, J. Berger, X. Zhou, et al. Apollo: Large-Scale Deployment of Optical Circuit Switching for Datacenter Networking. OFC 2023, 2023: M2G.1. DOI: 10.1364/OFC.2023.M2G.1（IEEE 版 DOI: 10.23919/OFC49934.2023.10116374）. 【Crossref 双 DOI+OpenAlex；摘要（全文未获取）】

[21] [Weigel2024] M. Weigel, M. Kleinert, M. Kresse, D. de Felipe, H. Conradi, J. Reck, et al. Design and Fabrication of Crossing-Free Waveguide Routing Networks Using a Multi-Layer Polymer-Based Photonic Integration Platform. Journal of Lightwave Technology, 2024, 42(5): 1511–1517. DOI: 10.1109/JLT.2023.3320908.【Crossref+OpenAlex；摘要】

[22] [Tan2022] D. Tan, X. Sun, Z. Li, J. Qiu. Effectively writing low propagation and bend loss waveguides in the silica glass by using a femtosecond laser. Optics Letters, 2022, 47(18): 4766. DOI: 10.1364/OL.470670.【Crossref+OpenAlex；摘要】

[23] [Lee2021] T. Lee, Q. Sun, M. Beresna, G. Brambilla. Low bend loss femtosecond laser written waveguides exploiting integrated microcrack. Scientific Reports, 2021, 11(1): 23770. DOI: 10.1038/s41598-021-03116-y.【Crossref+Nature 全文；全文】

[24] [Xiao2025] K.-H. Xiao, Y.-H. Zan, Y. Ouyang, S.-X. Fei, Z.-Y. Hu, L. Fang, et al. Low-loss and tight-bend waveguides via multiple scans of a femtosecond laser. Optics Letters, 2025, 50(5): 1449. DOI: 10.1364/OL.551272.【Crossref+OpenAlex；摘要】

[25] [Desmet2021] A. Desmet, A. Radosavljevic, J. Missinne, D. Van Thourhout, G. Van Steenberge. Laser Written Glass Interposer for Fiber Coupling to Silicon Photonic Integrated Circuits. IEEE Photonics Journal, 2021, 13(1): 1–12. DOI: 10.1109/JPHOT.2020.3039900.【Crossref+OpenAlex；摘要】

[26] [Liang2023] Y. Liang, C. Cai, K. Wang, X. Lian, J. Wang, et al. Low-insertion-loss femtosecond laser-inscribed three-dimensional high-density mux/demux devices. Advanced Photonics Nexus, 2023, 2(3): 036002. DOI: 10.1117/1.APN.2.3.036002.【Crossref+OpenAlex；摘要】

[27] [Dai2022] Z. Dai, J. Xiong, L. Ma, Z. He. Low-Loss and Low-Crosstalk Fan-in/Fan-out Device for Multicore Fiber Using a Femtosecond Laser Direct Inscription Technique. ICOCN 2022, 2022: 1–2. DOI: 10.1109/ICOCN55511.2022.9901157.【Crossref+OpenAlex；摘要】

[28] [Djogo2019] G. Djogo, J. Li, S. Ho, M. Haque, E. Y. Ertorer, et al. Femtosecond laser additive and subtractive micro-processing: enabling a high-channel-density silica interposer for multicore fibre to silicon-photonic packaging. International Journal of Extreme Manufacturing, 2019, 1(4): 045002. DOI: 10.1088/2631-7990/ab4d51.【Crossref+OpenAlex；摘要】

[29] [Yeary2023] L. W. Yeary, L. Brusberg, C. Kim, S.-H. Seok, J. Noh, A. Rozenvax. Co-packaged Optics on Glass Substrates for 102.4 Tb/s Data Center Switches. IEEE ECTC 2023, 2023: 224–227. DOI: 10.1109/ECTC51909.2023.00046.【Crossref+OpenAlex；摘要】

[30] [HipoLaos2020] G. Giamougiannis, A. Tsakyridis, N. Terzenidis, D. Spasopoulos, C. Vagionas, N. Pleros. Demonstration of Low-Latency ETH-switched DataCenter and 5G Fronthaul Networks Using the 1024-port Hipoλaos Optical Packet Switch. ECOC 2020, 2020: 1–4. DOI: 10.1109/ECOC48923.2020.9333177.【Crossref+OpenAlex；摘要】

[31] [Davis1996] K. M. Davis, K. Miura, N. Sugimoto, K. Hirao. Writing waveguides in glass with a femtosecond laser. Optics Letters, 1996, 21(21): 1729–1731. DOI: 10.1364/OL.21.001729.【Crossref+OpenAlex；摘要】

[32] [Gattass2008] R. R. Gattass, E. Mazur. Femtosecond laser micromachining in transparent materials. Nature Photonics, 2008, 2(4): 219–225. DOI: 10.1038/nphoton.2008.47.【Crossref；题录】

[33] [Tan2021] D. Tan, Z. Wang, B. Xu, J. Qiu. Photonic circuits written by femtosecond laser in glass: improved fabrication and recent progress in photonic devices. Advanced Photonics, 2021, 3(2): 024002. DOI: 10.1117/1.AP.3.2.024002.【Crossref+OpenAlex；摘要】

[34] [Choudhury2014] D. Choudhury, J. R. Macdonald, A. K. Kar. Ultrafast laser inscription: perspectives on future integrated applications. Laser & Photonics Reviews, 2014, 8(6): 827–846. DOI: 10.1002/lpor.201300195.【Crossref+OpenAlex；摘要】

[35] [YuOFC2025] F. Yu, L. Ma, J. Xiong, L. Bai, M. Xu, Z. He. Low-loss Fan-in/Fan-out Device for Coupled four-core Fiber Using a Femtosecond Laser Direct Inscription Technique. OFC 2025, 2025: M4J.5. DOI: 10.1364/OFC.2025.M4J.5.【Crossref+OpenAlex；摘要】

[36] [Bogaerts2018] W. Bogaerts, L. Chrostowski. Silicon Photonics Circuit Design: Methods, Tools and Challenges. Laser & Photonics Reviews, 2018, 12(4): 1700237. DOI: 10.1002/lpor.201700237.【Crossref+OpenAlex；摘要】

[37] [Minz2006] J. R. Minz, S. Thyagaraja, S. K. Lim. Optical Routing for 3D System-On-Package. DATE 2006, 2006: 1–2. DOI: 10.1109/DATE.2006.244180.【Crossref+OpenAlex；摘要】

[38] [Corning2026] Corning Incorporated. Shuffle Solutions（Fiber Shuffle Box and Multifiber Shuffle Assembly Solutions）. 官方产品页. URL: https://www.corning.com/optical-communications/asean/en/home/products/shuffle-solutions.html.（访问 2026-10-28）【官方页（经 r.jina.ai 取正文）；D 级证据】

> 注：本文件为**独立草稿**，合并时需把新增条目（Urata2023、Yeary2023、Skryabin2024、Davis1996、Gattass2008、Hipoλaos2020、Dai2022、YuOFC2025、Thomson2011、Tan2021、Choudhury2014、Suganuma2015、Lindenmann2015 等）同步写入 `docs/research/.refs_related.json`；其中 Thomson2011（10.1364/OE.19.005698）与 Suganuma2015（10.1364/OE.23.001585）、Lindenmann2015（10.1109/JLT.2014.2373051）因篇幅未列入上表，但已在正文论证中作为三维扇出/引线键合的补充证据。
