# 21-routing-height rebalanced 1024 experiment — contracts

Baseline (READ-ONLY, must never be modified):
`outputs/manual_c4_new_connectivity/FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024/`
GitHub baseline commit: `4451206a340008bc7d59c020eff7fdb5a6f1c085`.

New experiment root:
`outputs/manual_c4_new_connectivity/FANOUT_FIRST_21_HEIGHT_REBALANCED_1024/`

All new code lives under `four_side_1024/fanout1024/reheight21/` plus small
backward-compatible patches to `fanout1024/{fanout,layer2d,assemble}.py`.
No baseline semantic may change; the old 18-layer experiment must still run and
validate.  No file under the baseline RUN_DIR may be written.

## 1. Layer-plane model (21 routing heights)

19 body planes (18 old ids + new L20) + 2 interface planes that are now routable.

| plane_id | label | z (mm) | kind | role |
|---:|---|---:|---|---|
| 2 | L2 | -0.35 | body | Z1-U1 (manual, fixed) |
| 3 | L3 | -0.30 | body | Z1-U2 (manual, fixed) |
| 4 | L4 | -0.25 | body | Z1-U3 (manual, fixed) |
| 5 | L5 | -0.20 | body | Z1-U4 (manual, fixed) |
| 6 | L6 | -0.15 | body | Z1 other opposite |
| 7 | L7 | -0.10 | body | Z1 other opposite |
| 20 | L20 | -0.05 | body | Z1 other opposite (NEW id, z is BELOW L7) |
| 1001 | Z1_INTERFACE | 0.00 | interface_body | Z1 other opposite, direct 2D |
| 8 | L8 | +0.05 | body | Z1 other opposite (upward from z=0) |
| 9 | L9 | +0.10 | body | Z2 other adjacent |
| 10 | L10 | +0.15 | body | Z2-U1 (manual, fixed: id/z/members unchanged) |
| 11 | L11 | +0.20 | body | Z2-U2 (fixed) |
| 12 | L12 | +0.25 | body | Z2-U3 (fixed) |
| 13 | L13 | +0.30 | body | Z2-U4 (fixed) |
| 14 | L14 | +0.35 | body | Z2 other adjacent |
| 15 | L15 | +0.40 | body | Z2 other adjacent |
| 16 | L16 | +0.45 | body | Z2 other adjacent |
| 1002 | Z2_INTERFACE | 0.50 | interface_body | Z2 other adjacent, direct 2D |
| 17 | L17 | +0.55 | body | Z2 other adjacent |
| 18 | L18 | +0.60 | body | Z2 other adjacent |
| 19 | L19 | +0.65 | body | Z2 other adjacent |

* 21 distinct routing heights, all pairwise neighbours >= 0.05 mm apart.
* Glass z range [-0.35, +0.65], thickness 1.000 mm (unchanged).
* Z1 interface z=0, Z2 interface z=0.5.
* `layer_id` is NOT required to be monotone with z: L20 id 20 has z=-0.05.
  `l3d.layers.build_stack(heights={...})` accepts it because routing ids
  2..20 are contiguous; physical ordering is derived from z, never from id.

## 2. Assignment (A)

1024 rows, route ids and port pairs identical to `common.routes()`.

* Manual fixed (368):
  * Z1 256: Z1-U1 -> plane 2 (z -0.35), Z1-U2 -> plane 3 (-0.30),
    Z1-U3 -> plane 4 (-0.25), Z1-U4 -> plane 5 (-0.20); membership/grouping
    exactly the verified baseline manual assignment (64/64/64/64).
  * Z2 112: Z2-U1 -> 10 (0.15), Z2-U2 -> 11 (0.20), Z2-U3 -> 12 (0.25),
    Z2-U4 -> 13 (0.30); id/z/members unchanged (16/16/40/40).
* Z1 other 256 (64 C4 orbits, relation opposite): whole orbits, sorted by
  `group_id` ascending, consumed in order from plan
  `((6,13),(7,13),(20,13),(1001,13),(8,12))` -> 52/52/52/52/48 routes.
* Z2 other 400 (100 orbits, relation adjacent): group mapping by the baseline
  assignment's old target layer (whole old layer -> new plane, preserves
  orbits deterministically):
  old L8(48)->9, old L9(48)->14, old L14(48)->15, old L15(52)->16,
  old L16(52)->17, old L17(52)->18, old L18(52)->19, old L19(48)->1002.
* Every row: `needs_transition = (target_z != interface_z)`;
  `direction = 'direct' if not needs_transition else ('down' if target_z <
  interface_z else 'up')`.
  Expect exactly 100 direct routes (52 Z1_INTERFACE + 48 Z2_INTERFACE),
  924 routes with transitions -> 1848 endpoint transitions total.
* Required columns: route_id, plane, relation, manual_group, manual_pattern,
  layer_role, target_layer(=plane_id int), target_plane_label, target_z_mm,
  interface_z_mm, direction, needs_transition, c4_group_id, rotation_phase,
  baseline_old_layer (old target layer, for the diff audit; '' for manual),
  source_endpoint, target_endpoint, source_side, target_side,
  source_connector, target_connector, source_x_mm, source_y_mm, target_x_mm,
  target_y_mm, source_row, target_row.

