# E1 best solution — independent strict-C4 audit

- **Verdict: FAIL** — `symmetry_pass = false`
- audited layout: `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D\outputs\manual_c4_new_connectivity\z1_multilayer_150um\E1_z1_priority_z2_rerouting\best_solution\routes_1024.json`
- validator: `four_side_1024/c4/validate.py` (independent implementation; only the orbit definition from `connectivity_1024.json` and the frozen `ENDPOINTS` port table are shared with the rest of the project)
- report: `c4_validation.json` (this directory), generated 2026-10-31T01:32:10+08:00

## Headline numbers

| check | error pairs (orbit,k) | orbits |
|---|---|---|
| orbit structure (1024 routes / 256 orbits / 4 members) | 0 | – |
| endpoint rotation | 0 | 0 |
| layer symmetry | 122 | 61 |
| transition (path-segment) symmetry | 128 | 64 |
| 3D geometry symmetry | 128 | 64 |

- `total_routes = 1024` (expected 1024), `total_orbits = 256` (expected 256), `max_layer = 7` (from the payload layer stack L2..L7).
- `maximum_xyz_deviation_mm = **1.1**` (tolerance 1e-4 mm). worst pair: orbit 50 k=1 rep=69 member=309 (forward).
- `failed_orbits = 64 / 256`; `192` orbits pass. All failures are `(plane, kind) = (z1, opposite)`: 64 of the 66 z1-opposite C4 groups fail; every other plane/kind passes.

### Layer inconsistency (61 orbits)

- 18 orbits: the four members do not even share the part structure (2 of 4 are lifted, 2 stay flat at the interface).
- 43 orbits: same flat/travel structure but different physical travel heights among the 4 rotation images (e.g. one C2 pair at 0.65 mm, the other at 0.80 mm).
- per-orbit lift-level patterns of the 66 z1-opposite orbits:

| sorted max flat z of the 4 members (mm) | orbits |
|---|---|
| 0.65, 0.65, 0.8, 0.8 | 36 |
| 0, 0, 0.65, 0.65 | 14 |
| 0.65, 0.65, 0.95, 0.95 | 6 |
| 0, 0, 0.95, 0.95 | 3 |
| 0.8, 0.8, 0.8, 0.8 | 2 |
| 0.95, 0.95, 0.95, 0.95 | 2 |
| 0.8, 0.8, 0.95, 0.95 | 1 |
| 1.1, 1.1, 1.1, 1.1 | 1 |
| 0, 0, 1.1, 1.1 | 1 |

### Path-segment inconsistency (64 orbits)

First differing transition parameter per failing (orbit, k) pair:

- `position+footprint+z0/z1`: 64 pairs
- `transition count differs`: 36 pairs
- `footprint+position+z0/z1`: 22 pairs
- `position`: 6 pairs

64 orbit-level failures = 61 layer-inconsistent orbits + 3 orbits whose members use the same travel height but different S-bend windows (`a_in`/`a_out`), so their transitions sit at different arclengths.

## Why E1 fails strict C4

E1 planned the 3D lift route-by-route / C2-pair-wise (the z1-opposite routes were lifted as EW/NS pairs, and every route got its own `a_in`/`a_out` S-bend window from an independent search). A C4 orbit contains *two* C2 pairs and four 90°-rotation images of the same connection, so independent per-pair layer choices and per-route windows necessarily break the four-fold symmetry: the dominant pattern is two C2 pairs lifted to two different heights (36 orbits with `(0.65, 0.65, 0.80, 0.80)`), 18 orbits are only half lifted, and 3 orbits use the same height with different windows. Only 2 of the 66 z1-opposite orbits happen to be C4-consistent.

The 2D port/interface layer itself is exactly C4-symmetric: endpoint rotation errors are 0 and the 92 all-flat orbits deviate by < 1e-9 mm. The failure is therefore purely the 3D lifting decision, as expected from the E1 strategy.

## Method and tolerances

Rotation about the board centre (75, 75): `R(x, y, z) = (150 - y, x, z)`; the 256 groups of `inputs/connectivity_1024.json` are the C4 orbits. For every orbit and k = 1, 2, 3 the mapped member is found from the endpoint positions (a member may be traversed in the opposite direction, in which case sequences are compared reversed and transition `z0`/`z1` swapped).

| check | metric | tolerance |
|---|---|---|
| endpoint rotation | `|R^k(rep.source) - member.source_or_target|` and same for target | 1e-6 mm |
| layer symmetry | ordered physical flat heights, reversal aware | 1e-9 mm |
| transition symmetry | transition count, 2D arclength position (flat parts consume their 2D length, transitions their XY footprint), XY footprint, 3D length, `z0`/`z1` | 1e-6 mm |
| 3D geometry | max over dense centreline samples (0.1 mm) of the **exact point-to-curve distance**, bidirectional; flats = exact point-to-line/arc distance, transitions = exact point-to-two-arc S-curve distance | 1e-4 mm |

`symmetry_pass` = no structural/endpoint/layer/transition/geometry errors and maximum XYZ deviation within tolerance.

## Validator sanity checks (positive controls)

- Lead's strict-C4 interface-only baseline (`c4_symmetric_multilayer/baseline/routes_1024.json`): **PASS**, `maximum_xyz_deviation_mm = 2.84217e-14` (the baseline payload records 2.84e-14 mm; independent agreement).
- Synthetic strict-C4 3D layout built from E1 route records (k=1,2 copied forward, k=3 built as the reversed traversal): 5/5 test orbits pass (max dev 2.84217e-14 mm), so the validator handles real lifted S-bends and reversed traversal without false positives.
- Self-distance of every E1 route's exact 3D model is <= 2.8e-14 mm (the transition sampler and point-to-curve distance agree).
- Arclength bookkeeping: for the strict baseline layout `sum(flat 2D lengths) + sum(transition footprints)` equals `ctx.total(rid)` exactly (max dev 0.000e+00 mm, 0 routes above 1e-9).
- E1 caveat (explicitly checked, not used in the verdict): 256 E1 routes carry a stale top-level `primitives` field whose length differs from the real `parts` chain by up to 47 mm (all routes of the 16 z1-same + 48 z2-same orbits; those orbits pass C4). The validator therefore reconstructs all geometry from each record's `parts`; `parts` bookkeeping agrees with the record's own `xy_length_mm` to 5.7e-14 mm on all 1024 routes, and the E1 audit is a within-orbit comparison, so the stale field does not affect the symmetry verdict.

## Deliverables in this directory

- `c4_validation.json` — full report: totals, per-check error details, per-orbit summaries, aggregates by plane/kind, tolerances, skipped checks.
- `figures/fig1_e1_c4_error_orbits.png` — failures by plane/kind and per-member lift heights of the 66 z1-opposite orbits.
- `figures/fig2_example_orbit_4.png` — example failing orbit: XY overlay coloured by physical height plus height-vs-arclength profiles against the rotated representative.

## Validator API

```python
from four_side_1024.c4 import validate as V

# routes/payload/path -> report dict, no disk write:
report = V.validate_layout(routes_or_payload, max_layer=None)
# -> report["symmetry_pass"], report["maximum_xyz_deviation_mm"], ...

# file -> report dict, optionally writes <out_dir>/c4_validation.json:
report = V.validate_file(routes_path, out_dir=None)
```

CLI: `python four_side_1024/c4/validate.py <routes.json> [--out-dir DIR] [--max-layer 7]`

