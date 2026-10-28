# HBM、GPU、CPU与光互联：层级、通道口径及适用性

截止：2026-10-28。原始资料、页节定位见 `sources/计算系统互联证据分类.md` 和证据台账。数据以十进制GB/s、TB/s计；1 byte=8 bit。厂商公布值、模型值、计算示例分别标示。

## 1. 应用判断先行

GPU—HBM不是本课题现阶段最可信的直接替换对象。裸HBM接口为封装内电接口；无源玻璃不完成HBM命令、时钟、电平、电光转换或缓存一致性。更合理的位置是光I/O模块周边的固定扇出、机箱光背板、交换机与前面板之间的Shuffle，以及GPU集群网络的被动端口映射。即便如此，也须证明实际端口表和光预算，不等于GPU集群必须使用玻璃。

光HBM相关研究确实存在；“不存在光HBM研究”同样不准确。[OptHBM2025] 应将其视为未来系统方案，不能当作本系统已具备的能力。

## 2. HBM结构及产品点

HBM把多片DRAM垂直堆叠，通过TSV与微凸点形成密集电连接，再由底层及封装互联连接GPU／加速器的内存控制器与PHY。常见2.5D实现把处理器和HBM置于中介层或高密度重布线平台上。其优势是用很宽、相对低速的并行接口获取高带宽；宽总线同时要求大量互联资源、封装面积、供电和热管理。

| 代际与核实来源 | 数据接口／速率 | 单栈带宽、容量 | 数值条件与限制 |
|---|---|---|---|
| Samsung Flashbolt HBM2E，2020 | 1024位，3.2 Gb/s/pin | 409.6≈410 GB/s；16 GB | 特定产品点，不是所有HBM2E上限 [SamsungHBM2E] |
| SK hynix HBM3，2022 | 1024位，6.4 Gb/s/pin | 819.2≈819 GB/s；16/24 GB | 官方量产产品介绍 [SKHBM3] |
| Micron HBM3E，访问2026-10-28 | 1024有效数据I/O；>9.2 Gb/s | 厂商报>1.2 TB/s；24/36 GB | “>9.2”和“>1.2”不是等式；具体速率看SKU [MicronHBM3E] |
| HBM4 JESD270-4初版，2025-04 | 2048位；初版发布口径最高8 Gb/s | 算术为2.048 TB/s | 标准全文受限，未精读；不能称初版为2026最新修订 [JEDECHBM4] |
| Micron HBM4，2026-03-16 | 厂商报>11 Gb/s/pin | >2.8 TB/s；36 GB 12H | 厂商声称2026Q1已volume shipment；48 GB16H为送样 [MicronHBM4] |

后续SPHBM4/JESD330-4已出现JEDEC官方发布索引，但本次未取得标准正文，详细速率、引脚和距离不纳入已核定参数表。HBM4A修订亦需正式文本核对。[JEDECSPHBM4]

本次未取得足以统一比较上述产品整栈功耗的数据。功耗依赖速率、读写占比、活跃率、温度、电压及控制器边界。不能给一个“HBM能耗”常数，也不能把内部工具计算的厂商相对改善当作独立实验。

HBM的距离限制主要来自电PHY、通道预算、时序和封装实现。未取得指定PHY规范时，不应编造“只能几毫米”统一硬上限。扩大栈数还受到中介层面积、良率、供电、PHY边缘空间和散热约束；这些约束不会仅因加入无源波导而消失。

## 3. 1024位为何不等于1024根光波导

数据位宽描述并行电接口；光链路通过串行化、编码和WDM重新组织数据。设单向净数据率D，每波长线路速率r，每纤W波长，有效载荷效率η，则理论信号纤下界为：

`Nsignal ≥ ceil[D/(r·W·η)]`。

这不是完整BOM：收发分纤、冗余、时钟、外部激光供光、分区与连接器均可能增加数量。接口时序和协议兼容也不由带宽等式保证。

