# -*- coding: utf-8 -*-
# Strengthen 05 §5.2 and 11 E-EDA-04 with 03's verified EDA findings.

def patch(path, pairs):
    t = open(path, encoding='utf-8').read()
    orig = t
    for old, new in pairs:
        assert old in t, path + ' MISS: ' + old[:70]
        t = t.replace(old, new, 1)
    open(path, 'w', encoding='utf-8').write(t)
    print(path, len(orig), '->', len(t))

patch('docs/research/05_Research_Motivation.md', [
 ('- **光子系统级布线工具**：主要面向平面光集成电路（PIC）的波导布线，支持曲线波导与 DRC，但通常以**平面/有限层**为主，且以版图输出为目标（详见 03 文件 EDA 调查）。',
  '- **光电子 EDA / 光子布线工具**：现有工具已能完成四件事——①器件级仿真（Lumerical 的 FDTD/MODE、INTERCONNECT）；②版图与 PDK（OptoCompiler、IPKISS、gdsfactory）；③DRC/LVS（IC Validator、Irys、KLayout）；④二维曲线布线（gdsfactory 的 route_bundle、LiDAR 2.0 的曲率感知 A*）。因此**不能笼统说"EDA 不会布线"**。其真正的边界是：①GDSII/OASIS 本质是二维格式，没有连续深度（z/埋深）语义，工具只能把每个深度当作"一层"逐层布、再人工处理层间过渡；②没有把飞秒直写工艺规则（脉冲能量—Δn—模场—最小间距—写入顺序—深度相关损耗）编码为**可执行 DRC** 的公开规则集；③损耗模型是常数，不随深度/扫描遍数变化；④没有"1024 通道 + 三维 + 飞秒工艺"的公开基准（详见 03 文件 §4.3，已区分"商业工具无公开功能""学界无研究""有相关研究但不在 EDA 语境"三种"没有"）。'),
])

patch('docs/research/11_Evidence_Ledger.md', [
 ('| E-EDA-04 | 光子 EDA 工具（Lumerical/OpticStudio/Synopsys/KLayout/Luceda/gdsfactory/Tidy3D）的能力边界 | 各厂商官方页与文档（见 03 文件） | 见 03 文件 | — | 工具能力 | **本项目创新性论证的关键** | 由 03 文件给出 | 需区分"无公开功能"与"不存在" |',
  '| E-EDA-04 | 光子 EDA 能做：器件级仿真（Lumerical FDTD/MODE/INTERCONNECT）、版图与 PDK（OptoCompiler/IPKISS/gdsfactory）、DRC/LVS（IC Validator/Irys/KLayout）、二维曲线布线（gdsfactory route_bundle；LiDAR 2.0 曲率感知 A* 用于近千元件）；**空白**：A 无连续深度语义（GDSII/OASIS 为 2D 格式）；B 无飞秒直写工艺 DRC 规则集；C 损耗模型为常数、无深度相关项；D 无"1024 通道+三维+FsDLW"公开基准；E 布线目标不含加工时间/写入顺序 | 03 文件 §4.1–4.3（各厂商官方文档 + Zhou 等 2025/2026 + Brusberg 等 2025 + Huang 等 2020） | 见 03 文件 §4 | — | 工具能力/研究空白 | **本项目创新性论证的关键**：应表述为"官方文档未提供/检索不到"，而非"技术上不可能" | **A/B**（官方文档+摘要） | 需区分三种"没有"：商业工具无公开功能 / 学界无研究 / 有研究但不在 EDA 语境 |'),
])
print('done')
