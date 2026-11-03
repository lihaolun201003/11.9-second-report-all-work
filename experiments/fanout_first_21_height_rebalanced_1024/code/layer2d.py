# -*- coding: utf-8 -*-
"""Per-physical-layer 2D R15 body router (fanout-first 1024 system).

The fanout planner lifts every connection from its interface plane (z=0 / z=0.5)
to one fixed body layer and leaves a *landing pose* ``A`` (source) / ``B``
(target) on that layer.  This module routes the 2D body between those poses:

    body:  A --(heading dA)--> ... --> B (arriving with heading -dB)

Every body is a chain of axis-aligned straight lines and exact ``R = 15 mm``
quarter / short-S arcs (the frozen D56 primitive set).  The body must

* start at ``A`` with tangent ``dA`` and end at ``B`` with tangent ``-dB``
  (pose-complete to ``1e-6`` so the full-route assembler accepts it),
* stay inside the 150 x 150 mm glass (centreline in ``[0, 150]^2``),
* keep the same-layer strict ``D56Index`` rules (width 0.05 + edge gap 0.03,
  legal transverse crossings accepted, overlap / too-close rejected), and
* keep true 3D distance ``>= 0.05 mm`` to every transition obstacle sample of
  another route (the mandatory transition-vs-body rule; the router is
  conservative and uses ``0.062 mm`` so the online 3D world check passes).

Three homogeneous layer classes are supported (canonical frame: the body starts
at ``(0, 0)`` heading ``+y``):

``same``      end ``(bx, 0)``, arrival heading ``-y``   -- monotone R15 U-turn
              (dock / nested arm ladder families).
``opposite``  end ``(bx, by)``, arrival heading ``+y``  -- straight / short-S /
              Z-shift / staircase / detour families.
``adjacent``  end ``(bx, by)``, arrival heading ``+x``  -- L / shift-turn /
              3-bend / left-loop families.

Candidate generation is deterministic, several families are interleaved so one
family cannot monopolise the budget, candidates are de-duplicated by a rounded
primitive signature and ranked (shortest / fewest bends first, then harder
placements).  Routing is a deterministic greedy commit on a live strict
``D56Index`` plus a bounded rip-up-and-reroute (RRR) loop with transactional
rollback (the routed count never decreases inside a round).

Public API
----------
``route_layer(layer_id, z_mm, tasks, obstacles=None, budget=600, rr_rounds=2,
              rr_ripmax=3, log=print, ordering_seed=0, cfg=None)``
``route_all_layers(layer_tasks, out_dir=None, cfg=None, log=print,
                   ordering_seed=0)``
``make_tasks_from_assignment(assignment_rows, landings, obstacles=None)``
``synthesize_landings(rows, lead=2.0)``
``write_experiment_c(result, out_dir)``

Task record (input)::

    {'route_id': int, 'A': (x, y), 'dA': (dx, dy), 'B': (x, y), 'dB': (dx, dy),
     'relation': 'same'|'opposite'|'adjacent'|'', 'manual_group': str,
     'source_side': 'N'|..., 'target_side': ...}

The body starts at ``A`` heading ``dA`` and must arrive at ``B`` heading
``-dB`` (``dB`` is the target port's inward direction).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from ..d56.index import D56Index
from ..d56.index import prepare as d56_prepare
from ..fsd25d.world25d import point_primitive_distance_2d, primitive_bbox
from ..fslw import geom
from ..legacy_geometry import transform_primitives
from ..v2opt.candext import move_path as _move_path_ext
from . import common as C

# ---------------------------------------------------------------------------
# process / geometry constants (single source of truth: fanout1024.common)
# ---------------------------------------------------------------------------
R15 = float(C.MIN_BEND_RADIUS_MM)            # 15.0 mm, never lowered
BOARD = float(C.board_mm())                   # 150.0 mm
WIDTH = float(C.WIDTH_MM)                     # 0.05 mm
EDGE_GAP = float(C.EDGE_GAP_MM)               # 0.03 mm
CLEARANCE_2D = float(C.CLEARANCE_2D_MM)       # 0.08 mm (same-layer centreline)
CLEARANCE_3D = float(C.MIN_3D_CLEARANCE_MM)   # 0.05 mm (true 3D centreline)

#: conservative 3D acceptance threshold: the online ``ClearanceWorld3D`` accepts
#: a point distance of only ``clearance + 0.01 + 0.001`` (= 0.061 mm), so the
#: body must keep a little more than the nominal 0.05 mm rule.
CLEARANCE_3D_ACCEPT = CLEARANCE_3D + 0.012     # 0.062 mm

POSE_TOL = 1e-6          # endpoint / tangent acceptance of the body chain
TANGENT_TOL = 1e-6       # radians (cosine distance is tiny for our dyadic chain)
BOARD_TOL = 1e-7         # centreline board bound tolerance (validator allows 1e-6)
SELF_CLEARANCE = CLEARANCE_2D + 0.01
SELF_PATH_SEPARATION = 1.0

#: per-shape budget caps
DEFAULT_CFG = dict(
    budget=600,                 # candidate evaluations per route attempt
    rr_rounds=2,                # bounded rip-up & reroute rounds
    rr_ripmax=3,                # blockers ripped per failed route
    u_ladder_step=1.5,          # same-side U arm ladder step (mm)
    max_u_levels=160,           # cap of the same-side U arm ladder
    opp_ladder_count=40,        # z/shift level count of the opposite families
    opp_detour_count=14,        # detour excursion ladder count
    adj_ladder_count=24,        # adjacent dogleg ladder count
    adj_slot_count=8,
    max_candidates_built=4000,  # hard guard per attempt
    obstacle_cell_mm=0.5,
    obstacle_margin_mm=0.004,   # extra safety over CLEARANCE_3D_ACCEPT
    phase_scale=0.37,           # ordering_seed -> candidate ladder phase
)

#: frame kind order used by the deterministic difficulty ordering
_KIND_ORDER = {'same': 0, 'opposite': 1, 'adjacent': 2}

#: D4 (board-preserving isometries) matrices, preferred order.  Every matrix
#: maps the world square [0,150]^2 onto itself (as a set); with the translation
#: ``offset = -M @ A`` it gives the canonical frame ``canon = M @ (world - A)``.
_D4 = OrderedDict([
    ('id',    ((1.0, 0.0), (0.0, 1.0))),
    ('r90',   ((0.0, -1.0), (1.0, 0.0))),
    ('r180',  ((-1.0, 0.0), (0.0, -1.0))),
    ('r270',  ((0.0, 1.0), (-1.0, 0.0))),
    ('mx',    ((1.0, 0.0), (0.0, -1.0))),
    ('my',    ((-1.0, 0.0), (0.0, 1.0))),
    ('d1',    ((0.0, 1.0), (1.0, 0.0))),
    ('d2',    ((0.0, -1.0), (-1.0, 0.0))),
])

_AXES = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))


# ---------------------------------------------------------------------------
# tiny geometry helpers
# ---------------------------------------------------------------------------
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit_axis(vector):
    """Return ``(unit, error)`` for an axis-aligned unit direction."""
    try:
        x, y = float(vector[0]), float(vector[1])
    except (TypeError, ValueError, IndexError):
        return None, 'invalid_direction'
    norm = math.hypot(x, y)
    if not math.isfinite(norm) or norm <= 0.0:
        return None, 'nonfinite_direction'
    return (x / norm, y / norm), None


def _prim_length(prim):
    if prim['kind'] == 'line':
        return _dist(prim['p0'], prim['p1'])
    return abs(float(prim['sweep'])) * float(prim['radius'])


def _path_length(prims):
    return float(sum(_prim_length(prim) for prim in prims))


def _start_tangent(prim):
    if prim['kind'] == 'line':
        dx = float(prim['p1'][0]) - float(prim['p0'][0])
        dy = float(prim['p1'][1]) - float(prim['p0'][1])
        norm = math.hypot(dx, dy)
        return (dx / norm, dy / norm) if norm > 1e-15 else (0.0, 0.0)
    angle = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    sign = 1.0 if sweep >= 0.0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def _end_tangent(prim):
    if prim['kind'] == 'line':
        return _start_tangent(prim)
    angle = float(prim['start_angle']) + float(prim['sweep'])
    sweep = float(prim['sweep'])
    sign = 1.0 if sweep >= 0.0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def _tangent_gap(a, b):
    na = math.hypot(a[0], a[1])
    nb = math.hypot(b[0], b[1])
    if na <= 1e-12 or nb <= 1e-12:
        return math.pi
    value = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
    return math.acos(max(-1.0, min(1.0, value)))


def _short_s_advance(shift):
    """Longitudinal advance of the frozen two-arc short-S for ``shift`` (mm)."""
    value = abs(float(shift))
    if value <= 1e-12:
        return 0.0
    if value >= 2.0 * R15 - 1e-12:
        return float('inf')
    theta = math.acos(1.0 - value / (2.0 * R15))
    return 2.0 * R15 * math.sin(theta)


def _rounded(value, digits=6):
    out = round(float(value), digits)
    return 0.0 if out == 0.0 else out


# ---------------------------------------------------------------------------
# canonical frame
# ---------------------------------------------------------------------------
def _apply(matrix, vector):
    return (matrix[0][0] * vector[0] + matrix[0][1] * vector[1],
            matrix[1][0] * vector[0] + matrix[1][1] * vector[1])


def _inverse_apply(matrix, vector):
    # M orthonormal -> inverse = transpose
    return (matrix[0][0] * vector[0] + matrix[1][0] * vector[1],
            matrix[0][1] * vector[0] + matrix[1][1] * vector[1])


def _classify_arrival(vector, tol=1e-9):
    x, y = vector
    if abs(x) <= tol and abs(y + 1.0) <= tol:
        return 'same'
    if abs(x) <= tol and abs(y - 1.0) <= tol:
        return 'opposite'
    if abs(y) <= tol and abs(x - 1.0) <= tol:
        return 'adjacent'
    return None


def canonical_frame(task):
    """Build the canonical frame of one body task.

    Returns ``(frame, error)``.  In the canonical frame the body starts at
    ``(0, 0)`` heading ``(0, 1)`` and ends at ``(bx, by)`` with arrival heading
    ``-y`` (same side), ``+y`` (opposite side) or ``+x`` (adjacent sides).
    """
    try:
        A = (float(task['A'][0]), float(task['A'][1]))
        B = (float(task['B'][0]), float(task['B'][1]))
    except (KeyError, TypeError, ValueError, IndexError):
        return None, 'invalid_landing_pose'
    if not all(math.isfinite(v) for v in A + B):
        return None, 'nonfinite_landing_pose'
    dA, err = _unit_axis(task.get('dA'))
    if err:
        return None, 'invalid_source_direction'
    dB, err = _unit_axis(task.get('dB'))
    if err:
        return None, 'invalid_target_direction'
    if abs(dA[0]) > 1e-12 and abs(dA[1]) > 1e-12:
        return None, 'non_axis_source_direction'
    if abs(dB[0]) > 1e-12 and abs(dB[1]) > 1e-12:
        return None, 'non_axis_target_direction'
    for name, point in (('A', A), ('B', B)):
        if not (-BOARD_TOL <= point[0] <= BOARD + BOARD_TOL
                and -BOARD_TOL <= point[1] <= BOARD + BOARD_TOL):
            return None, f'{name}_outside_board'

    neg_dB = (-dB[0], -dB[1])
    chosen = None
    for name, matrix in _D4.items():
        if _dist(_apply(matrix, dA), (0.0, 1.0)) > 1e-9:
            continue
        arrival = _apply(matrix, neg_dB)
        kind = _classify_arrival(arrival)
        if kind is None:
            continue
        if kind == 'adjacent' and arrival[0] < 0.0:
            continue  # force the canonical arrival to be +x
        chosen = (name, matrix, kind, arrival)
        break
    if chosen is None:
        return None, 'unsupported_pose_relation'
    name, matrix, kind, arrival = chosen

    bx = matrix[0][0] * (B[0] - A[0]) + matrix[0][1] * (B[1] - A[1])
    by = matrix[1][0] * (B[0] - A[0]) + matrix[1][1] * (B[1] - A[1])
    # canonical coordinates of the board square (M is a board symmetry)
    corners = []
    for wx in (0.0, BOARD):
        for wy in (0.0, BOARD):
            corners.append(_apply(matrix, (wx - A[0], wy - A[1])))
    board = (min(p[0] for p in corners), min(p[1] for p in corners),
             max(p[0] for p in corners), max(p[1] for p in corners))
    transform = dict(matrix=[list(row) for row in matrix],
                     offset=[-(matrix[0][0] * A[0] + matrix[0][1] * A[1]),
                             -(matrix[1][0] * A[0] + matrix[1][1] * A[1])],
                     reflected=bool(matrix[0][0] * matrix[1][1]
                                    - matrix[0][1] * matrix[1][0] < 0.0))
    frame = dict(A=A, B=B, dA=dA, dB=dB, matrix=matrix, name=name,
                 transform=transform, kind=kind, arrival=arrival,
                 bx=float(bx), by=float(by), board=board)
    if kind == 'same' and abs(by) > 1e-6:
        # the two same-side landings must be at the same depth from the side
        return None, 'same_side_unequal_landing_depth'
    if kind == 'opposite' and by <= 1e-9:
        return None, 'opposite_side_zero_travel'
    return frame, None


def _map_canonical(frame, primitives):
    """Map canonical-frame primitives back into world coordinates."""
    return [dict(prim) for prim in
            transform_primitives([dict(prim) for prim in primitives],
                                 frame['transform'], inverse=True)]


#: family priority tiers: a route exhausts tier 0 before tier 1 is consulted.
#: Tier 0 holds the short, robust families; the more complex fallbacks come later.
_FAMILY_TIER = {
    'U_QUARTER_PAIR': 0, 'U_R15_LIBRARY': 1, 'U_SHORT_SHIFT': 0,
    'OPP_STRAIGHT': 0, 'OPP_SHORT_S': 0, 'OPP_Z': 0,
    'OPP_S2_SPLIT': 1, 'OPP_S_Z': 1, 'OPP_Z_S': 1, 'OPP_Z2_SAME': 1,
    'OPP_DETOUR': 2, 'OPP_DETOUR_BACK': 2,
    'ADJ_L': 0, 'ADJ_SHIFT_TURN': 0, 'ADJ_TURN_SHIFT': 0, 'ADJ_DOWN_LOOP': 0,
    'ADJ_Z_TURN': 0, 'ADJ_Z_TURN_LEFT': 0, 'ADJ_Z2_TURN': 1,
    'ADJ_UP_LOOP': 0, 'ADJ_SIDE_LOOP': 1,
    'ADJ_SHIFT2_TURN': 1, 'ADJ_SHIFT_LOOP': 1, 'ADJ_LEFT_LOOP': 1,
}


def _family_tier(family):
    return int(_FAMILY_TIER.get(str(family), 1))


# ---------------------------------------------------------------------------
# candidate specs
# ---------------------------------------------------------------------------
def _spec(family, params, moves=None, primitives=None):
    return dict(family=str(family), params=dict(params), moves=moves,
                primitives=primitives)


def _ladder(lo, hi, count, phase=0.0):
    """Deterministic ascending ladder of ``count`` values in ``[lo, hi]``."""
    lo = float(lo)
    hi = float(hi)
    if not math.isfinite(lo) or not math.isfinite(hi):
        return []
    if hi < lo - 1e-12:
        return []
    if hi - lo <= 1e-12:
        return [lo]
    count = max(2, int(count))
    step = (hi - lo) / (count - 1)
    values = []
    offset = (float(phase) % 1.0) * step
    for index in range(count):
        value = lo + index * step
        if index and offset:
            value = min(hi, value + offset)
        values.append(_rounded(value, 9))
    if values[0] > lo + 1e-12:
        values.insert(0, _rounded(lo, 9))
    return values


def _slot_pairs(budget, count, phase):
    """Small deterministic set of ``(first, second)`` vertical distributions."""
    budget = float(budget)
    if budget <= 0.0:
        return [(0.0, 0.0)]
    pairs = [(0.0, 0.0)]
    for first in _ladder(0.0, budget, max(2, int(count)), phase)[:max(3, count)]:
        pairs.append((first, 0.0))
    for fraction in (0.25, 0.5):
        pairs.append((0.0, budget * fraction))
        pairs.append((budget * fraction, 0.0))
    seen = set()
    out = []
    for first, second in pairs:
        key = (_rounded(first, 6), _rounded(second, 6))
        if key in seen or first + second > budget + 1e-9:
            continue
        seen.add(key)
        out.append((first, second))
    return out


# ---------------------------------------------------------------------------
# same-side U-turn family (canonical start (0,0)+y, end (bx,0) arrival -y)
# ---------------------------------------------------------------------------
def _same_side_specs(frame, cfg, phase=0.0):
    bx, by = frame['bx'], frame['by']
    xmin, ymin, xmax, ymax = frame['board']
    u = abs(bx)
    specs = []
    if u >= 2.0 * R15 - 1e-9:
        turn = -1.0 if bx > 0 else 1.0
        middle = u - 2.0 * R15
        amin = max(0.0, by)
        amax = ymax - R15 - 1e-6
        if amin > amax + 1e-12:
            return specs
        count = int(math.ceil((amax - amin) / max(cfg['u_ladder_step'], 1e-6))) + 1
        count = min(max(count, 2), int(cfg['max_u_levels']))
        for arm in _ladder(amin, amax, count, phase):
            moves = [('L', arm), ('Q', turn), ('L', middle), ('Q', turn),
                     ('L', arm - by)]
            specs.append(_spec('U_QUARTER_PAIR',
                               dict(arm_mm=arm, middle_mm=middle,
                                    separation_mm=u,
                                    depth_mm=arm - by + R15), moves))
    elif u > 1e-9:
        # separation below 2R: pre-shift with the frozen short-S then U-turn
        lateral = 1.0 if bx > 0 else -1.0
        turn = -lateral
        wmin = max(0.0, u - 2.0 * R15) + 1e-6
        wmax = u - 1e-6
        for w in _ladder(wmin, wmax, 8, phase):
            shift = lateral * (2.0 * R15 + w - u)
            if abs(shift) >= 2.0 * R15 - 1e-9:
                continue
            advance = _short_s_advance(shift)
            amin = max(0.0, by - advance)
            amax = ymax - R15 - 1e-6 - advance
            for arm in _ladder(amin, amax, 12, phase):
                c = arm + advance - by
                if c < -1e-9:
                    continue
                moves = [('L', arm), ('S', shift), ('L', 0.0), ('Q', turn),
                         ('L', w), ('Q', turn), ('L', c)]
                specs.append(_spec('U_SHORT_SHIFT',
                                   dict(arm_mm=arm, shift_mm=shift,
                                        middle_mm=w, separation_mm=u), moves))
    return specs


def _signed_depth(point, inward):
    """Depth of a landing ``point`` from its board side along ``-inward``."""
    x, y = point
    ix, iy = inward
    if abs(ix) > 0.5:      # E/W side
        return (BOARD - x) if ix < 0.0 else x
    return (BOARD - y) if iy < 0.0 else y


def _library_u_specs(task, frame):
    """``r15.u_geometry.u_candidates`` U-turns translated by the landing depth.

    Included as an independent library family (the main generator above is the
    dense arm-ladder equivalent).  Requires both landings at the same depth.
    """
    if frame['kind'] != 'same':
        return []
    A, B, dA, dB = frame['A'], frame['B'], frame['dA'], frame['dB']
    depth_a = _signed_depth(A, dA)
    depth_b = _signed_depth(B, dB)
    if abs(depth_a - depth_b) > 1e-6 or depth_a <= 0.0:
        return []
    depth = 0.5 * (depth_a + depth_b)
    p_edge = (A[0] - depth * dA[0], A[1] - depth * dA[1])
    q_edge = (B[0] - depth * dB[0], B[1] - depth * dB[1])
    try:
        from ..r15 import u_geometry as UG
        candidates = UG.u_candidates(p_edge, q_edge, dA, (-dB[0], -dB[1]),
                                     radius=R15)
    except Exception:  # pragma: no cover - defensive
        return []
    specs = []
    for index, candidate in enumerate(candidates):
        primitives = []
        for prim in candidate['primitives']:
            mapped = dict(prim)
            for key in ('p0', 'p1', 'center'):
                if key in mapped:
                    mapped[key] = [mapped[key][0] + depth * dA[0],
                                   mapped[key][1] + depth * dA[1]]
            primitives.append(mapped)
        params = dict(candidate.get('params') or {})
        params['landing_depth_mm'] = depth
        params['library_index'] = index
        specs.append(_spec('U_R15_LIBRARY', params, primitives=primitives))
    return specs


# ---------------------------------------------------------------------------
# opposite-side family (canonical start (0,0)+y, end (bx,by) arrival +y)
# ---------------------------------------------------------------------------
def _opp_slots(budget, cfg, phase, count=None):
    """Vertical distribution pairs ``(first, second)`` for two-block families."""
    count = count if count is not None else max(6, cfg['adj_slot_count'])
    return _slot_pairs(max(0.0, budget), count, phase)


def _opposite_specs(frame, cfg, phase=0.0):
    """Straight / short-S / Z / two-block staircase / detour families.

    Canonical frame: start ``(0, 0)`` heading ``+y``, end ``(bx, by)`` heading
    ``+y``.  A "Z block" is ``Q(s) L(w) Q(-s)``: it advances ``2R`` along ``+y``
    and shifts laterally by ``-s*(2R + w)``; an "S block" is the frozen two-arc
    short-S shifting ``-shift`` laterally with advance ``advance(shift)``.
    """
    bx, by = frame['bx'], frame['by']
    xmin, ymin, xmax, ymax = frame['board']
    u = abs(bx)
    lateral = 1.0 if bx > 0.0 else -1.0          # direction of the net shift
    turn = -lateral                              # Z block first-quarter sign
    specs = []
    if by <= 1e-9:
        return specs
    ladder = int(cfg['opp_ladder_count'])
    if u <= 1e-9:
        specs.append(_spec('OPP_STRAIGHT', dict(length_mm=by), [('L', by)]))
    # ---- one-block families -------------------------------------------------
    if u >= 2.0 * R15 - 1e-9:
        w = u - 2.0 * R15
        budget = by - 2.0 * R15
        if budget >= -1e-9:
            for a in _ladder(0.0, max(0.0, budget), ladder, phase):
                moves = [('L', a), ('Q', turn), ('L', w), ('Q', -turn),
                         ('L', max(0.0, budget) - a)]
                specs.append(_spec('OPP_Z', dict(shift_mm=lateral * u,
                                                 first_mm=a, w_mm=w), moves))
    if u < 2.0 * R15 - 1e-9:
        shift = -bx
        advance = _short_s_advance(shift)
        budget = by - advance
        if budget >= -1e-9:
            for a in _ladder(0.0, max(0.0, budget), ladder, phase):
                moves = [('L', a), ('S', shift), ('L', max(0.0, budget) - a)]
                specs.append(_spec('OPP_SHORT_S',
                                   dict(shift_mm=shift, first_mm=a,
                                        advance_mm=advance), moves))
    # ---- two-block families -------------------------------------------------
    # (a) two short-S shifts carrying the total lateral displacement
    if 1e-9 < u < 4.0 * R15 - 1e-9:
        for fraction in (0.25, 0.5, 0.75):
            shift1 = -bx * fraction
            shift2 = -bx * (1.0 - fraction)
            if (abs(shift1) >= 2.0 * R15 - 1e-9
                    or abs(shift2) >= 2.0 * R15 - 1e-9):
                continue
            advance = _short_s_advance(shift1) + _short_s_advance(shift2)
            budget = by - advance
            if budget < -1e-9:
                continue
            for first, second in _opp_slots(budget, cfg, phase):
                third = budget - first - second
                if third < -1e-9:
                    continue
                moves = [('L', first), ('S', shift1), ('L', second),
                         ('S', shift2), ('L', third)]
                specs.append(_spec('OPP_S2_SPLIT',
                                   dict(shift1_mm=shift1, shift2_mm=shift2),
                                   moves))
    # (b) short-S + Z jog (the two blocks split the lateral displacement)
    if 1e-9 < u < 4.0 * R15 - 1e-9:
        # Z block width w2 must satisfy: shift1 = lateral*(2R + w2 - u),
        # |shift1| < 2R  ->  u - 2R < w2 < u
        w2_lo = max(1e-6, u - 2.0 * R15 + 1e-6)
        w2_hi = u - 1e-6
        for w2 in _ladder(w2_lo, w2_hi, max(4, ladder // 3), phase):
            shift1 = lateral * (2.0 * R15 + w2 - u)
            if abs(shift1) >= 2.0 * R15 - 1e-9:
                continue
            advance = _short_s_advance(shift1) + 2.0 * R15
            budget = by - advance
            if budget < -1e-9:
                continue
            for first, second in _opp_slots(budget, cfg, phase, count=4):
                third = budget - first - second
                if third < -1e-9:
                    continue
                moves = [('L', first), ('S', shift1), ('L', second),
                         ('Q', turn), ('L', w2), ('Q', -turn), ('L', third)]
                specs.append(_spec('OPP_S_Z',
                                   dict(shift_mm=shift1, w_mm=w2), moves))
                moves = [('L', first), ('Q', turn), ('L', w2), ('Q', -turn),
                         ('L', second), ('S', shift1), ('L', third)]
                specs.append(_spec('OPP_Z_S',
                                   dict(shift_mm=shift1, w_mm=w2), moves))
    # (c) detour toward the target side (first block larger) -- any lateral shift
    budget = by - 4.0 * R15
    if budget >= -1e-9:
        budget = max(0.0, budget)
        excursion = _ladder(0.0, min(3.0 * R15, 4.0 * R15 + u),
                            cfg['opp_detour_count'], phase)
        for wexc in excursion:
            w1 = wexc + u
            w2 = wexc
            for first, second in _opp_slots(budget, cfg, phase, count=4):
                third = budget - first - second
                if third < -1e-9:
                    continue
                moves = [('L', first), ('Q', turn), ('L', w1),
                         ('Q', -turn), ('L', second), ('Q', -turn),
                         ('L', w2), ('Q', turn), ('L', third)]
                specs.append(_spec('OPP_DETOUR',
                                   dict(excursion_mm=wexc,
                                        shift_mm=lateral * u), moves))
        # (d) detour toward the opposite side (first block goes the other way)
        for wexc in excursion:
            w1 = wexc
            w2 = wexc + u
            for first, second in _opp_slots(budget, cfg, phase, count=4):
                third = budget - first - second
                if third < -1e-9:
                    continue
                moves = [('L', first), ('Q', -turn), ('L', w1),
                         ('Q', turn), ('L', second), ('Q', turn),
                         ('L', w2), ('Q', -turn), ('L', third)]
                specs.append(_spec('OPP_DETOUR_BACK',
                                   dict(excursion_mm=wexc,
                                        shift_mm=lateral * u), moves))
        # (e) same-direction staircase (needs a large lateral shift)
        if u >= 4.0 * R15 - 1e-9:
            remaining = u - 4.0 * R15
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                w1 = fraction * remaining
                w2 = remaining - w1
                for first, second in _opp_slots(budget, cfg, phase, count=4):
                    third = budget - first - second
                    if third < -1e-9:
                        continue
                    moves = [('L', first), ('Q', turn), ('L', w1),
                             ('Q', -turn), ('L', second), ('Q', turn),
                             ('L', w2), ('Q', -turn), ('L', third)]
                    specs.append(_spec('OPP_Z2_SAME',
                                       dict(w1_mm=w1, w2_mm=w2,
                                            shift_mm=lateral * u), moves))
    return specs


# ---------------------------------------------------------------------------
# adjacent-side family (canonical start (0,0)+y, end (bx,by) arrival +x)
# ---------------------------------------------------------------------------
def _adjacent_specs(frame, cfg, phase=0.0):
    bx, by = frame['bx'], frame['by']
    xmin, ymin, xmax, ymax = frame['board']
    specs = []
    # ---- single corner (shortest) ------------------------------------------
    if bx >= R15 - 1e-9 and by >= R15 - 1e-9:
        moves = [('L', by - R15), ('Q', -1), ('L', bx - R15)]
        specs.append(_spec('ADJ_L', dict(), moves))
    # ---- vertical short-S shift then quarter turn ---------------------------
    shift = R15 - bx
    if abs(shift) < 2.0 * R15 - 1e-9:
        advance = _short_s_advance(shift)
        budget = by - R15 - advance
        if budget >= -1e-9:
            for first in _ladder(0.0, max(0.0, budget),
                                 cfg['adj_ladder_count'], phase):
                moves = [('L', first), ('S', shift),
                         ('L', max(0.0, budget) - first), ('Q', -1)]
                specs.append(_spec('ADJ_SHIFT_TURN',
                                   dict(shift_mm=shift, first_mm=first), moves))
    # ---- quarter turn then horizontal short-S shift -------------------------
    for first in _ladder(0.0, max(0.0, by + R15),
                         cfg['adj_ladder_count'], phase):
        shift_y = by - R15 - first
        if abs(shift_y) >= 2.0 * R15 - 1e-9:
            continue
        advance = _short_s_advance(shift_y)
        last = bx - R15 - advance
        if last < -1e-9:
            continue
        moves = [('L', first), ('Q', -1), ('S', shift_y), ('L', last)]
        specs.append(_spec('ADJ_TURN_SHIFT',
                           dict(shift_y_mm=shift_y, first_mm=first), moves))
    # ---- down loop: up, right, down through the target row, right -----------
    if bx >= 3.0 * R15 - 1e-9:
        wmax = bx - 3.0 * R15
        amin = max(0.0, by + R15)
        amax = ymax - R15 - 1e-6
        for arm in _ladder(amin, amax, cfg['adj_ladder_count'], phase):
            down = arm - by - R15
            if down < -1e-9:
                continue
            # dense lateral ladder including positions just short of the end
            for w in _ladder(0.0, wmax,
                             max(12, 2 * cfg['adj_slot_count']), phase):
                last = bx - 3.0 * R15 - w
                if last < -1e-9:
                    continue
                moves = [('L', arm), ('Q', -1), ('L', w), ('Q', -1),
                         ('L', down), ('Q', 1), ('L', last)]
                specs.append(_spec('ADJ_DOWN_LOOP',
                                   dict(arm_mm=arm, w_mm=w, down_mm=down),
                                   moves))
    # ---- shift + down loop (covers small lateral targets) -------------------
    if by + R15 >= 0.0:
        budget = by + R15
        for down_extra in _ladder(0.0, max(0.0, budget),
                                  max(6, cfg['adj_slot_count']), phase):
            down = down_extra
            base = by + R15 + down
            # choose the pre-shift and the trailing horizontal lengths from a
            # small deterministic ladder; w = 0 keeps the loop compact
            for shift in _ladder(-2.0 * R15 + 0.5, 2.0 * R15 - 0.5,
                                 max(6, cfg['adj_slot_count'] // 2), phase):
                advance = _short_s_advance(shift)
                last = bx - 3.0 * R15 + shift
                if last < -1e-9:
                    continue
                # vertical: base + advance + c - down - R = by -> c = down + R - base ... solve
                c = down + R15 - base
                if c < -1e-9:
                    continue
                moves = [('L', base), ('S', shift), ('L', max(0.0, c)),
                         ('Q', -1), ('L', 0.0), ('Q', -1), ('L', down),
                         ('Q', 1), ('L', last)]
                specs.append(_spec('ADJ_SHIFT_LOOP',
                                   dict(shift_mm=shift, down_mm=down), moves))
    # ---- Z jog then final quarter arc (short final approach, big |bx|) ------
    if bx >= 3.0 * R15 - 1e-9:
        w = bx - 3.0 * R15
        budget = by - 3.0 * R15
        if budget >= -1e-9:
            budget = max(0.0, budget)
            for a in _ladder(0.0, budget, cfg['adj_ladder_count'], phase):
                last = budget - a
                if last < -1e-9:
                    continue
                moves = [('L', a), ('Q', -1), ('L', w), ('Q', 1),
                         ('L', max(0.0, last)), ('Q', -1)]
                specs.append(_spec('ADJ_Z_TURN',
                                   dict(w_mm=w, first_mm=a), moves))
        # two Z jogs then the final quarter arc (finer lateral positioning)
        if bx >= 5.0 * R15 - 1e-9:
            remaining = bx - 5.0 * R15
            budget2 = by - 5.0 * R15
            if budget2 >= -1e-9:
                budget2 = max(0.0, budget2)
                for fraction in (0.0, 0.5):
                    w1 = fraction * remaining
                    w2 = remaining - w1
                    for a, v in _slot_pairs(budget2,
                                            cfg['adj_slot_count'], phase):
                        last = budget2 - a - v
                        if last < -1e-9:
                            continue
                        moves = [('L', a), ('Q', -1), ('L', w1), ('Q', 1),
                                 ('L', v), ('Q', -1), ('L', w2), ('Q', 1),
                                 ('L', last), ('Q', -1)]
                        specs.append(_spec('ADJ_Z2_TURN',
                                           dict(w1_mm=w1, w2_mm=w2), moves))
    if bx <= -3.0 * R15 + 1e-9:
        # mirrored Z jog (net negative lateral shift) then final arc
        w = -bx - 3.0 * R15
        budget = by - 3.0 * R15
        if budget >= -1e-9:
            budget = max(0.0, budget)
            for a in _ladder(0.0, budget, cfg['adj_ladder_count'], phase):
                last = budget - a
                if last < -1e-9:
                    continue
                moves = [('L', a), ('Q', 1), ('L', w), ('Q', -1),
                         ('L', max(0.0, last)), ('Q', -1)]
                specs.append(_spec('ADJ_Z_TURN_LEFT',
                                   dict(w_mm=w, first_mm=a), moves))
    # ---- 3-bend "up loop" families (north/west, north/west variants) --------
    #  canonical turn patterns (+,-,+) and (+,-,-): they shift both legs onto
    #  different corridors, which is what the congested corner layers need.
    if bx >= 3.0 * R15 - 1e-9 and by >= 3.0 * R15 - 1e-9:
        xfree = bx - 3.0 * R15
        yfree = by - 3.0 * R15
        for a in _ladder(0.0, yfree, cfg['adj_ladder_count'], phase):
            down = yfree - a
            if down < -1e-9:
                continue
            for w in _ladder(0.0, xfree, max(10, cfg['adj_slot_count']), phase):
                last = xfree - w
                if last < -1e-9:
                    continue
                moves = [('L', a), ('Q', -1), ('L', w), ('Q', 1),
                         ('L', down), ('Q', -1), ('L', last)]
                specs.append(_spec('ADJ_UP_LOOP',
                                   dict(arm_mm=a, w_mm=w, down_mm=down),
                                   moves))
    if bx >= R15 - 1e-9 and by >= 3.0 * R15 - 1e-9:
        # pattern (+,-,-): e = bx - R + w (the first jog goes to -x)
        yfree = by - 3.0 * R15
        wmax = max(0.0, -xmin - 2.0 * R15)
        for a in _ladder(0.0, yfree, max(10, cfg['adj_slot_count']), phase):
            down = yfree - a
            if down < -1e-9:
                continue
            for w in _ladder(0.0, wmax, max(6, cfg['adj_slot_count'] // 2),
                             phase):
                last = bx - R15 + w
                if last < -1e-9:
                    continue
                moves = [('L', a), ('Q', 1), ('L', w), ('Q', -1),
                         ('L', down), ('Q', -1), ('L', last)]
                specs.append(_spec('ADJ_SIDE_LOOP',
                                   dict(arm_mm=a, w_mm=w, down_mm=down),
                                   moves))
    # ---- two short-S shifts then quarter turn -------------------------------
    total_shift = R15 - bx
    if abs(total_shift) < 4.0 * R15 - 1e-9:
        for split in (0.25, 0.5, 0.75):
            shift1 = total_shift * split
            shift2 = total_shift - shift1
            if abs(shift1) >= 2.0 * R15 - 1e-9 or abs(shift2) >= 2.0 * R15 - 1e-9:
                continue
            advance = _short_s_advance(shift1) + _short_s_advance(shift2)
            budget = by - R15 - advance
            if budget < -1e-9:
                continue
            for first in _ladder(0.0, max(0.0, budget),
                                 max(6, cfg['adj_slot_count']), phase):
                for second in (0.0, max(0.0, budget) * 0.5):
                    third = budget - first - second
                    if third < -1e-9:
                        continue
                    moves = [('L', first), ('S', shift1), ('L', second),
                             ('S', shift2), ('L', third), ('Q', -1)]
                    specs.append(_spec('ADJ_SHIFT2_TURN',
                                       dict(shift1_mm=shift1,
                                            shift2_mm=shift2), moves))
    # ---- three left turns (general corner fallback) -------------------------
    amin = max(0.0, R15 + by)
    amax = ymax - 1e-6
    if amin <= amax:
        wmin = max(0.0, -bx - R15)
        wmax = -xmin - 1e-6
        for arm in _ladder(amin, amax, max(6, cfg['adj_slot_count']), phase):
            down = arm - R15 - by
            if down < -1e-9:
                continue
            for w in _ladder(wmin, max(wmin, wmax),
                             max(6, cfg['adj_slot_count']), phase):
                last = bx + R15 + w
                if last < -1e-9 or last > xmax + 1e-9:
                    continue
                moves = [('L', arm), ('Q', 1), ('L', w), ('Q', 1),
                         ('L', down), ('Q', 1), ('L', last)]
                specs.append(_spec('ADJ_LEFT_LOOP',
                                   dict(arm_mm=arm, w_mm=w, down_mm=down),
                                   moves))
    return specs


# ---------------------------------------------------------------------------
# candidate construction / validation
# ---------------------------------------------------------------------------
def _pose_errors(world, frame):
    """Return a reason string if the world chain is not the exact body pose."""
    if not world:
        return 'empty_chain'
    A, B = frame['A'], frame['B']
    dA, dB = frame['dA'], frame['dB']
    if _dist(world[0]['p0'], A) > POSE_TOL:
        return 'start_pose_mismatch'
    if _dist(world[-1]['p1'], B) > POSE_TOL:
        return 'end_pose_mismatch'
    if _tangent_gap(_start_tangent(world[0]), dA) > POSE_TOL:
        return 'start_tangent_mismatch'
    if _tangent_gap(_end_tangent(world[-1]), (-dB[0], -dB[1])) > POSE_TOL:
        return 'end_tangent_mismatch'
    # chain continuity + exact radius: our builders guarantee it, still audit
    for index in range(1, len(world)):
        if _dist(world[index - 1]['p1'], world[index]['p0']) > 1e-9:
            return 'chain_discontinuous'
    for prim in world:
        if prim['kind'] == 'arc':
            if abs(float(prim['radius']) - R15) > 1e-9:
                return 'arc_radius_mismatch'
            if abs(float(prim['sweep'])) > math.pi / 2.0 + 1e-9:
                return 'arc_sweep_invalid'
        elif prim['kind'] == 'line':
            dx = abs(float(prim['p1'][0]) - float(prim['p0'][0]))
            dy = abs(float(prim['p1'][1]) - float(prim['p0'][1]))
            if dx > 1e-9 and dy > 1e-9:
                return 'diagonal_line'
        else:  # pragma: no cover
            return 'unknown_primitive'
    return None


def _inside_board(world):
    for prim in world:
        box = primitive_bbox(prim)
        if (box[0] < -BOARD_TOL or box[1] < -BOARD_TOL
                or box[2] > BOARD + BOARD_TOL or box[3] > BOARD + BOARD_TOL):
            return False
    return True


def _signature(world):
    parts = []
    for prim in world:
        parts.append((prim['kind'],
                      _rounded(prim['p0'][0], 6), _rounded(prim['p0'][1], 6),
                      _rounded(prim['p1'][0], 6), _rounded(prim['p1'][1], 6)))
    return tuple(parts)


def _build_candidate(spec, frame):
    """Return ``(world_primitives, reason)``; reason ``None`` on success."""
    try:
        if spec.get('primitives') is not None:
            world = [dict(prim) for prim in spec['primitives']]
        else:
            moves = spec.get('moves') or []
            canonical, end, heading = _move_path_ext(
                (0.0, 0.0), (0.0, 1.0), moves, radius=R15)
            if canonical is None:
                return None, 'build_failed'
            if _dist(end, (frame['bx'], frame['by'])) > POSE_TOL:
                return None, 'solver_pose_mismatch'
            arrival = frame['arrival']
            if _tangent_gap(heading, arrival) > 1e-6:
                return None, 'solver_heading_mismatch'
            world = _map_canonical(frame, canonical)
        reason = _pose_errors(world, frame)
        if reason is not None:
            return None, reason
        if not _inside_board(world):
            return None, 'outside_board'
        return world, None
    except (ValueError, TypeError, IndexError, KeyError,
            ZeroDivisionError, FloatingPointError):
        return None, 'build_exception'


def _buildable(spec, frame, cfg):
    return _build_candidate(spec, frame)


# ---------------------------------------------------------------------------
# transition obstacle index (mandatory 3D transition-vs-body rule)
# ---------------------------------------------------------------------------
class ObstacleIndex:
    """Spatial index of transition obstacle samples around one body layer.

    A body primitive at layer ``z`` violates the rule when an obstacle sample of
    *another* route satisfies ``sqrt(d2d^2 + (z - z_sample)^2) < 0.062`` (the
    nominal 0.05 mm rule plus the online acceptance safety).  Samples whose z
    difference alone already exceeds the threshold are dropped.
    """

    def __init__(self, samples, z_mm, cfg=None):
        cfg = dict(DEFAULT_CFG, **(cfg or {}))
        self.z_mm = float(z_mm)
        self.cell = float(cfg['obstacle_cell_mm'])
        self.accept = float(CLEARANCE_3D_ACCEPT + cfg['obstacle_margin_mm'])
        self.grid = {}
        self.kept = 0
        self.total = 0
        for sample in samples or ():
            self.total += 1
            try:
                x = float(sample['x'])
                y = float(sample['y'])
                z = float(sample['z'])
            except (KeyError, TypeError, ValueError):
                continue
            dz = self.z_mm - z
            if abs(dz) >= self.accept:
                continue
            route_id = sample.get('route_id')
            key = (int(math.floor(x / self.cell)),
                   int(math.floor(y / self.cell)))
            self.grid.setdefault(key, []).append((x, y, dz, route_id))
            self.kept += 1
        self.cells_x = {}
        for key in self.grid:
            self.cells_x.setdefault(key[0], set()).add(key[1])

    def __len__(self):
        return self.kept

    def check(self, primitives, route_id):
        """Return ``(ok, blocker_route_ids)`` for a candidate body chain."""
        if not self.grid:
            return True, []
        accept = self.accept
        cell = self.cell
        grid = self.grid
        blockers = set()
        limit = accept + 1e-9
        for prim in primitives:
            x0, y0, x1, y1 = primitive_bbox(prim)
            cx0 = int(math.floor((x0 - limit) / cell))
            cx1 = int(math.floor((x1 + limit) / cell))
            cy0 = int(math.floor((y0 - limit) / cell))
            cy1 = int(math.floor((y1 + limit) / cell))
            for cx in range(cx0, cx1 + 1):
                column = self.cells_x.get(cx)
                if not column:
                    continue
                for cy in range(cy0, cy1 + 1):
                    bucket = grid.get((cx, cy))
                    if not bucket:
                        continue
                    for sx, sy, dz, other in bucket:
                        if other == route_id:
                            continue
                        distance2 = point_primitive_distance_2d((sx, sy), prim)
                        if distance2 * distance2 + dz * dz < accept * accept:
                            try:
                                blockers.add(int(other))
                            except (TypeError, ValueError):
                                blockers.add(other)
            if blockers:
                return False, sorted(blockers, key=str)
        return True, []


# ---------------------------------------------------------------------------
# body self clearance (mirror of the online self-clearance rule)
# ---------------------------------------------------------------------------
def _self_clearance_ok(primitives):
    """Exact non-adjacent self-distance audit of one body chain.

    Only primitive pairs separated by more than ``SELF_PATH_SEPARATION`` along
    the body are checked (the online rule has a 1 mm along-path exemption).
    """
    count = len(primitives)
    if count < 3:
        return True
    try:
        from ..conflicts import _make_primitive, _exact_distance, _bbox_distance
        compiled = [_make_primitive(prim) for prim in primitives]
    except Exception:  # pragma: no cover - defensive fallback
        return True
    lengths = [_prim_length(prim) for prim in primitives]
    limit = SELF_CLEARANCE + 1e-3
    for i in range(count):
        for j in range(i + 2, count):
            between = sum(lengths[i + 1:j])
            if between <= SELF_PATH_SEPARATION:
                continue
            if _bbox_distance(compiled[i].bounds, compiled[j].bounds) >= limit:
                continue
            if _exact_distance(compiled[i], compiled[j]) < SELF_CLEARANCE:
                return False
    return True


# ---------------------------------------------------------------------------
# deterministic ordering
# ---------------------------------------------------------------------------
def _stable_hash(seed, route_id):
    raw = f'{int(seed)}:{int(route_id)}'.encode('utf-8')
    return int(hashlib.sha1(raw).hexdigest()[:12], 16)


def _task_difficulty(task, frame, strategy=0):
    """Return ``(kind_rank, difficulty)``; smaller is routed first.

    ``strategy`` (derived from ``ordering_seed``) selects an alternative but
    still fully deterministic route order so the joint-repair loop can retry a
    layer with a genuinely different packing.  Strategy 0 is the default
    best-known order; 1..4 are alternative orders for repair retries.
    """
    kind = frame['kind'] if frame is not None else None
    rank = _KIND_ORDER.get(kind, 9)
    if frame is None:
        return (rank, 1e9)
    bx = abs(frame['bx'])
    by = frame['by']
    if kind == 'same':
        # manual U-turns: innermost (smallest separation) first, proven order
        return (rank, bx)
    if kind == 'opposite':
        direction = (round(float(by), 6), bx)
        if strategy == 1:
            return (rank, -bx)                    # large shifts first
        if strategy == 2:
            return (rank, bx)                     # small shifts first
        if strategy == 3:
            return (rank, (frame['name'], -bx))
        if strategy == 4:
            return (rank, (round(float(by), 6), -bx))
        return (rank, direction)                  # grouped by travel direction
    # adjacent
    short_leg = min(bx, by)
    if strategy == 1:
        return (rank, -max(bx, by))
    if strategy == 2:
        return (rank, (frame['name'], short_leg))
    if strategy == 3:
        return (rank, -short_leg)
    if strategy == 4:
        return (rank, max(bx, by))
    return (rank, short_leg)


def _order_strategy(ordering_seed):
    return int(ordering_seed) % 5


def _order_tasks(tasks, frames, ordering_seed=0):
    strategy = _order_strategy(ordering_seed)

    def key(route_id):
        task = tasks[route_id]
        frame = frames.get(route_id)
        rank, difficulty = _task_difficulty(task, frame, strategy)
        if ordering_seed:
            return (rank, difficulty, _stable_hash(ordering_seed, route_id))
        return (rank, difficulty, int(route_id))
    return sorted(tasks, key=key)


def _candidate_phase(cfg, ordering_seed):
    if not ordering_seed:
        return 0.0
    return (int(ordering_seed) * float(cfg['phase_scale'])) % 1.0


# ---------------------------------------------------------------------------
# per-layer router
# ---------------------------------------------------------------------------
class _LayerRouter:
    def __init__(self, layer_id, z_mm, tasks, obstacles, cfg, log,
                 initial_routes=None):
        self.layer_id = int(layer_id)
        self.z_mm = float(z_mm)
        self.cfg = dict(DEFAULT_CFG, **(cfg or {}))
        self.log = log
        self.tasks = OrderedDict()
        for task in tasks:
            route_id = int(task['route_id'])
            self.tasks[route_id] = task
        self.frames = {}
        self.frame_errors = {}
        for route_id, task in self.tasks.items():
            frame, error = canonical_frame(task)
            self.frames[route_id] = frame
            if error:
                self.frame_errors[route_id] = error
        self.obstacles = ObstacleIndex(obstacles, self.z_mm, self.cfg)
        self.index = D56Index(width=WIDTH, gap=EDGE_GAP,
                              sagitta=0.0005, min_cross_angle_deg=5.0,
                              crossing_policy='strict')
        # frozen already-placed bodies of this layer: blockers only, they are
        # never reported as routed/failed and never ripped up by the RRR loop.
        # Their index keys must stay unique and *index-safe*: the frozen strict
        # D56 index packs pair keys as ``i*1e6 + route_id*128 + j``, so route
        # ids above ~7800 would alias different primitive pairs and could hide
        # a conflict.  Colliding or large keys are remapped to a private small
        # negative id instead of being silently dropped or aliased.
        SAFE_INDEX_KEY = 7000
        self.initial_routes = OrderedDict()
        self.initial_key_map = {}
        remapped = 0
        for key, primitives in (initial_routes or {}).items():
            try:
                route_id = int(key)
            except (TypeError, ValueError):
                continue
            if not primitives:
                continue
            if (route_id in self.tasks or route_id in self.initial_routes
                    or abs(route_id) >= SAFE_INDEX_KEY):
                mapped_id = -abs(route_id) - 1
                while (mapped_id in self.tasks
                       or mapped_id in self.initial_routes
                       or abs(mapped_id) >= SAFE_INDEX_KEY):
                    mapped_id -= 1
                self.initial_key_map[route_id] = mapped_id
                route_id = mapped_id
                remapped += 1
            prepared = d56_prepare([dict(prim) for prim in primitives])
            self.index.add(route_id, prepared)
            self.initial_routes[route_id] = prepared
        self.routed = OrderedDict()
        self.prepared = {}
        self.payload = {}
        self.failed = OrderedDict()
        self.stats = dict(
            layer_id=self.layer_id, z_mm=self.z_mm,
            input=len(self.tasks), attempted=0, success=0, failed=0,
            seconds=0.0, families={}, candidates_evaluated=0,
            candidates_built=0, d56_evaluations=0, obstacle_rejections=0,
            self_rejections=0, rejection_counts={},
            obstacle_samples_total=self.obstacles.total,
            obstacle_samples_active=self.obstacles.kept,
            initial_routes=len(self.initial_routes),
            initial_routes_remapped=remapped,
            rrr=[], frame_errors=dict(self.frame_errors),
        )
        self._rejection_counts = Counter()
        self._family_counts = Counter()
        self._attempted = 0
        self._candidates_built = 0

    # -- candidate iteration -------------------------------------------------
    def _specs(self, route_id, frame, phase=0.0):
        kind = frame['kind']
        cfg = self.cfg
        if kind == 'same':
            yield from _same_side_specs(frame, cfg, phase)
        elif kind == 'opposite':
            yield from _opposite_specs(frame, cfg, phase)
        elif kind == 'adjacent':
            yield from _adjacent_specs(frame, cfg, phase)
        # library family last (independent ``r15.u_geometry`` reference)
        if kind == 'same':
            yield from _library_u_specs(self.tasks[route_id], frame)

    def _iter_candidates(self, route_id, phase):
        """Yield built world chains ordered by family tier, then rank.

        Tier 0 (short robust families) is exhausted before tier 1 is consulted;
        inside one tier the families are interleaved round-robin so that a
        single family cannot monopolise the budget.
        """
        frame = self.frames.get(route_id)
        if frame is None:
            return
        tiers = OrderedDict()
        for spec in self._specs(route_id, frame, phase):
            tier = _family_tier(spec['family'])
            families = tiers.setdefault(tier, OrderedDict())
            families.setdefault(spec['family'], []).append(spec)
        seen_signatures = set()
        for tier in sorted(tiers):
            buckets = tiers[tier]
            rank = 0
            while True:
                emitted = False
                for family in list(buckets):
                    bucket = buckets[family]
                    if rank >= len(bucket):
                        continue
                    emitted = True
                    spec = bucket[rank]
                    world, reason = _build_candidate(spec, frame)
                    if reason is not None:
                        self._rejection_counts[reason] += 1
                        continue
                    signature = _signature(world)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    self._candidates_built += 1
                    self.stats['candidates_built'] = self._candidates_built
                    yield world, spec, signature
                if not emitted:
                    break
                rank += 1

    # -- one route attempt ---------------------------------------------------
    def _attempt(self, route_id, budget, commit=True, phase=0.0,
                 record_failure=True):
        frame = self.frames.get(route_id)
        if frame is None:
            if record_failure:
                self._store_failure(route_id, self.frame_errors.get(
                    route_id, 'invalid_frame'), 0, {}, [])
            return False
        evaluated = 0
        rejection = Counter()
        blockers = set()
        seen = set()
        family = None
        params = None
        chosen = None
        chosen_signature = None
        for world, spec, signature in self._iter_candidates(route_id, phase):
            if evaluated >= budget or self._candidates_built > int(
                    self.cfg['max_candidates_built']):
                break
            evaluated += 1
            prepared = d56_prepare(world)
            self.stats['d56_evaluations'] += 1
            evaluation = self.index.evaluate(prepared)
            if not evaluation.valid:
                rejection[evaluation.reason] += 1
                blockers.update(evaluation.blockers)
                continue
            ok, obstacle_blockers = self.obstacles.check(world, route_id)
            if not ok:
                rejection['obstacle'] += 1
                self.stats['obstacle_rejections'] += 1
                blockers.update(obstacle_blockers)
                continue
            if not _self_clearance_ok(world):
                rejection['self_clearance'] += 1
                self.stats['self_rejections'] += 1
                continue
            chosen = (world, prepared, spec)
            chosen_signature = signature
            break
        if chosen is None:
            primary = 'candidate_budget_exhausted'
            if not rejection:
                primary = ('no_candidate_generated'
                           if evaluated == 0 else 'no_candidate_available')
            elif rejection.get('obstacle', 0) and (
                    rejection['obstacle'] >= max(rejection.values())):
                primary = 'obstacle_blocked'
            if record_failure:
                self._store_failure(route_id, primary, evaluated,
                                    dict(rejection), sorted(blockers, key=str))
            return False
        world, prepared, spec = chosen
        if commit:
            self._commit(route_id, world, prepared, spec, evaluated)
            self._rejection_counts.update(rejection)
            self._candidates_built = 0
        return True

    def _commit(self, route_id, world, prepared, spec, evaluated=1):
        self.index.add(route_id, prepared)
        self.routed[route_id] = world
        self.prepared[route_id] = prepared
        family = spec['family']
        self._family_counts[family] += 1
        self.stats['families'] = dict(self._family_counts)
        self.stats['candidates_evaluated'] += evaluated
        self.payload[route_id] = dict(
            route_id=int(route_id), layer_id=self.layer_id, z_mm=self.z_mm,
            primitives=world, family=family,
            params=dict(spec.get('params') or {}),
            length_mm=_path_length(world),
            candidate_id=f'{int(route_id)}-{family}',
        )
        self.failed.pop(route_id, None)

    def _uncommit(self, route_id):
        if route_id in self.routed:
            self.index.remove(route_id)
            self.routed.pop(route_id, None)
            self.prepared.pop(route_id, None)
            self.payload.pop(route_id, None)

    def _store_failure(self, route_id, reason, evaluated, rejection, blockers):
        self.failed[route_id] = dict(
            route_id=int(route_id), reason=str(reason),
            evaluated=int(evaluated),
            rejection_counts={str(k): int(v) for k, v in
                              sorted(rejection.items())},
            blockers=[b for b in blockers],
        )

    # -- ordering / passes ---------------------------------------------------
    def run(self, budget, rr_rounds, rr_ripmax, ordering_seed,
            log=None):
        log = log or self.log
        started = time.time()
        phase = _candidate_phase(self.cfg, ordering_seed)
        order = _order_tasks(self.tasks, self.frames, ordering_seed)
        for route_id in order:
            self._attempted += 1
            self._attempt(route_id, budget, phase=phase)
        self.stats['attempted'] = self._attempted
        routed_count = len(self.routed)
        failure_count = len(self.failed)
        log(f'[layer2d] L{self.layer_id} first pass: routed={routed_count}/'
            f'{len(self.tasks)} failed={failure_count} '
            f'({time.time() - started:.1f}s)')
        if failure_count and rr_rounds > 0:
            self._ripup_reroute(budget, rr_rounds, rr_ripmax, phase, order,
                                log)
        self.stats['attempted'] = self._attempted
        self.stats['success'] = len(self.routed)
        self.stats['failed'] = len(self.failed)
        self.stats['rejection_counts'] = dict(self._rejection_counts)
        self.stats['seconds'] = float(time.time() - started)
        return self._result()

    def _ripup_reroute(self, budget, rr_rounds, rr_ripmax, phase, order, log):
        best = len(self.routed)
        history = []
        for round_index in range(1, int(rr_rounds) + 1):
            gained = 0
            pending = [rid for rid in order if rid in self.failed]
            for route_id in pending:
                if route_id not in self.failed:
                    continue
                failure = dict(self.failed.get(route_id) or {})
                blockers = []
                for blocker in failure.get('blockers') or ():
                    try:
                        blocker_id = int(blocker)
                    except (TypeError, ValueError):
                        continue
                    if blocker_id in self.routed:
                        blockers.append(blocker_id)
                if not blockers:
                    # retry only (expanded budget, alternate candidate phase)
                    self._attempted += 1
                    if self._attempt(route_id, budget * (round_index + 1),
                                     phase=(phase + 0.5) % 1.0):
                        self.failed.pop(route_id, None)
                        gained += 1
                    else:
                        self.failed[route_id] = failure
                    continue
                rip = blockers[:max(1, int(rr_ripmax))]
                saved = {}
                for blocker_id in rip:
                    saved[blocker_id] = (self.payload.get(blocker_id),
                                         self.prepared.get(blocker_id),
                                         self.routed.get(blocker_id))
                for blocker_id in rip:
                    self._uncommit(blocker_id)
                self._attempted += 1
                placed = self._attempt(route_id, budget,
                                       phase=(phase + 0.5 * round_index) % 1.0)
                restored = True
                if placed:
                    for blocker_id in rip:
                        self._attempted += 1
                        if not self._attempt(blocker_id, budget,
                                             phase=(phase + 0.5) % 1.0):
                            restored = False
                            break
                if placed and restored:
                    self.failed.pop(route_id, None)
                    for blocker_id in rip:
                        self.failed.pop(blocker_id, None)
                    gained += 1
                    continue
                # ---- transactional rollback to the exact previous state ----
                if route_id in self.routed:
                    self._uncommit(route_id)
                for blocker_id in rip:
                    if blocker_id in self.routed:
                        self._uncommit(blocker_id)
                for blocker_id, (payload, prepared, world) in saved.items():
                    if world is None or prepared is None:
                        continue
                    self.index.add(blocker_id, prepared)
                    self.routed[blocker_id] = world
                    self.prepared[blocker_id] = prepared
                    if payload is not None:
                        self.payload[blocker_id] = payload
                    self.failed.pop(blocker_id, None)
                self.failed[route_id] = failure
            current = len(self.routed)
            best = max(best, current)
            history.append(dict(round=round_index, pending=len(pending),
                                gained=gained, routed=current,
                                failed=len(self.failed)))
            log(f'[layer2d] L{self.layer_id} rrr round {round_index}: '
                f'pending={len(pending)} gained={gained} '
                f'routed={current}/{len(self.tasks)}')
            if gained == 0:
                break
        # final bounded retry of whatever is still failed (expanded budget)
        for route_id in [rid for rid in order if rid in self.failed]:
            self._attempted += 1
            if self._attempt(route_id, budget * 2,
                             phase=(phase + 0.75) % 1.0):
                self.failed.pop(route_id, None)
        self.stats['rrr'] = history

    def _result(self):
        stats = dict(self.stats)
        # reconcile the failure list with the real state: failed == assigned - routed
        routed_ids = set(int(rid) for rid in self.routed)
        failed = []
        for route_id in self.tasks:
            if int(route_id) in routed_ids:
                continue
            record = self.failed.get(route_id)
            if record is None:
                record = dict(route_id=int(route_id),
                              reason='unresolved_after_rollback',
                              evaluated=0, rejection_counts={}, blockers=[])
            failed.append(dict(record))
        stats['success'] = len(self.routed)
        stats['failed'] = len(failed)
        stats['families'] = dict(self._family_counts)
        stats['pending_failures'] = {int(r['route_id']): r['reason']
                                     for r in failed}
        return dict(layer_id=self.layer_id, z_mm=self.z_mm,
                    routed=OrderedDict(self.payload),
                    failed=failed, stats=stats)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def route_layer(layer_id, z_mm, tasks, obstacles=None, budget=600,
                rr_rounds=2, rr_ripmax=3, log=print, ordering_seed=0,
                cfg=None, initial_routes=None):
    """Route the 2D bodies of one physical layer.

    Parameters
    ----------
    layer_id : int
    z_mm : float | None
        Layer height; ``None`` resolves ``fanout1024.common.layer_z(layer_id)``.
    tasks : list[dict]
        ``{route_id, A, dA, B, dB, relation?, source_side?, target_side?,
        manual_group?}``.  The body starts at ``A`` heading ``dA`` and must
        arrive at ``B`` heading ``-dB``.
    obstacles : list[dict] | None
        Transition samples ``{x, y, z, route_id, role}`` of other routes.
    budget, rr_rounds, rr_ripmax : int
        Candidate budget per attempt and the bounded rip-up & reroute limits.
    log : callable
    ordering_seed : int
        Varies the deterministic difficulty ordering / candidate ladder phase.
    cfg : dict | None
        Overrides of :data:`DEFAULT_CFG`.
    initial_routes : dict | None
        ``{route_id: primitives}`` of already-placed same-layer bodies.  They
        are inserted into the strict D56 index as frozen blockers (never
        routed/failed, never ripped up); this is the repair primitive used by
        the joint-repair loop to route single failed tasks into a frozen
        layout.

    Returns
    -------
    dict with keys ``layer_id, z_mm, routed, failed, stats`` where ``routed``
    maps route_id -> ``{primitives, family, params, length_mm, candidate_id,
    route_id, layer_id, z_mm}``.
    """
    if z_mm is None:
        z_mm = C.layer_z(int(layer_id))
    merged = dict(DEFAULT_CFG)
    if cfg:
        merged.update(cfg)
    merged['budget'] = int(budget)
    fused = _LayerRouter(layer_id, z_mm, list(tasks or ()), obstacles or (),
                         merged, log, initial_routes=initial_routes)
    return fused.run(int(budget), int(rr_rounds), int(rr_ripmax),
                     int(ordering_seed), log=log)


def _normalize_layer_tasks(layer_tasks):
    """Accept ``{layer: {...}}`` or a plain list of per-layer payloads."""
    if layer_tasks is None:
        return []
    if isinstance(layer_tasks, dict):
        items = []
        for key, value in layer_tasks.items():
            value = dict(value or {})
            layer_id = int(value.get('layer_id', key))
            if 'z_mm' not in value or value.get('z_mm') is None:
                value['z_mm'] = _z_for_layer(layer_id)
            value['layer_id'] = layer_id
            items.append((layer_id, value))
        return sorted(items, key=lambda item: item[0])
    items = []
    for value in layer_tasks:
        value = dict(value or {})
        layer_id = int(value.get('layer_id', value.get('layer')))
        if 'z_mm' not in value or value.get('z_mm') is None:
            value['z_mm'] = _z_for_layer(layer_id)
        value['layer_id'] = layer_id
        items.append((layer_id, value))
    return sorted(items, key=lambda item: item[0])


def _initial_routes_for_layer(initial_routes, layer_id, single_layer):
    """Extract the frozen-body map of one layer from ``initial_routes``."""
    if not initial_routes or not isinstance(initial_routes, dict):
        return None
    for key in (int(layer_id), str(layer_id)):
        if key in initial_routes:
            value = initial_routes[key]
            if isinstance(value, dict):
                return value
    # flat {route_id: primitives} map: unambiguous only for a single layer
    if single_layer and all(isinstance(value, (list, tuple))
                            for value in initial_routes.values()):
        return initial_routes
    return None


def route_all_layers(layer_tasks, out_dir=None, cfg=None, log=print,
                     ordering_seed=0, budget=600, rr_rounds=2, rr_ripmax=3,
                     initial_routes=None):
    """Route every physical layer independently and aggregate the statistics.

    ``layer_tasks`` is ``{layer_id: {'z_mm': float, 'tasks': [...],
    'obstacles': [...]}}`` (a list of such payloads is accepted as well).

    ``initial_routes`` freezes already-placed bodies: either
    ``{layer_id: {route_id: primitives}}`` (recommended) or, when routing a
    single layer, a flat ``{route_id: primitives}`` map.  Frozen bodies are
    strict-D56 blockers only; they never show up in ``routed``/``failed``.

    When ``out_dir`` is given this writes exactly

    * ``<out_dir>/layerwise_routes/routes.json``
    * ``<out_dir>/per_layer.csv``
    * ``<out_dir>/failed_routes.json``

    and nothing else (``run_all.py`` owns the experiment directories/``summary``
    files).  ``out_dir=None`` writes nothing.
    """
    started = time.time()
    items = _normalize_layer_tasks(layer_tasks)
    if initial_routes is not None and not isinstance(initial_routes, dict):
        raise TypeError('initial_routes must be a dict')
    layers = OrderedDict()
    per_layer_rows = []
    failures = []
    total_input = 0
    total_routed = 0
    for layer_id, payload in items:
        tasks = list(payload.get('tasks') or ())
        obstacles = list(payload.get('obstacles') or ())
        z_mm = float(payload['z_mm'])
        frozen = _initial_routes_for_layer(initial_routes, layer_id,
                                           len(items) == 1)
        log(f'[layer2d] routing layer L{layer_id} (z={z_mm:+.2f} mm) '
            f'tasks={len(tasks)} obstacles={len(obstacles)}'
            + (f' initial={len(frozen)}' if frozen else ''))
        result = route_layer(layer_id, z_mm, tasks, obstacles=obstacles,
                             budget=budget, rr_rounds=rr_rounds,
                             rr_ripmax=rr_ripmax, log=log,
                             ordering_seed=ordering_seed, cfg=cfg,
                             initial_routes=frozen)
        layers[int(layer_id)] = result
        stats = result['stats']
        total_input += stats['input']
        total_routed += stats['success']
        failed_list = result['failed']
        for record in failed_list:
            failures.append(dict(record, layer_id=int(layer_id), z_mm=z_mm))
        per_layer_rows.append(dict(
            layer_id=int(layer_id), z_mm=z_mm,
            input=stats['input'], attempted=stats['attempted'],
            routed=stats['success'], failed=stats['failed'],
            seconds=round(float(stats['seconds']), 4),
            candidates_evaluated=stats['candidates_evaluated'],
            d56_evaluations=stats['d56_evaluations'],
            obstacle_rejections=stats['obstacle_rejections'],
            self_rejections=stats['self_rejections'],
            families=json.dumps(stats.get('families') or {},
                                ensure_ascii=False, sort_keys=True),
            failure_reasons=json.dumps(
                {record['reason']: sum(
                    1 for item in failed_list if item['reason'] == record['reason'])
                 for record in failed_list}, ensure_ascii=False, sort_keys=True),
        ))
        log(f'[layer2d] L{layer_id}: routed={stats["success"]}/{stats["input"]} '
            f'failed={stats["failed"]} ({stats["seconds"]:.1f}s)')
    wall = time.time() - started
    total_failed = total_input - total_routed
    result = dict(
        schema='fanout_first_layer2d_routes_v1',
        layers=layers,
        stats=dict(input=total_input, routed=total_routed,
                   failed=total_failed, seconds=float(wall),
                   layers=len(layers),
                   per_layer={int(key): dict(
                       input=value['stats']['input'],
                       routed=value['stats']['success'],
                       failed=value['stats']['failed'],
                       seconds=round(float(value['stats']['seconds']), 4),
                   ) for key, value in layers.items()},
                   families=_aggregate_families(layers)),
    )
    log(f'[layer2d] all layers: routed={total_routed}/{total_input} '
        f'failed={total_failed} ({wall:.1f}s)')
    if out_dir is not None:
        _write_layer_outputs(Path(out_dir), layers, per_layer_rows,
                             failures, result['stats'])
    return result


def _aggregate_families(layers):
    merged = Counter()
    for value in layers.values():
        merged.update(value['stats'].get('families') or {})
    return dict(sorted(merged.items()))


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1,
                               default=_json_default), encoding='utf-8')
    return path


def _json_default(value):
    if isinstance(value, (set, tuple)):
        return list(value)
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:  # pragma: no cover
        pass
    return str(value)


def _write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_layer_outputs(out_dir, layers, per_layer_rows, failures, stats):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    routes_payload = dict(
        schema='fanout_first_layerwise_routes_v1',
        layers={str(layer_id): dict(
            z_mm=value['z_mm'],
            routes={str(route_id): payload
                    for route_id, payload in value['routed'].items()},
            failed=value['failed'],
        ) for layer_id, value in layers.items()},
        stats=stats,
    )
    _write_json(out_dir / 'layerwise_routes' / 'routes.json', routes_payload)
    _write_csv(out_dir / 'per_layer.csv', per_layer_rows,
               ['layer_id', 'z_mm', 'input', 'attempted', 'routed', 'failed',
                'seconds', 'candidates_evaluated', 'd56_evaluations',
                'obstacle_rejections', 'self_rejections', 'families',
                'failure_reasons'])
    _write_json(out_dir / 'failed_routes.json',
                dict(total=len(failures), failures=failures))


def write_experiment_c(result, out_dir, log=print):
    """Write the standalone ``experiment_C`` artifacts of a routing result.

    Files: ``summary.json``, ``per_layer.csv``, ``failed_routes.json``,
    ``validation_status.json``.  Used by the self-tests / standalone runs;
    ``run_all.py`` writes the experiment directories itself.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    layers = result.get('layers') or {}
    per_layer = []
    failures = []
    total_input = total_routed = 0
    family_counts = Counter()
    reason_counts = Counter()
    for layer_id, value in sorted(layers.items(), key=lambda item: int(item[0])):
        stats = value['stats']
        total_input += int(stats['input'])
        total_routed += int(stats['success'])
        family_counts.update(stats.get('families') or {})
        for record in value['failed']:
            failures.append(dict(record, layer_id=int(layer_id),
                                 z_mm=value['z_mm']))
            reason_counts[record['reason']] += 1
        per_layer.append(dict(
            layer_id=int(layer_id), z_mm=value['z_mm'],
            input=stats['input'], attempted=stats['attempted'],
            routed=stats['success'], failed=stats['failed'],
            seconds=round(float(stats['seconds']), 4),
            candidates_evaluated=stats['candidates_evaluated'],
            families=json.dumps(stats.get('families') or {},
                                ensure_ascii=False, sort_keys=True),
        ))
    summary = dict(
        stage='experiment_C',
        input_routes=total_input,
        attempted_routes=total_input,
        routed_routes=total_routed,
        failed_routes=total_input - total_routed,
        failure_reasons=dict(sorted(reason_counts.items())),
        families=dict(sorted(family_counts.items())),
        per_layer=per_layer,
        wall_seconds=float(result.get('stats', {}).get('seconds') or 0.0),
    )
    _write_json(out_dir / 'summary.json', summary)
    _write_csv(out_dir / 'per_layer.csv', per_layer,
               ['layer_id', 'z_mm', 'input', 'attempted', 'routed', 'failed',
                'seconds', 'candidates_evaluated', 'families'])
    _write_json(out_dir / 'failed_routes.json',
                dict(total=len(failures), failures=failures))
    _write_json(out_dir / 'validation_status.json', dict(
        status='passed' if total_routed == total_input else 'incomplete',
        routed=total_routed, input=total_input,
        failed=total_input - total_routed,
        note='experiment C 2D body routing of the manual layers; independent '
             '3D route validation is performed by the final validator.'))
    log(f'[layer2d] wrote experiment_C to {out_dir} '
        f'(routed={total_routed}/{total_input})')
    return summary


