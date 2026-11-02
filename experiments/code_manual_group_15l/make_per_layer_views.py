# -*- coding: utf-8 -*-
"""Render one routing plot per physical layer for the manual-grouping 15L run.

Reuses the campaign's frozen per-layer view renderer (same geometry sampling,
same kind colours), pointed at this run's ``routes_l3d.json``.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

RUN_DIR = (ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_GROUP_15L_COMPARISON')
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN')

spec = importlib.util.spec_from_file_location(
    'campaign_layer_views', CAMPAIGN / 'make_layer_views.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.BEST = RUN_DIR
module.OUT = RUN_DIR / 'plots' / 'per_layer'
module.main()
