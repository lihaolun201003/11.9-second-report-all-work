# -*- coding: utf-8 -*-
"""Native 3D (multi-height body) routing experiment package.

The frozen E5 result gives every movable route exactly one body height.  This
package removes that restriction: a waveguide body may leave its body height
through an exact R15 S-curve, travel at another of the 21 routing heights, and
return to the original height - so one route can own several flat segments on
different physical z planes.

Only the *geometry model* lives here; the frozen modules
(``fanout1024.layer2d``, ``fanout1024.fanout``, ``reheight21.*``) are never
modified.
"""
from __future__ import annotations

__all__ = ['common', 'transition', 'route_model', 'crossing_cache',
           'single_route', 'crossing_intervals', 'batch_avoid',
           'global_optimizer', 'validate_native3d', 'visualize']
