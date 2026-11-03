# Fanout-First Z2-Manual-Verified 1024 — system design and file contracts

Working directory: `C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D`
Python: `.venv\Scripts\python.exe` (3.10, numpy, matplotlib). NEVER use the system
python to run project code.

Run directory (all new outputs, do not touch historical experiments):
`outputs/manual_c4_new_connectivity/FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024/`

## 0. Ground truth data (do not modify, do not regenerate connections)

* `outputs/.../NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected/routes_1024.json`
  — the true original 1024 connections (`routes`), plus `rotation_groups`
  (256 C4 rotation orbits × 4 routes). Loaded by `fanout1024.common.routes()`,
  `rotation_groups()`.
* `four_side_1024.v3c4.inputs.ENDPOINTS` — all 2048 physical ports with
  `routing_xy`, `inward`, `plane`, `z_mm`, side/connector/row/column/channel.
  Loaded by `common.endpoints()`.
* Excel input `C:\Users\lihao\Desktop\Z2人工U_具体端口分组_L10-L13_源数据待校验.xlsx`
  — 112 candidate rows, all marked `layer=z1`; must be audited, never copied.

True V4 route inventory: z1 = 512 (256 `opposite` + 256 `same`), z2 = 512
(400 `adjacent` + 112 `same`). The 112 z2 `same` routes are the real Z2 manual-U
candidates; the 256 z1 `same` routes are the real Z1 manual-U routes. The Excel
112 rows are Z1-port-numbered copies of the Z2 manual-U connector/channel pattern
and must be matched against the true 512 Z2 connections.

## 1. Process model (single source of truth: `fanout1024/common.py`)

* Glass 1.000 mm, z ∈ [-0.35, +0.65]. Z1 interface z=0, Z2 interface z=0.5.
* 18 body layers `PHYSICAL_LAYERS` L2..L19, min pitch 50 µm, clearance 50 µm.
* Manual group → layer fixed: Z1-U1→L2, Z1-U2→L3, Z1-U3→L4, Z1-U4→L5,
  Z2-U1→L10, Z2-U2→L11, Z2-U3→L12, Z2-U4→L13.
* Remaining: Z1 `opposite` (256 routes, 64 C4 orbits) → L6/L7 (32 orbits each);
  Z2 `adjacent` (400 routes, 100 C4 orbits) → L8,L9,L14..L19 (8 layers).
* R15 mm; transition = S-curve, two exact R=15 circular arcs in the vertical
  plane of the local inward direction; built by
  `four_side_1024.fsd25d.path3d.make_transition(start, dir, z0, z1, radius=15)`.

## 2. Route model (the 3D record consumed by `l3d.world.World`)

```python
route = {
  'route_id': int, 'plane': 'z1'|'z2',
  'source_endpoint': str, 'target_endpoint': str,
  'start_z_mm': float, 'end_z_mm': float,       # both = interface z
  'parts': [part, ...],                          # flat/transition alternating
  'layer_sequence': [...], 'layer_z_sequence': [...],
  'n_transitions': int, 'lifted': bool, 'layers_used': [...],
  'length_mm': float, 'xy_length_mm': float, 'z_span_mm': float,
}
flat part       = {'kind':'flat','layer_id':int,'z_mm':float,'length_mm':float,
                   'primitives':[line/arc dicts (fslw geom schema)]}
transition part = make_transition(...) + {'kind':'transition'}
```

Canonical body route of one connection with target layer `L`, z=`zt`:

```
P_s --flat lead_s(z0)--> Q_s --transition(z0->zt)--> A
A --flat body(z=zt, target layer L)--> B
B --transition(zt->z0)--> Q_t --flat lead_t(z0)--> P_t
```
where `P` = true port pose, `d` = inward direction, `lead` ≥ 0 (candidate),
`Q = P + lead*d`, footprint `f = 2*R*sin(acos(1-|zt-z0|/(2R)))`,
`A = Q + f*d`, and `B = Q_t + f*d_t`. The body starts at A heading `d_s` and
arrives at B heading `-d_t`. The target transition part is
`make_transition(B, -d_t, zt, z0)` (same curve traversed backwards).

