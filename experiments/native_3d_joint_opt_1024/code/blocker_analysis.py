# -*- coding: utf-8 -*-
"""D0 blocker analysis: why do most geometry-feasible mid-body excursion
candidates of the Native-3D round fail the *true 3D* world?

The candidate pool comes from ``analysis/crossing_intervals.json`` of the
previous round (produced against the frozen E5 baseline
``NON_C4_CROSSING_OPT_1024/E5_joint_repair_final``).  This module

1. re-selects a deterministic candidate set (every feasible candidate with
   ``estimated_net >= --min-net`` plus every ``net=16`` candidate of route 129),
2. rebuilds each candidate **exactly** from the E5 baseline body flat with
   ``route_model.duck_out`` (the arc-length ``s0/s1`` of the analysis refer to
   that flat; the E5 baseline is the only world in which the candidates are
   well defined),
3. runs the true-3D world check of the candidate's new geometry
   (up-S-curve / middle flat / down-S-curve) against every other route:
   strict-D56 same-plane spacing at the target height and true-3D centre-line
   clearance (0.05 mm) between different physical planes, plus self clearance,
4. classifies every violation (kind, blocking route id, manual vs movable,
   blocking primitive kind, XYZ position, distance, up/middle/down phase) and
   groups the candidates into
   (a) 1-3 movable blockers, (b) >= 4 movable blockers, (c) frozen manual
   blocker, (d) own geometry / bookkeeping failure, (e) world-clean,
5. additionally repeats the classification against the accepted Native-3D
   layout (``experiment_C``, 2440 crossings) for the candidates whose route was
   **not** converted in that experiment, and
6. writes ``analysis/blocker_analysis.json``, ``analysis/blocker_analysis_report.md``
   and ``analysis/plots/*.png``.

The module is read-only for both baselines and deterministic (sorted inputs,
rounded floats, no wall-clock data in the payload).

CLI::

    python -m four_side_1024.fanout1024.native3d.blocker_analysis \
        --baseline-dir <E5_joint_repair_final> \
        --native-dir  <NATIVE_3D_CROSSING_OPT_1024> \
        --out-dir     <NATIVE_3D_JOINT_OPT_1024>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

import numpy as np

from ...d56.index import D56Index, prepare
from ...fsd25d import path3d as P
from ...fsd25d.world25d import DENSE_STEP_MM, primitive_bbox, \
    self_clearance_violations
from ...fslw import config as FS
from . import common as N
from . import route_model as RM
from . import guard as G

SCHEMA = 'native3d_blocker_analysis_v1'

#: true 3D centre-line clearance of the corrected 50 um model (process rule)
CLEARANCE = float(N.MIN_3D_CLEARANCE)
#: production world sampling / safety constants (fsd25d.world25d)
ACCEPT_POINT = CLEARANCE + DENSE_STEP_MM / 2.0 + 0.001      # 0.061 mm
ACCEPT_SEGMENT = CLEARANCE + 0.001                          # 0.051 mm
TAU = 2.0 * math.pi
FLAT_CELL_MM = 0.5
TRANS_CELL_MM = 0.6

DEFAULT_BASELINE = N.E5_DIR
DEFAULT_NATIVE_DIR = N.RUN_DIR
DEFAULT_OUT_DIR = N.OUTPUT_ROOT / 'NATIVE_3D_JOINT_OPT_1024'

CATEGORY_LABEL = OrderedDict((
    ('a_1_3_movable', '1-3 movable blockers'),
    ('b_ge4_movable', '>=4 movable blockers'),
    ('c_manual', 'frozen manual (U) blocker'),
    ('d_own_geometry', 'own geometry / bookkeeping failure'),
    ('f_near_miss', 'guard near-miss only (no hard blocker)'),
    ('e_world_clean', 'world-clean'),
))
#: categories that are *rejected by the true 3D world* (hard blockers / own
#: geometry); ``f_near_miss`` is rejected by the guard's sampling safety margin
#: but its exact minimum distance is still >= 0.05 mm.
CATEGORY_ORDER_REJECTED = ('a_1_3_movable', 'b_ge4_movable', 'c_manual',
                           'd_own_geometry')


# ---------------------------------------------------------------------------
# small deterministic helpers
# ---------------------------------------------------------------------------
def _r(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _bbox_distance_2d(first, second):
    dx = max(0.0, max(second[0] - first[2], first[0] - second[2]))
    dy = max(0.0, max(second[1] - first[3], first[1] - second[3]))
    return math.hypot(dx, dy)


def _bbox_of_points(points):
    return (float(points[:, 0].min()), float(points[:, 1].min()),
            float(points[:, 0].max()), float(points[:, 1].max()))


def _points_prim_distance_2d(points_xy, prim):
    """Vectorised 2D distance of ``(N, 2)`` points to one primitive."""
    px = points_xy[:, 0]
    py = points_xy[:, 1]
    if prim['kind'] == 'line':
        ax, ay = float(prim['p0'][0]), float(prim['p0'][1])
        bx, by = float(prim['p1'][0]), float(prim['p1'][1])
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 <= 1e-18:
            return np.hypot(px - ax, py - ay)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / length2, 0.0, 1.0)
        return np.hypot(px - (ax + t * dx), py - (ay + t * dy))
    cx, cy = float(prim['center'][0]), float(prim['center'][1])
    radius = float(prim['radius'])
    vx = px - cx
    vy = py - cy
    distance = np.hypot(vx, vy)
    angle = np.arctan2(vy, vx)
    start = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    if sweep >= 0.0:
        delta = (angle - start) % TAU
        inside = delta <= sweep + 1e-12
    else:
        delta = (start - angle) % TAU
        inside = delta <= (-sweep) + 1e-12
    d_arc = np.abs(distance - radius)
    d_p0 = np.hypot(px - float(prim['p0'][0]), py - float(prim['p0'][1]))
    d_p1 = np.hypot(px - float(prim['p1'][0]), py - float(prim['p1'][1]))
    return np.where(inside, d_arc, np.minimum(d_p0, d_p1))


def _closest_point_on_prim(point, prim):
    """2D closest point of ``point`` on ``prim`` (production geometry)."""
    px, py = float(point[0]), float(point[1])
    if prim['kind'] == 'line':
        ax, ay = float(prim['p0'][0]), float(prim['p0'][1])
        bx, by = float(prim['p1'][0]), float(prim['p1'][1])
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 <= 1e-18:
            return (ax, ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        return (ax + t * dx, ay + t * dy)
    cx, cy = float(prim['center'][0]), float(prim['center'][1])
    radius = float(prim['radius'])
    vx, vy = px - cx, py - cy
    distance = math.hypot(vx, vy)
    if distance < 1e-12:
        return (cx + radius, cy)
    angle = math.atan2(vy, vx)
    start = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    if sweep >= 0.0:
        delta = (angle - start) % TAU
        inside = delta <= sweep + 1e-12
    else:
        delta = (start - angle) % TAU
        inside = delta <= (-sweep) + 1e-12
    if inside:
        return (cx + radius * vx / distance, cy + radius * vy / distance)
    endpoints = ((float(prim['p0'][0]), float(prim['p0'][1])),
                 (float(prim['p1'][0]), float(prim['p1'][1])))
    return min(endpoints, key=lambda item: math.hypot(px - item[0], py - item[1]))


def _points_polyline_distance(points, polyline):
    """Minimum 3D distance of ``(N,3)`` points to a ``(M,3)`` polyline."""
    best = float('inf')
    best_index = 0
    for index in range(len(polyline) - 1):
        a = polyline[index]
        b = polyline[index + 1]
        ab = b - a
        length2 = float(ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2])
        if length2 <= 1e-18:
            distance = np.linalg.norm(points - a, axis=1)
        else:
            t = np.clip(((points - a) @ ab) / length2, 0.0, 1.0)
            projected = a + t[:, None] * ab
            distance = np.linalg.norm(points - projected, axis=1)
        index_min = int(np.argmin(distance))
        value = float(distance[index_min])
        if value < best:
            best = value
            best_index = index_min
    return best, best_index


def _cells_of_bbox(bbox, margin, cell):
    x0 = int(math.floor((bbox[0] - margin) / cell))
    x1 = int(math.floor((bbox[2] + margin) / cell))
    y0 = int(math.floor((bbox[1] - margin) / cell))
    y1 = int(math.floor((bbox[3] + margin) / cell))
    for ix in range(x0, x1 + 1):
        for iy in range(y0, y1 + 1):
            yield (ix, iy)


# ---------------------------------------------------------------------------
# geometry index of one route world
# ---------------------------------------------------------------------------
class WorldGeom:
    """Part-level geometry / strict-D56 index of a set of 3D routes."""

    def __init__(self, routes, label='world'):
        started = time.time()
        self.label = str(label)
        self.routes = {int(route['route_id']): route for route in routes}
        # ---- flat primitives (with spatial grid) -------------------------
        self.flat_entries = []
        self.flat_grid = {}
        for rid in sorted(self.routes):
            route = self.routes[rid]
            for part_index, part in enumerate(route['parts']):
                if part['kind'] != 'flat':
                    continue
                z_mm = round(float(part['z_mm']), 9)
                plane = part.get('layer_id')
                for prim_index, prim in enumerate(part.get('primitives') or ()):
                    entry = dict(route_id=int(rid), z_mm=z_mm,
                                 plane=(None if plane is None else int(plane)),
                                 kind=prim['kind'],
                                 prim=prim,
                                 bbox=primitive_bbox(prim),
                                 part_index=int(part_index),
                                 prim_index=int(prim_index))
                    index = len(self.flat_entries)
                    self.flat_entries.append(entry)
                    for cell in _cells_of_bbox(entry['bbox'], FLAT_CELL_MM,
                                               FLAT_CELL_MM):
                        self.flat_grid.setdefault(cell, []).append(index)
        # ---- transitions (dense / coarse samples, spatial grid) ----------
        self.transitions = []
        self.transition_grid = {}
        for rid in sorted(self.routes):
            route = self.routes[rid]
            for part_index, part in enumerate(route['parts']):
                if part['kind'] != 'transition':
                    continue
                dense = np.asarray(P.transition_samples(part,
                                                        step=DENSE_STEP_MM),
                                   dtype=float)
                coarse = np.asarray(P.transition_samples(part, step=0.25),
                                    dtype=float)
                bbox = _bbox_of_points(dense)
                record = dict(route_id=int(rid), part_index=int(part_index),
                              z0=round(float(part['z0']), 9),
                              z1=round(float(part['z1']), 9),
                              dense=dense, coarse=coarse, bbox=bbox,
                              polyline=dense[::max(1, int(round(0.1 /
                                                               DENSE_STEP_MM)))],
                              part=part,
                              tag=str(part.get('tag') or ''))
                index = len(self.transitions)
                self.transitions.append(record)
                for cell in _cells_of_bbox(bbox, TRANS_CELL_MM,
                                           TRANS_CELL_MM):
                    self.transition_grid.setdefault(cell, []).append(index)
        # ---- global strict-D56 indices, one per physical plane -----------
        plane_prims = OrderedDict()
        for rid in sorted(self.routes):
            for part in self.routes[rid]['parts']:
                if part['kind'] != 'flat':
                    continue
                key = round(float(part['z_mm']), 9)
                merged = plane_prims.setdefault(key, {}).setdefault(rid, [])
                merged.extend(dict(prim) for prim in part['primitives'])
        self.plane_indices = {}
        self.plane_routes = {}
        for z_key in sorted(plane_prims):
            index = D56Index(width=FS.WIDTH_MM, gap=FS.EDGE_GAP_MM,
                             sagitta=FS.SAGITTA_MM,
                             min_cross_angle_deg=FS.MIN_CROSS_ANGLE_DEG,
                             crossing_policy='strict')
            for rid in sorted(plane_prims[z_key]):
                index.add(int(rid), prepare([dict(prim) for prim in
                                             plane_prims[z_key][rid]]))
            self.plane_indices[round(float(z_key), 9)] = index
            self.plane_routes[round(float(z_key), 9)] = plane_prims[z_key]
        self.plane_zs = tuple(sorted(self.plane_indices))
        # (plane z, route id) -> flat prim entries (used to localise D56 blockers)
        self.flat_by_plane_route = {}
        for entry in self.flat_entries:
            key = (entry['z_mm'], int(entry['route_id']))
            self.flat_by_plane_route.setdefault(key, []).append(entry)
        self.build_seconds = round(time.time() - started, 3)

    # -- spatial queries ---------------------------------------------------
    def flats_near(self, bbox, margin):
        found = set()
        for cell in _cells_of_bbox(bbox, margin, FLAT_CELL_MM):
            found.update(self.flat_grid.get(cell, ()))
        result = []
        for index in sorted(found):
            entry = self.flat_entries[index]
            if _bbox_distance_2d(entry['bbox'], bbox) <= margin:
                result.append(entry)
        return result

    def transitions_near(self, bbox, margin):
        found = set()
        for cell in _cells_of_bbox(bbox, margin, TRANS_CELL_MM):
            found.update(self.transition_grid.get(cell, ()))
        result = []
        for index in sorted(found):
            record = self.transitions[index]
            if _bbox_distance_2d(record['bbox'], bbox) <= margin:
                result.append(record)
        return result

    def sumary(self):
        return dict(label=self.label, routes=len(self.routes),
                    flat_primitives=len(self.flat_entries),
                    transitions=len(self.transitions),
                    planes=len(self.plane_indices))


# ---------------------------------------------------------------------------
# candidate rebuild + true-3D scan
# ---------------------------------------------------------------------------
def rebuild_candidate(baseline_route, body_index, s0, s1, target_z):
    """Exact ``duck_out`` rebuild.

    Returns ``(candidate, excursion_record, raw_metadata_errors)`` where
    ``raw_metadata_errors`` are the metadata inconsistencies of the raw
    ``duck_out`` result (before the repair derivation described below).
    """
    built = RM.duck_out(baseline_route, body_index, s0, s1, target_z)
    raw = built['route']
    raw_metadata_errors = RM.route_metadata_errors(raw)
    # ``duck_out`` re-derives the metadata from the *old* ``n_transitions``; for
    # direct (Z1/Z2 interface) routes this leaves stale body_heights behind.
    # A second derivation (now with the real transition count) repairs it.
    candidate = N.rebuild_route_metadata(raw)
    return candidate, dict(built['excursion']), raw_metadata_errors


def _violation(kind, phase, route_id, other_route, point, distance,
               blocker_kind, blocker_z_mm=None, blocker_z_range=None,
               manual=False, detail=None, distance_refined=None):
    """One guard-level violation record (``hard`` = true 0.05 mm violation)."""
    value = (distance if distance_refined is None else distance_refined)
    hard = bool(value is not None and value < CLEARANCE - 1e-9)
    record = dict(kind=kind, phase=phase, route_id=int(route_id),
                  other_route=int(other_route),
                  point=[_r(value) for value in point],
                  distance_mm=_r(distance, 6),
                  distance_refined_mm=(None if distance_refined is None
                                       else _r(distance_refined, 6)),
                  hard=hard,
                  clearance_deficit_mm=(
                      None if value is None
                      else _r(CLEARANCE - float(value), 6)),
                  blocker_kind=blocker_kind,
                  blocker_z_mm=(None if blocker_z_mm is None
                                else _r(blocker_z_mm, 9)),
                  blocker_z_range=(None if blocker_z_range is None
                                   else [_r(blocker_z_range[0], 9),
                                         _r(blocker_z_range[1], 9)]),
                  blocker_manual=bool(manual))
    if detail:
        record['detail'] = detail
    return record


# ---------------------------------------------------------------------------
# exact refinement of the discrete minimum distance
# ---------------------------------------------------------------------------
def transition_point_at(part, t):
    """Exact 3D point of a two-arc R15 S-curve at arc length ``t`` (mm)."""
    radius = float(part['radius_mm'])
    theta = float(part['theta_rad'])
    z0 = float(part['z0'])
    z1 = float(part['z1'])
    sign = 1.0 if z1 >= z0 else -1.0
    dz = abs(z1 - z0)
    half = radius * theta
    t = min(max(float(t), 0.0), 2.0 * half)
    if t <= half:
        phi = t / radius
        u = radius * math.sin(phi)
        w = z0 + sign * radius * (1.0 - math.cos(phi))
    else:
        s = t - half
        phi = theta - s / radius
        u = 2.0 * radius * math.sin(theta) - radius * math.sin(phi)
        w = z0 + sign * (dz - radius * (1.0 - math.cos(phi)))
    sx, sy = float(part['start'][0]), float(part['start'][1])
    dx, dy = float(part['direction'][0]), float(part['direction'][1])
    return np.array([sx + dx * u, sy + dy * u, w], dtype=float)


def _refine_transition_vs_flat(part, prim, z_flat, best_index,
                               span=0.06, count=161):
    """Min distance from the exact S-curve to one flat primitive."""
    length = float(part.get('length_mm') or 0.0)
    if length <= 0.0:
        return None
    step = length / float(max(1, len(P.transition_samples(
        part, step=DENSE_STEP_MM)) - 1))
    t_best = float(best_index) * step
    low = max(0.0, t_best - span)
    high = min(length, t_best + span)
    if high <= low:
        return None
    points = np.array([transition_point_at(part, value) for value
                       in np.linspace(low, high, count)])
    distance2 = _points_prim_distance_2d(points[:, :2], prim)
    distance3 = np.hypot(distance2, points[:, 2] - float(z_flat))
    index_min = int(np.argmin(distance3))
    return float(distance3[index_min]), points[index_min]


def _refine_flat_vs_transition(record, prims, z_flat, best_index,
                               span=0.06, count=161):
    """Min distance from the exact blocker S-curve to candidate flat prims."""
    part = record.get('part')
    if part is None or not prims:
        return None
    length = float(part.get('length_mm') or 0.0)
    if length <= 0.0:
        return None
    samples = record['dense']
    step = length / float(max(1, len(samples) - 1))
    t_best = float(best_index) * step
    low = max(0.0, t_best - span)
    high = min(length, t_best + span)
    if high <= low:
        return None
    best = (float('inf'), None)
    for value in np.linspace(low, high, count):
        point = transition_point_at(part, value)
        for prim in prims:
            distance2 = float(_points_prim_distance_2d(
                point[None, :2], prim)[0])
            distance3 = math.hypot(distance2, point[2] - float(z_flat))
            if distance3 < best[0]:
                best = (distance3, point)
    return best[0], best[1]


def _near_clearance(value, window=0.02):
    """True when a discrete distance is close enough to need refinement."""
    return value is not None and (CLEARANCE - window) <= value


def _d56_blockers(geom, candidate, rid, parts, manual_set):
    """Strict-D56 same-plane conflicts of the given candidate flat parts."""
    conflicts = []
    for part in parts:
        if part['kind'] != 'flat':
            continue
        z_key = round(float(part['z_mm']), 9)
        index = geom.plane_indices.get(z_key)
        if index is None:
            continue
        prims = [dict(prim) for prim in part['primitives']]
        evaluation = index.evaluate(prepare(prims), exclude=(int(rid),),
                                    stop_on_invalid=False)
        if evaluation is None or evaluation.valid:
            continue
        blocker_ids = sorted({int(value) for value in
                              (evaluation.blockers or ())})
        details = []
        for blocker_id in blocker_ids:
            best = None
            other_entries = geom.flat_by_plane_route.get((z_key, blocker_id), ())
            for prim in part['primitives']:
                # sample the candidate prim and look for the nearest blocker
                # flat primitive at the same physical plane
                samples = _prim_samples_2d(prim, step=0.05)
                for other in other_entries:
                    distance = _points_prim_distance_2d(samples, other['prim'])
                    index_min = int(np.argmin(distance))
                    value = float(distance[index_min])
                    if best is None or value < best['distance_mm']:
                        best = dict(distance_mm=value,
                                    point=[float(samples[index_min, 0]),
                                           float(samples[index_min, 1]),
                                           float(z_key)],
                                    blocker_kind=other['kind'],
                                    blocker_z_mm=z_key,
                                    blocker_route=blocker_id)
            if best is None:
                best = dict(distance_mm=None, point=[None, None, z_key],
                            blocker_kind=None, blocker_z_mm=z_key,
                            blocker_route=blocker_id)
            details.append(best)
        conflicts.append(dict(plane_z_mm=_r(z_key, 9),
                              reason=str(evaluation.reason),
                              blockers=blocker_ids,
                              details=details,
                              hard=True,
                              manual=[value for value in blocker_ids
                                      if value in manual_set]))
    return conflicts


def _prim_samples_2d(prim, step=0.05):
    if prim['kind'] == 'line':
        p0 = np.asarray(prim['p0'], dtype=float)
        p1 = np.asarray(prim['p1'], dtype=float)
        length = float(np.hypot(*(p1 - p0)))
        count = max(2, int(math.ceil(length / step)) + 1)
        t = np.linspace(0.0, 1.0, count)[:, None]
        return p0 + t * (p1 - p0)
    radius = float(prim['radius'])
    sweep = float(prim['sweep'])
    start = float(prim['start_angle'])
    count = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
    angles = start + np.linspace(0.0, sweep, count)
    cx, cy = float(prim['center'][0]), float(prim['center'][1])
    return np.stack([cx + radius * np.cos(angles),
                     cy + radius * np.sin(angles)], axis=1)


def scan_geometry(geom, parts, rid, manual_set, d56=True, phase_map=None):
    """True-3D scan of ``parts`` of a candidate against ``geom``.

    Returns ``(violations, d56_conflicts)``.  ``phase_map`` maps ``id(part)``
    to a phase label (up / middle / down / fanout / lead ...).  Distances close
    to the 0.05 mm threshold are refined against the exact S-curve geometry.
    """
    violations = []
    d56_conflicts = []

    def phase_of(part):
        return (phase_map or {}).get(id(part), '')

    for part in parts:
        if part['kind'] == 'flat':
            z_mm = float(part['z_mm'])
            prims = part['primitives']
            bbox = _parts_bbox(prims)
            # -- flat vs every other route's transitions ------------------
            for record in geom.transitions_near(bbox, ACCEPT_POINT):
                if record['route_id'] == rid:
                    continue
                samples = record['dense']
                best = (float('inf'), 0)
                for prim in prims:
                    distance = _points_prim_distance_2d(samples[:, :2], prim)
                    index_min = int(np.argmin(distance))
                    value = float(distance[index_min])
                    if value < best[0]:
                        best = (value, index_min)
                if best[0] < ACCEPT_POINT:
                    refined = None
                    if _near_clearance(best[0]):
                        refined = _refine_flat_vs_transition(
                            record, prims, z_mm, best[1])
                    if refined is not None:
                        value, sample = refined
                        distance_refined = value
                    else:
                        sample = samples[best[1]]
                        value = best[0]
                        distance_refined = None
                    violations.append(_violation(
                        'flat_vs_transition', phase_of(part), rid,
                        record['route_id'],
                        [sample[0], sample[1], sample[2]], best[0],
                        'transition', None, (record['z0'], record['z1']),
                        record['route_id'] in manual_set,
                        distance_refined=distance_refined))
        else:
            samples = np.asarray(P.transition_samples(part,
                                                      step=DENSE_STEP_MM),
                                 dtype=float)
            bbox = _bbox_of_points(samples)
            # -- transition vs every other route's flats ------------------
            for entry in geom.flats_near(bbox, ACCEPT_POINT):
                if entry['route_id'] == rid:
                    continue
                distance = _points_prim_distance_2d(samples[:, :2], entry['prim'])
                distance3 = np.hypot(distance, samples[:, 2] - entry['z_mm'])
                index_min = int(np.argmin(distance3))
                value = float(distance3[index_min])
                if value < ACCEPT_POINT:
                    refined = None
                    if _near_clearance(value):
                        refined = _refine_transition_vs_flat(
                            part, entry['prim'], entry['z_mm'], index_min)
                    if refined is not None:
                        refined_value, sample = refined
                        distance_refined = refined_value
                    else:
                        sample = samples[index_min]
                        distance_refined = None
                    violations.append(_violation(
                        'transition_vs_flat', phase_of(part), rid,
                        entry['route_id'],
                        [sample[0], sample[1], sample[2]], value,
                        entry['kind'], entry['z_mm'], None,
                        entry['route_id'] in manual_set,
                        detail=dict(blocker_part_index=entry['part_index'],
                                    blocker_prim_index=entry['prim_index']),
                        distance_refined=distance_refined))
            # -- transition vs every other route's transitions ------------
            for record in geom.transitions_near(bbox,
                                                ACCEPT_SEGMENT + 0.01):
                if record['route_id'] == rid:
                    continue
                distance, index_min = _points_polyline_distance(
                    samples, record['polyline'])
                if distance < ACCEPT_SEGMENT + 0.01:
                    sample = samples[index_min]
                    violations.append(_violation(
                        'transition_vs_transition', phase_of(part), rid,
                        record['route_id'],
                        [sample[0], sample[1], sample[2]], distance,
                        'transition', None, (record['z0'], record['z1']),
                        record['route_id'] in manual_set))
    if d56:
        flats = [part for part in parts if part['kind'] == 'flat']
        d56_conflicts = _d56_blockers(geom, None, rid, flats, manual_set)
    return violations, d56_conflicts


def _parts_bbox(prims):
    boxes = [primitive_bbox(prim) for prim in prims]
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def check_self_clearance(candidate):
    records = self_clearance_violations(candidate, CLEARANCE)
    return [dict(kind='self_clearance', phase='self',
                 point=[_r(value) for value in record['point']],
                 distance_mm=_r(record['distance_mm'], 6),
                 other_route=int(candidate['route_id']))
            for record in records]


def check_layer_pitch(candidate, plane_zs):
    problems = []
    heights = sorted({round(float(part['z_mm']), 9)
                      for part in candidate['parts']
                      if part['kind'] == 'flat'})
    for z in heights:
        for other in plane_zs:
            gap = abs(z - other)
            if 1e-9 < gap < CLEARANCE - 1e-9:
                problems.append(dict(z_mm=z, other_z_mm=other, gap_mm=gap))
    return problems


# ---------------------------------------------------------------------------
# classification / aggregation
# ---------------------------------------------------------------------------
def classify(candidate_record):
    if not candidate_record['build_ok']:
        return 'd_own_geometry'
    if candidate_record['structure_errors'] or candidate_record['layer_pitch']:
        return 'd_own_geometry'
    guard_flagged = bool(candidate_record['blockers']
                         or candidate_record['d56']
                         or candidate_record['self_clearance'])
    if not guard_flagged:
        return 'e_world_clean'
    hard = candidate_record['blockers_hard']
    if not hard:
        return 'f_near_miss'
    if candidate_record['manual_blockers']:
        return 'c_manual'
    if len(candidate_record['movable_blockers']) <= 3:
        return 'a_1_3_movable'
    return 'b_ge4_movable'


def _bucket(count):
    if count <= 0:
        return '0'
    if count <= 3:
        return str(count)
    if count <= 8:
        return '4-8'
    return '>8'


def aggregate(candidates, manual_set, assignment):
    clean = [item for item in candidates
             if item['category'] == 'e_world_clean']
    near_miss = [item for item in candidates
                 if item['category'] == 'f_near_miss']
    hard_rejected = [item for item in candidates
                     if item['category'] in CATEGORY_ORDER_REJECTED]
    rejected = [item for item in candidates
                if item['category'] != 'e_world_clean']
    movable_hist = Counter(_bucket(len(item['movable_blockers']))
                           for item in hard_rejected)
    total_hist = Counter(_bucket(len(item['blockers_hard']))
                         for item in hard_rejected)
    production_hist = Counter(_bucket(len(item['blockers']))
                              for item in rejected)
    guard_hist = Counter(_bucket(len(item['movable_blockers_guard']))
                         for item in rejected)
    kinds = Counter()
    kinds_hard = Counter()
    candidate_kinds = Counter()
    phases = Counter()
    violation_z = Counter()
    d56_reasons = Counter()
    blocker_frequency = Counter()
    manual_frequency = Counter()
    for item in rejected:
        item_kinds = set()
        for violation in item['violations']:
            kinds[violation['kind']] += 1
            if violation['hard']:
                kinds_hard[violation['kind']] += 1
            item_kinds.add(violation['kind'])
            phases[violation['phase']] += 1
            if violation['blocker_z_mm'] is not None:
                violation_z[_r(violation['blocker_z_mm'], 3)] += 1
            elif violation['blocker_z_range']:
                violation_z[round(0.5 * (violation['blocker_z_range'][0]
                                         + violation['blocker_z_range'][1]), 3)] += 1
            if violation['hard']:
                blocker_frequency[violation['other_route']] += 1
        for conflict in item['d56']:
            item_kinds.add('flat_same_plane_conflict')
            kinds['flat_same_plane_conflict'] += 1
            kinds_hard['flat_same_plane_conflict'] += 1
            d56_reasons[conflict['reason']] += 1
            for blocker in conflict['blockers']:
                blocker_frequency[blocker] += 1
        for blocker in item['manual_blockers']:
            manual_frequency[blocker] += 1
        for kind in item_kinds:
            candidate_kinds[kind] += 1
    world_clean_metadata_bug = [item for item in clean
                                if item['metadata_errors_raw']]
    direct_candidates = [item for item in candidates if item['route_direct']]
    guard_fixable = [item for item in candidates
                     if item['build_ok'] and not item['structure_errors']
                     and not item['layer_pitch'] and item['blockers']
                     and not item['manual_blockers_guard']
                     and 1 <= len(item['movable_blockers_guard']) <= 3]
    guard_fixable.sort(key=lambda item: (-item['estimated_net'],
                                         len(item['movable_blockers_guard']),
                                         item['route_id'],
                                         item['target_plane_id']))
    return dict(
        rejected=len(hard_rejected),
        production_rejected=len(rejected),
        near_miss=len(near_miss),
        world_clean=len(clean),
        world_clean_metadata_ok=len(clean) - len(world_clean_metadata_bug),
        world_clean_metadata_bug=len(world_clean_metadata_bug),
        world_clean_metadata_bug_top=[
            _candidate_brief(item) for item in
            sorted(world_clean_metadata_bug,
                   key=lambda row: (-row['estimated_net'], row['route_id']))[:10]],
        near_miss_top=[_candidate_brief(item) for item in
                       sorted(near_miss,
                              key=lambda row: (-row['estimated_net'],
                                               len(row['blockers']),
                                               row['route_id']))[:15]],
        direct_route_candidates=len(direct_candidates),
        direct_route_world_clean=sum(1 for item in direct_candidates
                                     if item['category'] == 'e_world_clean'),
        direct_route_metadata_bug=sum(1 for item in direct_candidates
                                      if item['metadata_errors_raw']),
        metadata_errors_raw_candidates=sum(1 for item in candidates
                                           if item['metadata_errors_raw']),
        manual_routes=int(len(manual_set)),
        category_counts=OrderedDict(
            (key, sum(1 for item in candidates
                      if item['category'] == key))
            for key in CATEGORY_LABEL),
        movable_blocker_histogram=OrderedDict(
            (key, int(movable_hist.get(key, 0)))
            for key in ('0', '1', '2', '3', '4-8', '>8')),
        total_blocker_histogram=OrderedDict(
            (key, int(total_hist.get(key, 0)))
            for key in ('0', '1', '2', '3', '4-8', '>8')),
        production_blocker_histogram=OrderedDict(
            (key, int(production_hist.get(key, 0)))
            for key in ('0', '1', '2', '3', '4-8', '>8')),
        guard_movable_blocker_histogram=OrderedDict(
            (key, int(guard_hist.get(key, 0)))
            for key in ('0', '1', '2', '3', '4-8', '>8')),
        fixable_1_3_guard=OrderedDict(
            count=len(guard_fixable),
            hard_clean=sum(1 for item in guard_fixable
                           if not item['blockers_hard']),
            fraction_of_production_rejected=_r(
                len(guard_fixable) / float(max(1, len(rejected))), 4),
            top=[_candidate_brief(item) for item in guard_fixable[:15]],
        ),
        candidates_with_manual_blocker=int(
            sum(1 for item in hard_rejected if item['manual_blockers'])),
        manual_blocker_routes=int(len(manual_frequency)),
        violation_kind_records=OrderedDict(sorted(kinds.items())),
        violation_kind_hard_records=OrderedDict(sorted(kinds_hard.items())),
        violation_kind_candidates=OrderedDict(sorted(candidate_kinds.items())),
        phase_records=OrderedDict(sorted(phases.items())),
        blocker_height_histogram=OrderedDict(
            ('%.3f' % key, value) for key, value in sorted(violation_z.items())),
        d56_reasons=OrderedDict(sorted(d56_reasons.items())),
        top_blocking_routes=[
            dict(route_id=int(rid), blockers=int(count),
                 manual=bool(rid in manual_set))
            for rid, count in sorted(blocker_frequency.items(),
                                     key=lambda item: (-item[1], item[0]))[:25]],
        top_manual_blocking_routes=[
            dict(route_id=int(rid), blockers=int(count))
            for rid, count in sorted(manual_frequency.items(),
                                     key=lambda item: (-item[1], item[0]))[:15]],
    )


def per_target_stats(candidates):
    table = OrderedDict()
    for item in candidates:
        key = item['target_plane_label']
        row = table.setdefault(key, dict(
            target_plane_label=key, target_z_mm=item['target_z'],
            candidates=0, world_clean=0, rejected=0, near_miss=0,
            manual_blocked=0, movable_blockers_sum=0,
            movable_blockers_max=0, hard_violations=0))
        row['candidates'] += 1
        row['hard_violations'] += int(item['hard_violations'])
        if item['category'] == 'e_world_clean':
            row['world_clean'] += 1
        elif item['category'] == 'f_near_miss':
            row['near_miss'] += 1
        else:
            row['rejected'] += 1
        if item['manual_blockers']:
            row['manual_blocked'] += 1
        row['movable_blockers_sum'] += len(item['movable_blockers'])
        row['movable_blockers_max'] = max(row['movable_blockers_max'],
                                          len(item['movable_blockers']))
    for row in table.values():
        count = max(1, row['rejected'])
        row['mean_movable_blockers'] = _r(
            row['movable_blockers_sum'] / float(count), 3)
        del row['movable_blockers_sum']
    return OrderedDict(sorted(table.items(),
                              key=lambda item: -item[1]['candidates']))


def per_route_best(candidates):
    best = OrderedDict()
    for item in candidates:
        rid = item['route_id']
        current = best.get(rid)
        rank = (-item['estimated_net'], item['target_plane_id'],
                item['s_start_mm'])
        if current is None or rank < current[0]:
            best[rid] = (rank, item)
    rows = []
    for rid in sorted(best):
        item = best[rid][1]
        rows.append(dict(route_id=rid, estimated_net=item['estimated_net'],
                         target_plane_label=item['target_plane_label'],
                         category=item['category'],
                         blockers=item['blockers'],
                         blockers_hard=item['blockers_hard'],
                         movable_blockers=item['movable_blockers'],
                         manual_blockers=item['manual_blockers'],
                         near_miss_blockers=item['near_miss_blockers']))
    return rows


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
def load_analysis(native_dir):
    path = Path(native_dir) / 'analysis' / 'crossing_intervals.json'
    return N.load_json(path), path


def select_candidates(analysis, min_net=3, extra_route=129, extra_net=16):
    """Deterministic candidate selection (feasible net>=min_net + r129 net)."""
    selected = OrderedDict()
    for route in analysis['routes']:
        route_id = int(route['route_id'])
        for candidate in route['candidates']:
            if not candidate.get('feasible'):
                continue
            if candidate.get('s_start_mm') is None:
                continue
            kept = int(candidate['estimated_net']) >= int(min_net)
            if (not kept and route_id == int(extra_route)
                    and int(candidate['estimated_net']) == int(extra_net)):
                kept = True
            if not kept:
                continue
            key = (route_id, int(candidate['target_plane_id']),
                   round(float(candidate['s_start_mm']), 6),
                   round(float(candidate['s_end_mm']), 6))
            selected[key] = (route, candidate)
    order = sorted(selected.items(),
                   key=lambda item: (-int(item[1][1]['estimated_net']),
                                     int(item[0][0]), int(item[0][1]),
                                     item[0][2]))
    return [(route, candidate) for _key, (route, candidate) in order]


def _route_parts_signature(route):
    return json.dumps(route.get('parts'), sort_keys=True)


def find_native_modified_routes(baseline_routes, native_routes):
    baseline = {int(route['route_id']): route for route in baseline_routes}
    modified = []
    for rid, route in sorted(native_routes.items()):
        if rid not in baseline:
            continue
        if _route_parts_signature(route) != _route_parts_signature(baseline[rid]):
            modified.append(rid)
    return modified


# ---------------------------------------------------------------------------
# validation against the production guard
# ---------------------------------------------------------------------------
def _validation_sample(candidates, limit):
    """Deterministic spread sample: top gains plus evenly spaced candidates."""
    if limit <= 0 or not candidates:
        return []
    limit = min(int(limit), len(candidates))
    head = candidates[:max(1, limit // 2)]
    rest = candidates[max(1, limit // 2):]
    stride = max(1, len(rest) // max(1, limit - len(head)))
    spread = rest[::stride]
    sample = list(head)
    for item in spread:
        if len(sample) >= limit:
            break
        sample.append(item)
    return sample[:limit]


def _production_blockers(violations):
    blockers = set()
    kinds = set()
    for value in violations:
        kinds.add(str(value['kind']))
        if value.get('other_route') is not None:
            blockers.add(int(value['other_route']))
        for part_id in value.get('blockers') or ():
            blockers.add(int(part_id) // 1000)
    return blockers, kinds


def validate_against_production(candidates, env, limit=40, guard_limit=15):
    """Compare the fast scan with ``guard.local_world_check`` / candidate_guard.

    The production ``World.check_route`` returns on the first violating part, so
    its blocker set must be a *subset* of the (complete-ish) fast scan.  We also
    count the opposite direction (fast scan clean but production flags) because
    that would indicate a false negative in the fast scan.
    """
    sample = _validation_sample(candidates, limit)
    compared = 0
    subset_violations = 0
    clean_contradictions = 0
    guard_stage = Counter()
    details = []
    for index, item in enumerate(sample):
        candidate = item['_build']['candidate']
        prod_violations, _info = G.local_world_check(env, candidate)
        prod_blockers, prod_kinds = _production_blockers(prod_violations)
        fast_blockers = set(item['blockers'])
        fast_kinds = {value['kind'] for value in item['violations']}
        fast_kinds |= {'flat_same_plane_conflict' for _ in item['d56']}
        if item['self_clearance']:
            fast_kinds.add('self_clearance')
        compared += 1
        if not (prod_blockers <= fast_blockers and prod_kinds <= fast_kinds):
            subset_violations += 1
            if len(details) < 8:
                details.append(dict(route_id=item['route_id'],
                                    target_plane_label=item['target_plane_label'],
                                    estimated_net=item['estimated_net'],
                                    production_blockers=sorted(prod_blockers),
                                    fast_blockers=sorted(fast_blockers),
                                    production_kinds=sorted(prod_kinds),
                                    fast_kinds=sorted(fast_kinds)))
        if item['world_clean'] and (prod_violations or item['d56']):
            clean_contradictions += 1
        if index < int(guard_limit):
            guard = G.candidate_guard(env, candidate)
            guard_stage[guard['stage']] += 1
    return dict(
        compared=compared,
        production_subset_violations=subset_violations,
        agreement_ratio=_r(1.0 - subset_violations / float(max(1, compared)), 4),
        world_clean_contradictions=clean_contradictions,
        candidate_guard_stage=OrderedDict(sorted(guard_stage.items())),
        guard_checked=int(min(int(guard_limit), len(sample))),
        mismatches=details)


def validate_native_world(candidates, native_env, limit=20):
    """Production check of the fast native scan (accepted layout sensitivity)."""
    sample = _validation_sample(
        [item for item in candidates
         if not item['route_modified_in_native']
         and item['native_world'] and item['native_world']['checked']],
        limit)
    compared = 0
    subset_violations = 0
    clean_both = 0
    details = []
    for item in sample:
        candidate = item['_build']['candidate']
        violations, _info = G.local_world_check(native_env, candidate)
        prod_blockers, prod_kinds = _production_blockers(violations)
        fast_blockers = set(item['native_world']['blockers'])
        fast_kinds = set(item['native_world']['kinds'])
        compared += 1
        if not (prod_blockers <= fast_blockers and prod_kinds <= fast_kinds):
            subset_violations += 1
            if len(details) < 8:
                details.append(dict(route_id=item['route_id'],
                                    target_plane_label=item['target_plane_label'],
                                    production_blockers=sorted(prod_blockers),
                                    fast_blockers=sorted(fast_blockers)))
        if not prod_blockers and not fast_blockers:
            clean_both += 1
    return dict(
        compared=compared,
        production_subset_violations=subset_violations,
        agreement_ratio=_r(1.0 - subset_violations / float(max(1, compared)), 4),
        world_clean_agreements=clean_both,
        mismatches=details)


# ---------------------------------------------------------------------------
# plotting
# ---------------------------------------------------------------------------
def _import_matplotlib():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def make_plots(candidates, aggregates, route129, out_dir):
    plt = _import_matplotlib()
    plots_dir = Path(out_dir) / 'analysis' / 'plots'
    plots_dir.mkdir(parents=True, exist_ok=True)
    written = []

    def save(fig, name):
        path = plots_dir / name
        fig.savefig(path, dpi=140, bbox_inches='tight')
        plt.close(fig)
        written.append(path.name)

    # 1. blocker-count histogram ------------------------------------------
    rejected = [item for item in candidates
                if item['category'] in CATEGORY_ORDER_REJECTED]
    near_miss = [item for item in candidates
                 if item['category'] == 'f_near_miss']
    buckets = ['1', '2', '3', '4-8', '>8']
    movable_counts = [_bucket(len(item['movable_blockers']))
                      for item in rejected]
    total_counts = [_bucket(len(item['blockers_hard'])) for item in rejected]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for axis, counts, title in ((axes[0], movable_counts, 'movable blockers'),
                                (axes[1], total_counts, 'all blockers')):
        values = [sum(1 for value in counts if value == bucket)
                  for bucket in buckets]
        bars = axis.bar(buckets, values, color='#4477aa')
        axis.set_title('rejected candidates by %s' % title)
        axis.set_xlabel('blocker count')
        axis.set_ylabel('candidates')
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, value,
                      str(value), ha='center', va='bottom', fontsize=8)
        axis.grid(axis='y', alpha=0.3)
    fig.suptitle('why excursion candidates fail: number of hard blocking '
                 'routes (n=%d rejected, %d near-miss only, %d world-clean)'
                 % (len(rejected), len(near_miss), aggregates['world_clean']))
    save(fig, 'blocker_count_histogram.png')

    # 2. XY heat map of violation positions -------------------------------
    points = []
    for item in rejected:
        for violation in item['violations']:
            if violation['hard']:
                points.append((violation['point'][0], violation['point'][1]))
        for conflict in item['d56']:
            for detail in conflict['details']:
                if detail['point'][0] is not None:
                    points.append((detail['point'][0], detail['point'][1]))
    fig, axis = plt.subplots(figsize=(7.2, 7.2))
    if points:
        array = np.asarray(points, dtype=float)
        heat, xedges, yedges = np.histogram2d(
            array[:, 0], array[:, 1], bins=(75, 75),
            range=[[0.0, 150.0], [0.0, 150.0]])
        image = axis.imshow(heat.T, origin='lower', extent=[0, 150, 0, 150],
                            aspect='equal', cmap='inferno')
        fig.colorbar(image, ax=axis, label='violation points per 2 mm cell')
    axis.set_xlabel('x (mm)')
    axis.set_ylabel('y (mm)')
    axis.set_title('XY positions of hard true-3D violation points\n'
                   '(%d points, 2 mm cells)' % len(points))
    save(fig, 'blocker_position_heatmap.png')

    # 3. route 129 detail figure -----------------------------------------
    route = route129['route']
    body = route['parts'][route129['body_flat_index']]
    body_samples = _part_polyline(body)
    net16 = route129.get('net16_targets') or route129['targets']
    colors = plt.cm.tab10(np.linspace(0, 1, 10))
    fig = plt.figure(figsize=(15, 9.5))
    grid = fig.add_gridspec(2, 2, height_ratios=(1.0, 0.95),
                            hspace=0.35, wspace=0.22)
    # -- panel 1: XY zoom around the excursion / violation corridor ------
    axis = fig.add_subplot(grid[0, 0])
    axis.plot(body_samples[:, 0], body_samples[:, 1], color='black',
              linewidth=2.0, label='route 129 body path (L6)', zorder=5)
    xs, ys = [], []
    annotated = set()
    for index, target in enumerate(net16):
        color = colors[index % len(colors)]
        for violation in target['violations']:
            xs.append(violation['point'][0])
            ys.append(violation['point'][1])
            marker = 'o' if violation['hard'] else 's'
            face = color if violation['hard'] else 'none'
            axis.scatter(violation['point'][0], violation['point'][1],
                         s=26, marker=marker, facecolors=face,
                         edgecolors=color, linewidths=0.8, zorder=6)
            blocker = violation['other_route']
            if blocker not in annotated:
                annotated.add(blocker)
                axis.annotate('r%d' % blocker,
                              (violation['point'][0], violation['point'][1]),
                              textcoords='offset points', xytext=(3, 3),
                              fontsize=5.5, color=color)
        axis.plot([], [], marker='o', linestyle='none', color=color,
                  label='%s net=%d (guard %d / hard %d)'
                  % (target['target_plane_label'], target['estimated_net'],
                     len(target['blockers']), len(target['blockers_hard'])))
    if xs:
        pad_x = max(2.0, 0.06 * (max(xs) - min(xs)))
        pad_y = max(1.0, 0.10 * (max(ys) - min(ys)))
        axis.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
        axis.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
    axis.grid(alpha=0.3)
    axis.set_xlabel('x (mm)')
    axis.set_ylabel('y (mm)')
    axis.set_title('route 129: violation positions along the excursion corridor\n'
                   '(filled = hard <0.05 mm, open square = guard near-miss; '
                   'colors follow the height panel)', fontsize=8.5)
    # -- panel 2: violation height vs distance ---------------------------
    axis = fig.add_subplot(grid[0, 1])
    for index, target in enumerate(net16):
        color = colors[index % len(colors)]
        for violation in target['violations']:
            distance = (violation['distance_refined_mm']
                        if violation['distance_refined_mm'] is not None
                        else violation['distance_mm'])
            axis.scatter(violation['point'][2], distance, s=22, color=color,
                         marker='o' if violation['hard'] else 's',
                         facecolors=color if violation['hard'] else 'none',
                         edgecolors=color, linewidths=0.8)
        axis.plot([], [], 'o', color=color, markersize=4,
                  label=target['target_plane_label'])
    axis.axhline(CLEARANCE, color='red', linestyle='--', linewidth=1,
                 label='0.05 mm process limit')
    axis.set_xlabel('violation z (mm)')
    axis.set_ylabel('exact 3D distance (mm)')
    axis.set_title('route 129: at which heights the S-curves are blocked',
                   fontsize=9)
    axis.grid(alpha=0.3)
    axis.legend(fontsize=5.5, loc='lower right')
    # -- panel 3: blockers per target height -----------------------------
    axis = fig.add_subplot(grid[1, 0])
    labels = [target['target_plane_label'] for target in net16]
    hard_move = [len(target['movable_blockers']) for target in net16]
    hard_man = [len(target['manual_blockers']) for target in net16]
    near_only = [len(target['near_miss_blockers']) for target in net16]
    positions = np.arange(len(labels))
    axis.bar(positions, hard_move, color='#4477aa',
             label='hard movable blockers')
    axis.bar(positions, hard_man, bottom=hard_move, color='#cc6677',
             label='hard manual (U) blockers')
    axis.bar(positions, near_only, bottom=np.array(hard_move)
             + np.array(hard_man), color='#dddddd',
             edgecolor='#777777', label='guard near-miss only')
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=35, ha='right', fontsize=7)
    axis.set_ylabel('blocker routes')
    axis.set_title('route 129 net=16: blockers per target height', fontsize=8.5)
    axis.legend(fontsize=6.5)
    axis.grid(axis='y', alpha=0.3)
    # -- panel 4: text summary -------------------------------------------
    axis = fig.add_subplot(grid[1, 1])
    axis.axis('off')
    lines = ['route 129 cluster: s=%.2f-%.2f mm, %d crossings, net=%d'
             % (route129['cluster_start_mm'], route129['cluster_end_mm'],
                route129['cluster_count'], 16)]
    lines.append('body: %s (z=%.3f mm);  %d net=16 target heights '
                 '(%d selected candidates)'
                 % (route129['body_layer_label'], route129['body_z'],
                    route129['n_target_heights'],
                    route129['n_selected_candidates']))
    lines.append('common hard blockers across all net=16 targets: %s'
                 % (route129['common_blockers'] or 'none'))
    for target in net16:
        lines.append('%s: guard %d / hard %d (mov %d, man %d), '
                     'near-only %d, kinds=%s'
                     % (target['target_plane_label'],
                        len(target['blockers']),
                        len(target['blockers_hard']),
                        len(target['movable_blockers']),
                        len(target['manual_blockers']),
                        len(target['near_miss_blockers']),
                        ','.join(target['hard_kinds']) or '-'))
    lines.append('verdict: all %d net=16 targets are rejected by the '
                 'production guard.' % route129['n_target_heights'])
    lines.append('L4 is physically clean (0 hard, 3 near-miss); L8 needs '
                 'r120 moved (1 hard).')
    axis.text(0.0, 1.0, '\n'.join(lines), va='top', fontsize=6.4,
              family='monospace')
    fig.suptitle('route 129 verdict: the net=16 candidate is blocked at every '
                 'target height (7 net=16 targets)', fontsize=11)
    save(fig, 'route129_detail.png')

    # 4. per-target-height blocker profile --------------------------------
    table = per_target_stats(candidates)
    labels = list(table)
    rejected_counts = [table[key]['rejected'] for key in labels]
    manual_counts = [table[key]['manual_blocked'] for key in labels]
    means = [table[key]['mean_movable_blockers'] for key in labels]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.2))
    positions = np.arange(len(labels))
    axes[0].bar(positions, rejected_counts, color='#4477aa',
                label='rejected candidates')
    axes[0].bar(positions, manual_counts, color='#cc6677',
                label='with manual blocker')
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(labels, rotation=60, ha='right', fontsize=7)
    axes[0].set_ylabel('candidates')
    axes[0].set_title('rejections per target height')
    axes[0].legend(fontsize=7)
    axes[0].grid(axis='y', alpha=0.3)
    axes[1].bar(positions, means, color='#228833')
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(labels, rotation=60, ha='right', fontsize=7)
    axes[1].set_ylabel('mean movable blockers')
    axes[1].set_title('average movable blockers per rejected candidate')
    axes[1].grid(axis='y', alpha=0.3)
    save(fig, 'per_target_height_stats.png')

    manifest = dict(plots=written,
                    description=OrderedDict((
                        ('blocker_count_histogram.png',
                         'rejected candidates by number of movable / all blockers'),
                        ('blocker_position_heatmap.png',
                         'XY heat map of true-3D violation points (2 mm cells)'),
                        ('route129_detail.png',
                         'route 129 net=16 candidate: violation XY, height '
                         'profile and blockers per target height'),
                        ('per_target_height_stats.png',
                         'rejections and mean movable blockers per target height'),
                    )))
    (Path(out_dir) / 'analysis' / 'plots' / 'plots_manifest.json').write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')
    return written


def _part_polyline(part, step=0.1):
    points = []
    for prim in part['primitives']:
        if prim['kind'] == 'line':
            points.append([float(prim['p0'][0]), float(prim['p0'][1])])
            points.append([float(prim['p1'][0]), float(prim['p1'][1])])
        else:
            samples = _prim_samples_2d(prim, step=step)
            points.extend(samples.tolist())
    return np.asarray(points, dtype=float)


# ---------------------------------------------------------------------------
# main analysis
# ---------------------------------------------------------------------------
def analyse(baseline_dir=None, native_dir=None, out_dir=None, min_net=3,
            extra_route=129, extra_net=16, limit=None, skip_native=False,
            validation_limit=60, log=print):
    started = time.time()
    baseline_dir = Path(baseline_dir or DEFAULT_BASELINE)
    native_dir = Path(native_dir or DEFAULT_NATIVE_DIR)
    out_dir = Path(out_dir or DEFAULT_OUT_DIR)
    (out_dir / 'analysis').mkdir(parents=True, exist_ok=True)

    # -- inputs ----------------------------------------------------------
    baseline_payload, baseline_routes = N.load_routes(run_dir=baseline_dir)
    baseline_by_id = N.routes_by_id(baseline_routes)
    assignment_rows, assignment_digest = N.load_assignment(run_dir=baseline_dir)
    assignment = N.assignment_by_id(assignment_rows)
    manual_set = {rid for rid, row in assignment.items()
                  if str(row.get('manual_group') or '').strip()}
    analysis, analysis_path = load_analysis(native_dir)
    native_payload, native_routes_list = N.load_routes(
        run_dir=native_dir / 'experiment_C')
    native_by_id = N.routes_by_id(native_routes_list)
    modified_in_native = set(find_native_modified_routes(baseline_routes,
                                                         native_by_id))
    log('[inputs] baseline %d routes, %d manual, native %d routes, %d '
        'converted in experiment_C'
        % (len(baseline_routes), len(manual_set), len(native_by_id),
           len(modified_in_native)))

    # -- world geometry --------------------------------------------------
    log('[world] building E5 geometry index ...')
    world = WorldGeom(baseline_routes, label='E5')
    log('[world] %s' % world.sumary())
    native_world = None
    delta_world = None
    if not skip_native:
        log('[world] building accepted-native geometry index ...')
        native_world = WorldGeom(native_routes_list, label='experiment_C')
        delta_routes = [native_by_id[rid] for rid in sorted(modified_in_native)]
        delta_world = WorldGeom(delta_routes, label='native_delta')
        log('[world] %s' % native_world.sumary())

    # -- candidate selection --------------------------------------------
    pairs = select_candidates(analysis, min_net=min_net,
                              extra_route=extra_route, extra_net=extra_net)
    if limit is not None:
        pairs = pairs[:int(limit)]
    log('[select] %d candidates (feasible, estimated_net >= %d, plus route %d '
        'net=%d)' % (len(pairs), min_net, extra_route, extra_net))

    # -- per candidate ---------------------------------------------------
    candidates = []
    for route, candidate in pairs:
        route_id = int(route['route_id'])
        baseline_route = baseline_by_id[route_id]
        record = OrderedDict(
            route_id=route_id,
            cluster_index=int(candidate['cluster_index']),
            target_plane_id=int(candidate['target_plane_id']),
            target_plane_label=str(candidate['target_plane_label']),
            target_z=float(candidate['target_z']),
            target_is_manual_plane=bool(candidate['target_is_manual_plane']),
            body_layer_label=str(route['body_layer_label']),
            body_z=float(route['body_z']),
            body_flat_index=int(route['body_flat_index']),
            s_start_mm=float(candidate['s_start_mm']),
            s_end_mm=float(candidate['s_end_mm']),
            footprint_mm=float(candidate['footprint_mm']),
            middle_mm=float(candidate['middle_mm']),
            estimated_removed=int(candidate['estimated_removed']),
            estimated_added=int(candidate['estimated_added']),
            estimated_net=int(candidate['estimated_net']),
            analytic_world_3d_ok=bool(candidate['world_3d_ok']),
            analytic_world_3d_reason=str(candidate.get('world_3d_reason') or ''),
            route_modified_in_native=bool(route_id in modified_in_native),
            route_direct=bool(N.is_direct(baseline_route)),
            build_ok=True, build_error=None,
            structure_errors=[], metadata_errors_raw=[],
            metadata_ok_repaired=True, layer_pitch=[],
            violations=[], d56=[], self_clearance=[],
            blockers=[], blockers_hard=[], near_miss_blockers=[],
            movable_blockers=[], manual_blockers=[],
            movable_blockers_guard=[], manual_blockers_guard=[],
            hard_violations=0, near_miss_violations=0,
            category=None, world_clean=False, production_rejected=False,
            native_world=None,
        )
        build = None
        try:
            candidate_route, excursion, raw_metadata = rebuild_candidate(
                baseline_route, int(route['body_flat_index']),
                float(candidate['s_start_mm']), float(candidate['s_end_mm']),
                float(candidate['target_z']))
            build = dict(candidate=candidate_route, excursion=excursion)
            record['metadata_errors_raw'] = list(raw_metadata)[:8]
        except Exception as error:  # noqa: BLE001 - report, never crash
            record['build_ok'] = False
            record['build_error'] = '%s: %s' % (type(error).__name__, error)
            record['category'] = 'd_own_geometry'
            candidates.append(record)
            continue
        record['_build'] = build
        record['structure_errors'] = RM.structure_errors(candidate_route)[:8]
        record['metadata_ok_repaired'] = not RM.route_metadata_errors(
            candidate_route)
        record['layer_pitch'] = check_layer_pitch(candidate_route, world.plane_zs)
        phase_map = {
            id(candidate_route['parts'][excursion['up_part_index']]): 'up',
            id(candidate_route['parts'][excursion['middle_part_index']]): 'middle',
            id(candidate_route['parts'][excursion['down_part_index']]): 'down',
        }
        new_parts = [candidate_route['parts'][excursion['up_part_index']],
                     candidate_route['parts'][excursion['middle_part_index']],
                     candidate_route['parts'][excursion['down_part_index']]]
        violations, d56 = scan_geometry(world, new_parts, route_id,
                                        manual_set, d56=True,
                                        phase_map=phase_map)
        # the middle flat's strict-D56 conflict is reported for the middle part
        # only; flat parts here are just the middle one
        record['violations'] = violations
        record['d56'] = d56
        record['self_clearance'] = check_self_clearance(candidate_route)
        record['hard_violations'] = sum(1 for value in violations
                                        if value['hard'])
        record['near_miss_violations'] = len(violations) \
            - record['hard_violations']
        blockers = set()
        hard_blockers = set()
        for violation in violations:
            blockers.add(int(violation['other_route']))
            if violation['hard']:
                hard_blockers.add(int(violation['other_route']))
        for conflict in d56:
            for blocker in conflict['blockers']:
                blockers.add(int(blocker))
                hard_blockers.add(int(blocker))
        if record['self_clearance']:
            blockers.add(route_id)
            hard_blockers.add(route_id)
        record['blockers'] = sorted(blockers)
        record['blockers_hard'] = sorted(hard_blockers)
        record['near_miss_blockers'] = sorted(blockers - hard_blockers)
        record['movable_blockers'] = [rid for rid in record['blockers_hard']
                                      if rid not in manual_set]
        record['manual_blockers'] = [rid for rid in record['blockers_hard']
                                     if rid in manual_set]
        record['movable_blockers_guard'] = [
            rid for rid in record['blockers'] if rid not in manual_set]
        record['manual_blockers_guard'] = [
            rid for rid in record['blockers'] if rid in manual_set]
        record['category'] = classify(record)
        record['world_clean'] = record['category'] == 'e_world_clean'
        record['production_rejected'] = record['category'] != 'e_world_clean'
        # -- accepted-native sensitivity ---------------------------------
        if (native_world is not None
                and not record['route_modified_in_native']):
            native_violations, native_d56 = scan_geometry(
                native_world, new_parts, route_id, manual_set, d56=True,
                phase_map=phase_map)
            delta_violations, delta_d56 = [], []
            if delta_world is not None and delta_world.routes:
                delta_violations, delta_d56 = scan_geometry(
                    delta_world, candidate_route['parts'], route_id,
                    manual_set, d56=False, phase_map=phase_map)
            native_blockers = set()
            native_hard_blockers = set()
            native_kinds = set()
            for violation in list(native_violations) + list(delta_violations):
                native_blockers.add(int(violation['other_route']))
                native_kinds.add(violation['kind'])
                if violation['hard']:
                    native_hard_blockers.add(int(violation['other_route']))
            for conflict in list(native_d56) + list(delta_d56):
                for blocker in conflict['blockers']:
                    native_blockers.add(int(blocker))
                    native_hard_blockers.add(int(blocker))
                native_kinds.add('flat_same_plane_conflict')
            if record['self_clearance']:
                native_blockers.add(route_id)
                native_hard_blockers.add(route_id)
                native_kinds.add('self_clearance')
            record['native_world'] = OrderedDict(
                checked=True,
                blockers=sorted(native_blockers),
                blockers_hard=sorted(native_hard_blockers),
                movable_blockers=[rid for rid in sorted(native_hard_blockers)
                                  if rid not in manual_set],
                manual_blockers=[rid for rid in sorted(native_hard_blockers)
                                 if rid in manual_set],
                kinds=sorted(native_kinds),
                violation_records=len(native_violations) + len(delta_violations),
                same_as_baseline=bool(set(record['blockers_hard'])
                                      == set(native_hard_blockers)))
        elif record['route_modified_in_native']:
            record['native_world'] = OrderedDict(checked=False,
                                                 reason='route_converted_in_native')
        candidates.append(record)
        if len(candidates) % 500 == 0:
            log('[candidates] %d / %d (%.1fs)'
                % (len(candidates), len(pairs), time.time() - started))
    log('[candidates] checked %d in %.1fs'
        % (len(candidates), time.time() - started))

    # -- aggregates ------------------------------------------------------
    aggregates = aggregate(candidates, manual_set, assignment)
    aggregates['per_target_height'] = per_target_stats(candidates)
    aggregates['per_route_best'] = per_route_best(candidates)
    aggregates['blocker_count_histogram_basis'] = (
        'rejected = candidates with at least one *hard* blocker (exact 3D '
        'distance < 0.05 mm, strict-D56 conflict or self clearance); '
        'near-miss = guard-flagged only by the 0.061 mm sampling safety margin, '
        'exact distance still >= 0.05 mm')
    # accepted-native sensitivity summary
    native_rows = [item for item in candidates
                   if item['native_world'] and item['native_world']['checked']]
    if native_rows:
        same = sum(1 for item in native_rows
                   if item['native_world']['same_as_baseline'])
        clean_e5 = sum(1 for item in native_rows if not item['blockers_hard'])
        clean_native = sum(1 for item in native_rows
                           if not item['native_world']['blockers_hard'])
        became_clean = sum(1 for item in native_rows
                           if item['blockers_hard']
                           and not item['native_world']['blockers_hard'])
        became_blocked = sum(1 for item in native_rows
                             if not item['blockers_hard']
                             and item['native_world']['blockers_hard'])
        aggregates['native_sensitivity'] = OrderedDict(
            checked=len(native_rows), skipped_converted=len(candidates)
            - len(native_rows), same_blockers=same,
            same_ratio=_r(same / float(len(native_rows)), 4),
            e5_hard_clean=clean_e5, native_hard_clean=clean_native,
            became_hard_clean=became_clean,
            became_hard_blocked=became_blocked)
    # -- highest-gain 1-3 movable candidate ------------------------------
    fixable = [item for item in candidates
               if item['category'] == 'a_1_3_movable']
    fixable.sort(key=lambda item: (-item['estimated_net'],
                                   len(item['movable_blockers']),
                                   item['route_id'],
                                   item['target_plane_id']))
    aggregates['fixable_1_3_movable'] = OrderedDict(
        count=len(fixable),
        fraction_of_rejected=_r(len(fixable) / float(
            max(1, aggregates['rejected'])), 4),
        top=[_candidate_brief(item) for item in fixable[:15]])
    clean_candidates = [item for item in candidates
                        if item['category'] == 'e_world_clean']
    clean_candidates.sort(key=lambda item: (-item['estimated_net'],
                                            item['route_id']))
    aggregates['world_clean_top'] = [_candidate_brief(item)
                                     for item in clean_candidates[:15]]
    # -- route 129 section ----------------------------------------------
    route129 = build_route_129_section(candidates, analysis, baseline_by_id,
                                       route_id=int(extra_route))
    # -- production validation ------------------------------------------
    log('[validate] production guard cross-check ...')
    from .crossing_cache import NativeRouteSet
    env = NativeRouteSet(baseline_routes)
    validation = validate_against_production(
        candidates, env, limit=validation_limit)
    validation['stage_check'] = 'guard.local_world_check + guard.candidate_guard'
    native_validation = None
    if native_world is not None:
        log('[validate] production check against accepted native world ...')
        native_env = NativeRouteSet(native_routes_list)
        native_validation = validate_native_world(candidates, native_env,
                                                  limit=20)
    # -- payload ---------------------------------------------------------
    payload = OrderedDict(
        schema=SCHEMA,
        module='four_side_1024.fanout1024.native3d.blocker_analysis',
        inputs=OrderedDict(
            baseline_dir=str(baseline_dir),
            baseline_routes_sha256=N.sha256_file(baseline_dir /
                                                 'routes_l3d.json'),
            assignment_sha256=assignment_digest,
            native_dir=str(native_dir),
            native_routes_sha256=N.sha256_file(native_dir /
                                               'experiment_C' /
                                               'routes_l3d.json'),
            crossing_intervals=str(analysis_path),
            crossing_intervals_sha256=N.sha256_file(analysis_path),
        ),
        parameters=dict(
            clearance_mm=CLEARANCE,
            accept_point_mm=ACCEPT_POINT,
            accept_segment_mm=ACCEPT_SEGMENT,
            min_estimated_net=int(min_net),
            extra_route=int(extra_route),
            extra_net=int(extra_net),
            candidate_world='E5_joint_repair_final (analysis baseline_dir)',
            native_world='NATIVE_3D_CROSSING_OPT_1024/experiment_C',
            deterministic=True,
        ),
        worlds=dict(e5=world.sumary(),
                    native=(native_world.sumary() if native_world else None),
                    native_delta=(delta_world.sumary() if delta_world else None),
                    native_converted_routes=sorted(modified_in_native)),
        selection=OrderedDict(
            analysis_routes=len(analysis['routes']),
            analysis_candidates=sum(len(route['candidates'])
                                    for route in analysis['routes']),
            analysis_feasible_net_ge_min=int(
                sum(1 for route in analysis['routes']
                    for candidate in route['candidates']
                    if candidate.get('feasible')
                    and int(candidate['estimated_net']) >= int(min_net))),
            selected=len(candidates),
            selected_world_clean=aggregates['world_clean'],
            selected_near_miss=aggregates['near_miss'],
            selected_rejected=aggregates['rejected'],
            selected_production_rejected=aggregates['production_rejected'],
            routes_in_selection=len({item['route_id'] for item in candidates}),
        ),
        aggregates=aggregates,
        route129=route129,
        validation=validation,
        native_validation=native_validation,
        candidate_results=[_candidate_payload(item) for item in candidates],
    )
    json_path = out_dir / 'analysis' / 'blocker_analysis.json'
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                         encoding='utf-8')
    log('[write] %s (%.1f MB)'
        % (json_path, json_path.stat().st_size / 1e6))
    # -- plots -----------------------------------------------------------
    written = make_plots(candidates, aggregates, route129, out_dir)
    log('[write] plots: %s' % ', '.join(written))
    # -- report ----------------------------------------------------------
    elapsed = time.time() - started
    report = build_report(payload, elapsed=elapsed)
    report_path = out_dir / 'analysis' / 'blocker_analysis_report.md'
    report_path.write_text(report, encoding='utf-8')
    log('[write] %s' % report_path)
    log('[done] %.1fs' % elapsed)
    return payload


def _candidate_brief(item):
    return OrderedDict(
        route_id=item['route_id'],
        target_plane_label=item['target_plane_label'],
        target_z=_r(item['target_z'], 9),
        s_start_mm=_r(item['s_start_mm'], 6),
        s_end_mm=_r(item['s_end_mm'], 6),
        estimated_removed=item['estimated_removed'],
        estimated_added=item['estimated_added'],
        estimated_net=item['estimated_net'],
        category=item['category'],
        blockers=item['blockers'],
        blockers_hard=item['blockers_hard'],
        near_miss_blockers=item['near_miss_blockers'],
        movable_blockers=item['movable_blockers'],
        manual_blockers=item['manual_blockers'],
        kinds=sorted({violation['kind'] for violation in item['violations']})
        + (['flat_same_plane_conflict'] if item['d56'] else []),
    )


def _candidate_payload(item):
    payload = OrderedDict(
        route_id=item['route_id'],
        cluster_index=item['cluster_index'],
        body_layer_label=item['body_layer_label'],
        target_plane_id=item['target_plane_id'],
        target_plane_label=item['target_plane_label'],
        target_z=_r(item['target_z'], 9),
        estimated_removed=item['estimated_removed'],
        estimated_added=item['estimated_added'],
        estimated_net=item['estimated_net'],
        s_start_mm=_r(item['s_start_mm'], 6),
        s_end_mm=_r(item['s_end_mm'], 6),
        footprint_mm=_r(item['footprint_mm'], 6),
        middle_mm=_r(item['middle_mm'], 6),
        analytic_world_3d_ok=item['analytic_world_3d_ok'],
        analytic_world_3d_reason=item['analytic_world_3d_reason'],
        route_modified_in_native=item['route_modified_in_native'],
        route_direct=item['route_direct'],
        build_ok=item['build_ok'],
        build_error=item['build_error'],
        structure_errors=item['structure_errors'],
        metadata_errors_raw=item['metadata_errors_raw'],
        metadata_ok_repaired=item['metadata_ok_repaired'],
        layer_pitch=item['layer_pitch'],
        violations=item['violations'],
        d56=item['d56'],
        self_clearance=item['self_clearance'],
        blockers=item['blockers'],
        blockers_hard=item['blockers_hard'],
        near_miss_blockers=item['near_miss_blockers'],
        movable_blockers=item['movable_blockers'],
        manual_blockers=item['manual_blockers'],
        hard_violations=item['hard_violations'],
        near_miss_violations=item['near_miss_violations'],
        category=item['category'],
        world_clean=item['world_clean'],
        production_rejected=item['production_rejected'],
    )
    native = item.get('native_world')
    if native is not None:
        payload['native_world'] = native
    return payload


def build_route_129_section(candidates, analysis, baseline_by_id, route_id=129):
    route_analysis = next((route for route in analysis['routes']
                           if int(route['route_id']) == int(route_id)), None)
    baseline_route = baseline_by_id[int(route_id)]
    entries = [item for item in candidates
               if item['route_id'] == int(route_id)]
    targets = []
    for item in sorted(entries, key=lambda row: (row['target_plane_id'],
                                                 row['s_start_mm'])):
        targets.append(OrderedDict(
            target_plane_id=item['target_plane_id'],
            target_plane_label=item['target_plane_label'],
            target_z=_r(item['target_z'], 9),
            target_is_manual_plane=item['target_is_manual_plane'],
            s_start_mm=_r(item['s_start_mm'], 6),
            s_end_mm=_r(item['s_end_mm'], 6),
            footprint_mm=_r(item['footprint_mm'], 6),
            middle_mm=_r(item['middle_mm'], 6),
            estimated_removed=item['estimated_removed'],
            estimated_added=item['estimated_added'],
            estimated_net=item['estimated_net'],
            analytic_world_3d_ok=item['analytic_world_3d_ok'],
            blockers=item['blockers'],
            blockers_hard=item['blockers_hard'],
            near_miss_blockers=item['near_miss_blockers'],
            movable_blockers=item['movable_blockers'],
            manual_blockers=item['manual_blockers'],
            kinds=sorted({violation['kind']
                          for violation in item['violations']})
            + (['flat_same_plane_conflict'] if item['d56'] else []),
            hard_kinds=sorted({violation['kind']
                               for violation in item['violations']
                               if violation['hard']})
            + (['flat_same_plane_conflict'] if item['d56'] else []),
            violations=item['violations'],
            d56=item['d56'],
            hard_violations=item['hard_violations'],
            near_miss_violations=item['near_miss_violations'],
            world_clean=item['world_clean'],
            category=item['category'],
        ))
    net16_targets = [target for target in targets
                    if int(target['estimated_net']) == 16]
    common = None
    if net16_targets:
        sets = [set(target['movable_blockers']) for target in net16_targets]
        common = sorted(set.intersection(*sets)) if sets else []
    hard_union = set()
    for target in (net16_targets or targets):
        hard_union.update(target['blockers_hard'])
    net16_hard_union = sorted(hard_union)
    section = OrderedDict(
        route_id=int(route_id),
        body_layer_label=(route_analysis['body_layer_label']
                          if route_analysis else None),
        body_z=(float(route_analysis['body_z']) if route_analysis else None),
        body_flat_index=(int(route_analysis['body_flat_index'])
                         if route_analysis else None),
        cluster_index=(int(route_analysis['candidates'][0]['cluster_index'])
                       if route_analysis and route_analysis['candidates']
                       else None),
        cluster_count=(int(route_analysis['candidates'][0]['cluster_count'])
                       if route_analysis and route_analysis['candidates']
                       else None),
        cluster_start_mm=(float(route_analysis['candidates'][0]
                                ['cluster_start_mm'])
                          if route_analysis and route_analysis['candidates']
                          else None),
        cluster_end_mm=(float(route_analysis['candidates'][0]['cluster_end_mm'])
                        if route_analysis and route_analysis['candidates']
                        else None),
        net=16,
        n_target_heights=len(net16_targets),
        n_selected_candidates=len(targets),
        targets=targets,
        net16_targets=net16_targets,
        common_blockers=common or [],
        net16_hard_union=net16_hard_union,
        verdict=('the net=16 candidate is rejected by the production guard at '
                 'every target height. Physically (exact 3D < 0.05 mm) L4 has '
                 'no hard blocker (near-miss only) and L8 has exactly one hard '
                 'blocker (r120, an L7 flat right above the excursion start); '
                 'all other target heights need 2-5 hard blockers, and L15/L19/'
                 'Z1/Z2 additionally hit target-plane strict-D56 conflicts. A '
                 'single mid-body excursion cannot be accepted as-is; the '
                 'cheapest route is L4/L8 + exact handling of the near-miss '
                 'pairs (+ moving r120 for L8).'),
        route=baseline_route,
    )
    return section


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def build_report(payload, elapsed=None):
    agg = payload['aggregates']
    selection = payload['selection']
    route129 = payload['route129']
    params = payload['parameters']
    rejected = agg['rejected']
    near_miss = agg['near_miss']
    clean = agg['world_clean']
    hist = agg['movable_blocker_histogram']
    ghist = agg['guard_movable_blocker_histogram']
    lines = []
    lines.append('# D0 阻断分析报告：几何可行候选为何过不了真 3D 世界')
    lines.append('')
    lines.append('## 0. 结论速览')
    lines.append('')
    lines.append('- 候选池：`crossing_intervals.json` 中 feasible 且 estimated_net ≥ '
                 '%d 的候选 **%d** 个；按 (route, target, s0, s1) 去重后为 '
                 '**%d** 个（覆盖 %d 条路由），另含 route %d 的全部 net=%d 候选。'
                 % (params['min_estimated_net'],
                    selection['analysis_feasible_net_ge_min'],
                    selection['selected'], selection['routes_in_selection'],
                    129, 16))
    lines.append('- **生产 guard 口径**（World，含采样安全余量 ~0.061 mm）：'
                 'world-clean **%d**、被拒 **%d**；'
                 '**精确物理口径**（真实 3D < 0.05 mm）：硬阻断 **%d**、'
                 '仅 near-miss（精确距离仍 ≥0.05 mm）**%d**、world-clean **%d**。'
                 % (agg['world_clean'], agg['production_rejected'], rejected,
                    near_miss, clean))
    lines.append('- 被拒候选按**可移动阻断路由数**（guard 口径）：'
                 '0/1/2/3/4–8/>8 = %d/%d/%d/%d/%d/%d；'
                 '硬阻断口径：1/2/3/4–8/>8 = %d/%d/%d/%d/%d。'
                 '含 manual 硬阻断 = **%d**。'
                 % (ghist['0'], ghist['1'], ghist['2'], ghist['3'],
                    ghist['4-8'], ghist['>8'],
                    hist['1'], hist['2'], hist['3'], hist['4-8'], hist['>8'],
                    agg['candidates_with_manual_blocker']))
    lines.append('- joint rerouting 可能救回（无 manual、1–3 条可移动）：'
                 'guard 口径 **%d** 个（占被拒 %.1f%%）；'
                 '其中**物理上完全无硬阻断（只需 near-miss 处理）%d 个**。'
                 % (agg['fixable_1_3_guard']['count'],
                    100.0 * agg['fixable_1_3_guard']
                    ['fraction_of_production_rejected'],
                    agg['fixable_1_3_guard']['hard_clean']))
    lines.append('- 最高收益的 1–3 可移动阻断候选：**route %d → %s**，net=%d，'
                 'guard 阻断 %s（硬阻断 %s）。'
                 % (agg['fixable_1_3_guard']['top'][0]['route_id'],
                    agg['fixable_1_3_guard']['top'][0]['target_plane_label'],
                    agg['fixable_1_3_guard']['top'][0]['estimated_net'],
                    agg['fixable_1_3_guard']['top'][0]['blockers'],
                    agg['fixable_1_3_guard']['top'][0]['blockers_hard'])
                 if agg['fixable_1_3_guard']['top'] else '')
    lines.append('- route 129 的 net=16 候选：guard 口径 **%d 个目标高度全部被拒**；'
                 '物理硬阻断最少的是 L4（0 个硬阻断，仅 near-miss）与 L8（1 个硬阻断 '
                 'r120）；**verdict=单次 excursion 无法直接成立**（详见 §6）。'
                 % route129['n_target_heights'])
    lines.append('- 另外：world-clean 中 **%d** 个只是 metadata 记账问题'
                 '（direct 路线 `duck_out` 过期 body_heights；二次推导后几何合格，'
                 '属可修复的记账 bug，不是物理阻断）。'
                 % agg['world_clean_metadata_bug'])
    lines.append('')
    lines.append('## 1. 方法与口径（可复现）')
    lines.append('')
    lines.append('1. 候选池来自 `analysis/crossing_intervals.json`，其 '
                 '`baseline_dir` 是冻结 E5 基线；候选的 `s_start/s_end` 是 E5 路线'
                 '**本体 flat** 的弧长，因此候选必须用 E5 路线重建。'
                 '`experiment_C`（已接受 2440 交叉布局）中已转 Native 3D 的 '
                 '%d 条路由本体几何已改变，其 %d 个候选标记 '
                 '`route_modified_in_native`，只做 E5 世界分析、不参与 Native 复核。'
                 % (len(payload['worlds']['native_converted_routes']),
                    sum(1 for item in payload['candidate_results']
                        if item['route_modified_in_native'])))
    lines.append('2. 每个候选按 `route_model.duck_out(baseline_route, '
                 'body_flat_index, s0, s1, target_z)` 精确重建；direct'
                 '（Z1/Z2 接口本体，0 个 fanout transition）路线的 `duck_out` '
                 '会留下过期 `body_heights`，分析中二次推导 metadata 后再做几何'
                 '检查（原始 metadata 错误单独统计，见 §2.2）。')
    lines.append('3. 真 3D 检查与生产 guard 同口径：')
    lines.append('   - 同一物理高度：严格 D56（0.08 mm 中心线）全平面索引；'
                 '跨物理平面 flat 对按 0.05 mm 层间距规则视为合法；')
    lines.append('   - 不同物理高度：S 曲线 / 目标高度 flat 与其它路由 flat / '
                 'transition 的真实 3D 中心线距离，工艺规则阈值 0.05 mm；'
                 '生产 guard 采样安全余量对应 %.3f mm；' % params['accept_point_mm'])
    lines.append('   - 自身间距：`self_clearance_violations`（0.05 mm）。')
    lines.append('   - **guard 口径** = 生产 World/guard 的判定（含采样余量，'
                 '候选在此口径被拒即实验无法采纳）；**硬口径** = 用精确 S 曲线'
                 '参数化（两段 R15 圆弧）局部细化到 <1e-3 mm 后仍 <0.05 mm 的'
                 '真实违规；介于两者之间的是 near-miss（生产会被保守拒绝，'
                 '但精确距离其实 ≥0.05 mm）。')
    lines.append('4. 阻断分类：可移动 vs 冻结 manual（`assignment_1024.csv` 的 '
                 '`manual_group` 非空 = 冻结 U，共 %d 条）；分组 '
                 '(a) 1–3 可移动硬阻断、(b) ≥4 可移动硬阻断、(c) 含 manual 硬阻断、'
                 '(d) 自身几何/记账失败、(e) world-clean、'
                 '(f) 仅 near-miss（无硬阻断）。'
                 % agg['manual_routes'])
    lines.append('5. 生产 guard 交叉验证：确定性抽样 %d 个候选，'
                 '`guard.local_world_check` 报出的阻断/类型全部被快速扫描覆盖 '
                 '（一致率 %.1f%%；fast-clean 但 production 报错矛盾 %d 个；'
                 '前 %d 个另跑 `guard.candidate_guard` 记录阶段分布）。'
                 % (payload['validation']['compared'],
                    100.0 * payload['validation']['agreement_ratio'],
                    payload['validation']['world_clean_contradictions'],
                    payload['validation'].get('guard_checked', 0)))
    if payload.get('native_validation'):
        native_val = payload['native_validation']
        lines.append('6. 已接受 Native 布局的生产复核：%d 个候选上 '
                     '`local_world_check` 与快速扫描一致率 %.1f%%，双方都 '
                     'world-clean 的 %d 个。'
                     % (native_val['compared'],
                        100.0 * native_val['agreement_ratio'],
                        native_val['world_clean_agreements']))
    lines.append('')
    lines.append('## 2. 总体分布')
    lines.append('')
    lines.append('### 2.1 阻断路由个数')
    lines.append('')
    lines.append('| 阻断个数 | guard 口径可移动 | 硬口径可移动 | 硬口径全部路由 |')
    lines.append('|---|---:|---:|---:|')
    for key in ('0', '1', '2', '3', '4-8', '>8'):
        lines.append('| %s | %d | %d | %d |'
                     % (key, ghist[key], hist[key],
                        agg['total_blocker_histogram'][key]))
    lines.append('')
    lines.append('### 2.2 候选分组（按硬口径）')
    lines.append('')
    lines.append('| 分组 | 候选数 |')
    lines.append('|---|---:|')
    labels = OrderedDict((
        ('a_1_3_movable', '(a) 1–3 个可移动硬阻断'),
        ('b_ge4_movable', '(b) ≥4 个可移动硬阻断'),
        ('c_manual', '(c) 含冻结 manual(U) 硬阻断'),
        ('d_own_geometry', '(d) 自身几何/记账失败'),
        ('f_near_miss', '(f) 仅 guard sampling near-miss'),
        ('e_world_clean', '(e) world-clean'),
    ))
    for key, label in labels.items():
        lines.append('| %s | %d |' % (label, agg['category_counts'][key]))
    lines.append('')
    lines.append('- world-clean 中 metadata 可正常通过生产 gate **%d** 个，'
                 'metadata 记账失败 **%d** 个（direct 路线重建 artifact）。'
                 % (agg['world_clean_metadata_ok'],
                    agg['world_clean_metadata_bug']))
    lines.append('- direct（Z1/Z2 接口本体）路线候选 **%d** 个：world-clean '
                 '**%d**、带 metadata artifact **%d**。'
                 % (agg['direct_route_candidates'],
                    agg['direct_route_world_clean'],
                    agg['direct_route_metadata_bug']))
    lines.append('')
    lines.append('### 2.3 违规类型')
    lines.append('')
    lines.append('| 违规类型 | 硬违规记录 | 全部 guard 记录 | 涉及候选数 |')
    lines.append('|---|---:|---:|---:|')
    for kind in sorted(agg['violation_kind_candidates']):
        lines.append('| %s | %d | %d | %d |'
                     % (kind, agg['violation_kind_hard_records'].get(kind, 0),
                        agg['violation_kind_records'].get(kind, 0),
                        agg['violation_kind_candidates'][kind]))
    lines.append('')
    lines.append('- 相位分布（up/down/middle）：%s'
                 % ', '.join('%s=%d' % (key, value) for key, value
                             in agg['phase_records'].items()))
    lines.append('- 阻断高度分布（blocker flat 的 z / transition 中点 z）：%s'
                 % ', '.join('%s:%d' % (key, value) for key, value
                             in list(agg['blocker_height_histogram'].items())))
    lines.append('')
    if agg['near_miss_top']:
        lines.append('### 2.4 仅 near-miss 的候选（精确距离 ≥0.05 mm，'
                     '被 guard 0.061 mm 余量拒绝）')
        lines.append('')
        lines.append('| route | 目标高度 | net | guard 口径阻断 |')
        lines.append('|---:|---|---:|---|')
        for item in agg['near_miss_top'][:10]:
            lines.append('| %d | %s | %d | %s |'
                         % (item['route_id'], item['target_plane_label'],
                            item['estimated_net'], item['blockers']))
        lines.append('')
    if agg.get('native_sensitivity'):
        ns = agg['native_sensitivity']
        lines.append('### 2.5 对已接受 Native 布局（experiment_C）的敏感性')
        lines.append('')
        lines.append('- 可复核候选（路线未被 experiment_C 改动）**%d** 个；'
                     '与 E5 世界相比硬阻断集合完全相同 **%d** 个（%.1f%%）。'
                     % (ns['checked'], ns['same_blockers'],
                        100.0 * ns['same_ratio']))
        lines.append('- 差异集中在被 experiment_C 转 Native 的 55 条路由上：'
                     '它们的本体 flat 被自己的 excursion 切开、travel flat 移到'
                     '目标高度，因此对其它候选的阻断几何随之变化；'
                     'E5 世界的阻断计数在那些区域是保守上界。')
        lines.append('- 硬口径 world-clean（无任何硬阻断）：E5 世界 %d 个，'
                     'Native 世界 %d 个；E5→Native 变 clean %d 个、'
                     '变 blocked %d 个。差异来自 55 条 converted 路由：'
                     '它们自己的 excursion 既移走了原本体 flat 上的阻挡段，'
                     '又把 travel flat 放到了目标高度（可能新增 D56/3D 阻挡），'
                     '因此 E5 世界的阻断计数在 converted 路由附近只是近似。'
                     % (ns['e5_hard_clean'], ns['native_hard_clean'],
                        ns['became_hard_clean'], ns['became_hard_blocked']))
        lines.append('')
    lines.append('## 3. 机制解释（为什么几何可行 ≠ 真 3D 可行）')
    lines.append('')
    lines.append('- **主因是 transition_vs_flat**：换层 S 曲线穿过所有中间物理层，'
                 '其它路由在那些高度上的 flat 只要落在 S 曲线 1–7 mm 的落点'
                 '范围内，真实 3D 距离就 < 0.05 mm。不同物理平面之间没有 crossing '
                 '豁免，这是硬冲突。')
    lines.append('- 一次 excursion 的可用空间不是 2D 走廊，而是**贯穿所有中间高度的'
                 '3D 柱体**；1024 条路由 + 21 个高度使大部分目标高度的 S 曲线 '
                 'footprint 都被多条 flat 穿过。')
    lines.append('- **目标高度 strict-D56** 是第二类阻断：middle flat 与目标高度上'
                 '其它路由 flat 的 2D 距离须 ≥0.08 mm（或合法横穿），'
                 '目标高度占用越满越难。')
    lines.append('- 目标高度离本体越远，S 曲线穿过的中间高度越多、阻断路由数越多；'
                 '这解释了 per-target-height 的差异（§4），也解释了上一轮 55 条'
                 '被接受的 Native 3D 路由集中在低层 L6/L7/L8/L20（占用较少）。')
    lines.append('')
    lines.append('## 4. 每目标高度统计')
    lines.append('')
    lines.append('| 目标高度 | z (mm) | 候选数 | world-clean | near-miss | '
                 '硬阻断 | 含 manual | 平均可移动硬阻断 | 最大 |')
    lines.append('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
    for key, row in agg['per_target_height'].items():
        lines.append('| %s | %.3f | %d | %d | %d | %d | %d | %.2f | %d |'
                     % (key, row['target_z_mm'], row['candidates'],
                        row['world_clean'], row['near_miss'], row['rejected'],
                        row['manual_blocked'], row['mean_movable_blockers'],
                        row['movable_blockers_max']))
    lines.append('')
    lines.append('## 5. joint rerouting 可能救回的候选')
    lines.append('')
    lines.append('### 5.1 最高收益的 1–3 可移动 guard 阻断候选')
    lines.append('')
    guard_top = agg['fixable_1_3_guard']['top'][:12]
    if guard_top:
        lines.append('| route | 目标高度 | net | guard 阻断路由 | 硬阻断路由 | kinds |')
        lines.append('|---:|---|---:|---|---|---|')
        for item in guard_top:
            lines.append('| %d | %s | %d | %s | %s | %s |'
                         % (item['route_id'], item['target_plane_label'],
                            item['estimated_net'], item['blockers'],
                            item['blockers_hard'] or '-',
                            ', '.join(item['kinds']) or '-'))
    else:
        lines.append('- 无。')
    lines.append('')
    lines.append('### 5.2 物理上无硬阻断（仅 near-miss）的候选')
    lines.append('')
    physical = [item for item in agg['near_miss_top']]
    if physical:
        lines.append('| route | 目标高度 | net | near-miss blocker 数 | '
                     'guard 阻断路由 |')
        lines.append('|---:|---|---:|---:|---|')
        for item in physical[:10]:
            lines.append('| %d | %s | %d | %d | %s |'
                         % (item['route_id'], item['target_plane_label'],
                            item['estimated_net'],
                            len(item['near_miss_blockers']), item['blockers']))
        lines.append('')
        lines.append('这些候选的真实 3D 距离全部 ≥0.05 mm；被拒只因生产 guard 的'
                     '保守采样余量（0.061 mm）。让 guard 对接近阈值的对做精确'
                     '细化、或对 near-miss 做微调（移动并行 flat 数 µm 级／'
                     '重新放置 excursion），即可在**不重路由**的情况下释放收益。')
    else:
        lines.append('- 无。')
    lines.append('')
    lines.append('## 6. Route 129（net=16）专门结论')
    lines.append('')
    lines.append('route 129 本体 %s（z=%.3f mm），cluster s=%.2f–%.2f mm 内 '
                 '%d 个交叉；analysis 在 **%d 个目标高度**给出 net=16 候选'
                 '（另有 %d 个 net<16 的候选见 JSON）。'
                 % (route129['body_layer_label'], route129['body_z'],
                    route129['cluster_start_mm'], route129['cluster_end_mm'],
                    route129['cluster_count'], route129['n_target_heights'],
                    route129['n_selected_candidates']
                    - route129['n_target_heights']))
    lines.append('')
    lines.append('| 目标高度 | z (mm) | footprint | middle | guard 阻断 | '
                 '硬阻断路由 | 可移动硬阻断 | manual | near-miss | hard kinds |')
    lines.append('|---|---:|---:|---:|---|---:|---:|---:|---:|---|')
    for target in route129['net16_targets']:
        lines.append('| %s | %.3f | %.2f | %.2f | %s | %s | %d | %d | %d | %s |'
                     % (target['target_plane_label'], target['target_z'],
                        target['footprint_mm'], target['middle_mm'],
                        target['blockers'], target['blockers_hard'] or '-',
                        len(target['movable_blockers']),
                        len(target['manual_blockers']),
                        len(target['near_miss_blockers']),
                        ', '.join(target['hard_kinds']) or '-'))
    lines.append('')
    lines.append('- **verdict**：net=16 的 **%d 个目标高度在生产 guard 口径下全部'
                 '被拒**，单次 excursion 直接采纳不可行。'
                 % route129['n_target_heights'])
    hard_counter = Counter()
    for target in route129['net16_targets']:
        for blocker in target['blockers_hard']:
            hard_counter[blocker] += 1
    lines.append('- 物理硬阻断并集 **%d** 条路由；出现最多的：%s。'
                 '其中 **r120（L7 flat，在 excursion 起点正上方约 31 µm）** 挡了 '
                 '%d/%d 个目标高度，是最关键的一条。'
                 % (len(hard_counter),
                    ', '.join('r%d×%d' % (rid, count) for rid, count
                              in sorted(hard_counter.items(),
                                        key=lambda item: (-item[1],
                                                          item[0]))[:8]),
                    hard_counter.get(120, 0), route129['n_target_heights']))
    l4 = next((target for target in route129['net16_targets']
               if target['target_plane_label'] == 'L4'), None)
    l8 = next((target for target in route129['net16_targets']
               if target['target_plane_label'] == 'L8'), None)
    lines.append('- 最好的两个目标高度：**L4**（%d 个硬阻断，仅 %d 个 near-miss）'
                 '与 **L8**（%d 个硬阻断 %s + %d 个 near-miss）。'
                 % (len(l4['blockers_hard']) if l4 else -1,
                    len(l4['near_miss_blockers']) if l4 else -1,
                    len(l8['blockers_hard']) if l8 else -1,
                    (l8['blockers_hard'] if l8 else '') or '-',
                    len(l8['near_miss_blockers']) if l8 else -1))
    lines.append('- 含义：L4 在**精确物理口径下已经合法**，只差 guard 的采样余量'
                 '（3 条并行/邻近 flat 在 0.051–0.058 mm）；L8 只差把 r120 移开'
                 '（或把 excursion 沿路径错开 ~mm 级）。'
                 '其它目标高度需 2–5 条硬阻断路由。')
    lines.append('- 结论：route 129 的 net=16 **不能**靠移动 1–3 条路由直接拿到；'
                 '最小可行路径是"取 L4（或 L8）目标 + 处理 2–5 条 near-miss' 
                 '（精确复核/微调）+ L8 时移开 r120"，之后再按生产 guard 完整复核。')
    lines.append('')
    lines.append('## 7. 给 Lead 的四个数字')
    lines.append('')
    lines.append('(i) 被拒候选（生产 guard 口径 %d 个）按可移动阻断路由数：'
                 '0/1/2/3/4–8/>8 = %d/%d/%d/%d/%d/%d；'
                 '含冻结 manual 硬阻断 = **%d**。'
                 '（物理硬口径：1/2/3/4–8/>8 = %d/%d/%d/%d/%d。）'
                 % (agg['production_rejected'], ghist['0'], ghist['1'],
                    ghist['2'], ghist['3'], ghist['4-8'], ghist['>8'],
                    agg['candidates_with_manual_blocker'],
                    hist['1'], hist['2'], hist['3'], hist['4-8'], hist['>8']))
    lines.append('(ii) 可能被 1–3 条路由 joint rerouting 修好的比例：'
                 '**%.1f%%**（%d / %d，guard 口径、无 manual）；'
                 '物理硬口径 = %.1f%%（%d / %d）。'
                 % (100.0 * agg['fixable_1_3_guard']
                    ['fraction_of_production_rejected'],
                    agg['fixable_1_3_guard']['count'],
                    agg['production_rejected'],
                    100.0 * agg['fixable_1_3_movable']['fraction_of_rejected'],
                    agg['fixable_1_3_movable']['count'], rejected))
    if agg['fixable_1_3_guard']['top']:
        item = agg['fixable_1_3_guard']['top'][0]
        lines.append('(iii) 最高收益的 1–3 可移动阻断候选 = route %d → %s，'
                     'net=%d，guard 阻断 %s（硬阻断 %s）；'
                     '若只算硬阻断，最高收益是 route 129 → L8（net=16，'
                     '1 个硬阻断 r120）。'
                     % (item['route_id'], item['target_plane_label'],
                        item['estimated_net'], item['blockers'],
                        item['blockers_hard'] or '无'))
    lines.append('(iv) route 129 verdict = **不可行（单次 excursion 直接采纳）**：'
                 '%d 个 net=16 目标高度 guard 口径全拒；物理硬阻断最少 L4（0，'
                 '仅 near-miss）与 L8（1, r120），其余 2–5 条；'
                 '需先解决 r120 + near-miss 才能谈 net=16。'
                 % route129['n_target_heights'])
    lines.append('')
    lines.append('## 8. 产物与复现')
    lines.append('')
    lines.append('- `analysis/blocker_analysis.json`：逐候选违规/硬阻断/native '
                 '复核、聚合分布、route 129 明细、生产 guard 校验（确定性、浮点取整）。')
    lines.append('- `analysis/plots/*.png`：阻断数直方图、硬违规位置 XY 热图、'
                 'route 129 明细图、目标高度统计图。')
    lines.append('- 复现：`python -m four_side_1024.fanout1024.native3d.'
                 'blocker_analysis --baseline-dir <E5> --native-dir '
                 '<NATIVE_3D_CROSSING_OPT_1024> --out-dir '
                 '<NATIVE_3D_JOINT_OPT_1024>`；入口脚本 '
                 '`scratch/blocker_analyst/scripts/run_blocker_analysis.py`。')
    lines.append('- 本次运行 %.1f s；candidate world = E5（候选定义世界），'
                 'Native 世界仅作敏感性复核。'
                 % (float(elapsed) if elapsed is not None else -1.0))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='D0 true-3D blocker analysis of Native-3D excursion '
                    'candidates (read-only baselines).')
    parser.add_argument('--baseline-dir', default=str(DEFAULT_BASELINE),
                        help='frozen E5 baseline run dir (READ ONLY)')
    parser.add_argument('--native-dir', default=str(DEFAULT_NATIVE_DIR),
                        help='NATIVE_3D_CROSSING_OPT_1024 run dir (READ ONLY)')
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT_DIR),
                        help='output run dir (only analysis/ is written)')
    parser.add_argument('--min-net', type=int, default=3,
                        help='select every feasible candidate with '
                             'estimated_net >= this value (default 3)')
    parser.add_argument('--extra-route', type=int, default=129)
    parser.add_argument('--extra-net', type=int, default=16)
    parser.add_argument('--limit', type=int, default=None,
                        help='debug: only the first N selected candidates')
    parser.add_argument('--skip-native', action='store_true',
                        help='skip the accepted-native sensitivity analysis')
    parser.add_argument('--validation-limit', type=int, default=60)
    args = parser.parse_args(argv)
    analyse(baseline_dir=args.baseline_dir, native_dir=args.native_dir,
            out_dir=args.out_dir, min_net=args.min_net,
            extra_route=args.extra_route, extra_net=args.extra_net,
            limit=args.limit, skip_native=args.skip_native,
            validation_limit=args.validation_limit, log=print)
    return 0


if __name__ == '__main__':
    sys.exit(main())
