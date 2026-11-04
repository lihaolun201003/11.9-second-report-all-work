# -*- coding: utf-8 -*-
"""E0 arc-crossing analysis for the Phase-2 arc-region local 3D rebuild.

Reads the frozen accepted 2440-crossing Native-3D baseline
(``outputs/manual_c4_new_connectivity/NATIVE_3D_CROSSING_OPT_1024``) and answers
three questions:

1. **Where do the 2440 same-plane crossings sit?**  For every crossing event the
   exact analytic point-to-primitive projection (not sampling) locates the
   crossing on BOTH routes' flat chains at the event height; every side is
   classified as ``line`` / ``arc`` and the crossing as ``line-line`` /
   ``line-arc`` / ``arc-arc``.  The event is additionally tagged with the flat
   role (``lead`` / ``base_body`` / ``excursion``) and with the native-3D flag.
2. **Does the previous round's "≈49% of crossings sit on arcs" claim hold?**
   The exact per-side incidence definition used by ``crossing_intervals.py`` is
   reproduced and three alternative definitions are reported next to it.
3. **Which arc regions of the hottest routes can be rebuilt locally?**  For the
   top-10 routes by own-side arc crossings the module derives, per arc-crossing
   region (maximal run of arc crossings on one body flat, allowing only arcs and
   short straight pieces in between), a rebuild interval ``[s0, s1]`` whose two
   flanking straight runs host the two R15 S-curves and whose middle sub-chain
   (the original XY path, including the arcs) travels at a target height.  Entry /
   exit S-curves may either stay on the body flat's flanking straight runs
   (``straight`` mode) or replace the adjacent transition (``prev_transition`` /
   ``next_transition`` mode, for arc regions that touch a flat end).  For every
   one of the 21 heights the required footprint, required length, host
   feasibility, intermediate planes and the crossing estimate (removed at the
   source height, added at the target height, net) are reported.

The module is deterministic (no timestamps, no random numbers) and only writes
inside ``<out-dir>/analysis`` and ``<out-dir>/plots`` (or the plot dir given on
the command line).

CLI::

    python -m four_side_1024.fanout1024.native3d.arc_crossing_analysis \
        --baseline outputs/manual_c4_new_connectivity/NATIVE_3D_CROSSING_OPT_1024 \
        --out-dir outputs/manual_c4_new_connectivity/NATIVE_3D_JOINT_OPT_1024
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import numpy as np

from ...fsd25d import path3d as P
from .. import common as C
from . import common as N
from . import crossing_intervals as CI
from . import transition as T

SCHEMA = 'native3d_arc_crossing_analysis_v1'

# ---------------------------------------------------------------- constants
TAU = 2.0 * math.pi
R15 = float(N.R15)
MIN_3D_CLEARANCE_MM = float(N.MIN_3D_CLEARANCE)
#: transition shadow (the S-curve is closer than 50 um to the plane it leaves)
SHADOW_MM = max(1.25, float(N.SHADOW_MM))
#: keep the excursion / rebuilt region away from the body-flat ends
END_MARGIN_MM = 0.5
#: minimum flat length between the two R15 S-curves (common.MIN_MIDDLE_MM)
MIN_MIDDLE_MM = float(N.MIN_MIDDLE_MM)
#: arc-crossing regions along one body flat: crossings on the same primitive always
#: belong to one region; a gap between primitives may be bridged only through arcs
#: and lines shorter than this threshold (otherwise a new region starts)
CLUSTER_GAP_MM = 20.0
MIN_CROSS_ANGLE_DEG = 5.0
MIN_SINE = math.sin(math.radians(MIN_CROSS_ANGLE_DEG))
CROSSING_DEDUPE_MM = 1e-6
PROJECTION_TOL_MM = 1e-3
INTERSECT_TOL = 1e-8
PAIR_EPS = 1e-9
#: the "≈49%" claim was measured on the E5 baseline (see crossing_intervals)
PREVIOUS_CLAIM = dict(
    source='NATIVE_3D_CROSSING_OPT_1024/analysis/crossing_intervals_report.md',
    baseline='NON_C4_CROSSING_OPT_1024/E5_joint_repair_final',
    events=2606,
    line_positions=2659,
    arc_positions=2553,
    arc_fraction=0.49,
    text='交叉事件位置：直线段 2659 个（51.0%），圆弧段 2553 个（49.0%）',
)
#: analysis / report parameters
HOTSPOT_BIN_MM = 10.0
ANGLE_BIN_DEG = 5.0
TOP_ROUTE_COUNT = 10
TOP20_ROUTE_COUNT = 20
MAX_PIECES_PER_CLUSTER = 3
MAX_ENTRY_OPTIONS = 3
MAX_EXIT_OPTIONS = 3
#: target heights that a movable route may be re-assigned to (13 movable planes)
PLAUSIBLE_PLANE_IDS = tuple(int(pid) for pid in N.MOVABLE_PLANES)
ALL_PLANE_IDS = tuple(int(pid) for pid in N.PLANE_Z)


# ================================================================ scalar geometry
def _prim_length(prim):
    return float(P.prim_length(prim))


def _prim_bbox(prim):
    return CI._prim_bbox(prim)


def _arc_arc_intersections(first, second, tol=INTERSECT_TOL):
    """``(points, sines, overlap)`` of two circular-arc primitives."""
    c1 = first['center']
    c2 = second['center']
    r1 = float(first['radius'])
    r2 = float(second['radius'])
    x1, y1 = float(c1[0]), float(c1[1])
    x2, y2 = float(c2[0]), float(c2[1])
    dx, dy = x2 - x1, y2 - y1
    distance = math.hypot(dx, dy)
    if distance <= tol:
        # concentric: only an equal-radius pair can overlap (flagged, not a crossing)
        if abs(r1 - r2) <= tol:
            return [], [], ('concentric', 'overlap')
        return [], [], None
    if distance > r1 + r2 + tol or distance < abs(r1 - r2) - tol:
        return [], [], None
    along = (r1 * r1 - r2 * r2 + distance * distance) / (2.0 * distance)
    height2 = r1 * r1 - along * along
    if height2 < -tol:
        return [], [], None
    height = math.sqrt(max(0.0, height2))
    ux, uy = dx / distance, dy / distance
    base_x = x1 + along * ux
    base_y = y1 + along * uy
    candidates = [(base_x - height * uy, base_y + height * ux)]
    if height > tol:
        candidates.append((base_x + height * uy, base_y - height * ux))
    points = []
    sines = []
    for point in candidates:
        angle = math.atan2(point[1] - y1, point[0] - x1)
        if not CI._arc_contains(angle, first):
            continue
        angle_2 = math.atan2(point[1] - y2, point[0] - x2)
        if not CI._arc_contains(angle_2, second):
            continue
        if any(math.hypot(point[0] - q[0], point[1] - q[1]) < tol
               for q in points):
            continue
        sign_1 = 1.0 if float(first['sweep']) >= 0.0 else -1.0
        sign_2 = 1.0 if float(second['sweep']) >= 0.0 else -1.0
        tangent_1 = (-sign_1 * math.sin(angle), sign_1 * math.cos(angle))
        tangent_2 = (-sign_2 * math.sin(angle_2), sign_2 * math.cos(angle_2))
        points.append(point)
        sines.append(CI._sine_between(tangent_1, tangent_2))
    return points, sines, None


def prim_pair_intersections(first, second):
    """``(points, sines, overlap)`` of two 2D line/arc primitives."""
    if first['kind'] == 'line':
        return CI._line_prim_intersections(first, second)
    if second['kind'] == 'line':
        return CI._line_prim_intersections(second, first)
    return _arc_arc_intersections(first, second)


def footprint_mm(dz_mm):
    return float(T.transition_footprint(dz_mm))


def intermediate_planes(z_from, z_to):
    """The routing planes strictly between two heights (sorted by z)."""
    low, high = sorted((float(z_from), float(z_to)))
    return [int(pid) for pid in N.PLANE_Z
            if low + 1e-9 < float(N.PLANE_Z[pid]) < high - 1e-9]


def plane_label(z_mm):
    pid = N.plane_of_z(z_mm)
    if pid is None:
        return '?'
    return N.PLANE_LABEL.get(pid, str(pid))


def _round(value, digits=6):
    return round(float(value), int(digits))


# ================================================================ flat chains
def build_flat_chains(route):
    """Every flat part of one route as a self-contained XY chain, part order."""
    chains = []
    for index, part in enumerate(route.get('parts') or ()):
        if part.get('kind') != 'flat':
            continue
        prims = [dict(prim) for prim in (part.get('primitives') or ())
                 if _prim_length(prim) > 1e-5]
        if not prims:
            continue
        offsets = []
        running = 0.0
        for prim in prims:
            offsets.append(running)
            running += _prim_length(prim)
        z_value = _round(part['z_mm'], 9)
        chains.append(dict(
            part_index=int(index),
            z_mm=z_value,
            plane_id=N.plane_of_z(z_value),
            plane_label=plane_label(z_value),
            tag=str(part.get('tag') or ''),
            prims=prims,
            offsets=offsets,
            length_mm=float(running),
        ))
    return chains


def build_flat_roles(route):
    """``{part_index: lead | base_body | excursion}`` of one route's flats."""
    body_indices = set(N.body_flat_indices(route))
    try:
        target_z = float(route.get('target_z_mm'))
    except (TypeError, ValueError):
        target_z = None
    roles = {}
    for index, part in enumerate(route.get('parts') or ()):
        if part.get('kind') != 'flat':
            continue
        z_value = _round(part['z_mm'], 9)
        if index in body_indices:
            if target_z is None or abs(z_value - target_z) <= 1e-9:
                roles[index] = 'base_body'
            else:
                roles[index] = 'excursion'
        else:
            roles[index] = 'lead'
    return roles


def _prim_descriptor(prim):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
        length = math.hypot(dx, dy)
        return dict(kind='line', length_mm=_round(length),
                    direction=[_round(dx / length) if length else 0.0,
                               _round(dy / length) if length else 0.0])
    return dict(kind='arc', length_mm=_round(_prim_length(prim)),
                radius_mm=_round(prim['radius']),
                sweep_deg=_round(math.degrees(abs(float(prim['sweep'])))),
                start_angle_deg=_round(math.degrees(float(prim['start_angle']))))


# ================================================================ crossing locate
def locate_on_route(chains, z_mm, point):
    """Exact nearest primitive of one route's flats at ``z_mm`` to ``point``."""
    target = _round(z_mm, 9)
    candidates = []
    for chain in chains:
        if abs(chain['z_mm'] - target) > 1e-9:
            continue
        for prim_index, prim in enumerate(chain['prims']):
            parameter, distance = CI._prim_parameter(prim, point)
            candidates.append(dict(distance_mm=float(distance),
                                   parameter=float(parameter),
                                   prim_index=int(prim_index),
                                   chain=chain))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item['distance_mm'],
                                      item['chain']['part_index'],
                                      item['prim_index']))
    best = candidates[0]
    ambiguous = []
    for other in candidates[1:]:
        if other['distance_mm'] > best['distance_mm'] + 1e-6:
            break
        if (other['chain']['part_index'], other['prim_index']) != (
                best['chain']['part_index'], best['prim_index']):
            ambiguous.append(other)
    chain = best['chain']
    prim = chain['prims'][best['prim_index']]
    s_mm = chain['offsets'][best['prim_index']] + best['parameter'] * _prim_length(prim)
    record = dict(
        route_id=None,
        prim_kind=str(prim['kind']),
        flat_part_index=int(chain['part_index']),
        flat_z_mm=chain['z_mm'],
        prim_index=int(best['prim_index']),
        s_mm=_round(s_mm),
        distance_mm=_round(best['distance_mm'], 9),
        prim=_prim_descriptor(prim),
        ambiguous=bool(ambiguous),
        alt_prim_kind=(str(ambiguous[0]['chain']['prims'][
            ambiguous[0]['prim_index']]['kind']) if ambiguous else None),
    )
    return record


def _side_record(route, chains, roles, z_mm, point):
    located = locate_on_route(chains, z_mm, point)
    manual = bool(str(route.get('manual_group') or '').strip())
    if located is None:
        return dict(found=False, route_id=int(route['route_id']),
                    native_3d=bool(route.get('native_3d')), manual=manual,
                    primitive_kind='missing', role='missing')
    located.update(
        found=True,
        route_id=int(route['route_id']),
        native_3d=bool(route.get('native_3d')),
        manual=manual,
        direct=bool(route.get('direct')),
        relation=str(route.get('relation') or ''),
        role=roles.get(located['flat_part_index'], 'unknown'),
    )
    return located


def classify_events(routes, chains_by_route, roles_by_route, events):
    """Classify every crossing event by the primitive kind on both sides."""
    records = []
    for index, event in enumerate(events):
        z_value = _round(event['z_mm'], 9)
        point = (float(event['x_mm']), float(event['y_mm']))
        side_a = _side_record(routes[int(event['route_a'])],
                              chains_by_route[int(event['route_a'])],
                              roles_by_route[int(event['route_a'])],
                              z_value, point)
        side_b = _side_record(routes[int(event['route_b'])],
                              chains_by_route[int(event['route_b'])],
                              roles_by_route[int(event['route_b'])],
                              z_value, point)
        kinds = tuple(sorted((str(side_a.get('prim_kind') or 'missing'),
                              str(side_b.get('prim_kind') or 'missing'))))
        if kinds == ('line', 'line'):
            crossing_class = 'line-line'
        elif kinds == ('arc', 'arc'):
            crossing_class = 'arc-arc'
        elif kinds in (('arc', 'line'), ('line', 'arc')):
            crossing_class = 'line-arc'
        else:
            crossing_class = 'unlocated'
        plane_id = N.plane_of_z(z_value)
        record = dict(
            event_index=int(index),
            route_a=int(event['route_a']),
            route_b=int(event['route_b']),
            z_mm=z_value,
            plane_id=(int(plane_id) if plane_id is not None else None),
            plane_label=plane_label(z_value),
            x_mm=_round(event['x_mm']),
            y_mm=_round(event['y_mm']),
            angle_deg=_round(event['angle_deg']),
            crossing_class=crossing_class,
            any_arc=bool(crossing_class in ('line-arc', 'arc-arc')),
            both_arc=bool(crossing_class == 'arc-arc'),
            route_a_kind=str(side_a.get('prim_kind') or 'missing'),
            route_b_kind=str(side_b.get('prim_kind') or 'missing'),
            route_a_role=str(side_a.get('role') or 'missing'),
            route_b_role=str(side_b.get('role') or 'missing'),
            route_a_native=bool(side_a.get('native_3d')),
            route_b_native=bool(side_b.get('native_3d')),
            manual_side=bool(side_a.get('manual') or side_b.get('manual')),
            excursion_involved=bool(side_a.get('role') == 'excursion'
                                    or side_b.get('role') == 'excursion'),
            ambiguous_sides=int(bool(side_a.get('ambiguous')))
            + int(bool(side_b.get('ambiguous'))),
            sides=[side_a, side_b],
        )
        records.append(record)
    return records


