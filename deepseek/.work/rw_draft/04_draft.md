# 04 直接相关论文对照与创新空间（relatedwork-researcher 独立草稿，供 Lead 合并）

> 本文件是《1024 通道三维光波导自动布线系统》调研文档第 04 部分的**独立草稿**。写作目的：把"高通道数光互连器件"与"光电子自动布线算法"两条文献脉络放进同一张核对表，回答三个问题——别人在"通道规模 / 三维程度 / 布线自动化 / 约束建模 / 实验验证"五个维度上分别走到哪里；哪些维度已被反复实现因而不能算创新；本项目在什么范围内可以主张贡献、哪些只是工程集成。
>
> 与 05 文件的分工：05 回答"为什么做、为什么是玻璃、为什么是 1024"；本文件只回答"别人做到哪、我们补什么、哪些话不能说"。
>
> 证据规则：每一条判断只以**可获取的正文或摘要**为依据，不根据标题、引用数或通道数推断贡献。标注体系：**【全文】**（正文可得，含 arXiv/开放获取）、**【摘要】**（仅有摘要）、**【仅题录】**（只有题录）、**【官方页】**（厂商页面，D 级证据）、**【估算】**（本文推算，假设随文写出）。凡写"未报"，意思是"在该文献可获取的文本中未见报告"，不表示作者没有做。

## 0. 检索范围、纳入标准与证据分级

### 0.1 检索策略

- 数据源：OpenAlex（题录、摘要、作者机构）、Crossref（卷期页核验）、arXiv（预印本全文）、Optica/Frontiers/J-STAGE（开放摘要）、RSoft/Google Research 等作者公开 PDF。检索截止 **2026-10-28**。
- 关键词族（英文；逐条检索）：automated waveguide routing / curvy waveguide routing / bend-loss aware routing / crossing-aware channel routing / 3D waveguide routing / optical waveguide shuffle / fan-in fan-out femtosecond laser / glass waveguide co-packaged optics / photonic design automation / EPDA / femtosecond laser direct writing review / optical circuit switch datacenter。
- 纳入标准（满足其一）：(a) 报告了通道数、端口数或布线规模；(b) 报告了自动/半自动版图或布线方法；(c) 报告了三维波导结构、层间连接或三维扇出；(d) 提供了可用的损耗、串扰、弯曲半径数据。
- 排除标准：仅用于传感、激光器、量子器件的波导工作（无互连含义）；纯逻辑层的片上光网络路由（无物理几何），除非同时给出物理设计方法。
- 检索边界：**未检索** CNKI 中文文献、日文文献、专利数据库与厂商内部工具链；因此本文件所有"未见/空白"均指**可获取的公开文献层面**，不得写成"没有研究"。

### 0.2 一条必须坚持的区分

本项目是**固定拓扑**（fixed-topology）的波导连接设计：连接表在设计阶段确定，加工完成后不可重构。它既不是动态光交换（OCS），也不是可编程光子电路。因此本文件把文献分为四类，分别对照、不混为一谈：

1. **需求侧/系统层**（OCS、CPO、光纤 Shuffle 产品）：证明"连接表从哪里来、规模有多大"，不提供波导几何方法；
2. **器件/工艺层**（玻璃 IOX、fs 直写、聚合物三维波导）：证明"哪些几何可被加工、损耗量级多少"，通常不含自动布线；
3. **算法/EDA 层**（光波导布线、PIC 详细布线、布局布线）：提供可迁移的方法骨架，但目前以二维单层为主；
4. **本项目**：固定拓扑 + 玻璃体内连续三维 + 工艺约束（最小间距/最小弯曲半径/交叉/写入顺序）+ 损耗与加工时间评估 + 加工路径输出。

---

## 1. 直接相关论文对照总表（20 项）

字段说明：**通道/规模** 混用了四种口径（波导条数、端口数、布线 net 数、并行通道数），表内逐项注明，**禁止横向直接比较**；**自动布线** 分三档：全自动＝输入连接表、输出可制造版图/路径；半自动＝自动生成路径但依赖模板或人工修正；无＝几何由设计者给定；**损耗模型** 分三档：无 / 常数（单点取值）/ 几何相关（随半径、角度、长度变化）；**实验** 分五档：无 / 仿真 / 单项器件测试 / 系统演示 / 生产部署。

