# -*- coding: utf-8 -*-
# Fix the TB/s vs Tb/s unit error in 05 and add JEDEC SPHBM4 evidence.
p = 'docs/research/05_Research_Motivation.md'
t = open(p, encoding='utf-8').read()
orig = t

old = '''- 若把 HBM 带宽转换为光通道，**需要的不是 1024 根波导，而是由"每光通道速率"决定的通道数**：
  - 【C】计算示例：HBM4 单堆栈 2 TB/s；若每光通道 32 Gb/s（Intel OCI 的通道速率【A】），则需 2 TB/s ÷ 32 Gb/s = **64 个光通道/方向**；
  - 【C】若每光通道 100 Gb/s（PAM4 单 lane 级），则需 **20 个光通道/方向**。
- 反过来，**1024 根波导**若每根 32 Gb/s，总容量为 1024 × 32 Gb/s = **32.8 Tb/s**（单向），远超单堆栈 HBM 的 2 TB/s【C】。'''

new = '''- 若把 HBM 带宽转换为光通道，**需要的不是 1024 根波导，而是由"每光通道速率"决定的通道数**。【C，所有换算均先统一单位：1 B = 8 bit】
  - HBM4 单堆栈 2 TB/s = **16 Tb/s = 16 384 Gb/s**（每方向）；
  - 若每光通道 32 Gb/s（Intel OCI 的通道速率【A】），则需 16 384 ÷ 32 = **512 个光通道/方向**；若采用 8 波长 WDM，则对应 **64 根光纤/波导**（512 ÷ 8）【C】；
  - 若每光通道 100 Gb/s（PAM4 单 lane 级），则需 16 384 ÷ 100 ≈ **164 个光通道/方向**；8λ WDM 时约 21 根光纤【C】。
- 反过来，**1024 根波导**若每根 32 Gb/s，总容量为 1024 × 32 Gb/s = 32 768 Gb/s = **32.8 Tb/s ≈ 4.096 TB/s**（单向）【C】，约为单堆栈 HBM4（2 TB/s）的 **2 倍**；若采用 8λ WDM，则可达约 **16 倍**。
- **一条重要的官方反证**：JEDEC 在 2026 年 7 月发布的 SPHBM4 标准（JESD330-4）把 HBM4 的 **2 048 个数据信号改为 512 个 + 4:1 串行化**，以相同总吞吐适配有机基板、放宽凸点间距 [JEDEC, 2026]。这直接证明"信号数/位宽"是**与速率、封装间距相交换的设计变量**，绝非物理通道数，更不是光波导数。'''

assert old in t
t = t.replace(old, new, 1)

# update the conclusion sentence
old2 = '**结论**：HBM 的 1024 位与"1024 根光波导"没有一一对应关系；把二者等同是概念错误。本项目不采用"HBM 1024 位 → 1024 光通道"的论证，而采用 §6.1 的系统级通道数论证。WDM/串行化/编码可以在"电气位宽"与"光通道数"之间做任意比例转换，具体比例是系统设计参数（详见 02 文件）。'
new2 = '**结论**：HBM 的 1024 位与"1024 根光波导"没有一一对应关系；把二者等同是概念错误（量纲不匹配）。本项目不采用"HBM 1024 位 → 1024 光通道"的论证，而采用 §6.1 的系统级通道数论证。串行化（SerDes）、WDM 与编码可以在"电气位宽"与"光通道数"之间做大幅比例转换——JEDEC SPHBM4 用 4:1 串行化把 2048 个信号压到 512 个就是官方例证——具体比例是系统设计参数（详见 02 文件）。'
assert old2 in t
t = t.replace(old2, new2, 1)

# add SPHBM4 reference after JEDEC HBM4 reference (item 9)
anchor = '9. **[JEDEC2025]** JEDEC Solid State Technology Association. *JEDEC and Industry Leaders Collaborate to Release JESD270-4 HBM4 Standard*. 新闻稿, 2025-04-16. URL: https://www.jedec.org/news/pressreleases/jedec%C2%AE-and-industry-leaders-collaborate-release-jesd270-4-hbm4-standard-advancing. 【核验：官方页面正文（经 r.jina.ai 抽取）】. 访问日期 2026-10-28.'
add = anchor + '''
9b. **[JEDEC2026SPHBM4]** JEDEC Solid State Technology Association. *New JEDEC SPHBM4 Standard Enables HBM4-Class Bandwidth on Organic Substrates*（JESD330-4；HBM4 的 2048 数据信号 → SPHBM4 的 512 数据信号 + 4:1 串行化）. 新闻稿, 2026-07-13. URL: https://www.jedec.org/news/pressreleases/new-jedec%C2%AE-sphbm4-standard-enables-hbm4-class-bandwidth-organic-substrates. 【核验：官方页面正文全文（经 r.jina.ai 抽取）】. 访问日期 2026-10-28.'''
assert anchor in t
t = t.replace(anchor, add, 1)

open(p, 'w', encoding='utf-8').write(t)
print('05 fixed. chars', len(orig), '->', len(t))

# ---------- fix 11 ledger ----------
p11 = 'docs/research/11_Evidence_Ledger.md'
t11 = open(p11, encoding='utf-8').read()
oldrow = '| E-HBM-05 | HBM4 单堆栈 2 TB/s；若每光通道 32 Gb/s，则需 64 光通道/方向；若 100 Gb/s 则需 20 | 本文推算 | — | — | 假设无 WDM 开销 | **辨析"HBM 1024 位 ≠ 1024 光波导"** | **C** | 实际系统可用 WDM 进一步压缩波导数 |'
newrow = '| E-HBM-05 | HBM4 单堆栈 2 TB/s = 16 Tb/s；每光通道 32 Gb/s → 512 光通道/方向（8λ WDM 时 64 根光纤）；100 Gb/s → 约 164 通道/方向（8λ 时约 21 根）；1024 波导 × 32 Gb/s = 32.8 Tb/s ≈ 4.096 TB/s ≈ 2× 单堆栈 HBM4 | 本文推算 | — | — | 单位统一：1 B = 8 bit；无 WDM 时按单通道计 | **辨析"HBM 1024 位 ≠ 1024 光波导"** | **C** | 实际系统可用 WDM 进一步压缩波导数；早期版本曾误写为 64 通道，已修正 |'
assert oldrow in t11
t11 = t11.replace(oldrow, newrow, 1)

anchor11 = '| E-HBM-08 | HBM DRAM 技术与架构综述 | IEEE IMW 2017 | 10.1109/IMW.2017.7939084 | 题录 | HBM | 02 文件 HBM 结构引用 | **D**（摘要未获取） | 需补摘要 |'
add11 = anchor11 + '\n| E-HBM-09 | JEDEC SPHBM4（JESD330-4，2026-07-13）：把 HBM4 的 2048 个数据信号改为 **512 个 + 4:1 串行化**，以相同总吞吐适配有机基板（放宽凸点间距、更长通道、可支持更多堆栈） | JEDEC 官方新闻稿 | https://www.jedec.org/news/pressreleases/new-jedec%C2%AE-sphbm4-standard-enables-hbm4-class-bandwidth-organic-substrates | 新闻稿正文全文 | 标准 | **证明"信号数/位宽"是可交换的设计变量，不是波导数**——答辩反驳"2048 位→2048 波导"的最强官方证据 | **A** | — |'
assert anchor11 in t11
t11 = t11.replace(anchor11, add11, 1)
open(p11, 'w', encoding='utf-8').write(t11)
print('11 updated. chars', len(t11))