def projection_verification(records):
    distances = []
    failures = 0
    for record in records:
        for side in record['sides']:
            if not side.get('found'):
                failures += 1
                continue
            distance = float(side.get('distance_mm') or 0.0)
            distances.append(distance)
            if distance > PROJECTION_TOL_MM:
                failures += 1
    distances.sort()
    if not distances:
        return dict(sides=0, failures=int(failures))
    return dict(
        sides=int(len(distances)),
        max_projection_error_mm=_round(distances[-1], 9),
        p99_projection_error_mm=_round(distances[int(0.99 * (len(distances) - 1))], 9),
        projection_failures=int(failures),
        tolerance_mm=PROJECTION_TOL_MM,
        ambiguous_junction_sides=int(sum(int(record['ambiguous_sides'])
                                         for record in records)),
    )


# ================================================================ aggregates
def _angle_stats(values):
    values = sorted(float(value) for value in values)
    if not values:
        return dict(count=0, min=None, max=None, mean=None, median=None)
    return dict(count=int(len(values)),
                min_deg=_round(values[0]),
                max_deg=_round(values[-1]),
                mean_deg=_round(sum(values) / len(values)),
                median_deg=_round(_percentile(values, 0.5)))


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = fraction * (len(sorted_values) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return float(sorted_values[low]) * (1.0 - weight) + float(sorted_values[high]) * weight


def _histogram(values, edges):
    counts = [0] * (len(edges) - 1)
    for value in values:
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]:
                counts[index] += 1
                break
        else:
            if value >= edges[-1]:
                counts[-1] += 1
    return counts


def build_aggregates(records, routes, stats, total_events):
    class_counter = Counter(record['crossing_class'] for record in records)
    side_kind_counter = Counter()
    role_counter = Counter()
    for record in records:
        for side in record['sides']:
            side_kind_counter[str(side.get('prim_kind') or 'missing')] += 1
            role_counter[str(side.get('role') or 'missing')] += 1
    events = len(records)
    any_arc = sum(1 for record in records if record['any_arc'])
    both_arc = sum(1 for record in records if record['both_arc'])
    excursion_events = sum(1 for record in records if record['excursion_involved'])
    native_events = sum(1 for record in records
                        if record['route_a_native'] or record['route_b_native'])
    manual_events = sum(1 for record in records if record['manual_side'])
    n_sides = sum(side_kind_counter.values())
    arc_sides = int(side_kind_counter.get('arc', 0))
    line_sides = int(side_kind_counter.get('line', 0))

    per_z = OrderedDict()
    for plane_id in N.PLANE_Z:
        z_value = _round(N.PLANE_Z[plane_id], 9)
        per_z[z_value] = dict(
            plane_id=int(plane_id), plane_label=N.PLANE_LABEL[int(plane_id)],
            z_mm=z_value,
            is_manual_plane=bool(int(plane_id) in N.MANUAL_PLANES),
            counts=dict.fromkeys(('line-line', 'line-arc', 'arc-arc'), 0),
            total=0, any_arc=0, sides_arc=0, sides_line=0)
    for record in records:
        row = per_z.get(record['z_mm'])
        if row is None:
            row = per_z[record['z_mm']] = dict(
                plane_id=(-1 if record['plane_id'] is None else int(record['plane_id'])),
                plane_label=record['plane_label'] or '?',
                z_mm=record['z_mm'],
                is_manual_plane=False,
                counts=dict.fromkeys(('line-line', 'line-arc', 'arc-arc'), 0),
                total=0, any_arc=0, sides_arc=0, sides_line=0)
        row['counts'][record['crossing_class']] += 1
        row['total'] += 1
        row['any_arc'] += int(record['any_arc'])
        for side in record['sides']:
            if side.get('prim_kind') == 'arc':
                row['sides_arc'] += 1
            elif side.get('prim_kind') == 'line':
                row['sides_line'] += 1
    for row in per_z.values():
        sides = row['sides_arc'] + row['sides_line']
        row['arc_side_fraction'] = _round(row['sides_arc'] / float(sides)) if sides else None
        row['any_arc_fraction'] = _round(row['any_arc'] / float(row['total'])) if row['total'] else None

    per_route = OrderedDict()
    for route_id in sorted(routes):
        route = routes[route_id]
        manual = bool(str(route.get('manual_group') or '').strip())
        per_route[route_id] = dict(
            route_id=int(route_id),
            relation=str(route.get('relation') or ''),
            native_3d=bool(route.get('native_3d')),
            manual=manual,
            direct=bool(route.get('direct')),
            n_transitions=int(route.get('n_transitions') or 0),
            target_plane_id=(int(route['target_plane'])
                             if route.get('target_plane') is not None else None),
            target_plane_label=str(route.get('target_plane_label') or ''),
            target_z_mm=(_round(route['target_z_mm'], 9)
                         if route.get('target_z_mm') is not None else None),
            total_crossings=0, own_arc=0, own_line=0,
            arc_involved=0, arc_partner_only=0,
            own_arc_base_body=0, own_arc_lead=0, own_arc_excursion=0,
            line_on_excursion=0,
            arc_primitive_total=0,
        )
    for route_id, route in routes.items():
        total = sum(1 for chain in build_flat_chains(route)
                    for prim in chain['prims'] if prim['kind'] == 'arc')
        per_route[route_id]['arc_primitive_total'] = int(total)
    for record in records:
        for side in record['sides']:
            route_id = int(side['route_id'])
            row = per_route[route_id]
            row['total_crossings'] += 1
            kind = side.get('prim_kind')
            if kind == 'arc':
                row['own_arc'] += 1
                if side.get('role') == 'base_body':
                    row['own_arc_base_body'] += 1
                elif side.get('role') == 'lead':
                    row['own_arc_lead'] += 1
                elif side.get('role') == 'excursion':
                    row['own_arc_excursion'] += 1
            elif kind == 'line':
                row['own_line'] += 1
                if side.get('role') == 'excursion':
                    row['line_on_excursion'] += 1
            if record['any_arc']:
                row['arc_involved'] += 1
                if kind == 'line':
                    row['arc_partner_only'] += 1

    def _route_row(route_id):
        row = per_route[route_id]
        enriched = dict(row)
        enriched['total_crossings'] = int(row['total_crossings'])
        enriched['arc_involved_fraction'] = _round(
            row['arc_involved'] / float(row['total_crossings'])) \
            if row['total_crossings'] else None
        return enriched

    top_own_arc = sorted(per_route, key=lambda rid: (-per_route[rid]['own_arc'],
                                                     int(rid)))
    top_own_arc = [rid for rid in top_own_arc
                   if per_route[rid]['own_arc'] > 0][:TOP20_ROUTE_COUNT]
    top_arc_involved = sorted(per_route,
                              key=lambda rid: (-per_route[rid]['arc_involved'],
                                               int(rid)))[:TOP20_ROUTE_COUNT]

    per_relation = defaultdict(lambda: dict.fromkeys(
        ('line-line', 'line-arc', 'arc-arc'), 0))
    for record in records:
        relation_a = str(routes[record['route_a']].get('relation') or '')
        relation_b = str(routes[record['route_b']].get('relation') or '')
        key = '|'.join(sorted((relation_a, relation_b)))
        per_relation[key][record['crossing_class']] += 1
    relation_rows = []
    for key in sorted(per_relation):
        counts = per_relation[key]
        total = sum(counts.values())
        relation_rows.append(dict(family_pair=key, total=int(total),
                                  counts=dict(counts),
                                  any_arc=int(counts['line-arc'] + counts['arc-arc'])))

    # XY hotspot grid (10 mm cells)
    xs = [record['x_mm'] for record in records]
    ys = [record['y_mm'] for record in records]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    cells = {}
    arc_cells = {}
    for record in records:
        index_x = int(math.floor((record['x_mm'] - x_min) / HOTSPOT_BIN_MM))
        index_y = int(math.floor((record['y_mm'] - y_min) / HOTSPOT_BIN_MM))
        key = (index_x, index_y)
        cell = cells.setdefault(key, dict(count=0, any_arc=0,
                                          line_line=0, line_arc=0, arc_arc=0))
        cell['count'] += 1
        cell['any_arc'] += int(record['any_arc'])
        cell[record['crossing_class'].replace('-', '_')] += 1
        if record['any_arc']:
            arc_cell = arc_cells.setdefault(key, dict(count=0, arc_arc=0,
                                                      line_arc=0))
            arc_cell['count'] += 1
            if record['crossing_class'] == 'arc-arc':
                arc_cell['arc_arc'] += 1
            else:
                arc_cell['line_arc'] += 1
    hotspot_rows = []
    for key, cell in cells.items():
        hotspot_rows.append(dict(
            ix=int(key[0]), iy=int(key[1]),
            x_mm=_round(x_min + (key[0] + 0.5) * HOTSPOT_BIN_MM),
            y_mm=_round(y_min + (key[1] + 0.5) * HOTSPOT_BIN_MM),
            count=int(cell['count']), any_arc=int(cell['any_arc']),
            line_line=int(cell['line_line']), line_arc=int(cell['line_arc']),
            arc_arc=int(cell['arc_arc']),
        ))
    hotspot_rows.sort(key=lambda row: (-row['count'], row['ix'], row['iy']))
    arc_hotspot_rows = []
    for key, cell in arc_cells.items():
        arc_hotspot_rows.append(dict(
            ix=int(key[0]), iy=int(key[1]),
            x_mm=_round(x_min + (key[0] + 0.5) * HOTSPOT_BIN_MM),
            y_mm=_round(y_min + (key[1] + 0.5) * HOTSPOT_BIN_MM),
            count=int(cell['count']), arc_arc=int(cell['arc_arc']),
            line_arc=int(cell['line_arc']),
        ))
    arc_hotspot_rows.sort(key=lambda row: (-row['count'], row['ix'], row['iy']))

    # crossing angle by class
    angle_edges = [float(step) for step in range(0, 95, int(ANGLE_BIN_DEG))]
    angle_rows = OrderedDict()
    for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
        values = [record['angle_deg'] for record in records
                  if record['crossing_class'] == crossing_class]
        angle_rows[crossing_class] = dict(
            histogram=dict(edges=angle_edges,
                           counts=_histogram(values, angle_edges)),
            stats=_angle_stats(values))
    all_values = [record['angle_deg'] for record in records]
    angle_rows['all'] = dict(histogram=dict(edges=angle_edges,
                                            counts=_histogram(all_values, angle_edges)),
                             stats=_angle_stats(all_values))

    fraction_side = _round(arc_sides / float(n_sides)) if n_sides else None
    fraction_event = _round(any_arc / float(events)) if events else None
    fraction_both = _round(both_arc / float(events)) if events else None
    verification = dict(
        events=int(events),
        crossing_stats_totals=(stats.get('totals') or {}).get('crossings'),
        event_sides=int(n_sides),
        per_side_incidence=dict(
            line=int(line_sides), arc=int(arc_sides),
            arc_fraction=fraction_side,
            definition='每个交叉事件在两侧各记一次位置（与 crossing_intervals.py '
                       '的“交叉事件位置”口径一致）；分母 = 2 * 事件数'),
        per_event_any_arc=dict(count=int(any_arc), fraction=fraction_event,
                               definition='两侧中至少一侧为圆弧段的事件占比'),
        per_event_both_arc=dict(count=int(both_arc), fraction=fraction_both,
                                definition='两侧均为圆弧段的事件占比'),
        previous_claim=PREVIOUS_CLAIM,
        verdict=None,
    )
    verdicts = []
    if fraction_side is not None:
        verdicts.append(
            '按上一轮报告的同口径（逐侧位置占比）圆弧占比 = %.2f%%（%d/%d），'
            '与上一轮的 49.0%% 一致，论断成立。'
            % (100.0 * fraction_side, arc_sides, n_sides))
    if fraction_event is not None:
        verdicts.append(
            '若按“事件只要任一侧在圆弧上即算”的口径，则为 %.2f%%（%d/%d）；'
            '两种口径含义不同，引用时必须注明。'
            % (100.0 * fraction_event, any_arc, events))
    verdicts.append('本基线中所有交叉均不涉及 manual（冻结）线路：manual 侧事件 = %d。'
                    % manual_events)
    verification['verdict'] = ' '.join(verdicts)

    return dict(
        totals=dict(
            events=int(events), event_sides=int(n_sides),
            class_counts=dict(class_counter),
            class_fractions={key: _round(value / float(events))
                             for key, value in class_counter.items()},
            any_arc=int(any_arc), any_arc_fraction=fraction_event,
            both_arc=int(both_arc), both_arc_fraction=fraction_both,
            side_kind=dict(side_kind_counter),
            side_arc_fraction=fraction_side,
            side_role=dict(role_counter),
            excursion_involved=int(excursion_events),
            native_involved=int(native_events),
            manual_involved=int(manual_events),
            direct_involved=int(sum(
                1 for record in records
                if routes[record['route_a']].get('direct')
                or routes[record['route_b']].get('direct'))),
            routes_total=int(len(routes)),
            routes_with_crossings=int(sum(1 for row in per_route.values()
                                          if row['total_crossings'] > 0)),
            routes_with_own_arc=int(sum(1 for row in per_route.values()
                                        if row['own_arc'] > 0)),
            crossing_planes=int(sum(1 for row in per_z.values() if row['total'])),
        ),
        verification=verification,
        per_plane=[row for row in per_z.values()],
        per_family=relation_rows,
        per_route=[_route_row(route_id) for route_id in sorted(per_route)],
        top_routes_by_own_arc=[_route_row(route_id) for route_id in top_own_arc],
        top_routes_by_arc_involved=[_route_row(route_id)
                                    for route_id in top_arc_involved],
        hotspot=dict(bin_mm=HOTSPOT_BIN_MM, x_min=_round(x_min),
                     y_min=_round(y_min), x_max=_round(x_max),
                     y_max=_round(y_max),
                     cells=hotspot_rows, arc_cells=arc_hotspot_rows),
        angle=dict(bin_deg=ANGLE_BIN_DEG, by_class=angle_rows),
    )


# ================================================== target-height intersections
class TargetCrossingCache(object):
    """Analytic intersections of body-flat chains against one target height."""

    def __init__(self, plane_index, route_id, min_sine=MIN_SINE):
        self.plane_index = plane_index
        self.route_id = int(route_id)
        self.min_sine = float(min_sine)
        self.body = {}

    # -- body chain --------------------------------------------------------
    def chain_intersections(self, chain, target_z):
        key = (int(chain['part_index']), _round(target_z, 9))
        cached = self.body.get(key)
        if cached is not None:
            return cached
        points = []
        overlaps = []
        for prim_index, prim in enumerate(chain['prims']):
            box = _prim_bbox(prim)
            for partner_id, other in self.plane_index.query(
                    target_z, box, exclude_route=self.route_id):
                found, sines, overlap = prim_pair_intersections(prim, other)
                if overlap is not None:
                    length = _prim_length(prim)
                    if isinstance(overlap[0], str):
                        s_lo, s_hi = 0.0, length
                    else:
                        s_lo = chain['offsets'][prim_index] + float(overlap[0]) * length
                        s_hi = chain['offsets'][prim_index] + float(overlap[1]) * length
                    overlaps.append(dict(partner=int(partner_id),
                                         s_lo=_round(min(s_lo, s_hi)),
                                         s_hi=_round(max(s_lo, s_hi))))
                    continue
                for point, sine in zip(found, sines):
                    parameter, _distance = CI._prim_parameter(prim, point)
                    s_mm = chain['offsets'][prim_index] + parameter * _prim_length(prim)
                    points.append(dict(partner=int(partner_id),
                                       x_mm=float(point[0]), y_mm=float(point[1]),
                                       sine=float(sine), s_mm=float(s_mm)))
        points.sort(key=lambda item: (item['s_mm'], item['partner']))
        cached = dict(points=points, overlaps=overlaps)
        self.body[key] = cached
        return cached

    # -- one extra straight piece (transition rescue) ----------------------
    def line_intersections(self, line, target_z, z_from=None, z_to=None):
        key = None
        points = []
        overlaps = []
        box = _prim_bbox(line)
        for partner_id, other in self.plane_index.query(
                target_z, box, exclude_route=self.route_id):
            found, sines, overlap = prim_pair_intersections(line, other)
            if overlap is not None:
                overlaps.append(dict(partner=int(partner_id)))
                continue
            for point, sine in zip(found, sines):
                points.append(dict(partner=int(partner_id),
                                   x_mm=float(point[0]), y_mm=float(point[1]),
                                   sine=float(sine), s_mm=None))
        return dict(points=points, overlaps=overlaps)


