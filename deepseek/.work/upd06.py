# -*- coding: utf-8 -*-
p = 'docs/research/06_Thesis_Chapter_1_Draft.md'
t = open(p, encoding='utf-8').read()
orig = t

# 1) add paragraph on 3D auto-routing precedents after the inference paragraph in 1.2.2
anchor = '【推理】因此，"玻璃 + 飞秒直写"这一技术路线的价值并不在于全面优于 IOX，而在于：当连接拓扑需要真三维自由度（跨层、任意深度、复杂扇出）且批量不大时，FsDLW 能提供 IOX 难以给出的设计自由度；而要把这种自由度用起来，必须有与之匹配的**自动布线工具**。'
add = anchor + '''

**（3）三维自动布线的已有先例。** 必须指出，"把三维几何自动生成出来"并非完全空白：Ling、Yuan 与 Yoo 在 OFC 2021 报道了用于多芯光纤集成的低损耗三维扇入扇出器件，其摘要明确说明该器件由**自动三维波导布线算法（automatic 3D waveguide routing algorithm）**制作，两种玻璃中的传播损耗分别为 0.3 dB/cm 与 0.16 dB/cm [Ling 等, 2021]；Hamamoto 等则提出用三维波导 Shuffle 转换器把多芯光纤/单模光纤扇入扇出结构推向**超过 1,000 端口**的目标，并给出原理器件的 2.1 dB 插损与低于 −57.4 dB 的串扰 [Hamamoto 等, 2018]。此外，二维平面内的自动布线已相当成熟：从 PROTON、PlanarONoC、ToPro 到 LiDAR（446 net、零设计规则违例、插损降低约 14%），形成了"曲率感知 A*＋交叉/间距/弯曲半径约束"的完整方法链 [Zhou 等, 2025]。因此，本领域真正的空白不是"三维自动布线"这一概念本身，而是**面向 1024 通道规模、支持通用连接表、并同时纳入光波导物理评价与加工时间评估的集成工具链**。Ling 等工作的全文尚未获取，其算法是否为通用约束求解，是本课题新颖性论证中最需要核实的文献（见 12 文件）。'''
assert anchor in t
t = t.replace(anchor, add, 1)

# 2) update summary table
old_eda = '| 光子 EDA | 器件仿真、平面/多层版图、DRC、链路预算工具成熟 | 大尺寸真三维 + 飞秒直写约束的自动布线未见公开工具 |'
new_rows = ('| 光子 EDA | 器件仿真、平面/多层版图、DRC、链路预算工具成熟 | 大尺寸真三维 + 飞秒直写约束的自动布线未见公开工具 |\n'
            '| 自动布线 | 二维曲率感知布线已工程化（LiDAR 2025，446 net）；三维布线有专用先例（Ling 2021，MCF 扇出） | 1024 通道、通用连接表、多物理约束、含加工时间评估的集成工具链未见公开 |')
assert old_eda in t
t = t.replace(old_eda, new_rows, 1)

# 3) revise problem 2
old2 = '**问题 2：现有光布线方法以平面/有限层为主，三维物理约束纳入不足。** 光子 EDA 的波导布线通常面向平面 PIC 或有限层数；飞秒直写的真三维自由度（任意深度、跨层、S 形过渡）尚未被现有工具以"曲率连续 + 最小间距 + 交叉规避 + 深度相关损耗"的统一形式建模。'
new2 = '**问题 2：三维布线已有先例，但物理约束与规模受限。** 二维曲率感知自动布线已经工程化（如 LiDAR 的 446 net 级布线）[Zhou 等, 2025]，三维自动布线也已有专用先例（Ling 等 2021 的 MCF 扇入扇出）[Ling 等, 2021]；但这些工作要么面向平面 SOI 平台、要么面向规则扇出几何，飞秒直写的真三维自由度（任意深度、跨层、S 形过渡）尚未被以"曲率连续 + 最小间距 + 交叉规避 + 深度相关损耗 + 加工时间"的统一形式建模，且未见 10³ 通道规模的验证。'
assert old2 in t
t = t.replace(old2, new2, 1)

# 4) append new references after item 20
ref_anchor = '20. [DasSharma 等, 2024] D. Das Sharma, et al. An Introduction to the Compute Express Link (CXL) Interconnect. ACM Computing Surveys, 2024. DOI: 10.1145/3669900.'
refs_new = ref_anchor + '''
21. [Ling 等, 2021] Y.-C. Ling, S. Yuan, S. J. B. Yoo. Low-Loss Three-Dimensional Fan-in/Fan-out Devices for Multi-Core Fiber Integration. OFC 2021, Th1A.37. DOI: 10.1364/OFC.2021.Th1A.37. 【核验：Crossref+摘要；全文未获取】
22. [Hamamoto 等, 2018] Shuffle converter using 3D waveguide for MCF/SMF fan-in fan-out configuration toward over 1,000 port count. OECC 2018. DOI: 10.1109/OECC.2018.8730115. 【核验：Crossref+摘要】
23. [Zhou 等, 2025] H. Zhou, et al. LiDAR: Automated Curvy Waveguide Detailed Routing for Large-Scale Photonic Integrated Circuits. 2025. DOI: 10.1145/3698364.3705355. 【核验：Crossref+摘要】
24. [Brusberg 等, 2025]（同第 4 条，TCPMT 2025，>1024 波导互连与 optical waveguide shuffle）'''
assert ref_anchor in t
t = t.replace(ref_anchor, refs_new, 1)

open(p, 'w', encoding='utf-8').write(t)
print('06 updated OK. chars', len(orig), '->', len(t))
