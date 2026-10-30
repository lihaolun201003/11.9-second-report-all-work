# -*- coding: utf-8 -*-
"""Independent strict-C4 (four-fold rotation) symmetry validator for 1024-route
multi-layer layouts.

The 256 connection groups of
``outputs/manual_c4_new_connectivity/inputs/connectivity_1024.json`` are the
C4 orbits.  Strict C4 symmetry about the board centre (75, 75) means, for every
orbit and every k = 1, 2, 3::

    R(x, y, z) = (150 - y, x, z)          # z is invariant under rotation

the orbit member ``m = rotation_map[k]`` must be the exact 3D image of the
representative under ``R^k``.  A member may be *traversed in the opposite
direction* (``direction == 'reversed'``), in which case its traversal
parameter is ``s' = L - s`` and its layer/transition sequences appear in
reverse order, and transitions swap ``z0``/``z1``.

Checks implemented (all tolerance based, on the real XYZ geometry reconstructed
from ``payload['routes'][i]['parts']``):

1. orbit structure: 1024 routes / 256 orbits / four members per orbit and no
   route in two orbits;
2. endpoints: ``R^k(rep.source xy)`` equals the mapped member's source or
   target xy (and the same for the target), tolerance 1e-6 mm;
3. layer symmetry: the ordered physical flat heights of the member equal the
   representative's heights (reversed when the direction is reversed),
   tolerance 1e-9 mm;
4. transition symmetry: same transition count, transition arclength positions
   (measured from the route start along the real 2D centreline), transition
   horizontal footprints, vertical lengths and ``z0``/``z1`` map correctly
   under rotation, tolerance 1e-6 mm;
5. geometry symmetry: dense 3D centreline sampling of each route (flats via
   their line/arc primitives, transitions via the exact two-arc S-curve) and
   the **exact point-to-curve distance** from each sample of the rotated
   representative to the member's continuous 3D centreline (and the reverse
   direction), tolerance 1e-4 mm.  A point-to-curve distance is used instead of
   a point-cloud nearest-neighbour distance because two samples of the *same*
   curve taken from opposite ends can differ by up to half the sampling step;
6. per-orbit details + aggregates by ``(plane, kind)``;
7. ``symmetry_pass`` is true only when every error count is zero and the
   maximum XYZ deviation is within tolerance.

Public API
----------
``validate_layout(routes_or_payload, max_layer=None) -> dict`` (no disk write)
``validate_file(routes_path, out_dir=None) -> dict`` (writes
``<out_dir>/c4_validation.json`` when ``out_dir`` is given)

The module is deliberately self-contained: it only uses the stateless rotation
and geometry formulas plus (lazily) the frozen ``ENDPOINTS`` port table; it does
not import the e1/c4 orbit builders and it never mutates its inputs.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

EXPECTED_ROUTES = 1024
EXPECTED_ORBITS = 256
BOARD_SPAN = 150.0
BOARD_CENTRE = 75.0

DEFAULT_TOLERANCES = {
    'endpoint_mm': 1e-6,       # rotation mapped endpoint positions
    'layer_z_mm': 1e-9,        # physical flat heights
    'transition_mm': 1e-6,     # transition arclength / footprint / length / z
    'geometry_mm': 1e-4,       # dense 3D centreline bidirectional NN distance
}
GEOMETRY_STEP_MM = 0.1

ME = Path(__file__).resolve()
PROJECT_ROOT = ME.parents[2]
if str(PROJECT_ROOT) not in sys.path:  # allow ``python four_side_1024/c4/validate.py``
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_CONNECTIVITY_PATH = (PROJECT_ROOT / 'outputs' / 'manual_c4_new_connectivity'
                             / 'inputs' / 'connectivity_1024.json')

_ENDPOINTS = None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def rot_xy(x, y, k=1):
    """Strict C4 rotation ``R(x, y) = (150 - y, x)`` applied ``k`` times."""
    for _ in range(int(k) % 4):
        x, y = BOARD_SPAN - float(y), float(x)
    return x, y


def rot_xyz(point, k=1):
    x, y = rot_xy(point[0], point[1], k)
    return (x, y, float(point[2]))


def rot_inv_xy(x, y, k=1):
    """Inverse rotation ``R^-1(x, y) = (y, 150 - x)`` applied ``k`` times."""
    for _ in range(int(k) % 4):
        x, y = float(y), BOARD_SPAN - float(x)
    return (x, y)


def rot_inv_xyz(point, k=1):
    x, y = rot_inv_xy(point[0], point[1], k)
    return (x, y, float(point[2]))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding='utf-8')


def _endpoint_xy(name):
    """Port position ``(x, y)`` of an endpoint name from the frozen table."""
    global _ENDPOINTS
    if _ENDPOINTS is None:
        from four_side_1024.v3c4.inputs import ENDPOINTS
        _ENDPOINTS = ENDPOINTS
    entry = _ENDPOINTS.get(str(name))
    if entry is None:
        raise KeyError(f'unknown endpoint {name!r}')
    xy = entry['routing_xy']
    return (float(xy[0]), float(xy[1]))


# ---------------------------------------------------------------------------
# primitive geometry (2D centreline of the frozen base layout)
# ---------------------------------------------------------------------------
def prim_length(prim):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return math.hypot(float(p1[0]) - float(p0[0]),
                          float(p1[1]) - float(p0[1]))
    if prim['kind'] == 'arc':
        return abs(float(prim['radius'])) * abs(float(prim['sweep']))
    raise ValueError(f"unknown primitive kind {prim.get('kind')!r}")


def prim_point_at(prim, t):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        return (float(p0[0]) + (float(p1[0]) - float(p0[0])) * t,
                float(p0[1]) + (float(p1[1]) - float(p0[1])) * t)
    center = prim['center']
    angle = float(prim['start_angle']) + float(prim['sweep']) * t
    radius = float(prim['radius'])
    return (float(center[0]) + radius * math.cos(angle),
            float(center[1]) + radius * math.sin(angle))


def prims_length(prims):
    return float(sum(prim_length(p) for p in prims))


def prims_point_at(prims, s):
    """Exact XY point at 2D arclength ``s`` along a primitive chain."""
    total = prims_length(prims)
    s = min(max(float(s), 0.0), total)
    remain = s
    for prim in prims:
        length = prim_length(prim)
        if remain <= length + 1e-12:
            t = 1.0 if length <= 0.0 else remain / length
            return prim_point_at(prim, t)
        remain -= length
    return prim_point_at(prims[-1], 1.0)


# ---------------------------------------------------------------------------
# route part bookkeeping: 2D transitions + physical flat heights
# ---------------------------------------------------------------------------
class _RouteProfile:
    """Part-level 2D bookkeeping of one route record.

    ``transitions`` holds the transitions in traversal order with the 2D
    arclength position of their start, their horizontal footprint and their
    heights.  ``flat_heights`` is the ordered list of physical flat heights.
    ``total_2d`` is the arclength of the complete 2D centreline.
    """

    def __init__(self, record, skipped):
        self.route_id = int(record['route_id'])
        self.flat_heights = []
        self.transitions = []
        self.total_2d = 0.0
        self.usable = True
        pos = 0.0
        parts = record.get('parts') or []
        if not parts:
            skipped.append(dict(route_id=self.route_id, check='profile',
                                reason='route has no parts'))
            self.usable = False
            return
        for index, part in enumerate(parts):
            kind = part.get('kind')
            if kind == 'flat':
                prims = part.get('primitives') or []
                if prims:
                    length = prims_length(prims)
                else:
                    length = float(part.get('length_mm') or 0.0)
                    skipped.append(dict(
                        route_id=self.route_id, check='flat_length',
                        reason='flat part without primitives; used length_mm'))
                self.flat_heights.append(float(part.get('z_mm', 0.0)))
                pos += length
            elif kind == 'transition':
                start = part.get('start')
                end = part.get('end')
                if start is not None and end is not None:
                    footprint = math.hypot(float(end[0]) - float(start[0]),
                                           float(end[1]) - float(start[1]))
                else:
                    footprint = float(part.get('footprint_mm') or 0.0)
                    skipped.append(dict(
                        route_id=self.route_id, check='transition_footprint',
                        reason='transition without start/end; used footprint_mm'))
                length_mm = part.get('length_mm')
                self.transitions.append(dict(
                    index=index,
                    position_mm=float(pos),
                    footprint_mm=float(footprint),
                    length_mm=(None if length_mm is None else float(length_mm)),
                    z0=float(part.get('z0', 0.0)),
                    z1=float(part.get('z1', 0.0)),
                ))
                pos += footprint
            else:
                skipped.append(dict(route_id=self.route_id, check='profile',
                                    reason=f'unknown part kind {kind!r}'))
                self.usable = False
                return
        self.total_2d = float(pos)

    def flat_z(self):
        return [round(z, 12) for z in self.flat_heights]


# ---------------------------------------------------------------------------
# exact 3D centreline sampler
# ---------------------------------------------------------------------------
class _RouteSampler:
    """Exact 3D centreline of one route as a list of arclength segments.

    * flat segments sample the exact line/arc primitives at constant ``z``;
    * transition segments use the exact two-arc S-curve implied by
      ``start``/``end``/``z0``/``z1`` (radius/theta re-derived from real
      geometry, not read from optional metadata).
    """

    def __init__(self, record, skipped):
        self.route_id = int(record['route_id'])
        self.segments = []
        self.length3d = 0.0
        self.usable = True
        flat_z = None
        for index, part in enumerate(record.get('parts') or []):
            kind = part.get('kind')
            if kind == 'flat':
                prims = part.get('primitives') or []
                if prims:
                    length = prims_length(prims)
                else:
                    length = float(part.get('length_mm') or 0.0)
                flat_z = float(part.get('z_mm', 0.0))
                self.segments.append(dict(kind='flat', prims=prims,
                                          z_mm=flat_z, length=float(length)))
                self.length3d += float(length)
            elif kind == 'transition':
                seg = self._transition_segment(part, skipped, index)
                if seg is None:
                    self.usable = False
                    return
                self.segments.append(seg)
                self.length3d += float(seg['length'])
            else:
                skipped.append(dict(route_id=self.route_id, check='sampler',
                                    reason=f'unknown part kind {kind!r}'))
                self.usable = False
                return
        del flat_z

    def _transition_segment(self, part, skipped, index):
        try:
            start = (float(part['start'][0]), float(part['start'][1]))
            end = (float(part['end'][0]), float(part['end'][1]))
            z0 = float(part.get('z0', 0.0))
            z1 = float(part.get('z1', 0.0))
        except (KeyError, TypeError, ValueError):
            skipped.append(dict(route_id=self.route_id, check='sampler',
                                reason='transition without usable start/end/z'))
            return None
        dx, dy = end[0] - start[0], end[1] - start[1]
        footprint = math.hypot(dx, dy)
        dz = z1 - z0
        if footprint <= 1e-12:
            if abs(dz) <= 1e-12:
                return dict(kind='transition', vertical=False, length=0.0,
                            footprint=0.0, start=start, direction=(0.0, 0.0),
                            z0=z0, z1=z1, radius=0.0, theta=0.0, sign=1.0)
            skipped.append(dict(
                route_id=self.route_id, check='sampler',
                reason=('vertical discontinuity transition (footprint=0, '
                        f'dz={dz}); sampled as a single point')))
            return dict(kind='transition', vertical=True, length=0.0,
                        footprint=0.0, start=start, direction=(0.0, 0.0),
                        z0=z0, z1=z1, radius=0.0, theta=0.0,
                        sign=(1.0 if dz >= 0.0 else -1.0))
        direction = (dx / footprint, dy / footprint)
        if abs(dz) <= 1e-12:
            # degenerate "transition" with no height change
            return dict(kind='transition', vertical=False, length=0.0,
                        footprint=footprint, start=start,
                        direction=direction, z0=z0, z1=z1, radius=0.0,
                        theta=0.0, sign=1.0)
        theta = 2.0 * math.atan2(abs(dz), footprint)
        radius = footprint / (2.0 * math.sin(theta))
        length = 2.0 * radius * theta
        return dict(kind='transition', vertical=False, length=float(length),
                    footprint=float(footprint), start=start,
                    direction=direction, z0=z0, z1=z1,
                    radius=float(radius), theta=float(theta),
                    sign=(1.0 if dz >= 0.0 else -1.0))

    def point_at(self, s):
        """Exact 3D point at 3D arclength ``s`` from the route start."""
        s = min(max(float(s), 0.0), self.length3d)
        if s >= self.length3d - 1e-12 and self.segments:
            # evaluate exactly at the end to avoid fp drift
            seg = self.segments[-1]
            return self._segment_point(seg, seg['length'])
        remain = s
        for seg in self.segments:
            if remain <= seg['length'] + 1e-12:
                return self._segment_point(seg, min(remain, seg['length']))
            remain -= seg['length']
        seg = self.segments[-1]
        return self._segment_point(seg, seg['length'])

    @staticmethod
    def _segment_point(seg, local):
        if seg['kind'] == 'flat':
            if seg['prims']:
                x, y = prims_point_at(seg['prims'], local)
            else:
                x = y = 0.0
            return (x, y, float(seg['z_mm']))
        if seg['vertical'] or seg['footprint'] <= 1e-12:
            return (float(seg['start'][0]), float(seg['start'][1]),
                    float(seg['z0']))
        length = seg['length']
        t = 0.0 if length <= 0.0 else min(max(local / length, 0.0), 1.0)
        radius, theta = seg['radius'], seg['theta']
        footprint = seg['footprint']
        sign = seg['sign']
        mid_w = 0.5 * (seg['z0'] + seg['z1'])
        if t <= 0.5:
            phi = theta * (2.0 * t)
            u = radius * math.sin(phi)
            w = seg['z0'] + sign * radius * (1.0 - math.cos(phi))
        else:
            t2 = 1.0 - t
            phi = theta * (2.0 * t2)
            u = footprint - radius * math.sin(phi)
            w = 2.0 * mid_w - (seg['z0'] + sign * radius
                               * (1.0 - math.cos(phi)))
        start = seg['start']
        direction = seg['direction']
        return (start[0] + direction[0] * u,
                start[1] + direction[1] * u, w)

    def sample(self, step=GEOMETRY_STEP_MM, from_end=False):
        """Dense points at a uniform 3D arclength step (both ends included)."""
        length = self.length3d
        if length <= 1e-12:
            return [self.point_at(0.0)]
        count = max(1, int(math.ceil(length / float(step))))
        if from_end:
            positions = [max(length - i * step, 0.0) for i in range(count + 1)]
            if positions[-1] != 0.0:
                positions.append(0.0)
        else:
            positions = [min(i * step, length) for i in range(count + 1)]
            if positions[-1] != length:
                positions.append(length)
        return [self.point_at(s) for s in positions]

    def curve_distance(self, points):
        """Exact 3D distance from each point to this route's centreline."""
        np = _np()
        pts = np.asarray(points, dtype=float)
        if pts.size == 0:
            return np.zeros(0)
        best = np.full(len(pts), np.inf)
        for seg in self.segments:
            if seg['kind'] == 'flat':
                distance = _flat_part_distance(pts, seg['prims'], seg['z_mm'])
            else:
                distance = _transition_part_distance(pts, seg)
            best = np.minimum(best, distance)
        return best