| 论文 | 年份 | 机构 | 材料 | 加工方法 | 通道/规模 | 2D/3D | 自动布线 | 约束 | 损耗模型 | 实验 | 主要局限 | 与本项目关系 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Brusberg 等（TCPMT） | 2025 | Corning（美） | 铝硅酸盐玻璃（IOX 芯层） | 热银离子交换，约 350 °C | **>1024 条波导互连** | 2D 单层 | 无 | 评估交叉、高密度间距、紧弯曲、高光功率、偏振；未给统一约束表述 | 常数：0.034 dB/cm；85 °C/5 年寿命 | 系统演示（波导桥、MCF 扇出、shuffle、CPO 电路） | 平面工艺；无三维；摘要未提自动布线 | **最强规模对照**：1024 波导与 shuffle 已在平面实现 → 规模本身不是创新点 |
| Li 等（ADMT） | 2023 | 浙江大学/之江实验室 | 玻璃、晶体、聚合物、光刻胶 | FsDLW | —（综述） | 3D | 无（综述未涉布线自动化） | 讨论弯曲与损耗机理，未形式化 | 损耗类型与测量方法分类 | 无（综述） | 无设计流程、无算法 | 提供损耗口径与材料选择边界 |
| Yu 等（Opt. Laser Technol.） | 2026 | 上海交通大学 | 未核实 | 激光直写（据题名推断） | 未报 | 未核实 | 未核实 | 未核实 | 未核实 | 未核实（摘要与全文均未获取） | **仅题录**，不得作定量依据 | 只能作"直写做 MCF 扇入扇出"的题录级证据 |
| Grenier 等（AOT） | 2023 | Corning（美） | 碱铝硅酸盐玻璃（IOX） | 多步离子交换＋超快激光切割与烧蚀 | MPO 多芯（数量未报） | 2D | 无 | 端面平坦度 <1 µm/6.5 mm；被动对准 | <0.1 dB/cm@1310 nm | 系统演示（MPO 插拔、被动对准） | 属封装接口，非布线 | 定义本项目输出的下游约束（端面、连接器、对准容差） |
| Wang 等（AOPC） | 2025 | 中科院重庆绿色智能院/光电所 | 熔融石英 | fs 直写＋液晶 SLM 像差校正 | 未报（多通道） | 3D（深度 100–600 µm 连续变化） | 无（余弦路径由设计给定） | 未报最小间距 | 常数：插入损耗 1.0 dB（3D）/1.2 dB（同深度平面） | 单项器件测试 | 无布线算法 | 曲率连续＋变深度可加工；深度像差必须补偿 |
| Skryabin 等（PR Applied） | 2024 | 莫斯科大学/俄量子中心 | 熔融石英 | fs 多扫描直写 | 25（干涉仪） | 3D | 无 | 未报 | 0.07 dB/cm；0.2 dB/facet；25 通道 IL<1 dB | 单项器件测试 | 器件级；无算法 | **低损耗可实现的最强证据之一**；25 通道级实测 |
| Rasel 等（IEICE） | 2018 | 庆应义塾大学 | GI 聚合物 | Mosquito 无掩模直写 | 6×6＝36 | 3D shuffle | 无（版图给定） | 250 µm 节距；含水平/垂直弯曲与跨接 | 串扰 <−30 dB；跨接未引入额外插损 | 单项器件测试 | 多模；36 通道；无算法 | 三维 shuffle 的物理可行性证据 |
| Rasel & Ishigure（OE） | 2019 | 庆应义塾大学 | 聚合物 | Mosquito | 4（2×2） | 3D 交叉 | 无 | 未报 | 6 cm 插损 3.95/3.81 dB@1310 nm；串扰 <−40 dB；±1.7/2.1 µm 对准 | 单项器件测试 | 4 通道 | 三维交叉的损耗与串扰量级参照 |
| Hamamoto 等（OECC） | 2018 | 九州大学 | 玻璃/MCF | 三维波导（原理器件） | 目标 >1000 端口；原理器件规模未报 | 3D | 无 | 未报 | 常数：插损 2.1 dB；串扰 <−57.4 dB | 单项器件测试 | 未实现千端口 | 唯一以千端口为目标的三维 shuffle 结构 |
| Ling 等（OFC） | 2021 | UC Davis | 玻璃 | 超快激光直写 | 未报 | 3D | **有：automatic 3D waveguide routing algorithm（摘要级）** | 未报 | 常数：0.3 / 0.16 dB/cm（两种玻璃） | 单项器件测试 | **全文未获取**；算法细节、通道数未知 | **最接近本项目的先例，新颖性主张的最大威胁** |
| Charles 等（AO） | 2012 | 悉尼大学/Macquarie | Eagle2000 玻璃 | fs 直写 | 8 | 3D | 半自动设计方法（等长迭代），非通用布线器 | 最小间距 30 µm；可用深度约 450 µm；由深到浅顺序写入 | 解析弯曲损耗＋BeamPROP 仿真＋实测 | 单项器件测试（等长 45 µm） | 仅解等长；8 通道 | 三维几何约束设计先例；给出关键**工艺约束清单** |
| Zhou 等（LiDAR, ISPD） | 2025 | ASU/复旦 | SOI（设计） | 曲率感知 A*＋自适应交叉插入 | 446 net（最大 spacious 基准） | 2D 单层 | **有（全自动详细布线，输出 GDS）** | 弯曲半径 5/60 µm；最小间距；交叉角 | 几何相关（线性可加：1.5 dB/cm；0.005 dB/90° 弯；0.52 dB/交叉） | 无加工（输出 GDS） | 单层；常数模型；不计串扰与制造时间 | **最强二维方法基线** |
| Zhou 等（LiDAR 2.0, TCAD） | 2026 | ASU/NVIDIA/RPI | SOI（设计） | 分层曲率感知 A*＋交叉空间保留 | **8,195 net（TeMPO 最大）；1,024 net（Benes）** | 2D 单层 | **有** | 同上＋冗余弯消除、布线序细化 | 同上 | 无加工 | 单层；compact 基准为生成器构造 | **1,024 net 直接对照**：二维已到 1024 net → 规模不是创新 |
| Zhou 等（Apollo-EPDA, ICCAD） | 2025 | ASU/NVIDIA/RPI | SOI（设计） | GPU 加速布局＋布线感知 | 千级器件 | 2D | 有（布局，非布线） | 对准、间距、弯曲 | 线长/拥塞/交叉（无物理损耗数值） | 无加工 | 解决布局而非布线 | 提供"人工布局是事实标准、耗时数周"的第三方证据 |
| Condrat 等（TCAD） | 2014 | 犹他大学 | 平面光波导 | 设计自动化（不加工） | 基准 | 2D | 有（通道路由，交叉最小） | 交叉、弯曲、面积 | 几何相关（交叉与弯曲计入目标） | 无加工 | 平面通道模型 | 损耗驱动布线的方法学源头 |
| Huang 等（OECC） | 2020 | 上海交通大学 | 聚合物 | 光刻（板级） | **512（多模）** | 2D | 有（自动布局＋弯曲半径优化） | 弯曲半径优化；150×150 mm² 面积约束 | 未报 | 系统演示 | 多模、平面、板级；摘要仅三行 | 512 通道自动布线的直接先例（需核实算法细节） |
| Zheng 等（ToPro, ICCAD） | 2021 | TUM | — | 拓扑投影＋波导布线 | 16 个 IP 核 | 2D | 有 | 交叉、长绕行 | 几何相关（最坏插损 −17%） | 无加工 | 平面；WRONoC 专用 | "先拓扑、后几何"思路可借鉴 |
| Zhang 等（JLT） | 2025 | Ghent/IMEC | —（方法） | grid-less 零交叉布线 | 16 芯片（5 Tb/s 级） | 2D | 有 | 平面图/环状拓扑假设；零交叉 | 近似评估（无实测拟合） | 无加工；数值评估 | 仅限平面环状拓扑 | 零交叉与面空间分配思路参照 |
| Poutievski 等（Jupiter, SIGCOMM） | 2022 | Google | 光纤 | MEMS OCS＋SDN＋人工倒纤 | 136×136 OCS | 2D（自由空间交换） | 无（拓扑工程） | 不适用 | 常数：OCS 插损典型 <2 dB | 生产部署（十年） | 扩容仍需人工光纤倒换 | 需求侧：连接表来源；物理层重排仍人工 |
| Urata 等（Apollo-OCS, OFC） | 2023 | Google | 光纤 | 自研 MEMS OCS＋WDM 收发器 | 未报（摘要级） | 2D | 无 | 不适用 | 未报 | 生产部署（首个大规模 OCS 部署，摘要级） | 全文未获取；不含波导/布线 | 系统侧部署证据；**须与 Apollo-EPDA 区分** |

