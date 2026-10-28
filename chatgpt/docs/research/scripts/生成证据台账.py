# -*- coding: utf-8 -*-
from pathlib import Path
import json
R=Path(__file__).resolve().parents[1]
S=json.loads((R/'sources/catalog.json').read_text()); by={x['id']:x for x in S}
F=[]
def f(k,claim,src,loc,cond,use,counter,level='高（该来源限定内）'):
 F.append(dict(id=k,claim=claim,sources=src.split(),locator=loc,conditions=cond,project_use=use,counter_or_limit=counter,confidence=level))
f('E01','Jupiter由Clos向聚合块直接连接演进，OCS+SDN提供动态拓扑','Jupiter2022','§2–3、Fig.1–3','Google生产网络经验，非无源器件实验','支撑OCS外围固定物理映射的场景','玻璃固定器件不具备动态交换')
f('E02','论文报告5倍速率/容量、capex降30%、功耗降41%、平均块级路径1.4','Jupiter2022','摘要、§2、Fig.1–3','整套架构和运营演进的汇总收益','仅作真实网络背景','不能归因于玻璃或移植为本课题提升')
f('E03','Palomar为136×136、毫秒量级；代表插损通常<2dB；最大整机功耗108W','Apollo2022','§2与§4；Fig.7–9；机架整机段','MEMS OCS系统，插损含系统相关参考面','说明端口/组合/同时连接区别','136²=18496是组合，非同时18496条物理路径')
f('E04','Shuffle Box为固定被动重排，面向AI/HPC和Spine–Leaf','CorningShuffle','Shuffle Solutions；FAQ','官方产品说明，未公开统一插损或价格','最直接应用功能','不证明某一1024规格或玻璃已替代光纤')
f('E05','Molex自动FlexPlane制造；系列72–6400纤、1–6RU','MolexShuffle','数据表p1 Features and Advantages','系列范围，非每个型号共同上限','千物理纤与自动制造的强工程依据','不能称1RU容纳6400纤；非玻璃芯片')
f('E06','EZ Shuffle最多256纤，41×84×9.5mm，可堆叠','USConecEZ','2018-10-17公告正文','指定光纤管理模块，16纤/带、16带','同类组件体积和模块化基线','堆叠1024纤不证明单模块任意1024映射')
f('E07','51.2Tb/s、100Gb/s单向lane、512radix示例给1024 Tx/Rx纤','USConec165','§1.1、Fig.1；作者稿PDF p1–2','2021 CPO架构研究示例；收发分纤','本项目1024物理路径的可追溯背景','不是通用标准、不是已使用本项目玻璃；WDM会改变纤数')
f('E08','传统250µm间距；新研究165µm间距配80µm包层，单排24纤','USConec165','摘要、§1.1及结构段','具体MT-style插芯研究','端面约束与高密度趋势','不是玻璃内部dmin；不能把包层、涂覆和中心距混用')
f('E09','贡献者演示称所讨论3D直写玻璃损耗高于optical-flex','Castro2026','p13；p10–14实现比较','2026-02技术贡献者演示，非IEEE正式标准','必须保留的负面证据','并非所有未来玻璃工艺的普遍定律')
f('E10','IOX论文摘要报告>1024互联、传播0.034dB/cm','Brusberg2025','IEEE原始摘要','优化玻璃/银离子交换；全文未取、波长与详细老化证据未核','证明千路玻璃先例；损耗仅摘要级锚点','不纳跨材料排名；不能称任意真3D、FLDW或全通道实测','中：原始摘要支持，细节待全文')
f('E11','4芯19µm芯距FI/FO，1550nm，α约0.2dB/cm、0.1dB/facet、组装平均0.63dB','Fanout2026','摘要、Introduction、Experimental片段','硼铝硅玻璃，多扫；芯片10×6.5mm、封装27×6.5mm','同工艺标定和装配影响实例','4路不外推1024，摘要片段不等于完整精读；正式卷期2026','中高：原始摘要/片段')
f('E12','Toward over1000为系统目标；原理器件IL2.1dB、XT<-54.2dB','Jiang2021','IEICE摘要；pp34–36','测量波长、实际规模及工艺未由可得文本核定','已有3D Shuffle概念先例','不能写实际1000路；数值不纳工艺性能排名','中：原始摘要')
f('E13','256条真3D波导由1×256线阵到16×16阵列；工具约束等光程、半径和间距','Yoo2016','3D optical phased arrays、Fig.7；PDF p4–5与7','ULI及所述玻璃工艺；文中示例Rmin20mm非通用','强反证：3D+曲率+间距已有','综述/系统介绍不等于开源任意1024优化器')
f('E14','8路真3D路径匹配已有实制；写入顺序/深度被讨论','Charles2012','作者稿§2–6、Fig.1–4/11–15','Eagle2000；工作1550nm；加工800nm、<50fs、5.1MHz、35nJ、250mm/min','制造约束与曲线设计先例','30µm间距、>23mm模型范围不能移植；设计0.1µm匹配≠实测45µm光程差')
f('E15','2021三维FI/FO摘要明确automatic 3D routing','Routing2021','Optica摘要','ULI；可得摘要未给实际通道数或算法','反驳3D自动路由空白','未披露项标NR而非否')
f('E16','2025玻璃3D直写实现folded Clos并表征400Gb/s流量','Castro2025','Optica摘要','Panduit+Modular Photonics；通道数未核实','直接应用竞争先例','不能虚构损耗分布、尺寸、路由算法或大规模部署')
f('E17','84-channel silica interposer采用激光写入和刻蚀自对准结构','Djogo2019','出版社/OA原始摘要','石英、高密度多纤封装','说明大通道接口和制造组合','不证明通用自动路由或千路')
f('E18','121波导fan-out约7dB实测吞吐损耗，约1.7dB是理想耦合估计','Thomson2012','Optica摘要','天文光子阵列转换，非1024Shuffle','证明端面/耦合决定表现','不能只引用1.7dB当实测')
f('E19','IOX玻璃连接器工艺：被动对准相对主动对准平均增加0.19dB','Grenier2023','§2–4；端面/重复插拔段','激光切割/对准槽，不是激光写光芯；特定MT接头','端面装配纳入系统规则','<1µm平坦度覆盖6.5mm区不等于本组平台精度')
f('E20','APR采用x/y/orientation曲率A*，考虑间距、交叉、端口与损耗','APR2024','v1 §2.2–2.5、§3–4','单光层平面PIC模型；非玻璃加工','明确可迁移算法对照','不能称只会直角，也不能直接当3D玻璃解')
f('E21','LiDAR2 v1有1024与8195 nets；部分表格仍有DRV','LiDAR2025','v1 TableIII、VI–VIII','内部PICnets；固定v1，非默认最新PDF','千连接软件规模已有','摘要DRV-free不可推广所有参数；不是千路玻璃实物')
f('E22','国内JLT2025路由研究多损耗与几何，当前讨论单波导限制','Deng2025','§II–IV，p7217；IEEE摘要','硅光二维；示例1000×1000µm²；3.72dB/44.17s是模型路由','国内相关工作与方法基线','不外推1024运行时间/玻璃弯曲半径')
f('E23','2026四路紧凑FI/FO尚未完整组装；1310nm、2.5×2mm²、IL<0.54dB','Yu2026Compact','Results、Fig.8–9、未组装说明','硼铝硅玻璃特定曲线与多扫描；α0.13dB/cm、端面0.06dB','弯曲工艺与封装状态的直接比较','Reff非局部Rmin；原文0.85×1.4单位算术疑点不沿用')
f('E24','808nm熔石英多扫90° R10mm，最小弯曲损耗1.028dB/cm','Xiao2025','Optica原始摘要','指定工作波长、弯角和扫描工艺','说明参数需条件化','不能用于1550nm玻璃通用约束')
f('E25','1152空间芯来自288根4芯MCF；576FIFO为两端合计','Kopp2023','原始摘要及Fujikura报告','城域已部署光缆；现场安装后XT测试覆盖有限','真实千空间通道旁证','不是1152独立纤或一块千路玻璃')
f('E26','Intel OCI每方向64×32Gb/s；8纤×8λ；双向8对纤；最远100m','IntelOCI2024 IntelHotChips2024','How It Works；Hot Chips OCI小节','2024演示，5pJ/bit为厂商co-packaged口径','位宽/lane/纤数区别、未来光I/O应用','100m不是所有内存可接受距离；5pJ/bit非裸无源玻璃')
f('E27','HBM2E 16GB、3.2Gb/s/pin、410GB/s；HBM3 6.4Gb/s/pin、819GB/s','SamsungHBM2E SKHBM3','各产品正文','指定产品点；1024有效数据位，十进制带宽','展示电HBM结构与带宽','不是所有SKU上限；未核整栈功耗/距离')
f('E28','HBM3E官方>9.2Gb/s、>1.2TB/s、24/36GB','MicronHBM3E','FAQ','滚动产品页；1024有效数据I/O','说明HBM演进及口径','9.2×1024/8=1.1776TB/s；两个大于号不能读为相等')
f('E29','HBM4初版JESD270-4已发布；Micron2026-03声称36GB12H量产、>11Gb/s、>2.8TB/s','JEDECHBM4 MicronHBM4','标准发布索引；Micron正文/脚注','标准全文未取得；厂商量产声明与初版规范不同','更新截至2026背景','4A修订、SPHBM4详细参数待正式标准；不把厂商算功率当实测')
f('E30','H100 18NVLink/900GB/s双向；当前NVIDIA表Blackwell1800、Rubin3000GB/s','HopperGuide NVLinkCurrent RubinCurrent','NVLink Interconnect与Specifications','2026-10-28滚动页；初步规格，Rubin内存19.2TB/s','不同层级方向注明后比较','不混CES历史22/3.6指标；逻辑全连不等于物理两两直连')
f('E31','PCIe5每lane32GT/s；x16编码后约63.015GB/s单方向','PCIE5','5.0 Integrators List；公式为本报告推导','128b/130b编码，未扣包头等','统一单位和方向','不是x16单向128GB/s')
f('E32','CXL4于2025-11发布128GT/s，光连接可经retimer实现','CXL4 CXL4QA','发布PDF p1；2026Q&A Q1/Q4','协议与物理传输分层，延迟依实现/流量','内存背景与技术时效','不是本课题被动器件原生支持CXL')
f('E33','Ou2025光HBM为模型：6组×48纤=288，含96TX/96RX/96供光','OptHBM2025','§II–III、Fig.2–6','传统HBM结构+EIC/PIC；每信号纤64λ×16Gb/s','光HBM真实研究存在，且纤数不同于位宽','不是实物/玻璃1024；性能收益依L2带宽等配置')
f('E34','Pond在158工作负载模型/评估中，8–16socket小池给DRAM降7%、性能差1–5%','Pond2023','§3–7；Fig.7–8','额外延迟模型约70–90ns；分层放置和预测策略','支持内存池化的条件证据','不是光传播单独收益或所有CXL实物测试')
f('E35','反方强调DIMM容量离散、交换/布线成本、复杂度及调度替代','AgainstCXL2023','§3–5','2023云工作负载与当时成本设定的立场论文','必须列出的条件反证','不证明所有内存扩容/共享无益')
f('E36','OCM以2纤承载4DDR4通道；1.02pJ/bit与最高5.5倍为模型/仿真','OCM2022','§3、Fig.3、§4.2–4.3','对40G NIC远端内存基线，非本地HBM','光内存架构与WDM计数','版本作者与2020会议版不同；不宣称已实测')
f('E37','femto公开源码支持xyz弯曲与PGM导出','Femto','README；waveguide.py bend(dy,dz,fx,radius)','只读源码，未安装运行','反驳专用直写软件不存在','未证明任意1024全局避碰/工艺自动标定')
f('E38','光子EDA已有曲线/半径/间距/场模拟/交互路由等能力','Gdsfactory IPKISS LumericalFDE LumericalBent OptoCompiler OpticStudio KLayout25D','各工具文档对应章节','不同功能层级与版本，未完成许可证实测','选择基线及参数库工具','3D场仿真、显示、物理自动路由不可混同')
f('E39','Zemax完成收购2021-10-01；Ansys完成2025-07-17；OSG/RSoft转Keysight2025-10-17','AnsysZemax2021 SynopsysAnsys2025 KeysightOSG2025','年报Acquisitions；两份完成公告首段/清单','历史归属与截至访问时产品区分','纠正产业生态描述','签约日期不等于完成；并购不证明自动路由能力')
f('E40','自由成形聚合物光线键合早已有芯片间3D互联实验','PhotonicWire2012','原始摘要','聚合物、双光子光刻、跨芯片，不是玻璃体内','直接竞争技术，避免假称只有玻璃可3D','不将聚合物样机所有指标外推PCB级或千路')
# Derived facts are calculations, not experimental evidence.
derived=[
('D01','N条一一映射=N条路径，两端各N端点；1024→2048端点','集合双射定义','不适用于有分束/合束或不同接口计数'),
('D02','路径对512/1024/2048→130816/523776/2096128','N(N−1)/2','对数不是实际运行时间；空间索引可剪枝'),
('D03','每路100折线段朴素段对约13.08/52.38/209.61亿','N(N−1)×100²/2','复杂度上界量级，非本系统执行次数'),
('D04','1024随机置换期望逆序261888，倒序523776；32×32转置246016','N(N−1)/4；N(N−1)/2；C(32,2)²','只针对给定一维端口与平面单调模型，非任意2D下界'),
('D05','250µm pitch时32阵列中心跨度7.75mm，1024单排255.75mm','(n−1)p，pitch示例来自USConec165','不含封装、边缘和连接器，也不是内部安全间距'),
('D06','D=9.6Tb/s、r=100Gb/s、W=8、η=.8→15信号纤；W=1→120','ceil[D/(rWη)]','人为带宽示例，非HBM光接口设计；需另计方向和供光'),
('D07','假设ng=1.5→5ns/m单程；1/10/100m→5/50/500ns','t=ngL/c，c约3×10^8m/s','ng为假设，非本组玻璃；远端访问还含转换和协议等'),
('D08','1024×50mm=51.2m；10mm/s单扫85.3min，8扫11.38h；1mm/s为14.22h/113.78h','Twrite=ΣmiLi/vi','假设条件，不含空程/加减速/装配，不是设备实测'),
('D09','假设独立每道成功p=.999/.9999，则p^1024≈.359/.903','独立伯努利全片概率','忽略共同失效与相关性，不能当真实良率预测'),
('D10','最终曲线Rmin=1/maxκ，dij=min||ri(u)−rj(v)||','三维微分几何与距离定义，详07','采样不必给连续保证；计算容差和参数化奇点需处理')]
(R/'sources/evidence_claims.json').write_text(json.dumps({'facts':F,'derived':derived},ensure_ascii=False,indent=2))
text=['# 核心事实与证据台账\n\n截止与访问日：2026-10-28。本台账覆盖关键数字、行业案例和现状判断，不能把来源支持强度与本项目完成状态混淆。\n\n访问等级：A=取得全文/作者稿并重点阅读相关章节，或明确标注的完整源码阅读；B=官方完整文档/网页；C=原始摘要/官方索引，全文未取得；C+=摘要加可读片段。A不表示已复现实验，C不允许填补缺失实验。\n']
for x in F:
 refs=[]
 for k in x['sources']:
  s=by[k];refs.append(f"[{k}]({s['url']})（{s.get('author','')}，{s.get('year') or '未署年'}，{s['access']}）")
 text.append(f"## {x['id']} {x['claim']}\n\n- 原始资料：{'；'.join(refs)}。\n- 支持位置：{x['locator']}。\n- 适用条件：{x['conditions']}。\n- 本项目用途：{x['project_use']}。\n- 可信度：{x['confidence']}。\n- 反例／限制：{x['counter_or_limit']}。\n")
text.append('## 理论计算与自行构造：不可标为实验\n\n|ID|结果|计算与假设|边界|\n|---|---|---|---|')
for row in derived:text.append('|'+ '|'.join(row)+'|')
text.append('\n## 完整文献与访问清单\n\n下列作者/年份优先由DOI逐条Crossref与原始页面核对。无日期网页不虚构发表年。原始JSON保留在sources中；arXiv按固定版本使用。\n')
for s in S:
 text.append(f"### {s['id']}\n\n{s.get('author','')}；{s.get('year') or '未署年，访问2026-10-28'}；**{s['title']}**。{s.get('venue','')}。\n\n[原始来源]({s['url']})"+(f"；DOI：`{s['doi']}`" if s['doi'] else '')+f"。访问 **{s['access']}**；定位：{s['locator']}。用途及边界：{s['role']}。\n")
(R/'11_核心事实与证据台账.md').write_text('\n'.join(text))
print('ledger facts',len(F),'derived',len(derived),'references',len(S))