**人为计算示例：** 若D=1.2 TB/s=9.6 Tb/s，r=100 Gb/s，W=8，η=0.8，则至少15根单向信号纤；W=1时为120根。这些是假设，不是可量产HBM光接口，目的是证明物理纤数并不由1024位唯一确定。

Intel的真实演示提供了更直接的口径例子：64个32 Gb/s通道/方向，经8条纤、每纤8波长承载；双向8对纤。每方向2.048 Tb/s，双向合计4.096 Tb/s，厂商简称4 Tb/s。[IntelOCI2024] “64通道”在此不能替换成“64根独立波导”。

## 4. 各互联层级必须分开

| 场景 | 常见机制 | 本次可核实指标例子 | 对玻璃Shuffle的关系 |
|---|---|---|---|
| GPU—HBM封装内 | 专用HBM电接口 | 单栈带宽见上表 | 不是透明替换对象 |
| CPU—GPU板／系统内 | PCIe、平台专用链路 | PCIe5 x16：编码后单向约63.0 GB/s，实际负载更低 | 光化还需PHY／retimer／协议实现 |
| GPU—GPU scale-up | NVLink及NVSwitch | H100 18 links，总900 GB/s双向 | 当前不能假设全部光化 |
| GPU集群scale-out | Ethernet／InfiniBand及收发器 | 需按具体速率、lane与光模块核算 | 固定lane重排的直接候选 |
| CPU—内存扩容／池化 | CXL.mem及交换系统 | CXL4.0于2025-11发布，128 GT/s | 协议可由光底层支持，但不是无源玻璃自带能力 |
| 光I/O chiplet | EIC/PIC、WDM、外部或集成光源 | Intel OCI见上节，最长100 m演示定位 | 可承担芯片至外部阵列间的固定光路 |

[PCIE5][HopperGuide][CXL4][IntelOCI2024]

PCIe 32 GT/s是每lane传输率，不是GB/s。x16按128b/130b计算：`32×16×128/130/8≈63.015 GB/s`单向。双向相加约126.03 GB/s还未扣分组开销。NVLink900 GB/s为双向汇总，HBM的TB/s又是内存接口口径，不能把三个数字放在一张不标方向的“速度排名”图里。

截至访问日NVIDIA官网给Hopper/Blackwell/Rubin每GPU双向NVLink分别900/1800/3000 GB/s，且表有初步规格提示；Rubin产品页内存带宽19.2 TB/s，区别于2026年1月CES稿的22 TB/s与3.6 TB/s NVLink。[NVLinkCurrent][RubinCurrent] 建议答辩优先用稳定历史SKU作为例子，使用滚动页面时附访问日期和截图。

无源波导本身没有逐比特开关驱动，不意味着整个光链路能耗为零。Intel所报5 pJ/bit属于其co-packaged方案口径；如果不知道激光、温控、FEC及有效负载边界，不宜据此断言优于任意铜链路。[IntelOCI2024]

## 5. CPO、光中介层、光背板分别是什么

CPO把光引擎移近交换／计算ASIC，以缩短高速电走线；光中介层可以承担封装内光学连接；光背板连接板卡或模块。三者既可能使用玻璃、聚合物、光纤或混合结构，也可能同时包含电路与光路。工艺材料并不决定协议和网络功能。

对于本课题，最可检验的问题是：给定光引擎和前面板的阵列坐标与纤序，能否产生低违规、光预算可接受的固定三维重排；不是设计完整CPU—GPU一致性互联。

## 6. 内存池化与存算分离：支持与反证

内存扩容是给一台主机增加可寻址容量；池化是把容量资源按需分配给主机；共享允许多个主机访问同一资源。是否缓存一致、是否跨交换机、是否允许细粒度动态共享取决于标准代际与系统实现。[CXLIntro2023]