# ---------------------------------------------------------------------------
# exact point-to-curve distances (the geometry-symmetry metric)
# ---------------------------------------------------------------------------
TAU = 2.0 * math.pi


def _np():
    import numpy as np
    return np


def _arc_distance_uw(qu, qw, cu, cw, radius, start_angle, sweep):
    """Exact distance from 2D points ``(qu, qw)`` to one circular arc.

    The arc has centre ``(cu, cw)``, ``radius``, starts at ``start_angle`` and
    spans ``sweep`` radians (signed).  A point whose angle projects inside the
    angular span is at ``|dist(centre) - radius|``; otherwise the nearest arc
    endpoint wins.
    """
    np = _np()
    du = qu - cu
    dw = qw - cw
    radial = np.abs(np.hypot(du, dw) - float(radius))
    if abs(float(sweep)) >= TAU - 1e-12:
        return radial
    angle = np.arctan2(dw, du)
    if sweep >= 0.0:
        delta = np.mod(angle - float(start_angle), TAU)
        inside = delta <= float(sweep) + 1e-12
    else:
        delta = np.mod(float(start_angle) - angle, TAU)
        inside = delta <= -float(sweep) + 1e-12
    end0 = (cu + radius * math.cos(start_angle),
            cw + radius * math.sin(start_angle))
    end_angle = start_angle + sweep
    end1 = (cu + radius * math.cos(end_angle),
            cw + radius * math.sin(end_angle))
    endpoint_distance = np.minimum(np.hypot(qu - end0[0], qw - end0[1]),
                                   np.hypot(qu - end1[0], qw - end1[1]))
    return np.where(inside, radial, endpoint_distance)


