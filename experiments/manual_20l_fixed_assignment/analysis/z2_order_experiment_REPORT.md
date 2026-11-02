# Z2 L9–L20 fixed-layer lifting — independent prototype report (task-2)

Status: stopped early at the Lead's request (production run needs the CPU). All
numbers below are measured, never estimated, and the exact commands are in
`scratch/team_z2/`. Nothing outside `scratch/team_z2/` was modified.

World used for the final measurements: snapshot of the Lead's validated fixed-Z1
set `MANUAL_LAYERS_20L_PROTO_C5R4/z1_all_routes.json` — **511/512 routes
(256 manual U L2–L5, 127 NS L7, 128 EW L8), 0 validator violations** (copied to
`scratch/team_z2/z1_fixed_routes.json` by `adopt_z1_snapshot.py`). The one
missing Z1 route is L7 route 210 (`candidate_2d_conflict`).

## (a) Measured success counts

Subsets (all deterministic, route ids in `z2_assignment_audit.csv`):
`first40` = first 40 adjacent high-layer routes (all have baseline 2D geometry),
`same` = all 60 same-side (U-shaped) high-layer routes.

| # | Construction order / world | Strategy | Subset | Success | Time |
|---|---|---|---|---|---|
| 1 | **Z1 complete first** (511 fixed Z1, 0 interface placed) | `independent` (two-sided fine sweep 2/1/0.5 mm, exact component checks) | first40 adjacent | **28/40 = 70 %** | 61.5 s (median 1.0 s/route) |
| 2 | Z1 complete first | `independent` | same-side (60) | **38/60 = 63 %** | 64.9 s |
| 3 | Z1 complete first, 498-route earlier snapshot | `standard` (stock `transition_plans` 160 plans + fast certificate) | first40 adjacent | **12/40 = 30 %** | 140 s |
| 4 | **Z2 first** (only 256 manual U's in world, no L7/L8 Z1) | `standard` | first40 adjacent | **39/40 = 97.5 %** | 20 s |
| 5 | Z1 complete first, 498-route snapshot | `standard` | first8 | 4/8 | 22 s |
| 6 | Z1 complete first, 498-route snapshot | `independent` (2/1/0.5 mm) | first8 | 6/8 | 57 s |

Combined Z1-first `independent`: **66/100 (66 %)** of the tested high-layer
routes. Strategy ranking on the same world: `independent` 28/40 vs `standard`
12/40 (the decoupled fine placement search is clearly the better search).

### Interface-plane (z=0.5) routes — measured, 68 assigned

| World in front of the 68 interface routes | placed |
|---|---|
| empty world | **48/68** (the other 20 have no baseline 2D geometry) |
| 256 fixed manual U's (production order) | **12/68** (36 × `flat_vs_transition`) |
| complete fixed Z1 (511 routes) | **0/68** (48 × `flat_vs_transition`, 20 × no 2D) |

→ The interface plane itself is feasible (48/48 with geometry fit when alone);
it is the fixed-Z1 transitions that block it.

## (b) Root cause / failure modes

1. **z1 and z2 baseline 2D layouts reuse the same tracks.** The frozen 2D
   campaign routed z1 (z=0) and z2 (z=0.5) as separate 2D problems, so their
   paths/port corridors overlap in XY. Example: z2 route 518 and z1 route 227
   start at the same port XY (150, 125.625) and share the first 23.6 mm of track
   exactly. A fixed Z1 S-curve from z=0 crosses z=0.5 about 3.5–4.2 mm after its
   rise start (~5–7 mm from the port), i.e. exactly in the near-port corridor
   that every Z2 route also uses at z=0.5. Any Z2 flat at z=0.5 that passes that
   point is a true-3D violation (near-miss distances measured 0.02–0.07 mm, just
   under 0.08 mm).
2. **Consequence for Z2 high routes:** the base-plane head flat can often only
   extend 2–22 mm from the port (`head_bound`/`tail_bound` monotone bounds in
   `scratch/team_z2/results/z1first_first40_independent.json`); when the allowed
   transition start range is that short, no legal R15 S-curve exists and the
   route fails as `blocked_rise_transition` / `blocked_fall_transition`.
   Breakdown of the 12 first40 failures: 6 blocked rise (head_bound 2.2–17 mm),
   6 blocked fall. Same-side failures: 19 blocked rise, 2 blocked fall, 1 no pair.
3. **Second-order conflict:** the Z2 S-curve itself crossing the L7/L8 Z1 lines
   at the matching z. On the first40 diagnostic (`diag_z2_conflicts.py`, 3
   representative plans per route) the first violation was vs
   `z1_opposite_ns`/`z1_opposite_ew` 100 times vs `manual_u` only 14 times.
4. **Hard ceiling: 12 of the 444 high-layer routes have no baseline 2D geometry**
   (621–624, 629–632, 853–856; 3 whole C4 groups) → 444 is impossible without
   2D re-planning; max = 432. The same holds for the interface set (48/68 max).
5. `standard` strategy failures on the Z1-first world were 18 ×
   `flat_vs_transition`, 7 × `transition_vs_flat`, 3 × `lift_route_none` —
   same root cause, it just finds fewer legal placements.

## (c) Reusable scripts (all under `scratch/team_z2/`)

* `z2lab.py` — core library: fixed-Z1 world assembly, interface placement,
  plan generators, `lift_independent` (decoupled two-sided fine search using the
  exact decomposition of `World.check_route`: each candidate part checked
  independently against the world, then the full route re-verified before
  commit), subset definitions, result summarising.
* `run_lab.py` — run one strategy on one subset against the fixed-Z1 world:
  `python scratch/team_z2/run_lab.py --strategy independent --subset first40`
  (`--strategy standard|prod|hybrid|dense|independent`).
* `exp_orders.py` — build-order comparison (`z1first` / `manual_iface_z1` /
  `z2first`), rebuilds the Z1 opposite routes in each order.
* `run_remaining.py` — the config table above (`--only <name>`).
* `build_z1_cache.py`, `adopt_z1_snapshot.py` — Z1 cache construction / adopting
  a Lead snapshot as the fixed world.
* `diag_z2_conflicts.py`, `diag_interface.py`, `exp_interface_fit.py` —
  part-role / blocker / interface-fit diagnostics.
* Results: `scratch/team_z2/results/*.json` (per-route details), logs in
  `scratch/team_z2/_work/`.

## (d) Is all 444 reachable?

* **With frozen 2D paths and a complete fixed Z1 world first: no.** Measured
  66 % on 100 routes → ≈ 285 of the 432 routable-if-2D-fixed (hard ceiling 432).
  `standard` would only get ≈ 130–250.
* **Building Z2 before the Z1 opposite routes (the production runner order)**
  lifts ≈ 95 %+ of Z2 (39/40 measured against the 256 manual U's) → ≈ 410/432,
  but then the Z1 L7/L8 opposite routes have to weave through the lifted Z2
  transitions; that trade-off is unmeasured here (killed early) and is the key
  risk of that order.
* **A consistent layout of everything** therefore needs one of:
  1. re-planning the blocked Z2 2D paths (the repo already has
     `v2opt.search.candidates_for` + `alternative_primitives` for Z1; applying it
     to Z2 would recover most of the `blocked_*` cases, since the head-flat
     blockage is a near-port track problem), or
  2. joint re-placement of the Z1 transition start positions so they dodge the
     Z2 near-port tracks (the offending near-misses are 0.02–0.07 mm, i.e. tiny
     position shifts suffice), or
  3. accepting the production order and re-building the Z1 opposite routes last
     (risk to the Z1 count instead).
* Realistic honest estimate for the full 444 today: **~300 if Z1 is fixed
  first, ~410 if Z2 is built first and Z1 is rebuilt last; 444 requires 2D
  re-planning of the blocked routes and is not reachable by placement search
  alone.** The interface-plane 68 routes need the same joint treatment (0/68
  after the full fixed Z1 set, 48/68 if the plane is routed first).