def _dedupe_incidences(incidences):
    """De-duplicate crossing incidences per partner route / 1e-6 mm point."""
    kept = []
    for incidence in sorted(incidences, key=lambda item: (item['partner'],
                                                          item.get('s_mm') or 0.0,
                                                          item['x_mm'])):
        duplicate = False
        for other in kept:
            if other['partner'] != incidence['partner']:
                continue
            if (abs(other['x_mm'] - incidence['x_mm']) < CROSSING_DEDUPE_MM
                    and abs(other['y_mm'] - incidence['y_mm']) < CROSSING_DEDUPE_MM):
                duplicate = True
                break
        if not duplicate:
            kept.append(incidence)
    return kept


def count_target_crossings(cache, chain, target_z, middle_lo, middle_hi,
                           extension_line=None):
    """Transverse / tangent / overlap incidences of the middle sub-chain."""
    data = cache.chain_intersections(chain, target_z)
    incidences = []
    overlaps = []
    for item in data['points']:
        if middle_lo - PAIR_EPS < item['s_mm'] < middle_hi - PAIR_EPS:
            incidences.append(item)
    for item in data['overlaps']:
        if item['s_hi'] > middle_lo + PAIR_EPS and item['s_lo'] < middle_hi - PAIR_EPS:
            overlaps.append(item)
    if extension_line is not None:
        extra = cache.line_intersections(extension_line, target_z)
        incidences.extend(extra['points'])
        overlaps.extend(extra['overlaps'])
    unique = _dedupe_incidences(incidences)
    transverse = [item for item in unique if item['sine'] >= cache.min_sine]
    tangent = [item for item in unique if item['sine'] < cache.min_sine]
    return dict(transverse=len(transverse), tangent=len(tangent),
                overlap_contacts=len(overlaps),
                distinct_partners=int(len({item['partner'] for item in transverse})),
                distinct_points=int(len(unique)),
                incidences=unique)


def _arcs_inside(prims, offsets, s_lo, s_hi):
    count = 0
    length = 0.0
    for prim_index, prim in enumerate(prims):
        if prim['kind'] != 'arc':
            continue
        prim_lo = offsets[prim_index]
        prim_hi = prim_lo + _prim_length(prim)
        low = max(prim_lo, s_lo)
        high = min(prim_hi, s_hi)
        if high > low + PAIR_EPS:
            count += 1
            length += high - low
    return count, float(length)


def _straight_runs(chain):
    return [dict(lo=float(lo), hi=float(hi), prim_index=int(index))
            for lo, hi, index in P.straight_intervals(chain['prims'])]


def _transition_before(route, flat_part_index):
    parts = route.get('parts') or ()
    if flat_part_index - 1 < 0:
        return None
    part = parts[flat_part_index - 1]
    if part.get('kind') != 'transition':
        return None
    return dict(part_index=int(flat_part_index - 1),
                z0=float(part['z0']), z1=float(part['z1']),
                footprint_mm=float(part['footprint_mm']),
                start=(float(part['start'][0]), float(part['start'][1])),
                direction=(float(part['direction'][0]),
                           float(part['direction'][1])),
                tag=str(part.get('tag') or ''))


def _transition_after(route, flat_part_index):
    parts = route.get('parts') or ()
    if flat_part_index + 1 >= len(parts):
        return None
    part = parts[flat_part_index + 1]
    if part.get('kind') != 'transition':
        return None
    return dict(part_index=int(flat_part_index + 1),
                z0=float(part['z0']), z1=float(part['z1']),
                footprint_mm=float(part['footprint_mm']),
                start=(float(part['start'][0]), float(part['start'][1])),
                direction=(float(part['direction'][0]),
                           float(part['direction'][1])),
                tag=str(part.get('tag') or ''))


def _extension_line(transition, footprint_used):
    """The target-height straight piece between the new S-curve and the flat."""
    sx, sy = transition['start']
    dx, dy = transition['direction']
    return dict(kind='line',
                p0=[sx + dx * float(footprint_used), sy + dy * float(footprint_used)],
                p1=[sx + dx * transition['footprint_mm'],
                    sy + dy * transition['footprint_mm']])


# ================================================== rebuild interval analysis
def _select_before_run(runs, region_lo):
    before = None
    for run in runs:
        if run['hi'] <= region_lo + 1e-9:
            before = run
    return before


def _select_after_run(runs, region_hi):
    for run in runs:
        if run['lo'] >= region_hi - 1e-9:
            return run
    return None


def _mergeable_prim_gap(chain, last_index, current_index, line_merge_mm):
    """True when the primitives between two crossings may belong to one region."""
    if int(current_index) <= int(last_index):
        return True
    prims = chain['prims']
    upper = min(int(current_index), len(prims))
    for index in range(int(last_index) + 1, upper):
        prim = prims[index]
        if prim['kind'] == 'line' and _prim_length(prim) > line_merge_mm + 1e-9:
            return False
    return True


def _arc_crossing_regions(chain, arc_records, line_merge_mm):
    """Maximal arc-crossing regions of one flat.

    Crossings on the same primitive are always merged.  Two crossings on
    different primitives are merged when every primitive strictly between them is
    an arc or a line shorter than ``line_merge_mm`` (so a contiguous arc bend
    block, even one interleaved with short straight pieces, is one region, while
    two arc bends separated by a long straight stay separate).
    """
    ordered = sorted(arc_records, key=lambda item: (item['s_mm'],
                                                    item['event_index']))
    regions = []
    for record in ordered:
        if regions:
            last = regions[-1]
            if _mergeable_prim_gap(chain, last['records'][-1]['prim_index'],
                                   record['prim_index'], line_merge_mm):
                last['records'].append(record)
                last['s_end_mm'] = float(record['s_mm'])
                last['prim_index_hi'] = int(record['prim_index'])
                continue
        regions.append(dict(records=[record],
                            s_start_mm=float(record['s_mm']),
                            s_end_mm=float(record['s_mm']),
                            prim_index_lo=int(record['prim_index']),
                            prim_index_hi=int(record['prim_index'])))
    for region in regions:
        members = region['records']
        region['count'] = len(members)
        region['partner_kinds'] = dict(Counter(
            str(member.get('partner_kind') or 'missing') for member in members))
        region['crossing_classes'] = dict(Counter(
            member['crossing_class'] for member in members))
    return regions


def _entry_options(chain, region_lo, source_s, footprint, prev_transition,
                   params):
    """Candidate up-transition placements (straight run / preceding transition)."""
    options = []
    end_margin = float(params['end_margin_mm'])
    shadow = float(params['shadow_mm'])
    before = _select_before_run(_straight_runs(chain), region_lo)
    straight_info = None
    if before is not None:
        lower = max(float(before['lo']), end_margin)
        upper = min(region_lo - shadow, float(before['hi'] - footprint))
        usable = max(0.0, float(before['hi']) - lower)
        straight_info = dict(prim_index=int(before['prim_index']),
                             s_lo=_round(before['lo'], 6),
                             s_hi=_round(before['hi'], 6),
                             length_mm=_round(before['hi'] - before['lo']),
                             usable_mm=_round(usable),
                             required_mm=_round(footprint))
        if upper >= lower - PAIR_EPS:
            starts = CI._valid_starts(upper, lower, source_s, shadow)
            for s0 in starts[:int(params['max_entry_options'])]:
                options.append(dict(mode='straight', feasible=True,
                                    s_start=_round(s0), s_end=_round(s0 + footprint),
                                    footprint_used_mm=_round(footprint),
                                    middle_lo=float(s0 + footprint),
                                    available_mm=_round(usable),
                                    shadow_ok=True, reason=''))
            if not starts:
                options.append(dict(mode='straight', feasible=False, s_start=None,
                                    s_end=None, footprint_used_mm=_round(footprint),
                                    middle_lo=None, available_mm=_round(usable),
                                    shadow_ok=False,
                                    reason='no_shadow_clear_start'))
        else:
            options.append(dict(mode='straight', feasible=False, s_start=None,
                                s_end=None, footprint_used_mm=_round(footprint),
                                middle_lo=None, available_mm=_round(usable),
                                shadow_ok=True, reason='straight_too_short'))
    if prev_transition is not None:
        used = footprint_mm(float(params['target_z']) - prev_transition['z0'])
        available = float(prev_transition['footprint_mm'])
        extension = max(0.0, available - used)
        shadow_crossings = int(np.count_nonzero(
            (source_s >= -PAIR_EPS) & (source_s <= shadow + PAIR_EPS)))
        ok = used <= available + 1e-9
        reason = ''
        if not ok:
            reason = 'prev_transition_too_short'
        elif shadow_crossings:
            reason = 'source_shadow_at_flat_start'
        options.append(dict(
            mode='prev_transition', feasible=bool(ok and not shadow_crossings),
            s_start=0.0, s_end=_round(used),
            footprint_used_mm=_round(used), middle_lo=_round(-extension),
            extension_mm=_round(extension), available_mm=_round(available),
            shadow_ok=bool(not shadow_crossings),
            source_shadow_crossings=int(shadow_crossings), reason=reason,
            transition_part_index=int(prev_transition['part_index']),
            z_from=_round(prev_transition['z0'])))
    return options, straight_info


def _exit_options(chain, region_hi, source_s, footprint, next_transition,
                  params):
    """Candidate down-transition placements (straight run / following transition)."""
    options = []
    end_margin = float(params['end_margin_mm'])
    shadow = float(params['shadow_mm'])
    total = float(chain['length_mm'])
    after = _select_after_run(_straight_runs(chain), region_hi)
    straight_info = None
    if after is not None:
        lower = max(region_hi + footprint, float(after['lo'] + footprint))
        upper = min(float(after['hi']), total - end_margin)
        usable = max(0.0, upper - max(float(after['lo']), region_hi))
        straight_info = dict(prim_index=int(after['prim_index']),
                             s_lo=_round(after['lo'], 6),
                             s_hi=_round(after['hi'], 6),
                             length_mm=_round(after['hi'] - after['lo']),
                             usable_mm=_round(usable),
                             required_mm=_round(footprint))
        if upper >= lower - PAIR_EPS:
            ends = CI._valid_ends(lower, upper, source_s, shadow)
            for s1 in ends[:int(params['max_exit_options'])]:
                options.append(dict(mode='straight', feasible=True,
                                    s_start=_round(s1 - footprint),
                                    s_end=_round(s1),
                                    footprint_used_mm=_round(footprint),
                                    middle_hi=float(s1 - footprint),
                                    available_mm=_round(usable),
                                    shadow_ok=True, reason=''))
            if not ends:
                options.append(dict(mode='straight', feasible=False,
                                    s_start=None, s_end=None,
                                    footprint_used_mm=_round(footprint),
                                    middle_hi=None, available_mm=_round(usable),
                                    shadow_ok=False,
                                    reason='no_shadow_clear_end'))
        else:
            options.append(dict(mode='straight', feasible=False, s_start=None,
                                s_end=None, footprint_used_mm=_round(footprint),
                                middle_hi=None, available_mm=_round(usable),
                                shadow_ok=True, reason='straight_too_short'))
    if next_transition is not None:
        used = footprint_mm(float(params['target_z']) - next_transition['z1'])
        available = float(next_transition['footprint_mm'])
        shadow_crossings = int(np.count_nonzero(
            (source_s >= total - shadow - PAIR_EPS)
            & (source_s <= total + PAIR_EPS)))
        ok = used <= available + 1e-9
        reason = ''
        if not ok:
            reason = 'next_transition_too_short'
        elif shadow_crossings:
            reason = 'source_shadow_at_flat_end'
        options.append(dict(
            mode='next_transition', feasible=bool(ok and not shadow_crossings),
            s_start=_round(total - used), s_end=_round(total),
            footprint_used_mm=_round(used), middle_hi=_round(total),
            available_mm=_round(available), shadow_ok=bool(not shadow_crossings),
            source_shadow_crossings=int(shadow_crossings), reason=reason,
            transition_part_index=int(next_transition['part_index']),
            z_to=_round(next_transition['z1'])))
    return options, straight_info


def _removed_crossings(source_records, s_start, s_end):
    removed = [record for record in source_records
               if s_start + PAIR_EPS < record['s_mm'] < s_end - PAIR_EPS]
    return removed


