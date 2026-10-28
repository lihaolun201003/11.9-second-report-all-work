# 04 文件补充/修订清单（可直接粘贴 · 供 Lead 合并）

> 用途：对 `docs/research/04_Related_Work_Comparison.md`（20:21 定稿版）做最小必要补全。
> 所有新增 DOI 均于 2026-10-28 经 Crossref 直接核验（`api.crossref.org/works/<doi>`），题名/年/卷期页以下列返回值为准；摘要类证据另注来源。
> 配套核验报告：`.work/rw_citation_verification.md`；中间数据：`.work/rw_newrefs_crossref.json`、`.work/rw_04_crossref.json`。

---

## 一、必补文献（3 条，缺 1 条则 task-4 验收不通过）

### 1. [Urata2023] Google Apollo——OCS 大规模生产部署（**task-4 强制项，04 现缺**）

```
[Urata2023] R. Urata, H. Liu, K. Yasumura, E. Mao, J. Berger, X. Zhou, et al. Apollo: Large-Scale Deployment of Optical Circuit Switching for Datacenter Networking. Optical Fiber Communication Conference (OFC) 2023, 2023: M2G.1. DOI: 10.1364/OFC.2023.M2G.1（另有 IEEE 版 DOI 10.23919/OFC49934.2023.10116374, pp. 1–3）. 【核验：Crossref 双 DOI 均返回同一题名与作者；OpenAlex 摘要；全文未获取】
```

- 摘要原文（OpenAlex）："In this paper, we describe Apollo, to the best of our knowledge, the world's first large-scale production deployment of optical circuit switches (OCSes) for datacenter networking. We review the underlying hardware technologies including the design of our internally developed OCS and WDM transceivers."
- **用途**：补足 "Jupiter/Apollo" 系统证据链；与 Zhou 等的 *Apollo*（EPDA 布局）严格区分；支撑"固定光布线层的连接表来自网络拓扑工程"的论证。

### 2. [Yeary2023] 玻璃基板 CPO（102.4 Tb/s）

```
[Yeary2023] L. W. Yeary, L. Brusberg, C. Kim, S.-H. Seok, J. Noh, A. Rozenvax. Co-packaged Optics on Glass Substrates for 102.4 Tb/s Data Center Switches. 2023 IEEE 73rd Electronic Components and Technology Conference (ECTC), 2023: 224–227. DOI: 10.1109/ECTC51909.2023.00046. 【核验：Crossref + OpenAlex 摘要；全文未获取】
```

- 摘要要点：玻璃基板上用离子交换（IOX）波导实现光与电互连；5 层金属细线布线；TGV 供电/数据；玻璃波导与高密度 SiN 光 I/O 的倏逝耦合。**摘要只描述设计与应用场景，未见实测指标**——引用时不得写"已实现 102.4 Tb/s 传输"。
- **用途**：支撑 H1（1024 lane 量级系统需求）与 H10（玻璃与 CPO 封装兼容），并为"1024 通道不是凭空设定"提供数量级依据（102.4 Tb/s ÷ 100 Gb/s/lane ≈ 1024 lane，属**推算**【估算】）。

### 3. [Skryabin2024] fs 直写低损耗多扫描波导（0.07 dB/cm + 0.2 dB/facet + 25 通道干涉仪）

```
[Skryabin2024] N. N. Skryabin, S. A. Zhuravitskii, I. V. Dyakonov, S. S. Straupe, A. A. Kalinkin, S. P. Kulik. Femtosecond-laser-written low-loss multiscan waveguides in fused silica. Physical Review Applied, 2024, 22(6): 064079. DOI: 10.1103/PhysRevApplied.22.064079. 【核验：Crossref + arXiv:2408.06688 全文；全文】
```

- 全文关键数据（arXiv 2408.06688）：传播损耗 **0.07 dB/cm**；与标准单模光纤模场重叠 >98.8%、耦合损耗平均 **0.2 dB/facet**；**25 通道**光纤耦合干涉仪总插入损耗 **<1 dB**；写入速度 1–6 mm/s。
- **用途**：H4（低损耗可实现）的最强证据之一；同时为"25 通道级器件现有实测"提供量级；与 04 已引 [Tan2022]（同为 0.07 dB/cm）形成两独立来源。

---

## 二、建议补文献（10 条，提升证据密度）