## 3. Interface-direct routes (type B)

A direct route is `原始端口 -> 同接口二维主体路径 -> 原始目标端口`:

* `needs_transition=False`, `n_transitions=0`, `z_span_mm=0`, `lifted=False`;
* NO lead and NO S-curve is generated; `parts` is a single flat part at the
  interface plane: `layer_id = 1001|1002`, `z_mm = 0.0|0.5`;
* the body starts exactly at the source port pose heading `inward(source)` and
  ends exactly at the target port pose arriving heading `-inward(target)`;
* the same full R15 + strict D56 2D rules apply as any other body;
* the flat body is an ordinary 3D world citizen: same-plane D56 against all
  interface leads/bodies of that height, and true-3D >= 0.05 mm against every
  S-transition of other routes; legitimate transverse crossings are allowed.

## 4. Fanout (B) and layer-wise 2D (C)

* Type A routes: existing Fanout-First pipeline unchanged (lead -> R15 S
  transition -> landing on target plane).  Target z comes from the plane model,
  including the new L20 and the upward Z1 L8 transition.
* Type B routes: no fanout at all; they are recorded as direct with port
  landings.  `fanout.plan_fanout` must accept rows with `needs_transition=False`
  and must NOT create degenerate zero-height S curves.
* Per routing height the 2D router receives:
  * `z_mm` of the height (0.0 / 0.5 for interface planes);
  * tasks from the fanout landings (A=landing start pose, dA=inward direction,
    B=landing end pose, dB=inward direction; arrival heading is -dB);
  * obstacles = transition samples of ALL non-direct routes with
    `|z_transition - z_plane| <= 0.07`;
  * for interface planes `initial_routes` = every interface lead segment of all
    non-direct routes at the same interface height (they are frozen D56
    blockers); interface bodies are routed among/around them.
* L8 Z1 other routes: upward transition z 0 -> +0.05 (dz +0.05).
* Z2 old L16 routes now target L17 (0.55) -> transition direction flips from
  down to up; Z2 old L19 routes target Z2_INTERFACE -> direct.

## 5. Assembly (D) / world

* Type A route parts: `[flat lead(s), transition, flat body(target plane),
  transition, flat lead(t)]` exactly as baseline.
* Type B route parts: `[flat body(interface plane)]` only.
* A fresh `l3d.world.World(stack, clearance=0.05)` is rebuilt for the final
  check of all 1024 assembled routes in route-id order.
* `World.check_route` is the online authority; the independent validator must
  rebuild the same world.

## 6. Deliverables in the new RUN_DIR

```
layer_planes.json
assignment_1024.csv
assignment_audit.json
assignment_diff_vs_baseline.md / .json
process_rules.json
physical_layer_stack.json (new stack)
experiment_A/ experiment_B/ experiment_C/ experiment_D/ experiment_E/
fanout_selected.json  fanout_validation.json  layerwise_endpoints/  layerwise_routes/
routes_l3d.json  failed_routes.json
validation.json  final_stats.json
crossing_stats.json  comparison.md  report.md
plots/   (21 per-height 2D PNG + comparison/3D figures)
tests.log run.log checkpoints/ code snapshot
```

Route records: baseline schema plus `target_plane`, `target_plane_label`,
`needs_transition`, `n_transitions` (0 or 2).  Direct routes:
`parts=[flat(interface plane)]` and the fields above.

## 7. Evaluation (what the final report must show)

New vs baseline 18-layer numbers:
* success: 1024/1024 or honest failure list with real route ids + reasons;
* 21 heights really used: per-plane routed count = assigned count;
* L6/L7 crossings: baseline L6=5610, L7=5284 (total 10894) vs new five Z1
  heights (L6, L7, L20, Z1_INTERFACE, L8);
* system crossings total + crossing route pairs, per plane, per-route crossing
  distribution (max, p95, mean), total length + max single-route length,
  transition count/length (1848 if all succeed), min true 3D clearance, min
  radius, C4 orbit integrity, runtime, RRR counts, and every failed route's
  real reason;
* interface-direct routes: separate crossing/collision statistics vs the leads
  at the same height (never skipped).
* Never claim optical loss values: crossing counts are geometric proxies only.
* If <1024 succeed, also compare crossings on the common routed set and state
  the limitation.

## 8. Ownership / write scopes

* `reheight21/model.py`, `assign21.py`, tests, `layer_planes.json`,
  `assignment_1024.csv`, `assignment_audit.json`, `assignment_diff_*`,
  `experiment_A/` — assign21 owner.
* `fanout.py` direct-route + model-aware-z patches, `tests_fanout.py` additions,
  `experiment_B/` — fanout owner.
* `layer2d.py` interface-plane test/patch, `experiment_C/` — layer2d owner.
* `run21.py`, `assemble.py` zero-transition support, `experiment_D/E`,
  `routes_l3d.json`, `failed_routes.json`, `final_stats.json` — Lead.
* `validate21.py` + `validation.json` + `validator_consistency_tests.json` —
  validator owner.
* `plots21.py` + `plots/` — plots owner.
* `report21.py`/`archive21.py` + `report.md` + `comparison.md` + GitHub archive —
  report owner (runs after final artifacts are frozen).
* Never edit another owner's files; never write the baseline RUN_DIR.