**表注（读表前必看）**：

1. **"通道数"不可直接比较。** Corning 的 >1024 是"波导条数"，Hamamoto 的 >1000 是"开关端口数目标"，LiDAR 的 446 / 8,195 是"布线 net 数"，Huang 的 512 是"多模并行通道数"。四者的几何复杂度与求解难度完全不同，把"1024"与"446"并排比较没有意义。
2. **"三维"至少有三种含义。** 连续三维几何（Nasu、Wang、Charles、Ling）、层化三维（Weigel 多层＋层间 MMI）、抽象三维（Minz 的封装层资源分配）。本项目属于第一种；与第二、三种只有方法类比价值。
3. **"自动布线"的含金量差别极大。** LiDAR 是"输入网表→输出无 DRV 的 GDS"；Huang 是"512 条多模波导在 150×150 mm² 内完成自动布局"；Ling 只声称使用了自动三维布线算法而摘要未给细节。三者不可等价。

### 1.1 五条结构性观察

**观察一：规模记录在工艺与器件手里，自动化记录在算法手里，两者尚未在玻璃三维上汇合。** 可获取文献中最大的玻璃波导互连规模（>1024 条）来自 Corning 平面 IOX 平台【摘要】；最大的三维 shuffle 目标（>1000 端口）来自九州大学原理器件【摘要】；而自动布线的规模记录来自 LiDAR 1.0 的 446 net 与 LiDAR 2.0 的 8,195 net【全文】、Huang 的 512 通道板级聚合物布局【摘要】。**关键负面事实：LiDAR 2.0 的 Benes_32×32_C 基准恰为 1,024 net。** 因此"1024 规模"在二维单层自动布线上已有基准级证据，**不能作为本项目的创新点**。

