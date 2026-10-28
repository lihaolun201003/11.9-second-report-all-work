# -*- coding: utf-8 -*-
"""Merge relatedwork-researcher's verified corrections into 04 and refs."""
import json
import re

P = 'docs/research/04_Related_Work_Comparison.md'
t = open(P, encoding='utf-8').read()
orig = t

def rep(old, new, count=1):
    global t
    assert old in t, 'NOT FOUND: ' + old[:80]
    t = t.replace(old, new, count)

# ---- 1. §1.3 观察一: fix the scale statement ----
rep('而自动布线文献的最大规模停在 446 net（LiDAR）与 512 条多模波导（Huang）。两组数字之间横着一条**"有规模、无自动化"与"有自动化、无三维规模"的裂缝**——这正是本项目可能的落点，但需要证明裂缝真实存在而非检索偏差。',
    '而自动布线文献的规模记录是分层的：LiDAR 1.0（ISPD 2025）的最大 spacious 基准为 446 net，**LiDAR 2.0（TCAD 2026）已把评测扩展到 compact 基准 8,195 net（TeMPO_32×32_C），其中 Benes_32×32_C 恰为 1,024 net**；Huang 等（2020）在板级实现 512 条多模波导自动布局。也就是说，**二维单层自动布线在基准层面已经到达 1,024 net 量级**——本项目若把"规模"作为新颖性论据，将被这一事实直接反驳；规模只能作为**压力测试目标**，而不能作为创新点。真正的裂缝是：**有 1024 规模但无三维/玻璃平台，或有三维几何但无自动布线**。')

# ---- 2. §1.2(1) channel-count trap mention of 446 net ----
rep('布线网表数（LiDAR 的 446 net）', '布线网表数（LiDAR 1.0 的 446 net、LiDAR 2.0 的 8,195 net／Benes 基准 1,024 net）')

# ---- 3. table rows: Yu 2025 -> 2026, Weigel 2023 -> 2024, Zhou row scale ----
rep('| Yu 等 2025 [Opt. Laser Technol.] |', '| Yu 等 2026（在线 2025）[Opt. Laser Technol.] |')
rep('| Weigel 等 2023 | Fraunhofer HHI |', '| Weigel 等 2024（early access 2023） | Fraunhofer HHI |')
rep('| Zhou 等 2025（LiDAR / LiDAR 2.0） | ASU/复旦 | SOI（设计） | 曲率感知 A* | 79–446 net |',
    '| Zhou 等 2025（LiDAR / LiDAR 2.0） | ASU/复旦 | SOI（设计） | 曲率感知 A* | 79–8,195 net（LiDAR 2.0；含 Benes 1,024 net） |')

# ---- 4. §2 开头 Yu 等（2025） ----
rep('覆盖表内除 Yu 等（2025，仅题录）之外的全部工作', '覆盖表内除 Yu 等（2026，在线 2025，仅题录）之外的全部工作')

# ---- 5. §2.4 LiDAR paragraph ----
rep('**Zhou 等（2025，LiDAR 与 LiDAR 2.0，ASU/复旦）【全文，arXiv 版＋摘要】** 作者称其为首个面向大规模 PIC 的详细布线器：网格化曲率感知 A*、自适应插入交叉、拥塞感知网序、插入损耗优化，并扩展为分层布线。基准最大 446 net、13×6.4 mm²、0.2 µm 网格，1204 s 完成且零设计规则违例，比 PROTON 类基线插损低 14%、快 6.25×。损耗取常数（传播 1.5 dB/cm、弯曲 0.005 dB、交叉 0.52 dB）；不建模串扰数值与制造时间；单层二维；基准由作者构造。它是本项目最直接的方法参照与对比基线。',
    '**Zhou 等（2025—2026，LiDAR 与 LiDAR 2.0，ASU/复旦）【全文，arXiv 版＋摘要】** 作者称其为首个面向大规模 PIC 的详细布线器：网格化曲率感知 A*、自适应插入交叉、拥塞感知网序、插入损耗优化，并扩展为分层布线。LiDAR 1.0 的最大 spacious 基准为 446 net、13×6.4 mm²、0.2 µm 网格，1,204 s 完成且零设计规则违例，比 PROTON 类基线插损低 14%、快 6.25×。**LiDAR 2.0（arXiv:2505.17239，TCAD 2026）进一步把评测扩展到 compact 基准 TeMPO_32×32_C 的 8,195 net 与 Benes_32×32_C 的 1,024 net，并用分层布线把 Benes_32×32 的运行时间从 PROTON 的 5,111 s 降到 246 s。** 损耗取常数（传播 1.5 dB/cm、弯曲 0.005 dB、交叉 0.52 dB）；不建模串扰数值与制造时间；单层二维；基准由作者构造。它是本项目最直接的方法参照与对比基线，也是"1024 规模本身不构成创新"的直接证据。')