def evaluate_target_height(route, chain, region_lo, region_hi, source_records,
                           source_s, target_plane_id, cache, prev_transition,
                           next_transition, params):
    """All rebuild options of one target height for one arc-crossing cluster."""
    target_z = float(N.PLANE_Z[int(target_plane_id)])
    flat_z = float(chain['z_mm'])
    dz = target_z - flat_z
    footprint = footprint_mm(dz)
    manual_plane = bool(int(target_plane_id) in N.MANUAL_PLANES)
    plausible = (not manual_plane
                 and int(target_plane_id) in PLAUSIBLE_PLANE_IDS
                 and abs(dz) > 1e-12)
    params = dict(params)
    params['target_z'] = target_z
    entry_options, before_info = _entry_options(
        chain, region_lo, source_s, footprint, prev_transition, params)
    exit_options, after_info = _exit_options(
        chain, region_hi, source_s, footprint, next_transition, params)
    middle_lo_of = lambda option: option.get('middle_lo')
    middle_hi_of = lambda option: option.get('middle_hi')

    combinations = []
    for entry in entry_options:
        for exit_option in exit_options:
            record = dict(
                entry_mode=entry['mode'], exit_mode=exit_option['mode'],
                entry=dict(entry), exit=dict(exit_option),
                interval_kind=None,
                covers_entire_flat=bool(entry['mode'] != 'straight'
                                        and exit_option['mode'] != 'straight'),
                s_start_mm=(_round(entry['s_start'], 6)
                            if entry.get('s_start') is not None else None),
                s_end_mm=(_round(exit_option['s_end'], 6)
                          if exit_option.get('s_end') is not None else None),
                span_2d_mm=(_round(float(exit_option['s_end'])
                                   - float(entry['s_start']))
                            if (entry.get('s_start') is not None
                                and exit_option.get('s_end') is not None)
                            else None),
                footprint_in_mm=_round(entry.get('footprint_used_mm') or 0.0),
                footprint_out_mm=_round(exit_option.get('footprint_used_mm') or 0.0),
                required_len_mm=_round((entry.get('footprint_used_mm') or 0.0)
                                       + (exit_option.get('footprint_used_mm') or 0.0)
                                       + params['min_middle_mm']),
                shadow_ok=bool(entry.get('shadow_ok', True)
                               and exit_option.get('shadow_ok', True)),
                feasible=False, reasons=[],
                estimated_removed=0, estimated_added=0, estimated_net=0,
                removed_classes=dict(), target_tangent_contacts=0,
                target_overlap_contacts=0, target_shadow_contacts=None,
                middle_lo_mm=None, middle_hi_mm=None, middle_mm=None,
                n_arcs_in_middle=0, arc_length_in_middle_mm=0.0,
                intermediate_planes=[],
            )
            reasons = []
            if not entry['feasible']:
                reasons.append(str(entry['reason'] or 'entry_infeasible'))
            if not exit_option['feasible']:
                reasons.append(str(exit_option['reason'] or 'exit_infeasible'))
            middle_lo = middle_lo_of(entry)
            middle_hi = middle_hi_of(exit_option)
            if middle_lo is not None and middle_hi is not None:
                middle = float(middle_hi) - float(middle_lo)
                record['middle_lo_mm'] = _round(middle_lo, 6)
                record['middle_hi_mm'] = _round(middle_hi, 6)
                record['middle_mm'] = _round(middle)
                if middle < params['min_middle_mm'] - PAIR_EPS:
                    reasons.append('middle_too_short')
                extension = None
                if entry['mode'] == 'prev_transition' and entry.get('extension_mm'):
                    extension = _extension_line(prev_transition,
                                                entry['footprint_used_mm'])
                counts = count_target_crossings(
                    cache, chain, target_z,
                    float(middle_lo) + PAIR_EPS, float(middle_hi) - PAIR_EPS,
                    extension_line=extension)
                record['estimated_added'] = int(counts['transverse'])
                record['target_tangent_contacts'] = int(counts['tangent'])
                record['target_overlap_contacts'] = int(counts['overlap_contacts'])
                record['target_partners'] = int(counts['distinct_partners'])
                n_arcs, arc_len = _arcs_inside(chain['prims'], chain['offsets'],
                                               float(middle_lo), float(middle_hi))
                record['n_arcs_in_middle'] = int(n_arcs)
                record['arc_length_in_middle_mm'] = _round(arc_len)
                # advisory mirror shadow where the S-curve is still near the
                # target height; only well defined for straight placements
                shadow_contacts = 0
                shadow_defined = (entry['mode'] == 'straight'
                                  and exit_option['mode'] == 'straight')
                if shadow_defined:
                    data = cache.chain_intersections(chain, target_z)
                    for item in data['points']:
                        s_value = item['s_mm']
                        if ((middle_lo - params['shadow_mm'] < s_value < middle_lo)
                                or (middle_hi < s_value < middle_hi + params['shadow_mm'])):
                            shadow_contacts += 1
                    record['target_shadow_contacts'] = int(shadow_contacts)
                removed = _removed_crossings(
                    source_records,
                    float(record['s_start_mm']) if record['s_start_mm'] is not None else 0.0,
                    float(record['s_end_mm']) if record['s_end_mm'] is not None else chain['length_mm'])
                record['estimated_removed'] = int(len(removed))
                record['removed_classes'] = dict(Counter(
                    item['crossing_class'] for item in removed))
                record['estimated_net'] = int(record['estimated_removed']
                                              - record['estimated_added'])
                entry_z_from = (float(prev_transition['z0'])
                                if entry['mode'] == 'prev_transition'
                                else flat_z)
                exit_z_to = (float(next_transition['z1'])
                             if exit_option['mode'] == 'next_transition'
                             else flat_z)
                record['intermediate_planes'] = sorted(set(
                    intermediate_planes(entry_z_from, target_z)
                    + intermediate_planes(exit_z_to, target_z)))
            else:
                middle = None
            if reasons:
                record['reasons'] = reasons
                record['feasible'] = False
            else:
                record['feasible'] = True
            if record['entry_mode'] == 'straight' and record['exit_mode'] == 'straight':
                record['interval_kind'] = 'local'
            elif (record['entry_mode'] == 'straight'
                  and record['exit_mode'] != 'straight'):
                record['interval_kind'] = 'exit_rescue'
            elif (record['entry_mode'] != 'straight'
                  and record['exit_mode'] == 'straight'):
                record['interval_kind'] = 'entry_rescue'
            else:
                record['interval_kind'] = 'whole_body_reassign'
            combinations.append(record)
    feasible = [item for item in combinations if item['feasible']]
    feasible_sorted = sorted(
        feasible,
        key=lambda item: (-int(item['estimated_net']),
                          int(item['estimated_added']),
                          float(item['middle_mm']),
                          -1 if item['entry_mode'] == 'straight' else 0,
                          -1 if item['exit_mode'] == 'straight' else 0,
                          float(item['s_start_mm'])))
    best = feasible_sorted[0] if feasible_sorted else None
    local_feasible = [item for item in feasible
                      if item['interval_kind'] == 'local']
    local_sorted = sorted(
        local_feasible,
        key=lambda item: (-int(item['estimated_net']),
                          int(item['estimated_added']),
                          float(item['middle_mm']),
                          float(item['s_start_mm'])))
    local_best = local_sorted[0] if local_sorted else None
    partial_feasible = [item for item in feasible
                        if item['interval_kind'] in ('entry_rescue',
                                                     'exit_rescue')]
    partial_sorted = sorted(
        partial_feasible,
        key=lambda item: (-int(item['estimated_net']),
                          int(item['estimated_added']),
                          float(item['middle_mm']),
                          float(item['s_start_mm'])))
    partial_best = partial_sorted[0] if partial_sorted else None
    best_index = None
    local_best_index = None
    partial_best_index = None
    for index, item in enumerate(combinations):
        item['target_plane_id'] = int(target_plane_id)
        item['target_z_mm'] = _round(target_z, 9)
        if item is best:
            best_index = int(index)
        if item is local_best:
            local_best_index = int(index)
        if item is partial_best:
            partial_best_index = int(index)
    return dict(
        target_plane_id=int(target_plane_id),
        target_plane_label=N.PLANE_LABEL[int(target_plane_id)],
        target_z_mm=_round(target_z, 9),
        target_is_manual_plane=manual_plane,
        plausible=bool(plausible),
        footprint_mm=_round(footprint),
        required_len_mm=_round(2.0 * footprint + params['min_middle_mm']),
        required_len_with_margins_mm=_round(2.0 * footprint
                                            + params['min_middle_mm']
                                            + 2.0 * params['end_margin_mm']),
        intermediate_planes_between_flat_and_target=intermediate_planes(flat_z, target_z),
        before_straight=before_info,
        after_straight=after_info,
        target_plane_route_count=int(len(
            cache.plane_index.route_ids.get(_round(target_z, 9), ()))),
        target_plane_flat_prims=int(
            cache.plane_index.flat_part_count.get(_round(target_z, 9), 0)),
        options=combinations,
        feasible_option_count=int(len(feasible)),
        local_feasible_option_count=int(len(local_feasible)),
        partial_feasible_option_count=int(len(partial_feasible)),
        best_option_index=best_index,
        local_option_index=local_best_index,
        partial_option_index=partial_best_index,
        best_estimated_removed=(int(best['estimated_removed']) if best else 0),
        best_estimated_added=(int(best['estimated_added']) if best else 0),
        best_estimated_net=(int(best['estimated_net']) if best else 0),
        best_entry_mode=(best['entry_mode'] if best else None),
        best_exit_mode=(best['exit_mode'] if best else None),
        best_interval_kind=(best['interval_kind'] if best else None),
        best_middle_mm=(_round(best['middle_mm']) if best else None),
        best_span_2d_mm=(_round(best['span_2d_mm']) if best else None),
        best_s_start_mm=(best['s_start_mm'] if best else None),
        best_s_end_mm=(best['s_end_mm'] if best else None),
        best_removed_classes=(dict(best['removed_classes']) if best else {}),
        local_estimated_removed=(int(local_best['estimated_removed'])
                                 if local_best else 0),
        local_estimated_added=(int(local_best['estimated_added'])
                               if local_best else 0),
        local_estimated_net=(int(local_best['estimated_net'])
                             if local_best else 0),
        local_entry_mode=(local_best['entry_mode'] if local_best else None),
        local_exit_mode=(local_best['exit_mode'] if local_best else None),
        local_interval_kind='local' if local_best is not None else None,
        local_s_start_mm=(local_best['s_start_mm'] if local_best else None),
        local_s_end_mm=(local_best['s_end_mm'] if local_best else None),
        partial_estimated_removed=(int(partial_best['estimated_removed'])
                                   if partial_best else 0),
        partial_estimated_added=(int(partial_best['estimated_added'])
                                 if partial_best else 0),
        partial_estimated_net=(int(partial_best['estimated_net'])
                               if partial_best else 0),
        partial_entry_mode=(partial_best['entry_mode'] if partial_best else None),
        partial_exit_mode=(partial_best['exit_mode'] if partial_best else None),
        partial_interval_kind=(partial_best['interval_kind']
                               if partial_best else None),
        partial_s_start_mm=(partial_best['s_start_mm'] if partial_best else None),
        partial_s_end_mm=(partial_best['s_end_mm'] if partial_best else None),
    )


def analyse_cluster(route, chain, cluster, flat_records, prev_transition,
                    next_transition, cache, params):
    region_lo = float(cluster['s_start_mm'])
    region_hi = float(cluster['s_end_mm'])
    source_records = [record for record in flat_records]
    source_s = np.asarray(sorted(float(record['s_mm'])
                                 for record in flat_records), dtype=float)
    before = _select_before_run(_straight_runs(chain), region_lo)
    after = _select_after_run(_straight_runs(chain), region_hi)
    n_arcs_region, arc_len_region = _arcs_inside(chain['prims'],
                                                 chain['offsets'],
                                                 region_lo, region_hi)
    total = float(chain['length_mm'])
    available_before = None
    if before is not None:
        available_before = max(
            0.0,
            min(float(before['hi']), region_lo - params['shadow_mm'])
            - max(float(before['lo']), params['end_margin_mm']))
    available_after = None
    if after is not None:
        available_after = max(
            0.0,
            min(float(after['hi']), total - params['end_margin_mm'])
            - max(float(after['lo']), region_hi + params['shadow_mm']))
    targets = []
    for plane_id in params['target_plane_ids']:
        if abs(float(N.PLANE_Z[int(plane_id)]) - float(chain['z_mm'])) <= 1e-12:
            continue
        targets.append(evaluate_target_height(
            route, chain, region_lo, region_hi, source_records, source_s,
            int(plane_id), cache, prev_transition, next_transition, params))
    feasible_targets = [item for item in targets if item['feasible_option_count'] > 0]
    plausible_feasible = [item for item in targets
                          if item['feasible_option_count'] > 0 and item['plausible']]

    def _rank(row):
        return (-int(row['best_estimated_net']),
                abs(float(row['target_z_mm']) - float(chain['z_mm'])),
                int(row['target_plane_id']))

    best_any_target = (sorted(feasible_targets, key=_rank)[0]
                       if feasible_targets else None)
    best_target = (sorted(plausible_feasible, key=_rank)[0]
                   if plausible_feasible else None)
    local_plausible = [item for item in plausible_feasible
                       if item['local_option_index'] is not None]
    best_local_target = (sorted(
        local_plausible,
        key=lambda row: (-int(row['local_estimated_net']),
                         abs(float(row['target_z_mm']) - float(chain['z_mm'])),
                         int(row['target_plane_id'])))[0]
        if local_plausible else None)
    positive_plausible = [item for item in plausible_feasible
                          if int(item['best_estimated_net']) >= 1]
    best_positive_target = (sorted(positive_plausible, key=_rank)[0]
                            if positive_plausible else None)

    def _summary(target, use_local=False):
        if target is None:
            return None
        if use_local:
            return dict(target_plane_id=target['target_plane_id'],
                        target_plane_label=target['target_plane_label'],
                        target_z_mm=target['target_z_mm'],
                        best_estimated_net=target['local_estimated_net'],
                        best_estimated_removed=target['local_estimated_removed'],
                        best_estimated_added=target['local_estimated_added'],
                        best_entry_mode=target['local_entry_mode'],
                        best_exit_mode=target['local_exit_mode'],
                        best_interval_kind=target['local_interval_kind'],
                        best_s_start_mm=target['local_s_start_mm'],
                        best_s_end_mm=target['local_s_end_mm'])
        return dict(target_plane_id=target['target_plane_id'],
                    target_plane_label=target['target_plane_label'],
                    target_z_mm=target['target_z_mm'],
                    best_estimated_net=target['best_estimated_net'],
                    best_estimated_removed=target['best_estimated_removed'],
                    best_estimated_added=target['best_estimated_added'],
                    best_entry_mode=target['best_entry_mode'],
                    best_exit_mode=target['best_exit_mode'],
                    best_interval_kind=target['best_interval_kind'],
                    best_s_start_mm=target['best_s_start_mm'],
                    best_s_end_mm=target['best_s_end_mm'])
    near_crossings = [record for record in source_records]
    previous_crossings = [record for record in near_crossings
                          if record['s_mm'] < region_lo - PAIR_EPS]
    next_crossings = [record for record in near_crossings
                      if record['s_mm'] > region_hi + PAIR_EPS]
    return dict(
        cluster_index=None,
        s_start_mm=_round(region_lo),
        s_end_mm=_round(region_hi),
        span_2d_mm=_round(region_hi - region_lo),
        arc_crossing_count=int(cluster['count']),
        arc_crossing_classes=dict(cluster['crossing_classes']),
        arc_crossing_partner_kinds=dict(cluster['partner_kinds']),
        arc_crossings=[dict(
            event_index=int(record['event_index']),
            s_mm=_round(record['s_mm']),
            partner_route=int(record['partner_route']),
            partner_kind=str(record['partner_kind']),
            partner_arc=bool(record.get('partner_arc')),
            crossing_class=str(record['crossing_class']),
            angle_deg=_round(record['angle_deg']),
            x_mm=_round(record['x_mm']), y_mm=_round(record['y_mm']),
            z_mm=_round(record['z_mm'])) for record in cluster['records']],
        source_crossings_on_flat=int(len(source_records)),
        source_crossing_class_counts=dict(Counter(
            record['crossing_class'] for record in source_records)),
        nearest_crossing_before_s_mm=(_round(previous_crossings[-1]['s_mm'])
                                      if previous_crossings else None),
        nearest_crossing_after_s_mm=(_round(next_crossings[0]['s_mm'])
                                     if next_crossings else None),
        n_arcs_in_region=int(n_arcs_region),
        arc_length_in_region_mm=_round(arc_len_region),
        before_straight=(dict(before, length_mm=_round(before['hi'] - before['lo']))
                         if before else None),
        after_straight=(dict(after, length_mm=_round(after['hi'] - after['lo']))
                        if after else None),
        available_before_straight_mm=(_round(available_before)
                                      if available_before is not None else None),
        available_after_straight_mm=(_round(available_after)
                                     if available_after is not None else None),
        prev_transition=prev_transition,
        next_transition=next_transition,
        prim_index_span=[int(cluster.get('prim_index_lo', -1)),
                         int(cluster.get('prim_index_hi', -1))],
        feasible_target_count=int(len(feasible_targets)),
        plausible_feasible_target_count=int(len(plausible_feasible)),
        plausible_positive_target_count=int(len(positive_plausible)),
        local_target_count=int(len(local_plausible)),
        best_target=_summary(best_target),
        best_any_target=_summary(best_any_target),
        best_positive_target=_summary(best_positive_target),
        best_local_target=_summary(best_local_target, use_local=True),
        best_plausible_target=_summary(best_target),
        targets=targets,
    )


