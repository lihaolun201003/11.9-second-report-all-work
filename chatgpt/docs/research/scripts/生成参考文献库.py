from pathlib import Path
import json, re, csv, requests, concurrent.futures, html
ROOT=Path(__file__).resolve().parents[1]
# Each item is a deliberately selected primary source, not a claim that the full paper was accessible.
S=[]
def paper(k,doi,access,loc,role,url=''):
 S.append(dict(id=k,doi=doi,url=url or 'https://doi.org/'+doi,access=access,locator=loc,role=role,kind='paper'))
def web(k,title,author,year,url,loc,role,access='B'):
 S.append(dict(id=k,title=title,author=author,year=year,url=url,doi='',access=access,locator=loc,role=role,kind='official'))
paper('Jupiter2022','10.1145/3544216.3544265','A','摘要；§2–3；Fig.1–3；附录F','Google生产网络，固定物理连接与动态逻辑拓扑','https://research.google/pubs/jupiter-evolving-transforming-googles-datacenter-network-via-optical-circuit-switches-and-software-defined-networking/')
paper('Apollo2022','10.48550/arXiv.2208.10041','A','§2–4，Table1，Fig.7–9','136×136 MEMS与系统指标','https://arxiv.org/abs/2208.10041')
paper('Brusberg2025','10.1109/TCPMT.2025.3526500','C','IEEE原始摘要；1614–1624全文未取得','超过1024 IOX玻璃互联；波长及全通道测试待补')
paper('Fanout2026','10.1016/j.optlastec.2025.114521','C+','ScienceDirect摘要、Introduction与Experimental片段','4芯1550nm组装FI/FO；卷期2026，DOI含2025')
paper('Li2023Review','10.1002/admt.202300620','C','Wiley原始摘要；全文未取得','工艺材料综述，不能伪造阅读全文')
paper('Jiang2021','10.1587/transele.2020ECS6002','C','IEICE摘要；pp34–36全文未取得','toward1000是目标；原理器件非千路证明')
paper('Yoo2016','10.1038/micronano.2016.30','A','3D multi-ring/optical phased arrays；Fig.6–7；PDF第4–5、7页','256真3D设计、等长、半径、间距')
paper('Routing2021','10.1364/OFC.2021.Th1A.37','C','Optica原始摘要','自动3D路由已有先例；算法与通道数待全文')
paper('Castro2025','10.1364/OFC.2025.W2A.36','C','Optica原始摘要','3D直写folded Clos与400Gb/s流量，通道数NR')
paper('Djogo2019','10.1088/2631-7990/ab4d51','C','原始OA摘要','84通道石英中介层；自动路由未证实')
paper('Thomson2012','10.1364/OL.37.002331','C','Optica原始摘要；作者稿索引','121波导fan-out，耦合假设不能当实测')
paper('GlassCPO2023','10.1109/JSTQE.2023.3247245','C','IEEE摘要及原始元数据','IOX+TGV+RDL封装，不能混同真3D光路')
paper('Grenier2023','10.3389/aot.2023.1244009','A','§2–4，端面加工和对准测试','IOX波导+激光机械加工，非激光写光芯')
paper('Charles2012','10.1364/AO.51.006489','A','作者稿§2–6；Fig.1–4、11–15','8路真3D等光程、曲率、间距与加工顺序')
paper('Minz2007','10.1109/TCAPT.2007.906300','C+','原始摘要及作者稿片段','系统3D封装路由，不是自由xyz玻璃')
paper('PROTON2015','10.1145/2830716','C+','机构记录与作者稿片段；single optical layer','3D系统、单光层、多拓扑P&R')
paper('Deng2025','10.1109/JLT.2025.3566775','C+','IEEE摘要，作者公开全文检索片段；§II–IV，p7217','国内二维损耗优化A*，单路由限制')
paper('LiDAR2025Formal','10.1145/3698364.3705355','C+','正式元数据、官方代码README','APR正式后续，勿重复当独立研究线')
paper('APR2024','10.48550/arXiv.2410.01260','A','v1 §2.2–2.5，§3.3–4，Fig.2–6','平面曲率感知A*、间距、交叉、损耗','https://arxiv.org/html/2410.01260v1')
paper('LiDAR2025','10.48550/arXiv.2505.17239','A','v1 §II–VI；TableIII、VI–VIII','1024/8195内部nets；部分参数有DRV','https://arxiv.org/html/2505.17239v1')
paper('Placement2025','10.48550/arXiv.2504.18813','A','v1 §3.3–4；Table1、4','路由感知布局；非Google Apollo','https://arxiv.org/html/2504.18813v1')
paper('Yu2026Compact','10.1002/adpr.70241','A','Results，Fig.8–9；尚未完整组装段','4路紧凑FLDW；Reff非局部Rmin，原文预算单位疑点')
paper('Xiao2025','10.1364/OL.551272','C','Optica原始摘要','808nm熔石英多扫描，不能移植1550nm约束')
paper('Kopp2023','10.1364/OE.477578','C+','原始摘要与Fujikura技术报告','288根4芯=1152空间芯；非芯片千路')
paper('Matching2021','10.1109/ICCAD51958.2021.9643560','C','NTU机构摘要','长度、弯曲、曲率、交叉匹配约束')
paper('Delay2025','10.23919/DATE64628.2025.10993062','C','HKUST机构摘要；作者PDF链接404','时延匹配；不引用可疑108%')
paper('OptHBM2025','10.1109/LCA.2025.3540058','A','§II–III；Fig.2–6；作者稿4页','光连接多栈HBM建模，非玻璃样机')
paper('Pond2023','10.1145/3575693.3578835','A','§3–7；Fig.7–8','内存池化支持性证据与条件')
paper('AgainstCXL2023','10.1145/3626111.3628195','A','§3 Cost、§4 Complexity、§5 Utility','DIMM离散容量、基础设施成本反证')
paper('OCM2022','10.1016/j.jpdc.2022.01.013','A','§3–4；Fig.3；§6','DDR光内存架构与仿真，非本地HBM实测')
paper('Rao2016','10.1145/2881025.2881030','A','§4–6；§5.2','Spark SQL特定工作负载可行性')
paper('Abali2015','10.48550/arXiv.1503.01416','C+','摘要与经济模型相关段','2015成本模型仅作方法反证','https://arxiv.org/abs/1503.01416')
paper('CXLIntro2023','10.48550/arXiv.2306.11227','A','协议／设备分类与内存池化相关章节','CXL1–3综述；不是2026最新标准','https://arxiv.org/abs/2306.11227')
paper('USConec165','10.1117/12.2578649','A','§1.1、Fig.1；实验与温循章节','51.2Tb/s架构1024 Tx/Rx纤及165µm插芯','https://www.usconec.com/media/5gqn45fu/next-generation-multi-fiber-ferrule-using-165-micron-pitch-optical-fiber.pdf')
paper('Davis1996','10.1364/OL.21.001729','C','Optica原始摘要','早期玻璃内部飞秒改性波导')
paper('Gattass2008','10.1038/nphoton.2008.47','C','作者机构摘要','透明介质飞秒加工物理综述')
paper('PhotonicWire2012','10.1364/OE.20.017667','C','原始摘要及arXiv作者记录','自由成形聚合物光线键合直接竞争')
web('CorningShuffle','Data Center Shuffling Solutions','Corning',None,'https://www.corning.com/optical-communications/asean/en/home/products/shuffle-solutions.html','Shuffle Solutions和FAQ','真实被动重排产品，未给统一损耗')
web('MolexShuffle','OptoConnect Aggregation Fiber Shuffle Boxes','Molex',None,'https://www.molex.com/content/dam/molex/molex-dot-com/en_us/pdf/datasheets/987651-1657.pdf?inline=','p1 Features and Advantages','72–6400纤、1–6RU系列、自动FlexPlane')
web('MolexFlex','FlexPlane Optical Circuitry and Routed Ribbon Cable Solutions','Molex',None,'https://www.molex.com/content/dam/molex/molex-dot-com/en_us/pdf/datasheets/987652-2611.pdf','p1–2','自动布纤、背板、Shuffle')
web('USConecEZ','US Conec Introduces EZ Shuffle Solution for High Density Fiber Management','US Conec',2018,'https://www.usconec.com/media/bldixi54/ez-shuffle-press-release.pdf','2018-10-17正文','256纤，41×84×9.5mm')
web('Castro2026','Optical Shuffle Architectures for Large AI Networks','Castro, Jose M.',2026,'https://www.ieee802.org/3/ad_hoc/E4AI/public/26_0224/castro_e4ai_02_260224.pdf','p2–14，尤其p13–14','贡献者演示，玻璃损耗反证；非正式IEEE标准','A')
web('CorningFiber','SMF-28 Ultra Optical Fibers','Corning',None,'https://www.corning.com/optical-communications/in/en/home/products/fiber/optical-fiber-products/smf-28-ultra.html','产品介绍','光纤成熟路线与模场/涂覆')
web('CorningPatch','Basic 2.0 mm 1 Fibre Patch Cord F585801G1Z20005M','Corning',None,'https://ecatalog.corning.com/optical-communications/EMEA/en_GB/Fibre-Optic-Cable-Assemblies/Indoor-Cable-Assemblies/Simplex-Indoor-Cable-Assemblies/Basic-2-0-mm-1-Fibre-Patch-Cord/p/F585801G1Z20005M','Mechanical/Optical Characteristics','特定跳线弯曲半径和光纤衰减条件')
web('IntelOCI2024','Intel Demonstrates First Fully Integrated Optical I/O Chiplet','Intel',2024,'https://www.intel.com/content/www/us/en/newsroom/news/intel-unveils-first-integrated-optical-io-chiplet.html','How It Works','64×32Gb/s/方向；8对纤；8λ/纤')
web('IntelHotChips2024','Intel Demonstrates AI Architectural Expertise at Hot Chips 2024','Intel',2024,'https://www.intel.com/content/www/us/en/newsroom/news/hot-chips-2024-ai-architectural-expertise.html','4 terabits per second…小节','用户指定，OCI补充')
web('SamsungHBM2E','Samsung to Advance High Performance Computing Systems with Launch of Industry’s First 3rd-generation (16GB) HBM2E','Samsung Electronics',2020,'https://news.samsung.com/global/samsung-to-advance-high-performance-computing-systems-with-launch-of-industrys-first-3rd-generation-16gb-hbm2e','Flashbolt速率容量段','16GB，3.2Gb/s/pin，410GB/s')
web('SKHBM3','First Movers on a Path That No-one Has Taken Before: Meet the Engineers Leading the World’s First Mass-production of HBM3','SK hynix',2022,'https://news.skhynix.com/en/meet-the-engineers-leading-the-worlds-first-mass-production-of-hbm3/','processing/storage小节','6.4Gb/s/pin，819GB/s')
web('MicronHBM3E','HBM3E','Micron Technology',None,'https://www.micron.com/products/memory/hbm/hbm3e','FAQ','1024I/O，>9.2Gb/s，>1.2TB/s')
web('JEDECHBM4','JEDEC and Industry Leaders Collaborate to Release JESD270-4 HBM4 Standard','JEDEC',2025,'https://www.jedec.org/news/pressreleases/jedec%C2%AE-and-industry-leaders-collaborate-release-jesd270-4-hbm4-standard-advancing','发布索引/交叉来源；正文未取得','标准存在确认，全文参数需补','C')
web('MicronHBM4','Micron in High-Volume Production of HBM4 Designed for NVIDIA Vera Rubin, PCIe Gen6 SSD and SOCAMM2','Micron Technology',2026,'https://micron.gcs-web.com/news-releases/news-release-details/micron-high-volume-production-hbm4-designed-nvidia-vera-rubin','2026-03-16正文与脚注','36GB12H量产声明，>11Gb/s，>2.8TB/s')
web('JEDECSPHBM4','New JEDEC SPHBM4 Standard Enables HBM4-Class Bandwidth on Organic Substrates','JEDEC',2026,'https://www.jedec.org/','官方首页索引；正文未取得','JESD330-4后续线索，详细数值未采用','C')
web('HopperGuide','NVIDIA Hopper Tuning Guide','NVIDIA',None,'https://docs.nvidia.com/cuda/hopper-tuning-guide/','NVLink Interconnect','H100 18 links/900GB/s双向')
web('NVLinkCurrent','NVIDIA NVLink and NVLink Switch','NVIDIA',None,'https://www.nvidia.com/en-us/data-center/nvlink/','Specifications','2026-10-28滚动表；有preliminary提示')
web('RubinCurrent','NVIDIA Vera Rubin NVL72','NVIDIA',None,'https://www.nvidia.com/en-us/data-center/vera-rubin-nvl72/','Specs','2026-10-28当前19.2TB/s/3TB/s，非CES版本')
web('PCIE5','PCIe Compliance Updates','PCI-SIG',None,'https://pcisig.com/developer/education/pcie-compliance-updates-16','5.0 Integrators List','32GT/s与x16口径')
web('CXL4','CXL Consortium Releases the Compute Express Link 4.0 Specification Increasing Speed and Bandwidth','CXL Consortium',2025,'https://computeexpresslink.org/wp-content/uploads/2025/11/CXL_4.0-Specification-Release_FINAL_Website-Copy.pdf','2025-11-18 p1 Key features','128GT/s，bundled ports')
web('CXL4QA','Introducing the CXL 4.0 Specification Webinar Q&A Recap','CXL Consortium',2026,'https://computeexpresslink.org/blog/introducing-the-cxl-4-0-specification-webinar-qa-recap-4386/','Q1/Q4','光连接retimer与延迟配置依赖')
web('LumericalFDE','MODE Finite-Difference Eigenmode FDE Solver Introduction','Ansys',None,'https://optics.ansys.com/hc/en-us/articles/360034917233-MODE-Finite-Difference-Eigenmode-FDE-solver-introduction','solver capabilities','模式与弯曲/螺旋波导')
web('LumericalBent','Solving Bent Waveguides in FDE and FEEM','Ansys',None,'https://optics.ansys.com/hc/en-us/articles/360034917253-Solving-bent-waveguides-in-FDE-and-FEEM','Bend orientation/Minimum bend radius','弯曲模型与半径定义')
web('LumericalCompact','Waveguide FDE','Ansys',None,'https://optics.ansys.com/hc/en-us/articles/360042800453-Waveguide-FDE','workflow','MODE到INTERCONNECT紧凑模型')
web('OpticStudio','Non-sequential Overview: OpticStudio User Guide','Ansys',2025,'https://ansyshelp.ansys.com/public/Views/Secured/Zemax/v25101/en/OpticStudio_User_Guide/OpticStudio_Help/topics/Non_sequential_Overview.html','Non-sequential Overview','三维光线追踪与导模计算不同')
web('OptoCompiler','OptoCompiler','Synopsys',None,'https://www.synopsys.com/photonic-solutions/optocompiler.html','Interactive Waveguide Routing','交互辅助避障和端口连接')
web('OptSim','OptSim','Synopsys',None,'https://www.synopsys.com/photonic-solutions/optsim.html','产品功能','系统与PIC信号传播仿真')
web('KLayout','Design Rule Checking','KLayout',None,'https://klayout.de/doc/manual/drc.html','DRC manual','平面多边形DRC')
web('KLayout25D','2.5d View','KLayout',None,'https://www.klayout.org/downloads/master/doc-qt5/about/25d_view.html','限制说明','垂直挤出显示，不是完整三维')
web('Gdsfactory','GDSFactory Routing','GDSFactory',None,'https://gdsfactory.github.io/gdsfactory/notebooks/04_routing/','routing notebook/API','bundle、曲线、半径间距与碰撞')
web('IPKISS','ConnectManhattanTapered','Luceda Photonics',2026,'https://academy.lucedaphotonics.com/ipkiss/reference/connectors/ref/ipkiss3.all.ConnectManhattanTapered','2026.09参数文档','bend_radius/min_spacing/matching')
web('Femto','femto: Femtosecond Laser Writing Photonic Circuits','Albiero, Riccardo',None,'https://github.com/ricalbr/femto','README、src/femto/waveguide.py','三维曲线和PGM导出；本次只读未运行','A')
web('AnsysZemax2021','Ansys 2022 Annual Report','Ansys',2022,'https://investors.ansys.com/static-files/90abb39f-75e6-4aee-891d-fa31bbdf8660','Acquisitions: October 1, 2021','Zemax完成日期，非8月签约日期')
web('SynopsysAnsys2025','Synopsys Completes Acquisition of Ansys','Synopsys',2025,'https://investor.synopsys.com/news/news-details/2025/Synopsys-Completes-Acquisition-of-Ansys/default.aspx','2025-07-17首段','交易完成日期')
web('KeysightOSG2025','Keysight Completes Acquisition of Synopsys Optical Solutions Group and Ansys PowerArtist','Keysight Technologies',2025,'https://www.keysight.com/in/en/about/newsroom/news-releases/2025/1017_pr25-083-keysight-completes-acquisition-of-synopsys-optical-solutions-group-and-ansys-powerartist.html','2025-10-17产品清单','RSoft归属转移')
web('LingThesis2023','Functional Photonic Integrated Circuits Based on Advanced Three-Dimensional Photonic Packaging','Ling, Yi-Chun',2023,'https://escholarship.org/uc/item/91t489m0','大学库摘要，PDF受限','ULI routing直接候选，未取得全文','C')
paper('Brusberg2020Multimode','10.1109/JLT.2019.2956915','C','Optica原始摘要；JLT38(6):1350–1357','1310nm多模IOX0.035dB/cm，9×12英寸玻璃与12×12 Shuffle，连接约1dB/接口')
# Harvest verified publisher metadata already retained by classifiers.
cache={}
for p in (ROOT/'sources').rglob('*.json'):
 try:
  d=json.loads(p.read_text()); d=d.get('message',d)
  if isinstance(d,dict) and d.get('DOI'):cache[d['DOI'].lower()]=d
 except Exception:pass