`l3d.world.World.check_route(route)` is the online acceptance rule; the final
validator must rebuild the same world from the finished routes. Do not lower R15,
do not restore the 80 µm global clearance.

## 3. Module contracts (write scopes are disjoint — do not edit another's files)

### 3.1 `four_side_1024/fanout1024/verify.py` (owner: data-verifier)
Functions:
* `audit_excel() -> dict` raw workbook audit (sheet, columns, 112 rows, per group,
  `layer=z1` count, route-id-vs-true-data mismatch evidence).
* `match_z2_manual(records) -> dict` rigorous match of every Excel row to exactly
  one true Z2 route. Matching key: both true endpoints on plane `z2`; same side
  and same connector number for both endpoints as the Excel row; plane index of
  each true endpoint == 2; and the Excel row's row/column/channel fingerprint used
  only to disambiguate when more than one true candidate has the same
  connector pair. Also cross-check the matched routes form the C4 orbit pattern
  (2 NS-group + 2 EW-group members per orbit) and that the four groups contain
  16/16/40/40 routes. Emit conflicts instead of guessing.
* `verify_z1_manual()` → 256 true z1 `same` routes grouped as
  Z1-U1..Z1-U4 (NS-1, NS-2, EW-1, EW-2 = 64 each) taken from the previous
  verified assignment (`MANUAL_20L_FIXED_ASSIGNMENT_FULL/assignment_1024.json`,
  `old_manual_layer` 1..4, manual_group NS-1/NS-2/EW-1/EW-2) cross-checked
  against the true route table; mapping NS-1→L2, NS-2→L3, EW-1→L4, EW-2→L5.
* `write_verified(...)` writes exactly:
  `input_excel_audit.json`, `z1_manual_u_verified_L2_L5.csv`,
  `z2_manual_u_verified_L10_L13.csv`, `z2_manual_u_match_audit.csv`,
  `z2_manual_u_unmatched.csv`, `z2_manual_u_conflicts.csv`,
  `z2_manual_u_summary.json` in RUN_DIR, plus `z1_manual_u_match_audit.csv`.
* The Z2 CSV columns (exactly, one real connection per row):
  route_id, plane, source_endpoint, target_endpoint, source_connector,
  target_connector, source_side, target_side, source_x_mm, source_y_mm,
  target_x_mm, target_y_mm, c4_group_id, manual_group, manual_pattern,
  target_layer, target_z_mm, interface_z_mm, direction, match_method,
  match_status, original_excel_row.
  `plane='z2'`, `interface_z_mm=0.5`, targets layers/z 10→0.15, 11→0.20,
  12→0.25, 13→0.30, `direction='down'`.
* The Z1 CSV: same schema with plane='z1', interface_z_mm=0.0,
  targets L2→-0.35, L3→-0.29, L4→-0.23, L5→-0.17, direction='down',
  manual_group Z1-U1..Z1-U4, manual_pattern NS-first/NS-second/EW-first/EW-second.
* `z2_manual_u_summary.json` must explicitly answer: Excel raw rows; how many are
  actually Z1 data; how many of the 512 true Z2 connections satisfy the manual
  template; per-group counts; duplicate route ids; routes in two groups; template
  pairs with no real Z2 route; coordinate availability of every confirmed route.

### 3.2 `four_side_1024/fanout1024/assign.py` (owner: data-verifier)
* `build_assignment() -> rows` from `common.routes()`, verified manual CSVs and
  C4 rotation groups. 1024 unique route ids, 512 z1 / 512 z2.