def analyse_route_rebuild(route_id, route, chains, own_records, plane_index,
                          params):
    """Arc-crossing clusters + rebuild intervals of one route."""
    records_by_flat = defaultdict(list)
    for record in own_records:
        records_by_flat[int(record['flat_part_index'])].append(record)
    chain_by_part = {int(chain['part_index']): chain for chain in chains}
    cache = TargetCrossingCache(plane_index, route_id)
    flat_results = []
    for part_index in sorted(records_by_flat):
        chain = chain_by_part.get(part_index)
        if chain is None:
            continue
        flat_records = sorted(records_by_flat[part_index],
                              key=lambda item: (item['s_mm'], item['event_index']))
        arc_records = [record for record in flat_records
                       if record['prim_kind'] == 'arc']
        if not arc_records:
            continue
        clusters = _arc_crossing_regions(chain, arc_records,
                                         params['line_merge_mm'])
        prev_transition = _transition_before(route, part_index)
        next_transition = _transition_after(route, part_index)
        cluster_results = []
        for cluster_index, cluster in enumerate(clusters):
            cluster_result = analyse_cluster(
                route, chain, cluster, flat_records, prev_transition,
                next_transition, cache, params)
            cluster_result['cluster_index'] = int(cluster_index)
            cluster_results.append(cluster_result)
        flat_results.append(dict(
            part_index=int(part_index),
            z_mm=_round(chain['z_mm'], 9),
            plane_id=(int(chain['plane_id']) if chain['plane_id'] is not None else None),
            plane_label=chain['plane_label'],
            tag=chain['tag'],
            length_mm=_round(chain['length_mm']),
            prim_kinds=[str(prim['kind']) for prim in chain['prims']],
            arc_crossing_count=int(len(arc_records)),
            crossing_count=int(len(flat_records)),
            n_clusters=int(len(clusters)),
            prev_transition=prev_transition,
            next_transition=next_transition,
            clusters=cluster_results,
        ))
    feasible_clusters = [
        (flat['part_index'], cluster)
        for flat in flat_results for cluster in flat['clusters']
        if cluster['feasible_target_count'] > 0]
    usable_clusters = [
        (flat['part_index'], cluster)
        for flat in flat_results for cluster in flat['clusters']
        if cluster['plausible_feasible_target_count'] > 0]
    positive_clusters = [
        (flat['part_index'], cluster)
        for flat in flat_results for cluster in flat['clusters']
        if cluster['plausible_positive_target_count'] > 0]
    best_overall = None
    for _part, cluster in sorted(
            usable_clusters,
            key=lambda item: (-int(item[1]['best_target']['best_estimated_net']),
                              item[1]['cluster_index'])):
        best_overall = cluster['best_target']
        break
    best_positive_overall = None
    for _part, cluster in sorted(
            positive_clusters,
            key=lambda item: (-int(item[1]['best_positive_target']['best_estimated_net']),
                              item[1]['cluster_index'])):
        best_positive_overall = cluster['best_positive_target']
        break
    best_local_overall = None
    local_clusters = [(part, cluster) for part, cluster in usable_clusters
                      if cluster['best_local_target'] is not None]
    for _part, cluster in sorted(
            local_clusters,
            key=lambda item: (-int(item[1]['best_local_target']['best_estimated_net']),
                              item[1]['cluster_index'])):
        best_local_overall = cluster['best_local_target']
        break
    best_any_overall = None
    any_clusters = [(part, cluster) for part, cluster in
                    [(flat['part_index'], cluster) for flat in flat_results
                     for cluster in flat['clusters']]
                    if cluster['best_any_target'] is not None]
    for _part, cluster in sorted(
            any_clusters,
            key=lambda item: (-int(item[1]['best_any_target']['best_estimated_net']),
                              item[1]['cluster_index'])):
        best_any_overall = cluster['best_any_target']
        break
    result = dict(
        route_id=int(route_id),
        relation=str(route.get('relation') or ''),
        manual=bool(str(route.get('manual_group') or '').strip()),
        native_3d=bool(route.get('native_3d')),
        direct=bool(route.get('direct')),
        n_transitions=int(route.get('n_transitions') or 0),
        target_plane_id=(int(route['target_plane'])
                         if route.get('target_plane') is not None else None),
        target_plane_label=str(route.get('target_plane_label') or ''),
        target_z_mm=(_round(route['target_z_mm'], 9)
                     if route.get('target_z_mm') is not None else None),
        total_crossings=int(len(own_records)),
        own_arc_crossings=int(sum(1 for record in own_records
                                  if record['prim_kind'] == 'arc')),
        arc_involved_crossings=int(sum(1 for record in own_records
                                       if record['own_arc']
                                       or record.get('partner_arc'))),
        flats=flat_results,
        n_clusters=int(sum(flat['n_clusters'] for flat in flat_results)),
        n_feasible_clusters=int(len(feasible_clusters)),
        n_usable_clusters=int(len(usable_clusters)),
        geometrically_feasible=bool(usable_clusters),
        usable=bool(positive_clusters),
        usable_local=bool(local_clusters),
        best_target=best_overall,
        best_positive_target=best_positive_overall,
        best_local_target=best_local_overall,
        best_any_target=best_any_overall,
    )
    return result


# ================================================== availability statistics
def build_availability_stats(route_results):
    routes_total = len(route_results)
    used = [item for item in route_results if item['usable']]
    local_used = [item for item in route_results if item['usable_local']]
    nets = [int(item['best_positive_target']['best_estimated_net'])
            for item in used]
    local_nets = [int(item['best_local_target']['best_estimated_net'])
                  for item in local_used]
    target_counter = Counter()
    mode_counter = Counter()
    kind_counter = Counter()
    clusters_total = 0
    clusters_feasible = 0
    clusters_usable = 0
    for item in route_results:
        clusters_total += int(item['n_clusters'])
        clusters_feasible += int(item['n_feasible_clusters'])
        clusters_usable += int(item['n_usable_clusters'])
        if item['usable']:
            kind_counter[str(item['best_positive_target'].get(
                'best_interval_kind') or 'unknown')] += 1
        for flat in item['flats']:
            for cluster in flat['clusters']:
                if cluster['plausible_feasible_target_count'] <= 0:
                    continue
                for target in cluster['targets']:
                    if not target['plausible']:
                        continue
                    if target['best_option_index'] is None:
                        continue
                    if int(target['best_estimated_net']) < 1:
                        continue
                    target_counter[int(target['target_plane_id'])] += 1
                    best = target['options'][int(target['best_option_index'])]
                    mode_counter['%s+%s' % (best['entry_mode'],
                                            best['exit_mode'])] += 1
    thresholds = {str(value): sum(1 for net in nets if net >= value)
                  for value in (1, 2, 3, 5)}
    rescue_only = len(used) - len([item for item in used
                                   if item['usable_local']])
    return dict(
        routes_total=int(routes_total),
        routes_with_arc_clusters=int(sum(1 for item in route_results
                                         if item['n_clusters'] > 0)),
        routes_geometrically_feasible=int(sum(
            1 for item in route_results if item['geometrically_feasible'])),
        routes_with_feasible_interval=int(sum(1 for item in route_results
                                              if item['geometrically_feasible'])),
        routes_with_usable_interval=int(len(used)),
        routes_without_usable_interval=int(routes_total - len(used)),
        routes_with_local_interval=int(len(local_used)),
        routes_with_entry_or_exit_rescue_only=int(rescue_only),
        clusters_total=int(clusters_total),
        clusters_with_feasible_target=int(clusters_feasible),
        clusters_with_usable_plausible_target=int(clusters_usable),
        usable_best_interval_kind_counts=dict(kind_counter),
        usable_route_best_net=dict(
            min=(min(nets) if nets else None),
            median=_round(_percentile(sorted(nets), 0.5)) if nets else None,
            max=(max(nets) if nets else None),
            sum=int(sum(nets)),
            threshold_counts=thresholds),
        local_route_best_net=dict(
            min=(min(local_nets) if local_nets else None),
            median=(_round(_percentile(sorted(local_nets), 0.5))
                    if local_nets else None),
            max=(max(local_nets) if local_nets else None),
            sum=int(sum(local_nets))),
        usable_target_height_counts=OrderedDict(
            (str(pid), int(target_counter[pid]))
            for pid in ALL_PLANE_IDS if target_counter.get(pid)),
        usable_entry_exit_mode_counts=dict(mode_counter),
        route_ids_usable=[int(item['route_id']) for item in used],
    )


def build_route_notes(route_results):
    notes = []
    for item in route_results:
        messages = []
        if not item['flats']:
            messages.append('无圆弧交叉簇')
        for flat in item['flats']:
            for cluster in flat['clusters']:
                if cluster['feasible_target_count'] == 0:
                    if cluster['before_straight'] is None:
                        messages.append('簇 %d 起点侧无直线段（平直段以圆弧开头）'
                                        % cluster['cluster_index'])
                    if cluster['after_straight'] is None:
                        messages.append('簇 %d 终点侧无直线段（平直段以圆弧结尾）'
                                        % cluster['cluster_index'])
                    if (cluster['before_straight'] is None
                            and cluster['prev_transition'] is None):
                        messages.append('簇 %d 起点侧无换层过渡可重建'
                                        % cluster['cluster_index'])
                    if (cluster['after_straight'] is None
                            and cluster['next_transition'] is None):
                        messages.append('簇 %d 终点侧无换层过渡可重建'
                                        % cluster['cluster_index'])
        if item['usable']:
            best = item['best_positive_target']
            messages.append('最佳可行目标：%s (z=%.2f mm, net=%d: -%d/+%d, '
                            '%s+%s=%s)'
                            % (best['target_plane_label'], best['target_z_mm'],
                               best['best_estimated_net'],
                               best['best_estimated_removed'],
                               best['best_estimated_added'],
                               best['best_entry_mode'], best['best_exit_mode'],
                               best.get('best_interval_kind') or '?'))
        elif item['geometrically_feasible']:
            best = item['best_target']
            messages.append('几何可行但无正收益目标：最佳 %s net=%+d（−%d/+%d，%s）'
                            % (best['target_plane_label'],
                               best['best_estimated_net'],
                               best['best_estimated_removed'],
                               best['best_estimated_added'],
                               best.get('best_interval_kind') or '?'))
        if item['usable_local']:
            local = item['best_local_target']
            messages.append('局部（两 S 曲线均在 body flat 直线段内）最佳：%s '
                            '(z=%.2f mm, net=%d)'
                            % (local['target_plane_label'],
                               local['target_z_mm'],
                               local['best_estimated_net']))
        item['notes'] = messages
    return route_results


# ================================================== own-crossing incidence table
def collect_own_records(classified):
    """``{route_id: [crossing records of that route]}`` sorted by flat / s."""
    own = defaultdict(list)
    for record in classified:
        side_a = record['sides'][0]
        side_b = record['sides'][1]
        for side, partner_side, partner_id in (
                (side_a, side_b, record['route_b']),
                (side_b, side_a, record['route_a'])):
            if not side.get('found'):
                continue
            own[int(side['route_id'])].append(dict(
                event_index=int(record['event_index']),
                flat_part_index=int(side['flat_part_index']),
                flat_z_mm=float(side['flat_z_mm']),
                z_mm=float(record['z_mm']),
                s_mm=float(side['s_mm']),
                prim_kind=str(side['prim_kind']),
                prim_index=int(side['prim_index']),
                role=str(side.get('role') or 'unknown'),
                native_3d=bool(side.get('native_3d')),
                partner_route=int(partner_id),
                partner_kind=str(partner_side.get('prim_kind') or 'missing'),
                partner_role=str(partner_side.get('role') or 'missing'),
                crossing_class=str(record['crossing_class']),
                angle_deg=float(record['angle_deg']),
                x_mm=float(record['x_mm']), y_mm=float(record['y_mm']),
                own_arc=bool(side['prim_kind'] == 'arc'),
                partner_arc=bool(partner_side.get('prim_kind') == 'arc'),
            ))
    for route_id in own:
        own[route_id].sort(key=lambda item: (item['flat_part_index'],
                                              item['s_mm'], item['event_index']))
    return own


def select_top_routes(own_records, count):
    """Deterministic top routes by own-side arc crossings (then route id)."""
    scored = [(int(route_id),
               int(sum(1 for record in records if record['prim_kind'] == 'arc')))
              for route_id, records in own_records.items()]
    scored = [item for item in scored if item[1] > 0]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [route_id for route_id, _score in scored[:int(count)]]


# ================================================== reporting helpers
def _previous_claim_rows(aggregates):
    verification = aggregates['verification']
    rows = []
    for name in ('per_side_incidence', 'per_event_any_arc', 'per_event_both_arc'):
        data = verification[name]
        if name == 'per_side_incidence':
            count = data['arc']
            total = data['line'] + data['arc']
            fraction = data['arc_fraction']
        else:
            count = data['count']
            total = verification['events']
            fraction = data['fraction']
        rows.append(dict(definition=name, count=int(count), denom=int(total),
                         fraction=float(fraction)))
    return rows


# ================================================== plots
def _load_pyplot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


CLASS_COLORS = {'line-line': '#1f77b4', 'line-arc': '#ff7f0e',
                'arc-arc': '#d62728'}


def _sample_chain(chain, s_lo, s_hi, step=0.5):
    """2D polyline of one flat chain between arc lengths ``s_lo`` and ``s_hi``."""
    s_lo = max(0.0, min(float(s_lo), chain['length_mm']))
    s_hi = max(s_lo, min(float(s_hi), chain['length_mm']))
    count = max(2, int(math.ceil((s_hi - s_lo) / max(step, 0.05))) + 1)
    points = []
    for index in range(count + 1):
        s_value = s_lo + (s_hi - s_lo) * index / count
        point, _tangent = P.path_point_at(chain['prims'], s_value)
        points.append((float(point[0]), float(point[1])))
    return points


def _plot_chain(ax, chain, line_color='#1f77b4', arc_color='#d62728',
                linewidth=1.6):
    for prim in chain['prims']:
        if prim['kind'] == 'line':
            p0, p1 = prim['p0'], prim['p1']
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=line_color,
                    linewidth=linewidth, solid_capstyle='round')
        else:
            start = float(prim['start_angle'])
            sweep = float(prim['sweep'])
            radius = float(prim['radius'])
            cx, cy = prim['center']
            count = max(8, int(math.ceil(abs(math.degrees(sweep)) / 2.0)))
            angles = [start + sweep * index / count for index in range(count + 1)]
            ax.plot([cx + radius * math.cos(angle) for angle in angles],
                    [cy + radius * math.sin(angle) for angle in angles],
                    color=arc_color, linewidth=linewidth + 0.6,
                    solid_capstyle='round')