**观察二：自动布线方法学几乎全部在单层平面内演进。** 从 PROTON（2013）、PlanarONoC（2018）、PSION+（2020）、ToPro（2021）到 LiDAR（2025/2026）与 Apollo-EPDA（2025），主线解决的是"平面内少交叉、少弯曲、低插损、可制造"，状态空间是二维网格加方向维；三维只以层分配形式出现（Minz, 2006），未进入连续几何搜索。

**观察三：玻璃体内真三维几何的工作，几何由人给定、算法缺位。** Nasu 的跨接、Wang 的变深度余弦路径、Charles 的等长路由、Rasel 的三维交叉，全部是"设计者先想形状、激光照着写"。唯一明确写出"automatic 3D waveguide routing algorithm"的是 Ling 等（2021），但全文未获取——**这是本文件最重要的待核实项**。

**观察四：布线器里的损耗模型与工艺文献的损耗数据不在同一量级。** LiDAR 在 SOI 上取传播 1.5 dB/cm、单弯 0.005 dB、单交叉 0.52 dB 作为常数代入目标函数；而 fs 直写玻璃的工艺文献报告：10 mm 弯曲半径下约 1 dB/cm（Lee 2021；Xiao 2025 为 1.028 dB/cm）、30 mm 半径下 0.001 dB/mm（Tan 2022）、传播损耗 0.07 dB/cm（Skryabin 2024；Tan 2022）。**把 SOI 常数模型直接搬到玻璃三维，会得到系统性错误的最优解**——这既是风险，也是可发表的建模问题。

**观察五：制造效率从未进入布线目标函数。** 可获取的自动布线文献中，没有一篇把"激光写入时间/写入顺序"作为优化项；而工艺文献给出写入速度量级：Skryabin 等用 1–6 mm/s（实验固定 1 mm/s）【全文】、Tan 等报告最高 125 µm/s 的有效写入速度【摘要】。对 1024 条、每条数十毫米的路径，单次扫描即达数十小时量级（§3 H9，【估算】），多扫描成倍增加。**加工时间与写入顺序是本项目可以主张"领域特异"的少数维度之一，但必须先做出模型并标定。**
## 2. 逐篇十问（20 篇）

十问定义：**Q1** 材料/平台；**Q2** 加工或实现方法；**Q3** 通道/规模；**Q4** 2D 还是 3D；**Q5** 自动布线能力（无/半自动/全自动）；**Q6** 显式约束；**Q7** 损耗模型；**Q8** 实验验证程度；**Q9** 主要局限；**Q10** 与本项目的关系（可复用点/差距）。表中"未报"＝该文献可获取文本未见报告；"未核实"＝连摘要都未取得。

### 2.1 器件与工艺（6 篇）

| 论文 | Q1 材料 | Q2 方法 | Q3 规模 | Q4 维数 | Q5 自动布线 | Q6 约束 | Q7 损耗模型 | Q8 实验 | Q9 局限 | Q10 关系 |
|---|---|---|---|---|---|---|---|---|---|---|
| Brusberg 2025【摘要】 | 玻璃（IOX 芯层） | 热 Ag⁺ 离子交换，约 350 °C | >1024 波导互连 | 2D | 无 | 交叉、高密度间距、紧弯曲、偏振（评估项，非形式化） | 常数：0.034 dB/cm；85 °C/5 年 | 系统演示 | 平面；无三维；摘要未提自动布线 | 规模与 shuffle 已被平面工艺实现 |
| Li 2023【摘要】 | 玻璃/晶体/聚合物/光刻胶 | FsDLW | 综述 | 3D | 无 | 未形式化 | 损耗类型与测量方法分类 | 无（综述） | 无设计流程 | 损耗口径与材料边界 |
| Yu 2026【仅题录】 | 未核实 | 激光直写（题名推断） | 未报 | 未核实 | 未核实 | 未核实 | 未核实 | 未核实 | 摘要/全文均未获取 | 只能作题录证据 |
| Grenier 2023【摘要】 | 玻璃（IOX） | 多步离子交换＋超快激光切割/烧蚀 | MPO 多芯（未报） | 2D | 无 | 端面 <1 µm/6.5 mm；被动对准 | <0.1 dB/cm@1310 nm | 系统演示 | 封装接口非布线 | 下游封装约束来源 |
| Wang 2025【摘要】 | 熔融石英 | fs 直写＋液晶 SLM 像差校正 | 未报 | 3D（100–600 µm 连续变深度） | 无（余弦路径由设计给定） | 未报最小间距 | 常数：IL 1.0 dB（3D）/1.2 dB（平面） | 单项器件测试 | 无布线算法 | 证明连续变深度可加工、像差须补偿 |
| Skryabin 2024【全文】 | 熔融石英 | fs 多扫描直写 | 25 通道干涉仪 | 3D | 无 | 未报 | 0.07 dB/cm；0.2 dB/facet；25 通道 IL<1 dB | 单项器件测试 | 器件级；无算法 | 低损耗可实现的关键证据 |

