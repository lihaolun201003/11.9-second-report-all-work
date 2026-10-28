# -*- coding: utf-8 -*-
# Fix stale HBM bandwidth->optical-channel conversions in 08 (unit error: TB/s vs Tb/s).
import re

p = 'docs/research/08_Defense_QA.md'
t = open(p, encoding='utf-8').read()
orig = t

# 1) Q19 technical explanation
old1 = '**第三，反算恰好证明"不需要 1024 根波导"**：单堆栈 2 TB/s，若每光通道 32 Gb/s（Intel OCI 的通道速率【A】），需约 64 个光通道/方向；若每光通道 100 Gb/s，则约 20 个/方向【C；11 E-HBM-05】。也就是说 HBM 的带宽换算成光通道只有几十条量级，和 1024 根波导差一个数量级以上。'
new1 = '**第三，反算恰好证明"不需要 1024 根波导"**：单堆栈 2 TB/s = 16 Tb/s（注意 B 与 b 差 8 倍）。若每光通道 32 Gb/s（Intel OCI 的通道速率【A】），需 16 384 ÷ 32 = 512 个光通道/方向；若采用 8λ WDM，则对应 64 根光纤/波导。若每光通道 100 Gb/s，则约 164 个/方向（8λ 时约 21 根光纤）【C；11 E-HBM-05】。因此 HBM 的带宽换算成**光通道**是数百条量级、换算成**光纤**是数十根量级——它既不是 1024 根波导，也不能反过来证明"需要 1024 根波导"。'
assert old1 in t
t = t.replace(old1, new1, 1)

# 2) Q20 30-second answer
old2 = '把带宽换算成光通道：按每通道 32 Gb/s 算，2 TB/s 约需 64 个光通道/方向；按 100 Gb/s 算约 20 个/方向。反过来，1024 根波导若每根 32 Gb/s，总容量约 32.8 Tb/s，远超单堆栈 HBM 的 2 TB/s。所以二者没有一一对应关系。'
new2 = '把带宽换算成光通道：2 TB/s = 16 Tb/s，按每通道 32 Gb/s 算约需 512 个光通道/方向（8λ WDM 后约 64 根光纤）；按 100 Gb/s 算约 164 个/方向。反过来，1024 根波导若每根 32 Gb/s，总容量约 32.8 Tb/s（约 4.1 TB/s），约为单堆栈 HBM4 的 2 倍。所以二者量纲不同、没有一一对应关系。'
assert old2 in t
t = t.replace(old2, new2, 1)

# 3) Q20 detailed conversion list
old3 = '''- 2 TB/s ÷ 32 Gb/s = 64 个光通道/方向【C；假设无 WDM、无编码开销】；
- 2 TB/s ÷ 100 Gb/s = 20 个光通道/方向【C；假设 100 Gb/s/lane】；
- 反向：1024 × 32 Gb/s = 32.8 Tb/s（单向）【C；11 E-CALC-03】。'''
new3 = '''- 统一单位：2 TB/s = 16 Tb/s = 16 384 Gb/s【C；1 B = 8 bit】；
- 16 384 Gb/s ÷ 32 Gb/s = **512 个光通道/方向**【C；假设无编码开销】；若 8λ WDM，则对应 **64 根光纤/波导**；
- 16 384 Gb/s ÷ 100 Gb/s ≈ **164 个光通道/方向**【C；假设 100 Gb/s/lane】；8λ 时约 21 根光纤；
- 反向：1024 × 32 Gb/s = 32.8 Tb/s ≈ **4.096 TB/s**（单向），约为单堆栈 HBM4（2 TB/s）的 **2 倍**；8λ WDM 时约 16 倍【C；11 E-CALC-03】。
- **官方反证**：JEDEC 2026 年 7 月的 SPHBM4（JESD330-4）把 HBM4 的 2048 个数据信号改为 512 个 + 4:1 串行化以适配有机基板【A；JEDEC，2026】——"信号数"本身就是与速率、封装间距交换的变量，把它当成波导数在方法上就是错的。'''
assert old3 in t
t = t.replace(old3, new3, 1)

# 4) append a note to the evidence anchor line of Q20 if present
old4 = '> 难度 ★★★｜**最高频陷阱题**｜证据：05 §6.2、11 E-HBM-01/05、E-CALC-03、JEDEC【A】'
new4 = '> 难度 ★★★｜**最高频陷阱题**｜证据：05 §6.2、11 E-HBM-01/05/09、E-CALC-03、JEDEC HBM4（2025）与 SPHBM4（2026）【A】'
if old4 in t:
    t = t.replace(old4, new4, 1)
else:
    print('NOTE: evidence anchor not matched (ok)')

open(p, 'w', encoding='utf-8').write(t)
print('08 fixed. chars', len(orig), '->', len(t))

# ---------- check 09 for the same stale numbers ----------
p9 = 'docs/research/09_Presentation_Outline.md'
t9 = open(p9, encoding='utf-8').read()
hits = [m.start() for m in re.finditer(r'64 个光通道|2 TB/s ÷ 32|32\.8 Tb/s', t9)]
print('09 stale-calc hits:', len(hits))
for h in hits:
    print('  ...', t9[max(0, h-160):h+200].replace('\n', ' '))