* Manual rows: fixed layers per section 1, `manual_group`, `manual_pattern`.
* Non-manual: whole C4 rotation orbits go to one layer. z1 opposite: 64 orbits
  ↔ {L6:32, L7:32}. z2 adjacent: 100 orbits ↔ L8,L9,L14..L19 balanced
  12/13 orbits per layer (prefer the layers closest to the Z2 interface for the
  13-orbit layers). Deterministic ordering.
* Every row: route_id, plane, relation, manual_group, manual_pattern,
  target_layer, target_z_mm, interface_z_mm, direction ('down'|'up'),
  layer_role ('z1_manual_u'|'z2_manual_u'|'z1_other'|'z2_other'),
  c4_group_id, rotation_phase, source_endpoint, target_endpoint,
  source_side, target_side, source_connector, target_connector,
  source_x_mm, source_y_mm, target_x_mm, target_y_mm.
* Writes `assignment_1024.csv`, `assignment_audit.json`,
  `physical_layer_stack.json` (via `common.physical_layer_stack_payload()`),
  `process_rules.json` (via `common.process_rules_payload()`),
  and `experiment_A/` summary + per-group audit.
* Hard invariants: 1024 rows, 1024 unique ids, 512/512 planes, every manual
  route on its fixed layer, no manual layer overwritten by non-manual rows,
  port pairs identical to `common.routes()`.

### 3.3 `four_side_1024/fanout1024/fanout.py` (owner: fanout-planner)
* `candidate_transitions(route, role, target_layer, leads=...) -> list[dict]`
  each candidate: `route_id, endpoint_role, candidate_id, start_xy, start_xyz,
  direction, z0, z1, target_layer, target_z, end_xy, end_xyz, footprint_mm,
  length_mm, theta_rad, radius_mm=15, lead_mm, geometry='two_arc_S',
  transition={make_transition dict}, reversed_transition={...}`.
* `plan_fanout(rows, stack, fixed=None, repair_ids=None, seed=..., log=...) -> dict`
  globally coordinate every endpoint's transition in one 3D world:
  * iterate endpoints in a deterministic difficulty order, try the candidate
    leads (0.25, 1, 2, 4, 8, 16 mm; all ≥ 0.25 mm) and pick the first candidate
    whose partial route `[flat lead, transition]` (source role) or
    `[transition, flat lead]` (target role) passes the 3D world;
  * conflicts trigger rip-up of the blocking route and a retry (bounded), then
    alternative leads; unresolved endpoints are recorded as failures with the
    real route_id/role/reason;
  * `fixed` (dict route_id→{source,target}) is kept immutable (manual groups in
    experiment C/D/E);
  * returns `{'selected': {route_id: {'source': rec, 'target': rec}},
    'failures': [...], 'stats': {...}, 'world': ...}`.
* `landings(selected) -> {route_id: {'A': (x,y), 'dA': (dx,dy), 'B': (x,y),
  'dB': (dx,dy)}}` with `A`/`B` = transition end points (`end_xy`) and
  `dA = inward(source)`, `dB = inward(target)`.
* `layer_obstacles(selected, layer_id) -> list[{x,y,z,route_id,role}]` all
  transition samples with `|z - layer_z| < 0.05 + 0.02` (the layer 2D router must
  keep bodies ≥ 0.05 mm true 3D from every sample of another route).
* `write_artifacts(result, out_dir)` writes `fanout_candidates.json`,
  `fanout_selected.json`, `fanout_validation.json`,
  `layerwise_endpoints/endpoints.json`, and `experiment_B/` (manual groups only
  stats: per group actual count, endpoints needing transitions, succeeded,
  failed, transition conflicts, R15 legality).
* Must verify each transition's R15/curvature/continuity independently and report
  `minimum_radius` by true 3D curvature (sampled), not only the 2D projection.

### 3.4 `four_side_1024/fanout1024/layer2d.py` (owner: layer2d-router)
* `route_layer(layer_id, z_mm, tasks, obstacles, budget=..., rr_rounds=...,
  log=...) -> dict` with tasks list
  `{route_id, A, dA, B, dB, relation, source_side, target_side, manual_group}`
  where the body starts at A heading dA and must arrive at B heading -dB.