### 2.2 三维结构与扇出（5 篇）

| 论文 | Q1 材料 | Q2 方法 | Q3 规模 | Q4 维数 | Q5 自动布线 | Q6 约束 | Q7 损耗模型 | Q8 实验 | Q9 局限 | Q10 关系 |
|---|---|---|---|---|---|---|---|---|---|---|
| Rasel 2018【摘要】 | GI 聚合物 | Mosquito 无掩模直写 | 6×6＝36 | 3D shuffle | 无（版图给定） | 250 µm 节距；水平/垂直弯曲 | 串扰 <−30 dB；跨接无额外插损 | 单项器件测试 | 多模；36 通道 | 三维 shuffle 物理可行 |
| Rasel 2019【摘要】 | 聚合物 | Mosquito | 4（2×2） | 3D 交叉 | 无 | 未报 | 6 cm IL 3.95/3.81 dB@1310；串扰 <−40 dB；±1.7/2.1 µm | 单项器件测试 | 4 通道 | 三维交叉损耗/串扰量级 |
| Hamamoto 2018【摘要】 | 玻璃/MCF | 三维波导（原理器件） | 目标 >1000 端口 | 3D | 无 | 未报 | 2.1 dB；串扰 <−57.4 dB | 原理器件 | 未实现千端口 | 唯一以千端口为目标的三维 shuffle |
| Ling 2021【摘要】 | 玻璃 | 超快激光直写 | 未报 | 3D | **有：automatic 3D waveguide routing algorithm** | 未报 | 0.3/0.16 dB/cm（两种玻璃） | 单项器件测试 | 全文未获取；算法细节未知 | 最接近的先例；新颖性最大威胁 |
| Charles 2012【全文】 | Eagle2000 玻璃 | fs 直写 | 8 | 3D | 半自动（等长迭代设计方法） | 最小间距 30 µm；深度约 450 µm；由深到浅写入；同对波导不得两次上下穿越 | 解析弯曲损耗＋BeamPROP＋实测（含耦合 9±2%、吸收 0.0075 mm⁻¹） | 单项器件测试（等长 45 µm） | 仅解等长；8 通道 | 三维工艺约束清单的直接来源 |

### 2.3 自动布线、EDA 与系统（9 篇）

| 论文 | Q1 平台 | Q2 方法 | Q3 规模 | Q4 维数 | Q5 自动布线 | Q6 约束 | Q7 损耗模型 | Q8 实验 | Q9 局限 | Q10 关系 |
|---|---|---|---|---|---|---|---|---|---|---|
| LiDAR 2025【全文】 | SOI（设计） | 网格曲率感知 A*＋自适应交叉插入 | 446 net（最大 spacious） | 2D 单层 | 全自动（输出 GDS） | 弯曲半径 5/60 µm；最小间距；交叉角；端口对准 | 线性可加（1.5 dB/cm；0.005 dB/90°弯；0.52 dB/交叉） | 无加工（GDS 输出） | 单层；常数模型；不计串扰与制造时间 | 最强二维方法基线 |
| LiDAR 2.0【全文】 | SOI（设计） | 分层曲率感知 A*＋冗余弯消除＋交叉空间保留 | **8,195 net（最大 compact）；1,024 net（Benes）** | 2D 单层 | 全自动 | 同上＋布线序细化 | 同上 | 无加工 | 单层；compact 基准由生成器构造 | 1,024 net 直接对照：规模不是创新 |
| Apollo-EPDA 2025【摘要】 | SOI（设计） | GPU 加速布局＋布线感知线长 | 千级器件 | 2D | 有（布局，非布线） | 对准、间距、弯曲半径 | 线长/拥塞/交叉（无物理损耗） | 无加工 | 解决布局而非布线 | "人工布局数周"的第三方证据 |
| Condrat 2014【摘要】 | 平面光波导 | 通道布线（交叉最小） | 基准 | 2D | 有 | 交叉、弯曲、面积 | 几何相关（交叉与弯曲计数） | 无加工 | 平面通道模型 | 损耗驱动布线方法学源头 |
| ToPro 2021【摘要】 | —（WRONoC） | 拓扑投影＋改变布线序 | 16 IP 核 | 2D | 有 | 交叉、长绕行 | 最坏插损 −17% | 无加工 | 平面；专用拓扑 | "先拓扑、后几何"可借鉴 |
| Zhang 2025【全文】 | —（PNoW） | grid-less 零交叉路由＋边着色 | 16 芯片（5 Tb/s 级） | 2D | 有 | 平面图/环状拓扑假设；零交叉 | 近似评估（无实测拟合） | 无数值实验/无加工 | 仅限平面环状拓扑 | 零交叉与面空间分配思路 |
| Huang 2020【摘要】 | 聚合物 | 光刻（板级）＋自动布局 | **512（多模）** | 2D | 有（自动布局＋弯曲半径优化） | 弯曲半径；150×150 mm² 面积 | 未报 | 系统演示 | 多模、平面；摘要仅三行 | 512 通道自动布线先例（细节待核） |
| Jupiter 2022【全文】 | 光纤 | MEMS OCS＋SDN 拓扑工程 | 136×136 OCS | 2D（自由空间） | 无（不生成波导） | 不适用 | OCS IL 典型 <2 dB | 生产部署（十年） | 扩容仍需人工倒纤 | 需求侧：连接表来源 |
| Apollo-OCS 2023【摘要】 | 光纤 | 自研 MEMS OCS＋WDM 收发器 | 未报 | 2D | 无 | 不适用 | 未报 | 生产部署（首个大规模 OCS 部署，摘要级） | 全文未获取 | 系统部署证据；与 Apollo-EPDA 区分 |