Pond采用8—16 socket小池、工作负载识别和本地／池内存分层放置，在其158种工作负载评估条件下给出DRAM成本约降7%、相对同NUMA节点性能差1—5%。文中额外70—90 ns等硬件模型条件必须一起引用。[Pond2023, §4.1、Fig.7–8、§6]

Google的 A Case Against CXL Memory Pooling 则强调：DIMM容量离散、CXL交换／配线额外成本、软件复杂度和既有调度优化，可能使DRAM节约无法转化为总成本收益。[AgainstCXL2023, §3–5] 两文工作负载、价格和实现假设不同；反证不等于所有CXL无用，支持结果也不证明光解耦普遍经济。

Spark SQL案例发现特定分析任务的带宽需求可能由当时网络满足，但不能推广到随机依赖访问或GPU—HBM。[Rao2016] 早期光内存经济模型也提醒需比较容量利用率收益和网络费用，2015价格不能作为2026报价。[Abali2015]

## 7. 光传播到底占多少时延

分解：`Tremote = Tcontroller + Tserialization + TE/O + Tflight + Tswitch/queue + TO/E + Tprotocol + TDRAM`。往返访问还需在对应方向计入返回和请求；不要把只有数据路径的测量写成完整load-to-use延迟。

假设群折射率ng=1.5，则`Tflight≈ngL/c≈5 ns/m`单程，1/10/100 m分别约5/50/500 ns，往返传播约10/100/1000 ns。此为理论估算，ng不是本项目测量值。厘米玻璃内几何优化对总体远端访问延迟通常只影响很小一项，不能消除协议和DRAM时延。

指针追逐、依赖load、缓存未命中串行链更敏感；可预取、批处理、大块DMA、带宽受限且并发高的任务可能更适合远端访问。光可缓解长距离高速电链路损耗和带宽密度，但距离本身仍增加飞行时间。

## 8. 两篇直接光内存研究的准确使用

**Ou等2025多栈光HBM：** 保留传统HBM结构，以EIC/PIC和CPO构成多栈模块。论文设计6组EIC/PIC、每组48根纤，共288根（含供光、TX、RX），并以LLMCompass做性能建模；没有制造光HBM封装，也不是1024根玻璃路径实验。[OptHBM2025, §II–III、Fig.2–6] 它证明相关架构有人研究，同时说明本课题若要直接服务该场景，必须拿到具体端口与封装约束。

**OCM2022：** 传统DDR DRAM、SerDes和WDM构成光连接内存；4个DDR4通道用2根纤承载。系统性能和1.02 pJ/bit能耗为模型结果，对照是论文设定的远端网络方案，不能读成相对本地HBM的实测提升。[OCM2022, §3、Fig.3、§4.2–4.3]

## 9. 最终适用性矩阵

| 候选应用 | 当前判断 | 决定性缺口 |
|---|---|---|
| 直接取代GPU—HBM PHY | 不适合作为当前直接应用 | 缺主动器件、协议和时序、功耗、散热及封装验证 |
| 光HBM模块内固定扇出 | 未来候选 | 缺真实BOM、端口、目标波长和光预算 |
| GPU集群网络Shuffle | 最可信应用方向之一 | 需明确方向、lane/纤/WDM口径、服务与换件边界 |
| 机箱光背板／CPO前板重排 | 适合固定拓扑研究 | 需与成熟光纤／optical-flex同条件对照 |
| 跨机架长距离主体传输 | 光纤更合理 | 玻璃芯片只适合局部互联，不能替代长距离柔性走缆 |
| 按负载实时重构内存池 | 无源玻璃单独不能完成 | 需CXL／光开关及控制系统 |

最可信的千级**物理**通道依据来自高密度CPO/Shuffle资料，而不是HBM位宽。课题价值应聚焦固定互联设计工具，保留面向未来光计算封装的接口扩展可能。

## 本文引用来源

完整作者、卷期、DOI及访问边界见10与11文件；下面给原始来源快捷链接。

