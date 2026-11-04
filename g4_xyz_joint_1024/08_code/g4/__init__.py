# -*- coding: utf-8 -*-
"""G4 experiment package: dynamic manual-U regrouping + large-neighbourhood
XY+Z joint re-routing on the existing XYZ router.

Owned files (interface contract, written by the Lead, do not modify):
``paths.py``, ``ledger.py``, ``joint_world.py``, ``artifacts.py``, ``arm_base.py``.

Algorithm files are owned by the individual experiment work packages
(``neighborhood.py`` / ``make_way.py`` / ``alns.py`` / ``run_g4*.py`` /
``group_replan.py`` / ``fair_runner.py`` / ...).
"""
from __future__ import annotations

__all__ = ['paths', 'ledger', 'joint_world', 'artifacts', 'arm_base']