**十问的横向结论**：（i）Q5"全自动"只出现在二维单层 PIC/板级布线上（LiDAR、Huang），玻璃三维场景全部为"无"或"半自动"；（ii）Q6 显式约束最完整的是 LiDAR（弯曲半径、间距、交叉角、端口对准），但全部定义在平面内；（iii）Q7 唯一可直接用于目标函数的是 LiDAR 的线性可加模型，其系数来自 SOI 器件参数表，**不可移植到玻璃**；（iv）Q8 中真正完成"加工+测量"的都是器件论文（玻璃/聚合物），算法论文全部无加工；（v）Q4＝3D 的器件论文（Rasel、Hamamoto、Wang、Charles、Ling）无一提供通用布线算法——**"三维可加工"与"三维可自动设计"在文献中是分裂的**。

---

## 3. 十个假设的逐条检验

判定四分法：**有证据支持**（有直接文献证据）｜**部分支持**（证据存在但有边界或反例）｜**证据不足**（可获取文献不足以判断）｜**反例**（存在直接推翻该假设的文献）。每个假设后给出"论文表述建议"。

### H1 需求假设：1024 量级通道数是当前 AI/HPC 光互连的真实系统需求。

- **证据**：1024 端口光分组交换已在真实 DC/5G 前传测试床运行（Hipoλaos，ECOC 2020，10 Gb/s/端口）【摘要】；Corning 平面 IOX 玻璃已演示 >1024 条波导互连与波导 shuffle【摘要】；LiDAR 2.0 的 Benes 基准为 1,024 net【全文】；102.4 Tb/s CPO 玻璃基板设计（Yeary 等，ECTC 2023），若按 100 Gb/s/lane 折算约 1,024 lane【估算，lane 速率假设】；NVL72 按 72×18＝1,296 条 NVLink link【估算】。
- **边界**：未检索到"某产品明确规格为 1024 条独立玻璃波导"；"1024 端口"与"1024 条波导"是两种口径。
- **结论：部分支持。** 论文表述建议：写"系统级光通道/端口数已进入 10³ 量级，1024 是研究规模目标而非某产品规格"，并给出上述四条数量级证据；不得写"产品需要 1024 条玻璃波导"。

### H2 二维不足假设：二维平面布线无法支撑 1024 通道，因此必须采用真三维。

- **反例**：Corning 在平面 IOX 玻璃上演示 >1024 条波导互连（含 shuffle 电路）【摘要】；LiDAR 2.0 在单层二维上完成 Benes_32×32_C 的 1,024 net 布线（416 个逻辑交叉、零 DRV）【全文】。二者直接推翻"二维无法支撑 1024 连接"的强命题。
- **仍可成立的弱命题**：在**玻璃 fs 直写**的弯曲半径（文献实测需 R≥10–30 mm 才能把弯曲损耗压到 1 dB/cm 以下，Lee 2021、Xiao 2025、Charles 2012）与**最小间距**（Charles 取 30 µm）约束下，给定玻璃尺寸（如 75×75 mm）内二维单层能容纳的连接数有限；三维可提供额外的空间自由度。但这一弱命题**目前没有文献给出定量上限**，需要本项目自己做面积/可布率分析。
- **结论：反例（对"必须真三维"）。** 论文表述建议：删除"二维做不到 1024"这类表述；改为"二维已能实现 1024 通道（Corning IOX；LiDAR 2.0 基准），本项目研究的是在飞秒直写玻璃的工艺约束下，三维几何自由度能否降低交叉/弯曲损耗并提高单位体积内的可布连接数——这是一个需要实测与对照实验回答的问题"。