# ---------------------------------------------------------------------------
# assignment / landing helpers (integration + standalone tests)
# ---------------------------------------------------------------------------
def footprint_mm(dz_mm, radius=R15):
    """Transition footprint of the two-arc S-curve (DESIGN.md section 2)."""
    dz = abs(float(dz_mm))
    if dz <= 0.0:
        return 0.0
    if dz >= 2.0 * radius:
        raise ValueError('layer drop exceeds the two-arc transition reach')
    return 2.0 * radius * math.sin(math.acos(1.0 - dz / (2.0 * radius)))


def synthesize_landings(rows, lead=2.0, radius=R15, endpoints=None,
                        plane_z=None):
    """Build ``{route_id: {'A','dA','B','dB'}}`` from the true port table.

    ``A = P_s + (lead + footprint) * d_s`` and
    ``B = P_t + (lead + footprint) * d_t`` with
    ``footprint = 2R sin(acos(1 - |z_t - z_0|/(2R)))``.

    Rows with ``needs_transition`` false (interface-direct routes) get
    ``A = P_s`` / ``B = P_t`` (no lead, no transition); ``plane_z`` optionally
    supplies ``{layer_id: z_mm}`` for layer ids outside ``common.PHYSICAL_LAYERS``
    (e.g. the 21-height experiment's interface planes 1001/1002).
    """
    eps = endpoints if endpoints is not None else C.endpoints()
    out = {}
    for row in rows:
        route_id = int(row['route_id'])
        plane = str(row.get('plane') or 'z1')
        z0 = C.interface_z(plane)
        source = eps[str(row['source_endpoint'])]
        target = eps[str(row['target_endpoint'])]
        d_s = (float(source['inward'][0]), float(source['inward'][1]))
        d_t = (float(target['inward'][0]), float(target['inward'][1]))
        p_s = (float(source['routing_xy'][0]), float(source['routing_xy'][1]))
        p_t = (float(target['routing_xy'][0]), float(target['routing_xy'][1]))
        needs_transition = row.get('needs_transition')
        direct = needs_transition is not None and not _truthy(needs_transition)
        if direct:
            out[route_id] = dict(A=p_s, dA=d_s, B=p_t, dB=d_t,
                                 direct=True)
            continue
        target_layer = row.get('target_layer')
        if target_layer is None:
            target_layer = row.get('physical_layer')
        target_z = row.get('target_z_mm')
        if target_z is None or target_z == '':
            if plane_z is not None and int(target_layer) in plane_z:
                target_z = plane_z[int(target_layer)]
            elif plane_z is not None and str(target_layer) in plane_z:
                target_z = plane_z[str(target_layer)]
            else:
                target_z = C.layer_z(int(target_layer))
        target_z = float(target_z)
        drop = footprint_mm(target_z - z0, radius=radius) + float(lead)
        out[route_id] = dict(
            A=(p_s[0] + drop * d_s[0], p_s[1] + drop * d_s[1]),
            dA=d_s,
            B=(p_t[0] + drop * d_t[0], p_t[1] + drop * d_t[1]),
            dB=d_t,
        )
    return out


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y')
    return bool(value)


