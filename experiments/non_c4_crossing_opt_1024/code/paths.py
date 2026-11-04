# -*- coding: utf-8 -*-
"""Path patching for the C4-free crossing-optimisation experiment.

``reheight21.model`` keeps its writable paths in module level constants that
are resolved *at call time* by the drivers (``run21``, ``validate21``...), so
pointing an experiment at its own directory only requires re-binding those
constants before any driver function runs.  The frozen 21-height baseline is
never re-bound and never written by this experiment.
"""
from __future__ import annotations

from pathlib import Path

from .. import common as C
from ..reheight21 import model as M

#: root of the whole C4-free research programme
EXPERIMENT_ROOT = C.OUTPUT_ROOT / 'NON_C4_CROSSING_OPT_1024'
#: frozen 21-height baseline (READ-ONLY, never written here)
BASELINE_21H_DIR = C.OUTPUT_ROOT / 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'
#: frozen 18-layer baseline of the 21-height work (READ-ONLY)
BASELINE_18L_DIR = C.RUN_DIR

#: writable sub-directories every experiment directory has
_SUBDIRS = (
    'checkpoints', 'experiment_A', 'experiment_B', 'experiment_C',
    'experiment_D', 'experiment_E', 'layerwise_routes',
    'layerwise_endpoints', 'plots',
)


def experiment_dir(name):
    """Absolute experiment directory for ``name`` under the programme root."""
    return EXPERIMENT_ROOT / str(name)


def use_experiment(run_dir):
    """Re-bind ``reheight21.model`` writable paths onto ``run_dir``.

    Returns the (created) experiment directory.  Safe to call repeatedly; each
    call fully re-points the model constants, so several experiments can run
    sequentially in one python process.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for sub in _SUBDIRS:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    M.RUN_DIR = run_dir
    M.NEW_RUN_DIR = run_dir
    M.NEW_ASSIGNMENT = run_dir / 'assignment_1024.csv'
    M.NEW_ASSIGNMENT_AUDIT = run_dir / 'assignment_audit.json'
    M.NEW_ASSIGNMENT_DIFF_JSON = run_dir / 'assignment_diff_vs_baseline.json'
    M.NEW_ASSIGNMENT_DIFF_MD = run_dir / 'assignment_diff_vs_baseline.md'
    M.LAYER_PLANES_JSON = run_dir / 'layer_planes.json'
    M.NEW_STACK_JSON = run_dir / 'physical_layer_stack.json'
    M.NEW_RULES_JSON = run_dir / 'process_rules.json'
    M.NEW_EXPERIMENT_A = run_dir / 'experiment_A'
    return run_dir