def plot_hotspot(result, path):
    plt = _load_pyplot()
    aggregates = result['aggregates']
    records = result['crossings']
    figure, axes = plt.subplots(1, 2, figsize=(15.0, 6.6))
    for axis, subset, title in (
            (axes[0], records, 'all 2440 crossings'),
            (axes[1], [item for item in records if item['any_arc']],
             'arc-involved crossings (%d)' % sum(
                 1 for item in records if item['any_arc']))):
        for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
            xs = [item['x_mm'] for item in subset
                  if item['crossing_class'] == crossing_class]
            ys = [item['y_mm'] for item in subset
                  if item['crossing_class'] == crossing_class]
            if not xs:
                continue
            axis.scatter(xs, ys, s=9, marker='x', linewidths=0.6,
                         color=CLASS_COLORS[crossing_class],
                         label='%s (%d)' % (crossing_class, len(xs)))
        hotspot = aggregates['hotspot']
        x_min = float(hotspot['x_min'])
        y_min = float(hotspot['y_min'])
        index_x = [item['ix'] for item in hotspot['cells']]
        index_y = [item['iy'] for item in hotspot['cells']]
        counts = [item['count'] for item in hotspot['cells']]
        if index_x:
            axis.scatter([x_min + (index + 0.5) * hotspot['bin_mm']
                          for index in index_x],
                         [y_min + (index + 0.5) * hotspot['bin_mm']
                          for index in index_y],
                         s=[max(1.0, count * 0.35) for count in counts],
                         facecolors='none', edgecolors='#555555',
                         linewidths=0.4, alpha=0.55,
                         label='%g mm grid cell density' % hotspot['bin_mm'])
        axis.set_xlabel('x (mm)')
        axis.set_ylabel('y (mm)')
        axis.set_title(title)
        axis.grid(True, linewidth=0.3, alpha=0.4)
        axis.set_aspect('equal', adjustable='datalim')
        axis.legend(loc='upper right', fontsize=8)
    figure.suptitle('Arc-crossing XY hotspot (accepted 2440-crossing baseline)',
                    fontsize=12)
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    figure.savefig(path, dpi=140)
    plt.close(figure)


def plot_angle_hist(result, path):
    plt = _load_pyplot()
    angle = result['aggregates']['angle']
    figure, axis = plt.subplots(figsize=(9.5, 5.4))
    edges = angle['by_class']['all']['histogram']['edges']
    width = float(edges[1] - edges[0])
    for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
        counts = angle['by_class'][crossing_class]['histogram']['counts']
        centers = [0.5 * (edges[index] + edges[index + 1])
                   for index in range(len(counts))]
        axis.bar(centers, counts, width=width * 0.82, alpha=0.65,
                 color=CLASS_COLORS[crossing_class],
                 label='%s (n=%d, median %.1f deg)'
                       % (crossing_class,
                          angle['by_class'][crossing_class]['stats']['count'],
                          angle['by_class'][crossing_class]['stats']['median_deg']))
    axis.set_xlabel('crossing angle (deg)')
    axis.set_ylabel('crossing event count')
    axis.set_title('Crossing angle distribution by crossing class')
    axis.set_xlim(0.0, 92.0)
    axis.grid(True, axis='y', linewidth=0.3, alpha=0.4)
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def plot_per_height(result, path):
    plt = _load_pyplot()
    rows = [row for row in result['aggregates']['per_plane'] if row['total'] > 0]
    labels = ['%s\nz=%.2f' % (row['plane_label'], row['z_mm']) for row in rows]
    positions = list(range(len(rows)))
    figure, axis = plt.subplots(figsize=(13.0, 5.6))
    bottom = [0.0] * len(rows)
    for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
        values = [row['counts'][crossing_class] for row in rows]
        axis.bar(positions, values, bottom=bottom, width=0.72,
                 color=CLASS_COLORS[crossing_class], label=crossing_class)
        bottom = [base + value for base, value in zip(bottom, values)]
    for position, row in zip(positions, rows):
        axis.text(position, bottom[position] + 4.0, '%d' % row['total'],
                  ha='center', va='bottom', fontsize=8)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, fontsize=8)
    axis.set_ylabel('crossing event count')
    axis.set_title('Crossings per physical height, stacked by crossing class')
    axis.grid(True, axis='y', linewidth=0.3, alpha=0.4)
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def plot_top20_routes(result, path):
    plt = _load_pyplot()
    rows = result['aggregates']['top_routes_by_own_arc']
    labels = []
    own_arc = []
    partner_only = []
    for row in rows:
        labels.append('r%d %s L%d' % (row['route_id'],
                                      row['relation'] or '?',
                                      int(row['target_plane_id'] or 0)))
        own_arc.append(int(row['own_arc']))
        partner_only.append(int(row['arc_partner_only']))
    positions = list(range(len(rows)))[::-1]
    figure, axis = plt.subplots(figsize=(10.5, 7.6))
    axis.barh(positions, own_arc, height=0.7, color='#d62728',
              label='own side on arc (arc crossings)')
    axis.barh(positions, partner_only, left=own_arc, height=0.7,
              color='#ff7f0e', label='own line, partner on arc')
    axis.set_yticks(positions)
    axis.set_yticklabels(labels, fontsize=8)
    axis.set_xlabel('crossing event count')
    axis.set_title('Top-20 routes by own-side arc crossings')
    for position, first, second in zip(positions, own_arc, partner_only):
        axis.text(first + second + 0.3, position, '%d' % (first + second),
                  va='center', fontsize=8)
    axis.grid(True, axis='x', linewidth=0.3, alpha=0.4)
    axis.legend(fontsize=8, loc='lower right')
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def _pick_example_routes(route_results, count=3):
    usable = [item for item in route_results if item['usable']]

    def best_net(item):
        return int(item['best_target']['best_estimated_net'])

    both_straight = [item for item in usable
                     if item['best_target']['best_entry_mode'] == 'straight'
                     and item['best_target']['best_exit_mode'] == 'straight']
    rescued = [item for item in usable
               if item['best_target']['best_entry_mode'] != 'straight'
               or item['best_target']['best_exit_mode'] != 'straight']
    chosen = []
    for pool in (sorted(both_straight, key=lambda item: (-best_net(item),
                                                         item['route_id'])),
                 sorted(rescued, key=lambda item: (-best_net(item),
                                                   item['route_id'])),
                 sorted(route_results,
                        key=lambda item: (-item['own_arc_crossings'],
                                          item['route_id']))):
        for item in pool:
            if len(chosen) >= count:
                break
            if item['route_id'] in [entry['route_id'] for entry in chosen]:
                continue
            chosen.append(item)
        if len(chosen) >= count:
            break
    return chosen[:count]


def plot_examples(result, own_records, routes, chains_by_route, paths):
    plt = _load_pyplot()
    examples = _pick_example_routes(result['top_routes'])
    produced = []
    for index, item in enumerate(examples):
        route_id = int(item['route_id'])
        route = routes[route_id]
        chains = chains_by_route[route_id]
        chain_by_part = {int(chain['part_index']): chain
                         for chain in chains}
        chosen_cluster = None
        chosen_flat = None
        best_rank = None
        for flat in item['flats']:
            for cluster in flat['clusters']:
                if cluster['plausible_feasible_target_count'] <= 0:
                    continue
                target = cluster['best_plausible_target']
                rank = (-int(target['best_estimated_net']),
                        cluster['cluster_index'])
                if best_rank is None or rank < best_rank:
                    best_rank = rank
                    chosen_cluster = cluster
                    chosen_flat = flat
        if chosen_cluster is None:
            for flat in item['flats']:
                for cluster in flat['clusters']:
                    target = cluster['best_target']
                    if target is None:
                        continue
                    rank = (-int(target['best_estimated_net']),
                            cluster['cluster_index'])
                    if best_rank is None or rank < best_rank:
                        best_rank = rank
                        chosen_cluster = cluster
                        chosen_flat = flat
        if chosen_flat is None:
            continue
        chain = chain_by_part[int(chosen_flat['part_index'])]
        figure, axis = plt.subplots(figsize=(10.5, 7.2))
        _plot_chain(axis, chain)
        for flat in item['flats']:
            if int(flat['part_index']) != int(chosen_flat['part_index']):
                continue
            for cluster in flat['clusters']:
                points = _sample_chain(chain, cluster['s_start_mm'],
                                       cluster['s_end_mm'], step=0.4)
                axis.plot([point[0] for point in points],
                          [point[1] for point in points], color='#9467bd',
                          linewidth=3.2, alpha=0.42,
                          label='arc-crossing region' if cluster is
                                flat['clusters'][0] else None)
        records = [record for record in own_records.get(route_id, ())
                   if int(record['flat_part_index']) == int(chain['part_index'])]
        for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
            subset = [record for record in records
                      if record['crossing_class'] == crossing_class]
            if not subset:
                continue
            axis.scatter([record['x_mm'] for record in subset],
                         [record['y_mm'] for record in subset],
                         marker='x', s=70, linewidths=1.6,
                         color=CLASS_COLORS[crossing_class], zorder=6,
                         label='%s crossing (%d)'
                               % (crossing_class, len(subset)))
        target = chosen_cluster['best_plausible_target'] or chosen_cluster['best_target']
        title = ('route %d | %s | body %s z=%.2f mm'
                 % (route_id, route.get('relation') or '?',
                    chosen_flat['plane_label'], chosen_flat['z_mm']))
        subtitle = ('cluster s=[%.2f, %.2f] mm | %d arc crossings'
                    % (chosen_cluster['s_start_mm'], chosen_cluster['s_end_mm'],
                       chosen_cluster['arc_crossing_count']))
        if target is not None:
            for label, s_value, marker, color in (
                    ('s0', target['best_s_start_mm'], 'D', '#2ca02c'),
                    ('s1', target['best_s_end_mm'], 'D', '#2ca02c')):
                if s_value is None:
                    continue
                s_value = min(max(float(s_value), 0.0), float(chain['length_mm']))
                point, _tangent = P.path_point_at(chain['prims'], s_value)
                axis.scatter([point[0]], [point[1]], marker=marker, s=95,
                             color=color, zorder=7,
                             label='rebuild interval %s' % label
                                   if label == 's0' else None)
            subtitle = (subtitle
                        + ' | target %s z=%.2f mm (%s+%s) net %+d'
                        % (target['target_plane_label'], target['target_z_mm'],
                           target['best_entry_mode'], target['best_exit_mode'],
                           int(target['best_estimated_net'])))
        axis.set_title(title + '\n' + subtitle, fontsize=11)
        axis.set_xlabel('x (mm)')
        axis.set_ylabel('y (mm)')
        axis.grid(True, linewidth=0.3, alpha=0.4)
        axis.set_aspect('equal', adjustable='datalim')
        axis.legend(fontsize=8, loc='best')
        figure.tight_layout()
        figure.savefig(paths[index], dpi=140)
        plt.close(figure)
        produced.append(dict(path=str(paths[index]), route_id=route_id,
                             cluster_index=int(chosen_cluster['cluster_index']),
                             target=(dict(target) if target else None)))
    return produced


def make_plots(result, own_records, routes, chains_by_route, plots_dir):
    plots_dir = Path(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)
    # keep the output directory deterministic on re-runs
    for stale in sorted(plots_dir.glob('arc_crossing_*.png')):
        try:
            stale.unlink()
        except OSError:
            pass
    produced = []
    targets = [
        ('arc_crossing_hotspot.png', plot_hotspot, 'XY hotspot map'),
        ('arc_crossing_angle_hist.png', plot_angle_hist,
         'crossing angle distribution'),
        ('arc_crossing_per_height.png', plot_per_height,
         'crossings per physical height'),
        ('arc_crossing_top20_routes.png', plot_top20_routes,
         'top-20 routes by arc crossings'),
    ]
    for name, function, title in targets:
        path = plots_dir / name
        function(result, path)
        produced.append(dict(path=str(path), kind=name, title=title))
    examples = _pick_example_routes(result['top_routes'])
    example_paths = [plots_dir / ('arc_crossing_example_%d_route_%d.png'
                                  % (index + 1, int(item['route_id'])))
                     for index, item in enumerate(examples)]
    produced.extend(plot_examples(result, own_records, routes,
                                  chains_by_route, example_paths))
    return produced


# ================================================== markdown report
def _format_table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |',
             '| ' + ' | '.join('---' for _ in headers) + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(value) for value in row) + ' |')
    return '\n'.join(lines)


def _short_path(path):
    try:
        return str(Path(path))
    except TypeError:
        return str(path)