def _z_for_layer(layer_id, plane_z=None):
    """Resolve a plane height: explicit map first, then ``common.layer_z``."""
    if plane_z is not None:
        if layer_id in plane_z:
            return float(plane_z[layer_id])
        if str(layer_id) in plane_z:
            return float(plane_z[str(layer_id)])
    try:
        return float(C.layer_z(int(layer_id)))
    except KeyError:
        raise KeyError(
            f'no z_mm supplied for layer id {layer_id!r}: pass an explicit '
            'z_mm per layer (or a plane_z map) for heights outside '
            'common.PHYSICAL_LAYERS, e.g. the 21-height experiment ids '
            '20/1001/1002')


def make_tasks_from_assignment(assignment_rows, landings, obstacles=None,
                               plane_z=None):
    """Turn assignment rows + landing poses into ``layer_tasks`` input.

    ``assignment_rows`` are dicts with at least ``route_id``, ``target_layer``
    (or ``physical_layer``), ``target_z_mm`` (optional), ``plane`` and the port
    fields; ``landings`` is ``{route_id: {'A','dA','B','dB'}}``.  When a landing
    pose is missing it is synthesised from the true port table with ``lead=2``.
    ``obstacles`` may be a prebuilt ``{layer_id: [...]}`` map and ``plane_z`` an
    optional ``{layer_id: z_mm}`` map for layer ids outside the baseline 18
    body layers (21-height experiment ids 20/1001/1002).
    """
    by_id = {}
    for row in assignment_rows:
        by_id[int(row['route_id'])] = row
    landing_map = {}
    for key, pose in (landings or {}).items():
        landing_map[int(key)] = pose
    missing = [row for route_id, row in by_id.items()
               if route_id not in landing_map]
    if missing:
        landing_map.update(synthesize_landings(missing, plane_z=plane_z))
    obstacles = obstacles or {}
    layer_tasks = OrderedDict()
    for route_id, row in sorted(by_id.items()):
        layer_id = row.get('target_layer')
        if layer_id is None:
            layer_id = row.get('physical_layer')
        layer_id = int(layer_id)
        pose = landing_map[route_id]
        entry = layer_tasks.setdefault(layer_id, dict(
            layer_id=layer_id, z_mm=_z_for_layer(layer_id, plane_z),
            tasks=[], obstacles=list(obstacles.get(layer_id) or
                                     obstacles.get(str(layer_id)) or [])))
        entry['tasks'].append(dict(
            route_id=int(route_id),
            manual_group=row.get('manual_group') or '',
            relation=row.get('relation') or row.get('logical_kind') or '',
            source_side=row.get('source_side'),
            target_side=row.get('target_side'),
            A=(float(pose['A'][0]), float(pose['A'][1])),
            dA=(float(pose['dA'][0]), float(pose['dA'][1])),
            B=(float(pose['B'][0]), float(pose['B'][1])),
            dB=(float(pose['dB'][0]), float(pose['dB'][1])),
        ))
    return layer_tasks
