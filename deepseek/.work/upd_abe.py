# -*- coding: utf-8 -*-
p = 'docs/research/05_Research_Motivation.md'
t = open(p, encoding='utf-8').read()
orig = t

anchor = '| Ling 等 2021（OFC） | 自动三维波导布线算法用于多芯光纤扇入扇出（通道数未在摘要报告） | 实验演示（仅摘要） | 【B】DOI 10.1364/OFC.2021.Th1A.37 |'
new = ('| Abe 2005（IEICE） | 面向 >10,000 芯的 scalable optical fiber wiring system，实际构建 **16,384 芯**光纤 shuffler（64 张 256 芯 fiber sheet + 16 芯 FPC 连接器） | 系统演示（仅摘要） | 【B】DOI 10.1093/ietele/e88-c.8.1755 |\n'
       '| Jiang 等 2021（IEICE） | 面向 **>1,000 端口**光矩阵开关的三维波导 shuffle converter（串扰 <−54.2 dB、插损 2.1 dB） | 原理器件（仅摘要） | 【B】DOI 10.1587/transele.2020ECS6002 |\n'
       + anchor)
assert anchor in t
t = t.replace(anchor, new, 1)

old = '2. 玻璃波导器件已实现 >1024 波导互连【B】；'
new2 = '2. 玻璃波导器件已实现 >1024 波导互连【B】；光纤固定布线系统更已达到 **16,384 芯** shuffler 的规模（Abe 2005【B】）；三维波导 shuffle converter 已把 **>1,000 端口**作为明确目标（Jiang 2021【B】）；'
assert old in t
t = t.replace(old, new2, 1)
open(p, 'w', encoding='utf-8').write(t)
print('05 updated:', len(orig), '->', len(t))

p11 = 'docs/research/11_Evidence_Ledger.md'
t11 = open(p11, encoding='utf-8').read()
o11 = t11
a = '| E-OCS-13 | 全光纤自动配线架（automated patch-panel）原型 140×140 | JLT 2009 论文 | 10.1109/JLT.2008.2006280 | 摘要 | 全光纤交叉连接 | 说明「机器人/机械式自动配线」路线存在 | **B** | 规模与切换时间未核实 |'
row17 = '| E-OCS-17 | 面向 >10,000 芯的 scalable 光纤布线系统，实际构建 **16,384 芯**光纤 shuffler（64×256 芯 sheet + 16 芯 FPC 连接器），用于 128×128 热光开关系统 | Abe, IEICE Trans. Electron. 2005 | 10.1093/ietele/e88-c.8.1755 | 摘要 | 光纤固定布线 | **固定拓扑布线的万芯级规模证据**——说明「置换本身」不是难点，光纤管理与连接器才是 | **B** | 全文未获取；实现年代较早 |'
row18 = '| E-OCS-18 | 面向 >1,000 端口光矩阵开关的三维波导 shuffle converter：串扰 <−54.2 dB、插损 2.1 dB | Jiang 等, IEICE Trans. Electron. 2021 | 10.1587/transele.2020ECS6002 | 摘要 | MCF/SMF 扇入扇出 | 与本项目最接近的「三维＋高端口＋交叉规避」学术工作（但为原理器件、非自动布线） | **B** | 全文未获取；规模/算法未报 |'
if a in t11:
    t11 = t11.replace(a, a + '\n' + row17 + '\n' + row18, 1)
else:
    # try to append after the E-OCS-13 row by looser match
    import re
    m = re.search(r'\| E-OCS-13 \|[^\n]*\n', t11)
    assert m, 'E-OCS-13 row not found'
    t11 = t11[:m.end()] + row17 + '\n' + row18 + '\n' + t11[m.end():]
open(p11, 'w', encoding='utf-8').write(t11)
print('11 updated:', len(o11), '->', len(t11))