def _points_to_prim_distance(points, prim):
    """Exact 2D distance from ``points[:, :2]`` to one line/arc primitive."""
    np = _np()
    xs, ys = points[:, 0], points[:, 1]
    if prim['kind'] == 'line':
        ax, ay = float(prim['p0'][0]), float(prim['p0'][1])
        bx, by = float(prim['p1'][0]), float(prim['p1'][1])
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den <= 1e-18:
            return np.hypot(xs - ax, ys - ay)
        t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / den, 0.0, 1.0)
        return np.hypot(xs - (ax + t * dx), ys - (ay + t * dy))
    if prim['kind'] == 'arc':
        cx, cy = float(prim['center'][0]), float(prim['center'][1])
        return _arc_distance_uw(xs, ys, cx, cy, float(prim['radius']),
                                float(prim['start_angle']),
                                float(prim['sweep']))
    raise ValueError(f"unknown primitive kind {prim.get('kind')!r}")


def _flat_part_distance(points, prims, z_mm):
    """Exact 3D distance from points to a flat part (2D curve at height z)."""
    np = _np()
    count = len(points)
    if not prims:
        return np.abs(points[:, 2] - float(z_mm))
    distance2d = np.full(count, np.inf)
    for prim in prims:
        distance2d = np.minimum(distance2d, _points_to_prim_distance(points, prim))
    return np.sqrt(distance2d * distance2d
                   + (points[:, 2] - float(z_mm)) ** 2)


