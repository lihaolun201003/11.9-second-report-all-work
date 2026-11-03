# -*- coding: utf-8 -*-
"""Confirmed 1 mm glass process rules.

Only the following are confirmed inputs:
* glass thickness 1.00 mm
* Z1 interface z=0.00 mm, Z2 interface z=0.50 mm
* minimum physical layer pitch 50 um
* bidirectional z routing

An 80 um *global centre-line clearance* is NOT a confirmed process requirement.
It is retained only as an explicitly named legacy mode for reproducing earlier
experiments, never as the default for the corrected run.
"""
from __future__ import annotations

GLASS_THICKNESS_MM = 1.000
Z1_MM = 0.000
Z2_MM = 0.500
MIN_LAYER_PITCH_MM = 0.050
MIN_3D_CLEARANCE_MM = 0.050       # corrected cross-layer / transition floor
LEGACY_GLOBAL_CLEARANCE_MM = 0.080  # only when mode='legacy_80um'
PROCESS_MODE = 'corrected_50um'


def clearance_for_mode(mode: str | None = None) -> float:
    mode = PROCESS_MODE if mode is None else mode
    if mode == 'legacy_80um':
        return LEGACY_GLOBAL_CLEARANCE_MM
    return MIN_3D_CLEARANCE_MM


def rules_payload():
    return {
        'schema': 'glass_1mm_process_rules_v1',
        'mode': PROCESS_MODE,
        'glass_thickness_mm': GLASS_THICKNESS_MM,
        'z1_interface_mm': Z1_MM,
        'z2_interface_mm': Z2_MM,
        'min_layer_pitch_mm': MIN_LAYER_PITCH_MM,
        'min_3d_clearance_mm': MIN_3D_CLEARANCE_MM,
        'legacy_global_clearance_mm': LEGACY_GLOBAL_CLEARANCE_MM,
        'rules': {
            'different_physical_planes': (
                'legal when |dz| >= 0.05 mm; XY overlap does not make it '
                'illegal by itself'),
            'same_physical_plane': (
                'existing 2D D56/controlled-crossing rules are unchanged; '
                'this is a same-layer geometry rule, not the global 80 um rule'),
            'transition_vs_other': (
                'true 3D centre-line distance must be >= 0.05 mm; a transition '
                'may not pass through another waveguide'),
            'layer_stack': (
                'every routing plane and interface plane must be at least '
                '0.05 mm from its neighbours'),
            'not_confirmed': (
                'optical crosstalk, fabrication tolerance and an 80 um global '
                'clearance are not confirmed process requirements'),
        },
    }
