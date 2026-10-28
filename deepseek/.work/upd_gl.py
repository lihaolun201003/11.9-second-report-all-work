# -*- coding: utf-8 -*-
import json

# ---- 1. clarify Yu papers in 11 ledger ----
p11 = 'docs/research/11_Evidence_Ledger.md'
t = open(p11, encoding='utf-8').read()
o = t
old = '| E-GL-09 | 激光直写多芯光纤扇入扇出器件（题录级，具体损耗未获取） | Yu et al., Opt. Laser Technol. 194:114521, 2026 | 10.1016/j.optlastec.2025.114521 | 题录 | 多芯光纤 | 相关度最高的近作之一 | **D**（摘要/全文均未获取） | 不得引用其任何数值 |'
new = ('| E-GL-09 | 激光直写多芯光纤扇入扇出器件（题录级，具体损耗未获取） | Yu et al., Opt. Laser Technol. 194:114521, 2026 | 10.1016/j.optlastec.2025.114521 | 题录 | 多芯光纤 | 相关度最高的近作之一 | **D**（摘要/全文均未获取） | 不得引用其任何数值 |\n'
 '| E-GL-11 | **注意：与 E-GL-09 是两篇不同论文**。同一团队 2026 年在 Advanced Photonics Research 报道超紧凑低损耗 3D 玻璃波导芯片：2.5×2.0 mm² footprint、1310 nm 插损 0.54 dB、传播损耗 **0.13 dB/cm**、耦合损耗 0.06 dB/端面、沟槽辅助 + 偏移辅助余弦弯曲 | Yu et al., Adv. Photonics Res., 2026 | 10.1002/adpr.70241 | 摘要 | 飞秒直写玻璃 | 03 文件引用的 0.13 dB/cm 来自**本条**，不是 E-GL-09（optlastec）；两者不可混淆 | **B** | 4 芯器件、通道数少、无自动布线 |')
assert old in t
t = t.replace(old, new, 1)

# ---- 2. Ansys/Zemax completion date verified by 03 (10-K) ----
old2 = '| E-EDA-02 | Ansys 于 2021 年宣布收购 Zemax（"Ansys to Acquire Zemax Pursuant to Definitive Acquisition Agreement"，2021-08-30）；完成日期待核 | Ansys 新闻稿（搜索索引）；Kirkland & Ellis 新闻（2021-09） | 见 03 文件核实结果 | — | 企业并购 | 同上 | **C**（完成日期未核实） | 需以 SEC 8-K/10-K 核实 |'
new2 = '| E-EDA-02 | Ansys 于 **2021-10-01 完成**收购 Zemax（交易金额约 4.115 亿美元）；收购宣布于 2021-08-30 | Ansys 10-K（2021 财年）；03 文件 §4.2 核实 | 见 03 文件 §4.2 | 10-K | 企业并购 | 说明光学仿真与 EDA 融合趋势 | **A**（SEC 10-K） | — |'
assert old2 in t
t = t.replace(old2, new2, 1)

open(p11, 'w', encoding='utf-8').write(t)
print('11 updated:', len(o), '->', len(t))

# ---- 3. update 12 Ansys item ----
p12 = 'docs/research/12_Open_Questions.md'
t12 = open(p12, encoding='utf-8').read()
o12 = t12
if 'Ansys 收购 Zemax 的完成日期' in t12:
    t12 = t12.replace('【待核实】Ansys 于 2021 年宣布收购 Zemax（2021-08-30 宣布）；完成日期待核', '【已核实】Ansys 于 2021-10-01 完成收购 Zemax（10-K，约 4.115 亿美元）')
open(p12, 'w', encoding='utf-8').write(t12)
print('12 checked:', len(o12), '->', len(t12))