def _transition_part_distance(points, seg):
    """Exact 3D distance from points to the two-arc S-curve of a transition.

    The S-curve is a planar curve in the vertical plane spanned by the local
    XY direction; decomposing a query point into ``(u, v, z)`` (u along the
    direction, v perpendicular in XY) gives
    ``distance = sqrt(v**2 + d_uw**2)`` with ``d_uw`` the exact distance in the
    vertical ``(u, z)`` plane to the two arcs.
    """
    np = _np()
    sx, sy = float(seg['start'][0]), float(seg['start'][1])
    dx, dy = seg['direction']
    px, py = points[:, 0] - sx, points[:, 1] - sy
    u = px * dx + py * dy
    v = np.abs(px * dy - py * dx)
    qz = points[:, 2]
    z0, z1 = float(seg['z0']), float(seg['z1'])
    footprint = float(seg['footprint'])
    if seg.get('vertical'):
        low, high = (z0, z1) if z0 <= z1 else (z1, z0)
        return np.hypot(np.hypot(px, py), qz - np.clip(qz, low, high))
    if footprint <= 1e-12:
        return np.hypot(np.hypot(px, py), qz - z0)
    if seg['theta'] <= 1e-12:
        # zero height change: a straight chord at constant height
        du = np.maximum(np.maximum(-u, u - footprint), 0.0)
        return np.sqrt((v * v) + du * du + (qz - z0) ** 2)
    radius = float(seg['radius'])
    theta = float(seg['theta'])
    sign = float(seg['sign'])
    first = _arc_distance_uw(u, qz, 0.0, z0 + sign * radius, radius,
                             -sign * math.pi / 2.0, sign * theta)
    second = _arc_distance_uw(u, qz, footprint, z1 - sign * radius, radius,
                              sign * math.pi / 2.0, sign * theta)
    distance_uw = np.minimum(first, second)
    return np.sqrt(v * v + distance_uw * distance_uw)


# ---------------------------------------------------------------------------
# layout / connectivity loading
# ---------------------------------------------------------------------------
def _coerce_layout(routes_or_payload):
    """Return ``(records, payload, source_path)`` from list/dict/JSON path."""
    if isinstance(routes_or_payload, (str, Path)):
        path = Path(routes_or_payload)
        payload = _read_json(path)
        if not isinstance(payload, dict) or 'routes' not in payload:
            raise ValueError(f'{path} has no "routes" payload')
        return list(payload['routes']), payload, str(path)
    if isinstance(routes_or_payload, dict):
        if 'routes' not in routes_or_payload:
            raise ValueError('payload dict has no "routes" key')
        return list(routes_or_payload['routes']), routes_or_payload, None
    if isinstance(routes_or_payload, (list, tuple)):
        return list(routes_or_payload), None, None
    raise TypeError('routes_or_payload must be a route list, a payload dict or '
                    'a JSON path')


def _is_routed(record):
    status = record.get('status')
    if status is None:
        return True
    return str(status).lower() in ('routed', 'ok', 'valid', 'accepted')


def _load_connectivity(path=None):
    path = Path(path) if path is not None else DEFAULT_CONNECTIVITY_PATH
    payload = _read_json(path)
    groups = []
    for group in payload['groups']:
        groups.append(dict(
            group_id=int(group['group_id']),
            kind=str(group.get('kind', '')),
            plane=str(group.get('plane', '')),
            route_ids=sorted(int(r) for r in group['route_ids'])))
    return groups, str(path)


def _infer_max_layer(payload):
    """Highest routing layer id declared by the payload layer stack."""
    if not isinstance(payload, dict):
        return None
    stack = payload.get('layer_stack') or {}
    heights = stack.get('routing_heights_mm') or {}
    ids = []
    for key in heights:
        try:
            ids.append(int(key))
        except (TypeError, ValueError):
            continue
    for key, entry in (stack.get('layers') or {}).items():
        try:
            entry = entry or {}
            if str(entry.get('layer_type', 'routing')) == 'routing':
                ids.append(int(entry.get('layer_id', key)))
        except (TypeError, ValueError):
            continue
    return max(ids) if ids else None