# ---- 6. §3.1 evidence boundary "通篇" ----
rep('此外，Corning 的 1024 通道论文通篇未提布线自动化，但这只是"未记载"，不能据此推断其产线依靠人工。',
    '此外，Corning 的 1024 通道论文（Brusberg 等, 2025）**全文未获取，其可获取摘要未提及布线自动化**；"未记载"既不能证明其产线依靠人工，也不能证明其没有内部自动化流程。')

# ---- 7. §3.9 LiDAR timing reference ----
rep('**与实测对照**：LiDAR 在 446 net、13×6.4 mm²、0.2 µm 网格上用时 1204 s（Python 实现，i5-125600KF 工作站），约 2.7 s/net。按同一单位耗时外推，1024 net 约需 46 min；三维增加一个维度、曲率连续性与深度相关检查，保守放大 5–20 倍，得到 **4–15 h/网表**，与上面的独立估算同量级。',
    '**与实测对照**：LiDAR 1.0 在 446 net、13×6.4 mm²、0.2 µm 网格上用时 1,204 s（Python 实现，i5-125600KF 工作站），约 2.7 s/net；LiDAR 2.0 在 Benes_32×32_C（1,024 net）上用时 246 s（分层布线 + C++ 实现），说明**实现优化后 1024 net 的单层二维布线可在数分钟内完成**。本项目的外推应以此为上界参照：三维增加一个维度、曲率连续性与深度相关检查，并对 Python 原型取保守常数，保守放大 5–20 倍，仍可能落在 **20 min–4 h/网表** 区间；具体量级必须用本项目实现实测，不能照搬。')

# ---- 8. §4.1 "没有任何一篇…达到千级通道" needs qualification ----
rep('但在可获取文献中，**没有任何一篇同时覆盖上述四个环节并达到千级通道**。',
    '但在可获取文献中，**没有任何一篇在玻璃/三维平台上同时覆盖上述四个环节并达到千级通道**；二维单层平台已达到 1,024 net（LiDAR 2.0 的 Benes 基准），因此"千级通道"本身不是空白，"玻璃三维形态下的端到端工具链"才是。')

# ---- 9. §2.5 append Apollo-OCS paragraph ----
apollo_anchor = '### 2.5 需求侧：可重构网络与光纤 shuffle'
idx = t.find(apollo_anchor)
assert idx >= 0
# find the end of section 2.5 (next '## 3.' heading)
nxt = t.find('## 3. 能力空白检验', idx)
assert nxt > idx
apollo_para = ('\n**Urata 等（2023，Google）【摘要】** 报道 Google 自研 MEMS OCS 与 WDM 收发器的硬件技术，并称 Apollo 是"据我们所知，全球首个面向数据中心网络的大规模 OCS 生产部署"。该文给出的是系统级（机架/网络层）量产证据，不涉及玻璃波导几何；其价值有二：一是 OCS 已从研究原型走到生产网络，"固定光布线层 + 可重构交换层"的分工被工业界接受；二是它从需求侧证明连接表会随网络扩容与拓扑工程变化，从而支撑"同一套工具要能处理多张连接表"的设计目标。**注意与 Zhou 等（2025）的 Apollo（EPDA 布局工具）区分：二者同名不同工作，本文件一律以"Apollo-OCS"与"Apollo-EPDA"指代。** 全文未获取，只能引用摘要级结论。\n\n')
t = t[:nxt] + apollo_para + t[nxt:]

