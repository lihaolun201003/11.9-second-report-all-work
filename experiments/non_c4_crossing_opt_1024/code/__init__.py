# -*- coding: utf-8 -*-
"""C4-free (non-C4) crossing-optimisation experiment package.

This package is the *new* independent experiment path for
``outputs/manual_c4_new_connectivity/NON_C4_CROSSING_OPT_1024``.

It reuses the frozen reheight21 module semantics (model, fanout, layer2d,
assemble, validators) but:

* overrides every writable path onto the new RUN_DIR (never the baseline),
* replaces the whole-C4-orbit layer assignment by a per-``route_id``
  C4-free assignment,
* keeps the 368 manual U routes frozen on their 8 planes,
* adds crossing-oriented analysis / search tooling.

Nothing in this package may write into the frozen 21-height baseline
``FANOUT_FIRST_21_HEIGHT_REBALANCED_1024``.
"""
from __future__ import annotations

__all__ = ['paths', 'data', 'crossings', 'assign_nc', 'run_nc',
           'validate_nc']
