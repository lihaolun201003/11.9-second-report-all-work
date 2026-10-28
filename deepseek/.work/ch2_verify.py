import sys, json, time
sys.path.insert(0, '.')
import lib

DOIS = [
 "10.1038/nphoton.2008.47",
 "10.1364/OL.21.001729",
 "10.1002/admt.202300620",
 "10.1109/JQE.1973.1077767",
 "10.1109/5.104225",
 "10.1364/JOSA.66.000216",
 "10.1002/j.1538-7305.1969.tb01177.x",
 "10.1109/JQE.1975.1068563",
 "10.1109/TSSC.1968.300136",
 "10.1177/0278364911406761",
 "10.1109/TEC.1961.5219222",
 "10.1145/201310.201328",
 "10.1137/0114025",
 "10.1109/PROC.1964.3442",
 "10.1364/OL.32.002801",
 "10.1364/OE.13.005676",
 "10.1364/OE.13.004708",
 "10.1364/OE.16.009443",
 "10.1364/AOP.6.000293",
 "10.1038/lsa.2014.30",
 "10.1364/JOSA.62.001267",
 "10.1364/JOSAA.11.000963",
 "10.1109/JLT.2007.902113",
 "10.1109/OIC.2015.7115671",
 "10.1364/JOSAA.11.000963",
 "10.1109/JLT.2008.2006280",
 "10.1364/AO.47.000000",
]
out = {}
for d in DOIS:
    if d in out: continue
    m = lib.crossref_doi(d)
    if m:
        out[d] = {
            "title": (m.get("title") or [""])[0],
            "authors": [((a.get("given") or "") + " " + (a.get("family") or "")).strip() for a in m.get("author", [])][:10],
            "venue": (m.get("container-title") or [""])[0],
            "year": ((m.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0],
            "volume": m.get("volume"), "issue": m.get("issue"), "page": m.get("page"),
            "type": m.get("type"),
        }
        print("OK ", d, "|", out[d]["year"], "|", out[d]["title"][:80], "|", out[d]["venue"][:50], "|", out[d]["volume"], out[d]["issue"], out[d]["page"])
    else:
        print("FAIL", d)
    time.sleep(0.7)
json.dump(out, open("ch2_verified.json", "w"), ensure_ascii=False, indent=1)
print("saved", len(out))
