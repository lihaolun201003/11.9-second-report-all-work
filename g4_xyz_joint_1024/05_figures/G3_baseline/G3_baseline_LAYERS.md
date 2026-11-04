# G3_baseline

Source (accepted layout): `outputs\manual_c4_new_connectivity\XYZ_JOINT_G123_1024\best_valid`

- routes: **1024** (manual-U 368, groups 8)
- crossings (sum of exact-z events): **1322**
- routes SHA256: `711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`
- generated: 2026-11-04 18:28:03

| # | height | z (mm) | body routes | manual-U | groups | crossings | unique pairs | avg/route | max/route | mid-layer routes | covered blocks | idle blocks | congested blocks | max X/block |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | L2 | -0.35 | 34 | 33 | 1 | **17** | 17 | 1.00 | 17 | 0 | 76 | 24 | 3 | 8 |
| 2 | L3 | -0.30 | 62 | 62 | 1 | **0** | 0 | 0.00 | 0 | 0 | 58 | 42 | 0 | 0 |
| 3 | L4 | -0.25 | 61 | 61 | 2 | **0** | 0 | 0.00 | 0 | 0 | 80 | 20 | 0 | 0 |
| 4 | L5 | -0.20 | 86 | 86 | 2 | **0** | 0 | 0.00 | 0 | 0 | 80 | 20 | 0 | 0 |
| 5 | L6 | -0.15 | 58 | 0 | 0 | **96** | 93 | 3.31 | 13 | 13 | 100 | 0 | 18 | 19 |
| 6 | L7 | -0.10 | 54 | 0 | 0 | **54** | 49 | 2.00 | 11 | 17 | 96 | 4 | 10 | 11 |
| 7 | L20 | -0.05 | 45 | 0 | 0 | **44** | 40 | 1.96 | 7 | 12 | 97 | 3 | 12 | 9 |
| 8 | Z1_INTERFACE | +0.00 | 512 | 256 | 4 | **82** | 77 | 0.32 | 11 | 9 | 100 | 0 | 14 | 12 |
| 9 | L8 | +0.05 | 42 | 0 | 0 | **79** | 76 | 3.76 | 12 | 6 | 98 | 2 | 17 | 16 |
| 10 | L9 | +0.10 | 55 | 2 | 1 | **109** | 107 | 3.96 | 13 | 7 | 99 | 1 | 15 | 18 |
| 11 | L10 | +0.15 | 25 | 7 | 3 | **84** | 78 | 6.72 | 13 | 0 | 96 | 4 | 28 | 4 |
| 12 | L11 | +0.20 | 39 | 12 | 2 | **55** | 37 | 2.82 | 12 | 1 | 98 | 2 | 13 | 9 |
| 13 | L12 | +0.25 | 49 | 44 | 3 | **9** | 7 | 0.37 | 4 | 0 | 88 | 12 | 1 | 2 |
| 14 | L13 | +0.30 | 47 | 42 | 2 | **12** | 10 | 0.51 | 5 | 0 | 91 | 9 | 2 | 2 |
| 15 | L14 | +0.35 | 48 | 0 | 0 | **99** | 99 | 4.12 | 18 | 0 | 98 | 2 | 12 | 31 |
| 16 | L15 | +0.40 | 51 | 6 | 1 | **81** | 75 | 3.18 | 12 | 0 | 98 | 2 | 16 | 11 |
| 17 | L16 | +0.45 | 47 | 0 | 0 | **79** | 79 | 3.36 | 12 | 0 | 98 | 2 | 13 | 24 |
| 18 | Z2_INTERFACE | +0.50 | 512 | 112 | 4 | **130** | 126 | 0.51 | 19 | 0 | 100 | 0 | 21 | 31 |
| 19 | L17 | +0.55 | 53 | 6 | 1 | **109** | 103 | 4.11 | 16 | 0 | 98 | 2 | 17 | 16 |
| 20 | L18 | +0.60 | 47 | 0 | 0 | **92** | 92 | 3.92 | 17 | 0 | 98 | 2 | 13 | 25 |
| 21 | L19 | +0.65 | 50 | 7 | 1 | **91** | 88 | 3.64 | 18 | 0 | 98 | 2 | 14 | 18 |

Notes:
- Every number is computed from the accepted `routes_l3d.json` real primitives and the `crossing_stats.json` events with an **exact** physical-z match (rounded to 1e-6 mm).
- *body routes* = routes with at least one flat part on that physical height; *groups* = distinct original `manual_group` labels among those body routes.
- *covered blocks* = 10 x 10 grid of 15 mm blocks touched by flat routes or transition footprints; *idle blocks* = no route geometry at all on that height.
- *congested block* = block with >=2 real crossing events on that height.