- [OptHBM2025: Optically Connected Multi-Stack HBM Modules for Large Language Model Training and Inference](https://doi.org/10.1109/LCA.2025.3540058)（2025；访问A）
- [SamsungHBM2E: Samsung to Advance High Performance Computing Systems with Launch of Industry’s First 3rd-generation (16GB) HBM2E](https://news.samsung.com/global/samsung-to-advance-high-performance-computing-systems-with-launch-of-industrys-first-3rd-generation-16gb-hbm2e)（2020；访问B）
- [SKHBM3: First Movers on a Path That No-one Has Taken Before: Meet the Engineers Leading the World’s First Mass-production of HBM3](https://news.skhynix.com/en/meet-the-engineers-leading-the-worlds-first-mass-production-of-hbm3/)（2022；访问B）
- [MicronHBM3E: HBM3E](https://www.micron.com/products/memory/hbm/hbm3e)（未署年；访问B）
- [JEDECHBM4: JEDEC and Industry Leaders Collaborate to Release JESD270-4 HBM4 Standard](https://www.jedec.org/news/pressreleases/jedec%C2%AE-and-industry-leaders-collaborate-release-jesd270-4-hbm4-standard-advancing)（2025；访问C）
- [MicronHBM4: Micron in High-Volume Production of HBM4 Designed for NVIDIA Vera Rubin, PCIe Gen6 SSD and SOCAMM2](https://micron.gcs-web.com/news-releases/news-release-details/micron-high-volume-production-hbm4-designed-nvidia-vera-rubin)（2026；访问B）
- [JEDECSPHBM4: New JEDEC SPHBM4 Standard Enables HBM4-Class Bandwidth on Organic Substrates](https://www.jedec.org/)（2026；访问C）
- [IntelOCI2024: Intel Demonstrates First Fully Integrated Optical I/O Chiplet](https://www.intel.com/content/www/us/en/newsroom/news/intel-unveils-first-integrated-optical-io-chiplet.html)（2024；访问B）
- [PCIE5: PCIe Compliance Updates](https://pcisig.com/developer/education/pcie-compliance-updates-16)（未署年；访问B）
- [HopperGuide: NVIDIA Hopper Tuning Guide](https://docs.nvidia.com/cuda/hopper-tuning-guide/)（未署年；访问B）
- [CXL4: CXL Consortium Releases the Compute Express Link 4.0 Specification Increasing Speed and Bandwidth](https://computeexpresslink.org/wp-content/uploads/2025/11/CXL_4.0-Specification-Release_FINAL_Website-Copy.pdf)（2025；访问B）
- [NVLinkCurrent: NVIDIA NVLink and NVLink Switch](https://www.nvidia.com/en-us/data-center/nvlink/)（未署年；访问B）
- [RubinCurrent: NVIDIA Vera Rubin NVL72](https://www.nvidia.com/en-us/data-center/vera-rubin-nvl72/)（未署年；访问B）
- [CXLIntro2023: An Introduction to the Compute Express Link (CXL) Interconnect](https://arxiv.org/abs/2306.11227)（2023；访问A）
- [Pond2023: Pond: CXL-Based Memory Pooling Systems for Cloud Platforms](https://doi.org/10.1145/3575693.3578835)（2023；访问A）
- [AgainstCXL2023: A Case Against CXL Memory Pooling](https://doi.org/10.1145/3626111.3628195)（2023；访问A）
- [Rao2016: Is Memory Disaggregation Feasible?: A Case Study with Spark SQL](https://doi.org/10.1145/2881025.2881030)（2016；访问A）
- [Abali2015: Disaggregated and optically interconnected memory: when will it be cost effective?](https://arxiv.org/abs/1503.01416)（2015；访问C+）
- [OCM2022: Optically connected memory for disaggregated data centers](https://doi.org/10.1016/j.jpdc.2022.01.013)（2022；访问A）
