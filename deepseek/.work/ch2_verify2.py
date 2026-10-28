import sys, json, time
sys.path.insert(0, '.')
import lib

DOIS = [
 "10.1364/OPEX.13.005676",
 "10.1145/800260.809014",
 "10.1017/CBO9780511546877",
 "10.1109/TRO.2004.829820",
 "10.1007/978-3-642-97385-7",
 "10.1109/9780470546376",
 "10.1007/978-3-642-23366-1",
 "10.1007/978-3-642-23366-1_1",
 "10.1364/AOP.6.000293",
 "10.1002/j.1538-7305.1969.tb01167.x",
]
res = {}
for d in DOIS:
    m = lib.crossref_doi(d)
    if m:
        res[d] = {"title": (m.get("title") or [""])[0],
                  "authors": [((a.get("given") or "") + " " + (a.get("family") or "")).strip() for a in m.get("author", [])][:8],
                  "venue": (m.get("container-title") or [""])[0],
                  "year": ((m.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0],
                  "volume": m.get("volume"), "issue": m.get("issue"), "page": m.get("page"), "type": m.get("type")}
        r = res[d]
        print("OK ", d, "|", r["year"], "|", r["title"][:85], "|", r["venue"][:45], "|", r["volume"], r["issue"], r["page"])
    else:
        print("FAIL", d)
    time.sleep(0.8)
json.dump(res, open("ch2_verified2.json", "w"), ensure_ascii=False, indent=1)

for q in ["slit beam shaping method femtosecond laser symmetric waveguides",
          "A solution to line-routing problems on the continuous plane",
          "self-organized nanogratings femtosecond laser silica Taylor",
          "fiber-to-waveguide coupling loss mode field mismatch silicon photonics"]:
    print("\n### ", q)
    for it in lib.crossref_search(q, rows=5):
        print("   ", it["doi"], "|", it["year"], "|", (it["title"] or "")[:90], "|", (it["venue"] or "")[:40])
    time.sleep(1.2)
