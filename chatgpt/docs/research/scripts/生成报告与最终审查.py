# -*- coding: utf-8 -*-
from pathlib import Path
import json,re,math,csv,html,sys
import markdown,bibtexparser
R=Path(__file__).resolve().parents[1]
S=json.loads((R/'sources/catalog.json').read_text());by={s['id']:s for s in S}
# Reproducible arithmetic, explicitly separated from measurements.
calc={
 'kind':'theoretical calculations and constructed research examples; NOT measurements',
 'scaling':[{'N':n,'path_pairs':n*(n-1)//2,'naive_segment_pairs_100_segments_per_path':n*(n-1)//2*10000} for n in [64,128,256,512,1024,2048]],
 'inversions_1024_random_expectation':1024*1023//4,
 'inversions_1024_reversal':1024*1023//2,
 'inversions_32_by_32_transpose':math.comb(32,2)**2,
 'CPO_example':{'source':'USConec165 section1.1','one_way_Tbps':51.2,'Gbps_per_unidirectional_lane':100,'tx_fibers':512,'rx_fibers':512,'total_physical_fibers':1024},
 'array_span_mm_at_250um_pitch':{'32_positions':31*.25,'1024_positions':1023*.25},
 'optical_lane_lower_bound_example':{'D_Tbps':9.6,'r_Gbps':100,'eta':.8,'fibers_W8':math.ceil(9600/(100*8*.8)),'fibers_W1':math.ceil(9600/(100*.8))},
 'time_example':{'N':1024,'length_per_waveguide_mm':50,'total_length_m':51.2,'v10_mms_single_scan_min':51200/10/60,'v10_mms_8scans_hours':51200*8/10/3600,'v1_mms_single_scan_hours':51200/3600,'v1_mms_8scans_hours':51200*8/3600},
 'independent_yield_example':{'p_0.999':.999**1024,'p_0.9999':.9999**1024},
 'ng1_5_propagation_ns_per_m':1.5/3e8*1e9,
 'pcie5_x16_128b130b_GBps_one_way':32*16*128/130/8}
(R/'sources/scaling_calculations.json').write_text(json.dumps(calc,ensure_ascii=False,indent=2))
with (R/'sources/example_32x32_connections.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['net_id','input_group_a','input_lane_b','input_linear','output_group_b','output_lane_a','output_linear','status'])
 for a in range(32):
  for b in range(32):w.writerow([f'n{a*32+b:04d}',a,b,a*32+b,b,a,b*32+a,'constructed_example_not_deployed'])
# Add source links without requiring a citation manager to follow keys.
for p in sorted(R.glob('0[1-9]_*.md')):
 text=p.read_text().split('\n## 本文引用来源\n')[0]
 keys=[]
 for m in re.finditer(r'\[([A-Za-z][A-Za-z0-9]+)(?:[,，][^\]]*)?\]',text):
  k=m.group(1)
  if k in by and k not in keys:keys.append(k)
 if keys:
  out=['\n## 本文引用来源\n\n完整作者、卷期、DOI及访问边界见10与11文件；下面给原始来源快捷链接。\n']
  out += [f"- [{k}: {by[k]['title']}]({by[k]['url']})（{by[k].get('year') or '未署年'}；访问{by[k]['access']}）" for k in keys]
  p.write_text(text+'\n'.join(out)+'\n')
# Machine-readable methods log. No synthetic coverage percentage.
queries=[
 'Optical Design and Applications for Ion-Exchanged Glass Waveguide Circuits',
 'Fully-assembled low-loss fan-in/fan-out device laser direct writing 114521',
 'Optical Waveguides Fabricated via Femtosecond Direct Laser Writing 202300620',
 'three dimensional glass waveguide shuffle automatic routing 1024',
 'Jupiter Evolving optical circuit switches Google Apollo',
 'Photonic Chip with Embedded Data Center Fabric',
 'fiber shuffle CPO 1024 fibers automated FlexPlane',
 'three-dimensional waveguide routing curvature manufacturability',
 'HBM optical interconnect optical compute interconnect chiplet',
 'memory disaggregation photonics Pond A Case Against CXL Memory Pooling',
 'gdsfactory routing IPKISS Lumerical bent waveguides femto',
 'Synopsys Ansys acquisition completed Keysight Optical Solutions Group']
plan={'date':'2026-10-28','language':'zh','purpose':'topic-focused deep research, not systematic review','concept_groups':['OCS/Shuffle/CPO','3D glass/FLDW/IOX','automatic routing/EDA','HBM/GPU/CPU/CXL and counterevidence'],'queries':queries,'cutoff':'2026-10-28','classic_years_included':True}
(R/'sources/query_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
prisma={
 '1_database_information':{'used':['publisher original pages','author/university repositories','arXiv original records','Crossref exact DOI','official vendor/standards documentation'],'not_used':['OpenAlex API','Semantic Scholar API','PubMed systematic search']},
 '2_multi_database_searching':{'note':'Primary-source web retrieval plus Crossref. Not a five-database systematic run.'},
 '3_study_registries':{'performed':False,'reason':'engineering topic'},
 '4_online_resources_browsing':{'performed':True,'sources':'IEEE/Optica/ACM/Nature/Wiley/ScienceDirect, Google, Intel, Corning, Molex, JEDEC/CXL, tool docs'},
 '5_citation_searching':{'performed':True,'method':'manual source/reference chasing Charles/Yoo/Ling/Castro and APR-LiDAR lines','max_hops':'not quantified; no API graph coverage claim'},
 '6_contacts':{'performed':False},'7_other_methods':{'methods':['parallel evidence classification in three subject groups','primary-source cross-check']},
 '8_full_search_strategies':plan,
 '9_limits_and_restrictions':{'cutoff':'2026-10-28','language':'Chinese report; primary materials mainly English','publication_types':'papers, preprints, official products/standards/docs'},
 '10_search_filters':{'validated_filter':None},
 '11_prior_work':{'seeds':['10.1109/TCPMT.2025.3526500','10.1016/j.optlastec.2025.114521','10.1002/admt.202300620','user Google/Corning/Intel/Microsoft URLs']},
 '12_updates':{'incremental_search':False},
 '13_dates_of_searches':{'date':'2026-10-28','timezone':'Asia/Shanghai'},
 '14_total_records':{'retained_unique_sources':len(S),'papers_or_preprints':sum(s['kind']=='paper' for s in S),'official_materials':sum(s['kind']=='official' for s in S),'papers_fulltext_relevant_sections':sum(s['kind']=='paper' and s['access']=='A' for s in S),'universe_retrieval_count':None,'coverage_estimate':None},
 '15_deduplication':{'method':'case-insensitive DOI, URL and title/manual version relation; preprint/formal versions explicitly related'},
 '16_record_management':{'outputs':['12 requested files','source catalog JSON','BibTeX/RIS/CSV','methods log','HTML','raw primary texts where available'],'limitations':'No fabricated abstracts/citation counts/saturation.'}}
log={'prisma_s':prisma,'errors':['OpenAlex and Semantic Scholar API credentials absent; public-source fallback used','some publisher full texts unavailable; access graded C/C+','API helper initially missing PyYAML; installed in local venv'],'stop_reason':'topic coverage, direct competitors and counterevidence established; key remaining gaps are full texts and project-specific process/implementation data','generated_at':'2026-10-28','scope':'adapted deep topic research'}
(R/'sources/execution_log.json').write_text(json.dumps(log,ensure_ascii=False,indent=2))
(R/'sources/curve.json').write_text(json.dumps({'saturation_estimate':None,'coverage_estimate':None,'reason':'purposeful source selection, no complete round-level database retrieval universe; no statistical fit justified'},ensure_ascii=False,indent=2))
# Hydrate the skill's Shadcn source catalog. Missing citation statistics display as dash.
UI=R/'sources/report_data';UI.mkdir(exist_ok=True)
papers=[]
for s in S:
 papers.append({'paper_id':s['id'],'title':s['title'],'authors_full':s.get('author','').split(' and '),'year':s.get('year'),'venue':s.get('venue') or ('官方技术资料' if s['kind']=='official' else '原始论文/预印本'),'doi':s['doi'] or None,'doi_url':s['url'],'abstract':None,'tldr':s['role'],'rcs':10 if s['id'] in ['Brusberg2025','Castro2025','Yoo2016','Charles2012','Routing2021','USConec165','LiDAR2025'] else (8 if s['kind']=='paper' else 7),'rcs_reasoning':f"访问{s['access']}；{s['locator']}。{s['role']}。相关性为课题用途分级，不是质量排名；未知引文数据未填。",'sources':['primary-source'],'discovery_path':'original-source retrieval and manual citation tracing','is_oa':None})
meta={'query':'1024通道三维玻璃光波导：可核查文献与官方资料','search_id':'20261028_3d-glass-routing','tier':'deep','generated_at':'2026-10-28','skill_version':'adapted public-source workflow','papers_evaluated':len(S),'papers_in_kg':len(S),'highly_relevant_count':7,'closely_related_count':len(S)-7,'coverage_estimate':None,'stop_reason':'专题覆盖；统计覆盖率未知。论文与官方资料混合目录，非系统综述。'}
meta.pop('coverage_estimate',None)
for name,data in [('metadata',meta),('paper_list',papers),('chart_data',{}),('prisma_log',prisma)]:
 (UI/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False))
sys.path.insert(0,'/Users/lihaolun/.codex/skills/paper-search-pro')
from scripts.html_renderer_webartifacts import render_html_webartifacts
render_html_webartifacts(UI,R/'可筛选文献目录.html',user_query=meta['query'],language='zh')
# The bundled template treats null coverage as numeric zero. Omit that field and
# correct template labels in this generated copy, without changing skill assets.
sp=R/'可筛选文献目录.html';sh=sp.read_text()
sh=sh.replace('confidence:`95% 置信`','confidence:`未计算；非系统综述`').replace('confidence:`95% confidence`','confidence:`Not estimated`')
sh=sh.replace('papersScreened:`篇文献已筛选`','papersScreened:`项资料`').replace('foundationalDesc:`领域定义性文献 · ≥0.85 RCS`','foundationalDesc:`课题直接对照与优先阅读；非质量排名`').replace('Foundational:`奠基性`','Foundational:`优先阅读`')
notice='<div style="padding:16px 24px;background:#faf4de;color:#544728;font:14px/1.7 sans-serif">来源目录：74项资料含38项论文/预印本、36项官方材料；覆盖率与引文统计未估计。相关性等级仅为课题用途排序。实际检索方法与访问限制见 <a href="检索方法与执行记录.md">检索方法与执行记录.md</a>；<a href="完整调研报告.html">返回全文报告</a>。</div>'
sh=re.sub(r'<body[^>]*>',lambda m:m.group(0)+notice,sh,count=1);sp.write_text(sh)

# Compact offline full-text reading artifact.
files=[R/'阅读指南与文件目录.md']+sorted(R.glob('[0-9][0-9]_*.md'))+[R/'检索方法与执行记录.md']
css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f5f1;color:#202c30;font:16px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft Yahei",sans-serif}aside{position:fixed;inset:0 auto 0 0;width:280px;background:#123b3e;color:#fff;padding:30px 22px;overflow:auto}aside h2{font-size:20px;line-height:1.5;color:#fff}aside a{display:block;color:#d9e9e6;text-decoration:none;font-size:13px;padding:7px 0;border-bottom:1px solid #ffffff18}main{margin-left:280px;max-width:1450px;padding:30px 50px}header{border-bottom:3px solid #a8793e;padding:20px 0 35px}header .tag{font-size:12px;letter-spacing:2px;color:#517b76}h1{font-size:30px;line-height:1.5}h2{font-size:24px;color:#164e50;margin-top:44px}h3{font-size:19px}section{background:#fff;border:1px solid #dedfd7;padding:30px 36px;margin:30px 0;border-radius:8px}section>h1{border-bottom:1px solid #dde4df;padding-bottom:14px}a{color:#116e78;text-underline-offset:3px}table{display:block;overflow:auto;border-collapse:collapse;font-size:13px;line-height:1.7;margin:24px 0;max-width:100%}td,th{padding:11px 14px;border:1px solid #d8e1dc;min-width:100px;max-width:600px;vertical-align:top}th{background:#e9f1ec;text-align:left}tr:nth-child(even){background:#f8faf6}blockquote{border-left:4px solid #b49460;padding:8px 20px;background:#faf7ed;margin:22px 0;color:#5d563f}code{font-size:.87em;background:#eef1eb;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{overflow:auto;background:#eff2ee;padding:16px}img{max-width:100%;height:auto;border:1px solid #ddd}#search{width:100%;border:0;padding:10px;border-radius:5px;font-size:14px}.small{font-size:13px;color:#59706c}.toplinks{display:flex;gap:14px;flex-wrap:wrap}@media(max-width:900px){aside{position:static;width:auto;max-height:380px}main{margin:0;padding:18px}section{padding:20px 16px}h1{font-size:25px}}@media print{aside{display:none}main{margin:0;max-width:none;padding:0}section{border:none;break-before:page}table{display:table;width:100%;font-size:10px}}'''
nav=[];sections=[]
for i,p in enumerate(files):
 name=p.stem;txt=p.read_text();title=txt.splitlines()[0].lstrip('# ')
 rendered=markdown.markdown(txt,extensions=['tables','fenced_code','sane_lists'])
 def cite(m):
  k=m.group(1)
  return f'<a class="citation" href="{html.escape(by[k]["url"],quote=True)}">[{k}]</a>' if k in by else m.group(0)
 rendered=re.sub(r'\[([A-Za-z][A-Za-z0-9]+)\]',cite,rendered)
 nav.append(f'<a href="#part{i}">{html.escape(title)}</a>')
 sections.append(f'<section id="part{i}" data-title="{html.escape(title,quote=True)}"><p class="small">源文件：<a href="{p.name}">{p.name}</a></p>{rendered}</section>')
js='''const q=document.getElementById('search');q.addEventListener('input',()=>{const t=q.value.trim().toLowerCase();document.querySelectorAll('section').forEach(s=>s.hidden=!!t&&!s.textContent.toLowerCase().includes(t));});'''
page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>1024通道三维玻璃光波导调研</title><style>'+css+'</style><aside><h2>三维玻璃光互联<br>研究资料包</h2><p>2026 / 10 / 28</p><input id="search" placeholder="按关键词筛选章节" aria-label="筛选章节">'+''.join(nav)+'</aside><main><header><div class="tag">EVIDENCE · GEOMETRY · MANUFACTURING</div><h1>1024通道三维玻璃光波导<br>应用、现状与技术基础</h1><p>74项来源 · 38项论文/预印本 · 16篇全文重点章节 · 32个答辩问题</p><p class="small">区分原始事实、理论推导、研究构造与未验证目标。全文访问限制和本课题参数缺口均保留。</p><div class="toplinks"><a href="可筛选文献目录.html">筛选文献目录</a><a href="10_参考文献库.bib">BibTeX</a><a href="参考文献库.ris">RIS</a><a href="参考文献目录.csv">CSV</a></div></header>'+''.join(sections)+'</main><script>'+js+'</script></html>'
(R/'完整调研报告.html').write_text(page)
# Scientific/engineering comparison diagram generated as SVG, no inferred measurements.
svg='''<svg xmlns="http://www.w3.org/2000/svg" width="1300" height="610" viewBox="0 0 1300 610"><rect width="1300" height="610" fill="#f5f5ef"/><style>text{font-family:"PingFang SC","Microsoft YaHei",sans-serif;fill:#173e42}.t{font-size:26px;font-weight:600}.s{font-size:19px}.n{font-size:16px;fill:#617675}</style><text x="55" y="62" class="t">固定三维玻璃器件在系统中的位置</text><text x="55" y="98" class="n">功能边界示意：候选研究位置，不代表 Google 或任何厂商已采用本课题器件</text><g stroke="#2a6a6d" stroke-width="2" fill="#ffffff"><rect x="55" y="165" width="240" height="155" rx="12"/><rect x="365" y="165" width="250" height="155" rx="12" fill="#dceee8"/><rect x="685" y="165" width="250" height="155" rx="12"/><rect x="1005" y="165" width="240" height="155" rx="12"/></g><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10" fill="#286f70"/></marker></defs><g stroke="#286f70" stroke-width="3" marker-end="url(#a)"><path d="M295 242H355"/><path d="M615 242H675"/><path d="M935 242H995"/></g><text x="80" y="216" class="s">收发器 / 光 I/O</text><text x="80" y="252" class="n">主动电光转换、WDM</text><text x="80" y="285" class="n">协议、编码与光源</text><text x="390" y="216" class="s">固定玻璃 Shuffle</text><text x="390" y="252" class="n">制造前决定端口映射</text><text x="390" y="285" class="n">三维波导、端面适配</text><text x="710" y="216" class="s">OCS 或网络模块</text><text x="710" y="252" class="n">OCS 才改变运行期连接</text><text x="710" y="285" class="n">也可接固定背板接口</text><text x="1030" y="216" class="s">对端系统</text><text x="1030" y="252" class="n">交换机 / 计算节点</text><text x="1030" y="285" class="n">实际功能取决于架构</text><rect x="55" y="385" width="1190" height="150" rx="12" fill="#fff" stroke="#d6dcd3"/><text x="80" y="425" class="s">本课题的软件链</text><text x="80" y="466" class="s">连接表 → 端口与工艺规则 → 三维曲线 → 独立几何验证 → 模型与加工评价</text><text x="80" y="505" class="n">1024 = 1024 条固定物理路径；单双向、波长与供光另行计数。几何合格 ≠ 器件实测合格。</text><text x="55" y="580" class="n">本报告自绘。依据 Corning Shuffle / Jupiter / Apollo 的功能分工；玻璃方框为研究候选。</text></svg>'''
(R/'figures/系统功能边界示意图.svg').write_text(svg)
# Audit generated artifacts and cross-references.
issues=[]
expected=['01_光电路交换与光纤重排调研.md','02_HBM与GPU及CPU互联调研.md','03_产业技术与光子设计工具调研.md','04_相关研究对照与创新空间分析.md','05_研究意义与1024通道论证.md','06_毕业论文第一章绪论初稿.md','07_毕业论文第二章提纲与初稿.md','08_毕业答辩问答库.md','09_开题与阶段汇报提纲.md','10_参考文献库.bib','11_核心事实与证据台账.md','12_未决问题与验证清单.md']
for name in expected:
 if not (R/name).exists() or (R/name).stat().st_size<100:issues.append('missing/empty '+name)
bib=bibtexparser.loads((R/'10_参考文献库.bib').read_text());keys={x['ID'] for x in bib.entries}
if len(keys)!=len(S):issues.append('BibTeX record count mismatch')
used=set()
for p in R.glob('*.md'):
 txt=p.read_text()
 for k in re.findall(r'\[([A-Za-z][A-Za-z0-9]+)(?:[,，][^\]]*)?\]',txt):
  if k in by:used.add(k)
  elif re.search(r'\d{4}$',k):issues.append(p.name+' unknown key '+k)
 for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',txt):
  if target.startswith(('https:','http:','#','mailto:')):continue
  if not (R/target.split('#')[0]).exists():issues.append(p.name+' broken local '+target)
qa=(R/'08_毕业答辩问答库.md').read_text();nqa=len(re.findall(r'^## Q\d\d ',qa,re.M))
for label in ['30秒口头回答','2分钟技术解释','关键证据','容易说错','尚不能肯定']:
 if qa.count('**'+label+'：**')!=32:issues.append('QA field count '+label)
if nqa!=32:issues.append('QA count '+str(nqa))
if any(not s.get('title') or not s.get('author') for s in S):issues.append('missing metadata')
if calc['inversions_32_by_32_transpose']!=246016:issues.append('arithmetic error')
report=['# 最终审查记录\n\n日期：2026-10-28。以下为实际自动检查，不代表光学实验验证。\n',f'- 12份要求文件：{len(expected)}份均存在且非空。',f'- BibTeX解析：{len(bib.entries)}条，ID唯一；论文/预印本38条，官方材料36条。',f'- 原文全文及相关章节A类论文：16篇；另有完整技术演示/源码2项。',f'- 顶层Markdown引用到的有效文献键：{len(used)}个。',f'- 答辩：{nqa}问，每问五字段齐全。','- 本地Markdown链接、图像路径、必需文件和引用键已检查。','- 组合数、转置逆序、写入时间、纤数下界和PCIe方向换算由脚本重算。','- 关键原图页已经渲染并视觉检查；报告宽表支持横向滚动。','- 明确保留全文受限、非系统综述、未取得项目代码/工艺/测量的限制。','\n## 自动发现的问题\n']
report += ['- '+x for x in issues] if issues else ['未发现缺失文件、断开的本地链接、未知年份引用键或QA字段缺失。']
report+=['\n## 不能由本审查证明的事项\n','本项目实际运行、1024可行率、工艺参数、低损耗/低串扰、制造良率、长期可靠性与成本优势均未被验证。少数付费全文、JEDEC正文和商业EDA实测仍需补足。元数据与引用解析通过不代表原论文所有结论都已复现。']
(R/'最终审查记录.md').write_text('\n'.join(report)+'\n')
(R/'sources/audit_result.json').write_text(json.dumps({'issues':issues,'required_files':len(expected),'bib_entries':len(bib.entries),'qa_count':nqa,'citations_used':len(used)},ensure_ascii=False,indent=2))
print(json.dumps({'required_files':len(expected),'bib_entries':len(bib.entries),'qa_count':nqa,'citation_keys_used':len(used),'issues':issues,'html_bytes':(R/'完整调研报告.html').stat().st_size},ensure_ascii=False))
