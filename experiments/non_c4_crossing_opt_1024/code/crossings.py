# -*- coding: utf-8 -*-
"""Authoritative same-layer crossing audit for the C4-free experiment.

The crossing definition is the one used by the frozen 21-height validator
(``reheight21.validate21.check_crossings``): every flat part is grouped by its
*physical height* ``z`` (the two interface heights therefore merge the frozen
interface leads, the interface-direct bodies and any other flat at z=0.0/0.5 into
one audit), and every group is audited with the independent
``four_side_1024.fslw.validate_fslw`` strict-policy route-pair audit.

Nothing here is approximate: the totals produced by :func:`crossing_report`
must reproduce the frozen baseline exactly (11890 crossing events / 9797
crossing pairs).
"""
from __future__ import annotations

import hashlib
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import common as C
from ...fslw import validate_fslw
from ..reheight21 import model as M
from . import data as D

#: the same constants the validator uses
D56_CLEARANCE_MM = C.CLEARANCE_2D_MM          # 0.08 mm centreline
SAGITTA_MM = 0.0005
CROSSING_SCHEMA = 'nonc4_crossing_stats_v1'

__all__ = [
    'D56_CLEARANCE_MM', 'SAGITTA_MM', 'CROSSING_SCHEMA',
    'flat_groups_by_z', 'audit_flat_group', 'crossing_report',
    'count_crossings', 'percentile', 'distribution',
]


# --------------------------------------------------------------------- helpers
def _finite_xy(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return (x, y)


def flat_z(part):
    try:
        z = float(part.get('z_mm'))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(z):
        return None
    return z


def _clean_primitives(primitives):
    out = []
    for prim in primitives or ():
        if not isinstance(prim, dict):
            continue
        if prim.get('kind') == 'line':
            p0 = _finite_xy(prim.get('p0'))
            p1 = _finite_xy(prim.get('p1'))
            if p0 is None or p1 is None:
                continue
            if math.dist(p0, p1) <= 1e-12:
                continue
        out.append(dict(prim))
    return out


def flat_groups_by_z(records):
    """``OrderedDict(z -> OrderedDict(route_id -> [primitive, ...]))``.

    Exactly the grouping of ``validate21.check_crossings``: every flat part is
    collected per physical height, nothing is skipped.
    """
    groups = OrderedDict()
    for record in records:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        for part in record.get('parts') or ():
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            z = flat_z(part)
            if z is None:
                continue
            prims = _clean_primitives(part.get('primitives'))
            if not prims:
                continue
            entry = groups.setdefault(round(z, 9), OrderedDict())
            entry.setdefault(route_id, []).extend(prims)
    return groups


def audit_flat_group(route_prims):
    """Strict route-pair audit of one physical height.

    ``route_prims`` is ``{route_id: [primitive, ...]}``.  Returns the exact
    ``validate_fslw.audit_route_pairs`` result (crossings list with route_a /
    route_b / x / y / angle_deg, violation list, min non-crossing distance).
    """
    prepared = []
    failed = []
    for route_id, prims in sorted(route_prims.items()):
        try:
            prepared.append(validate_fslw.prepare_route(prims,
                                                        route_id=int(route_id)))
        except (ValueError, KeyError, TypeError) as error:  # pragma: no cover
            failed.append(dict(route_id=int(route_id), error=str(error)))
    if not prepared:
        return dict(crossing_count=0, crossing_pair_count=0, violations=[],
                    crossings=[], min_non_crossing_centerline_mm=None,
                    prepare_failures=failed)
    result = validate_fslw.audit_route_pairs(
        prepared, clearance=D56_CLEARANCE_MM, sagitta=SAGITTA_MM,
        policy='strict')
    result['prepare_failures'] = failed
    return result


def count_crossings(route_prims):
    """Fast crossing counts of one already-grouped height: (events, pairs)."""
    result = audit_flat_group(route_prims)
    return int(result.get('crossing_count') or 0), \
        int(result.get('crossing_pair_count') or 0)


# ------------------------------------------------------------------- statistics
def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * float(fraction)
    lower = int(math.floor(position))
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight)
                 + sorted_values[upper] * weight)


def distribution(counter):
    values = sorted(int(value) for value in counter.values())
    if not values:
        return dict(routes=0, max=0, p95=0.0, mean=0.0, median=0.0,
                    routes_with_crossings=0)
    return dict(routes=len(values), max=int(values[-1]),
                p95=round(percentile(values, 0.95), 6),
                mean=round(sum(values) / float(len(values)), 6),
                median=round(percentile(values, 0.5), 6),
                routes_with_crossings=sum(1 for value in values if value > 0))


