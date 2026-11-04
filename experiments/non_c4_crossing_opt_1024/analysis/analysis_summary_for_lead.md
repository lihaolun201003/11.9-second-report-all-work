# Crossing analysis - summary for the Lead

**Headline numbers**
- 11890 crossing events / 9797 crossing pairs over 13/21 heights; per-route max=83, p95=60.0, mean=37.63 (632 of 656 movable routes involved; 368 manual + 24 movable routes clean).
- Crossing mass: Z1 movable heights 4510 (37.9%), Z2 grid heights L15-L19 7200 (60.5%), corner heights L9/L14/Z2_INTERFACE only 180 (1.5%); manual heights 0.
- Classification: forced=884 (all direct/direct interface flats), avoidable-by-2D-repath=3868, needs-height-separation=7138.
- No lead-involved crossing at all: the 1848 interface leads never cross; all interface events are direct-body/direct-body.

**Top-5 findings**
1. Crossings are an ORIENTATION/QUADRANT problem: Z1 vertical x horizontal port chords alternate 100% of the time, Z2 corner-family cross pairs 73%, within-family only ~19-20%.
2. L9/L14/Z2_INTERFACE are NOT a lucky permutation - they hold the 36 corner-bundle orbits (short chords inside one quadrant, families in disjoint corners), so cross-family crossings = 0 and only the 4 x 15 = 60 staircase crossings remain.
3. L15-L19 hold the 64 grid orbits (150-220 mm diagonals through the board centre): 91-93% of their crossings are cross-family, 83-86% of all route pairs actually cross (56-59% alternate) -> high crossings are structural for that orbit block.
4. fanout/leads are NOT the problem (0 lead crossings); interface-height risk is the 100 direct/direct routes, which alone own all 884 forced crossings.
5. Baseline topological lower bound = 7868 alternating same-height pairs; keeping C4 orbits whole can only reach ~6584, but a C4-free per-route assignment reaches 724 (-90.8%).

**L9 vs L15 in 4 lines**
- Both planes: 12 C4 orbits x 4 families = 48 routes; L9 = 60 crossings, L15 = 1246.
- L9 carries orbits 233-244 = E-connectors 3-8 x S-connectors 9-14: every chord 57-95 mm, each family confined to one corner -> cross-family crossings 0, within-family 60.
- L15 carries orbits 181-192 = the 8x8 grid pairing: chord medians 133-178 mm, all families cross the centre -> within-family 110, cross-family 1136.
- The 60 = 4 families x 15 staircase crossings between the two shifted port rows (E07 row vs E08 row, y shift 9 mm, target-x shift only 0.25 mm).

**Top-10 routes by crossings** (route(id): crossings)
522(Z2_ES,L17):83, 520(Z2_SW,L17):72, 765(Z2_EN,L15):72, 541(Z2_EN,L17):71, 537(Z2_EN,L17):69
540(Z2_SW,L17):69, 536(Z2_SW,L17):68, 564(Z2_SW,L17):68, 571(Z2_NW,L18):68, 538(Z2_ES,L17):67
**Recommendation for the C4-free layer assignment**
- Drop the C4-orbit-on-one-plane rule: biggest lever (orbit-respecting best ~6584 vs C4-free 724 alternating pairs).
- C4-free distribution to start from: Z1 {6:57, 7:57, 8:60, 20:22, 1001:60}, Z2 {9:51, 14:51, 15:51, 16:51, 17:49, 18:49, 19:49, 1002:49} (~105 interface-direct routes).
- If orbits must stay whole: fallback = Z1 orientation split (NS/SN vs EW/WE on disjoint heights) + Z2 corner/grid split; the floor stays ~5000-6600, no path to 0.
- Keep <=60 routes/height and ~100 interface-direct routes (the 100 direct already own all 884 forced crossings).
- Floor of ~724 same-height alternating pairs that no 2D router can remove; the crossing-aware router can only clean the ~3868 avoidable events.
**Artifacts**
- analysis/crossing_analysis.json (8.4 MB: full crossing records + answers)
- analysis/crossing_conflict_graph.json (3.7 MB: 656 nodes / 54545 edges)
- analysis/crossing_source_report.md (Chinese full report)
- analysis/plots/ (28 PNG: 21 per-height + 7 aggregate)
- analysis/scripts/run_all.py (reproduces everything deterministically)