# ---- 10. references: fix labels/years ----
rep('[Yu2025] F. Yu, L. Ma, L. Bai, J. Xiong, M. Xu, X. Chen, Z. He. Fully-assembled low-loss fan-in/fan-out device by laser direct writing for coupled-core fiber. Optics & Laser Technology, 2026, 194: 114521. DOI: 10.1016/j.optlastec.2025.114521. 【核验：Crossref 元数据；仅题录（摘要与全文均未获取）】',
    '[Yu2026] F. Yu, L. Ma, L. Bai, J. Xiong, M. Xu, X. Chen, Z. He. Fully-assembled low-loss fan-in/fan-out device by laser direct writing for coupled-core fiber. Optics & Laser Technology, 2026, 194: 114521（在线发表 2025）. DOI: 10.1016/j.optlastec.2025.114521. 【核验：Crossref 元数据（issued 2026）；仅题录（摘要与全文均未获取）】')
rep('[Nash2010] K. Daniel, A. Nash, S. Koenig, A. Felner. Theta*: Any-Angle Path Planning on Grids. Journal of Artificial Intelligence Research, 2010, 39. DOI: 10.1613/jair.2994. 【核验：OpenAlex+DOI 解析（Crossref 未收录该 DOI 记录）；摘要】',
    '[Nash2010] K. Daniel, A. Nash, S. Koenig, A. Felner. Theta*: Any-Angle Path Planning on Grids. Journal of Artificial Intelligence Research, 2010, 39: 533–579. DOI: 10.1613/jair.2994. 【核验：Crossref + OpenAlex；摘要】')