```
[Davis1996] K. M. Davis, K. Miura, N. Sugimoto, K. Hirao. Writing waveguides in glass with a femtosecond laser. Optics Letters, 1996, 21(21): 1729–1731. DOI: 10.1364/OL.21.001729. 【核验：Crossref + OpenAlex 摘要；摘要】

[Gattass2008] R. R. Gattass, E. Mazur. Femtosecond laser micromachining in transparent materials. Nature Photonics, 2008, 2(4): 219–225. DOI: 10.1038/nphoton.2008.47. 【核验：Crossref；题录（OpenAlex 无摘要）】

[HipoLaos2020] G. Giamougiannis, A. Tsakyridis, N. Terzenidis, D. Spasopoulos, C. Vagionas, N. Pleros. Demonstration of Low-Latency ETH-switched DataCenter and 5G Fronthaul Networks Using the 1024-port Hipoλaos Optical Packet Switch. European Conference on Optical Communication (ECOC) 2020, 2020: 1–4. DOI: 10.1109/ECOC48923.2020.9333177. 【核验：Crossref + OpenAlex 摘要；摘要】

[Dai2022] Z. Dai, J. Xiong, L. Ma, Z. He. Low-Loss and Low-Crosstalk Fan-in/Fan-out Device for Multicore Fiber Using a Femtosecond Laser Direct Inscription Technique. 2022 20th International Conference on Optical Communications and Networks (ICOCN), 2022: 1–2. DOI: 10.1109/ICOCN55511.2022.9901157. 【核验：Crossref + OpenAlex 摘要；摘要】

[YuOFC2025] F. Yu, L. Ma, J. Xiong, L. Bai, M. Xu, Z. He. Low-loss Fan-in/Fan-out Device for Coupled four-core Fiber Using a Femtosecond Laser Direct Inscription Technique. Optical Fiber Communication Conference (OFC) 2025, 2025: M4J.5. DOI: 10.1364/OFC.2025.M4J.5. 【核验：Crossref + OpenAlex 摘要；摘要】

[Thomson2011] R. R. Thomson, T. A. Birks, S. G. Leon-Saval, A. K. Kar, J. Bland-Hawthorn. Ultrafast laser inscription of an integrated photonic lantern. Optics Express, 2011, 19(6): 5698. DOI: 10.1364/OE.19.005698. 【核验：Crossref + OpenAlex 摘要；摘要】

[Tan2021] D. Tan, Z. Wang, B. Xu, J. Qiu. Photonic circuits written by femtosecond laser in glass: improved fabrication and recent progress in photonic devices. Advanced Photonics, 2021, 3(2): 024002. DOI: 10.1117/1.AP.3.2.024002. 【核验：Crossref + OpenAlex 摘要；摘要】

[Choudhury2014] D. Choudhury, J. R. Macdonald, A. K. Kar. Ultrafast laser inscription: perspectives on future integrated applications. Laser & Photonics Reviews, 2014, 8(6): 827–846. DOI: 10.1002/lpor.201300195. 【核验：Crossref + OpenAlex 摘要；摘要】

[Suganuma2015] D. Suganuma, T. Ishigure. Fan-in/out polymer optical waveguide for a multicore fiber fabricated using the Mosquito method. Optics Express, 2015, 23(2): 1585. DOI: 10.1364/OE.23.001585. 【核验：Crossref + OpenAlex 摘要；摘要】

[Lindenmann2015] N. Lindenmann, S. Dottermusch, M. L. Goedecke, T. Hoose, M. R. Billah, T. Onanuga, et al. Connecting Silicon Photonic Circuits to Multicore Fibers by Photonic Wire Bonding. Journal of Lightwave Technology, 2015, 33(4): 755–760. DOI: 10.1109/JLT.2014.2373051. 【核验：Crossref + OpenAlex 摘要；摘要】
```

**逐条用途**：
- Davis1996：fs 直写玻璃波导的起点（Δn 0.01–0.035），用于技术史与"为何 30 年后才谈自动设计"。
- Gattass2008：fs 微加工权威综述（题录级），用于技术路线引证。
- HipoLaos2020：**1,024 端口**光分组交换、10 Gb/s/端口、真实 DC/5G 前传测试床——"1024 端口"的独立系统证据（注意：**端口数≠波导数**）。
- Dai2022：fs 直写 3 芯 FI/FO，平均插损 1.33 dB、串扰 <−49 dB——细粒度器件实测。
- YuOFC2025：与 04 的 [Yu2025/2026]（仅题录）同一课题组，**摘要可得**：19 µm 芯距耦合四芯光纤 FI/FO，平均插损 0.49 dB（封装前）/0.92 dB（封装后）——可替代仅题录条目承担定量论证。
- Thomson2011：fs 直写 3D 光子灯笼（多模→2D 单模阵列），总插损 5.7 dB、模式耦合损耗约 0.7 dB——3D 扇出器件的另一种实现。
- Tan2021：fs 直写玻璃光子电路工艺改进综述（0.07 dB/cm 等"低损耗配方"脉络）。
- Choudhury2014：ULI 综述，给出三类波导截面架构与选择性刻蚀，供 §2.2 综述段引用。
- Suganuma2015：Mosquito 法 7 芯聚合物 FI/FO，10 cm 长最小插损 5.26 dB@850 nm——聚合物 FI/FO 的对照数据。
- Lindenmann2015：光子引线键合连 4 芯 MCF，耦合损耗低至 1.7 dB——引线键合从"概念"到"器件"的补充。