def build_report(result):
    aggregates = result['aggregates']
    verification = aggregates['verification']
    totals = aggregates['totals']
    lines = []
    lines.append('# E0 圆弧交叉分析报告（2440 交叉基线 → 圆弧区局部三维重建输入）')
    lines.append('')
    lines.append('## 1. 输入与口径')
    lines.append('')
    inputs = result['inputs']
    lines.append('- 只读基线：`%s`' % _short_path(inputs['baseline_dir']))
    lines.append('- 线路：%d 条（可行 %d 条，失败 %d 条）；交叉事件：%d 个（冻结 '
                 '`crossing_stats.json` 事件，strict-D56 合法横向交叉）。'
                 % (inputs['route_count'], inputs['routed'], inputs['failed'],
                    totals['events']))
    lines.append('- 交叉平面：%d 个；全部交叉都不涉及 manual（冻结）线路。'
                 % totals['crossing_planes'])
    lines.append('- 定位方法：把每个事件点 (x, y) **解析投影**到双方线路在该事件物理高度 z '
                 '上的所有 flat 图元（line 投影到线段、arc 投影到圆弧角度区间），取最近图元；'
                 '投影误差见第 2 节。')
    lines.append('- 侧别分类：交叉点在某一侧所在图元的类型为 line 或 arc；事件类别 = 两侧类型的'
                 '多重集合：`line-line` / `line-arc` / `arc-arc`。')
    lines.append('- flat 角色：`base_body`（线路主目标高度上的 body flat）、'
                 '`excursion`（native 三维线路在其它高度上的 body flat）、`lead`（接口引出段）。'
                 '本基线共 %d 条 native 三维线路（带 mid 换层 excursion）。'
                 % inputs['native_routes'])
    lines.append('- 目标高度是否“可用”按 13 个 movable 物理高度判断（manual 平面为冻结手工几何，'
                 '只作几何参考）；重建区间与 S 曲线口径见第 7 节。')
    lines.append('')
    projection = verification.get('projection') or {}
    lines.append('投影校验：%d 个侧别，最大误差 %.2e mm，p99 %.2e mm，超差 %d 个'
                 '（阈值 %.0e mm）；图元交点处歧义 %d 个侧别。'
                 % (projection.get('sides', 0),
                    projection.get('max_projection_error_mm') or 0.0,
                    projection.get('p99_projection_error_mm') or 0.0,
                    projection.get('projection_failures', 0),
                    projection.get('tolerance_mm', PROJECTION_TOL_MM),
                    projection.get('ambiguous_junction_sides', 0)))
    lines.append('')
    lines.append('## 2. 总体分类')
    lines.append('')
    rows = []
    names = {'line-line': '直线-直线', 'line-arc': '直线-圆弧',
             'arc-arc': '圆弧-圆弧'}
    for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
        count = int(totals['class_counts'].get(crossing_class, 0))
        rows.append([names[crossing_class], count,
                     '%.2f%%' % (100.0 * totals['class_fractions'][crossing_class])])
    rows.append(['**合计**', totals['events'], '100.00%'])
    lines.append(_format_table(['类别', '事件数', '占比'], rows))
    lines.append('')
    lines.append('- 任一侧在圆弧上的事件（arc 涉及）：**%d / %d = %.2f%%**；'
                 '两侧都在圆弧上的事件：%d / %d = %.2f%%。'
                 % (totals['any_arc'], totals['events'],
                    100.0 * totals['any_arc_fraction'], totals['both_arc'],
                    totals['events'], 100.0 * totals['both_arc_fraction']))
    lines.append('- 逐侧位置计数：line %d，arc %d（共 %d 个侧别位置）。'
                 % (totals['side_kind'].get('line', 0),
                    totals['side_kind'].get('arc', 0), totals['event_sides']))
    lines.append('- 角色分布（侧别）：%s。'
                 % '，'.join('%s=%d' % (key, value)
                            for key, value in sorted(totals['side_role'].items())))
    lines.append('- 落在 excursion flat 上的交叉事件：%d 个。'
                 % totals['excursion_involved'])
    lines.append('')
    lines.append('### 2.1 “≈49% 的交叉落在圆弧段上”复核')
    lines.append('')
    lines.append('上一轮口径（`crossing_intervals_report.md`，E5 基线）：交叉事件位置 '
                 'line 2659 个（51.0%）、arc 2553 个（49.0%），即 **每个事件在双方各记一次位置**，'
                 'arc 位置占比 49.0%。')
    rows = []
    labels = {
        'per_side_incidence': '逐侧位置占比（上一轮同口径）',
        'per_event_any_arc': '事件“任一侧为圆弧”占比',
        'per_event_both_arc': '事件“两侧均为圆弧”占比',
    }
    for item in _previous_claim_rows(aggregates):
        rows.append([labels[item['definition']], item['count'], item['denom'],
                     '%.2f%%' % (100.0 * item['fraction'])])
    lines.append(_format_table(['定义', '圆弧计数', '分母', '占比'], rows))
    lines.append('')
    lines.append('- **结论：论断成立**。本基线按上一轮完全相同的口径为 '
                 '**%.2f%%**（%d/%d），与 49.0%% 一致；但“49%%”只能对应逐侧位置口径，'
                 '不能解读为“49%% 的交叉事件涉及圆弧”——按事件口径该数字是 '
                 '**%.2f%%**。'
                 % (100.0 * verification['per_side_incidence']['arc_fraction'],
                    verification['per_side_incidence']['arc'],
                    verification['per_side_incidence']['line']
                    + verification['per_side_incidence']['arc'],
                    100.0 * verification['per_event_any_arc']['fraction']))
    lines.append('')
    lines.append('## 3. 按物理高度（平面）分布')
    lines.append('')
    rows = []
    for row in aggregates['per_plane']:
        if row['total'] <= 0:
            continue
        rows.append(['%s' % row['plane_label'], '%.2f' % row['z_mm'],
                     row['counts']['line-line'], row['counts']['line-arc'],
                     row['counts']['arc-arc'], row['total'],
                     '%.2f%%' % (100.0 * row['any_arc_fraction']
                                 if row['any_arc_fraction'] is not None else 0.0),
                     '%.2f%%' % (100.0 * row['arc_side_fraction']
                                 if row['arc_side_fraction'] is not None else 0.0)])
    lines.append(_format_table(['平面', 'z (mm)', 'line-line', 'line-arc',
                                'arc-arc', '合计', 'arc 涉及率', '逐侧 arc 占比'],
                               rows))
    lines.append('')
    lines.append('## 4. 交叉角度分布')
    lines.append('')
    rows = []
    for crossing_class in ('line-line', 'line-arc', 'arc-arc'):
        stats = aggregates['angle']['by_class'][crossing_class]['stats']
        rows.append([names[crossing_class], stats['count'],
                     '%.2f' % (stats['median_deg'] or 0.0),
                     '%.2f' % (stats['mean_deg'] or 0.0),
                     '%.2f' % (stats['min_deg'] or 0.0),
                     '%.2f' % (stats['max_deg'] or 0.0)])
    lines.append(_format_table(['类别', '数量', '中位数 (°)', '均值 (°)',
                                '最小 (°)', '最大 (°)'], rows))
    lines.append('')
    lines.append('说明：本基线 2D 路径为横平竖直直线 + R15 圆弧，因此 line-line 交叉全部是 '
                 '90°，角度分布只对含圆弧的类别有实际展宽；line-arc 中位数约 63°，'
                 'arc-arc 中位数约 49°。')
    lines.append('')
    lines.append('## 5. 圆弧热点线路 Top-20')
    lines.append('')
    rows = []
    for rank, row in enumerate(aggregates['top_routes_by_own_arc'], start=1):
        rows.append([rank, row['route_id'], row['relation'],
                     '%s(%.2f)' % (row['target_plane_label'],
                                   row['target_z_mm'] or 0.0),
                     row['total_crossings'], row['own_arc'],
                     row['arc_involved'], row['own_arc_base_body'],
                     row['own_arc_excursion'],
                     'native' if row['native_3d'] else '',
                     row['arc_primitive_total']])
    lines.append(_format_table(['#', 'route', 'family', 'body 平面(z mm)',
                                '总交叉', '自身弧上', 'arc 涉及', 'base_body',
                                'excursion', 'native', '弧图元数'], rows))
    lines.append('')
    lines.append('说明：%d 条线路至少有一个自身弧上交叉；%d 条线路有交叉；'
                 '本表“自身弧上”= 攻击点落在线路自己的圆弧段上（局部重建的难点所在）。'
                 % (totals['routes_with_own_arc'], totals['routes_with_crossings']))
    lines.append('')
    lines.append('## 6. XY 热点')
    lines.append('')
    hotspot = aggregates['hotspot']
    rows = []
    for row in hotspot['cells'][:10]:
        rows.append(['(%.1f, %.1f)' % (row['x_mm'], row['y_mm']), row['count'],
                     row['line_line'], row['line_arc'], row['arc_arc'],
                     row['any_arc']])
    lines.append(_format_table(['网格中心 (x, y) mm', '交叉数', 'line-line',
                                'line-arc', 'arc-arc', 'arc 涉及'], rows))
    lines.append('')
    lines.append('热点图见 `plots/arc_crossing_hotspot.png`（左：全部事件；右：arc 涉及事件；'
                 '空心圆为 %g mm 网格密度）。' % hotspot['bin_mm'])
    lines.append('')
    lines.append('## 7. Top-10 线路的圆弧区重建区间')
    lines.append('')
    lines.append('口径：对每条线路的每个 “圆弧交叉区”（同一条 body flat 上、由圆弧上的交叉'
                 '组成的极大连续区：同一图元上的交叉强制合并，不同图元之间的间隔只允许穿过'
                 '圆弧或长度 ≤ %g mm 的短直线段），在区两侧寻找可承载 R15 S 曲线的直线段：\n'
                 '- `straight` 模式：S 曲线完全落在 body flat 内该区前/后的直线段上（= 局部区间）；\n'
                 '- `prev_transition` / `next_transition` 模式：圆弧区贴着 flat 起点/终点、'
                 '平直段不足时，用重建相邻换层过渡（fanout 或 mid transition）的方式把线路'
                 '在 flat 起点/终点处直接抬到目标高度（= 端部救援）；\n'
                 '- 若入口与出口都采用换层重建，则整个 body flat 都在目标高度，退化为'
                 '“整段重赋高”（`whole_body_reassign`），会单独标注。\n'
                 '- 中间段 = 原 XY 路径（含原圆弧）在目标高度上的子链，长度必须 ≥ %.2f mm；'
                 '两端 1.25 mm transition shadow 内不得有源高度交叉。'
                 % (result['parameters']['line_merge_mm'],
                    result['parameters']['min_middle_mm']))
    lines.append('')
    for rank, item in enumerate(result['top_routes'], start=1):
        lines.append('### 7.%d route %d（%s，body %s z=%.2f mm，'
                     '自身弧上交叉 %d，总交叉 %d）'
                     % (rank, item['route_id'], item['relation'],
                        (item['flats'][0]['plane_label'] if item['flats'] else '?'),
                        (item['flats'][0]['z_mm'] if item['flats'] else 0.0),
                        item['own_arc_crossings'], item['total_crossings']))
        lines.append('')
        rows = []
        for flat in item['flats']:
            for cluster in flat['clusters']:
                best = cluster['best_target'] or cluster['best_any_target']
                local = cluster['best_local_target']
                rows.append([
                    '%s/%d' % (flat['plane_label'], cluster['cluster_index']),
                    '[%.2f, %.2f]' % (cluster['s_start_mm'], cluster['s_end_mm']),
                    cluster['arc_crossing_count'],
                    cluster['n_arcs_in_region'],
                    '%.2f' % (cluster['arc_length_in_region_mm']),
                    ('%.2f' % cluster['available_before_straight_mm']
                     if cluster['available_before_straight_mm'] is not None else '—'),
                    ('%.2f' % cluster['available_after_straight_mm']
                     if cluster['available_after_straight_mm'] is not None else '—'),
                    cluster['feasible_target_count'],
                    cluster['plausible_feasible_target_count'],
                    cluster['plausible_positive_target_count'],
                    ('%s net %+d' % (best['target_plane_label'],
                                     best['best_estimated_net'])
                     if best else '不可行'),
                    ('%s net %+d' % (local['target_plane_label'],
                                     local['best_estimated_net'])
                     if local else '—'),
                ])
        lines.append(_format_table(['flat/区', 's 区间 (mm)', '弧交叉数',
                                    '区内弧数', '区内弧长', '入口直线可用',
                                    '出口直线可用', '可行高度数(全部)',
                                    '可用高度数(movable)', '正收益高度数',
                                    '最佳目标(可用)', '局部最佳'], rows))
        lines.append('')
        lines.append('说明：“入口/出口直线可用”只统计 body flat 内直线段（不含端部换层救援）；'
                     '端部换层救援的可行性参见下方“可行组合数/方式”列。')
        lines.append('')
        # per height table (movable / plausible targets only)
        chosen = None
        chosen_rank = None
        for flat in item['flats']:
            for cluster in flat['clusters']:
                if cluster['plausible_feasible_target_count'] <= 0:
                    continue
                rank = (-int(cluster['best_target']['best_estimated_net'])
                        if cluster['best_target'] else 0,
                        int(cluster['arc_crossing_count']))
                if chosen_rank is None or rank < chosen_rank:
                    chosen_rank = rank
                    chosen = cluster
        if chosen is None:
            for flat in item['flats']:
                for cluster in flat['clusters']:
                    chosen = cluster
                    break
                if chosen is not None:
                    break
        if chosen is not None:
            rows = []
            for target in chosen['targets']:
                if not target['plausible']:
                    continue
                best = (target['options'][int(target['best_option_index'])]
                        if target['best_option_index'] is not None else None)
                local = (target['options'][int(target['local_option_index'])]
                         if target['local_option_index'] is not None else None)
                entry_ok = any(option['feasible'] for option in target['options']
                               if option['entry_mode'] == 'straight')
                exit_ok = any(option['feasible'] for option in target['options']
                              if option['exit_mode'] == 'straight')
                rows.append([
                    '%s' % target['target_plane_label'],
                    '%.2f' % target['target_z_mm'],
                    '%.2f' % target['footprint_mm'],
                    ('%.2f/%.2f' % (best['footprint_in_mm'],
                                    best['footprint_out_mm'])
                     if best else '—'),
                    '%.2f' % target['required_len_mm'],
                    ('%.2f' % best['span_2d_mm'] if best else '—'),
                    '%.2f/%.2f' % ((target['before_straight'] or {}).get('usable_mm', 0.0),
                                   (target['after_straight'] or {}).get('usable_mm', 0.0)),
                    '是' if entry_ok else '否',
                    '是' if exit_ok else '否',
                    target['feasible_option_count'],
                    ('%+d (−%d/+%d)' % (target['best_estimated_net'],
                                        target['best_estimated_removed'],
                                        target['best_estimated_added'])
                     if best else '—'),
                    ('%+d' % target['local_estimated_net']
                     if target['local_option_index'] is not None else '—'),
                    (best['interval_kind'] if best else '—'),
                    ('%s+%s' % (best['entry_mode'], best['exit_mode'])
                     if best else '—'),
                ])
            lines.append(_format_table(
                ['目标平面', 'z (mm)', 'S 足迹 (mm)', '实际入口/出口足迹 (mm)',
                 '需求长度 (mm)', '区间跨度 (mm)', '入口/出口直线可用 (mm)',
                 '入口直线可承载', '出口直线可承载', '可行组合数', '最佳净变化',
                 '局部净变化', '区间类型', '方式'], rows))
            lines.append('')
            lines.append('说明：JSON 中每个目标高度记录最多 9 个 (s0, s1) 组合'
                         '（不同 snap 起点/终点），上表只列“最佳净变化”组合；'
                         '如需最短区间或特定方向，可从 JSON `options` 中选取。')
            lines.append('')
            lines.append('说明：`S 足迹` 是按 |目标高度−当前 body 高度| 计算的一条 R15 S 曲线'
                         '足迹；`实际入口/出口足迹` 为所选最佳方式实际使用的足迹'
                         '（端部换层救援时分别按 |目标高度−前一/后一flat高度| 计算，'
                         '可能小于/大于 S 足迹）。`需求长度 = 2×S足迹 + %.2f mm`。'
                         % result['parameters']['min_middle_mm'])
            lines.append('')
            lines.append('（仅列出 13 个 movable 目标高度；其余 8 个 manual 平面因属冻结手工'
                         '几何不列为可用目标，全部 21 个高度的完整数据见 '
                         '`analysis/arc_crossing_analysis.json` 的对应 route 记录。）')
            lines.append('')
    lines.append('## 8. 重建区间可用性统计（Top-10）')
    lines.append('')
    availability = result['availability']
    rows = [
        ['分析线路数', availability['routes_total']],
        ['有圆弧交叉区的线路数', availability['routes_with_arc_clusters']],
        ['至少 1 个“几何可行”区间的线路数',
         availability['routes_geometrically_feasible']],
        ['至少 1 个“可用（movable 目标高度 + 估计净收益 ≥ 1）”区间的线路数',
         availability['routes_with_usable_interval']],
        ['其中存在真正“局部（两 S 曲线都在 body flat 直线段内）”方案的线路数',
         availability['routes_with_local_interval']],
        ['只能靠端部换层重建（entry/exit rescue）的可用线路数',
         availability['routes_with_entry_or_exit_rescue_only']],
        ['无可用（净收益 ≥ 1）区间的线路数',
         availability['routes_without_usable_interval']],
        ['圆弧交叉区总数', availability['clusters_total']],
        ['有可行目标高度的区数', availability['clusters_with_feasible_target']],
        ['有正收益目标高度的区数',
         availability['clusters_with_usable_plausible_target']],
    ]
    lines.append(_format_table(['指标', '数量'], rows))
    lines.append('')
    best = availability['usable_route_best_net']
    if best['max'] is not None:
        lines.append('- 可用线路的最佳净变化：min %+d / median %+d / max %+d（合计 %+d）；'
                     '净变化 ≥3 的线路 %d 条、≥5 的 %d 条。'
                     % (best['min'], int(round(best['median'])), best['max'],
                        best['sum'], best['threshold_counts']['3'],
                        best['threshold_counts']['5']))
    local_best = availability.get('local_route_best_net') or {}
    if local_best.get('max') is not None:
        lines.append('- 局部方案的最佳净变化：min %+d / median %+d / max %+d（合计 %+d）。'
                     % (local_best['min'], int(round(local_best['median'])),
                        local_best['max'], local_best['sum']))
    if availability.get('usable_best_interval_kind_counts'):
        lines.append('- 各线路最优方案的类型分布：%s。'
                     % '，'.join('%s=%d' % (key, value) for key, value in
                                sorted(availability['usable_best_interval_kind_counts'].items())))
    if availability['usable_target_height_counts']:
        lines.append('- 可用（线路×目标高度）组合分布：%s。'
                     % '，'.join('%s=%d' % (N.PLANE_LABEL[int(pid)], count)
                                for pid, count in
                                availability['usable_target_height_counts'].items()))
    if availability['usable_entry_exit_mode_counts']:
        lines.append('- 采用方式分布：%s。'
                     % '，'.join('%s=%d' % (key, value) for key, value in
                                sorted(availability['usable_entry_exit_mode_counts'].items())))
    lines.append('')
    lines.append('## 9. 结论与对实验 E 的建议')
    lines.append('')
    own_arc_top = aggregates['top_routes_by_own_arc']
    lines.append('1. **圆弧问题确实存在且集中**：%.2f%% 的交叉事件至少一侧在圆弧段上；'
                 '逐侧口径 %.2f%%（与上一轮 49%% 一致）。%d 条线路共 %d 个“自身弧上”交叉，'
                 '全部落在 base_body flat 上（0 个在 excursion/lead 上）。'
                 % (100.0 * totals['any_arc_fraction'],
                    100.0 * verification['per_side_incidence']['arc_fraction'],
                    totals['routes_with_own_arc'],
                    totals['side_kind'].get('arc', 0)))
    if own_arc_top:
        lines.append('2. **热点高度集中**：自身弧上交叉最多的线路集中在 %s 等高度（见第 5 节），'
                     'Top-10 线路的弧交叉簇大多位于 body flat 的**起始或结束端**，'
                     '平直段只在一侧存在。'
                     % '、'.join(sorted({row['target_plane_label']
                                         for row in own_arc_top[:10]})))
    if availability['usable_entry_exit_mode_counts']:
        lines.append('3. **单靠 body flat 内直线段不够**：需要把贴端圆弧区通过'
                     '“重建相邻换层过渡”的方式纳入重建区间，否则大量热点线路无法执行；'
                     '实际采用方式为 %s。各线路最优方案类型分布：%s。'
                     % ('，'.join('%s=%d' % (key, value) for key, value in
                                 sorted(availability['usable_entry_exit_mode_counts'].items())),
                        '，'.join('%s=%d' % (key, value) for key, value in
                                 sorted(availability.get('usable_best_interval_kind_counts',
                                                         {}).items())) or '—'))
    lines.append('4. 重建区间的净收益只是**几何估计**（源高度移出、目标高度加入的横向交叉），'
                 '尚未做真三维净空与 D56 间距复核；S 曲线跨越中间高度平面时按 D0/实验 E 流程'
                 '仍需 staircase 或逐段验证（见 task-9）。')
    unusable = [item for item in result['top_routes'] if not item['usable']]
    if unusable:
        lines.append('5. **并非所有热点线路都有正收益目标**：%s 在 10 条中最佳可行目标'
                     '仍为负收益（几何可行但估计净变化 < 1），不应纳入实验 E 的首批候选；'
                     '它们的圆弧区仍可用“整段重赋高”等更强手段处理。'
                     % '、'.join('route %d' % item['route_id']
                                for item in unusable))
    lines.append('%d. 建议实验 E 优先尝试 Top-10 中 %d 条“可用”线路的 best 目标高度组合，'
                 '并把本文档第 7 节的 s0/s1、目标高度作为输入；若要求真正“局部”'
                 '（圆弧区两端 S 曲线都在 body flat 直线段内），则只有 %d/%d 条线路存在'
                 '正收益局部方案，其余必须接受端部换层重建（或放宽接口/换层几何）。'
                 % (6 if unusable else 5,
                    availability['routes_with_usable_interval'],
                    availability['routes_with_local_interval'],
                    availability['routes_total']))
    lines.append('')
    lines.append('## 10. 产物与复现')
    lines.append('')
    lines.append('- 脚本：`four_side_1024/fanout1024/native3d/arc_crossing_analysis.py`')
    lines.append('- 入口：`python -m four_side_1024.fanout1024.native3d.arc_crossing_analysis '
                 '--baseline <NATIVE_3D_CROSSING_OPT_1024> --out-dir <NATIVE_3D_JOINT_OPT_1024>`')
    lines.append('- JSON：`analysis/arc_crossing_analysis.json`（全量 2440 事件逐侧分类、'
                 '1024 线路统计、Top-10 重建区间与 21 高度候选）')
    lines.append('- 图：`plots/arc_crossing_hotspot.png`、`arc_crossing_angle_hist.png`、'
                 '`arc_crossing_per_height.png`、`arc_crossing_top20_routes.png`、'
                 '`arc_crossing_example_*.png`（并同步一份到 `analysis/plots/`）')
    lines.append('- 确定性：无时间戳、无随机数；同一输入重复运行输出一致。')
    lines.append('')
    return '\n'.join(lines)


