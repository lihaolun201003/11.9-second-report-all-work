import sys, json, time
sys.path.insert(0, '.')
import lib

QUERIES = [
 "Bends in optical dielectric guides Marcatili",
 "Dielectric rectangular waveguide and directional coupler for integrated optics Marcatili",
 "Slit beam shaping method for femtosecond laser direct-write fabrication of symmetric waveguides in bulk glasses",
 "Heat accumulation effects in femtosecond laser-written waveguides with variable repetition rate",
 "Effect of refractive index-mismatch on laser microfabrication in silica glass",
 "femtosecond laser written waveguide bend loss curvature",
 "femtosecond laser waveguide crossings glass low loss",
 "three-dimensional photonic integrated circuits femtosecond laser direct writing",
 "Euler bend silicon photonics low loss waveguide",
 "curvature-aware routing photonic integrated circuits waveguide",
 "automated waveguide routing photonic integrated circuit algorithm",
 "Ultra-low crosstalk and low-loss multi-core fiber design fabrication Hayashi",
 "Femtosecond optical breakdown in dielectrics Lenzner",
 "Optical ablation by high-power short-pulse lasers Stuart",
 "Femtosecond laser micromachining photonic devices review Della Valle Osellame",
 "multilayer optical waveguide routing three-dimensional interconnect",
 "design rule checking silicon photonics layout verification",
 "Fundamentals of Optical Waveguides Okamoto",
 "Optical Waveguide Theory Snyder Love",
 "Fiber-Optic Communication Systems Agrawal",
 "Curves and Surfaces for CAGD Farin",
 "Algorithms for VLSI Physical Design Automation Sherwani",
 "Wire routing by optimizing channel assignment within large apertures Hashimoto Stevens",
 "A solution to line-routing problems on the continuous plane Hightower",
 "femtosecond laser waveguide writing review low loss mid-infrared",
]

res = {}
for q in QUERIES:
    items = lib.crossref_search(q, rows=6)
    res[q] = items
    print("\n### ", q)
    for it in items[:6]:
        print("   %s | %s | %s | %s" % (it["doi"], it["year"], (it["title"] or "")[:95], (it["venue"] or "")[:40]))
    time.sleep(1.2)
json.dump(res, open("ch2_search.json", "w"), ensure_ascii=False, indent=1)
print("\nDONE", len(res))
