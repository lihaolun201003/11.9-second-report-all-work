# -*- coding: utf-8 -*-
"""Shared helpers for the crossing-source analysis (read-only on the baseline).

All paths are derived from this file's location, so every script can be run
from any working directory:

    <repo>/outputs/manual_c4_new_connectivity/NON_C4_CROSSING_OPT_1024/analysis/scripts/

The baseline run directory (21-height rebalanced 1024) is READ-ONLY.  Nothing in
this package writes outside ``analysis/`` (scripts/, plots/, _work/).

Key facts reproduced here (authoritative, from the baseline validator):
  * crossing definition = per physical height strict D56 pairwise audit of all
    merged flat parts (``validate21.check_crossings`` + ``fslw.validate_fslw``).
  * 11890 crossing events / 9797 crossing pairs over 21 heights.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = SCRIPTS_DIR.parent
PROJECT_ROOT = ANALYSIS_DIR.parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASELINE_DIR = (PROJECT_ROOT / 'outputs' / 'manual_c4_new_connectivity'
                / 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024')
OUT_DIR = ANALYSIS_DIR
PLOTS_DIR = OUT_DIR / 'plots'
WORK_DIR = OUT_DIR / '_work'
for _p in (OUT_DIR, PLOTS_DIR, WORK_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --- cross-checked reference totals (crossing_stats.json, baseline) ---------
REFERENCE_TOTALS = dict(crossings=11890, crossing_pairs=9797, violations=0,
                        audited_heights=21, planes_with_crossings=13)
REFERENCE_PLANE_CROSSINGS = OrderedDict([
    (2, 0), (3, 0), (4, 0), (5, 0), (6, 986), (7, 928), (20, 964),
    (1001, 896), (8, 736), (9, 60), (10, 0), (11, 0), (12, 0), (13, 0),
    (14, 60), (15, 1246), (16, 1478), (1002, 60), (17, 1560), (18, 1476),
    (19, 1440),
])
REFERENCE_PLANE_PAIRS = OrderedDict([
    (2, 0), (3, 0), (4, 0), (5, 0), (6, 874), (7, 866), (20, 886),
    (1001, 860), (8, 696), (9, 60), (10, 0), (11, 0), (12, 0), (13, 0),
    (14, 60), (15, 954), (16, 1131), (1002, 60), (17, 1143), (18, 1105),
    (19, 1102),
])
REFERENCE_PER_ROUTE = dict(routes=632, max=83, p95=60.0, mean=37.626582,
                           median=39.0, routes_with_crossings=632)
REFERENCE_ROUTES_SHA256 = ('1fe24c977c36c0b24692ee386213e6e870010ac1f0bed5c6b3a1eb4be53119d9')

# --- frozen model / experiment constants -----------------------------------
MANUAL_FIXED_PLANES = OrderedDict([
    ('Z1-U1', 2), ('Z1-U2', 3), ('Z1-U3', 4), ('Z1-U4', 5),
    ('Z2-U1', 10), ('Z2-U2', 11), ('Z2-U3', 12), ('Z2-U4', 13),
])
Z1_OTHER_ALLOWED = [6, 7, 20, 1001, 8]
Z2_OTHER_ALLOWED = [9, 14, 15, 16, 1002, 17, 18, 19]
Z1_MANUAL_ALLOWED = [2, 3, 4, 5]
Z2_MANUAL_ALLOWED = [10, 11, 12, 13]
ALL_INTERFACE_PLANES = (1001, 1002)

#: movable non-manual families -> allowed plane set (the new experiment)
FAMILY_ALLOWED_PLANES = OrderedDict()
for _fam in ('Z1_NS', 'Z1_SN', 'Z1_EW', 'Z1_WE'):
    FAMILY_ALLOWED_PLANES[_fam] = list(Z1_OTHER_ALLOWED)
for _fam in ('Z2_EN', 'Z2_ES', 'Z2_NW', 'Z2_SW'):
    FAMILY_ALLOWED_PLANES[_fam] = list(Z2_OTHER_ALLOWED)

#: coarse family groups: (routes, allowed planes) used for recommendations
FAMILY_GROUP = OrderedDict([
    ('Z1_NS', 'Z1_other'), ('Z1_SN', 'Z1_other'),
    ('Z1_EW', 'Z1_other'), ('Z1_WE', 'Z1_other'),
    ('Z2_EN', 'Z2_other'), ('Z2_ES', 'Z2_other'),
    ('Z2_NW', 'Z2_other'), ('Z2_SW', 'Z2_other'),
])

FAMILY_ORDER = ['Z1_NS', 'Z1_SN', 'Z1_EW', 'Z1_WE',
                'Z2_EN', 'Z2_ES', 'Z2_NW', 'Z2_SW',
                'Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4',
                'Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4']

#: expected family sizes from the frozen experiment brief
EXPECTED_FAMILY_COUNTS = {
    'Z1_NS': 69, 'Z1_SN': 59, 'Z1_EW': 64, 'Z1_WE': 64,
    'Z2_EN': 100, 'Z2_ES': 100, 'Z2_NW': 100, 'Z2_SW': 100,
    'Z1-U1': 64, 'Z1-U2': 64, 'Z1-U3': 64, 'Z1-U4': 64,
    'Z2-U1': 16, 'Z2-U2': 16, 'Z2-U3': 40, 'Z2-U4': 40,
}

SIDE_NAME = {'N': 'N', 'S': 'S', 'E': 'E', 'W': 'W'}


# ---------------------------------------------------------------------------
# basic io
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def write_json(path, payload, indent=None, sort_keys=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=indent,
                  sort_keys=sort_keys)
        handle.write('\n')
    return path


def read_csv_rows(path):
    import csv
    with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def as_bool(value):
    return str(value).strip().lower() in ('true', '1', 'yes', 'direct')


def as_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_float(value, default=None):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# model / baseline loading
# ---------------------------------------------------------------------------
def load_planes():
    """The frozen 21-height model, ordered by z then plane_id."""
    payload = read_json(BASELINE_DIR / 'layer_planes.json')
    planes = OrderedDict()
    for entry in payload['planes']:
        planes[int(entry['plane_id'])] = dict(
            plane_id=int(entry['plane_id']),
            label=str(entry['label']),
            z_mm=round(float(entry['z_mm']), 9),
            kind=str(entry['kind']),
            role=entry.get('role'),
            role_detail=entry.get('role_detail'),
            side=entry.get('side'),
            is_interface=bool(entry.get('is_interface')),
            assigned=entry.get('assigned'),
        )
    return planes


def load_routes_payload():
    return read_json(BASELINE_DIR / 'routes_l3d.json')


def load_assignment_rows():
    return read_csv_rows(BASELINE_DIR / 'assignment_1024.csv')


def load_crossing_stats():
    return read_json(BASELINE_DIR / 'crossing_stats.json')


def flat_z_of(part):
    try:
        return float(part.get('z_mm'))
    except (TypeError, ValueError):
        return None


def route_flat_parts(record):
    """[(z, prims)] for every flat part of a route record (validator order)."""
    out = []
    for part in record.get('parts') or []:
        if not isinstance(part, dict) or part.get('kind') != 'flat':
            continue
        z = flat_z_of(part)
        if z is None:
            continue
        prims = []
        for prim in part.get('primitives') or []:
            if not isinstance(prim, dict):
                continue
            if prim.get('kind') == 'line':
                try:
                    p0 = (float(prim['p0'][0]), float(prim['p0'][1]))
                    p1 = (float(prim['p1'][0]), float(prim['p1'][1]))
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                if math.dist(p0, p1) <= 1e-12:
                    continue
            prims.append(dict(prim))
        if prims:
            out.append((round(z, 9), prims))
    return out


# ---------------------------------------------------------------------------
# primitives geometry helpers (lines + arcs, same conventions as fslw)
# ---------------------------------------------------------------------------
def prim_start(prim):
    if prim.get('kind') == 'line':
        return (float(prim['p0'][0]), float(prim['p0'][1]))
    if prim.get('kind') == 'arc':
        start = prim.get('start')
        if start is not None:
            return (float(start[0]), float(start[1]))
        center = prim.get('center')
        return (_arc_point(prim, 0.0) if center else None)
    if prim.get('kind') == 'polyline':
        pts = prim.get('points') or []
        return (float(pts[0][0]), float(pts[0][1])) if pts else None
    return None


def prim_end(prim):
    if prim.get('kind') == 'line':
        return (float(prim['p1'][0]), float(prim['p1'][1]))
    if prim.get('kind') == 'arc':
        end = prim.get('end')
        if end is not None:
            return (float(end[0]), float(end[1]))
        return _arc_point(prim, 1.0)
    if prim.get('kind') == 'polyline':
        pts = prim.get('points') or []
        return (float(pts[-1][0]), float(pts[-1][1])) if pts else None
    return None


def _arc_point(prim, t):
    center = prim['center']
    radius = float(prim['radius_mm'] if 'radius_mm' in prim else prim.get('radius'))
    start_angle = float(prim.get('start_angle', prim.get('angle0', 0.0)))
    sweep = float(prim.get('sweep_angle', prim.get('sweep', 0.0)))
    theta = start_angle + sweep * t
    return (float(center[0]) + radius * math.cos(theta),
            float(center[1]) + radius * math.sin(theta))


def prim_kinds(prims):
    return Counter(str(prim.get('kind')) for prim in prims)


def polyline_of(prims):
    """Ordered sample polyline of a flat part (lines run p0->p1, arcs sampled)."""
    points = []
    for prim in prims:
        kind = str(prim.get('kind'))
        if kind == 'line':
            p0 = (float(prim['p0'][0]), float(prim['p0'][1]))
            p1 = (float(prim['p1'][0]), float(prim['p1'][1]))
            if not points or math.dist(points[-1], p0) > 1e-9:
                points.append(p0)
            points.append(p1)
        elif kind == 'arc':
            n = 12
            seg = [_arc_point(prim, i / float(n)) for i in range(n + 1)]
            if points and math.dist(points[-1], seg[0]) > 1e-9:
                points.extend(seg)
            elif not points:
                points.extend(seg)
            else:
                points.extend(seg[1:])
        elif kind == 'polyline':
            pts = [(float(p[0]), float(p[1])) for p in (prim.get('points') or [])]
            if points and pts and math.dist(points[-1], pts[0]) > 1e-9:
                points.extend(pts)
            elif not points:
                points.extend(pts)
            else:
                points.extend(pts[1:])
    return points


def body_chord_of(prims):
    """Straight chord between the two end points of a flat body."""
    pts = polyline_of(prims)
    if len(pts) < 2:
        return None
    return (pts[0], pts[-1])


# ---------------------------------------------------------------------------
# family classification
# ---------------------------------------------------------------------------
def classify_family(route_or_row):
    """Fine-grained route family (16 values: 8 movable + 8 manual U groups)."""
    manual = str(route_or_row.get('manual_group') or '').strip()
    if manual:
        return manual
    plane = str(route_or_row.get('plane') or '').strip().lower()
    src = str(route_or_row.get('source_side') or '').strip().upper()[:1]
    dst = str(route_or_row.get('target_side') or '').strip().upper()[:1]
    if plane == 'z1':
        return {'NS': 'Z1_NS', 'SN': 'Z1_SN',
                'EW': 'Z1_EW', 'WE': 'Z1_WE'}.get(src + dst,
                                                  'Z1_%s%s' % (src, dst))
    return {'EN': 'Z2_EN', 'ES': 'Z2_ES',
            'NW': 'Z2_NW', 'SW': 'Z2_SW'}.get(src + dst,
                                              'Z2_%s%s' % (src, dst))


def family_group(family):
    if family in FAMILY_GROUP:
        return FAMILY_GROUP[family]
    return 'manual'


def is_manual_family(family):
    return family not in FAMILY_GROUP


def allowed_planes_for(family, current_plane_id, frozen):
    if frozen:
        return [int(current_plane_id)]
    if family in FAMILY_ALLOWED_PLANES:
        return list(FAMILY_ALLOWED_PLANES[family])
    for group, plane_id in MANUAL_FIXED_PLANES.items():
        if family == group:
            return [int(plane_id)]
    return [int(current_plane_id)]


# ---------------------------------------------------------------------------
# timeline / distribution helpers
# ---------------------------------------------------------------------------
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


def distribution(counter, universe=None):
    """Same schema as validate21._crossing_distribution."""
    values = sorted(int(value) for value in counter.values())
    if not values:
        return dict(routes=0, max=0, p95=0.0, mean=0.0, median=0.0,
                    routes_with_crossings=0)
    return dict(routes=len(values), max=int(values[-1]),
                p95=round(percentile(values, 0.95), 6),
                mean=round(sum(values) / float(len(values)), 6),
                median=round(percentile(values, 0.5), 6),
                routes_with_crossings=sum(1 for value in values if value > 0))


def distribution_over_universe(counter, universe):
    """Distribution over ALL routes of a universe (zeros included)."""
    return distribution({rid: int(counter.get(rid, 0)) for rid in universe})


# ---------------------------------------------------------------------------
# authoritative crossing recomputation (exact replica of validate21 grouping)
# ---------------------------------------------------------------------------
def compute_crossings(routes, planes, verbose=True):
    """Recompute the per-height strict D56 audit exactly like validate21.

    Groups ALL flat parts by physical z (interface planes merge frozen leads +
    interface-direct bodies), then runs one ``audit_route_pairs`` per height.
    Returns dict(planes=[...], totals={...}, crossings=[...]).
    """
    from four_side_1024.fanout1024 import common as fanout_common
    from four_side_1024.fanout1024.reheight21 import validate21 as V21
    from four_side_1024.fslw import validate_fslw

    clearance = fanout_common.CLEARANCE_2D_MM
    sagitta = V21.SAGITTA_MM

    groups = group_flats_by_height(routes)

    planes_by_z = {}
    for plane in planes.values():
        planes_by_z[round(float(plane['z_mm']), 9)] = plane

    plane_rows = []
    all_crossings = []
    all_violations = []
    route_crossings = Counter()
    totals = dict(crossings=0, crossing_pairs=0, violations=0)
    for z_key in sorted(groups):
        plane = planes_by_z.get(z_key)
        if plane is None:
            plane = dict(plane_id=None, label='unknown_z%+.3f' % z_key,
                         z_mm=z_key, kind='unknown', interface=None)
        route_prims = groups[z_key]
        prepared = []
        for route_id, prims in sorted(route_prims.items()):
            try:
                prepared.append(validate_fslw.prepare_route(prims, route_id=route_id))
            except (ValueError, KeyError, TypeError) as error:   # pragma: no cover
                all_violations.append(dict(kind='prepare_failed', route_id=route_id,
                                           detail=str(error)))
        result = validate_fslw.audit_route_pairs(
            prepared, clearance=clearance, sagitta=sagitta, policy='strict') if prepared \
            else dict(crossing_count=0, crossing_pair_count=0, violations=[], crossings=[],
                      min_non_crossing_centerline_mm=None)
        plane_counter = Counter()
        for crossing in result.get('crossings') or []:
            a = as_int(crossing.get('route_a'))
            b = as_int(crossing.get('route_b'))
            all_crossings.append(dict(
                plane_id=plane.get('plane_id'), z_mm=round(z_key, 9),
                route_a=a, route_b=b,
                x_mm=round(float(crossing['x']), 6),
                y_mm=round(float(crossing['y']), 6),
                angle_deg=round(float(crossing['angle_deg']), 6)))
            if a is not None:
                plane_counter[a] += 1
                route_crossings[a] += 1
            if b is not None:
                plane_counter[b] += 1
                route_crossings[b] += 1
        plane_rows.append(dict(
            plane_id=plane.get('plane_id'), label=plane.get('label'),
            z_mm=round(z_key, 9), kind=plane.get('kind'),
            interface=plane.get('interface'),
            routes=len(route_prims),
            parts=sum(len(items) for items in route_prims.values()),
            crossings=int(result.get('crossing_count') or 0),
            crossing_pairs=int(result.get('crossing_pair_count') or 0),
            min_non_crossing_centerline_mm=result.get('min_non_crossing_centerline_mm'),
            violations=len(result.get('violations') or []),
            route_crossing_distribution=distribution(plane_counter),
            route_ids=sorted(route_prims),
        ))
        totals['crossings'] += plane_rows[-1]['crossings']
        totals['crossing_pairs'] += plane_rows[-1]['crossing_pairs']
        totals['violations'] += plane_rows[-1]['violations']
        if verbose:
            print('  plane %-14s z=%+.2f routes=%3d crossings=%5d pairs=%5d'
                  % (plane.get('label'), z_key, len(route_prims),
                     plane_rows[-1]['crossings'], plane_rows[-1]['crossing_pairs']))
    totals['audited_heights'] = len(plane_rows)
    totals['planes_with_crossings'] = sum(1 for row in plane_rows
                                          if row['crossings'] > 0)
    totals['per_route_distribution'] = distribution(route_crossings)
    totals['min_non_crossing_centerline_mm'] = min(
        (row['min_non_crossing_centerline_mm'] for row in plane_rows
         if row['min_non_crossing_centerline_mm'] is not None), default=None)
    return dict(planes=plane_rows, totals=totals, crossings=all_crossings,
                violations=all_violations, route_crossings=dict(route_crossings))


def verify_reference(result, strict=True):
    """Compare a recomputation against the frozen crossing_stats.json numbers."""
    problems = []
    totals = result['totals']
    for key, expected in REFERENCE_TOTALS.items():
        got = totals.get(key)
        if got != expected:
            problems.append('TOTAL %s: got %r expected %r' % (key, got, expected))
    by_plane = {row['plane_id']: row for row in result['planes']}
    for plane_id, expected in REFERENCE_PLANE_CROSSINGS.items():
        row = by_plane.get(plane_id)
        if row is None:
            problems.append('MISSING plane %s' % plane_id)
            continue
        if row['crossings'] != expected:
            problems.append('PLANE %s crossings %d != %d'
                            % (plane_id, row['crossings'], expected))
        if row['crossing_pairs'] != REFERENCE_PLANE_PAIRS[plane_id]:
            problems.append('PLANE %s pairs %d != %d'
                            % (plane_id, row['crossing_pairs'],
                               REFERENCE_PLANE_PAIRS[plane_id]))
    dist = totals['per_route_distribution']
    for key, expected in REFERENCE_PER_ROUTE.items():
        if dist.get(key) != expected:
            problems.append('PER_ROUTE %s: %r != %r'
                            % (key, dist.get(key), expected))
    if problems and strict:
        raise SystemExit('crossing reproduction FAILED:\n  ' + '\n  '.join(problems))
    return problems


# ---------------------------------------------------------------------------
# route table (one enriched record per route)
# ---------------------------------------------------------------------------
def build_route_table(planes):
    """1024 enriched route records: geometry anchors, family, plane metadata."""
    routes = load_routes_payload()['routes']
    assignment = {as_int(row['route_id']): row for row in load_assignment_rows()}
    plane_by_z = {round(plane['z_mm'], 9): plane for plane in planes.values()}
    table = OrderedDict()
    for record in routes:
        rid = as_int(record['route_id'])
        row = assignment.get(rid, {})
        family = classify_family(record)
        manual = bool(str(record.get('manual_group') or '').strip())
        target_layer = as_int(record.get('target_layer'))
        target_z = round(float(record.get('target_z_mm')), 9)
        plane = plane_by_z.get(target_z)
        direct = bool(record.get('direct'))
        frozen = manual
        allowed = allowed_planes_for(family, target_layer, frozen)
        # flat geometry anchors: [{'z':z,'plane_id':pid,'prims':...,'chord':...}]
        flats = []
        for z, prims in route_flat_parts(record):
            pid = (plane_by_z.get(z) or {}).get('plane_id')
            flats.append(dict(z_mm=z, plane_id=pid, prims=prims,
                              chord=body_chord_of(prims)))
        table[rid] = dict(
            route_id=rid,
            plane=record.get('plane'),
            family=family,
            family_group=family_group(family),
            is_manual=manual,
            is_direct=direct,
            frozen=frozen,
            manual_group=record.get('manual_group') or '',
            layer_role=record.get('layer_role') or '',
            target_layer=target_layer,
            target_z_mm=target_z,
            target_plane=(plane or {}).get('plane_id'),
            target_plane_label=(plane or {}).get('label'),
            allowed_planes=allowed,
            needs_transition=bool(record.get('needs_transition')),
            n_transitions=record.get('n_transitions'),
            length_mm=record.get('length_mm'),
            xy_length_mm=record.get('xy_length_mm'),
            source_endpoint=record.get('source_endpoint'),
            target_endpoint=record.get('target_endpoint'),
            source_side=record.get('source_side'),
            target_side=record.get('target_side'),
            c4_group_id=as_int(row.get('c4_group_id')),
            rotation_phase=as_int(row.get('rotation_phase')),
            baseline_old_layer=as_int(row.get('baseline_old_layer')),
            flats=flats,
        )
    return table


def body_chords(table, plane_id):
    """route_id -> straight chord of the body flat on ``plane_id``."""
    out = {}
    for rid, rec in table.items():
        for flat in rec['flats']:
            if flat['plane_id'] == plane_id and flat['chord'] is not None:
                out[rid] = flat['chord']
    return out


def port_xy(table, rid):
    """Board-side port coordinates (source, target) in mm."""
    rec = table[rid]
    src = rec.get('source_endpoint')
    dst = rec.get('target_endpoint')
    return src, dst


# ---------------------------------------------------------------------------
# board ports + straight port-to-port chords (topology analysis)
# ---------------------------------------------------------------------------
BOARD_MM = 150.0
BOARD_EPS_MM = 1e-6


def split_endpoint(endpoint_id):
    """'E07:2:14' -> dict(connector='E07', row=2, column=14)."""
    text = str(endpoint_id or '')
    parts = text.split(':')
    out = dict(connector=parts[0] if parts else '', row=None, column=None)
    if len(parts) >= 3:
        out['row'] = as_int(parts[1])
        out['column'] = as_int(parts[2])
    return out


def load_port_map():
    """route_id -> {src:(x,y), dst:(x,y), src_ep, dst_ep, connector/row/column}."""
    out = {}
    for row in load_assignment_rows():
        rid = as_int(row.get('route_id'))
        if rid is None:
            continue
        src_ep = split_endpoint(row.get('source_endpoint'))
        dst_ep = split_endpoint(row.get('target_endpoint'))
        out[rid] = dict(
            src=(float(row['source_x_mm']), float(row['source_y_mm'])),
            dst=(float(row['target_x_mm']), float(row['target_y_mm'])),
            src_ep=row.get('source_endpoint'), dst_ep=row.get('target_endpoint'),
            src_side=row.get('source_side'), dst_side=row.get('target_side'),
            src_connector=src_ep['connector'], dst_connector=dst_ep['connector'],
            src_row=src_ep['row'], dst_row=dst_ep['row'],
            src_column=src_ep['column'], dst_column=dst_ep['column'],
        )
    return out


def port_side(point):
    """Board side of a port coordinate (N/S/E/W), tolerance 1e-6 mm."""
    x, y = point
    if abs(y - BOARD_MM) <= BOARD_EPS_MM:
        return 'N'
    if abs(y) <= BOARD_EPS_MM:
        return 'S'
    if abs(x - BOARD_MM) <= BOARD_EPS_MM:
        return 'E'
    if abs(x) <= BOARD_EPS_MM:
        return 'W'
    return '?'


#: how to place a port position along each side on the *counter-clockwise*
#: boundary walk starting at (150,0): E: y up, N: x left, W: y down, S: x right.
SIDE_CCW_START = {'E': 0.0, 'N': 90.0, 'W': 180.0, 'S': 270.0}


def side_along(point):
    """Coordinate of a port along its own side in the CCW walk direction."""
    side = port_side(point)
    x, y = point
    if side == 'E':
        return y
    if side == 'N':
        return BOARD_MM - x
    if side == 'W':
        return BOARD_MM - y
    if side == 'S':
        return x
    return None


def ccw_angle(point):
    """CCW angle (degrees, 0..360) of a boundary port around the board."""
    side = port_side(point)
    along = side_along(point)
    if side is None or along is None:
        return None
    return (SIDE_CCW_START[side] + along) % 360.0


def segments_intersect(p1, q1, p2, q2):
    """True iff the two open segments properly cross (no shared endpoints)."""
    def orient(a, b, c):
        value = ((b[0] - a[0]) * (c[1] - a[1])
                 - (b[1] - a[1]) * (c[0] - a[0]))
        if abs(value) <= 1e-12:
            return 0
        return 1 if value > 0 else -1

    o1 = orient(p1, q1, p2)
    o2 = orient(p1, q1, q2)
    o3 = orient(p2, q2, p1)
    o4 = orient(p2, q2, q1)
    if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
        return False
    return o1 != o2 and o3 != o4


def segment_intersection(p1, q1, p2, q2):
    """Intersection point + acute angle (deg) for two properly crossing segments."""
    if not segments_intersect(p1, q1, p2, q2):
        return None
    rx, ry = q1[0] - p1[0], q1[1] - p1[1]
    sx, sy = q2[0] - p2[0], q2[1] - p2[1]
    denom = rx * sy - ry * sx
    if abs(denom) <= 1e-15:
        return None
    t = ((p2[0] - p1[0]) * sy - (p2[1] - p1[1]) * sx) / denom
    x = p1[0] + t * rx
    y = p1[1] + t * ry
    a1 = math.degrees(math.atan2(ry, rx))
    a2 = math.degrees(math.atan2(sy, sx))
    diff = abs(a1 - a2) % 180.0
    acute = min(diff, 180.0 - diff)
    return (x, y), acute


def acute_angle_between(p1, q1, p2, q2):
    a1 = math.degrees(math.atan2(q1[1] - p1[1], q1[0] - p1[0]))
    a2 = math.degrees(math.atan2(q2[1] - p2[1], q2[0] - p2[0]))
    diff = abs(a1 - a2) % 180.0
    return min(diff, 180.0 - diff)


def chord_pairs_crossing(chords):
    """All pairs (a, b) whose straight port chords properly cross.

    ``chords`` = {route_id: ((x0, y0), (x1, y1))}.  Returns
    {(a, b): dict(x=, y=, angle_deg=)} with a < b.
    """
    items = sorted(chords.items())
    out = {}
    for i in range(len(items)):
        a, (p1, q1) = items[i]
        ax0, ax1 = min(p1[0], q1[0]), max(p1[0], q1[0])
        ay0, ay1 = min(p1[1], q1[1]), max(p1[1], q1[1])
        for j in range(i + 1, len(items)):
            b, (p2, q2) = items[j]
            # bbox prune
            if max(p2[0], q2[0]) < ax0 or min(p2[0], q2[0]) > ax1:
                continue
            if max(p2[1], q2[1]) < ay0 or min(p2[1], q2[1]) > ay1:
                continue
            hit = segment_intersection(p1, q1, p2, q2)
            if hit is not None:
                point, angle = hit
                out[(a, b)] = dict(x=round(point[0], 6), y=round(point[1], 6),
                                   angle_deg=round(angle, 6))
    return out


def bbox_overlap_area(bbox_a, bbox_b):
    if bbox_a is None or bbox_b is None:
        return 0.0
    dx = min(bbox_a[2], bbox_b[2]) - max(bbox_a[0], bbox_b[0])
    dy = min(bbox_a[3], bbox_b[3]) - max(bbox_a[1], bbox_b[1])
    if dx <= 0.0 or dy <= 0.0:
        return 0.0
    return round(dx * dy, 6)


def prims_bbox(prims):
    """Axis-aligned bbox (xmin, ymin, xmax, ymax) of a flat primitive list."""
    xs = []
    ys = []
    for prim in prims:
        for point in polyline_of([prim]):
            xs.append(point[0])
            ys.append(point[1])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# flat-part grouping per physical height (shared by analysis and plots)
# ---------------------------------------------------------------------------
def group_flats_by_height(routes):
    """{z_mm: {route_id: [prim, ...]}} - exact replica of the validator grouping."""
    from four_side_1024.fanout1024.reheight21 import validate21 as V21

    groups = OrderedDict()
    for record in routes:
        route_id = as_int(record.get('route_id'))
        if route_id is None:
            continue
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            z = V21._part_flat_z(part)
            if z is None:
                continue
            prims = []
            for prim in part.get('primitives') or []:
                if not isinstance(prim, dict):
                    continue
                if prim.get('kind') == 'line':
                    p0 = V21._finite_xy(prim.get('p0'))
                    p1 = V21._finite_xy(prim.get('p1'))
                    if p0 is None or p1 is None:
                        continue
                    if math.dist(p0, p1) <= 1e-12:
                        continue
                prims.append(dict(prim))
            if prims:
                groups.setdefault(round(z, 9), {}).setdefault(route_id, []).extend(prims)
    return groups