---

## 三、须修订的既有条目（4 条，old → new）

### 3.1 [Yu2025] → [Yu2026]（年份与标签统一）

将 04 中的标签与正文统一如下（**原文两处：§1.1 表"Yu 等 2025"、§2 开头"Yu 等（2025，仅题录）"、文献 [Yu2025]**）：

```
[Yu2026] F. Yu, L. Ma, L. Bai, J. Xiong, M. Xu, X. Chen, Z. He. Fully-assembled low-loss fan-in/fan-out device by laser direct writing for coupled-core fiber. Optics & Laser Technology, 2026, 194: 114521（在线发表 2025）. DOI: 10.1016/j.optlastec.2025.114521. 【核验：Crossref 元数据（issued 2026）；摘要与全文均未获取（Elsevier captcha），仅题录】
```
正文统一写"Yu 等（2026，在线 2025）"。

### 3.2 [Weigel2024]（表内年份 2023 → 2024）

04 表内与 §2.3 写"Weigel 等 2023"，文献条目写 2024。Crossref issued=**2024**（JLT 42(5): 1511–1517，early access 2023）。统一为"2024（early access 2023）"或直接"2024"。

### 3.3 [Nash2010]（删除过时备注）

04 原文："【核验：OpenAlex+DOI 解析（Crossref 未收录该 DOI 记录）；摘要】"。
**本次核验：Crossref `works/10.1613/jair.2994` 正常返回（JAIR, 2010, 39: 533–579）。** 改为：

```
[Nash2010] K. Daniel, A. Nash, S. Koenig, A. Felner. Theta*: Any-Angle Path Planning on Grids. Journal of Artificial Intelligence Research, 2010, 39: 533–579. DOI: 10.1613/jair.2994. 【核验：Crossref + OpenAlex；摘要】
```

### 3.4 [Zhou2025b]（标【摘要】→【全文】，并补规模数据）

04 标【摘要】偏低：arXiv:2505.17239 全文可获取。建议改为：

```
[Zhou2025b] H. Zhou, H. Yang, Z. Yin, N. W. Gangi, Z. Huang, H. M. Ren, et al. LiDAR 2.0: Hierarchical Curvy Waveguide Detailed Routing for Large-Scale Photonic Integrated Circuits. IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems, 2026, 45(6): 2664–2678（2025 年在线发表）. DOI: 10.1109/TCAD.2025.3624197. 【核验：Crossref + arXiv:2505.17239 全文；全文】
```
并可补数据：compact 基准最大 **TeMPO_32×32_C 8,195 net**、**Benes_32×32_C 1,024 net**；Benes_32×32 运行时间 **LiDAR 2.0 246 s vs PROTON 5,111 s**；相比 LiDAR 1.0 最高 **16% 插损降幅、7.69× 加速**（spacious 基准）；评测机 AMD EPYC 7763/512 GB。

---

## 四、三处"严重问题"的替换文本

### 4.1 替换 S1（规模表述）

**04 §1.3 观察一原文**：
> "……而自动布线文献的最大规模停在 446 net（LiDAR）与 512 条多模波导（Huang）。"

**建议替换为**：
> "……而自动布线文献的规模记录是分层的：LiDAR 1.0（ISPD 2025）的最大 spacious 基准为 446 net，LiDAR 2.0（TCAD 2026）已把评测扩展到 compact 基准 **8,195 net（TeMPO_32×32_C）**，其中 **Benes_32×32_C 恰为 1,024 net**、416 个逻辑交叉；Huang 等（2020）在板级实现 512 条多模波导自动布局。也就是说，**二维单层自动布线在基准层面已经到达 1,024 net 量级**——本项目若把'规模'作为新颖性论据，将被这一事实直接反驳；规模只能作为**压力测试目标**，而不能作为创新点。"

**04 §2.4 LiDAR 段原文**：
> "……基准最大 446 net、13×6.4 mm²、0.2 µm 网格，1204 s 完成且零设计规则违例……"

**建议替换为**：
> "……LiDAR 1.0 的最大 spacious 基准为 ADEPT_32×32（446 net、13×6.4 mm²、0.2 µm 网格），用时 1,204 s（Python+GDSFactory，i5-125600KF 3.7 GHz/32 GB）且零设计规则违例；LiDAR 2.0 进一步把基准扩展到 TeMPO_32×32_C 的 8,195 net 与 Benes_32×32_C 的 1,024 net，并用分层布线把 Benes_32×32 的运行时间从 PROTON 的 5,111 s 降到 246 s……"