### H3 三维收益假设：真三维布线相比二维能减少交叉并降低损耗。

- **证据**：三维跨接/三维交叉在实验中"未引入额外插损"（Rasel 2018：跨接无额外插损、串扰 <−30 dB；Rasel 2019：2×2 三维交叉几乎无附加损耗、串扰 <−40 dB）【摘要/全文】；多层聚合物路由网络以层间 MMI 换取零交叉（Weigel 等，JLT 2024：16×4、4 层）【摘要】；二维平面交叉单个损耗 0.1–1 dB（LiDAR 全文引用文献值，模型中取 0.52 dB）【全文】。
- **边界**：上述"三维"多为层化/聚合物平台，与玻璃体内连续三维不同；玻璃三维交叉的损耗/串扰公开数据极少（Nasu 2005 的 2000 µm 跨接总过量损耗 2.7/2.8 dB，含耦合与传播）【摘要】；三维变深度还引入球差/模式失配代价（Wang 2025 需 SLM 校正）【摘要】。
- **结论：部分支持。** 论文表述建议：写"三维交叉的物理可行性已被聚合物与 PLC 实验证明，但'三维优于二维'在玻璃 fs 直写平台上尚无定量证据，需本项目对照实验（同连接表的 2D 版 vs 3D 版）"。

### H4 低损耗假设：飞秒直写玻璃波导能达到 1024 通道互连所需的损耗水平。

- **证据**：传播损耗 0.07 dB/cm（Skryabin 2024 全文；Tan 2022 摘要）；耦合 0.2 dB/facet、25 通道干涉仪总 IL<1 dB（Skryabin 2024 全文）；玻璃 interposer 0.88 dB/cm、光纤耦合 1.24 dB（Desmet 2021 摘要）；fs 直写三维扇出 FI/FO 0.3/0.16 dB/cm（Ling 2021 摘要）、19 通道 mux/demux 平均 IL 0.88 dB（Liang 2023 摘要）、3 芯 FI/FO 1.33 dB（Dai 2022 摘要）；平面 IOX 0.034 dB/cm 与 <0.1 dB/cm（Brusberg 2025、Grenier 2023 摘要）为不同工艺，仅作参照。
- **边界**：以上均为**器件级、单一或数十通道**的测量；1024 通道整体链路的插损预算、串扰累积与良率**没有公开数据**；不同玻璃/波长/长度/测量方法不可直接横比。
- **结论：有证据支持（器件级）。** 论文表述建议：写"单元工艺已能实现 0.07–0.9 dB/cm 量级传播损耗与 dB 量级器件插损（多来源），但 1024 通道系统的链路预算与良率仍需本项目实测/建模"。

### H5 损耗模型假设：已有可用损耗模型能支撑自动布线的代价函数。

- **证据**：LiDAR 用线性可加模型 IL=α_w·L+α_c·#CR+α_b·∠BN，并给出参数表（1.5 dB/cm、0.52 dB/交叉、0.005 dB/90°弯）【全文】；Charles 2012 给出解析弯曲损耗模型并用 BeamPROP 仿真与实测对比（R>23 mm 时吻合，R<23 mm 实测损耗高于模型且原因未明）【全文】；S 弯解析公式已有实验验证（Syahriar 2025，Sci Rep，全文可得）；
- **边界**：上述模型均为平面/硅光或均匀弯曲情形；玻璃 fs 直写波导的截面非对称、Δn 小、损耗与**写入深度/像差**相关（Wang 2025），三维交叉角的损耗/串扰函数**无公开模型**；线性可加假设在强弯曲叠加密集交叉时可能失效。
- **结论：部分支持。** 论文表述建议：模型"形式可借鉴、参数必须自标定"；论文中可写"采用可标定的分项可加模型（传播＋弯曲＋交叉＋深度项），各项系数由本课题组测试结构拟合"，并把"分项可加性验证"列为首批实验之一。

### H6 EDA 空白假设：现有公开 EDA/布线工具不支持"大尺寸＋真三维＋fs-laser 工艺约束＋加工路径输出"的自动布线。

- **证据**：LiDAR/LiDAR 2.0 明确针对**单层** PIC 详细布线【全文】；Apollo-EPDA 面向二维布局【摘要】；PROTON/PlanarONoC/PSION+/ToPro 均为平面或层化 ONoC 物理设计【摘要】；商业/开源版图工具（KLayout、Luceda IPKISS、gdsfactory）以二维版图与 DRC 为核心（见 03 文件）。
- **反例/边界**：Ling 等（2021）摘要明确使用 "automatic 3D waveguide routing algorithm" 制作三维 FI/FO 器件（全文未获取，通用性未知）；Charles 2012 的等长迭代是三维几何设计方法；Minz 2006 有三维 SoP 布线算法（抽象层资源分配）。
- **结论：部分支持。** 严格命题"没有任何三维自动布线研究"是**反例**；弱命题"面向大尺寸玻璃体内 fs-laser 工艺约束、输出加工路径的通用三维波导布线工具在可获取文献中未见"成立。论文表述建议：只用弱命题，并把 Ling 2021 列为最接近先例与待核实项；**不得写"首次"**。

