"""Independent validator for the corrected L1-L5 model, extended to L1-L11 by dynamic ROUTING_LAYER_IDS.

The corrected model (``four_side_1024/l3d/SCHEMA_L3D.md``) is:

* **L1 is the interface routing layer and contains BOTH port rows**: ``z1`` at
  physical height 0.0 mm and ``z2`` at 0.5 mm (a real 0.5 mm height difference);
* **L2..L5** are four additional routing layers whose physical heights are
  *unconfirmed simulation parameters*; formal process acceptance is refused while
  they are unconfirmed;
* a route may make several transitions (even back-to-back, even between
  non-adjacent layers), and the full path is checked in true XYZ;
* ``layer_id`` is a logical identity, **never** a z coordinate.

This validator is independent of the router: it never imports ``l3d.router`` /
``l3d.paths`` / ``l3d.world`` / ``l3d.layers`` and it never trusts router flags
or saved validation fields.  Every transition is rebuilt from the JSON parameters
(``dz`` / ``radius`` -> ``theta = acos(1 - |dz|/(2R))``, ``footprint = 2R sin
theta``, ``length = 2R theta``), every flat sample is re-derived from the 2D
primitives, and every distance/curvature number is computed here.  The R15
process profile (``four_side_1024.r15.profile_r15.apply()``) is applied before the
frozen ``fslw`` modules are imported, exactly as required for this round.

Checks (SCHEMA section 4, requirements 1-10)
--------------------------------------------
1. L1 is the interface layer with rows z1=0.0 / z2=0.5, ports of every route carry
   the z of their row.
2. The two same-column ports of the two rows keep their 0.5 mm real 3D distance
   even when their XY is identical (port-model self-check).
3. Every routed route starts/ends exactly on a correct L1 port with the row z.
4. Transitions L1->L2..L5 are legal: R=15, theta/footprint/length consistent with
   dz, endpoints joined to the adjacent flats, horizontal tangent continuity.
5. Intermediate-layer transitions / multiple / back-to-back transitions are legal;
   layer and z sequences are consistent; every layer pair is allowed by
   ``allowed_transitions``.
6. Full 3D curvature: the rebuilt path is sampled at <= 0.02 mm and the minimum
   circumradius must be >= 15*(1-1e-3) = 14.985 mm; flat arcs are exactly R=15 and
   lines axis aligned; transitions are analytically R=15; endpoint/tangent
   continuity is checked.
7. Transitions (and any other-layer parts) versus L1 row flats: true 3D centre-line
   distance >= 0.08 mm - no crossing exemption across different physical z.
8. Two routes on the same logical layer but different physical height (L1 z1 row
   vs z2 row) are checked in real 3D; parts on the same physical z use the frozen
   strict 2D pair rules (legal crossing windows allowed).
9. ``layer_id`` is never used as z: same layer_id with different z -> distinct
   planes; different layer_ids at close z -> still checked (and rejected if the
   stack violates its physical-plane spacing invariant).
10. If L2..L5 heights are undefined/invalid or ``provenance != 'confirmed'``:
    formal acceptance is refused (``formal_acceptance=false``,
    ``status='exploratory_only'``; nonzero exit unless ``--allow-exploratory``,
    where the geometry may be reported as ``exploratory_pass=true`` but never
    formal).  Invalid stacks (non-monotonic heights, planes closer than the
    0.08 mm clearance, missing L2..L5, wrong L1 rows, ...) are rejected.

Command line::

    .venv\\Scripts\\python.exe -m four_side_1024.l3d.validate_l3d \\
        --routes outputs/four_side_1024_v2_l1l5_v01/.../routes_l3d.json \\
        [--layer-stack <stack.json|inline-json>] [--allow-exploratory] \\
        [--out <report.json>]

Exit codes: 0 = requested acceptance level passed (formal, or exploratory with
``--allow-exploratory``), 1 = geometry/contract failure, 2 = invalid layer stack /
geometry unavailable, 3 = formal acceptance refused (unconfirmed layer stack) and
exploratory acceptance not allowed.

Output: one JSON report with the layer-stack verdict, per-check blocks, counters,
statistics, a machine-readable ``items[]`` list (one entry per requirement) and
every violation detail.
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

# ---------------------------------------------------------------------------
# R15 process profile: must be applied BEFORE importing the frozen fslw modules
# (they and their import-time constants belong to the R15 round).  The import is
# lazy so importing this module alone has no side effects.
# ---------------------------------------------------------------------------
_FSLW_CACHE = {}


def _fslw_modules():
    """Import the frozen ``fslw`` modules after applying the R15 profile."""
    if "mods" not in _FSLW_CACHE:
        from ..r15 import profile_r15
        profile_r15.apply()
        from ..fslw import ports as fslw_ports
        from ..fslw import validate_fslw
        _FSLW_CACHE["mods"] = (fslw_ports, validate_fslw)
    return _FSLW_CACHE["mods"]


def _fslw_ports():
    return _fslw_modules()[0]


def _fslw_validate():
    return _fslw_modules()[1]


# ---------------------------------------------------------------------------
# Process constants of this round (R15 fixed radius)
# ---------------------------------------------------------------------------
RADIUS_MM = 15.0
MIN_CURVATURE_MM = RADIUS_MM * (1.0 - 1e-3)      # 14.985 mm (SCHEMA tolerance)
CLEARANCE_MM = 0.08                               # centre-line clearance
WIDTH_MM = 0.05
BOARD_MM = 150.0
SAGITTA_MM = 0.0005
INTERFACE_LAYER_ID = 1
ROUTING_LAYER_IDS = (2, 3, 4, 5)  # dynamically extended by caller for L6..L11
INTERFACE_ROWS = {"z1": 0.0, "z2": 0.5}
ROW_OF_PLANE = {"z1": 1, "z2": 2}
PLANE_OF_ROW = {1: "z1", 2: "z2"}
PROVENANCE_CONFIRMED = "confirmed"
PROVENANCE_UNCONFIRMED = "unconfirmed_simulation"
PROVENANCE_VALUES = (PROVENANCE_CONFIRMED, PROVENANCE_UNCONFIRMED)
STACK_SCHEMA = "four_side_1024_v2_l3d_layer_stack_v1"
ROUTES_SCHEMA = "four_side_1024_v2_l3d_routes_v1"
REPORT_SCHEMA = "four_side_1024_v2_l3d_validation_v1"

# Tolerances.  Delivered numbers are rounded to 1e-9 (coordinates, z, footprint,
# theta) and 1e-6 (lengths); the tolerances below are tighter than physical
# meaning but looser than that rounding.
POS_TOL_MM = 1e-6
POSE_TOL = 1e-6
ORTHO_TOL = 1e-9
RADIUS_TOL = 1e-9
QUARTER_TOL = 1e-9
Z_TOL = 1e-9
THETA_TOL = 1e-6
TRANSITION_TOL_MM = 1e-6
LEN_FIELD_TOL_MM = 1e-5
INTERFACE_ROW_TOL = 1e-9
CLEARANCE_TOL_MM = 1e-7

# Sampling (mm).  Curvature samples the full path at <= 0.02 mm as required; the
# 3D clearance pass uses the same 0.02 mm on curved parts and 0.1 mm on straight
# lines (a straight chord is exact, so this changes nothing but memory).
CURVATURE_STEP_MM = 0.02
TRANSITION_STEP_MM = 0.02
FLAT_LINE_STEP_MM = 0.1
FLAT_ARC_STEP_MM = 0.02
QUERY_RADIUS_MM = 0.18
SELF_PATH_SEPARATION_MM = 1.0
MAX_VIOLATIONS_STORED = 300

#: Coordinates are delivered rounded to 1e-9 mm.  Two points closer than this are
#: the same point; merging them keeps polyline samples well conditioned (a
#: near-duplicate sample would otherwise create a spurious tiny circumradius).
POINT_MERGE_TOL_MM = 1e-6

CATEGORIES = (
    "contract_errors",
    "port_errors",
    "geometry_errors",
    "curvature_violations",
    "clearance_violations",
    "same_plane_violations",
    "self_clearance_violations",
    "other_errors",
)


class _DataError(Exception):
    """Raised when a JSON value cannot be interpreted at all."""


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------
def _as_float(value, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _DataError(f"invalid_{what}")
    if not math.isfinite(number):
        raise _DataError(f"nonfinite_{what}")
    return number


def _as_xy(value, what):
    try:
        if isinstance(value, (str, bytes)) or len(value) != 2:
            raise ValueError
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError, IndexError):
        raise _DataError(f"invalid_{what}")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise _DataError(f"nonfinite_{what}")
    return (x, y)


def _as_int(value, what):
    if isinstance(value, bool):
        raise _DataError(f"invalid_{what}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _DataError(f"invalid_{what}")
    if isinstance(value, float) and not value.is_integer():
        raise _DataError(f"invalid_{what}")
    return number


def _round(value, digits=9):
    return None if value is None else round(float(value), digits)


def _fmt(value, digits=6):
    return "n/a" if value is None else f"{value:.{digits}f}"


# ---------------------------------------------------------------------------
# Violation report
# ---------------------------------------------------------------------------
class _Report:
    """Violation collector with per-category counts and capped detail storage."""

    def __init__(self, max_stored=MAX_VIOLATIONS_STORED):
        self.counts = OrderedDict((name, 0) for name in CATEGORIES)
        self.violations = []
        self.warnings = []
        self.kind_counts = Counter()
        self.max_stored = int(max_stored)

    def add(self, category, kind, detail=None, route_id=None, other_route=None,
            **extra):
        if category not in self.counts:
            raise KeyError(category)
        self.counts[category] += 1
        self.kind_counts[f"{category}:{kind}"] += 1
        if len(self.violations) >= self.max_stored:
            return
        entry = {"kind": kind, "category": category}
        if route_id is not None:
            entry["route_id"] = route_id
        if other_route is not None:
            entry["other_route"] = other_route
        if detail is not None:
            entry["detail"] = detail
        entry.update(extra)
        self.violations.append(entry)

    def warn(self, message):
        if len(self.warnings) < 200:
            self.warnings.append(str(message))

    @property
    def total(self):
        return sum(self.counts.values())


def _finalise_counts(report):
    counts = OrderedDict()
    counts["violations"] = report.total
    for name in CATEGORIES:
        counts[name] = report.counts[name]
    return counts


# ---------------------------------------------------------------------------
# Independent 2D primitive geometry (lines + R15 circular arcs)
# ---------------------------------------------------------------------------
class _Prim2D:
    """Parsed 2D line/arc primitive with its own analytic parameterisation."""

    __slots__ = ("kind", "p0", "p1", "center", "radius", "start_angle", "sweep",
                 "length")

    def __init__(self, kind, p0, p1, center=None, radius=0.0, start_angle=0.0,
                 sweep=0.0):
        self.kind = kind
        self.p0 = p0
        self.p1 = p1
        self.center = center
        self.radius = radius
        self.start_angle = start_angle
        self.sweep = sweep
        if kind == "line":
            self.length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        else:
            self.length = abs(sweep) * radius

    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            raise _DataError("primitive_not_a_mapping")
        kind = raw.get("kind")
        p0 = _as_xy(raw.get("p0"), "p0")
        p1 = _as_xy(raw.get("p1"), "p1")
        if kind == "line":
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if length <= RADIUS_TOL:
                raise _DataError("zero_length_line")
            return cls("line", p0, p1)
        if kind != "arc":
            raise _DataError(f"unknown_primitive_kind:{kind!r}")
        center = _as_xy(raw.get("center"), "center")
        radius = _as_float(raw.get("radius"), "radius")
        start_angle = _as_float(raw.get("start_angle"), "start_angle")
        sweep = _as_float(raw.get("sweep"), "sweep")
        if radius <= RADIUS_TOL:
            raise _DataError("nonpositive_radius")
        if abs(sweep) <= RADIUS_TOL or abs(sweep) > 2.0 * math.pi + RADIUS_TOL:
            raise _DataError("invalid_sweep")
        return cls("arc", p0, p1, center, radius, start_angle, sweep)

    def point(self, t):
        if self.kind == "line":
            return (self.p0[0] + (self.p1[0] - self.p0[0]) * t,
                    self.p0[1] + (self.p1[1] - self.p0[1]) * t)
        angle = self.start_angle + self.sweep * t
        return (self.center[0] + self.radius * math.cos(angle),
                self.center[1] + self.radius * math.sin(angle))

    def tangent(self, t):
        if self.kind == "line":
            return ((self.p1[0] - self.p0[0]) / self.length,
                    (self.p1[1] - self.p0[1]) / self.length)
        sign = 1.0 if self.sweep >= 0.0 else -1.0
        angle = self.start_angle + self.sweep * t
        return (-sign * math.sin(angle), sign * math.cos(angle))

    def samples2d(self, step):
        count = max(2, int(math.ceil(self.length / step)) + 1)
        if self.kind == "line":
            t = np.linspace(0.0, 1.0, count)
            return np.column_stack([
                self.p0[0] + t * (self.p1[0] - self.p0[0]),
                self.p0[1] + t * (self.p1[1] - self.p0[1])])
        angles = self.start_angle + self.sweep * np.linspace(0.0, 1.0, count)
        return np.column_stack([
            self.center[0] + self.radius * np.cos(angles),
            self.center[1] + self.radius * np.sin(angles)])

    def point_many(self, t):
        """Vectorised ``point(t)`` for an array of parameters."""
        t = np.asarray(t, dtype=float)
        if self.kind == "line":
            return np.column_stack([
                self.p0[0] + t * (self.p1[0] - self.p0[0]),
                self.p0[1] + t * (self.p1[1] - self.p0[1])])
        angles = self.start_angle + self.sweep * t
        return np.column_stack([
            self.center[0] + self.radius * np.cos(angles),
            self.center[1] + self.radius * np.sin(angles)])

    def to_raw(self):
        if self.kind == "line":
            return {"kind": "line", "p0": list(self.p0), "p1": list(self.p1)}
        return {"kind": "arc", "p0": list(self.p0), "p1": list(self.p1),
                "center": list(self.center), "radius": float(self.radius),
                "start_angle": float(self.start_angle),
                "sweep": float(self.sweep)}


# ---------------------------------------------------------------------------
# Route parts (independent 3D reconstruction)
# ---------------------------------------------------------------------------
class _FlatPart:
    """Constant-height sub-chain of the 2D path on one logical layer."""

    kind = "flat"
    __slots__ = ("index", "layer_id", "z_mm", "primitives", "length")

    def __init__(self, index, layer_id, z_mm, primitives):
        self.index = index
        self.layer_id = layer_id
        self.z_mm = z_mm
        self.primitives = primitives
        self.length = sum(primitive.length for primitive in primitives)

    @property
    def start_xyz(self):
        return (self.primitives[0].p0[0], self.primitives[0].p0[1], self.z_mm)

    @property
    def end_xyz(self):
        return (self.primitives[-1].p1[0], self.primitives[-1].p1[1], self.z_mm)

    def start_tangent3(self):
        tangent = self.primitives[0].tangent(0.0)
        return (tangent[0], tangent[1], 0.0)

    def end_tangent3(self):
        tangent = self.primitives[-1].tangent(1.0)
        return (tangent[0], tangent[1], 0.0)

    def raw_primitives(self):
        return [primitive.to_raw() for primitive in self.primitives]

    def point_xyz_at_s(self, s_values):
        """Exact 3D points at arc-length positions along the flat chain."""
        s = np.asarray(s_values, dtype=float)
        lengths = np.array([primitive.length for primitive in self.primitives],
                           dtype=float)
        cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
        out = np.empty((len(s), 3))
        out[:, 2] = float(self.z_mm)
        index = np.searchsorted(cumulative, s, side="right") - 1
        index = np.clip(index, 0, len(self.primitives) - 1)
        local = (s - cumulative[index]) / lengths[index]
        local = np.clip(local, 0.0, 1.0)
        for position, primitive in enumerate(self.primitives):
            mask = index == position
            if not np.any(mask):
                continue
            out[mask, :2] = primitive.point_many(local[mask])
        return out

    def samples3d(self, line_step=FLAT_LINE_STEP_MM,
                  arc_step=FLAT_ARC_STEP_MM):
        chunks = []
        previous = None
        for primitive in self.primitives:
            step = line_step if primitive.kind == "line" else arc_step
            xy = primitive.samples2d(step)
            if previous is not None and len(xy):
                # delivered coordinates are rounded to 1e-9 mm; a shared primitive
                # joint may differ by a few 1e-10 mm -> merge, never keep a
                # zero-length step (it would corrupt discrete curvature)
                if math.hypot(xy[0, 0] - previous[0],
                              xy[0, 1] - previous[1]) <= POINT_MERGE_TOL_MM:
                    xy = xy[1:]
            if not len(xy):
                continue
            chunks.append(xy)
            previous = (float(xy[-1, 0]), float(xy[-1, 1]))
        if not chunks:
            return np.zeros((0, 3))
        xy = np.vstack(chunks)
        return np.column_stack([xy, np.full(len(xy), float(self.z_mm))])


class _TransitionPart:
    """Vertical-plane two-arc S-curve rebuilt from the JSON parameters."""

    kind = "transition"
    __slots__ = ("index", "from_layer", "to_layer", "z0", "z1", "dz", "radius",
                 "theta", "footprint", "length", "start", "direction", "end",
                 "declared")

    def __init__(self, index, from_layer, to_layer, z0, z1, radius, start,
                 direction, end=None, declared=None):
        self.index = index
        self.from_layer = int(from_layer)
        self.to_layer = int(to_layer)
        self.z0 = float(z0)
        self.z1 = float(z1)
        self.dz = self.z1 - self.z0
        self.radius = float(radius)
        self.start = (float(start[0]), float(start[1]))
        norm = math.hypot(direction[0], direction[1])
        self.direction = (float(direction[0]) / norm, float(direction[1]) / norm)
        ratio = 1.0 - abs(self.dz) / (2.0 * self.radius)
        self.theta = math.acos(max(-1.0, min(1.0, ratio)))
        self.footprint = 2.0 * self.radius * math.sin(self.theta)
        self.length = 2.0 * self.radius * self.theta
        if end is None:
            end = (self.start[0] + self.direction[0] * self.footprint,
                   self.start[1] + self.direction[1] * self.footprint)
        self.end = (float(end[0]), float(end[1]))
        self.declared = declared or {}

    @property
    def sign(self):
        return 1.0 if self.z1 >= self.z0 else -1.0

    @property
    def start_xyz(self):
        return (self.start[0], self.start[1], self.z0)

    @property
    def end_xyz(self):
        return (self.end[0], self.end[1], self.z1)

    def start_tangent3(self):
        return (self.direction[0], self.direction[1], 0.0)

    def end_tangent3(self):
        return (self.direction[0], self.direction[1], 0.0)

    def point_at_s(self, s_values):
        """Exact 3D points at arc-length positions along the S-curve."""
        s = np.asarray(s_values, dtype=float)
        count = len(s)
        u = np.empty(count, dtype=float)
        z = np.empty(count, dtype=float)
        half = 0.5 * self.length
        first = s <= half + 1e-15
        sign = self.sign
        phi = s[first] / self.radius
        u[first] = self.radius * np.sin(phi)
        z[first] = self.z0 + sign * self.radius * (1.0 - np.cos(phi))
        phi = (self.length - s[~first]) / self.radius
        u[~first] = self.footprint - self.radius * np.sin(phi)
        middle_z = self.z0 + sign * abs(self.dz) / 2.0
        z[~first] = 2.0 * middle_z - (
            self.z0 + sign * self.radius * (1.0 - np.cos(phi)))
        x = self.start[0] + self.direction[0] * u
        y = self.start[1] + self.direction[1] * u
        return np.column_stack([x, y, z])

    def samples3d(self, step=TRANSITION_STEP_MM):
        count = max(2, int(math.ceil(self.length / step)) + 1)
        return self.point_at_s(np.linspace(0.0, self.length, count))


class _RouteGeom:
    """Rebuilt 3D geometry of one routed L3D route."""

    __slots__ = ("route_id", "plane", "row", "row_z", "parts", "record")

    def __init__(self, route_id, plane, row, row_z, parts, record=None):
        self.route_id = int(route_id)
        self.plane = plane
        self.row = int(row)
        self.row_z = float(row_z)
        self.parts = parts
        self.record = record or {}

    @property
    def flat_parts(self):
        return [part for part in self.parts if part.kind == "flat"]

    @property
    def transitions(self):
        return [part for part in self.parts if part.kind == "transition"]

    @property
    def start_xyz(self):
        return self.parts[0].start_xyz

    @property
    def end_xyz(self):
        return self.parts[-1].end_xyz

    def start_tangent3(self):
        return self.parts[0].start_tangent3()

    def end_tangent3(self):
        return self.parts[-1].end_tangent3()

    @property
    def flat_length(self):
        return sum(part.length for part in self.flat_parts)

    @property
    def transition_length(self):
        return sum(part.length for part in self.transitions)

    @property
    def xy_length(self):
        return self.flat_length + sum(part.footprint for part in self.transitions)

    @property
    def total_length(self):
        return self.flat_length + self.transition_length

    @property
    def z_span(self):
        heights = [part.z_mm for part in self.flat_parts]
        return (max(heights) - min(heights)) if heights else 0.0

    def samples3d(self, line_step=FLAT_LINE_STEP_MM,
                  arc_step=FLAT_ARC_STEP_MM,
                  transition_step=TRANSITION_STEP_MM):
        chunks = []
        previous = None
        for part in self.parts:
            if part.kind == "flat":
                points = part.samples3d(line_step, arc_step)
            else:
                points = part.samples3d(transition_step)
            if previous is not None and len(points):
                distance = math.dist(previous, tuple(points[0]))
                # delivered coordinates are rounded to 1e-9 mm, so coincident
                # join points may differ by a few 1e-10 mm; merge them so the
                # sampled polyline never contains ill-conditioned zero-length steps
                if distance <= POINT_MERGE_TOL_MM:
                    points = points[1:]
            if len(points):
                chunks.append(points)
                previous = tuple(float(value) for value in points[-1])
        if not chunks:
            return np.zeros((0, 3))
        return np.vstack(chunks)

    def samples3d_uniform(self, step=CURVATURE_STEP_MM):
        """Exact uniform arc-length 3D sampling of the whole path (step <= 0.02).

        Each part/primitive is evaluated from its own analytic geometry at the
        requested arc length, so every point lies on the true centre-line (no
        chord interpolation) and no two consecutive samples can coincide - a
        rounded primitive joint can therefore never create a spurious curvature
        triple.
        """
        pieces = []          # (length_mm, callable(local_arc_length) -> (n, 3))
        for part in self.parts:
            if part.kind == "flat":
                for primitive in part.primitives:
                    if primitive.length <= 0.0:
                        continue

                    def _flat(local, primitive=primitive, z=part.z_mm):
                        t = np.asarray(local, dtype=float) / primitive.length
                        xy = primitive.point_many(np.clip(t, 0.0, 1.0))
                        return np.column_stack([xy, np.full(len(xy), float(z))])

                    pieces.append((primitive.length, _flat))
            else:
                if part.length <= 0.0:
                    continue
                pieces.append((part.length, part.point_at_s))
        if not pieces:
            return self.samples3d()
        lengths = np.array([length for length, _fn in pieces], dtype=float)
        cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
        total = float(cumulative[-1])
        if total <= step:
            return self.samples3d()
        count = max(2, int(math.ceil(total / step)) + 1)
        grid = np.linspace(0.0, total, count)
        index = np.clip(np.searchsorted(cumulative, grid, side="right") - 1,
                        0, len(pieces) - 1)
        out = np.empty((count, 3))
        for position, (length, function) in enumerate(pieces):
            mask = index == position
            if not np.any(mask):
                continue
            out[mask] = function(grid[mask] - cumulative[position])
        return out


# ---------------------------------------------------------------------------
# Layer stack (independent parse + invariants from SCHEMA_L3D.md section 1)
# ---------------------------------------------------------------------------
class _LayerStack:
    """Parsed L1-L5 layer stack with an explicit validity verdict."""

    __slots__ = ("layers", "provenance", "note", "schema", "valid", "errors",
                 "warnings", "source", "height_defined", "allowed", "planes",
                 "reported_formal_flag")

    def __init__(self):
        self.layers = {}
        self.provenance = None
        self.note = ""
        self.schema = None
        self.valid = False
        self.errors = []
        self.warnings = []
        self.source = None
        self.height_defined = False
        self.allowed = {}
        self.planes = []
        self.reported_formal_flag = None

    # -- derived queries ----------------------------------------------------
    @property
    def confirmed(self):
        return self.provenance == PROVENANCE_CONFIRMED

    def layer(self, layer_id):
        return self.layers.get(int(layer_id))

    def is_interface(self, layer_id):
        layer = self.layer(layer_id)
        return bool(layer and layer["layer_type"] == "interface")

    def z_for_layer(self, layer_id, row):
        """Physical z of a logical layer for one interface row."""
        layer = self.layer(layer_id)
        if layer is None:
            raise _DataError(f"unknown_layer:{layer_id}")
        if layer["layer_type"] == "interface":
            if row not in layer["interface_rows"]:
                raise _DataError(f"unknown_interface_row:{row}")
            return float(layer["interface_rows"][row])
        if layer["physical_z_mm"] is None:
            raise _DataError(f"undefined_layer_height:{layer_id}")
        return float(layer["physical_z_mm"])

    def plane_label(self, layer_id, row=None):
        layer = self.layer(layer_id)
        if layer is None:
            return f"L{layer_id}"
        if layer["layer_type"] == "interface":
            return f"L1 row {row} (z={self.z_for_layer(layer_id, row):g})"
        return f"L{layer_id} (z={layer['physical_z_mm']:g})"

    def to_dict(self):
        return {
            "schema": self.schema,
            "provenance": self.provenance,
            "note": self.note,
            "source": self.source,
            "valid": bool(self.valid),
            "confirmed": bool(self.confirmed),
            "height_defined": bool(self.height_defined),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "layers": OrderedDict(
                (str(layer_id), dict(self.layers[layer_id]))
                for layer_id in sorted(self.layers)),
            "allowed_transitions": OrderedDict(
                (str(layer_id), sorted(targets))
                for layer_id, targets in sorted(self.allowed.items())),
            "physical_planes": [dict(entry) for entry in self.planes],
            "reported_formal_acceptance_allowed": self.reported_formal_flag,
        }


def _normalise_layer_entries(raw_layers):
    """Accept a mapping keyed by layer id/string or a list of layer dicts."""
    entries = []
    if isinstance(raw_layers, dict):
        for key, value in raw_layers.items():
            if not isinstance(value, dict):
                raise _DataError("layer_not_a_mapping")
            entry = dict(value)
            try:
                key_id = int(str(key).strip().lstrip("L"))
            except ValueError:
                raise _DataError(f"invalid_layer_key:{key!r}")
            entry.setdefault("layer_id", key_id)
            entries.append(entry)
    elif isinstance(raw_layers, list):
        for value in raw_layers:
            if not isinstance(value, dict):
                raise _DataError("layer_not_a_mapping")
            entries.append(dict(value))
    else:
        raise _DataError("layers_not_a_mapping_or_list")
    return entries


def parse_layer_stack(raw, source="embedded"):
    """Parse and validate a layer stack; returns a :class:`_LayerStack`."""
    stack = _LayerStack()
    stack.source = source
    if not isinstance(raw, dict):
        stack.errors.append("layer_stack_not_a_mapping")
        return stack
    stack.schema = raw.get("schema")
    if stack.schema is not None and stack.schema != STACK_SCHEMA:
        stack.errors.append(f"layer_stack_schema_mismatch:{stack.schema!r}")
    stack.provenance = raw.get("provenance")
    stack.note = raw.get("note") or raw.get("provenance_note") or ""
    stack.reported_formal_flag = raw.get("formal_acceptance_allowed")
    if stack.provenance is None:
        stack.errors.append("provenance_missing")
    elif stack.provenance not in PROVENANCE_VALUES:
        stack.errors.append(f"provenance_invalid:{stack.provenance!r}")
    if raw.get("interface_layer") is not None:
        try:
            if int(raw.get("interface_layer")) != INTERFACE_LAYER_ID:
                stack.errors.append(
                    f"interface_layer_invalid:{raw.get('interface_layer')!r}")
        except (TypeError, ValueError):
            stack.errors.append("interface_layer_invalid")
    try:
        entries = _normalise_layer_entries(raw.get("layers"))
    except _DataError as exc:
        stack.errors.append(str(exc))
        entries = []
    seen = set()
    for entry in entries:
        try:
            layer_id = _as_int(entry.get("layer_id"), "layer_id")
        except _DataError:
            stack.errors.append("layer_id_invalid")
            continue
        if layer_id in seen:
            stack.errors.append(f"duplicate_layer_id:{layer_id}")
            continue
        seen.add(layer_id)
        layer_type = entry.get("layer_type")
        physical_z = entry.get("physical_z_mm")
        if physical_z is not None:
            try:
                physical_z = float(physical_z)
                if not math.isfinite(physical_z):
                    physical_z = None
                    stack.errors.append(f"layer_height_not_finite:{layer_id}")
            except (TypeError, ValueError):
                physical_z = None
                stack.errors.append(f"layer_height_invalid:{layer_id}")
        interface_rows = {}
        raw_rows = entry.get("interface_rows") or {}
        if isinstance(raw_rows, dict):
            for name, value in raw_rows.items():
                try:
                    interface_rows[str(name)] = float(value)
                except (TypeError, ValueError):
                    stack.errors.append(
                        f"interface_row_invalid:{layer_id}:{name}")
        allowed_raw = entry.get("allowed_transitions")
        allowed = []
        if isinstance(allowed_raw, (list, tuple)):
            for value in allowed_raw:
                try:
                    allowed.append(_as_int(value, "allowed_transition"))
                except _DataError:
                    stack.errors.append(
                        f"allowed_transition_invalid:{layer_id}:{value!r}")
        else:
            stack.errors.append(f"allowed_transitions_missing:{layer_id}")
        stack.layers[layer_id] = {
            "layer_id": layer_id,
            "layer_type": layer_type,
            "physical_z_mm": physical_z,
            "interface_rows": interface_rows,
            "allowed_transitions": sorted(set(allowed)),
        }
    # ---- required layer set ------------------------------------------------
    required = {INTERFACE_LAYER_ID, *ROUTING_LAYER_IDS}
    if set(stack.layers) != required:
        missing = sorted(required - set(stack.layers))
        extra = sorted(set(stack.layers) - required)
        if missing:
            stack.errors.append(f"layers_missing:{missing}")
        if extra:
            stack.errors.append(f"layers_unexpected:{extra}")
    # ---- L1 interface layer ------------------------------------------------
    interface = stack.layers.get(INTERFACE_LAYER_ID)
    if interface is not None:
        if interface["layer_type"] != "interface":
            stack.errors.append("L1_must_be_interface_layer")
        if interface["physical_z_mm"] is not None:
            stack.errors.append("L1_must_not_have_single_physical_z")
        rows = interface["interface_rows"]
        if set(rows) != set(INTERFACE_ROWS):
            stack.errors.append(f"L1_interface_rows_invalid:{sorted(rows)}")
        else:
            for name, expected in INTERFACE_ROWS.items():
                if abs(rows[name] - expected) > INTERFACE_ROW_TOL:
                    stack.errors.append(
                        f"L1_row_height_invalid:{name}={rows[name]!r}"
                        f"!= {expected}")
    # ---- L2..L5 routing layers --------------------------------------------
    heights = []
    height_defined = True
    for layer_id in ROUTING_LAYER_IDS:
        layer = stack.layers.get(layer_id)
        if layer is None:
            height_defined = False
            continue
        if layer["layer_type"] != "routing":
            stack.errors.append(f"L{layer_id}_must_be_routing_layer")
        if layer["physical_z_mm"] is None:
            stack.errors.append(f"L{layer_id}_height_undefined")
            height_defined = False
        else:
            heights.append((layer_id, layer["physical_z_mm"]))
    stack.height_defined = bool(height_defined and len(heights) == len(ROUTING_LAYER_IDS))
    if stack.height_defined:
        for (id_a, z_a), (id_b, z_b) in zip(heights, heights[1:]):
            if not z_b > z_a:
                stack.errors.append(
                    f"routing_heights_not_strictly_ordered:"
                    f"L{id_a}={z_a:g},L{id_b}={z_b:g}")
        interface_planes = [("L1_row_z1", INTERFACE_ROWS["z1"]),
                            ("L1_row_z2", INTERFACE_ROWS["z2"])]
        all_planes = interface_planes + [
            (f"L{layer_id}", height) for layer_id, height in heights]
        for index_a in range(len(all_planes)):
            for index_b in range(index_a + 1, len(all_planes)):
                name_a, z_a = all_planes[index_a]
                name_b, z_b = all_planes[index_b]
                gap = abs(z_b - z_a)
                if gap < CLEARANCE_MM - 1e-12:
                    stack.errors.append(
                        f"physical_planes_too_close:{name_a}={z_a:g},"
                        f"{name_b}={z_b:g},gap={gap:g}<{CLEARANCE_MM:g}")
                elif abs(gap - CLEARANCE_MM) <= 1e-12:
                    stack.warnings.append(
                        f"physical_planes_at_exact_clearance:{name_a},"
                        f"{name_b},gap={gap:g}")
    # ---- allowed transitions: symmetry + connectivity ----------------------
    allowed = {}
    for layer_id in sorted(stack.layers):
        targets = set()
        for target in stack.layers[layer_id]["allowed_transitions"]:
            if target not in stack.layers:
                stack.errors.append(
                    f"allowed_transition_unknown_layer:{layer_id}->{target}")
                continue
            if target != layer_id:
                targets.add(target)
        allowed[layer_id] = targets
    for layer_id, targets in allowed.items():
        for target in targets:
            if layer_id not in allowed.get(target, set()):
                stack.errors.append(
                    f"allowed_transitions_asymmetric:{layer_id}<->{target}")
    stack.allowed = allowed
    if stack.layers and not any(
            error.startswith("allowed_transitions")
            for error in stack.errors):
        reachable = {INTERFACE_LAYER_ID}
        frontier = [INTERFACE_LAYER_ID]
        while frontier:
            current = frontier.pop()
            for target in allowed.get(current, set()):
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        if reachable != set(stack.layers):
            stack.errors.append(
                f"allowed_transitions_not_fully_connected:{sorted(reachable)}")
    # ---- physical plane table ---------------------------------------------
    stack.planes = _build_physical_planes(stack)
    stack.valid = not stack.errors
    return stack


def _build_physical_planes(stack):
    """Distinct physical z planes: L1 has two (rows), L2..L5 one each."""
    planes = []
    interface = stack.layers.get(INTERFACE_LAYER_ID)
    if interface is not None and interface["layer_type"] == "interface":
        for row_name in ("z1", "z2"):
            if row_name in interface["interface_rows"]:
                planes.append({
                    "z_mm": float(interface["interface_rows"][row_name]),
                    "layer_ids": [INTERFACE_LAYER_ID],
                    "interface_row": row_name,
                    "label": f"L1 row {row_name}",
                })
    for layer_id in ROUTING_LAYER_IDS:
        layer = stack.layers.get(layer_id)
        if layer is None or layer["physical_z_mm"] is None:
            continue
        planes.append({
            "z_mm": float(layer["physical_z_mm"]),
            "layer_ids": [int(layer_id)],
            "interface_row": None,
            "label": f"L{layer_id}",
        })
    planes.sort(key=lambda entry: entry["z_mm"])
    return planes


def _load_layer_stack_arg(value):
    """``--layer-stack`` accepts a path or an inline JSON string."""
    text = str(value).strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text), "cli_inline"
    path = Path(text)
    return json.loads(path.read_text(encoding="utf-8")), f"cli_file:{path}"


# ---------------------------------------------------------------------------
# Frozen V2 port identity / port-row separation (requirements 1-3)
# ---------------------------------------------------------------------------
_PORT_CACHE = {}


def _port_identity():
    """Load the frozen V2 port model: route identity + endpoints for both rows."""
    if "identity" in _PORT_CACHE:
        return _PORT_CACHE["identity"]
    ports = _fslw_ports()
    identity = {"available": False, "error": None, "planes": {}}
    try:
        for plane in ("z1", "z2"):
            routes, endpoints, _connectors, _validation = ports.load_plane(
                "V2", plane)
            identity["planes"][plane] = {
                "routes": {int(record["route_id"]): record for record in routes},
                "endpoints": endpoints,
            }
        identity["available"] = True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        identity["error"] = f"{type(exc).__name__}: {exc}"
    _PORT_CACHE["identity"] = identity
    return identity


def _endpoint_xy(endpoint):
    return tuple(float(value) for value in endpoint["routing_xy"])


def _check_port_row_model(report):
    """Requirement 2: same-column ports of the two rows keep 0.5 mm real distance."""
    block = {
        "enabled": True,
        "pairs_checked": 0,
        "pairs_expected": 1024,
        "min_3d_distance_mm": None,
        "row_heights_mm": dict(INTERFACE_ROWS),
        "ok": False,
        "errors": [],
    }
    ports = _fslw_ports()
    try:
        endpoints_all = ports.build_plane_endpoints()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        block["errors"].append(f"port_model_unavailable:{type(exc).__name__}:{exc}")
        report.add("port_errors", "port_model_unavailable",
                   detail=block["errors"][-1])
        return block
    by_xy = {}
    for endpoint in endpoints_all.values():
        key = (round(endpoint["routing_xy"][0], 9),
               round(endpoint["routing_xy"][1], 9))
        by_xy.setdefault(key, {})[endpoint["plane"]] = endpoint
    minimum = None
    for key, rows in by_xy.items():
        if "z1" not in rows or "z2" not in rows:
            continue
        block["pairs_checked"] += 1
        z1 = float(rows["z1"]["z_mm"])
        z2 = float(rows["z2"]["z_mm"])
        distance = math.sqrt((float(rows["z2"]["routing_xy"][0])
                              - float(rows["z1"]["routing_xy"][0])) ** 2
                             + (float(rows["z2"]["routing_xy"][1])
                                - float(rows["z1"]["routing_xy"][1])) ** 2
                             + (z2 - z1) ** 2)
        if minimum is None or distance < minimum:
            minimum = distance
        if abs(z1 - INTERFACE_ROWS["z1"]) > INTERFACE_ROW_TOL:
            report.add("port_errors", "port_model_row_height",
                       detail=f"z1 endpoint {rows['z1']['endpoint_id']} z={z1}")
        if abs(z2 - INTERFACE_ROWS["z2"]) > INTERFACE_ROW_TOL:
            report.add("port_errors", "port_model_row_height",
                       detail=f"z2 endpoint {rows['z2']['endpoint_id']} z={z2}")
        if distance < CLEARANCE_MM - CLEARANCE_TOL_MM:
            report.add("port_errors", "port_model_row_distance",
                       detail=f"same-XY rows distance={distance:.9g}")
    block["min_3d_distance_mm"] = _round(minimum)
    block["ok"] = (block["pairs_checked"] == block["pairs_expected"]
                   and minimum is not None
                   and minimum >= 0.5 - 1e-9
                   and not report.counts["port_errors"])
    if not block["ok"]:
        report.add("port_errors", "port_row_model_failed",
                   detail=f"pairs={block['pairs_checked']}, "
                          f"min_distance={block['min_3d_distance_mm']}")
    return block


# ---------------------------------------------------------------------------
# Route parsing
# ---------------------------------------------------------------------------
def _parse_flat_primitive(raw, index, report, route_id):
    where = f"primitive={index}"
    try:
        primitive = _Prim2D.from_raw(raw)
    except _DataError as exc:
        report.add("geometry_errors", "primitive_invalid",
                   detail=f"{where}: {exc}", route_id=route_id, primitive=index)
        return None
    if primitive.kind == "line":
        if not (abs(primitive.p1[0] - primitive.p0[0]) <= ORTHO_TOL
                or abs(primitive.p1[1] - primitive.p0[1]) <= ORTHO_TOL):
            report.add("geometry_errors", "diagonal_line",
                       detail=f"{where} p0={primitive.p0} p1={primitive.p1}",
                       route_id=route_id, primitive=index)
    else:
        if abs(primitive.radius - RADIUS_MM) > RADIUS_TOL:
            report.add("curvature_violations", "flat_arc_radius_not_r15",
                       detail=f"{where} radius={primitive.radius!r} "
                              f"(expected {RADIUS_MM})",
                       route_id=route_id, primitive=index)
        for name, angle, endpoint in (
                ("p0", primitive.start_angle, primitive.p0),
                ("p1", primitive.start_angle + primitive.sweep, primitive.p1)):
            reconstructed = (
                primitive.center[0] + primitive.radius * math.cos(angle),
                primitive.center[1] + primitive.radius * math.sin(angle))
            if math.hypot(reconstructed[0] - endpoint[0],
                          reconstructed[1] - endpoint[1]) > POS_TOL_MM:
                report.add("geometry_errors", "arc_endpoint_inconsistent",
                           detail=f"{where} {name}", route_id=route_id,
                           primitive=index)
    return primitive


def _parse_flat_part(raw, index, stack, row, route_id, report):
    layer_id = _as_int(raw.get("layer_id"), "layer_id")
    z_mm = _as_float(raw.get("z_mm"), "z_mm")
    declared_length = raw.get("length_mm")
    raw_primitives = raw.get("primitives")
    if not isinstance(raw_primitives, list) or not raw_primitives:
        report.add("geometry_errors", "flat_part_empty",
                   detail=f"part={index}", route_id=route_id)
        raise _DataError(f"flat_part_empty:part={index}")
    primitives = []
    for primitive_index, primitive_raw in enumerate(raw_primitives):
        primitive = _parse_flat_primitive(primitive_raw, primitive_index,
                                          report, route_id)
        if primitive is not None:
            primitives.append(primitive)
    if not primitives:
        raise _DataError(f"flat_part_no_valid_primitives:part={index}")
    if len(primitives) != len(raw_primitives):
        report.add("geometry_errors", "flat_part_primitive_count",
                   detail=f"part={index}", route_id=route_id)
    for primitive_index in range(1, len(primitives)):
        previous = primitives[primitive_index - 1]
        current = primitives[primitive_index]
        distance = math.hypot(previous.p1[0] - current.p0[0],
                              previous.p1[1] - current.p0[1])
        if distance > POS_TOL_MM:
            report.add("geometry_errors", "primitive_discontinuity",
                       detail=f"part={index} joint={primitive_index} "
                              f"distance={distance:.9g}",
                       route_id=route_id, primitive=primitive_index)
    part = _FlatPart(index, layer_id, z_mm, primitives)
    # the declared flat height must be the physical z of its logical layer
    try:
        expected_z = stack.z_for_layer(layer_id, PLANE_OF_ROW[row])
    except _DataError:
        report.add("geometry_errors", "flat_layer_unknown",
                   detail=f"part={index} layer_id={layer_id}",
                   route_id=route_id)
        expected_z = None
    if expected_z is not None:
        if abs(z_mm - expected_z) > Z_TOL:
            report.add("geometry_errors", "flat_height_mismatch",
                       detail=f"part={index} layer_id={layer_id} "
                              f"z={z_mm!r} expected={expected_z!r}",
                       route_id=route_id)
        if layer_id == INTERFACE_LAYER_ID \
                and abs(z_mm - stack.z_for_layer(layer_id,
                                                 PLANE_OF_ROW[row])) > Z_TOL:
            report.add("geometry_errors", "interface_row_changed",
                       detail=f"part={index} z={z_mm!r}", route_id=route_id)
    if declared_length is not None:
        try:
            declared = float(declared_length)
            if abs(declared - part.length) > LEN_FIELD_TOL_MM:
                report.add("contract_errors", "flat_part_length_mismatch",
                           detail=f"part={index} declared={declared!r} "
                                  f"rebuilt={_round(part.length)}",
                           route_id=route_id)
        except (TypeError, ValueError):
            report.add("contract_errors", "flat_part_length_invalid",
                       detail=f"part={index} {declared_length!r}",
                       route_id=route_id)
    return part


def _parse_transition_part(raw, index, stack, row, route_id, report):
    row_name = PLANE_OF_ROW[row]
    from_layer = _as_int(raw.get("from_layer"), "from_layer")
    to_layer = _as_int(raw.get("to_layer"), "to_layer")
    z0 = _as_float(raw.get("z0"), "z0")
    z1 = _as_float(raw.get("z1"), "z1")
    dz = _as_float(raw.get("dz_mm"), "dz_mm")
    radius = _as_float(raw.get("radius_mm"), "radius_mm")
    start = _as_xy(raw.get("start"), "start")
    direction = _as_xy(raw.get("direction"), "direction")
    end = _as_xy(raw.get("end"), "end")
    declared = {
        "theta_rad": raw.get("theta_rad"),
        "footprint_mm": raw.get("footprint_mm"),
        "length_mm": raw.get("length_mm"),
    }
    where = f"part={index}"
    norm = math.hypot(direction[0], direction[1])
    if abs(norm - 1.0) > POSE_TOL or norm <= 0.0:
        report.add("geometry_errors", "transition_direction_not_unit",
                   detail=f"{where} |direction|={norm}",
                   route_id=route_id)
        if norm <= 0.0:
            raise _DataError(f"zero_transition_direction:{where}")
    if abs(radius - RADIUS_MM) > RADIUS_TOL:
        report.add("curvature_violations", "transition_radius_not_r15",
                   detail=f"{where} radius={radius!r} (expected {RADIUS_MM})",
                   route_id=route_id)
    if abs(radius) <= RADIUS_TOL:
        raise _DataError(f"zero_transition_radius:{where}")
    # logical-layer legality
    if from_layer == to_layer:
        report.add("geometry_errors", "transition_same_layer",
                   detail=f"{where} layer={from_layer}", route_id=route_id)
    for layer_id in (from_layer, to_layer):
        if layer_id not in stack.layers:
            report.add("geometry_errors", "transition_unknown_layer",
                       detail=f"{where} layer_id={layer_id}", route_id=route_id)
            raise _DataError(f"transition_unknown_layer:{layer_id}")
    allowed = stack.allowed.get(from_layer, set())
    if to_layer not in allowed:
        report.add("geometry_errors", "transition_layer_pair_not_allowed",
                   detail=f"{where} {from_layer}->{to_layer}", route_id=route_id)
    # physical z consistency with the layer stack
    try:
        expected_z0 = stack.z_for_layer(from_layer, row_name)
        expected_z1 = stack.z_for_layer(to_layer, row_name)
    except _DataError as exc:
        report.add("geometry_errors", "transition_layer_height_undefined",
                   detail=f"{where} {exc}", route_id=route_id)
        expected_z0 = expected_z1 = None
    if expected_z0 is not None and abs(z0 - expected_z0) > Z_TOL:
        report.add("geometry_errors", "transition_z0_mismatch",
                   detail=f"{where} z0={z0!r} expected={expected_z0!r} "
                          f"layer={from_layer}", route_id=route_id)
    if expected_z1 is not None and abs(z1 - expected_z1) > Z_TOL:
        report.add("geometry_errors", "transition_z1_mismatch",
                   detail=f"{where} z1={z1!r} expected={expected_z1!r} "
                          f"layer={to_layer}", route_id=route_id)
    if from_layer == INTERFACE_LAYER_ID and expected_z0 is not None \
            and abs(z0 - stack.z_for_layer(INTERFACE_LAYER_ID, row_name)) > Z_TOL:
        report.add("geometry_errors", "interface_row_changed",
                   detail=f"{where} leaves L1 at z={z0!r}", route_id=route_id)
    if to_layer == INTERFACE_LAYER_ID and expected_z1 is not None \
            and abs(z1 - stack.z_for_layer(INTERFACE_LAYER_ID, row_name)) > Z_TOL:
        report.add("geometry_errors", "interface_row_changed",
                   detail=f"{where} enters L1 at z={z1!r}", route_id=route_id)
    if abs(dz - (z1 - z0)) > Z_TOL:
        report.add("geometry_errors", "transition_dz_mismatch",
                   detail=f"{where} dz={dz!r} z1-z0={z1 - z0!r}",
                   route_id=route_id)
    if abs(dz) <= Z_TOL:
        report.add("geometry_errors", "transition_zero_height",
                   detail=f"{where}", route_id=route_id)
        raise _DataError(f"transition_zero_height:{where}")
    if abs(dz) >= 2.0 * abs(radius) - RADIUS_TOL:
        report.add("geometry_errors", "transition_height_exceeds_2r",
                   detail=f"{where} dz={dz!r} radius={radius!r}",
                   route_id=route_id)
        raise _DataError(f"transition_height_exceeds_2r:{where}")
    if not (abs(direction[0]) <= ORTHO_TOL or abs(direction[1]) <= ORTHO_TOL):
        report.add("geometry_errors", "transition_direction_not_axis_aligned",
                   detail=f"{where} direction={direction!r}", route_id=route_id)
    part = _TransitionPart(index, from_layer, to_layer, z0, z1, radius,
                           start, direction, end=end, declared=declared)
    # analytic formula checks (SCHEMA section 2)
    expected_end = (part.start[0] + part.direction[0] * part.footprint,
                    part.start[1] + part.direction[1] * part.footprint)
    distance = math.hypot(expected_end[0] - part.end[0],
                          expected_end[1] - part.end[1])
    if distance > POS_TOL_MM:
        report.add("geometry_errors", "transition_end_mismatch",
                   detail=f"{where} end={part.end!r} expected={expected_end!r} "
                          f"distance={distance:.9g}", route_id=route_id)
    try:
        declared_theta = declared["theta_rad"]
        if declared_theta is not None and \
                abs(float(declared_theta) - part.theta) > THETA_TOL:
            report.add("curvature_violations", "transition_theta_mismatch",
                       detail=f"{where} declared={declared_theta!r} "
                              f"rebuilt={part.theta!r}", route_id=route_id)
    except (TypeError, ValueError):
        report.add("contract_errors", "transition_theta_invalid",
                   detail=f"{where} {declared['theta_rad']!r}", route_id=route_id)
    try:
        declared_footprint = declared["footprint_mm"]
        if declared_footprint is not None and \
                abs(float(declared_footprint) - part.footprint) \
                > TRANSITION_TOL_MM:
            report.add("curvature_violations",
                       "transition_footprint_mismatch",
                       detail=f"{where} declared={declared_footprint!r} "
                              f"rebuilt={_round(part.footprint)}",
                       route_id=route_id)
    except (TypeError, ValueError):
        report.add("contract_errors", "transition_footprint_invalid",
                   detail=f"{where} {declared['footprint_mm']!r}",
                   route_id=route_id)
    try:
        declared_length = declared["length_mm"]
        if declared_length is not None and \
                abs(float(declared_length) - part.length) > TRANSITION_TOL_MM:
            report.add("curvature_violations", "transition_length_mismatch",
                       detail=f"{where} declared={declared_length!r} "
                              f"rebuilt={_round(part.length)}",
                       route_id=route_id)
    except (TypeError, ValueError):
        report.add("contract_errors", "transition_length_invalid",
                   detail=f"{where} {declared['length_mm']!r}",
                   route_id=route_id)
    return part


def _parse_parts(record, stack, report, route_id):
    raw_parts = record.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        report.add("contract_errors", "route_parts_missing",
                   route_id=route_id)
        raise _DataError("route_parts_missing")
    row = int(record.get("source_row"))
    parts = []
    for index, raw in enumerate(raw_parts):
        if not isinstance(raw, dict):
            report.add("contract_errors", "part_not_a_mapping",
                       route_id=route_id, detail=f"part={index}")
            continue
        kind = raw.get("kind")
        try:
            if kind == "flat":
                parts.append(_parse_flat_part(raw, index, stack, row,
                                              route_id, report))
            elif kind == "transition":
                parts.append(_parse_transition_part(raw, index, stack, row,
                                                    route_id, report))
            else:
                report.add("contract_errors", "unknown_part_kind",
                           route_id=route_id,
                           detail=f"part={index} kind={kind!r}")
        except _DataError as exc:
            report.add("geometry_errors", "part_unparseable",
                       route_id=route_id,
                       detail=f"part={index}: {exc}")
    if not parts:
        raise _DataError("no_usable_parts")
    return parts


def _audit_part_sequence(geom, record, stack, report):
    """Structure / order / continuity / declared-field checks of one route."""
    route_id = geom.route_id
    parts = geom.parts
    # 1) start and end on L1 at the route row height
    first, last = parts[0], parts[-1]
    for name, part in (("start", first), ("end", last)):
        if part.kind != "flat":
            report.add("geometry_errors", f"route_{name}_not_l1_flat",
                       detail=f"{name} part is {part.kind}",
                       route_id=route_id)
        elif part.layer_id != INTERFACE_LAYER_ID:
            report.add("geometry_errors", f"route_{name}_not_l1_flat",
                       detail=f"{name} flat layer_id={part.layer_id}",
                       route_id=route_id)
        elif abs(part.z_mm - geom.row_z) > Z_TOL:
            report.add("geometry_errors", f"route_{name}_wrong_row_height",
                       detail=f"{name} z={part.z_mm!r} row_z={geom.row_z!r}",
                       route_id=route_id)
    # 2) 3D continuity and tangent continuity between adjacent parts
    for index in range(1, len(parts)):
        previous, current = parts[index - 1], parts[index]
        previous_end = previous.end_xyz
        current_start = current.start_xyz
        distance = math.dist(previous_end, current_start)
        if distance > POS_TOL_MM:
            report.add("geometry_errors", "part_discontinuity",
                       route_id=route_id,
                       detail=f"joint={index} distance={distance:.9g}")
        tangent_distance = math.dist(previous.end_tangent3(),
                                     current.start_tangent3())
        if tangent_distance > POSE_TOL:
            report.add("geometry_errors", "part_tangent_discontinuity",
                       route_id=route_id,
                       detail=f"joint={index} tangent_distance="
                              f"{tangent_distance:.9g}")
    # 3) transition connectivities: previous logical layer -> next logical layer
    current_layer = first.layer_id if first.kind == "flat" else None
    layer_sequence = [current_layer] if current_layer is not None else []
    back_to_back = 0
    for index, part in enumerate(parts):
        if part.kind == "flat":
            if current_layer is not None and part.layer_id != current_layer:
                report.add("geometry_errors", "flat_layer_sequence_mismatch",
                           route_id=route_id,
                           detail=f"part={index} layer={part.layer_id} "
                                  f"expected={current_layer}")
            if current_layer is None:
                current_layer = part.layer_id
                layer_sequence.append(current_layer)
            continue
        # transition: from_layer must match the current logical layer
        if current_layer is not None and part.from_layer != current_layer:
            report.add("geometry_errors", "transition_from_layer_mismatch",
                       route_id=route_id,
                       detail=f"part={index} from={part.from_layer} "
                              f"expected={current_layer}")
        if index > 0 and parts[index - 1].kind == "transition":
            back_to_back += 1
        current_layer = part.to_layer
        layer_sequence.append(current_layer)
    geom.record["_back_to_back_transitions"] = back_to_back
    # 4) declared sequence fields must agree with the rebuilt ones
    declared_sequence = record.get("layer_sequence")
    if isinstance(declared_sequence, list):
        try:
            declared = [int(value) for value in declared_sequence]
        except (TypeError, ValueError):
            declared = None
        if declared is not None and declared != layer_sequence:
            report.add("contract_errors", "layer_sequence_mismatch",
                       route_id=route_id,
                       detail=f"declared={declared} rebuilt={layer_sequence}")
    elif declared_sequence is not None:
        report.add("contract_errors", "layer_sequence_invalid",
                   route_id=route_id, detail=repr(declared_sequence))
    else:
        report.add("contract_errors", "layer_sequence_missing",
                   route_id=route_id)
    declared_z_sequence = record.get("layer_z_sequence")
    try:
        rebuilt_z_sequence = [stack.z_for_layer(layer_id, geom.plane)
                              for layer_id in layer_sequence]
    except _DataError:
        rebuilt_z_sequence = None
    if isinstance(declared_z_sequence, list) and rebuilt_z_sequence is not None:
        if len(declared_z_sequence) != len(rebuilt_z_sequence):
            report.add("contract_errors", "layer_z_sequence_mismatch",
                       route_id=route_id,
                       detail=f"declared={declared_z_sequence} "
                              f"rebuilt={rebuilt_z_sequence}")
        else:
            for index, (declared, rebuilt) in enumerate(
                    zip(declared_z_sequence, rebuilt_z_sequence)):
                try:
                    if abs(float(declared) - rebuilt) > Z_TOL:
                        report.add("contract_errors",
                                   "layer_z_sequence_mismatch",
                                   route_id=route_id,
                                   detail=f"index={index} declared={declared!r} "
                                          f"rebuilt={rebuilt!r}")
                except (TypeError, ValueError):
                    report.add("contract_errors", "layer_z_sequence_invalid",
                               route_id=route_id, detail=repr(declared))
    elif declared_z_sequence is None:
        report.add("contract_errors", "layer_z_sequence_missing",
                   route_id=route_id)
    else:
        report.add("contract_errors", "layer_z_sequence_invalid",
                   route_id=route_id, detail=repr(declared_z_sequence))
    # 5) declared transition count / lifted flag / layers_used / lengths
    transitions = geom.transitions
    declared_transitions = record.get("n_transitions")
    if declared_transitions is None:
        report.add("contract_errors", "n_transitions_missing",
                   route_id=route_id)
    else:
        try:
            if int(declared_transitions) != len(transitions):
                report.add("contract_errors", "n_transitions_mismatch",
                           route_id=route_id,
                           detail=f"declared={declared_transitions!r} "
                                  f"rebuilt={len(transitions)}")
        except (TypeError, ValueError):
            report.add("contract_errors", "n_transitions_invalid",
                       route_id=route_id, detail=repr(declared_transitions))
    lifted = record.get("lifted")
    rebuilt_lifted = bool(transitions)
    if lifted is None:
        report.add("contract_errors", "lifted_missing", route_id=route_id)
    elif bool(lifted) != rebuilt_lifted:
        report.add("contract_errors", "lifted_mismatch", route_id=route_id,
                   detail=f"declared={lifted!r} rebuilt={rebuilt_lifted}")
    layers_used = record.get("layers_used")
    rebuilt_layers_used = sorted({part.layer_id for part in geom.flat_parts})
    if isinstance(layers_used, list):
        try:
            declared_used = sorted({int(value) for value in layers_used})
        except (TypeError, ValueError):
            declared_used = None
        if declared_used is not None and declared_used != rebuilt_layers_used:
            report.add("contract_errors", "layers_used_mismatch",
                       route_id=route_id,
                       detail=f"declared={declared_used} "
                              f"rebuilt={rebuilt_layers_used}")
    elif layers_used is not None:
        report.add("contract_errors", "layers_used_invalid", route_id=route_id,
                   detail=repr(layers_used))
    else:
        report.add("contract_errors", "layers_used_missing", route_id=route_id)
    for field, rebuilt in (("xy_length_mm", geom.xy_length),
                           ("length_mm", geom.total_length),
                           ("z_span_mm", geom.z_span)):
        declared = record.get(field)
        if declared is None:
            report.add("contract_errors", "route_field_missing",
                       route_id=route_id, detail=field)
            continue
        try:
            if abs(float(declared) - rebuilt) > LEN_FIELD_TOL_MM:
                report.add("contract_errors", "route_field_mismatch",
                           route_id=route_id,
                           detail=f"{field} declared={declared!r} "
                                  f"rebuilt={_round(rebuilt)}")
        except (TypeError, ValueError):
            report.add("contract_errors", "route_field_invalid",
                       route_id=route_id, detail=f"{field}={declared!r}")
    # 6) horizontal tangents at transition ends and transition axis alignment
    for index, part in enumerate(parts):
        if part.kind != "transition":
            continue
        if abs(part.start_tangent3()[2]) > Z_TOL \
                or abs(part.end_tangent3()[2]) > Z_TOL:
            report.add("geometry_errors", "transition_tangent_not_horizontal",
                       route_id=route_id, detail=f"part={index}")
        if not (abs(part.direction[0]) <= ORTHO_TOL
                or abs(part.direction[1]) <= ORTHO_TOL):
            report.add("geometry_errors",
                       "transition_direction_not_axis_aligned",
                       route_id=route_id, detail=f"part={index}")


def _check_route_ports(geom, record, identity, stack, report):
    """Requirements 1/3: start/end are the correct L1 ports with the row z."""
    route_id = geom.route_id
    plane = geom.plane
    row_z = geom.row_z
    block = {"checked": True, "identity_checked": False,
             "start_port": None, "end_port": None, "errors": 0}
    source_port = record.get("source_port")
    target_port = record.get("target_port")
    for name, port in (("source", source_port), ("target", target_port)):
        if not isinstance(port, dict):
            report.add("port_errors", f"{name}_port_missing", route_id=route_id)
            block["checked"] = False
            continue
        try:
            xy = _as_xy(port.get("xy"), f"{name}_port_xy")
            z_mm = _as_float(port.get("z_mm"), f"{name}_port_z")
            layer_id = _as_int(port.get("layer_id"), f"{name}_port_layer")
        except _DataError as exc:
            report.add("port_errors", f"{name}_port_invalid",
                       route_id=route_id, detail=str(exc))
            block["checked"] = False
            continue
        if layer_id != INTERFACE_LAYER_ID:
            report.add("port_errors", f"{name}_port_not_l1", route_id=route_id,
                       detail=f"layer_id={layer_id}")
        if abs(z_mm - row_z) > Z_TOL:
            report.add("port_errors", f"{name}_port_row_height",
                       route_id=route_id,
                       detail=f"z_mm={z_mm!r} row_z={row_z!r}")
        block[f"{name}_port"] = {"xy": [_round(xy[0]), _round(xy[1])],
                                 "z_mm": _round(z_mm), "layer_id": layer_id}
        # part endpoints must coincide with the port poses
        if name == "source":
            start = geom.start_xyz
            distance = math.hypot(start[0] - xy[0], start[1] - xy[1])
            if distance > POS_TOL_MM or abs(start[2] - z_mm) > Z_TOL:
                report.add("port_errors", "route_start_mismatch",
                           route_id=route_id,
                           detail=f"start={start} port=({xy},{z_mm})")
            declared_start = record.get("start_z_mm")
            if declared_start is not None:
                try:
                    if abs(float(declared_start) - z_mm) > Z_TOL:
                        report.add("port_errors", "start_z_mismatch",
                                   route_id=route_id,
                                   detail=f"{declared_start!r} != {z_mm!r}")
                except (TypeError, ValueError):
                    report.add("contract_errors", "start_z_invalid",
                               route_id=route_id, detail=repr(declared_start))
        else:
            end = geom.end_xyz
            distance = math.hypot(end[0] - xy[0], end[1] - xy[1])
            if distance > POS_TOL_MM or abs(end[2] - z_mm) > Z_TOL:
                report.add("port_errors", "route_end_mismatch",
                           route_id=route_id,
                           detail=f"end={end} port=({xy},{z_mm})")
            declared_end = record.get("end_z_mm")
            if declared_end is not None:
                try:
                    if abs(float(declared_end) - z_mm) > Z_TOL:
                        report.add("port_errors", "end_z_mismatch",
                                   route_id=route_id,
                                   detail=f"{declared_end!r} != {z_mm!r}")
                except (TypeError, ValueError):
                    report.add("contract_errors", "end_z_invalid",
                               route_id=route_id, detail=repr(declared_end))
        # declared start/end directions (port metadata) must match the geometry
        direction_key = "start_dir" if name == "source" else "end_dir"
        declared_dir = record.get(direction_key)
        if declared_dir is not None:
            try:
                direction = _as_xy(declared_dir, direction_key)
            except _DataError:
                direction = None
            if direction is not None:
                tangent = (geom.start_tangent3() if name == "source"
                           else geom.end_tangent3())
                distance = math.hypot(tangent[0] - direction[0],
                                      tangent[1] - direction[1])
                if distance > POSE_TOL:
                    report.add("geometry_errors", f"{direction_key}_mismatch",
                               route_id=route_id,
                               detail=f"{direction} vs {tangent}")
    # V2 CSV identity (route id -> source/target endpoint poses)
    block["ok"] = report.counts["port_errors"] == 0
    if not identity.get("available"):
        return block
    block["identity_checked"] = True
    plane_identity = identity["planes"].get(plane)
    if plane_identity is None:
        report.add("port_errors", "plane_identity_missing", route_id=route_id)
        block["ok"] = False
        return block
    csv_record = plane_identity["routes"].get(route_id)
    if csv_record is None:
        report.add("port_errors", "route_id_not_in_v2_csv",
                   route_id=route_id, detail=plane)
        return block
    endpoints = plane_identity["endpoints"]
    for name, port, key in (("source", source_port, "source_endpoint"),
                            ("target", target_port, "target_endpoint")):
        if not isinstance(port, dict):
            continue
        endpoint = endpoints.get(csv_record.get(key))
        if endpoint is None:
            report.add("port_errors", f"{name}_endpoint_missing",
                       route_id=route_id, detail=str(csv_record.get(key)))
            continue
        expected_xy = _endpoint_xy(endpoint)
        try:
            xy = _as_xy(port.get("xy"), f"{name}_port_xy")
        except _DataError:
            continue
        distance = math.hypot(xy[0] - expected_xy[0], xy[1] - expected_xy[1])
        if distance > POS_TOL_MM:
            report.add("port_errors", f"{name}_port_identity_mismatch",
                       route_id=route_id,
                       detail=f"port={xy} csv={expected_xy} "
                              f"distance={distance:.9g}")
        # expected physical z from the CSV row
        expected_row = int(csv_record.get(f"{name}_row")) \
            if csv_record.get(f"{name}_row") is not None else geom.row
        expected_z = INTERFACE_ROWS[PLANE_OF_ROW.get(expected_row, "z1")]
        try:
            z_mm = _as_float(port.get("z_mm"), f"{name}_port_z")
            if abs(z_mm - expected_z) > Z_TOL:
                report.add("port_errors", f"{name}_port_row_z_mismatch",
                           route_id=route_id,
                           detail=f"port z={z_mm!r} csv row={expected_row} "
                                  f"expected z={expected_z!r}")
        except _DataError:
            pass
        # declared port direction identity: start_dir = source inward,
        # end_dir = -target inward (the CSV port direction, not a router flag)
        direction_key = "start_dir" if name == "source" else "end_dir"
        declared_dir = record.get(direction_key)
        if declared_dir is not None:
            try:
                direction = _as_xy(declared_dir, direction_key)
            except _DataError:
                direction = None
            if direction is not None:
                inward = endpoint.get("inward") or [0.0, 0.0]
                expected_dir = ((float(inward[0]), float(inward[1]))
                                if name == "source"
                                else (-float(inward[0]), -float(inward[1])))
                distance = math.hypot(direction[0] - expected_dir[0],
                                      direction[1] - expected_dir[1])
                if distance > POSE_TOL:
                    report.add("port_errors", f"{name}_direction_identity",
                               route_id=route_id,
                               detail=f"{direction} vs {expected_dir} "
                                      f"(csv inward={tuple(inward)})")
    block["errors"] = report.counts["port_errors"]
    block["ok"] = report.counts["port_errors"] == 0
    return block


def _parse_route(record, stack, identity, report):
    """Parse one routed record into a :class:`_RouteGeom`."""
    route_id = _as_int(record.get("route_id"), "route_id")
    plane = record.get("plane")
    if plane not in PLANE_OF_ROW.values():
        raise _DataError(f"invalid_plane:{plane!r}")
    row = ROW_OF_PLANE[plane]
    declared_row = record.get("source_row")
    try:
        declared_row = _as_int(declared_row, "source_row")
    except _DataError:
        declared_row = None
    if declared_row is not None and declared_row != row:
        report.add("contract_errors", "source_row_mismatch", route_id=route_id,
                   detail=f"declared={declared_row} plane={plane} row={row}")
    target_row = record.get("target_row")
    try:
        target_row_value = _as_int(target_row, "target_row")
    except _DataError:
        target_row_value = None
    if target_row_value is not None and target_row_value != row:
        report.add("geometry_errors", "interface_row_changed", route_id=route_id,
                   detail=f"target_row={target_row_value} source_row={row}")
    try:
        row_z = stack.z_for_layer(INTERFACE_LAYER_ID, plane)
    except _DataError:
        raise _DataError("interface_row_height_undefined")
    parts = _parse_parts(record, stack, report, route_id)
    geom = _RouteGeom(route_id, plane, row, row_z, parts, record=record)
    _audit_part_sequence(geom, record, stack, report)
    _check_route_ports(geom, record, identity, stack, report)
    # small metadata: start/end z of the record must be the row z
    for field in ("start_z_mm", "end_z_mm"):
        declared = record.get(field)
        if declared is None:
            report.add("contract_errors", "route_field_missing",
                       route_id=route_id, detail=field)
            continue
        try:
            if abs(float(declared) - row_z) > Z_TOL:
                report.add("contract_errors", "route_row_height_mismatch",
                           route_id=route_id,
                           detail=f"{field}={declared!r} row_z={row_z!r}")
        except (TypeError, ValueError):
            report.add("contract_errors", "route_field_invalid",
                       route_id=route_id, detail=f"{field}={declared!r}")
    return geom


def _check_failed_record(record, identity, stack, report):
    """Light structural / port-identity check of a failed L3D record."""
    route_id = record.get("route_id")
    plane = record.get("plane")
    block = {"checked": True}
    for field in ("route_id", "plane", "status", "source_row", "target_row",
                  "source_port", "target_port"):
        if field not in record:
            report.add("contract_errors", "failed_record_missing_field",
                       route_id=route_id, detail=field)
            block["checked"] = False
    if plane not in PLANE_OF_ROW.values():
        report.add("contract_errors", "failed_record_plane_invalid",
                   route_id=route_id, detail=repr(plane))
        return block
    row = ROW_OF_PLANE[plane]
    row_z = INTERFACE_ROWS[plane]
    for name in ("source", "target"):
        port = record.get(f"{name}_port")
        if not isinstance(port, dict):
            continue
        try:
            z_mm = _as_float(port.get("z_mm"), f"{name}_port_z")
            layer_id = _as_int(port.get("layer_id"), f"{name}_port_layer")
        except _DataError:
            continue
        if layer_id != INTERFACE_LAYER_ID:
            report.add("port_errors", f"failed_{name}_port_not_l1",
                       route_id=route_id, detail=f"layer_id={layer_id}")
        if abs(z_mm - row_z) > Z_TOL:
            report.add("port_errors", f"failed_{name}_port_row_height",
                       route_id=route_id,
                       detail=f"z={z_mm!r} row_z={row_z!r}")
    if identity.get("available"):
        csv_record = identity["planes"][plane]["routes"].get(int(route_id)) \
            if isinstance(route_id, (int, float)) else None
        if csv_record is None:
            report.add("port_errors", "failed_route_id_not_in_v2_csv",
                       route_id=route_id)
    return block


# ---------------------------------------------------------------------------
# Curvature (requirement 6)
# ---------------------------------------------------------------------------
def _polyline_min_curvature(points):
    """Minimum sampled circumradius (mm) of a 3D polyline; inf if unknown."""
    if len(points) < 3:
        return float("inf")
    a = points[:-2]
    b = points[1:-1]
    c = points[2:]
    ab = b - a
    ac = c - a
    double_area = np.linalg.norm(np.cross(ab, ac), axis=1)
    length_ab = np.linalg.norm(ab, axis=1)
    length_ac = np.linalg.norm(ac, axis=1)
    length_bc = np.linalg.norm(c - b, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        radius = length_ab * length_ac * length_bc / (2.0 * double_area)
    # ill-conditioned triples (straight runs or a degenerate sampled step) do not
    # define a curvature; only well-spaced triples are used
    shortest = np.minimum(np.minimum(length_ab, length_ac), length_bc)
    usable = (double_area > 1e-14) & (shortest > 1e-6)
    if not np.any(usable):
        return float("inf")
    return float(np.min(radius[usable]))


def _audit_curvature(geom, report):
    """Requirement 6: sampled full-path 3D curvature >= 14.985 mm.

    The rebuilt path is resampled uniformly along its 3D arc length with a step
    of at most ``CURVATURE_STEP_MM`` (0.02 mm) before the discrete circumradius
    estimate, so rounded primitive joints cannot create spurious curvature.
    """
    points = geom.samples3d_uniform(CURVATURE_STEP_MM)
    minimum = _polyline_min_curvature(points)
    if minimum < MIN_CURVATURE_MM:
        report.add("curvature_violations", "min_3d_radius_below_r15_limit",
                   route_id=geom.route_id,
                   detail=f"min sampled radius {_fmt(minimum)} mm < "
                          f"{MIN_CURVATURE_MM:.3f}")
    return minimum


# ---------------------------------------------------------------------------
# Same physical plane strict 2D audit (requirement 8)
# ---------------------------------------------------------------------------
def _group_flat_parts_by_plane(geoms):
    """Group flat parts by *physical z*, never by layer_id (requirement 9)."""
    groups = OrderedDict()
    for geom in geoms:
        for part in geom.flat_parts:
            key = round(part.z_mm, 9)
            groups.setdefault(key, []).append((geom, part))
    return groups


def _audit_same_plane(geoms, report):
    """Frozen strict 2D pair audit per physical z plane (legal crossings allowed)."""
    validate = _fslw_validate()
    groups = _group_flat_parts_by_plane(geoms)
    block = {"planes": [], "total_violations": 0, "crossings": 0,
             "min_non_crossing_centerline_mm": None}
    for z_mm, entries in sorted(groups.items()):
        prepared = []
        part_ids = []
        for geom, part in entries:
            part_id = f"{geom.route_id}:{part.index}"
            try:
                prepared.append(validate.prepare_route(
                    part.raw_primitives(), route_id=part_id))
                part_ids.append((part_id, geom, part))
            except (ValueError, KeyError, TypeError) as exc:
                report.add("same_plane_violations", "prepare_failed",
                           route_id=geom.route_id,
                           detail=f"z={z_mm} {type(exc).__name__}: {exc}")
        started = time.perf_counter()
        result = validate.audit_route_pairs(
            prepared, clearance=CLEARANCE_MM, sagitta=SAGITTA_MM,
            policy="strict")
        plane_block = {
            "z_mm": _round(z_mm),
            "layer_ids": sorted({int(part.layer_id) for _geom, part in entries}),
            "interface_rows": sorted({str(_geom.record.get("plane"))
                                      for _geom, _part in entries
                                      if int(_part.layer_id) == 1}),
            "parts": len(prepared),
            "routes": len({int(geom.route_id) for geom, _part in entries}),
            "violations": int(len(result.get("violations") or [])),
            "crossings": int(result.get("crossing_count") or 0),
            "crossing_pairs": int(result.get("crossing_pair_count") or 0),
            "min_non_crossing_centerline_mm": _round(
                result.get("min_non_crossing_centerline_mm")),
            "runtime_seconds": round(time.perf_counter() - started, 3),
        }
        block["planes"].append(plane_block)
        block["total_violations"] += plane_block["violations"]
        block["crossings"] += plane_block["crossings"]
        layer_min = result.get("min_non_crossing_centerline_mm")
        if layer_min is not None:
            if block["min_non_crossing_centerline_mm"] is None \
                    or float(layer_min) < block["min_non_crossing_centerline_mm"]:
                block["min_non_crossing_centerline_mm"] = float(layer_min)
        for violation in (result.get("violations") or [])[:50]:
            report.add("same_plane_violations",
                       str(violation.get("kind") or "pair_violation"),
                       route_id=violation.get("route_a"),
                       other_route=violation.get("route_b"),
                       detail=f"z={_round(z_mm)} "
                              f"distance={violation.get('distance_mm')} "
                              f"at ({violation.get('x')},{violation.get('y')})")
    return block


# ---------------------------------------------------------------------------
# True 3D clearance between different physical planes (requirements 7-9)
# ---------------------------------------------------------------------------
def _segments_from_polyline(points):
    if len(points) < 2:
        empty = np.zeros((0, 3))
        return empty, empty, empty
    a = points[:-1]
    b = points[1:]
    return a, b, 0.5 * (a + b)


def _segment_segment_closest(p1, q1, p2, q2):
    """Vectorised closest points between 3D segment pairs (Ericson, clamped)."""
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = np.einsum("ij,ij->i", d1, d1)
    e = np.einsum("ij,ij->i", d2, d2)
    f = np.einsum("ij,ij->i", d2, r)
    c = np.einsum("ij,ij->i", d1, r)
    b = np.einsum("ij,ij->i", d1, d2)
    safe_a = np.where(a > 1e-24, a, 1.0)
    safe_e = np.where(e > 1e-24, e, 1.0)
    denom = a * e - b * b
    parallel = denom <= 1e-18 * safe_a * safe_e
    s_inner = np.where(parallel, 0.0,
                       (b * f - c * e) / np.where(parallel, 1.0, denom))
    s = np.clip(s_inner, 0.0, 1.0)
    t = (b * s + f) / safe_e
    negative = t < 0.0
    positive = t > 1.0
    s = np.where(negative, np.clip(-c / safe_a, 0.0, 1.0),
                 np.where(positive, np.clip((b - c) / safe_a, 0.0, 1.0), s))
    t = np.where(negative, 0.0, np.where(positive, 1.0, np.clip(t, 0.0, 1.0)))
    point_a = p1 + s[:, None] * d1
    point_b = p2 + t[:, None] * d2
    diff = point_a - point_b
    return (np.sqrt(np.einsum("ij,ij->i", diff, diff)), point_a, point_b, s, t)


def _iter_candidate_pairs(tree, query_points, radius, chunk_size=32768):
    total = len(query_points)
    for start in range(0, total, chunk_size):
        stop = min(total, start + chunk_size)
        neighbours = tree.query_ball_point(query_points[start:stop],
                                           r=radius, workers=-1)
        counts = np.fromiter((len(item) for item in neighbours),
                             dtype=np.int64, count=len(neighbours))
        if counts.sum() == 0:
            continue
        query_index = np.repeat(np.arange(start, stop, dtype=np.int64), counts)
        tree_index = np.concatenate([np.asarray(item, dtype=np.int64)
                                     for item in neighbours])
        yield query_index, tree_index


def _build_3d_segment_store(geoms):
    """Flat and transition 3D segments for the true-3D clearance pass."""
    flat = ([], [], [])
    trans = ([], [], [])
    for geom in geoms:
        for part in geom.flat_parts:
            points = part.samples3d(FLAT_LINE_STEP_MM, FLAT_ARC_STEP_MM)
            a, b, _middle = _segments_from_polyline(points)
            if len(a):
                flat[0].append(a)
                flat[1].append(b)
                flat[2].append(np.full(len(a), geom.route_id, dtype=np.int64))
        for part in geom.transitions:
            points = part.samples3d(TRANSITION_STEP_MM)
            a, b, _middle = _segments_from_polyline(points)
            if len(a):
                trans[0].append(a)
                trans[1].append(b)
                trans[2].append(np.full(len(a), geom.route_id, dtype=np.int64))

    def _stack(store):
        if not store[0]:
            empty = np.zeros((0, 3))
            return empty, empty, np.zeros(0, dtype=np.int64)
        return (np.vstack(store[0]), np.vstack(store[1]),
                np.concatenate(store[2]))

    return {"flat_a": _stack(flat), "trans_a": _stack(trans)}


def _audit_true_3d_clearance(geoms, report):
    """Requirement 7: true 3D clearance of every transition versus all parts."""
    block = {
        "enabled": True,
        "transition_vs_flat": {"violations": 0, "min_mm": None},
        "transition_vs_transition": {"violations": 0, "min_mm": None},
        "flat_segments": 0,
        "transition_segments": 0,
    }
    flats = [geom for geom in geoms if geom.flat_parts]
    transitions = [geom for geom in geoms if geom.transitions]
    if not transitions:
        block["enabled"] = False
        return block
    import scipy.spatial as _spatial
    store = _build_3d_segment_store(geoms)
    flat_a, flat_b, flat_route = store["flat_a"]
    trans_a, trans_b, trans_route = store["trans_a"]
    block["flat_segments"] = int(len(flat_a))
    block["transition_segments"] = int(len(trans_a))
    limit = CLEARANCE_MM - CLEARANCE_TOL_MM
    # ---- transition vs flat ------------------------------------------------
    if len(flat_a) and len(trans_a):
        flat_mid = 0.5 * (flat_a + flat_b)
        trans_mid = 0.5 * (trans_a + trans_b)
        tree = _spatial.cKDTree(flat_mid)
        minimum = float("inf")
        radius = QUERY_RADIUS_MM
        for query_index, flat_index in _iter_candidate_pairs(
                tree, trans_mid, radius):
            keep = trans_route[query_index] != flat_route[flat_index]
            if not np.any(keep):
                continue
            query_index = query_index[keep]
            flat_index = flat_index[keep]
            distance, point_a, point_b, _s, _t = _segment_segment_closest(
                trans_a[query_index], trans_b[query_index],
                flat_a[flat_index], flat_b[flat_index])
            minimum = min(minimum, float(np.min(distance)))
            bad = np.flatnonzero(distance < limit)
            block["transition_vs_flat"]["violations"] += int(bad.size)
            for index in bad[:20]:
                report.add(
                    "clearance_violations", "transition_vs_flat",
                    route_id=int(trans_route[query_index[index]]),
                    other_route=int(flat_route[flat_index[index]]),
                    detail=f"distance={distance[index]:.9g} "
                           f"at ({point_a[index, 0]:.9g},"
                           f"{point_a[index, 1]:.9g},"
                           f"{point_a[index, 2]:.9g})")
        block["transition_vs_flat"]["min_mm"] = (
            _round(minimum) if math.isfinite(minimum) else None)
    # ---- transition vs transition -----------------------------------------
    if len(trans_a) > 1:
        trans_mid = 0.5 * (trans_a + trans_b)
        tree = _spatial.cKDTree(trans_mid)
        minimum = float("inf")
        radius = QUERY_RADIUS_MM
        for query_index, other_index in _iter_candidate_pairs(
                tree, trans_mid, radius):
            keep = trans_route[query_index] != trans_route[other_index]
            keep &= query_index < other_index
            if not np.any(keep):
                continue
            query_index = query_index[keep]
            other_index = other_index[keep]
            distance, point_a, point_b, _s, _t = _segment_segment_closest(
                trans_a[query_index], trans_b[query_index],
                trans_a[other_index], trans_b[other_index])
            minimum = min(minimum, float(np.min(distance)))
            bad = np.flatnonzero(distance < limit)
            block["transition_vs_transition"]["violations"] += int(bad.size)
            for index in bad[:20]:
                report.add(
                    "clearance_violations", "transition_vs_transition",
                    route_id=int(trans_route[query_index[index]]),
                    other_route=int(trans_route[other_index[index]]),
                    detail=f"distance={distance[index]:.9g}")
        block["transition_vs_transition"]["min_mm"] = (
            _round(minimum) if math.isfinite(minimum) else None)
    return block


def _cross_plane_flat_clearance(geoms, report):
    """Flat/flat pairs on different physical planes: true 3D distance check.

    Two flats on different planes are pure z translations, so the exact minimum
    3D distance is ``hypot(min 2D distance, |dz|)``.  When the plane gap is above
    the clearance this is provably >= |dz| > 0.08 mm (the layer-stack invariant);
    when the stack is invalid (planes too close) a sampled+refined 2D scan detects
    the actual violations.  ``layer_id`` is never consulted.
    """
    groups = _group_flat_parts_by_plane(geoms)
    plane_keys = sorted(groups)
    block = {"plane_pairs": [], "violations": 0, "min_lower_bound_mm": None,
             "guaranteed_by_plane_gap": True}
    for index_a in range(len(plane_keys)):
        for index_b in range(index_a + 1, len(plane_keys)):
            z_a = plane_keys[index_a]
            z_b = plane_keys[index_b]
            dz = abs(z_b - z_a)
            entry = {"z_a": _round(z_a), "z_b": _round(z_b),
                     "dz_mm": _round(dz),
                     "layer_ids_a": sorted({int(part.layer_id)
                                            for _g, part in groups[z_a]}),
                     "layer_ids_b": sorted({int(part.layer_id)
                                            for _g, part in groups[z_b]}),
                     "guaranteed": False, "min_3d_mm": None,
                     "violations": 0}
            if dz > CLEARANCE_MM + CLEARANCE_TOL_MM:
                entry["guaranteed"] = True
                entry["min_3d_mm"] = _round(dz)
                if block["min_lower_bound_mm"] is None \
                        or dz < block["min_lower_bound_mm"]:
                    block["min_lower_bound_mm"] = dz
            else:
                min_2d, violations = _min_flat_pair_2d_distance(
                    groups[z_a], groups[z_b], report)
                entry["min_3d_mm"] = (
                    _round(math.hypot(min_2d, dz))
                    if min_2d is not None else _round(dz))
                entry["violations"] = violations
                block["violations"] += violations
                block["guaranteed_by_plane_gap"] = False
                if block["min_lower_bound_mm"] is None \
                        or entry["min_3d_mm"] < block["min_lower_bound_mm"]:
                    block["min_lower_bound_mm"] = entry["min_3d_mm"]
            block["plane_pairs"].append(entry)
    return block


def _polyline_segments_2d(part, line_step=FLAT_LINE_STEP_MM,
                          arc_step=FLAT_ARC_STEP_MM):
    """2D chords of one flat part plus their midpoints."""
    points = part.samples3d(line_step, arc_step)
    if len(points) < 2:
        empty = np.zeros((0, 2))
        return empty, empty, empty
    xy = points[:, :2]
    a = xy[:-1]
    b = xy[1:]
    return a, b, 0.5 * (a + b)


def _segment_segment_distance_2d(a1, b1, a2, b2):
    """Exact 2D distance between chord pairs (3D helper with z=0)."""
    zero1 = np.zeros((len(a1), 1))
    zero2 = np.zeros((len(a2), 1))
    p1 = np.hstack([a1, zero1])
    q1 = np.hstack([b1, zero1])
    p2 = np.hstack([a2, zero2])
    q2 = np.hstack([b2, zero2])
    distance, _pa, _pb, _s, _t = _segment_segment_closest(p1, q1, p2, q2)
    return distance


def _min_flat_pair_2d_distance(entries_a, entries_b, report):
    """Minimum 2D distance between two groups of flat parts on distinct planes.

    Both parts are pure z translations of their 2D centre-lines, so the true 3D
    distance of a point pair is ``hypot(d2d, dz)``.  The scan uses the chord
    polylines at the same fine sampling as the clearance pass plus exact chord
    distance refinement; it is only used when the layer stack violates the
    plane-spacing invariant (otherwise ``|dz|`` alone already proves >= 0.08).
    """
    import scipy.spatial as _spatial

    def _collect(entries):
        arrays_a, arrays_b, owners = [], [], []
        for geom, part in entries:
            a, b, _middle = _polyline_segments_2d(part)
            if len(a):
                arrays_a.append(a)
                arrays_b.append(b)
                owners.extend([(geom, part)] * len(a))
        if not arrays_a:
            return None
        return (np.vstack(arrays_a), np.vstack(arrays_b), owners)

    group_a = _collect(entries_a)
    group_b = _collect(entries_b)
    if group_a is None or group_b is None:
        return None, 0
    a_a, b_a, owners_a = group_a
    a_b, b_b, owners_b = group_b
    middle_b = 0.5 * (a_b + b_b)
    tree = _spatial.cKDTree(middle_b)
    middle_a = 0.5 * (a_a + b_a)
    radius = (CLEARANCE_MM - CLEARANCE_TOL_MM) + FLAT_LINE_STEP_MM
    limit = CLEARANCE_MM - CLEARANCE_TOL_MM
    minimum = None
    violations = 0
    for a_index, neighbours in enumerate(
            tree.query_ball_point(middle_a, r=radius, workers=-1)):
        if not neighbours:
            continue
        geom_a, part_a = owners_a[a_index]
        candidates = [index for index in neighbours
                      if owners_b[index][0].route_id != geom_a.route_id]
        if not candidates:
            continue
        candidates = np.asarray(candidates, dtype=np.int64)
        distances = _segment_segment_distance_2d(
            a_a[a_index][None, :], b_a[a_index][None, :],
            a_b[candidates], b_b[candidates])
        candidate_minimum = float(np.min(distances))
        if minimum is None or candidate_minimum < minimum:
            minimum = candidate_minimum
        for offset in np.flatnonzero(distances < limit)[:5]:
            geom_b, part_b = owners_b[int(candidates[offset])]
            violations += 1
            report.add(
                "clearance_violations", "flat_cross_plane_too_close",
                route_id=geom_a.route_id, other_route=geom_b.route_id,
                detail=f"z={_round(part_a.z_mm)} vs {_round(part_b.z_mm)} "
                       f"2d_distance={distances[offset]:.9g}")
    return minimum, violations


def _point_to_primitive_distance_2d(point, primitive):
    """Exact 2D distance from a point to a finite line/arc primitive."""
    if primitive.kind == "line":
        p0 = primitive.p0
        ux = primitive.p1[0] - p0[0]
        uy = primitive.p1[1] - p0[1]
        wx = point[0] - p0[0]
        wy = point[1] - p0[1]
        projection = wx * ux + wy * uy
        if projection <= 0.0:
            return math.hypot(wx, wy)
        denominator = primitive.length * primitive.length
        if projection >= denominator:
            return math.hypot(point[0] - primitive.p1[0],
                              point[1] - primitive.p1[1])
        t = projection / denominator
        return math.hypot(point[0] - (p0[0] + t * ux),
                          point[1] - (p0[1] + t * uy))
    center = primitive.center
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    angle = math.atan2(dy, dx)
    delta = ((angle - primitive.start_angle) if primitive.sweep > 0
             else (primitive.start_angle - angle)) % (2.0 * math.pi)
    inside = delta <= abs(primitive.sweep) + 1e-12 \
        or 2.0 * math.pi - delta < 1e-12
    if inside:
        return abs(math.hypot(dx, dy) - primitive.radius)
    return min(math.hypot(point[0] - primitive.p0[0],
                          point[1] - primitive.p0[1]),
               math.hypot(point[0] - primitive.p1[0],
                          point[1] - primitive.p1[1]))


# ---------------------------------------------------------------------------
# Self clearance (true 3D)
# ---------------------------------------------------------------------------
def _audit_self_clearance(geom, report):
    """Same-route non-adjacent (path separation > 1 mm) true 3D clearance."""
    points = geom.samples3d(FLAT_LINE_STEP_MM, FLAT_ARC_STEP_MM,
                            TRANSITION_STEP_MM)
    if len(points) < 2:
        return float("inf")
    a, b, middle = _segments_from_polyline(points)
    lengths = np.linalg.norm(b - a, axis=1)
    arc_start = np.zeros(len(lengths))
    if len(lengths):
        arc_start[1:] = np.cumsum(lengths)[:-1]
    arc_end = arc_start + lengths
    import scipy.spatial as _spatial
    tree = _spatial.cKDTree(middle)
    pairs = tree.query_pairs(QUERY_RADIUS_MM, output_type="ndarray")
    if pairs.size == 0:
        return float("inf")
    first = pairs[:, 0]
    second = pairs[:, 1]
    span = np.maximum(arc_end[first], arc_end[second]) - np.minimum(
        arc_start[first], arc_start[second])
    candidates = np.flatnonzero(span > SELF_PATH_SEPARATION_MM)
    if candidates.size == 0:
        return float("inf")
    first = first[candidates]
    second = second[candidates]
    distance, point_first, point_second, s_param, t_param = \
        _segment_segment_closest(a[first], b[first], a[second], b[second])
    s_first = arc_start[first] + s_param * lengths[first]
    s_second = arc_start[second] + t_param * lengths[second]
    delta = np.abs(s_first - s_second)
    minimum_possible = np.where(
        arc_start[first] <= arc_start[second],
        arc_start[second] - arc_end[first],
        arc_start[first] - arc_end[second])
    genuine = (delta > SELF_PATH_SEPARATION_MM) | (
        minimum_possible > SELF_PATH_SEPARATION_MM)
    limit = CLEARANCE_MM - CLEARANCE_TOL_MM
    bad = np.flatnonzero(genuine & (distance < limit))
    minimum = float(np.min(distance)) if distance.size else float("inf")
    for index in bad[:5]:
        report.add("self_clearance_violations", "self_clearance",
                   route_id=geom.route_id,
                   detail=f"distance={distance[index]:.9g} at "
                          f"({point_first[index, 0]:.9g},"
                          f"{point_first[index, 1]:.9g},"
                          f"{point_first[index, 2]:.9g})")
    if bad.size > 5:
        report.add("self_clearance_violations", "self_clearance",
                   route_id=geom.route_id, detail=f"{bad.size} violating pairs")
    return minimum


# ---------------------------------------------------------------------------
# Route level accumulation
# ---------------------------------------------------------------------------
def _new_geometry_stats():
    return {
        "flats": 0, "transitions": 0, "flat_arcs": 0, "flat_lines": 0,
        "transition_radius_values": set(), "flat_arc_radius_values": set(),
        "back_to_back_transitions": 0,
        "transition_pairs": Counter(),
        "interface_transitions": 0, "intermediate_transitions": 0,
    }


def _accumulate_geometry_stats(stats, geom):
    for part in geom.flat_parts:
        stats["flats"] += 1
        for primitive in part.primitives:
            if primitive.kind == "arc":
                stats["flat_arcs"] += 1
                stats["flat_arc_radius_values"].add(round(primitive.radius, 9))
            else:
                stats["flat_lines"] += 1
    for part in geom.transitions:
        stats["transitions"] += 1
        stats["transition_radius_values"].add(round(part.radius, 9))
        stats["transition_pairs"][f"{part.from_layer}->{part.to_layer}"] += 1
        if INTERFACE_LAYER_ID in (part.from_layer, part.to_layer):
            stats["interface_transitions"] += 1
        if part.from_layer != INTERFACE_LAYER_ID \
                and part.to_layer != INTERFACE_LAYER_ID:
            stats["intermediate_transitions"] += 1
    stats["back_to_back_transitions"] += int(
        geom.record.get("_back_to_back_transitions") or 0)


# ---------------------------------------------------------------------------
# Report assembly / acceptance semantics
# ---------------------------------------------------------------------------
def _build_items(stack, port_model, checks, counts, stats, geometry_pass,
                 geometry_executed, formal_acceptance, status, exit_code,
                 allow_exploratory):
    def status_of(ok):
        return "pass" if ok else "fail"

    items = []
    items.append({
        "item": "layer_stack_L1_interface",
        "requirement": 1,
        "status": status_of(stack.valid),
        "detail": ("L1 is the interface layer with rows z1=0.0 / z2=0.5"
                   if stack.valid else f"invalid stack: {stack.errors[:5]}"),
        "metrics": {
            "provenance": stack.provenance,
            "confirmed": stack.confirmed,
            "height_defined": stack.height_defined,
            "planes": [dict(entry) for entry in stack.planes],
        },
    })
    rows_ok = bool(port_model.get("ok"))
    items.append({
        "item": "port_rows_real_3d_separation",
        "requirement": 2,
        "status": status_of(rows_ok),
        "detail": (f"{port_model.get('pairs_checked')} same-XY row pairs, "
                   f"min 3D distance {port_model.get('min_3d_distance_mm')} mm"),
        "metrics": port_model,
    })
    ports = checks.get("route_ports") or {}
    items.append({
        "item": "routes_start_end_on_L1_ports",
        "requirement": 3,
        "status": status_of(ports.get("ok", False)),
        "detail": (f"routed={ports.get('routed_routes')}, "
                   f"identity_checked={ports.get('identity_checked')}, "
                   f"port_errors={counts.get('port_errors')}"),
        "metrics": ports,
    })
    transitions = checks.get("transitions") or {}
    items.append({
        "item": "transitions_from_interface",
        "requirement": 4,
        "status": status_of(transitions.get("interface_transitions_ok", False)),
        "detail": (f"interface transitions={transitions.get('interface_transitions')}, "
                   f"geometry/curvature/clearance violations="
                   f"{counts.get('geometry_errors') + counts.get('curvature_violations')}"),
        "metrics": transitions,
    })
    items.append({
        "item": "transitions_intermediate_multi",
        "requirement": 5,
        "status": status_of(transitions.get("intermediate_transitions_ok", False)),
        "detail": (f"intermediate transitions="
                   f"{transitions.get('intermediate_transitions')}, "
                   f"multi-transition routes={stats.get('multi_transition_routes')}, "
                   f"back-to-back={transitions.get('back_to_back_transitions')}"),
        "metrics": transitions,
    })
    curvature = checks.get("curvature") or {}
    items.append({
        "item": "curvature_3d_min_radius",
        "requirement": 6,
        "status": status_of(bool(curvature.get("ok"))),
        "detail": (f"min sampled 3D radius="
                   f"{curvature.get('min_curvature_radius_mm')} mm "
                   f"(limit {MIN_CURVATURE_MM}), "
                   f"analytic violations={counts.get('curvature_violations')}"),
        "metrics": curvature,
    })
    clearance = checks.get("clearance") or {}
    items.append({
        "item": "transition_vs_L1_clearance",
        "requirement": 7,
        "status": status_of(bool(clearance.get("transition_clearance_ok"))),
        "detail": (f"transition-vs-flat min="
                   f"{clearance.get('transition_vs_flat_min_mm')} mm, "
                   f"transition-vs-transition min="
                   f"{clearance.get('transition_vs_transition_min_mm')} mm, "
                   f"violations={counts.get('clearance_violations')}"),
        "metrics": clearance,
    })
    items.append({
        "item": "same_plane_strict_and_cross_plane",
        "requirement": 8,
        "status": status_of(bool(clearance.get("plane_rules_ok"))),
        "detail": (f"same-plane strict violations="
                   f"{counts.get('same_plane_violations')}, cross-plane "
                   f"violations={clearance.get('cross_plane_violations')}, "
                   f"min 3D clearance={stats.get('min_3d_clearance_mm')} mm"),
        "metrics": clearance,
    })
    layer_id_block = checks.get("layer_id_not_z") or {}
    items.append({
        "item": "layer_id_is_not_a_z_coordinate",
        "requirement": 9,
        "status": status_of(bool(layer_id_block.get("ok"))),
        "detail": (f"{len(layer_id_block.get('physical_planes') or [])} distinct "
                   f"physical planes; same layer id in "
                   f"{layer_id_block.get('same_layer_different_z_groups')} "
                   f"distinct-z groups; different layer ids sharing one physical "
                   f"plane: {layer_id_block.get('different_layer_same_z_groups')}"),
        "metrics": layer_id_block,
    })
    acceptance = checks.get("acceptance") or {}
    exploratory_pass = acceptance.get("exploratory_pass")
    expected_formal = bool(stack.valid and stack.confirmed and geometry_pass)
    semantics_ok = bool(formal_acceptance) == expected_formal
    if formal_acceptance:
        refusal_note = "formal acceptance granted (valid + confirmed + geometry pass)"
    elif not stack.valid:
        refusal_note = ("formal acceptance refused: invalid layer stack "
                        f"({stack.errors[:3]})")
    elif not stack.confirmed:
        refusal_note = ("formal acceptance refused: layer heights are not "
                        f"supervisor-confirmed (provenance={stack.provenance!r}); "
                        "exploratory only")
    else:
        refusal_note = "formal acceptance refused: geometry checks failed"
    items.append({
        "item": "formal_acceptance",
        "requirement": 10,
        "status": "pass" if semantics_ok else "fail",
        "detail": (f"{refusal_note}; formal_acceptance={formal_acceptance}, "
                   f"status={status}, exit_code={exit_code}, "
                   f"allow_exploratory={allow_exploratory}, "
                   f"exploratory_pass={exploratory_pass}, "
                   f"geometry_executed={geometry_executed}"),
        "metrics": acceptance,
    })
    return items


def _acceptance_verdict(stack, geometry_executed, geometry_pass,
                        allow_exploratory):
    """Return ``(formal_acceptance, status, exit_code, exploratory_pass)``."""
    exploratory_pass = bool(geometry_pass) if geometry_executed else None
    formal = bool(stack.valid and stack.confirmed and geometry_pass)
    if not stack.valid:
        status = "invalid_stack"
    elif not stack.confirmed:
        status = "exploratory_only"
    elif geometry_pass:
        status = "confirmed_pass"
    else:
        status = "failed"
    if formal:
        exit_code = 0
    elif not stack.valid or not geometry_executed:
        exit_code = 2
    elif geometry_pass:
        exit_code = 0 if allow_exploratory else 3
    else:
        exit_code = 1
    return formal, status, exit_code, exploratory_pass


# ---------------------------------------------------------------------------
# Top-level validation API
# ---------------------------------------------------------------------------
def validate_payload(payload, *, layer_stack_raw=None, allow_exploratory=False,
                     routes_file="<memory>", run_frozen_2d=True,
                     write=None):
    """Validate one L3D routes payload; returns the JSON-ready report dict."""
    started = time.perf_counter()
    report = _Report()
    # ---- layer stack selection -------------------------------------------
    embedded_raw = payload.get("layer_stack") if isinstance(payload, dict) else None
    if layer_stack_raw is not None:
        try:
            stack_raw, stack_source = _load_layer_stack_arg(layer_stack_raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report.add("contract_errors", "layer_stack_unreadable",
                       detail=f"{type(exc).__name__}: {exc}")
            stack_raw, stack_source = None, "cli_unreadable"
    elif embedded_raw is not None:
        stack_raw, stack_source = embedded_raw, "embedded"
    else:
        stack_raw, stack_source = None, "missing"
    stack = parse_layer_stack(stack_raw, source=stack_source) \
        if stack_raw is not None else _LayerStack()
    if stack_raw is None:
        stack.errors.append("layer_stack_missing")
        stack.valid = False
    if layer_stack_raw is not None and embedded_raw is not None:
        try:
            embedded_stack = parse_layer_stack(embedded_raw, source="embedded")
            if embedded_stack.to_dict() != stack.to_dict():
                report.warn("embedded layer_stack differs from --layer-stack; "
                            "the --layer-stack value is used")
        except (ValueError, KeyError, TypeError):
            report.warn("embedded layer_stack could not be parsed for comparison")
    # ---- payload contract -------------------------------------------------
    if not isinstance(payload, dict):
        report.add("contract_errors", "payload_not_a_mapping")
        payload = {}
    schema = payload.get("schema")
    if schema is not None and schema != ROUTES_SCHEMA:
        report.add("contract_errors", "routes_schema_mismatch",
                   detail=f"{schema!r} != {ROUTES_SCHEMA!r}")
    topology = payload.get("topology")
    if topology is not None and topology != "V2":
        report.add("contract_errors", "topology_mismatch",
                   detail=repr(topology))
    csv_sha = payload.get("csv_sha256")
    if csv_sha is not None:
        try:
            expected_sha = _fslw_ports().EXPECTED_SHA256["V2"]
        except (KeyError, TypeError):
            expected_sha = None
        if expected_sha is not None and str(csv_sha).lower() != expected_sha.lower():
            report.add("port_errors", "csv_sha256_mismatch",
                       detail=f"{csv_sha!r} != {expected_sha!r}")
    process = payload.get("process")
    if isinstance(process, dict):
        try:
            process_radius = float(process.get("radius_mm"))
            if abs(process_radius - RADIUS_MM) > RADIUS_TOL:
                report.add("contract_errors", "process_radius_not_r15",
                           detail=repr(process.get("radius_mm")))
        except (TypeError, ValueError):
            report.add("contract_errors", "process_radius_invalid",
                       detail=repr(process.get("radius_mm")))
        try:
            process_clearance = float(process.get("clearance_mm"))
            if abs(process_clearance - CLEARANCE_MM) > 1e-9:
                report.add("contract_errors", "process_clearance_mismatch",
                           detail=repr(process.get("clearance_mm")))
        except (TypeError, ValueError):
            report.warn("process clearance missing")
    else:
        report.warn("payload has no process record")
    routes = payload.get("routes")
    if not isinstance(routes, list):
        report.add("contract_errors", "routes_missing")
        routes = []
    declared_count = payload.get("route_count")
    if declared_count is not None:
        try:
            if int(declared_count) != len(routes):
                report.add("contract_errors", "route_count_mismatch",
                           detail=f"declared={declared_count} "
                                  f"actual={len(routes)}")
        except (TypeError, ValueError):
            report.add("contract_errors", "route_count_invalid",
                       detail=repr(declared_count))
    identity = _port_identity()
    # ---- requirement 2: port-row model self-check ------------------------
    port_model = _check_port_row_model(report)
    # ---- routes ----------------------------------------------------------
    routed_records = []
    failed_records = []
    route_ids = []
    for record in routes:
        if not isinstance(record, dict):
            report.add("contract_errors", "route_not_a_mapping")
            continue
        route_ids.append(record.get("route_id"))
        if record.get("status") == "routed":
            routed_records.append(record)
        else:
            failed_records.append(record)
    duplicates = sorted({value for value in route_ids if route_ids.count(value) > 1})
    if duplicates:
        report.add("other_errors", "duplicate_route_id",
                   detail=str(duplicates[:20]))
    port_usage = Counter()
    geoms = []
    min_curvature = float("inf")
    curvature_checked = 0
    geometry_stats = _new_geometry_stats()
    port_block = {"routed_routes": 0, "failed_routes": len(failed_records),
                  "checked": 0, "identity_checked": bool(identity.get("available")),
                  "ok": True}
    if not identity.get("available"):
        report.warn(f"V2 port identity unavailable: {identity.get('error')}")
    for record in routed_records:
        try:
            geom = _parse_route(record, stack, identity, report)
        except _DataError as exc:
            report.add("geometry_errors", "route_unparseable",
                       route_id=record.get("route_id"), detail=str(exc))
            continue
        geoms.append(geom)
        port_block["routed_routes"] += 1
        port_block["checked"] += 1
        # port usage (identity/duplicate detection)
        plane_identity = identity.get("planes", {}).get(geom.plane) or {}
        csv_record = (plane_identity.get("routes") or {}).get(geom.route_id)
        if csv_record is not None:
            for key in ("source_endpoint", "target_endpoint"):
                endpoint = csv_record.get(key)
                if endpoint is not None:
                    port_usage[endpoint] += 1
        # curvature
        try:
            minimum = _audit_curvature(geom, report)
        except _DataError:
            minimum = float("inf")
        min_curvature = min(min_curvature, minimum)
        curvature_checked += 1
        _accumulate_geometry_stats(geometry_stats, geom)
    for record in failed_records:
        try:
            _check_failed_record(record, identity, stack, report)
        except (ValueError, KeyError, TypeError) as exc:
            report.add("contract_errors", "failed_record_unparseable",
                       route_id=record.get("route_id"), detail=str(exc))
        # failed records still carry their CSV port identities: count them so the
        # port-usage coverage check sees all 1024 connections
        if identity.get("available"):
            plane = record.get("plane")
            route_id_value = record.get("route_id")
            try:
                route_id_int = int(route_id_value)
            except (TypeError, ValueError):
                route_id_int = None
            if plane in identity["planes"] and route_id_int is not None:
                csv_record = identity["planes"][plane]["routes"].get(route_id_int)
                if csv_record is not None:
                    for key in ("source_endpoint", "target_endpoint"):
                        endpoint = csv_record.get(key)
                        if endpoint is not None:
                            port_usage[endpoint] += 1
    duplicate_ports = [endpoint for endpoint, count in port_usage.items()
                       if count > 1]
    if duplicate_ports:
        report.add("port_errors", "duplicate_port_usage",
                   detail=str(sorted(duplicate_ports)[:20]))
    if identity.get("available") and len(routes) == 1024:
        expected_ports = 2048
        if len(port_usage) != expected_ports:
            report.add("port_errors", "port_coverage_incomplete",
                       detail=f"{len(port_usage)} != {expected_ports}")
    port_block["unique_ports_used"] = len(port_usage)
    port_block["ok"] = (report.counts["port_errors"] == 0)
    # ---- requirement 8: same physical plane strict 2D audit --------------
    same_plane = _audit_same_plane(geoms, report) if run_frozen_2d else {
        "planes": [], "total_violations": 0, "crossings": 0,
        "min_non_crossing_centerline_mm": None, "enabled": False}
    # ---- requirements 7/8/9: true 3D clearance ---------------------------
    transition_clearance = _audit_true_3d_clearance(geoms, report)
    cross_plane = _cross_plane_flat_clearance(geoms, report)
    self_min = float("inf")
    for geom in geoms:
        try:
            self_min = min(self_min, _audit_self_clearance(geom, report))
        except (ValueError, FloatingPointError):
            report.add("self_clearance_violations", "self_clearance_failed",
                       route_id=geom.route_id)
    # ---- requirement 9: layer_id is never a z coordinate ------------------
    layer_id_block = _layer_id_usage_block(geoms, stack)
    # ---- aggregate statistics -------------------------------------------
    layers_used_histogram = Counter(
        "->".join(str(value) for value in sorted(
            {part.layer_id for part in geom.flat_parts}))
        for geom in geoms)
    transitions_histogram = Counter(len(geom.transitions) for geom in geoms)
    multi_transition = sum(1 for geom in geoms if len(geom.transitions) > 1)
    lifted = sum(1 for geom in geoms if geom.transitions)
    flat_routes = len(geoms) - lifted
    transition_pairs = dict(geometry_stats["transition_pairs"])
    # declared statistics / counts (recorded but never trusted)
    declared_statistics = payload.get("statistics") \
        if isinstance(payload.get("statistics"), dict) else {}
    stats = {
        "routed": len(routed_records),
        "failed": len(failed_records),
        "total": len(routes),
        "lifted": lifted,
        "flat_routes": flat_routes,
        "multi_transition_routes": multi_transition,
        "transition_count": geometry_stats["transitions"],
        "interface_transition_count": geometry_stats["interface_transitions"],
        "intermediate_transition_count":
            geometry_stats["intermediate_transitions"],
        "back_to_back_transition_count":
            geometry_stats["back_to_back_transitions"],
        "transition_pairs": transition_pairs,
        "layers_used_histogram": dict(layers_used_histogram),
        "transitions_histogram": {str(key): value
                                  for key, value in sorted(
                                      transitions_histogram.items())},
        "flat_parts": geometry_stats["flats"],
        "flat_lines": geometry_stats["flat_lines"],
        "flat_arcs": geometry_stats["flat_arcs"],
        "flat_arc_radius_values": sorted(geometry_stats["flat_arc_radius_values"]),
        "transition_radius_values":
            sorted(geometry_stats["transition_radius_values"]),
        "total_length_mm": _round(sum(geom.total_length for geom in geoms)),
        "xy_length_mm": _round(sum(geom.xy_length for geom in geoms)),
        "z_span_max_mm": _round(max((geom.z_span for geom in geoms), default=0.0)),
        "duplicate_route_ids": duplicates,
        "min_curvature_radius_mm": (
            None if not math.isfinite(min_curvature)
            else _round(min_curvature)),
        "curvature_routes_checked": curvature_checked,
        "same_plane_crossings": int(same_plane.get("crossings") or 0),
        "physical_planes": layer_id_block["physical_planes"],
        "min_self_clearance_mm": (
            None if not math.isfinite(self_min) else _round(self_min)),
        "declared_statistics": declared_statistics,
    }
    # ---- min 3D clearance -------------------------------------------------
    components = []
    lower_bounds = []
    same_plane_min = same_plane.get("min_non_crossing_centerline_mm")
    if same_plane_min is not None:
        components.append(float(same_plane_min))
    elif same_plane.get("planes"):
        lower_bounds.append(CLEARANCE_MM + 2.0 * SAGITTA_MM)
    if transition_clearance.get("transition_vs_flat", {}).get("min_mm") is not None:
        components.append(float(transition_clearance["transition_vs_flat"]["min_mm"]))
    elif transition_clearance.get("transition_segments"):
        lower_bounds.append(QUERY_RADIUS_MM - 0.05 - 0.01)
    if transition_clearance.get("transition_vs_transition", {}).get("min_mm") \
            is not None:
        components.append(float(
            transition_clearance["transition_vs_transition"]["min_mm"]))
    elif transition_clearance.get("transition_segments", 0) > 1:
        lower_bounds.append(QUERY_RADIUS_MM - 0.02)
    cross_min = cross_plane.get("min_lower_bound_mm")
    if cross_min is not None:
        lower_bounds.append(float(cross_min))
    if components:
        min_3d = min(components)
        min_3d_bound = "measured"
    elif lower_bounds:
        min_3d = min(lower_bounds)
        min_3d_bound = "lower_bound"
    else:
        min_3d = None
        min_3d_bound = "unknown"
    stats["min_3d_clearance_mm"] = _round(min_3d)
    stats["min_3d_clearance_bound"] = min_3d_bound
    stats["sampling"] = {
        "curvature_step_mm": CURVATURE_STEP_MM,
        "transition_step_mm": TRANSITION_STEP_MM,
        "flat_line_step_mm": FLAT_LINE_STEP_MM,
        "flat_arc_step_mm": FLAT_ARC_STEP_MM,
        "clearance_query_radius_mm": QUERY_RADIUS_MM,
        "curvature_limit_mm": MIN_CURVATURE_MM,
        "clearance_limit_mm": CLEARANCE_MM,
        "clearance_tolerance_mm": CLEARANCE_TOL_MM,
    }
    # ---- geometry pass / acceptance --------------------------------------
    geometry_executed = bool(geoms) and stack.height_defined
    counts = _finalise_counts(report)
    curvature_ok = (
        (not report.counts["curvature_violations"])
        and (stats["min_curvature_radius_mm"] is None
             or stats["min_curvature_radius_mm"] >= MIN_CURVATURE_MM))
    clearance_ok = (
        (not report.counts["clearance_violations"])
        and (not report.counts["same_plane_violations"])
        and (min_3d is None or min_3d >= CLEARANCE_MM - CLEARANCE_TOL_MM))
    geometry_pass = bool(
        geometry_executed
        and not report.total
        and curvature_ok and clearance_ok
        and port_block["ok"])
    formal_acceptance, status, exit_code, exploratory_pass = _acceptance_verdict(
        stack, geometry_executed, geometry_pass, allow_exploratory)
    checks = {
        "layer_stack": stack.to_dict(),
        "port_model": port_model,
        "route_ports": port_block,
        "transitions": {
            "interface_transitions": geometry_stats["interface_transitions"],
            "intermediate_transitions":
                geometry_stats["intermediate_transitions"],
            "back_to_back_transitions":
                geometry_stats["back_to_back_transitions"],
            "transition_pairs": transition_pairs,
            "transition_radius_values":
                sorted(geometry_stats["transition_radius_values"]),
            "interface_transitions_ok": True,
            "intermediate_transitions_ok": True,
        },
        "curvature": {
            "min_curvature_radius_mm": stats["min_curvature_radius_mm"],
            "limit_mm": MIN_CURVATURE_MM,
            "sampled": stats["curvature_routes_checked"],
            "flat_arc_radius_values": stats["flat_arc_radius_values"],
            "transition_radius_values": stats["transition_radius_values"],
            "violations": report.counts["curvature_violations"],
            "ok": curvature_ok,
        },
        "clearance": {
            "same_plane": same_plane,
            "transition_vs_flat": transition_clearance.get(
                "transition_vs_flat"),
            "transition_vs_transition": transition_clearance.get(
                "transition_vs_transition"),
            "transition_vs_flat_min_mm": transition_clearance.get(
                "transition_vs_flat", {}).get("min_mm"),
            "transition_vs_transition_min_mm": transition_clearance.get(
                "transition_vs_transition", {}).get("min_mm"),
            "cross_plane": cross_plane,
            "cross_plane_violations": cross_plane.get("violations", 0),
            "min_3d_clearance_mm": stats["min_3d_clearance_mm"],
            "min_3d_clearance_bound": stats["min_3d_clearance_bound"],
            "transition_clearance_ok": (
                transition_clearance.get("transition_vs_flat", {}
                                         ).get("violations", 0) == 0
                and transition_clearance.get("transition_vs_transition", {}
                                             ).get("violations", 0) == 0),
            "plane_rules_ok": (
                report.counts["same_plane_violations"] == 0
                and cross_plane.get("violations", 0) == 0),
            "ok": clearance_ok,
        },
        "layer_id_not_z": layer_id_block,
        "self_clearance": {
            "min_mm": stats["min_self_clearance_mm"],
            "violations": report.counts["self_clearance_violations"],
            "ok": report.counts["self_clearance_violations"] == 0,
        },
        "acceptance": {
            "formal_acceptance": formal_acceptance,
            "status": status,
            "exit_code": exit_code,
            "exploratory_pass": exploratory_pass,
            "allow_exploratory": bool(allow_exploratory),
            "geometry_executed": bool(geometry_executed),
            "geometry_pass": bool(geometry_pass),
            "provenance": stack.provenance,
            "stack_valid": bool(stack.valid),
            "stack_confirmed": bool(stack.confirmed),
            "reported_router_formal_flag": stack.reported_formal_flag,
            "note": ("formal process acceptance requires provenance='confirmed' "
                     "and a valid layer stack; unconfirmed heights are "
                     "exploratory only"),
        },
    }
    # fix the two transition sub-verdicts from the actual counters
    checks["transitions"]["interface_transitions_ok"] = (
        report.counts["geometry_errors"] == 0
        and report.counts["curvature_violations"] == 0)
    checks["transitions"]["intermediate_transitions_ok"] = (
        report.counts["geometry_errors"] == 0
        and report.counts["curvature_violations"] == 0)
    items = _build_items(stack, port_model, checks, counts, stats,
                         geometry_pass, geometry_executed, formal_acceptance,
                         status, exit_code, allow_exploratory)
    report_dict = {
        "schema": REPORT_SCHEMA,
        "validator": "four_side_1024.l3d.validate_l3d",
        "routes_file": str(routes_file),
        "layer_stack_source": stack_source,
        "layer_stack": stack.to_dict(),
        "formal_acceptance": bool(formal_acceptance),
        "exploratory_pass": exploratory_pass,
        "geometry_pass": bool(geometry_pass),
        "geometry_executed": bool(geometry_executed),
        "status": status,
        "exit_code": int(exit_code),
        "allow_exploratory": bool(allow_exploratory),
        "counts": counts,
        "stats": stats,
        "checks": checks,
        "items": items,
        "violations": report.violations,
        "violation_kinds": dict(report.kind_counts),
        "warnings": report.warnings,
        "runtime_seconds": None,
    }
    report_dict["runtime_seconds"] = round(time.perf_counter() - started, 3)
    if write is not None:
        write_json(Path(write), report_dict)
    return report_dict


def _layer_id_usage_block(geoms, stack):
    """Requirement 9 evidence: physical planes / same-layer-different-z groups."""
    groups = _group_flat_parts_by_plane(geoms)
    physical_planes = []
    for z_mm, entries in sorted(groups.items()):
        layer_ids = sorted({int(part.layer_id) for _geom, part in entries})
        interface_rows = sorted({str(geom.record.get("plane"))
                                 for geom, part in entries
                                 if int(part.layer_id) == INTERFACE_LAYER_ID})
        physical_planes.append({
            "z_mm": _round(z_mm),
            "layer_ids": layer_ids,
            "interface_rows": interface_rows,
            "parts": len(entries),
            "routes": len({int(geom.route_id) for geom, _part in entries}),
            "label": ", ".join(f"L{layer_id}" for layer_id in layer_ids),
        })
    same_layer_different_z = Counter()
    for z_mm, entries in groups.items():
        for layer_id in {int(part.layer_id) for _geom, part in entries}:
            same_layer_different_z[layer_id] += 1
    different_layer_same_z = sum(
        1 for entry in physical_planes if len(entry["layer_ids"]) > 1)
    # cross-check the stack's own plane table against the observed planes
    stack_plane_table = [dict(entry) for entry in stack.planes]
    observed = {entry["z_mm"] for entry in physical_planes}
    declared = {_round(entry["z_mm"]) for entry in stack_plane_table}
    ok = True
    if stack.valid and not observed.issubset(declared):
        ok = False
    return {
        "ok": bool(ok and not different_layer_same_z) if stack.valid else bool(ok),
        "physical_planes": physical_planes,
        "stack_physical_planes": stack_plane_table,
        "same_layer_different_z_groups": dict(
            (f"L{layer_id}", count)
            for layer_id, count in sorted(same_layer_different_z.items())),
        "different_layer_same_z_groups": different_layer_same_z,
        "note": ("planes are grouped by physical z, never by layer_id; "
                 "L1's two rows share layer_id=1 but are distinct planes"),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def validate_file(routes_path, *, layer_stack_raw=None,
                  allow_exploratory=False, out=None, run_frozen_2d=True):
    """Load an L3D routes JSON, validate it, optionally write the report."""
    routes_path = Path(routes_path)
    started = time.perf_counter()
    try:
        payload = json.loads(routes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = _Report()
        report.add("contract_errors", "routes_unreadable",
                   detail=f"{type(exc).__name__}: {exc}")
        counts = _finalise_counts(report)
        result = {
            "schema": REPORT_SCHEMA,
            "validator": "four_side_1024.l3d.validate_l3d",
            "routes_file": str(routes_path),
            "status": "invalid_stack",
            "formal_acceptance": False,
            "exploratory_pass": None,
            "geometry_pass": False,
            "geometry_executed": False,
            "exit_code": 2,
            "counts": counts,
            "violations": report.violations,
            "items": [],
            "runtime_seconds": round(time.perf_counter() - started, 3),
        }
        if out is not None:
            write_json(out, result)
        return result
    result = validate_payload(
        payload, layer_stack_raw=layer_stack_raw,
        allow_exploratory=allow_exploratory, routes_file=routes_path,
        run_frozen_2d=run_frozen_2d,
        write=out)
    return result


def _print_summary(result):
    print(f"routes: {result.get('routes_file')}")
    print(f"status: {result.get('status')}   "
          f"formal_acceptance={result.get('formal_acceptance')}   "
          f"exploratory_pass={result.get('exploratory_pass')}   "
          f"exit_code={result.get('exit_code')}")
    stack = result.get("layer_stack") or {}
    print(f"layer stack: valid={stack.get('valid')} "
          f"provenance={stack.get('provenance')} "
          f"heights={ {key: value.get('physical_z_mm') for key, value in (stack.get('layers') or {}).items()} }")
    stats = result.get("stats") or {}
    counts = result.get("counts") or {}
    print(f"routed={stats.get('routed')} failed={stats.get('failed')} "
          f"lifted={stats.get('lifted')} transitions={stats.get('transition_count')} "
          f"multi={stats.get('multi_transition_routes')}")
    print(f"min_curvature={stats.get('min_curvature_radius_mm')} mm "
          f"min_3d_clearance={stats.get('min_3d_clearance_mm')} mm "
          f"({stats.get('min_3d_clearance_bound')})")
    print(f"violations: {counts.get('violations')} "
          f"({', '.join(f'{key}={counts.get(key)}' for key in CATEGORIES)})")
    print("items:")
    for item in result.get("items") or []:
        print(f"  [{item.get('status'):>14s}] req{item.get('requirement')}: "
              f"{item.get('item')}")
    if result.get("warnings"):
        print("warnings:", "; ".join(str(value) for value in result["warnings"][:5]))


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(
        description=("Independent validator for the corrected L1-L5 physical "
                     "layer model (R9, fixed radius R=15 mm)."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--routes", type=Path, required=True,
                        help="routes_l3d.json produced by the L3D experiment")
    parser.add_argument("--layer-stack", default=None,
                        help="layer stack JSON file or inline JSON object "
                             "(default: the stack embedded in the routes file)")
    parser.add_argument("--allow-exploratory", action="store_true",
                        help="exit 0 for a passing *exploratory* geometry result "
                             "even while formal acceptance is refused "
                             "(unconfirmed layer heights)")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the JSON report here (default: "
                             "<routes dir>/validation/<routes stem>.json)")
    parser.add_argument("--skip-frozen-2d", action="store_true",
                        help="skip the frozen strict 2D same-plane pair audit "
                             "(debugging aid; geometry/3D checks still run)")
    parser.add_argument("--dump-summary", action="store_true",
                        help="print the whole report JSON to stdout")
    args = parser.parse_args(argv)
    routes_path = Path(args.routes)
    out = args.out
    if out is None:
        out = routes_path.parent / "validation" / (
            routes_path.stem + ".validation.json")
    print("R15 profile applied before frozen fslw imports: "
          f"{_fslw_modules()[0].EXPECTED_SHA256.get('V2', '')[:12]}...")
    result = validate_file(
        routes_path, layer_stack_raw=args.layer_stack,
        allow_exploratory=args.allow_exploratory, out=out,
        run_frozen_2d=not args.skip_frozen_2d)
    _print_summary(result)
    print(f"report written {out}")
    if args.dump_summary:
        print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    code = result.get("exit_code")
    return int(code) if code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())