### 4.2 替换 S2（Corning 证据边界）

**04 §3.1 原文**：
> "此外，Corning 的 1024 通道论文通篇未提布线自动化，但这只是'未记载'，不能据此推断其产线依靠人工。"

**建议替换为**：
> "此外，Corning 的 1024 通道论文（Brusberg 等, 2025）**全文未获取，其可获取摘要未提及布线自动化**；'未记载'既不能证明其产线依靠人工，也不能证明其没有内部自动化流程。"

### 4.3 补 S3（Google Apollo：新增段落 + 总表行）

**在 §2.5 末尾新增一段**：
> **Urata 等（2023，Google）【摘要】** 报道 Google 对其自研 MEMS OCS 与 WDM 收发器的硬件技术，并称 Apollo 是"据我们所知，全球首个面向数据中心网络的大规模 OCS 生产部署"。该文给出的是系统级（机架/网络层）量产证据，不涉及玻璃波导几何；其价值有二：一是 OCS 已从研究原型走到生产网络，"固定光布线层 + 可重构交换层"的分工被工业界接受；二是它从需求侧证明连接表会随网络扩容与拓扑工程变化，从而支撑"同一台设备要能处理多张连接表"的设计目标。**注意与 Zhou 等（2025）的 Apollo（EPDA 布局工具）区分：二者同名不同工作，本文一律以"Apollo-OCS"与"Apollo-EPDA"指代。** 全文未获取，只能引用摘要级结论。

**在 §1.1 总表末尾（Poutievski 行之后）新增一行**：

| Urata 等 2023（Apollo-OCS） | Google | 光纤 | MEMS OCS＋WDM 收发器 | OCS 端口规模未报（同期 Jupiter 为 136×136） | 2D（自由空间交换） | 无（系统部署，不生成波导几何） | 不适用 | 未报 | 是（大规模生产部署，摘要级） | 全文未获取；不含波导/布线内容 | 系统侧需求证据；与 Apollo-EPDA 区分 |

---

## 五、可补入正文的定量增强（已有文献，不新增 DOI）

1. **[Grenier2023]**：摘要与全文均报告，被动对准 MPO 相比主动对准使耦合损耗"平均增加 0.19 dB"——可作为"封装对准容差代价"的量化锚点（全文 Frontiers 可获取）。
2. **[Blaicher2020]**：除 448 Gbit/s / 732.7 Gbit/s 外，摘要报告**自动化量产的光子引线键合插损 (0.7 ± 0.15) dB**，并通过环境稳定性与高光功率测试——可支撑"三维自由曲面互连已具备量产级一致性"。
3. **[LiDAR 2.0]**：Table V 的损耗系数：传播 1.5 dB/cm、90° 弯曲 0.005 dB、交叉 0.52 dB——04 已用，可补"这些是**器件参数表**而非拟合模型"的限定。
4. **[Zhang2025]**：全文（UGent 作者版）明确该方法**仅适用于二维晶圆平面**且为 grid-less；可补"其零交叉性依赖收发组构成环路的平面图假设（每个 component 为环）"——说明该方法不能直接处理任意置换网表。
5. **[Charles2012]**：全文（arXiv 1209.5144）给出三个对本项目极关键的工艺约束：①波导最小间距 **30 µm**；②受物镜工作距离限制的可用深度约 **450 µm**；③激光不能穿过已改性区域，故必须**由深到浅顺序写入**，且任意两条波导不能在两处同时上下穿越。**建议把这三条写入 §3.9 或 §4.2**，因为它们直接构成"三维布线算法必须内建的工艺约束"，也是本项目区别于纯几何路径规划的理由。
6. **[Nasu2005]**：过量损耗 2.7/2.8 dB 是"2000 µm 跨接"的总过量损耗，不宜解释为"每个交叉 2.7 dB"；正文引用时须带"（含耦合与传播）"限定。

---

## 六、引用格式与核验记录

- 所有新增 DOI 均在 2026-10-28 通过 `https://api.crossref.org/works/<doi>` 核验，返回的题名/年/卷期页已写入条目；摘要级证据来自 OpenAlex `abstract_inverted_index` 重建或 arXiv/Frontiers/Optica 页面原文。
- 具体核验输出存于：`.work/rw_newrefs_crossref.json`（13 条新增/补充）、`.work/rw_04_crossref.json`（04 既有 41 条）。
- 未获取全文的条目：Urata2023（OFC 付费墙）、Yeary2023（IEEE 付费墙）、Gattass2008（无摘要）、Yu2026（Elsevier captcha），均已在条目中标注。
