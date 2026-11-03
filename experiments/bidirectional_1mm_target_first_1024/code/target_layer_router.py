# -*- coding: utf-8 -*-
"""Round-2 target-layer XY candidates with real R15 straight/arc geometry."""
from __future__ import annotations

import math
from collections import OrderedDict

from . import fixed_layer_3d as F3
from ..legacy_geometry import adjacent, opposite
from ..v3c4 import lift_cross as LIFT


def candidate_paths(frame, radius=15.0, count=24):
    """Yield world-coordinate primitive lists for new target-layer bodies.

    Only orthogonal straight/quarter-arc families with the requested R15 are
    used.  No 5 mm legacy arc is ever passed to the 3D builder.
    """
    p, q = frame.p, frame.q
    tracks = []
    if frame.kind == 'opposite':
        # horizontal transfer tracks, plus a direct straight when aligned
        if abs(p[0] - q[0]) < 1e-9:
            tracks.append(None)
        for t in (p[1] + radius + 2, q[1] - radius - 2,
                  (p[1] + q[1]) / 2):
            if radius + 1 < t < 150 - radius - 1:
                tracks.append(t)
        step = max(1.0, (150 - 2 * radius) / max(1, count // 3))
        t = radius + 1
        while t <= 150 - radius - 1 and len(tracks) < count:
            tracks.append(t)
            t += step
        for t in tracks:
            try:
                if t is None:
                    prims = opposite(p, q, radius + 1, radius=radius)
                else:
                    prims = opposite(p, q, t, radius=radius)
            except Exception:
                continue
            yield [dict(x) for x in frame.to_world(prims)]
    else:
        # A single R15 L path is legal when both the vertical and horizontal
        # legs are long enough; the legacy 4-point adjacent template leaves
        # only 5 mm at the board edge and cannot be used with R15.
        tracks.append(q[1])
        step = max(1.0, (150 - 2 * radius) / max(1, count // 3))
        t = radius + 1
        while t <= 150 - radius - 1 and len(tracks) < count:
            if abs(t - q[1]) > radius:
                tracks.append(t)
            t += step
        for t in tracks:
            try:
                prims = adjacent(p, q, t, radius=radius)
            except Exception:
                continue
            yield [dict(x) for x in frame.to_world(prims)]


def try_route(lifter, record, row, target_layer, frame, *, max_candidates=24,
              max_plans=60):
    """Try new R15 XY bodies on one target layer; return (route, reason)."""
    last = 'no_candidate'
    for prims in candidate_paths(frame, radius=15.0, count=max_candidates):
        if not prims:
            continue
        route, reason, plan = F3.try_fixed_route(
            lifter, record, row, prims, target_layer, fast=None, mode='all',
            max_plans=max_plans, window_positions=5, check_plane=True)
        if route is not None:
            return route, None
        last = reason
    return None, last