* Candidate generation: R15 line + exact quarter/short-S arc chains in world
  coordinates (`four_side_1024.v2opt.candext.move_path`-style move sequences,
  `four_side_1024.legacy_geometry._orthogonal_quarters`, or your own equivalent)
  covering: straight, single-L, Z-shift, staircases, same-side U-turns
  (reuse `four_side_1024.r15.u_geometry.u_candidates` translated to the landing
  depth for same-side pairs), multiple lead lengths and lateral tracks.
  Multiple candidates per route are mandatory; deterministic order.
* Acceptance: `four_side_1024.d56.index.D56Index` strict (width 0.05,
  gap 0.03, R=15, crossing_policy='strict') over the layer's accepted bodies PLUS
  the transition obstacles: for every candidate primitive, every obstacle sample
  with `route_id != candidate.route_id` must satisfy
  `sqrt(d2d² + (z_layer - z_sample)²) >= 0.05` (implement an efficient spatial
  grid; verify primitives by sampling at ≤0.05 mm and using primitive distance).
* `route_all_layers(layer_tasks, cfg, out_dir, log=...) -> dict` routes every
  layer independently (they are independent except through the obstacles),
  failures are real route ids with reasons; supports bounded RRR inside a layer
  and records per-layer stats. Writes `layerwise_routes/routes.json` +
  `experiment_C/`.
* Same-layer legal transverse crossings stay legal (D56Index semantics); overlap,
  parallel-too-close and all non-crossing proximity < 0.08 are illegal.

### 3.5 `four_side_1024/fanout1024/assemble.py` + `run_all.py` (owner: Lead)
Owns full-route assembly, the joint repair loop, experiments D/E and the final
routes_l3d.json / failed_routes.json / validation.json / final_stats.json.

### 3.6 `four_side_1024/fanout1024/validate_final.py`, `plots.py`, `report.py`,
`archive.py` (owner: validator-reporter)
* Independent validator rebuilds a fresh `l3d.world.World` from `routes_l3d.json`
  and re-checks every route; plus R15 radius audit, port identity/coverage audit,
  glass bounds, layer assignment audit, transition-vs-fixed-plane audit,
  online-vs-validator consistency spot checks (50/49 µm boundary cases).
* Plots: 3D geometry of all routed routes + the 8 manual groups, per-layer 2D
  views (`plots/`).
* `report.md`, `comparison.md`, `final_stats.json` answers, and the GitHub archive
  through the existing repo clone + API push pattern with `GH_TOKEN`.

## 4. Experiment output requirements (RUN_DIR)

```
input_excel_audit.json
z1_manual_u_verified_L2_L5.csv
z2_manual_u_verified_L10_L13.csv
z2_manual_u_match_audit.csv
z2_manual_u_unmatched.csv
z2_manual_u_conflicts.csv
z2_manual_u_summary.json
assignment_1024.csv
physical_layer_stack.json
process_rules.json
fanout_candidates.json
fanout_selected.json
fanout_validation.json
layerwise_endpoints/
layerwise_routes/
experiment_A/ experiment_B/ experiment_C/ experiment_D/ experiment_E/
routes_l3d.json
failed_routes.json
validation.json
final_stats.json
comparison.md
report.md
checkpoints/
plots/
run.log
```
Each `experiment_X/` must report: input line count, actual attempts, success,
failures, failure reasons, validation status.

## 5. Rules of engagement

* Every member works only inside its own files (listed above). Do not edit
  `four_side_1024/fanout1024/common.py`; request changes from the Lead.
* Never modify original inputs, historical outputs, or the true connection data.
* Run everything with `.venv\Scripts\python.exe` from the project root and
  `sys.path.insert(0, project_root)`.
* Keep stdout concise; write details to JSON/CSV; every long run must append to
  `RUN_DIR/run.log`.
* Report honestly: failures are never hidden or renamed; no fake success counts.