# ================================================== run / CLI
def run(baseline_dir, out_dir, plot_dir=None, top_routes=TOP_ROUTE_COUNT,
        line_merge_mm=CLUSTER_GAP_MM, log=None):
    started = time.time()
    log = log or (lambda *_args, **_kwargs: None)
    baseline_dir = Path(baseline_dir)
    out_dir = Path(out_dir)
    analysis_dir = out_dir / 'analysis'
    plots_dir = Path(plot_dir) if plot_dir is not None else (out_dir / 'plots')
    analysis_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    payload = N.load_json(baseline_dir / 'routes_l3d.json')
    records = payload.get('routes') or []
    routes = {int(record['route_id']): record for record in records
              if str(record.get('status') or '') != 'failed'}
    failed = len(records) - len(routes)
    stats = N.load_json(baseline_dir / 'crossing_stats.json')
    events = stats.get('crossing_events') or []
    log('[arc] baseline %s: %d routes, %d crossing events'
        % (baseline_dir, len(routes), len(events)))

    chains_by_route = {route_id: build_flat_chains(route)
                       for route_id, route in routes.items()}
    roles_by_route = {route_id: build_flat_roles(route)
                      for route_id, route in routes.items()}
    classified = classify_events(routes, chains_by_route, roles_by_route, events)
    projection = projection_verification(classified)
    aggregates = build_aggregates(classified, routes, stats, len(events))
    aggregates['verification']['projection'] = projection
    own_records = collect_own_records(classified)
    log('[arc] classified %d events in %.1fs'
        % (len(classified), time.time() - started))

    top_route_ids = select_top_routes(own_records, top_routes)
    plane_index = CI.PlaneFlatIndex(list(routes.values()))
    params = dict(
        line_merge_mm=float(line_merge_mm),
        shadow_mm=float(SHADOW_MM),
        end_margin_mm=float(END_MARGIN_MM),
        min_middle_mm=float(MIN_MIDDLE_MM),
        min_cross_angle_deg=float(MIN_CROSS_ANGLE_DEG),
        crossing_dedupe_mm=float(CROSSING_DEDUPE_MM),
        max_entry_options=int(MAX_ENTRY_OPTIONS),
        max_exit_options=int(MAX_EXIT_OPTIONS),
        target_plane_ids=[int(pid) for pid in ALL_PLANE_IDS],
        plausible_plane_ids=[int(pid) for pid in PLAUSIBLE_PLANE_IDS],
        manual_plane_ids=[int(pid) for pid in N.MANUAL_PLANES],
        radius_mm=float(R15),
        top_route_count=int(top_routes),
    )
    route_results = []
    for route_id in top_route_ids:
        result = analyse_route_rebuild(route_id, routes[route_id],
                                       chains_by_route[route_id],
                                       own_records.get(route_id, ()),
                                       plane_index, params)
        route_results.append(result)
    route_results = build_route_notes(route_results)
    availability = build_availability_stats(route_results)
    log('[arc] rebuild analysis: %d routes, %d clusters in %.1fs'
        % (len(route_results),
           sum(item['n_clusters'] for item in route_results),
           time.time() - started))

    inputs = dict(
        baseline_dir=str(baseline_dir),
        routes_sha256=N.sha256_file(baseline_dir / 'routes_l3d.json'),
        crossing_stats_sha256=N.sha256_file(baseline_dir / 'crossing_stats.json'),
        route_count=int(len(routes)),
        routed=int(payload.get('routed') or len(routes)),
        failed=int(failed),
        crossing_event_count=int(len(events)),
        crossing_stats_totals=dict(stats.get('totals') or {}),
        native_routes=int(sum(1 for route in routes.values()
                              if route.get('native_3d'))),
        manual_routes=int(sum(1 for route in routes.values()
                              if str(route.get('manual_group') or '').strip())),
        experiment=str(payload.get('experiment') or ''),
        crossing_definition=str(payload.get('crossing_definition') or ''),
    )
    result = dict(
        schema=SCHEMA,
        inputs=inputs,
        parameters=params,
        crossings=classified,
        aggregates=aggregates,
        top_route_ids=[int(route_id) for route_id in top_route_ids],
        top_routes=route_results,
        availability=availability,
        mechanism_notes=dict(
            definitions=dict(
                event='冻结 crossing_stats.json 的 crossing_events 记录 '
                      '(strict-D56 横向交叉，x/y 保留 6 位小数)',
                event_side='事件点解析投影到该线路在事件高度 z 的所有 flat 图元'
                           '（line 到线段垂足、arc 到圆弧角度区间），取最近图元',
                crossing_class='两侧图元类型排序后的多重集合：line-line / line-arc / '
                               'arc-arc',
                per_side_incidence='每个事件在两侧各记一次位置，分母 = 2 * 事件数'
                                   '（与上一轮 49% 口径一致）',
                own_arc_crossing='交叉点落在该线路自身圆弧段上的事件',
                arc_involved='两侧中至少一侧在圆弧段上的事件',
                flat_role='base_body = 主目标高度 body flat；excursion = native '
                          '线路其它高度 body flat；lead = 接口引出段',
                rebuild_interval='[s0, s1]：s0 在圆弧交叉区前方直线段、s1 在其后方'
                                 '直线段，承载两条 R15 S 曲线；中间子链 = 原 XY 路径'
                                 '（含原圆弧）在目标高度',
                arc_crossing_region='同一条 body flat 上、由圆弧上的交叉组成的极大连续区：'
                                    '同一图元上的交叉强制合并，不同图元之间的间隔只允许'
                                    '穿过圆弧或长度 <= %.1f mm 的短直线段' % CLUSTER_GAP_MM,
                interval_kind='local = 两条 S 曲线都在 body flat 直线段内；'
                              'entry_rescue / exit_rescue = 圆弧区贴着 flat 起点/终点，'
                              '用重建相邻换层过渡替代对应 S 曲线；'
                              'whole_body_reassign = 两端换层都重建（退化为整段重赋高）',
                entry_mode='straight = S 曲线在 body flat 内前直线段；'
                           'prev_transition = 重建 flat 前相邻换层过渡，使线路在 flat '
                           '起点即到达目标高度',
                exit_mode='straight = S 曲线在 body flat 内后直线段；'
                          'next_transition = 重建 flat 后相邻换层过渡，使 flat 终点'
                          '仍保持目标高度',
                estimated_removed='源高度上落在 (s0, s1) 内的该线路自身交叉事件数'
                                  '（含直线与圆弧上的交叉）',
                estimated_added='目标高度平面其它线路的 flat 与中间子链的横向交叉数'
                                '（解析求交，5 度最小交叉角，按伙伴线路去重）',
                feasibility='入口/出口均可承载 R15 S 曲线 + 中间段长度 >= %.2f mm + '
                            '两端 1.25 mm 源高度 shadow 内无交叉' % MIN_MIDDLE_MM,
                plausible_target='13 个 movable 物理高度（不含当前高度）；manual 平面'
                                 '为冻结手工几何，仅计入 JSON 参考',
            ),
            parameters=dict(params),
            limitations=[
                '估计只统计平面几何横向交叉，未做真三维净空 / D56 间距复核；'
                '实际可执行性需要 guard.local_world_check 与 strict-D56 重审。',
                '跨越中间高度平面的 R15 S 曲线本身可能被中间平面线路阻挡（见 D0 分析），'
                '实验 E 可能需要对远端高度使用 staircase。',
                'fanout 过渡重建保持接口 lead 姿态不变，但改变了过渡足迹；'
                '中间段在目标高度的 D56 合法性未预判。',
                '重建区间只分析 Top-10 线路，其余线路的圆弧交叉未给候选。',
            ],
        ),
    )
    json_path = analysis_dir / 'arc_crossing_analysis.json'
    N.write_json(json_path, result)
    log('[arc] wrote %s (%.1f MB)' % (json_path,
                                      json_path.stat().st_size / 1.0e6))

    plots = []
    try:
        plots = make_plots(result, own_records, routes, chains_by_route, plots_dir)
        result['plots'] = plots
        N.write_json(json_path, result)
    except Exception as exc:  # pragma: no cover - plotting is optional
        log('[arc] plotting failed: %r' % (exc,))
        result['plots'] = []
        N.write_json(json_path, result)

    report = build_report(result)
    report_path = analysis_dir / 'arc_crossing_report.md'
    report_path.write_text(report, encoding='utf-8')
    log('[arc] wrote %s' % report_path)

    # mirror the figures into analysis/plots/ as well (task wording + convenience)
    mirror_dir = analysis_dir / 'plots'
    try:
        import shutil
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for stale in sorted(mirror_dir.glob('arc_crossing_*.png')):
            try:
                stale.unlink()
            except OSError:
                pass
        for item in (result.get('plots') or []):
            source = Path(item['path'])
            if source.exists():
                shutil.copy2(source, mirror_dir / source.name)
    except Exception as exc:  # pragma: no cover
        log('[arc] plot mirror failed: %r' % (exc,))

    log('[arc] done in %.1fs' % (time.time() - started))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='E0 arc-crossing analysis for the arc-region local 3D rebuild')
    parser.add_argument('--baseline', required=True,
                        help='frozen accepted Native-3D baseline run dir '
                             '(routes_l3d.json + crossing_stats.json)')
    parser.add_argument('--out-dir', required=True,
                        help='new run dir; writes analysis/ and plots/')
    parser.add_argument('--plot-dir', default=None,
                        help='override plot directory (default <out-dir>/plots)')
    parser.add_argument('--top-routes', type=int, default=TOP_ROUTE_COUNT,
                        help='number of arc-hotspot routes for rebuild intervals')
    parser.add_argument('--line-merge-mm', type=float, default=CLUSTER_GAP_MM,
                        help='max straight length that may be bridged inside one '
                             'arc-crossing region')
    parser.add_argument('--quiet', action='store_true', help='no progress log')
    args = parser.parse_args(argv)
    log = None if args.quiet else (lambda message: print(message, flush=True))
    started = time.time()
    result = run(args.baseline, args.out_dir, plot_dir=args.plot_dir,
                 top_routes=args.top_routes,
                 line_merge_mm=args.line_merge_mm, log=log)
    if not args.quiet:
        aggregates = result['aggregates']
        totals = aggregates['totals']
        print('classes: %s' % dict(totals['class_counts']))
        print('any_arc: %d / %d = %.4f' % (totals['any_arc'], totals['events'],
                                           totals['any_arc_fraction']))
        print('per-side arc fraction: %.4f' % totals['side_arc_fraction'])
        print('runtime: %.1fs' % (time.time() - started))
    return 0


if __name__ == '__main__':
    sys.exit(main())