# ---------------------------------------------------------------------------
# core validator
# ---------------------------------------------------------------------------
def validate_layout(routes_or_payload, max_layer=None, connectivity_path=None,
                    tolerances=None):
    """Validate one 1024-route layout against strict C4 symmetry.

    Parameters
    ----------
    routes_or_payload : list[dict] | dict | str | Path
        Route records, a ``routes_1024.json`` payload (``{'routes': [...]}``)
        or a path to such a JSON file.
    max_layer : int | None
        Highest routing layer id used by the layout, recorded in the report
        (inferred from ``payload['layer_stack']`` when omitted).
    connectivity_path : str | Path | None
        Orbit definition file; defaults to the frozen
        ``outputs/manual_c4_new_connectivity/inputs/connectivity_1024.json``.
    tolerances : dict | None
        Overrides for ``DEFAULT_TOLERANCES``.

    Returns
    -------
    dict
        Full report; see module docstring. No files are written.
    """
    tol = dict(DEFAULT_TOLERANCES)
    tol.update(tolerances or {})
    records_all, payload, source_path = _coerce_layout(routes_or_payload)
    inferred_max_layer = _infer_max_layer(payload)
    if max_layer is None:
        max_layer = inferred_max_layer
    else:
        max_layer = int(max_layer)

    skipped = []
    records = [r for r in records_all if _is_routed(r)]
    routed_ids = [int(r['route_id']) for r in records]
    unrouted_ids = sorted(int(r['route_id']) for r in records_all
                          if not _is_routed(r))
    by_id = {}
    duplicate_ids = []
    for record in records:
        rid = int(record['route_id'])
        if rid in by_id:
            duplicate_ids.append(rid)
        else:
            by_id[rid] = record

    groups, connectivity_used = _load_connectivity(connectivity_path)

    # -- orbit structure ---------------------------------------------------
    orbit_size_errors = []
    membership = Counter()
    known_ids = set()
    for group in groups:
        known_ids.update(group['route_ids'])
        for rid in group['route_ids']:
            membership[rid] += 1
    duplicate_memberships = sorted(rid for rid, count in membership.items()
                                   if count > 1)
    missing_route_ids = sorted(known_ids - set(by_id))
    extra_route_ids = sorted(set(by_id) - known_ids)
    for group in groups:
        if len(group['route_ids']) != 4:
            orbit_size_errors.append(dict(
                group_id=group['group_id'], plane=group['plane'],
                kind=group['kind'], n_routes=len(group['route_ids']),
                route_ids=group['route_ids'],
                reason='orbit must contain exactly 4 routes'))
    if duplicate_ids:
        orbit_size_errors.append(dict(
            reason='duplicate route records in layout',
            route_ids=sorted(set(duplicate_ids))))
    if duplicate_memberships:
        orbit_size_errors.append(dict(
            reason='route appears in more than one orbit',
            route_ids=duplicate_memberships))
    if missing_route_ids:
        orbit_size_errors.append(dict(
            reason='connectivity routes missing from layout',
            route_ids=missing_route_ids))

    total_routes = len(records)
    total_orbits = len(groups)

    # -- per route profiles / samplers ------------------------------------
    profiles = {}
    samplers = {}
    for rid, record in by_id.items():
        profile = _RouteProfile(record, skipped)
        sampler = _RouteSampler(record, skipped)
        profiles[rid] = profile
        samplers[rid] = sampler

    endpoint_errors = []
    layer_errors = []
    transition_errors = []
    geometry_errors = []
    max_xyz_dev = 0.0
    worst_pair = None
    per_orbit = []
    failed_orbits = []
    geo_step = GEOMETRY_STEP_MM

    for group in groups:
        gid = group['group_id']
        ids = group['route_ids']
        present = [rid for rid in ids if rid in by_id]
        rep = min(present) if present else None
        orbit_entry = dict(
            group_id=gid, plane=group['plane'], kind=group['kind'],
            route_ids=ids, rep=rep, n_present=len(present),
            rotations=[], plane_error=False,
            endpoint_ok=True, layer_ok=True, transition_ok=True,
            geometry_ok=True, xyz_max_mm=0.0, failed=False)
        if rep is None:
            orbit_entry.update(failed=True, skipped='no routed member')
            per_orbit.append(orbit_entry)
            continue
        rep_record = by_id[rep]
        rep_profile = profiles[rep]
        rep_sampler = samplers[rep]
        try:
            rep_src = _endpoint_xy(rep_record.get('source_endpoint'))
            rep_tgt = _endpoint_xy(rep_record.get('target_endpoint'))
        except (KeyError, TypeError):
            skipped.append(dict(group_id=gid, check='endpoints',
                                reason='representative endpoint missing '
                                       'from ENDPOINTS table'))
            orbit_entry.update(failed=True, skipped='representative endpoints')
            per_orbit.append(orbit_entry)
            continue
        # planes must agree inside an orbit (C4 keeps z, so base heights equal)
        orbit_planes = {str(by_id[rid].get('plane', '')) for rid in present}
        if len(orbit_planes - {''}) > 1 or (group['plane'] and
                                            orbit_planes - {'', group['plane']}):
            orbit_entry['plane_error'] = True

        used = {rep}
        rotation_map = {}
        for k in (1, 2, 3):
            expected_src = rot_xy(rep_src[0], rep_src[1], k)
            expected_tgt = rot_xy(rep_tgt[0], rep_tgt[1], k)
            best = None
            for rid in present:
                if rid in used:
                    continue
                member = by_id[rid]
                try:
                    s_xy = _endpoint_xy(member.get('source_endpoint'))
                    t_xy = _endpoint_xy(member.get('target_endpoint'))
                except (KeyError, TypeError):
                    continue
                d_src = math.hypot(expected_src[0] - s_xy[0],
                                   expected_src[1] - s_xy[1])
                d_tgt = math.hypot(expected_tgt[0] - t_xy[0],
                                   expected_tgt[1] - t_xy[1])
                d_rev_src = math.hypot(expected_src[0] - t_xy[0],
                                       expected_src[1] - t_xy[1])
                d_rev_tgt = math.hypot(expected_tgt[0] - s_xy[0],
                                       expected_tgt[1] - s_xy[1])
                forward_dev = max(d_src, d_tgt)
                reversed_dev = max(d_rev_src, d_rev_tgt)
                direction = ('forward' if forward_dev <= reversed_dev
                             else 'reversed')
                entry = dict(route_id=rid, direction=direction,
                             endpoint_dev_mm=float(min(forward_dev,
                                                       reversed_dev)),
                             map_dev_mm=float(min(d_src, d_tgt)),
                             forward=True)
                if best is None or entry['endpoint_dev_mm'] < best[
                        'endpoint_dev_mm']:
                    best = entry
            if best is None:
                endpoint_errors.append(dict(
                    group_id=gid, plane=group['plane'], kind=group['kind'],
                    k=k, rep=rep, reason='no unused member left for rotation',
                    expected_source_xy=[float(expected_src[0]),
                                        float(expected_src[1])]))
                orbit_entry['endpoint_ok'] = False
                continue
            rid = int(best['route_id'])
            used.add(rid)
            member = by_id[rid]
            direction = best['direction']
            rotation_map[k] = dict(route_id=rid, direction=direction)
            e1 = best['endpoint_dev_mm']
            if e1 > tol['endpoint_mm']:
                endpoint_errors.append(dict(
                    group_id=gid, plane=group['plane'], kind=group['kind'],
                    k=k, rep=rep, member=rid, direction=direction,
                    reason='rotated endpoint does not match member endpoint',
                    dev_mm=float(e1),
                    expected_source_xy=[float(expected_src[0]),
                                        float(expected_src[1])],
                    expected_target_xy=[float(expected_tgt[0]),
                                        float(expected_tgt[1])]))
                orbit_entry['endpoint_ok'] = False

            member_profile = profiles[rid]
            member_sampler = samplers[rid]
            rotation_entry = dict(
                k=int(k), route_id=int(rid), direction=direction,
                map_dev_mm=float(best['map_dev_mm']),
                endpoint_dev_mm=float(e1),
                layer_ok=True, transition_ok=True,
                xyz_dev_mm=0.0)

            # -- 3. layer symmetry (physical flat heights, reversal aware) --
            expected_heights = list(rep_profile.flat_heights)
            if direction == 'reversed':
                expected_heights = list(reversed(expected_heights))
            actual_heights = list(member_profile.flat_heights)
            layer_ok = (
                len(expected_heights) == len(actual_heights)
                and all(abs(a - b) <= tol['layer_z_mm']
                        for a, b in zip(expected_heights, actual_heights)))
            if not layer_ok:
                rotation_entry['layer_ok'] = False
                orbit_entry['layer_ok'] = False
                layer_errors.append(dict(
                    group_id=gid, plane=group['plane'], kind=group['kind'],
                    k=int(k), rep=rep, member=int(rid), direction=direction,
                    reason=('flat height count differs'
                            if len(expected_heights) != len(actual_heights)
                            else 'flat heights differ'),
                    expected_flat_z_mm=[float(v) for v in expected_heights],
                    member_flat_z_mm=[float(v) for v in actual_heights]))

            # -- 4. transition symmetry -----------------------------------
            transition_ok, transition_detail = _compare_transitions(
                rep_profile, member_profile, direction, tol['transition_mm'])
            if not transition_ok:
                rotation_entry['transition_ok'] = False
                orbit_entry['transition_ok'] = False
                transition_errors.append(dict(
                    group_id=gid, plane=group['plane'], kind=group['kind'],
                    k=int(k), rep=rep, member=int(rid), direction=direction,
                    **transition_detail))

            # -- 5. geometry symmetry (exact point-to-curve, 3D) ----------
            if (rep_sampler.usable and rep_sampler.segments
                    and member_sampler.usable and member_sampler.segments):
                np = _np()
                rep_points = (rep_sampler.sample(step=geo_step, from_end=False)
                              + rep_sampler.sample(step=geo_step,
                                                   from_end=True))
                member_points = (member_sampler.sample(step=geo_step,
                                                       from_end=False)
                                 + member_sampler.sample(step=geo_step,
                                                         from_end=True))
                rotated_rep = np.asarray([rot_xyz(p, k) for p in rep_points],
                                         dtype=float)
                # rotated representative samples -> member continuous curve
                distance_member = member_sampler.curve_distance(rotated_rep)
                index_member = int(np.argmax(distance_member))
                dev_member = float(distance_member[index_member])
                # member samples mapped back by R^-k -> representative curve
                back_points = np.asarray([rot_inv_xyz(p, k)
                                          for p in member_points], dtype=float)
                distance_rep = rep_sampler.curve_distance(back_points)
                index_rep = int(np.argmax(distance_rep))
                dev_rep = float(distance_rep[index_rep])
                if dev_member >= dev_rep:
                    dev = dev_member
                    worst_point = [float(v) for v in rotated_rep[index_member]]
                else:
                    dev = dev_rep
                    worst_point = [float(v) for v in back_points[index_rep]]
                rotation_entry['xyz_dev_mm'] = float(dev)
                if dev > max_xyz_dev:
                    max_xyz_dev = float(dev)
                    worst_pair = dict(
                        group_id=gid, plane=group['plane'], kind=group['kind'],
                        k=int(k), rep=rep, member=int(rid),
                        direction=direction, xyz_dev_mm=float(dev),
                        worst_point_mm=worst_point)
                if dev > tol['geometry_mm']:
                    orbit_entry['geometry_ok'] = False
                    geometry_errors.append(dict(
                        group_id=gid, plane=group['plane'],
                        kind=group['kind'], k=int(k), rep=rep,
                        member=int(rid), direction=direction,
                        xyz_dev_mm=float(dev),
                        tolerance_mm=float(tol['geometry_mm']),
                        worst_point_mm=worst_point))
            else:
                skipped.append(dict(
                    group_id=gid, k=int(k), route_id=int(rid),
                    check='geometry', reason='route has no usable parts'))
                orbit_entry['geometry_ok'] = False

            orbit_entry['xyz_max_mm'] = max(orbit_entry['xyz_max_mm'],
                                            rotation_entry['xyz_dev_mm'])
            orbit_entry['rotations'].append(rotation_entry)

        orbit_entry['failed'] = not (orbit_entry['endpoint_ok']
                                     and orbit_entry['layer_ok']
                                     and orbit_entry['transition_ok']
                                     and orbit_entry['geometry_ok']
                                     and not orbit_entry['plane_error'])
        per_orbit.append(orbit_entry)
        if orbit_entry['failed']:
            failed_orbits.append(_failed_orbit_detail(
                orbit_entry, group, by_id, profiles))

    # -- aggregates --------------------------------------------------------
    def _orbit_count(entries):
        return len({entry['group_id'] for entry in entries})

    by_plane_kind = defaultdict(lambda: dict(
        orbits=0, failed_orbits=0, endpoint_orbit_errors=0,
        layer_orbit_errors=0, transition_orbit_errors=0,
        geometry_orbit_errors=0))
    orbit_verdicts = {entry['group_id']: entry for entry in per_orbit}
    for group in groups:
        key = (group['plane'], group['kind'])
        bucket = by_plane_kind[key]
        bucket['orbits'] += 1
        entry = orbit_verdicts.get(group['group_id'])
        if entry is None:
            continue
        if entry['failed']:
            bucket['failed_orbits'] += 1
        for field, counter_name in (
                ('endpoint_ok', 'endpoint_orbit_errors'),
                ('layer_ok', 'layer_orbit_errors'),
                ('transition_ok', 'transition_orbit_errors'),
                ('geometry_ok', 'geometry_orbit_errors')):
            if not entry[field]:
                bucket[counter_name] += 1
    error_counts_by_plane_kind = [
        dict(plane=plane, kind=kind, **values)
        for (plane, kind), values in sorted(by_plane_kind.items())]

    structural_errors = len(orbit_size_errors)
    endpoint_error_count = len(endpoint_errors)
    layer_error_count = len(layer_errors)
    transition_error_count = len(transition_errors)
    geometry_error_count = len(geometry_errors)
    endpoint_error_orbits = _orbit_count(endpoint_errors)
    layer_error_orbits = _orbit_count(layer_errors)
    transition_error_orbits = _orbit_count(transition_errors)
    geometry_error_orbits = _orbit_count(geometry_errors)
    failed_orbit_ids = [entry['group_id'] for entry in failed_orbits]

    structure_ok = (structural_errors == 0
                    and total_routes == EXPECTED_ROUTES
                    and total_orbits == EXPECTED_ORBITS
                    and not extra_route_ids
                    and not missing_route_ids)
    symmetry_pass = bool(
        structure_ok
        and endpoint_error_count == 0
        and layer_error_count == 0
        and transition_error_count == 0
        and geometry_error_count == 0
        and max_xyz_dev <= tol['geometry_mm'])

    report = {
        'schema': 'four_side_1024_strict_c4_validation_v1',
        'validator': str(ME),
        'generated_at': _now_iso(),
        'routes_path': source_path,
        'connectivity_path': connectivity_used,
        'max_layer': max_layer,
        'max_layer_inferred_from_payload': inferred_max_layer,
        'tolerances': {key: float(value) for key, value in tol.items()},
        'sampling': dict(
            geometry_step_mm=float(geo_step),
            geometry_metric=('max over dense centreline samples of the exact '
                             'point-to-curve distance, bidirectional'),
            transition_model='exact two-arc S-curve',
            transition_arclength='flat parts consume their 2D length; '
                                 'transitions consume their XY footprint'),
        'expected': dict(total_routes=EXPECTED_ROUTES,
                         total_orbits=EXPECTED_ORBITS),
        'total_routes': int(total_routes),
        'total_orbits': int(total_orbits),
        'unrouted_route_ids': unrouted_ids,
        'missing_route_ids': missing_route_ids,
        'extra_route_ids': extra_route_ids,
        'duplicate_route_records': sorted(set(duplicate_ids)),
        'duplicate_orbit_memberships': duplicate_memberships,
        'orbit_size_errors': orbit_size_errors,
        'orbit_size_error_count': int(len(orbit_size_errors)),
        'endpoint_rotation_errors': endpoint_errors,
        'endpoint_rotation_error_count': int(endpoint_error_count),
        'endpoint_rotation_error_orbits': int(endpoint_error_orbits),
        'layer_symmetry_errors': layer_errors,
        'layer_symmetry_error_count': int(layer_error_count),
        'layer_symmetry_error_orbits': int(layer_error_orbits),
        'transition_symmetry_errors': transition_errors,
        'transition_symmetry_error_count': int(transition_error_count),
        'transition_symmetry_error_orbits': int(transition_error_orbits),
        'geometry_symmetry_errors': geometry_errors,
        'geometry_symmetry_error_count': int(geometry_error_count),
        'geometry_symmetry_error_orbits': int(geometry_error_orbits),
        'maximum_xyz_deviation_mm': float(max_xyz_dev),
        'worst_geometry_pair': worst_pair,
        'failed_orbit_count': int(len(failed_orbits)),
        'failed_orbit_ids': failed_orbit_ids,
        'failed_orbits': failed_orbits,
        'per_orbit': per_orbit,
        'error_counts_by_plane_kind': error_counts_by_plane_kind,
        'skipped_checks': skipped,
        'skipped_check_count': int(len(skipped)),
        'structure_ok': bool(structure_ok),
        'symmetry_pass': symmetry_pass,
        'verdict': 'PASS' if symmetry_pass else 'FAIL',
        'notes': [
            ('Independent validator: own rotation/geometry formulas; the orbit '
             'definition comes from connectivity_1024.json, the verdict never '
             'uses eight_builder-side symmetry metadata.'),
            ('Error counts are pair counts over (orbit, k); the *_orbits '
             'fields count distinct orbits and are the headline numbers.'),
            ('A member may be traversed in the opposite direction; layer and '
             'transition sequences are then compared reversed and transition '
             'z0/z1 swapped, and the representative is sampled from both '
             'traversal ends for the geometry check.'),
        ],
    }
    return report


