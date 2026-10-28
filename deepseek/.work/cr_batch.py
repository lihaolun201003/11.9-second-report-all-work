import sys, json, time
sys.path.insert(0,'.')
import lib
dois = """10.1109/tcpmt.2025.3526500
10.1002/admt.202300620
10.1016/j.optlastec.2025.114521
10.1145/3544216.3544265
10.1145/3698364.3705355
10.1109/tcad.2025.3624197
10.1109/iccad66269.2025.11240728
10.1109/tcad.2014.2317575
10.1109/iccad51958.2021.9643451
10.1109/jlt.2025.3539231
10.1364/ao.51.006489
10.1117/12.3083656
10.1109/date.2006.244180
10.1587/transele.e101.c.509
10.1364/oe.27.032465
10.1109/icsj.2017.8240138
10.3389/aot.2023.1244009
10.1364/optica.559260
10.1364/oe.20.017667
10.1109/jlt.2014.2373051
10.1109/jphot.2020.3039900
10.1364/ol.551272
10.1103/physrevapplied.22.064079
10.1038/s41598-021-03116-y
10.1109/oecc48412.2020.9273659
10.1364/ol.470670
10.1117/1.ap.3.2.024002
10.1002/lpor.201300195
10.1515/nanoph-2015-0020
10.1109/oecc.2018.8730115
10.1117/12.3007419
10.1109/vlsid51830.2021.00047
10.1007/s10825-022-01989-4
10.1143/jjap.44.l1446
10.1038/s41598-024-84274-7
10.1002/lpor.201700237
10.1109/jlt.2023.3320908
10.1109/iccad.2013.6691109
10.1145/3195970.3196093
10.1109/tcad.2020.2971536
10.1093/jair.2994
10.1109/tec.1961.5219222
10.1364/ofc.2021.th1a.37
10.1088/2631-7990/ab4d51
10.1117/1.apn.2.3.036002
10.1109/ipc60965.2024.10799666
10.1109/jlt.2008.2006280
10.1364/acpc.2017.m1c.6
10.1364/oe.19.005698
10.1038/s41377-020-0272-5""".split()
out={}
for d in dois:
    m = lib.crossref_doi(d)
    if not m:
        print("FAIL", d); out[d]=None; continue
    out[d]={
      "title": (m.get("title") or [""])[0],
      "container": (m.get("container-title") or [""])[0],
      "volume": m.get("volume"), "issue": m.get("issue"), "page": m.get("page"),
      "year": (m.get("issued",{}).get("date-parts") or [[None]])[0][0],
      "authors": [ (a.get("given","")+" "+a.get("family","")).strip() for a in m.get("author",[])][:8],
      "article-number": m.get("article-number"),
      "type": m.get("type"),
    }
    print(d, "|", out[d]["year"], "|", out[d]["container"][:45], "|", out[d]["volume"], out[d]["issue"], out[d]["page"])
    time.sleep(1.2)
json.dump(out, open('cr_meta.json','w'), ensure_ascii=False, indent=1)
