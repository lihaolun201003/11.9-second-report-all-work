import json, sys, time
sys.path.insert(0,'.')
import lib
QS = [
 "femtosecond laser micromachining transparent materials",
 "ultrafast laser inscription photonic devices review",
 "femtosecond laser written waveguides glass low loss review",
 "writing waveguides in glass with a femtosecond laser",
 "ion exchanged glass waveguide photonic integrated circuit",
 "polymer optical waveguide backplane board",
 "optical backplane high speed interconnect",
 "three dimensional optical interconnect waveguide fabricated laser",
 "waveguide shuffle optical interconnect",
 "1024 channel optical switch",
 "thousand port optical switch datacenter",
 "robotic fiber cross connect patch panel automation",
 "large scale matrix optical switch 384 port",
 "fan-out waveguide multicore fiber coupling loss",
 "HBM high bandwidth memory review",
 "HBM3 bandwidth TSV stack",
 "memory disaggregation CXL performance evaluation",
 "co-packaged optics silicon photonics energy efficiency",
 "silicon photonics transceiver energy per bit datacenter",
 "photonic integrated circuit placement routing automation",
]
out={}
for q in QS:
    r=lib.crossref_search(q, rows=8)
    print('###',q)
    for it in r:
        print('  ', it['year'], '|', (it['title'] or '')[:110], '|', it['doi'], '|', (it['venue'] or '')[:40])
    for it in r:
        out.setdefault(it['doi'], it)
    time.sleep(0.8)
json.dump(out, open('q2_results.json','w'), ensure_ascii=False, indent=1)
print('unique', len(out))
