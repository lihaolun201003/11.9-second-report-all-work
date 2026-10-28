import json, sys, time
sys.path.insert(0,'.')
import lib

QUERIES = {
 "A_OCS": [
   "optical circuit switch data center network",
   "MEMS optical circuit switch large port count",
   "Jupiter datacenter network optical circuit switch",
   "hybrid optical circuit switching packet switching datacenter",
   "optical circuit switch Clos topology reconfiguration",
   "large scale optical cross-connect switch datacenter",
 ],
 "A_Shuffle": [
   "fiber shuffle optical interconnect high density",
   "optical shuffle waveguide backplane",
   "three-dimensional waveguide shuffle optical interconnect",
   "optical backplane passive optical interconnect waveguide",
   "waveguide shuffle network multiprocessor",
   "fiber shuffle module data center cabling",
   "MPO ferrule high density fiber connector loss",
 ],
 "B_HBM": [
   "high bandwidth memory HBM DRAM stack TSV",
   "HBM3E memory interface bandwidth",
   "HBM4 standard JEDEC",
   "optical interconnect high bandwidth memory",
   "optically connected memory HBM",
   "memory disaggregation optical interconnect datacenter",
   "co-packaged optics AI accelerator interconnect",
   "optical I/O chiplet silicon photonics",
   "CXL memory expansion pooling",
   "photonic memory interconnect rack scale",
   "GPU interconnect NVLink scale-up network",
   "optical scale-up network AI cluster",
 ],
 "C_Glass": [
   "femtosecond laser direct writing optical waveguide glass",
   "ultrafast laser inscription photonic integrated circuits review",
   "ion exchange glass waveguide optical interconnect",
   "glass optical interposer co-packaged optics waveguide",
   "femtosecond laser written waveguide bending loss",
   "laser written 3D photonic interconnect multicore fiber",
   "fan-in fan-out multicore fiber femtosecond laser",
   "polymer waveguide optical backplane",
   "silicon photonics transceiver energy per bit",
   "glass waveguide optical shuffle",
   "thin glass waveguide optical interconnect 3D",
   "femtosecond laser glass waveguide low loss",
 ],
 "D_Routing_EDA": [
   "automated routing photonic integrated circuits",
   "waveguide routing algorithm optical interconnect layout",
   "curvilinear routing silicon photonics",
   "photonic design automation electronic photonic design tool",
   "three-dimensional path planning waveguide routing",
   "optical interconnect routing algorithm optimization",
   "bend radius aware waveguide routing",
   "KLayout photonic layout",
   "Lumerical photonic simulation",
 ],
 "E_Scale1024": [
   "1024 channel optical interconnect",
   "large port count optical switch 1024",
   "high channel count optical fiber array",
   "1024 waveguide",
   "thousand fiber optical interconnect",
   "optical interconnect exascale computing",
   "wafer scale optical interconnect",
   "optical fan-out high density parallel",
 ],
}
import os
res={}
if os.path.exists('candidates.json'):
    for it in json.load(open('candidates.json')): res[it['doi']]=it
for grp, qs in QUERIES.items():
    for q in qs:
        r = lib.crossref_search(q, rows=15)
        for it in r:
            it['group']=grp; it['query']=q
            if it['doi'] not in res:
                res[it['doi']]=it
        print(f"{grp} | {q} -> {len(r)}", file=sys.stderr)
        json.dump(list(res.values()), open('candidates.json','w'), ensure_ascii=False, indent=1)
        time.sleep(1.0)
json.dump(list(res.values()), open('candidates.json','w'), ensure_ascii=False, indent=1)
print("TOTAL", len(res))