def _compare_transitions(rep_profile, member_profile, direction, tol_mm):
    """Rotation-aware comparison of the transition inventories of two routes."""
    rep_transitions = rep_profile.transitions
    member_transitions = member_profile.transitions
    expected = []
    for transition in rep_transitions:
        position = float(transition['position_mm'])
        footprint = float(transition['footprint_mm'])
        z0, z1 = float(transition['z0']), float(transition['z1'])
        length = transition['length_mm']
        if direction == 'forward':
            expected.append(dict(position_mm=position,
                                 footprint_mm=footprint, z0=z0, z1=z1,
                                 length_mm=length))
        else:
            position = float(member_profile.total_2d) - position - footprint
            expected.append(dict(position_mm=position,
                                 footprint_mm=footprint, z0=z1, z1=z0,
                                 length_mm=length))
    expected.sort(key=lambda item: item['position_mm'])
    actual = []
    for transition in member_transitions:
        actual.append(dict(position_mm=float(transition['position_mm']),
                           footprint_mm=float(transition['footprint_mm']),
                           z0=float(transition['z0']),
                           z1=float(transition['z1']),
                           length_mm=transition['length_mm']))
    actual.sort(key=lambda item: item['position_mm'])

    def pack(items, keys):
        return [[item[key] for key in keys] for item in items]

    detail_keys = ('position_mm', 'footprint_mm', 'z0', 'z1')
    if len(expected) != len(actual):
        return False, dict(
            reason='transition count differs',
            expected_transition_count=len(expected),
            member_transition_count=len(actual),
            expected_transitions=pack(expected, detail_keys),
            member_transitions=pack(actual, detail_keys))
    for index, (want, got) in enumerate(zip(expected, actual)):
        for key in detail_keys:
            if abs(float(want[key]) - float(got[key])) > tol_mm:
                return False, dict(
                    reason=f'transition {index} {key} differs',
                    expected_transitions=pack(expected, detail_keys),
                    member_transitions=pack(actual, detail_keys),
                    max_abs_dev_mm=float(max(
                        abs(float(want[k]) - float(got[k]))
                        for k in detail_keys)))
    return True, dict(
        expected_transitions=pack(expected, detail_keys),
        member_transitions=pack(actual, detail_keys))