# ---- 11. append new references before the "## 局限与待核实" heading ----
marker = '## 局限与待核实'
idx2 = t.rfind(marker)
assert idx2 > 0
new_refs = '''[Urata2023] R. Urata, H. Liu, K. Yasumura, E. Mao, J. Berger, X. Zhou, et al. Apollo: Large-Scale Deployment of Optical Circuit Switching for Datacenter Networking. Optical Fiber Communication Conference (OFC) 2023, 2023: M2G.1. DOI: 10.1364/OFC.2023.M2G.1（IEEE 版 DOI 10.23919/OFC49934.2023.10116374, pp. 1–3）. 【核验：Crossref 双 DOI + OpenAlex 摘要；全文未获取】

[Yeary2023] L. W. Yeary, L. Brusberg, C. Kim, S.-H. Seok, J. Noh, A. Rozenvax. Co-packaged Optics on Glass Substrates for 102.4 Tb/s Data Center Switches. 2023 IEEE 73rd Electronic Components and Technology Conference (ECTC), 2023: 224–227. DOI: 10.1109/ECTC51909.2023.00046. 【核验：Crossref + OpenAlex 摘要；全文未获取（摘要只描述设计与应用场景，未见实测指标）】

[Skryabin2024] N. N. Skryabin, S. A. Zhuravitskii, I. V. Dyakonov, S. S. Straupe, A. A. Kalinkin, S. P. Kulik. Femtosecond-laser-written low-loss multiscan waveguides in fused silica. Physical Review Applied, 2024, 22(6): 064079. DOI: 10.1103/PhysRevApplied.22.064079. 【核验：Crossref + arXiv:2408.06688 全文；全文（0.07 dB/cm、0.2 dB/facet、25 通道干涉仪总插损 <1 dB、写入速度 1–6 mm/s）】

[Davis1996] K. M. Davis, K. Miura, N. Sugimoto, K. Hirao. Writing waveguides in glass with a femtosecond laser. Optics Letters, 1996, 21(21): 1729–1731. DOI: 10.1364/OL.21.001729. 【核验：Crossref + OpenAlex 摘要】

[Gattass2008] R. R. Gattass, E. Mazur. Femtosecond laser micromachining in transparent materials. Nature Photonics, 2008, 2(4): 219–225. DOI: 10.1038/nphoton.2008.47. 【核验：Crossref；题录】

[HipoLaos2020] G. Giamougiannis, A. Tsakyridis, N. Terzenidis, D. Spasopoulos, C. Vagionas, N. Pleros. Demonstration of Low-Latency ETH-switched DataCenter and 5G Fronthaul Networks Using the 1024-port Hipoλaos Optical Packet Switch. ECOC 2020, 2020: 1–4. DOI: 10.1109/ECOC48923.2020.9333177. 【核验：Crossref + OpenAlex 摘要】

[Dai2022] Z. Dai, J. Xiong, L. Ma, Z. He. Low-Loss and Low-Crosstalk Fan-in/Fan-out Device for Multicore Fiber Using a Femtosecond Laser Direct Inscription Technique. ICOCN 2022, 2022: 1–2. DOI: 10.1109/ICOCN55511.2022.9901157. 【核验：Crossref + OpenAlex 摘要】

[YuOFC2025] F. Yu, L. Ma, J. Xiong, L. Bai, M. Xu, Z. He. Low-loss Fan-in/Fan-out Device for Coupled four-core Fiber Using a Femtosecond Laser Direct Inscription Technique. OFC 2025, 2025: M4J.5. DOI: 10.1364/OFC.2025.M4J.5. 【核验：Crossref + OpenAlex 摘要（19 µm 芯距四芯，平均插损 0.49 dB 封装前 / 0.92 dB 封装后）】

[Thomson2011] R. R. Thomson, T. A. Birks, S. G. Leon-Saval, A. K. Kar, J. Bland-Hawthorn. Ultrafast laser inscription of an integrated photonic lantern. Optics Express, 2011, 19(6): 5698. DOI: 10.1364/OE.19.005698. 【核验：Crossref + OpenAlex 摘要】

[Tan2021] D. Tan, Z. Wang, B. Xu, J. Qiu. Photonic circuits written by femtosecond laser in glass: improved fabrication and recent progress in photonic devices. Advanced Photonics, 2021, 3(2): 024002. DOI: 10.1117/1.AP.3.2.024002. 【核验：Crossref + OpenAlex 摘要】

[Choudhury2014] D. Choudhury, J. R. Macdonald, A. K. Kar. Ultrafast laser inscription: perspectives on future integrated applications. Laser & Photonics Reviews, 2014, 8(6): 827–846. DOI: 10.1002/lpor.201300195. 【核验：Crossref + OpenAlex 摘要】

[Suganuma2015] D. Suganuma, T. Ishigure. Fan-in/out polymer optical waveguide for a multicore fiber fabricated using the Mosquito method. Optics Express, 2015, 23(2): 1585. DOI: 10.1364/OE.23.001585. 【核验：Crossref + OpenAlex 摘要】

[Lindenmann2015] N. Lindenmann, S. Dottermusch, M. L. Goedecke, T. Hoose, M. R. Billah, T. Onanuga, et al. Connecting Silicon Photonic Circuits to Multicore Fibers by Photonic Wire Bonding. Journal of Lightwave Technology, 2015, 33(4): 755–760. DOI: 10.1109/JLT.2014.2373051. 【核验：Crossref + OpenAlex 摘要】

'''
t = t[:idx2] + new_refs + t[idx2:]

# update header count claim
rep('以下 42 条均经 DOI 解析或 OpenAlex/Crossref 元数据核对；', '以下 55 条均经 DOI 解析或 OpenAlex/Crossref 元数据核对（其中 14 条为 2026-10-28 补充核验）；')

open(P, 'w', encoding='utf-8').write(t)
print('04 patched:', len(orig), '->', len(t))

# ---- merge new refs json ----
try:
    cur = json.load(open('docs/research/.refs_related.json', encoding='utf-8'))
except Exception:
    cur = []
new = json.load(open('.work/rw_missing_refs.json', encoding='utf-8'))
if isinstance(new, dict):
    new = new.get('refs', [])
have = {(r.get('doi') or '').lower() for r in cur}
added = 0
for r in new:
    d = (r.get('doi') or '').lower()
    if d and d in have:
        continue
    cur.append(r); added += 1
json.dump(cur, open('docs/research/.refs_related.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('refs_related.json merged, added', added, 'total', len(cur))
