# G4_best

Source (accepted layout): `experiments\xyz_joint_g4_1024\07_best_valid`

- routes: **1024** (manual-U 368, groups 8)
- crossings (sum of exact-z events): **1185**
- routes SHA256: `b74ae51185edcef43419c3157d07e24237bf05f10e50321310b554f487e9e77a`
- generated: 2026-11-04 19:50:20

| # | height | z (mm) | body routes | manual-U | groups | crossings | unique pairs | avg/route | max/route | mid-layer routes | covered blocks | idle blocks | congested blocks | max X/block |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | L2 | -0.35 | 35 | 34 | 2 | **0** | 0 | 0.00 | 0 | 0 | 71 | 29 | 0 | 0 |
| 2 | L3 | -0.30 | 68 | 62 | 1 | **26** | 26 | 0.77 | 13 | 0 | 80 | 20 | 6 | 6 |
| 3 | L4 | -0.25 | 62 | 62 | 2 | **0** | 0 | 0.00 | 0 | 0 | 80 | 20 | 0 | 0 |
| 4 | L5 | -0.20 | 89 | 87 | 2 | **4** | 2 | 0.09 | 2 | 0 | 80 | 20 | 0 | 1 |
| 5 | L6 | -0.15 | 57 | 0 | 0 | **88** | 85 | 3.09 | 12 | 13 | 100 | 0 | 18 | 19 |
| 6 | L7 | -0.10 | 53 | 0 | 0 | **50** | 45 | 1.89 | 10 | 17 | 96 | 4 | 10 | 8 |
| 7 | L20 | -0.05 | 45 | 0 | 0 | **44** | 40 | 1.96 | 7 | 12 | 97 | 3 | 12 | 9 |
| 8 | Z1_INTERFACE | +0.00 | 512 | 256 | 4 | **82** | 77 | 0.32 | 11 | 8 | 100 | 0 | 14 | 12 |
| 9 | L8 | +0.05 | 39 | 0 | 0 | **66** | 63 | 3.38 | 9 | 5 | 98 | 2 | 16 | 8 |
| 10 | L9 | +0.10 | 55 | 2 | 1 | **109** | 107 | 3.96 | 13 | 7 | 99 | 1 | 15 | 18 |
| 11 | L10 | +0.15 | 25 | 9 | 3 | **52** | 50 | 4.16 | 10 | 0 | 88 | 12 | 15 | 4 |
| 12 | L11 | +0.20 | 38 | 11 | 2 | **43** | 31 | 2.26 | 12 | 1 | 98 | 2 | 9 | 9 |
| 13 | L12 | +0.25 | 52 | 44 | 3 | **33** | 27 | 1.27 | 8 | 0 | 92 | 8 | 8 | 7 |
| 14 | L13 | +0.30 | 50 | 40 | 1 | **38** | 33 | 1.52 | 10 | 0 | 92 | 8 | 10 | 7 |
| 15 | L14 | +0.35 | 47 | 0 | 0 | **81** | 81 | 3.45 | 12 | 0 | 98 | 2 | 12 | 24 |
| 16 | L15 | +0.40 | 50 | 6 | 1 | **77** | 71 | 3.08 | 12 | 0 | 98 | 2 | 15 | 11 |
| 17 | L16 | +0.45 | 46 | 0 | 0 | **67** | 67 | 2.91 | 8 | 0 | 98 | 2 | 13 | 17 |
| 18 | Z2_INTERFACE | +0.50 | 512 | 112 | 4 | **130** | 126 | 0.51 | 19 | 0 | 100 | 0 | 21 | 31 |
| 19 | L17 | +0.55 | 47 | 4 | 1 | **64** | 64 | 2.72 | 8 | 0 | 95 | 5 | 11 | 11 |
| 20 | L18 | +0.60 | 47 | 0 | 0 | **72** | 72 | 3.06 | 11 | 0 | 98 | 2 | 14 | 19 |
| 21 | L19 | +0.65 | 48 | 7 | 1 | **59** | 57 | 2.46 | 8 | 0 | 98 | 2 | 12 | 11 |

Notes:
- Every number is computed from the accepted `routes_l3d.json` real primitives and the `crossing_stats.json` events with an **exact** physical-z match (rounded to 1e-6 mm).
- *body routes* = routes with at least one flat part on that physical height; *groups* = distinct original `manual_group` labels among those body routes.
- *covered blocks* = 10 x 10 grid of 15 mm blocks touched by flat routes or transition footprints; *idle blocks* = no route geometry at all on that height.
- *congested block* = block with >=2 real crossing events on that height.