def _failed_orbit_detail(orbit_entry, group, by_id, profiles):
    """Compact failure detail of one orbit (for the JSON report)."""
    ids = group['route_ids']
    detail = dict(
        group_id=group['group_id'], plane=group['plane'], kind=group['kind'],
        route_ids=ids, rep=orbit_entry['rep'],
        endpoint_error=not orbit_entry['endpoint_ok'],
        layer_error=not orbit_entry['layer_ok'],
        transition_error=not orbit_entry['transition_ok'],
        geometry_error=not orbit_entry['geometry_ok'],
        plane_error=orbit_entry['plane_error'],
        max_xyz_deviation_mm=float(orbit_entry['xyz_max_mm']),
        flat_z_by_route={int(rid): [float(z) for z in
                                    profiles[rid].flat_heights]
                         for rid in ids if rid in profiles},
        transitions_by_route={int(rid): [
            [float(t['position_mm']), float(t['footprint_mm']),
             float(t['z0']), float(t['z1'])]
            for t in profiles[rid].transitions]
            for rid in ids if rid in profiles},
        rotations=orbit_entry['rotations'],
    )
    return detail


# ---------------------------------------------------------------------------
# file convenience API
# ---------------------------------------------------------------------------
def validate_file(routes_path, out_dir=None, max_layer=None,
                  connectivity_path=None, tolerances=None):
    """Validate a ``routes_*.json`` file; optionally write ``c4_validation.json``.

    Parameters
    ----------
    routes_path : str | Path
        Path to a payload JSON with a ``routes`` list.
    out_dir : str | Path | None
        When given, ``<out_dir>/c4_validation.json`` is written.
    max_layer, connectivity_path, tolerances
        Forwarded to :func:`validate_layout`.

    Returns
    -------
    dict
        The report returned by :func:`validate_layout`.
    """
    report = validate_layout(routes_path, max_layer=max_layer,
                             connectivity_path=connectivity_path,
                             tolerances=tolerances)
    if out_dir is not None:
        out_path = Path(out_dir) / 'c4_validation.json'
        _write_json(out_path, report)
        report['written_to'] = str(out_path)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_summary(report):
    print(f"routes: {report['total_routes']}  orbits: {report['total_orbits']}"
          f"  max_layer: {report['max_layer']}")
    print(f"orbit_size_errors: {report['orbit_size_error_count']}  "
          f"endpoint_rotation_errors: {report['endpoint_rotation_error_count']}"
          f" ({report['endpoint_rotation_error_orbits']} orbits)")
    print(f"layer_symmetry_errors: {report['layer_symmetry_error_count']} "
          f"({report['layer_symmetry_error_orbits']} orbits)  "
          f"transition_symmetry_errors: "
          f"{report['transition_symmetry_error_count']} "
          f"({report['transition_symmetry_error_orbits']} orbits)")
    print(f"geometry_symmetry_errors: {report['geometry_symmetry_error_count']}"
          f" ({report['geometry_symmetry_error_orbits']} orbits)  "
          f"maximum_xyz_deviation_mm: {report['maximum_xyz_deviation_mm']:.6g}")
    print(f"failed_orbits: {report['failed_orbit_count']}  "
          f"symmetry_pass: {report['symmetry_pass']}  "
          f"verdict: {report['verdict']}")
    if report.get('written_to'):
        print(f"report written to: {report['written_to']}")
    if report['skipped_check_count']:
        print(f"skipped_checks: {report['skipped_check_count']}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Strict C4 symmetry validator for 1024-route layouts')
    parser.add_argument('routes', help='path to routes_1024.json payload')
    parser.add_argument('--out-dir', default=None,
                        help='directory for c4_validation.json')
    parser.add_argument('--max-layer', type=int, default=None)
    parser.add_argument('--connectivity', default=None,
                        help='orbit definition JSON (defaults to frozen input)')
    args = parser.parse_args(argv)
    report = validate_file(args.routes, out_dir=args.out_dir,
                           max_layer=args.max_layer,
                           connectivity_path=args.connectivity)
    _print_summary(report)
    return 0 if report['symmetry_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