### H7 自动化增益假设：自动布线相对人工设计能显著提升规模、可布率或设计效率。

- **证据**：Apollo-EPDA 摘要指出人工 PIC 布局"耗时数周且易错"【摘要】；LiDAR 在 446 net 基准上 1,204 s 完成且零 DRV，比 PROTON 类基线插损低 14%、快 6.25×【全文/摘要】；LiDAR 2.0 在 Benes_32×32 上 246 s vs PROTON 5,111 s【全文】；ToPro 将综合时间从 >6 天降到 <1 s【摘要】；PlanarONoC 最大插损降 37%【摘要】；Huang 2020 完成 512 条多模波导自动布局【摘要】。
- **边界**：人工 vs 自动的**直接对照**只在 LiDAR 的小电路上做过，结论是"质量与人工相当（个别更低插损）"，并非"显著更优"【全文 Table IX】；上述全部是二维/板级证据，玻璃三维场景的增益无文献；
- **结论：部分支持。** 论文表述建议：把自动化价值写成"可复现性、约束一致性、规模可扩展性"，而不是"质量必然超过人工"；增益指标用本项目自己的对照实验（人工/半自动/全自动的设计周期与违例数）。

### H8 计算可行性假设：10³ 规模的三维多约束自动布线可在可接受时间内完成。

- **证据（间接）**：二维 8,195 net 级别的 LiDAR 2.0 可在分层策略下运行（原文给出各基准运行时间，量级 10²–10³ s）【全文】；Zhang 2025 的 grid-less 方法强调"最小计算需求"【全文】。
- **缺口**：没有任何公开文献报告三维（连续几何＋曲率约束）在 10³ net 规模的运行结果；三维网格的分支因子、约束一致性维护与物理模型求值都会显著放大常数。本项目自估（10 µm–20 µm 网格、10×10×1 mm³ 域、1024 net、30 mm 平均路径、3–5 轮拆线重布）量级为 10³–10⁴ s，但**这是【估算】，不是实测**（假设见 12 文件）。
- **结论：证据不足。** 论文表述建议：写"二维证据表明 10³ net 量级可行；三维可行性需本项目用复杂度分析与样机实验证明"，并做分层/分窗/骨架引导的消融实验。

### H9 加工时间假设：1024 通道 fs 直写的加工时间在可接受范围（小时—数十小时）。

- **证据**：写入速度公开值差异大——Skryabin 2024 用 1–6 mm/s（固定 1 mm/s）【全文】、Tan 2022 报告最高 125 µm/s 有效写入速度（低损耗配方）【摘要】、多扫描工艺会成倍增加扫描次数【全文】；Charles 2012 记录"由深到浅顺序写入"的工艺顺序约束【全文】。
- **缺口**：无公开文献报告 1024 通道规模的实测加工时间；加工时间还取决于玻璃厚度、物镜工作距离、加速度与换行开销。
- **结论：证据不足。** 论文表述建议：给出参数化模型 T=Σ(路径长度×扫描次数)/有效写入速度＋换行/定位开销，用本课题组设备参数代入并做小规模实测外推；在论文中写成"估算＋待实测"，不写成结论。

### H10 技术路线假设：玻璃波导 Shuffle 相对光纤 Shuffle 具有密度/成本优势，且与 CPO 封装兼容。

- **证据（兼容性）**：玻璃基板已用于 CPO 研究（Yeary 2023 摘要；Brusberg 2025 摘要；Grenier 2023 摘要：玻璃波导基板＋MPO 接口）；玻璃尺寸稳定、可利用现有光纤连接器生态【摘要】。
- **缺口（密度/成本）**：Corning Shuffle Solutions 官方页只有产品形态与价值主张（Shuffle Boxes、Multifiber Shuffle Assemblies、2×2/4×4 MPO 重排），**没有端口数上限、插损、成本或密度指标**【官方页】；玻璃波导方案也没有公开的良率/成本数据。不同层级（芯片内波导 vs 机架级光纤组件）的密度不可直接横比。
- **结论：部分支持。** 论文表述建议：写"玻璃波导与 CPO 封装兼容、可利用既有连接器生态"（有证据）；"相对光纤 Shuffle 更密/更便宜"**不得写**（无证据），最多写"在原理上具有把重排集成到玻璃基板内部的潜力，需本项目给出对比框架与数据"。
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
