# fanout_first_21_height_rebalanced_1024

Archived at 2026-11-03T22:18:17.

## Result

* routed / failed: **1024 / 0** of 1024 (Z1 512 / Z2 512; 100 interface-direct routes, 1848 transitions)
* routing heights: **21** (19 body planes ids 2..20 + interface-body planes 1001 Z1_INTERFACE z=0.0 / 1002 Z2_INTERFACE z=0.5)
* same-plane crossings: **11890** (pairs 9797) vs baseline 18108 (-6218.000)
* total length 157484.192735242 mm, max route 283.187759688 mm
* min 3D clearance 0.100699741 mm (rule 0.05 mm), min radius 15 mm

## Independent validation

* geometry_pass: True
* contract_pass: True
* validation_pass: True
* violations: 0
* validator consistency tests: True
* routes_l3d.json sha256: 1fe24c977c36c0b24692ee386213e6e870010ac1f0bed5c6b3a1eb4be53119d9

## Contents

* `routes_l3d.json`, `failed_routes.json`, `validation.json`, `validator_consistency_tests.json`, `crossing_stats.json`
* `report.md`, `comparison.md`, `final_stats.json` (+ `final_stats_run_all.json`)
* `assignment_1024.csv`, `layer_planes.json`, `assignment_audit.json`, `assignment_diff_vs_baseline.md`, `physical_layer_stack.json`, `process_rules.json`
* `fanout_selected.json`, `fanout_validation.json`, `layerwise_routes/`, `layerwise_endpoints/`
* `experiment_A/ .. experiment_E/` (incl. the regenerated `experiment_C/` initial-C layout), `plots/` (21 per-height images + 7 comparison figures), `tests.log`, `run.log`, `checkpoints/`
* `code/reheight21/`: model.py, assign21.py, run21.py, validate21.py, plots21.py, report21.py, archive21.py, SPEC.md, __init__.py, tests_assign21.py, tests_validate21.py, tests_plots21.py
* `code/*.py`: patched shared modules (fanout.py, layer2d.py, assemble.py, common.py) + run_all.py, validate_final.py, archive.py, report.py, plots.py, verify.py, assign.py
* `MANIFEST.json`: sha256 + size of every archived file (including every code file); `code/CODE_FILES.json`: the same code-file sha256 list in machine-readable form