missing=[s for s in S if s.get('doi') and s['doi'].lower() not in cache and not s['doi'].startswith('10.48550')]
def get(s):
 try:
  r=requests.get('https://api.crossref.org/works/'+s['doi'],timeout=25);r.raise_for_status();d=r.json()['message'];(ROOT/'sources/raw'/('crossref_'+re.sub('[^a-zA-Z0-9.-]','_',s['doi'])+'.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2));return s['doi'].lower(),d
 except Exception:return s['doi'].lower(),None
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 for doi,d in ex.map(get,missing):
  if d:cache[doi]=d
arxiv={
'Apollo2022':('Mission Apollo: Landing Optical Circuit Switching at Datacenter Scale','Ryohei Urata and Hong Liu and Kevin Yasumura and Erji Mao and Jill Berger and Xiang Zhou and Cedric Lam and Roy Bannon and Darren Hutchinson and Daniel Nelson and Leon Poutievski and Arjun Singh and Joon Ong and Amin Vahdat',2022),
'APR2024':('Automated Curvy Waveguide Routing for Large-Scale Photonic Integrated Circuits','Hongjian Zhou and Keren Zhu and Jiaqi Gu',2024),
'LiDAR2025':('LiDAR 2.0: Hierarchical Curvy Waveguide Detailed Routing for Large-Scale Photonic Integrated Circuits','Hongjian Zhou and Haoyu Yang and Ziang Yin and Nicholas Gangi and Zhaoran (Rena) Huang and Haoxing Ren and Joaquin Matres and Jiaqi Gu',2025),
'Placement2025':('Automated Routing-Informed Placement for Large-Scale Photonic Integrated Circuits','Hongjian Zhou and Haoyu Yang and Nicholas Gangi and Haoxing Ren and Rena Huang and Jiaqi Gu',2025),
'Abali2015':('Disaggregated and optically interconnected memory: when will it be cost effective?','Bulent Abali and Richard J. Eickemeyer and Hubertus Franke and Chung-Sheng Li and Marc A. Taubenblatt',2015),
'CXLIntro2023':('An Introduction to the Compute Express Link (CXL) Interconnect','Debendra Das Sharma and Robert Blankenship and Daniel S. Berger',2023)}
for s in S:
 if s['id'] in arxiv:
  s['title'],s['author'],s['year']=arxiv[s['id']];s['metadata_verification']='arXiv/author original record';continue
 if s['doi']:
  d=cache.get(s['doi'].lower())
  if not d:print('MISSING',s['id'],s['doi']);continue
  s['title']=html.unescape(re.sub('<[^>]+>','',d.get('title',[''])[0] + (': '+d['subtitle'][0] if d.get('subtitle') else '')));s['author']=' and '.join((a.get('given','')+' '+a.get('family','')).strip() or a.get('name','') for a in d.get('author',[]))
  date=d.get('published-print') or d.get('published') or d.get('issued') or d.get('published-online',{})
  s['year']=date.get('date-parts',[[None]])[0][0];s['venue']=html.unescape(d.get('container-title',[''])[0]);s['volume']=d.get('volume','');s['number']=d.get('issue','');s['pages']=d.get('page',d.get('article-number',''));s['metadata_verification']='Crossref DOI exact match + publisher record'
 else:s['metadata_verification']='official organization or named author source; undated webpages have no invented publication year'
 if s['id']=='Fanout2026':s['year']=2026
(ROOT/'sources/catalog.json').write_text(json.dumps(S,ensure_ascii=False,indent=2))
def esc(v):return str(v).replace('\\','').replace('{','\\{').replace('}','\\}').replace('&','\\&').replace('%','\\%')
entries=[]
for s in S:
 typ='article' if s['kind']=='paper' and not s['doi'].startswith('10.48550') else 'misc'
 if s['id'] in ['Jupiter2022','Routing2021','Castro2025','LiDAR2025Formal','Matching2021','Delay2025','Pond2023','AgainstCXL2023','Rao2016','USConec165']:typ='inproceedings'
 fields={'title':s.get('title','METADATA PENDING'),'author':s.get('author',''),'year':s.get('year'),'doi':s['doi'],'url':s['url'],'urldate':'2026-10-28','note':'Access '+s['access']+'; '+s['locator']}
 if s['kind']=='official':fields['author']='{'+s.get('author','')+'}'
 if s.get('venue'):fields['booktitle' if typ=='inproceedings' else 'journal']=s['venue']
 for a in ['volume','number','pages']:
  if s.get(a):fields[a]=s[a]
 body=[]
 for k,v in fields.items():
  if v is None or v=='':continue
  val=esc(v)
  if k=='author' and s['kind']=='official':val='{'+esc(s.get('author',''))+'}'
  body.append('  '+k+' = {'+val+'}')
 entries.append('@'+typ+'{'+s['id']+',\n'+',\n'.join(body)+'\n}')
(ROOT/'10_参考文献库.bib').write_text('% Primary-source library. Access date: 2026-10-28. Missing publication year for undated pages is intentional.\n\n'+'\n\n'.join(entries)+'\n')
with (ROOT/'参考文献目录.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=['id','title','author','year','doi','url','kind','access','locator','role'],extrasaction='ignore');w.writeheader();w.writerows(S)
ris=[]
for s in S:
 lines=['TY  - '+('JOUR' if s['kind']=='paper' else 'ELEC'),'ID  - '+s['id'],'TI  - '+s.get('title','')]
 lines+=['AU  - '+a for a in s.get('author','').split(' and ') if a]
 if s.get('year'):lines.append('PY  - '+str(s['year']))
 if s['doi']:lines.append('DO  - '+s['doi'])
 lines+=['UR  - '+s['url'],'N1  - Access '+s['access']+'; '+s['locator'],'ER  - '];ris.append('\n'.join(lines))
(ROOT/'参考文献库.ris').write_text('\n\n'.join(ris)+'\n')
print(json.dumps({'references':len(S),'papers':sum(s['kind']=='paper' for s in S),'full_or_relevant_sections_A':sum(s['access']=='A' for s in S),'metadata_missing':[s['id'] for s in S if not s.get('title')]},ensure_ascii=False))
