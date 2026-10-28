from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests
from pypdf import PdfReader
root=Path(__file__).resolve().parents[1]/'sources/raw'
u={
'optical_hbm2025':'https://www.csl.cornell.edu/~cbatten/pdfs/ou-optical-mem-llm-cal2025.pdf',
'pond2023':'https://pages.cs.wisc.edu/~markhill/papers/asplos2023_pond.pdf',
'against_cxl2023':'https://conferences.sigcomm.org/hotnets/2023/papers/hotnets23_levis.pdf',
'ocm2022':'https://lightwave.ee.columbia.edu/sites/lightwave.ee.columbia.edu/files/content/publications/2022/optically_connected_memory.pdf',
'rao2016':'https://cseweb.ucsd.edu/~gmporter/papers/memdisagg-ancs16.pdf',
'cxl_intro2023':'https://arxiv.org/pdf/2306.11227',
'apr2024v1':'https://arxiv.org/pdf/2410.01260v1',
'placement2025v1':'https://arxiv.org/pdf/2504.18813v1',
'lidar2025v1':'https://arxiv.org/pdf/2505.17239v1'}
def get(x):
 k,v=x;p=root/(k+'.pdf')
 try:
  r=requests.get(v,timeout=50);r.raise_for_status();p.write_bytes(r.content);rd=PdfReader(p);(root/(k+'.txt')).write_text('\n\n'.join('PDF PAGE '+str(i+1)+'\n'+(q.extract_text() or '') for i,q in enumerate(rd.pages)));return k,len(rd.pages)
 except Exception as e:
  if p.exists():p.unlink()
  return k,type(e).__name__
with ThreadPoolExecutor(max_workers=3) as ex:
 for r in ex.map(get,u.items()):print(r,flush=True)