# --------------------------------------------------------------------- report
def crossing_report(records, planes=None, assignment_by_id=None,
                    include_events=True, routes_path=None):
    """Full authoritative crossing report with per-plane and per-route detail.

    ``planes`` is the ``layer_planes.json`` payload (or ``None`` to derive the
    21-height model from ``reheight21.model``).  ``assignment_by_id`` enables the
    interface-direct / manual classification of the crossing partners.
    """
    started = time.time()
    groups = flat_groups_by_z(records)
    if planes is None:
        plane_rows = [dict(plane_id=int(pid), label=M.plane_label(pid),
                           z_mm=float(M.plane_z(pid)),
                           kind=M.plane_kind(pid))
                      for pid in M.PLANE_IDS]
    else:
        plane_rows = [dict(item) for item in planes['planes']]
    planes_by_z = {}
    for plane in plane_rows:
        planes_by_z[round(float(plane['z_mm']), 9)] = plane

    assignment_by_id = assignment_by_id or {}
    manual_ids = {rid for rid, row in assignment_by_id.items()
                  if str(row.get('manual_group') or '').strip()}
    direct_ids = {rid for rid, row in assignment_by_id.items()
                  if D.is_direct(row)}

    all_route_crossings = Counter()
    totals = dict(crossings=0, crossing_pairs=0, violations=0)
    plane_stats = []
    events = []
    audited_heights = 0
    for z_key in sorted(groups):
        plane = planes_by_z.get(z_key)
        if plane is None:
            plane = dict(plane_id=None, label=f'unknown_z{z_key:+.3f}',
                         z_mm=z_key, kind='unknown')
        route_prims = groups[z_key]
        result = audit_flat_group(route_prims)
        route_crossings = Counter()
        for crossing in result.get('crossings') or ():
            rid_a = int(crossing['route_a'])
            rid_b = int(crossing['route_b'])
            route_crossings[rid_a] += 1
            route_crossings[rid_b] += 1
            all_route_crossings[rid_a] += 1
            all_route_crossings[rid_b] += 1
            if include_events:
                events.append(dict(
                    route_a=rid_a, route_b=rid_b,
                    plane_id=plane.get('plane_id'),
                    plane_label=plane.get('label'), z_mm=round(z_key, 6),
                    x_mm=round(float(crossing['x']), 6),
                    y_mm=round(float(crossing['y']), 6),
                    angle_deg=round(float(crossing['angle_deg']), 6),
                    manual_a=rid_a in manual_ids, manual_b=rid_b in manual_ids,
                    direct_a=rid_a in direct_ids, direct_b=rid_b in direct_ids,
                ))
        plane_row = dict(
            plane_id=plane.get('plane_id'), label=plane.get('label'),
            z_mm=round(z_key, 6), kind=plane.get('kind'),
            route_count=len(route_prims),
            part_count=sum(len(items) for items in route_prims.values()),
            crossings=int(result.get('crossing_count') or 0),
            crossing_pairs=int(result.get('crossing_pair_count') or 0),
            violations=len(result.get('violations') or []),
            min_non_crossing_centerline_mm=(
                None if result.get('min_non_crossing_centerline_mm') is None
                else round(float(result['min_non_crossing_centerline_mm']), 9)),
            route_crossing_distribution=distribution(route_crossings),
            prepare_failures=result.get('prepare_failures') or [],
        )
        plane_stats.append(plane_row)
        totals['crossings'] += plane_row['crossings']
        totals['crossing_pairs'] += plane_row['crossing_pairs']
        totals['violations'] += plane_row['violations']
        audited_heights += 1
    minima = [row['min_non_crossing_centerline_mm'] for row in plane_stats
              if row['min_non_crossing_centerline_mm'] is not None]
    report = dict(
        schema=CROSSING_SCHEMA,
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        crossing_rule=dict(
            d56_centerline_mm=D56_CLEARANCE_MM, sagitta_mm=SAGITTA_MM,
            policy='strict (legal transverse crossings preserved)',
            note='geometric proxy only; no optical loss is claimed'),
        totals=dict(
            crossings=totals['crossings'],
            crossing_pairs=totals['crossing_pairs'],
            violations=totals['violations'],
            audited_heights=audited_heights,
            planes_with_crossings=sum(1 for row in plane_stats
                                      if row['crossings'] > 0),
            per_route_distribution=distribution(all_route_crossings),
            min_non_crossing_centerline_mm=(min(minima) if minima else None),
        ),
        planes=plane_stats,
        per_route_crossings={str(rid): int(count)
                             for rid, count in sorted(all_route_crossings.items())},
        runtime_seconds=round(time.time() - started, 2),
    )
    if routes_path is not None:
        report['routes_file'] = str(Path(routes_path))
        report['routes_file_sha256'] = D.sha256_file(routes_path)
    if include_events:
        report['crossing_events'] = events
    return report


def quick_totals(records):
    """Cheap totals only (no per-event records)."""
    groups = flat_groups_by_z(records)
    total = 0
    pairs = 0
    per_plane = OrderedDict()
    for z_key, route_prims in groups.items():
        events, npairs = count_crossings(route_prims)
        total += events
        pairs += npairs
        per_plane[str(z_key)] = dict(crossings=events, pairs=npairs,
                                     routes=len(route_prims))
    return dict(crossings=total, crossing_pairs=pairs, per_plane=per_plane)
