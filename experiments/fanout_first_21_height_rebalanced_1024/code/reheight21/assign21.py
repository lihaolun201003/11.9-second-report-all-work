# -*- coding: utf-8 -*-
"""Experiment A of the 21-routing-height rebalanced 1024 experiment.

Owner: assign21 (data-verifier).  Contract: ``reheight21/SPEC.md`` sections 1-2
and the Lead's frozen API (2026-11-03).

What this module produces (all inside ``reheight21.model.RUN_DIR``)
-------------------------------------------------------------------
* ``layer_planes.json``        -- the 21 routing heights (frozen schema);
* ``assignment_1024.csv``      -- the new 1024-row assignment (whole C4 orbits on
  one body plane for every non-manual route, manual groups fixed);
* ``assignment_audit.json``    -- counts, orbit allocations, hard invariants and
  the read-only baseline cross-check;
* ``assignment_diff_vs_baseline.json`` / ``.md`` -- route-level old plane -> new
  plane audit against the frozen 18-layer baseline;
* ``experiment_A/``            -- ``summary.json``, ``layer_audit.csv``,
  ``audit.json``, ``validation_status.json`` (SPEC section 6 / task contract);
* ``physical_layer_stack.json`` -- the new 19-body-plane ``l3d`` stack;
* ``process_rules.json``       -- process rules incl. the interface-body rule.

The baseline run directory is READ-ONLY: it is opened for reading only
(``assignment_1024.csv``) and its sha256 is recorded before and after this
module writes anything, so "baseline untouched" is an audited fact.

Assignment rules (SPEC section 2)
---------------------------------
* manual fixed (368): Z1-U1..Z1-U4 -> planes 2/3/4/5, Z2-U1..Z2-U4 ->
  planes 10/11/12/13; membership is exactly the verified baseline assignment;
* Z1 other (256, 64 C4 ``opposite`` orbits): orbits sorted by ``group_id``,
  consumed from ``model.Z1_OTHER_PLAN`` -> 52/52/52/52/48 routes;
* Z2 other (400, 100 C4 ``adjacent`` orbits): the baseline assignment's old
  target layer is remapped 1:1 to the new plane
  ``model.Z2_OTHER_OLD_TO_NEW`` (whole orbits preserved);
* ``needs_transition = target_z != interface_z``; ``direction`` is
  ``direct`` / ``down`` / ``up`` (expect 100 direct routes, 1848 endpoint
  transitions on the remaining 924 routes).

Entry points::

    .venv\\Scripts\\python.exe -m four_side_1024.fanout1024.reheight21.assign21
    .venv\\Scripts\\python.exe -m four_side_1024.fanout1024.reheight21.tests_assign21

``main()`` is importable and takes no required argument (``run21.stage_a`` calls
it when the assignment is missing).
"""
from __future__ import annotations

import collections
import csv
import hashlib
import math
import time
from pathlib import Path

from .. import common as C
from . import model as M

# ================================================================ contract
ASSIGNMENT_COLUMNS = [
    'route_id', 'plane', 'relation', 'manual_group', 'manual_pattern',
    'layer_role', 'target_layer', 'target_plane_label', 'target_z_mm',
    'interface_z_mm', 'direction', 'needs_transition', 'c4_group_id',
    'rotation_phase', 'baseline_old_layer', 'source_endpoint',
    'target_endpoint', 'source_side', 'target_side', 'source_connector',
    'target_connector', 'source_x_mm', 'source_y_mm', 'target_x_mm',
    'target_y_mm', 'source_row', 'target_row',
]

#: exact plane counts stage A of run21 asserts (SPEC section 2)
EXPECTED_PLANE_COUNTS = collections.OrderedDict([
    (2, 64), (3, 64), (4, 64), (5, 64),
    (6, 52), (7, 52), (20, 52), (1001, 52), (8, 48),
    (9, 48),
    (10, 16), (11, 16), (12, 40), (13, 40),
    (14, 48), (15, 48), (16, 52), (1002, 48), (17, 52), (18, 52), (19, 52),
])
EXPECTED_DIRECT_ROUTES = 100
EXPECTED_DIRECT_Z1 = 52
EXPECTED_DIRECT_Z2 = 48
EXPECTED_TRANSITION_ROUTES = 1024 - EXPECTED_DIRECT_ROUTES
EXPECTED_ENDPOINT_TRANSITIONS = 2 * EXPECTED_TRANSITION_ROUTES   # 1848
EXPECTED_MANUAL_COUNTS = collections.OrderedDict([
    ('Z1-U1', 64), ('Z1-U2', 64), ('Z1-U3', 64), ('Z1-U4', 64),
    ('Z2-U1', 16), ('Z2-U2', 16), ('Z2-U3', 40), ('Z2-U4', 40),
])
EXPECTED_MANUAL_TOTAL = sum(EXPECTED_MANUAL_COUNTS.values())      # 368
EXPECTED_Z1_OTHER_COUNTS = collections.OrderedDict([
    (plane, capacity * 4) for plane, capacity in M.Z1_OTHER_PLAN])
# baseline old-layer -> route count (from the frozen baseline assignment)
EXPECTED_OLD_LAYER_COUNTS = collections.OrderedDict([
    (8, 48), (9, 48), (14, 48), (15, 52), (16, 52), (17, 52), (18, 52),
    (19, 48),
])
#: new-plane route counts implied by the old-layer -> new-plane mapping
EXPECTED_Z2_OTHER_COUNTS = collections.OrderedDict(
    (int(new_plane), int(EXPECTED_OLD_LAYER_COUNTS[int(old_layer)]))
    for old_layer, new_plane in M.Z2_OTHER_OLD_TO_NEW.items())

#: manual C4 orbit structure: each manual orbit is split over exactly the two
#: fixed planes of its numbering scheme (NS plane + EW plane)
EXPECTED_MANUAL_ORBIT_PLANE_SETS = {
    (2, 4): 32, (3, 5): 32, (10, 11): 8, (12, 13): 20,
}

_ROWS = None
_STATE = None


# ================================================================ baseline
def load_baseline():
    """Read the frozen baseline assignment (READ-ONLY) and its metadata."""
    path = M.BASE_ASSIGNMENT
    if not path.is_file():
        raise FileNotFoundError(f'baseline assignment missing: {path}')
    rows, digest = C.read_csv_rows(path)
    by_id = {}
    planes = collections.Counter()
    manual_counts = collections.Counter()
    layer_counts = collections.Counter()
    roles = collections.Counter()
    for row in rows:
        try:
            rid = int(float(row['route_id']))
        except (KeyError, TypeError, ValueError):
            continue
        by_id[rid] = row
        planes[str(row.get('plane'))] += 1
        manual = str(row.get('manual_group') or '').strip()
        if manual:
            manual_counts[manual] += 1
        layer_counts[int(float(row['target_layer']))] += 1
        roles[str(row.get('layer_role') or '')] += 1
    return dict(
        path=str(path),
        run_dir=str(M.BASELINE_RUN_DIR),
        sha256=digest,
        rows=len(rows),
        route_ids=sorted(by_id),
        by_id=by_id,
        planes=dict(planes),
        roles=dict(roles),
        manual_counts=dict(manual_counts),
        layer_counts=dict(sorted(layer_counts.items())),
    )


def _read_baseline_file_sha256():
    try:
        return C.sha256_file(M.BASE_ASSIGNMENT)
    except Exception:  # pragma: no cover - defensive
        return None


# ================================================================ assignment
def _manual_allocation(baseline):
    """route_id -> fixed new plane / group / pattern from the baseline."""
    manual = {}
    baseline_manual_counts = collections.Counter()
    for rid, row in baseline['by_id'].items():
        group = str(row.get('manual_group') or '').strip()
        if not group:
            continue
        if group not in M.MANUAL_GROUP_SPECS:
            raise KeyError(f'route {rid}: unknown baseline manual group '
                           f'{group!r}')
        spec = M.MANUAL_GROUP_SPECS[group]
        baseline_layer = int(float(row['target_layer']))
        if baseline_layer != spec['plane_id']:
            raise ValueError(
                f'route {rid}: baseline manual layer {baseline_layer} != '
                f'model plane {spec["plane_id"]} for group {group}')
        manual[rid] = dict(plane_id=spec['plane_id'], group=group,
                           pattern=spec['pattern'],
                           layer_role=('z1_manual_u' if group.startswith('Z1')
                                       else 'z2_manual_u'),
                           sides=spec['sides'])
        baseline_manual_counts[group] += 1
    return manual, dict(baseline_manual_counts)


def _z1_other_allocation(groups):
    """Whole C4 ``opposite`` Z1 orbits -> five planes per model.Z1_OTHER_PLAN."""
    plan = list(M.Z1_OTHER_PLAN)
    orbit_plane = collections.OrderedDict()
    route_plane = {}
    index = 0
    for plane_id, capacity in plan:
        for _ in range(int(capacity)):
            if index >= len(groups):
                raise ValueError('Z1 other plan exceeds the orbit count')
            group = groups[index]
            index += 1
            orbit_plane[int(group['group_id'])] = int(plane_id)
            for rid in group['route_ids']:
                route_plane[int(rid)] = int(plane_id)
    if index != len(groups):
        raise ValueError('Z1 other plan does not consume all orbits')
    return route_plane, orbit_plane


def _z2_other_allocation(baseline, z2_orbits):
    """Whole C4 ``adjacent`` Z2 orbits: baseline old layer -> new plane."""
    route_plane = {}
    orbit_plane = collections.OrderedDict()
    old_layer_counts = collections.Counter()
    for group in z2_orbits:
        old_layers = {int(float(baseline['by_id'][int(rid)]['target_layer']))
                      for rid in group['route_ids']}
        if len(old_layers) != 1:
            raise ValueError(f'z2 orbit {group["group_id"]}: baseline old '
                             f'layers not unique: {sorted(old_layers)}')
        old_layer = old_layers.pop()
        if old_layer not in M.Z2_OTHER_OLD_TO_NEW:
            raise ValueError(f'z2 orbit {group["group_id"]}: old layer '
                             f'{old_layer} has no new-plane mapping')
        new_plane = int(M.Z2_OTHER_OLD_TO_NEW[old_layer])
        orbit_plane[int(group['group_id'])] = dict(
            old_layer=old_layer, new_plane=new_plane,
            route_ids=[int(rid) for rid in group['route_ids']])
        for rid in group['route_ids']:
            route_plane[int(rid)] = new_plane
        old_layer_counts[old_layer] += len(group['route_ids'])
    return route_plane, orbit_plane, dict(sorted(old_layer_counts.items()))


def build_assignment(force=False):
    """Return the new 1024-row assignment (deterministic; cached)."""
    global _ROWS
    if _ROWS is not None and not force:
        return _ROWS
    routes = C.routes()
    route_by_id = {int(route['route_id']): route for route in routes}
    baseline = load_baseline()
    if baseline['rows'] != 1024 or len(baseline['by_id']) != 1024:
        raise ValueError(f'baseline assignment is not 1024 rows: '
                         f'{baseline["rows"]}')
    if sorted(route_by_id) != baseline['route_ids']:
        raise ValueError('baseline route ids differ from common.routes()')
    groups = C.rotation_groups()
    group_of = C.route_group_map()
    z1_opposite = sorted([group for group in groups
                          if group['plane'] == 'z1'
                          and group['kind'] == 'opposite'],
                         key=lambda group: int(group['group_id']))
    z2_adjacent = sorted([group for group in groups
                          if group['plane'] == 'z2'
                          and group['kind'] == 'adjacent'],
                         key=lambda group: int(group['group_id']))
    if len(z1_opposite) != 64 or len(z2_adjacent) != 100:
        raise ValueError('unexpected baseline orbit counts: '
                         f'z1_opposite={len(z1_opposite)} '
                         f'z2_adjacent={len(z2_adjacent)}')

    manual, baseline_manual_counts = _manual_allocation(baseline)
    if baseline_manual_counts != dict(EXPECTED_MANUAL_COUNTS):
        raise ValueError(f'baseline manual counts differ: '
                         f'{baseline_manual_counts}')
    z1_route_plane, z1_orbit_plane = _z1_other_allocation(z1_opposite)
    z2_route_plane, z2_orbit_plane, z2_old_layer_counts = \
        _z2_other_allocation(baseline, z2_adjacent)

    rows = []
    for route in sorted(routes, key=lambda item: int(item['route_id'])):
        rid = int(route['route_id'])
        plane_name = str(route['plane'])
        base = baseline['by_id'][rid]
        group_spec = group_of[rid]
        if rid in manual:
            spec = manual[rid]
            plane_id = int(spec['plane_id'])
            manual_group = spec['group']
            manual_pattern = spec['pattern']
            layer_role = spec['layer_role']
            baseline_old_layer = ''
        elif plane_name == 'z1':
            if rid not in z1_route_plane:
                raise KeyError(f'z1 other route {rid} not allocated')
            plane_id = int(z1_route_plane[rid])
            manual_group = ''
            manual_pattern = ''
            layer_role = 'z1_other'
            baseline_old_layer = int(float(base['target_layer']))
        else:
            if rid not in z2_route_plane:
                raise KeyError(f'z2 other route {rid} not allocated')
            plane_id = int(z2_route_plane[rid])
            manual_group = ''
            manual_pattern = ''
            layer_role = 'z2_other'
            baseline_old_layer = int(float(base['target_layer']))
        target_z = M.plane_z(plane_id)
        interface_z = M.interface_z(plane_name)
        needs = M.needs_transition(plane_id, plane_name)
        if needs:
            direction = 'down' if target_z < interface_z else 'up'
        else:
            direction = 'direct'
        record = collections.OrderedDict()
        record['route_id'] = rid
        record['plane'] = plane_name
        record['relation'] = str(route['relation'])
        record['manual_group'] = manual_group
        record['manual_pattern'] = manual_pattern
        record['layer_role'] = layer_role
        record['target_layer'] = int(plane_id)
        record['target_plane_label'] = M.plane_label(plane_id)
        record['target_z_mm'] = float(target_z)
        record['interface_z_mm'] = float(interface_z)
        record['direction'] = direction
        record['needs_transition'] = bool(needs)
        record['c4_group_id'] = int(group_spec['group_id'])
        record['rotation_phase'] = int(
            group_spec['route_ids'].index(rid))
        record['baseline_old_layer'] = baseline_old_layer
        record['source_endpoint'] = str(route['source_endpoint'])
        record['target_endpoint'] = str(route['target_endpoint'])
        record['source_side'] = str(route['source_side'])
        record['target_side'] = str(route['target_side'])
        record['source_connector'] = str(route['source_connector'])
        record['target_connector'] = str(route['target_connector'])
        record['source_x_mm'] = float(route['source_xy'][0])
        record['source_y_mm'] = float(route['source_xy'][1])
        record['target_x_mm'] = float(route['target_xy'][0])
        record['target_y_mm'] = float(route['target_xy'][1])
        record['source_row'] = int(route['source_row'])
        record['target_row'] = int(route['target_row'])
        rows.append(record)
    _check_contract(rows)
    state = dict(
        rows=rows,
        baseline=baseline,
        manual=manual,
        baseline_manual_counts=baseline_manual_counts,
        z1_orbit_plane=z1_orbit_plane,
        z2_orbit_plane=z2_orbit_plane,
        z2_old_layer_counts=z2_old_layer_counts,
        z1_opposite_groups=z1_opposite,
        z2_adjacent_groups=z2_adjacent,
        route_by_id=route_by_id,
        group_of=group_of,
    )
    global _STATE
    _STATE = state
    _ROWS = rows
    return rows


def _state(force=False):
    global _STATE
    if _STATE is None or force:
        build_assignment(force=force)
    return _STATE


# ================================================================ checks
def _new(passed, detail=None):
    return dict(passed=bool(passed), detail=detail)


def _invariants(rows, state):
    """Every hard invariant of SPEC section 2 + the Lead's frozen contract."""
    baseline = state['baseline']
    route_by_id = state['route_by_id']
    group_of = state['group_of']
    checks = collections.OrderedDict()

    def add(check_id, passed, detail=None, description=''):
        checks[check_id] = dict(id=check_id, description=description,
                                passed=bool(passed), detail=detail)

    ids = [int(row['route_id']) for row in rows]
    add('rows_1024', len(rows) == 1024, dict(rows=len(rows)),
        'exactly 1024 assignment rows')
    add('route_ids_complete_unique',
        len(set(ids)) == 1024 and sorted(ids) == sorted(route_by_id),
        dict(unique=len(set(ids)), true_routes=len(route_by_id)),
        'route ids == common.routes() ids, each exactly once')
    planes = collections.Counter(row['plane'] for row in rows)
    add('plane_split_512_512', dict(planes) == {'z1': 512, 'z2': 512},
        dict(planes), '512 z1 + 512 z2 routes')
    manual_counts = collections.Counter(
        row['manual_group'] for row in rows if row['manual_group'])
    add('manual_total_368',
        sum(manual_counts.values()) == EXPECTED_MANUAL_TOTAL,
        dict(manual_rows=sum(manual_counts.values())),
        '368 manual routes (256 Z1 + 112 Z2)')
    add('manual_group_counts',
        dict(manual_counts) == dict(EXPECTED_MANUAL_COUNTS),
        dict(manual_counts), 'manual group counts 64/64/64/64 + 16/16/40/40')
    manual_fixed = []
    for row in rows:
        group = row['manual_group']
        if not group:
            continue
        spec = M.MANUAL_GROUP_SPECS[group]
        if (int(row['target_layer']) != int(spec['plane_id'])
                or abs(float(row['target_z_mm'])
                       - float(M.plane_z(spec['plane_id']))) > 1e-12
                or row['manual_pattern'] != spec['pattern']
                or row['baseline_old_layer'] != ''):
            manual_fixed.append(dict(row))
    add('manual_routes_fixed', not manual_fixed, manual_fixed[:10],
        'every manual route on its fixed model plane/z/pattern')
    manual_membership = True
    manual_detail = {}
    for group in M.MANUAL_GROUP_SPECS:
        new_ids = {int(row['route_id']) for row in rows
                   if row['manual_group'] == group}
        old_ids = {int(rid) for rid, row in baseline['by_id'].items()
                   if str(row.get('manual_group') or '').strip() == group}
        manual_membership = manual_membership and new_ids == old_ids
        manual_detail[group] = dict(new=len(new_ids), baseline=len(old_ids),
                                    identical=new_ids == old_ids)
    add('manual_membership_matches_baseline', manual_membership, manual_detail,
        'manual route sets identical to the verified baseline assignment')
    baseline_manual_ids = {int(row['route_id']) for row in rows
                           if row['manual_group']}
    add('manual_plane_ids_unchanged',
        all(int(row['target_layer'])
            == int(float(baseline['by_id'][int(row['route_id'])]['target_layer']))
            for row in rows if int(row['route_id']) in baseline_manual_ids),
        None, 'manual plane ids unchanged vs baseline (z values follow model)')

    plane_counts = collections.Counter(int(row['target_layer']) for row in rows)
    add('plane_counts_exact',
        dict(plane_counts) == dict(EXPECTED_PLANE_COUNTS),
        dict(sorted(plane_counts.items())),
        'per-plane route counts exactly as SPEC section 2')
    z1_other_counts = collections.Counter(
        int(row['target_layer']) for row in rows
        if row['layer_role'] == 'z1_other')
    add('z1_other_counts_52_52_52_52_48',
        dict(z1_other_counts) == dict(EXPECTED_Z1_OTHER_COUNTS),
        dict(z1_other_counts), 'Z1 other 52/52/52/52/48 on planes '
        '6/7/20/1001/8')
    z2_other_counts = collections.Counter(
        int(row['target_layer']) for row in rows
        if row['layer_role'] == 'z2_other')
    add('z2_other_counts_48_48_48_52_52_52_52_48',
        dict(z2_other_counts) == dict(EXPECTED_Z2_OTHER_COUNTS),
        dict(z2_other_counts),
        'Z2 other 48/48/48/52/52/52/52/48 via the old-layer mapping')
    direct = [row for row in rows if not row['needs_transition']]
    direct_z1 = [row for row in direct if row['plane'] == 'z1']
    direct_z2 = [row for row in direct if row['plane'] == 'z2']
    add('direct_route_count_100',
        len(direct) == EXPECTED_DIRECT_ROUTES
        and len(direct_z1) == EXPECTED_DIRECT_Z1
        and len(direct_z2) == EXPECTED_DIRECT_Z2,
        dict(total=len(direct), z1=len(direct_z1), z2=len(direct_z2)),
        '100 direct routes: 52 Z1_INTERFACE + 48 Z2_INTERFACE')
    transition = [row for row in rows if row['needs_transition']]
    add('transition_routes_924_endpoints_1848',
        len(transition) == EXPECTED_TRANSITION_ROUTES,
        dict(transition_routes=len(transition),
             endpoint_transitions=2 * len(transition)),
        '924 routes with transitions -> 1848 endpoint transitions')
    add('direct_planes_are_interfaces',
        all(int(row['target_layer']) == M.interface_plane_for(row['plane'])
            for row in direct),
        dict(direct_planes=sorted({int(row['target_layer'])
                                   for row in direct})),
        'every direct route targets its own interface plane (1001/1002)')
    heights = {round(M.plane_z(plane_id), 9) for plane_id in M.PLANE_IDS}
    add('all_21_planes_used',
        len(plane_counts) == 21 and all(plane_counts[plane_id] > 0
                                       for plane_id in M.PLANE_IDS),
        dict(planes_used=len(plane_counts)), 'all 21 routing heights used')
    add('height_count_21_distinct', len(heights) == 21,
        dict(distinct_heights=sorted(heights)), '21 distinct physical heights')
    measured_pitch = M.min_height_pitch()
    add('min_pitch_ge_0.05', measured_pitch >= M.MIN_LAYER_PITCH_MM - 1e-9,
        dict(measured=measured_pitch, required=M.MIN_LAYER_PITCH_MM),
        'minimum neighbour pitch >= 50 um')
    bad_z = [dict(row) for row in rows
             if abs(float(row['target_z_mm'])
                    - M.plane_z(int(row['target_layer']))) > 1e-12]
    add('target_z_matches_model', not bad_z, bad_z[:5],
        'target_z_mm equals model plane z')
    bad_interface = [dict(row) for row in rows
                     if abs(float(row['interface_z_mm'])
                            - M.interface_z(row['plane'])) > 1e-12]
    add('interface_z_matches_plane', not bad_interface, bad_interface[:5],
        'interface z is 0.0 (z1) / 0.5 (z2)')
    bad_direction = []
    for row in rows:
        expected = M.direction_for(int(row['target_layer']), row['plane'])
        if row['direction'] != expected:
            bad_direction.append(dict(row))
    add('direction_rule', not bad_direction, bad_direction[:5],
        "direction is direct/down/up per the target z vs interface z")
    bad_needs = []
    for row in rows:
        expected = M.needs_transition(int(row['target_layer']), row['plane'])
        if bool(row['needs_transition']) != bool(expected):
            bad_needs.append(dict(row))
    add('needs_transition_rule', not bad_needs, bad_needs[:5],
        'needs_transition == (target_z != own interface z)')
    label_bad = [dict(row) for row in rows
                 if row['target_plane_label']
                 != M.plane_label(int(row['target_layer']))]
    add('target_plane_labels', not label_bad, label_bad[:5],
        'target_plane_label matches the model label')

    # ---------------------------------------------------------- orbits
    non_manual_ids = {int(row['route_id']) for row in rows
                      if not row['manual_group']}
    manual_ids = {int(row['route_id']) for row in rows
                  if row['manual_group']}
    non_manual_orbits = [group for group in C.rotation_groups()
                         if all(int(rid) in non_manual_ids
                                for rid in group['route_ids'])]
    spanning = []
    plane_by_route = {int(row['route_id']): int(row['target_layer'])
                      for row in rows}
    for group in non_manual_orbits:
        planes = {plane_by_route[int(rid)] for rid in group['route_ids']}
        if len(planes) != 1:
            spanning.append(dict(c4_group_id=group['group_id'],
                                 planes=sorted(planes)))
    add('nonmanual_orbit_single_plane', not spanning, spanning,
        'every non-manual C4 orbit keeps all 4 routes on one plane '
        '(164 orbits: 64 Z1 other + 100 Z2 other)')
    add('nonmanual_orbit_count_164', len(non_manual_orbits) == 164,
        dict(non_manual_orbits=len(non_manual_orbits)),
        '64 Z1 opposite + 100 Z2 adjacent orbits')
    z1_orbit_ok = True
    z1_detail = []
    for index, group in enumerate(state['z1_opposite_groups']):
        expected_plane = None
        consumed = 0
        for plane_id, capacity in M.Z1_OTHER_PLAN:
            if index < consumed + capacity:
                expected_plane = int(plane_id)
                break
            consumed += capacity
        planes = {plane_by_route[int(rid)] for rid in group['route_ids']}
        ok = planes == {expected_plane}
        z1_orbit_ok = z1_orbit_ok and ok
        if not ok:
            z1_detail.append(dict(orbit_index=index,
                                  group_id=group['group_id'],
                                  planes=sorted(planes),
                                  expected=expected_plane))
    add('z1_other_orbits_follow_plan', z1_orbit_ok, z1_detail[:10],
        'Z1 other orbits sorted by group_id consume model.Z1_OTHER_PLAN')
    z2_orbit_ok = True
    z2_detail = []
    for group_id, info in state['z2_orbit_plane'].items():
        planes = {plane_by_route[int(rid)] for rid in info['route_ids']}
        expected = int(M.Z2_OTHER_OLD_TO_NEW[info['old_layer']])
        ok = planes == {expected}
        z2_orbit_ok = z2_orbit_ok and ok
        if not ok:
            z2_detail.append(dict(c4_group_id=group_id,
                                  planes=sorted(planes), expected=expected))
    add('z2_other_orbits_follow_old_layer_map', z2_orbit_ok, z2_detail[:10],
        'Z2 other whole orbits remapped by their baseline old target layer')
    manual_orbit_counts = collections.Counter()
    manual_orbit_bad = []
    for group in C.rotation_groups():
        if not all(int(rid) in manual_ids for rid in group['route_ids']):
            continue
        planes = tuple(sorted({plane_by_route[int(rid)]
                               for rid in group['route_ids']}))
        manual_orbit_counts[planes] += 1
        if planes not in EXPECTED_MANUAL_ORBIT_PLANE_SETS:
            manual_orbit_bad.append(dict(c4_group_id=group['group_id'],
                                         planes=list(planes)))
    manual_orbit_detail = {
        '+'.join(str(plane_id) for plane_id in planes): int(count)
        for planes, count in manual_orbit_counts.items()}
    expected_manual_orbit_detail = {
        '+'.join(str(plane_id) for plane_id in planes): int(count)
        for planes, count in EXPECTED_MANUAL_ORBIT_PLANE_SETS.items()}
    add('manual_orbit_split_documented',
        dict(manual_orbit_counts) == EXPECTED_MANUAL_ORBIT_PLANE_SETS,
        dict(manual_orbit_detail, expected=expected_manual_orbit_detail),
        'manual orbits split over the documented NS/EW plane pairs '
        '(32x{2,4}, 32x{3,5}, 8x{10,11}, 20x{12,13})')

    # ---------------------------------------------------------- data identity
    port_bad = []
    for row in rows:
        route = route_by_id[int(row['route_id'])]
        if (row['source_endpoint'] != route['source_endpoint']
                or row['target_endpoint'] != route['target_endpoint']
                or row['source_side'] != route['source_side']
                or row['target_side'] != route['target_side']
                or row['source_connector'] != route['source_connector']
                or row['target_connector'] != route['target_connector']
                or abs(float(row['source_x_mm']) - route['source_xy'][0]) > 1e-12
                or abs(float(row['source_y_mm']) - route['source_xy'][1]) > 1e-12
                or abs(float(row['target_x_mm']) - route['target_xy'][0]) > 1e-12
                or abs(float(row['target_y_mm']) - route['target_xy'][1]) > 1e-12):
            port_bad.append(int(row['route_id']))
    add('port_pairs_identical_to_true_routes', not port_bad, port_bad[:10],
        'endpoint ids / sides / connectors / xy identical to common.routes()')
    c4_bad = []
    for row in rows:
        group = group_of[int(row['route_id'])]
        if (int(row['c4_group_id']) != int(group['group_id'])
                or int(row['rotation_phase'])
                != int(group['route_ids'].index(int(row['route_id'])))):
            c4_bad.append(int(row['route_id']))
    add('c4_group_and_phase_match', not c4_bad, c4_bad[:10],
        'c4_group_id/rotation_phase match common.rotation_groups()')
    old_layer_bad = []
    for row in rows:
        base = baseline['by_id'][int(row['route_id'])]
        if row['manual_group']:
            if row['baseline_old_layer'] != '':
                old_layer_bad.append(dict(row))
        else:
            try:
                old = int(float(row['baseline_old_layer']))
            except (TypeError, ValueError):
                old_layer_bad.append(dict(row))
                continue
            if old != int(float(base['target_layer'])):
                old_layer_bad.append(dict(row))
    add('baseline_old_layer_field', not old_layer_bad, old_layer_bad[:10],
        "baseline_old_layer is the baseline target layer ('' for manual)")
    add('baseline_old_layer_counts',
        dict(state['z2_old_layer_counts']) == dict(EXPECTED_OLD_LAYER_COUNTS),
        state['z2_old_layer_counts'],
        'baseline Z2 other old-layer counts 48/48/48/52/52/52/52/48')
    baseline_ok = (baseline['rows'] == 1024
                   and baseline['planes'] == {'z1': 512, 'z2': 512}
                   and dict(baseline['manual_counts'])
                   == dict(EXPECTED_MANUAL_COUNTS))
    add('baseline_assignment_read_ok', baseline_ok,
        dict(rows=baseline['rows'], planes=baseline['planes'],
             manual_counts=baseline['manual_counts']),
        'baseline assignment read-only cross-check (1024 rows, 512/512)')
    rebuilt = build_assignment(force=True)
    add('deterministic_rebuild', rebuilt == rows, None,
        'two consecutive builds are identical')

    failures = [check for check in checks.values() if not check['passed']]
    return checks, failures


def _check_contract(rows):
    """Fail-fast hard contract used while building the assignment rows."""
    if len(rows) != 1024:
        raise ValueError(f'expected 1024 rows, got {len(rows)}')
    ids = [int(row['route_id']) for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate route ids')
    planes = collections.Counter(row['plane'] for row in rows)
    if dict(planes) != {'z1': 512, 'z2': 512}:
        raise ValueError(f'plane split wrong: {dict(planes)}')
    counts = collections.Counter(int(row['target_layer']) for row in rows)
    if dict(counts) != dict(EXPECTED_PLANE_COUNTS):
        raise ValueError(f'plane counts wrong: {dict(sorted(counts.items()))}')
    direct = sum(1 for row in rows if not row['needs_transition'])
    if direct != EXPECTED_DIRECT_ROUTES:
        raise ValueError(f'expected {EXPECTED_DIRECT_ROUTES} direct routes, '
                         f'got {direct}')
    for row in rows:
        expected_z = M.plane_z(int(row['target_layer']))
        if abs(float(row['target_z_mm']) - expected_z) > 1e-12:
            raise ValueError(f'route {row["route_id"]}: target z mismatch')
        expected_direction = M.direction_for(int(row['target_layer']),
                                             row['plane'])
        if row['direction'] != expected_direction:
            raise ValueError(f'route {row["route_id"]}: direction mismatch')
    return True


# ================================================================ audits
def build_audit(rows, state):
    checks, failures = _invariants(rows, state)
    plane_counts = collections.Counter(int(row['target_layer']) for row in rows)
    orbit_planes = collections.defaultdict(set)
    for row in rows:
        orbit_planes[int(row['target_layer'])].add(int(row['c4_group_id']))
    direction_counts = collections.Counter(row['direction'] for row in rows)
    role_counts = collections.Counter(row['layer_role'] for row in rows)
    manual_counts = collections.Counter(
        row['manual_group'] for row in rows if row['manual_group'])
    baseline = state['baseline']
    z1_by_plane = collections.OrderedDict(
        (str(plane_id), sum(1 for row in rows
                            if row['layer_role'] == 'z1_other'
                            and int(row['target_layer']) == int(plane_id)))
        for plane_id, _capacity in M.Z1_OTHER_PLAN)
    z2_by_plane = collections.OrderedDict(
        (str(new_plane), sum(1 for row in rows
                             if row['layer_role'] == 'z2_other'
                             and int(row['target_layer']) == int(new_plane)))
        for old, new_plane in M.Z2_OTHER_OLD_TO_NEW.items())
    audit = dict(
        schema='reheight21_assignment_audit_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        run_dir=str(M.RUN_DIR),
        baseline_run_dir=str(M.BASELINE_RUN_DIR),
        model='reheight21.model',
        assignment_csv=str(M.NEW_ASSIGNMENT),
        rows=len(rows),
        z1=int(plane_counts_total(rows, 'z1')),
        z2=int(plane_counts_total(rows, 'z2')),
        unique_route_ids=len({int(row['route_id']) for row in rows}),
        plane_count=len(M.PLANE_IDS),
        height_count=len({round(M.plane_z(plane_id), 9)
                          for plane_id in M.PLANE_IDS}),
        min_pitch_mm=M.min_height_pitch(),
        min_pitch_required_mm=M.MIN_LAYER_PITCH_MM,
        plane_counts=dict(sorted(plane_counts.items())),
        physical_plane_orbit_counts={
            str(plane_id): len(orbit_planes.get(plane_id, ()))
            for plane_id in M.PLANE_IDS},
        role_counts=dict(role_counts),
        direction_counts=dict(direction_counts),
        manual_counts=dict(manual_counts),
        direct_routes=dict(
            total=sum(1 for row in rows if not row['needs_transition']),
            z1=sum(1 for row in rows
                   if not row['needs_transition'] and row['plane'] == 'z1'),
            z2=sum(1 for row in rows
                   if not row['needs_transition'] and row['plane'] == 'z2'),
            planes=sorted({int(row['target_layer']) for row in rows
                           if not row['needs_transition']}),
        ),
        transition_routes=dict(
            routes=sum(1 for row in rows if row['needs_transition']),
            endpoint_transitions=2 * sum(1 for row in rows
                                         if row['needs_transition'])),
        manual_planes={str(spec['plane_id']): dict(
            group=group, label=spec['label'], z_mm=spec['z_mm'],
            routes=int(manual_counts.get(group, 0)))
            for group, spec in M.MANUAL_GROUP_SPECS.items()},
        z1_other=dict(
            orbits=len(state['z1_opposite_groups']),
            plan=[[int(plane_id), int(capacity)]
                  for plane_id, capacity in M.Z1_OTHER_PLAN],
            routes_per_plane=dict(z1_by_plane),
            orbit_plane=[[int(group_id), int(plane_id)]
                         for group_id, plane_id
                         in state['z1_orbit_plane'].items()],
        ),
        z2_other=dict(
            orbits=len(state['z2_adjacent_groups']),
            old_to_new={str(old): int(new) for old, new
                        in M.Z2_OTHER_OLD_TO_NEW.items()},
            routes_per_new_plane=dict(z2_by_plane),
            baseline_old_layer_counts=dict(state['z2_old_layer_counts']),
            orbit_plane=[[int(group_id), dict(info)] for group_id, info
                         in state['z2_orbit_plane'].items()],
        ),
        baseline=dict(
            path=baseline['path'], sha256=baseline['sha256'],
            rows=baseline['rows'], planes=baseline['planes'],
            manual_counts=baseline['manual_counts'],
            layer_counts=baseline['layer_counts'],
        ),
        layer_model=M.layer_planes_payload(assigned=plane_counts),
        invariants=[dict(check) for check in checks.values()],
        invariant_failures=failures,
        all_invariants_passed=not failures,
        notes=[
            'the baseline RUN_DIR is read-only; only its assignment_1024.csv '
            'is opened for reading and its sha256 is recorded',
            'manual plane ids are unchanged vs the baseline; the Z1 manual '
            'z values follow the new model (planes 3/4/5 shift by '
            '-0.01/-0.02/-0.03 mm)',
            'direct routes (needs_transition=False) keep their plane-owner '
            'layer_role (z1_other / z2_other) in the assignment CSV; the '
            'plane itself carries the interface_direct role in '
            'layer_planes.json',
            'the Z2 other mapping keeps whole C4 orbits: each old target '
            'layer -> one new plane',
        ],
    )
    return audit


def plane_counts_total(rows, plane_name):
    return sum(1 for row in rows if row['plane'] == plane_name)


# ================================================================ baseline diff
def _baseline_old_z(old_layer):
    try:
        return float(C.PHYSICAL_LAYERS[int(old_layer)])
    except KeyError:
        return None


def _baseline_old_label(old_layer):
    try:
        layer = int(old_layer)
    except (TypeError, ValueError):
        return ''
    if layer in C.PHYSICAL_LAYERS:
        return f'L{layer}'
    return f'L{layer}'


def build_diff(rows):
    """Route-level and aggregate diff of the new assignment vs the baseline."""
    baseline = _state()['baseline']
    route_by_id = _state()['route_by_id']
    category_of = {'z1_manual_u': 'z1_manual_u', 'z2_manual_u': 'z2_manual_u',
                   'z1_other': 'z1_other', 'z2_other': 'z2_other'}
    route_changes = []
    transition_matrix = collections.Counter()
    direction_matrix = collections.Counter()
    direction_flips = collections.Counter()
    old_plane_counts = collections.Counter(
        int(layer) for layer in baseline['layer_counts'])
    new_plane_counts = collections.Counter(
        int(row['target_layer']) for row in rows)
    example_flips = collections.defaultdict(list)
    for row in rows:
        rid = int(row['route_id'])
        base = baseline['by_id'][rid]
        old_layer = int(float(base['target_layer']))
        old_z = _baseline_old_z(old_layer)
        old_direction = str(base.get('direction')
                            or ('down' if old_z < float(base['interface_z_mm'])
                                else 'up'))
        new_plane = int(row['target_layer'])
        category = category_of[row['layer_role']]
        direction_matrix[(old_direction, row['direction'])] += 1
        transition_matrix[(old_layer, new_plane)] += 1
        if old_direction != row['direction']:
            direction_flips[f'{old_direction}->{row["direction"]}'] += 1
            key = (category, f'{old_direction}->{row["direction"]}')
            if len(example_flips[key]) < 5:
                example_flips[key].append(rid)
        route_changes.append(dict(
            route_id=rid,
            plane=row['plane'],
            relation=row['relation'],
            category=category,
            manual_group=row['manual_group'],
            old_layer=old_layer,
            old_label=_baseline_old_label(old_layer),
            old_z_mm=old_z,
            old_direction=old_direction,
            new_plane=new_plane,
            new_label=row['target_plane_label'],
            new_z_mm=float(row['target_z_mm']),
            new_direction=row['direction'],
            needs_transition=bool(row['needs_transition']),
            changed_plane=(old_layer != new_plane),
            changed_z=(old_z is None
                       or abs(old_z - float(row['target_z_mm'])) > 1e-9),
        ))
    manual_changes = []
    for group, spec in M.MANUAL_GROUP_SPECS.items():
        group_rows = [row for row in rows if row['manual_group'] == group]
        old_layers = {int(float(baseline['by_id'][int(row['route_id'])]
                                ['target_layer'])) for row in group_rows}
        old_zs = {round(_baseline_old_z(layer), 9) for layer in old_layers}
        manual_changes.append(dict(
            manual_group=group,
            routes=len(group_rows),
            plane_id=int(spec['plane_id']),
            label=spec['label'],
            old_planes=sorted(old_layers),
            plane_id_unchanged=old_layers == {int(spec['plane_id'])},
            old_z_mm=sorted(old_zs),
            new_z_mm=float(spec['z_mm']),
            z_changed=old_zs != {round(float(spec['z_mm']), 9)},
            membership_unchanged=True,
        ))
    z1_other = []
    for index, group in enumerate(_state()['z1_opposite_groups']):
        plane = int(_state()['z1_orbit_plane'][int(group['group_id'])])
        old_layers = {int(float(baseline['by_id'][int(rid)]['target_layer']))
                      for rid in group['route_ids']}
        z1_other.append(dict(
            orbit_index=index, c4_group_id=int(group['group_id']),
            old_layer=sorted(old_layers)[0] if len(old_layers) == 1 else None,
            new_plane=plane, routes_per_orbit=len(group['route_ids']),
        ))
    z2_mapping = []
    for old_layer, new_plane in M.Z2_OTHER_OLD_TO_NEW.items():
        orbits = [group_id for group_id, info
                  in _state()['z2_orbit_plane'].items()
                  if int(info['old_layer']) == int(old_layer)]
        z2_mapping.append(dict(
            old_layer=int(old_layer),
            old_label=_baseline_old_label(old_layer),
            old_z_mm=_baseline_old_z(old_layer),
            new_plane=int(new_plane),
            new_label=M.plane_label(new_plane),
            new_z_mm=M.plane_z(new_plane),
            old_route_count=int(EXPECTED_OLD_LAYER_COUNTS[int(old_layer)]),
            new_route_count=int(new_plane_counts[int(new_plane)]),
            orbits=len(orbits),
            direction_old=('down' if _baseline_old_z(old_layer)
                           < float(C.INTERFACE_Z['z2']) else 'up'),
            direction_new=M.direction_for(int(new_plane), 'z2'),
        ))
    diff = dict(
        schema='reheight21_assignment_diff_vs_baseline_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        new_run_dir=str(M.RUN_DIR),
        baseline_run_dir=str(M.BASELINE_RUN_DIR),
        baseline_assignment=dict(path=str(M.BASE_ASSIGNMENT),
                                 sha256=baseline['sha256'],
                                 rows=baseline['rows'],
                                 planes=baseline['planes'],
                                 layer_counts=baseline['layer_counts'],
                                 manual_counts=baseline['manual_counts']),
        new_assignment=dict(path=str(M.NEW_ASSIGNMENT), rows=len(rows),
                            planes=dict(collections.Counter(
                                row['plane'] for row in rows)),
                            layer_counts=dict(sorted(new_plane_counts.items())),
                            manual_counts=dict(collections.Counter(
                                row['manual_group'] for row in rows
                                if row['manual_group']))),
        plane_counts=dict(
            baseline={str(layer): count for layer, count
                      in sorted(old_plane_counts.items())},
            new={str(plane): count for plane, count
                 in sorted(new_plane_counts.items())},
            baseline_plane_count=len(old_plane_counts),
            new_plane_count=len(new_plane_counts),
        ),
        manual=dict(
            unchanged_membership=True,
            unchanged_plane_ids=all(item['plane_id_unchanged']
                                    for item in manual_changes),
            groups=manual_changes,
            note='manual groups keep their baseline route membership and '
                 'plane ids; the Z1 manual z values follow the new model, so '
                 'planes 3/4/5 shift to -0.30/-0.25/-0.20 mm',
        ),
        z1_other=dict(plan=[[int(plane), int(capacity)] for plane, capacity
                            in M.Z1_OTHER_PLAN],
                      orbits=z1_other,
                      note='64 whole C4 opposite orbits sorted by group_id '
                           'are consumed from the plan (52/52/52/52/48)'),
        z2_other=dict(old_to_new=[dict(item) for item in z2_mapping],
                      note='baseline whole-layer C4 orbit groups are remapped '
                           '1:1 to new planes; direction flips are documented '
                           'in direction_changes'),
        transition_matrix=[[int(old), int(new), int(count)]
                           for (old, new), count
                           in sorted(transition_matrix.items())],
        direction_changes=dict(
            matrix={f'{old}->{new}': count for (old, new), count
                    in sorted(direction_matrix.items())},
            flips=dict(direction_flips),
            example_route_ids={f'{key[0]}:{key[1]}': ids for key, ids
                               in sorted(example_flips.items())},
        ),
        direct_routes=dict(
            total=sum(1 for row in rows if not row['needs_transition']),
            z1=dict(plane=1001,
                    route_ids=[int(row['route_id']) for row in rows
                               if not row['needs_transition']
                               and row['plane'] == 'z1']),
            z2=dict(plane=1002,
                    route_ids=[int(row['route_id']) for row in rows
                               if not row['needs_transition']
                               and row['plane'] == 'z2']),
            note='Z1: baseline L6/L7 routes now direct on Z1_INTERFACE; '
                 'Z2: baseline L19 routes now direct on Z2_INTERFACE'),
        heights=dict(
            baseline_heights=len({round(value, 9) for value
                                  in C.PHYSICAL_LAYERS.values()}),
            new_heights=len({round(M.plane_z(plane_id), 9)
                             for plane_id in M.PLANE_IDS}),
            new_min_pitch_mm=M.min_height_pitch(),
            baseline_planes={str(layer): float(z) for layer, z
                             in C.PHYSICAL_LAYERS.items()},
            new_planes={str(plane_id): float(M.plane_z(plane_id))
                        for plane_id in M.PLANE_IDS},
        ),
        route_changes=route_changes,
        route_change_count=len(route_changes),
        summary=dict(
            routes=len(rows),
            changed_plane=sum(1 for item in route_changes
                              if item['changed_plane']),
            unchanged_plane=sum(1 for item in route_changes
                                if not item['changed_plane']),
            changed_z=sum(1 for item in route_changes if item['changed_z']),
            direction_flip_routes=sum(direction_flips.values()),
            direct_routes=sum(1 for row in rows if not row['needs_transition']),
            manual_unchanged=all(item['plane_id_unchanged']
                                 for item in manual_changes),
        ),
    )
    return diff


def diff_markdown(diff):
    """Human-readable ``assignment_diff_vs_baseline.md``."""
    lines = []
    lines.append('# 21-height rebalanced 1024 assignment — diff vs the '
                 '18-layer baseline')
    lines.append('')
    lines.append(f"* new run dir: `{diff['new_run_dir']}`")
    lines.append(f"* baseline run dir (read-only): "
                 f"`{diff['baseline_run_dir']}`")
    lines.append(f"* baseline assignment sha256: "
                 f"`{diff['baseline_assignment']['sha256']}`")
    lines.append('')
    lines.append('## 1. Plane counts (baseline 18 planes -> new 21 planes)')
    lines.append('')
    lines.append('| plane (new) | label | z (mm) | routes |')
    lines.append('|---|---|---:|---:|')
    for plane_id in M.PLANE_IDS:
        count = diff['new_assignment']['layer_counts'].get(
            str(plane_id), 0)
        lines.append(f"| {plane_id} | {M.plane_label(plane_id)} | "
                     f"{M.plane_z(plane_id):+.2f} | {count} |")
    lines.append('')
    lines.append('| old layer | baseline routes |')
    lines.append('|---|---:|')
    for layer, count in sorted(
            (int(k), v) for k, v in
            diff['plane_counts']['baseline'].items()):
        lines.append(f"| L{layer} | {count} |")
    lines.append('')
    lines.append('## 2. Manual groups (fixed)')
    lines.append('')
    lines.append('| group | routes | new plane | old planes | '
                 'plane id unchanged | old z | new z |')
    lines.append('|---|---:|---:|---|---|---|---:|')
    for item in diff['manual']['groups']:
        lines.append(f"| {item['manual_group']} | {item['routes']} | "
                     f"{item['plane_id']} ({item['label']}) | "
                     f"{item['old_planes']} | {item['plane_id_unchanged']} | "
                     f"{item['old_z_mm']} | {item['new_z_mm']:+.2f} |")
    lines.append('')
    lines.append('## 3. Z1 other (64 C4 opposite orbits, sorted by group_id)')
    lines.append('')
    lines.append('plan: ' + ' '.join(
        f'{plane}:{capacity}' for plane, capacity in M.Z1_OTHER_PLAN))
    lines.append('')
    lines.append('| orbit index | c4 group | old layer | new plane |')
    lines.append('|---:|---:|---:|---:|')
    for item in diff['z1_other']['orbits']:
        lines.append(f"| {item['orbit_index']} | {item['c4_group_id']} | "
                     f"{item['old_layer']} | {item['new_plane']} |")
    lines.append('')
    lines.append('## 4. Z2 other (whole baseline layer C4 groups remapped)')
    lines.append('')
    lines.append('| old layer | baseline routes | new plane | new label | '
                 'new z | new routes | direction old -> new |')
    lines.append('|---|---:|---:|---|---:|---:|---|')
    for item in diff['z2_other']['old_to_new']:
        lines.append(f"| L{item['old_layer']} | {item['old_route_count']} | "
                     f"{item['new_plane']} | {item['new_label']} | "
                     f"{item['new_z_mm']:+.2f} | {item['new_route_count']} | "
                     f"{item['direction_old']} -> {item['direction_new']} |")
    lines.append('')
    lines.append('## 5. Direction changes')
    lines.append('')
    lines.append('routes whose direction differs from the baseline: '
                 f"**{diff['summary']['direction_flip_routes']}**")
    lines.append('')
    lines.append('| change | routes |')
    lines.append('|---|---:|')
    for flip, count in sorted(diff['direction_changes']['flips'].items()):
        lines.append(f'| {flip} | {count} |')
    lines.append('')
    lines.append('## 6. Direct routes (interface bodies)')
    lines.append('')
    lines.append(f"* total direct routes: "
                 f"**{diff['direct_routes']['total']}**")
    lines.append(f"* Z1_INTERFACE (plane 1001): "
                 f"{len(diff['direct_routes']['z1']['route_ids'])} routes")
    lines.append(f"* Z2_INTERFACE (plane 1002): "
                 f"{len(diff['direct_routes']['z2']['route_ids'])} routes")
    lines.append('')
    lines.append('## 7. Heights and pitch')
    lines.append('')
    lines.append(f"* baseline heights: {diff['heights']['baseline_heights']}")
    lines.append(f"* new heights: **{diff['heights']['new_heights']}**")
    lines.append(f"* new minimum pitch: "
                 f"**{diff['heights']['new_min_pitch_mm']:.3f} mm** "
                 f"(required >= 0.05)")
    lines.append('')
    lines.append('## 8. Summary')
    lines.append('')
    summary = diff['summary']
    lines.append(f"* assignment rows: {summary['routes']}")
    lines.append(f"* routes whose target plane changed vs baseline: "
                 f"{summary['changed_plane']}")
    lines.append(f"* routes whose target plane is unchanged: "
                 f"{summary['unchanged_plane']}")
    lines.append(f"* routes whose target z changed: {summary['changed_z']}")
    lines.append(f"* manual groups unchanged (membership + plane ids): "
                 f"{summary['manual_unchanged']}")
    lines.append('')
    lines.append('The baseline 18-layer experiment is read-only and was not '
                 'modified; its assignment sha256 is recorded above.')
    return '\n'.join(lines) + '\n'


# ================================================================ experiment A
def _layer_audit_rows(rows):
    plane_counts = collections.Counter(int(row['target_layer']) for row in rows)
    orbit_planes = collections.defaultdict(set)
    for row in rows:
        orbit_planes[int(row['target_layer'])].add(int(row['c4_group_id']))
    direction = collections.defaultdict(collections.Counter)
    manual_group = {}
    baseline_layers = collections.defaultdict(collections.Counter)
    baseline = _state()['baseline']
    for row in rows:
        plane_id = int(row['target_layer'])
        direction[plane_id][row['direction']] += 1
        if row['manual_group']:
            manual_group[plane_id] = row['manual_group']
        old = row['baseline_old_layer']
        if old != '':
            baseline_layers[plane_id][int(old)] += 1
    audit_rows = []
    for plane_id in M.PLANE_IDS:
        audit_rows.append(dict(
            plane_id=int(plane_id),
            label=M.plane_label(plane_id),
            z_mm=float(M.plane_z(plane_id)),
            kind=M.plane_kind(plane_id),
            role=M.plane_role(plane_id),
            role_detail=M.plane_role_detail(plane_id),
            side=M.plane_side(plane_id),
            route_count=int(plane_counts.get(plane_id, 0)),
            orbit_count=len(orbit_planes.get(plane_id, ())),
            direct_count=int(direction[plane_id].get('direct', 0)),
            down_count=int(direction[plane_id].get('down', 0)),
            up_count=int(direction[plane_id].get('up', 0)),
            manual_group=manual_group.get(plane_id, ''),
            baseline_old_layers=','.join(
                f'L{layer}:{count}' for layer, count
                in sorted(baseline_layers.get(plane_id, {}).items())),
            assigned_ok=plane_counts.get(plane_id, 0) > 0,
        ))
    return audit_rows


def _experiment_a(rows, audit):
    if not M.NEW_EXPERIMENT_A.is_dir():
        M.NEW_EXPERIMENT_A.mkdir(parents=True, exist_ok=True)
    checks = audit['invariants']
    failures = audit['invariant_failures']
    plane_counts = audit['plane_counts']
    layer_rows = _layer_audit_rows(rows)
    summary = dict(
        schema='reheight21_experiment_A_summary_v1',
        experiment='A',
        run_dir=str(M.RUN_DIR),
        baseline_run_dir=str(M.BASELINE_RUN_DIR),
        assignment_rows=len(rows),
        plane_count=audit['plane_count'],
        height_count=audit['height_count'],
        min_pitch_mm=audit['min_pitch_mm'],
        planes_used=len([plane for plane, count in plane_counts.items()
                         if count > 0]),
        manual_routes=sum(audit['manual_counts'].values()),
        manual_counts=audit['manual_counts'],
        role_counts=audit['role_counts'],
        direction_counts=audit['direction_counts'],
        direct_routes=audit['direct_routes'],
        transition_routes=audit['transition_routes'],
        plane_counts=plane_counts,
        baseline=dict(path=str(M.BASE_ASSIGNMENT),
                      sha256=audit['baseline']['sha256'],
                      rows=audit['baseline']['rows'],
                      plane_counts=audit['baseline']['layer_counts']),
        diff_summary=dict(
            changed_plane=sum(1 for row in rows
                              if row['baseline_old_layer'] != ''
                              and int(row['baseline_old_layer'])
                              != int(row['target_layer']))
            + sum(1 for row in rows if row['manual_group']
                  and int(row['target_layer'])
                  != int(M.MANUAL_GROUP_SPECS[row['manual_group']]['plane_id'])),
            manual_unchanged=all(
                int(row['target_layer'])
                == int(M.MANUAL_GROUP_SPECS[row['manual_group']]['plane_id'])
                for row in rows if row['manual_group']),
        ),
        validation_status='passed' if not failures else 'failed',
        artifacts=dict(
            layer_planes=str(M.LAYER_PLANES_JSON),
            assignment=str(M.NEW_ASSIGNMENT),
            audit=str(M.NEW_ASSIGNMENT_AUDIT),
            diff_json=str(M.NEW_ASSIGNMENT_DIFF_JSON),
            diff_md=str(M.NEW_ASSIGNMENT_DIFF_MD),
            stack=str(M.NEW_STACK_JSON),
            rules=str(M.NEW_RULES_JSON),
            experiment_a=str(M.NEW_EXPERIMENT_A),
        ),
    )
    questions = [
        dict(id='Q1_rows', question='assignment rows == 1024?',
             answer=len(rows) == 1024, evidence=dict(rows=len(rows))),
        dict(id='Q2_planes', question='z1 512 / z2 512?',
             answer=(audit['z1'] == 512 and audit['z2'] == 512),
             evidence=dict(z1=audit['z1'], z2=audit['z2'])),
        dict(id='Q3_manual_fixed',
             question='368 manual routes fixed on the model planes?',
             answer=(audit['manual_counts'] == dict(EXPECTED_MANUAL_COUNTS)),
             evidence=dict(manual_counts=audit['manual_counts'],
                           planes=audit['manual_planes'])),
        dict(id='Q4_direct',
             question='exactly 100 interface-direct routes?',
             answer=audit['direct_routes']['total'] == EXPECTED_DIRECT_ROUTES,
             evidence=dict(direct=audit['direct_routes'])),
        dict(id='Q5_transitions',
             question='1848 endpoint transitions (924 routes)?',
             answer=(audit['transition_routes']['endpoint_transitions']
                     == EXPECTED_ENDPOINT_TRANSITIONS),
             evidence=dict(transition=audit['transition_routes'])),
        dict(id='Q6_heights',
             question='21 distinct heights with min pitch >= 0.05 mm?',
             answer=(audit['height_count'] == 21
                     and audit['min_pitch_mm']
                     >= M.MIN_LAYER_PITCH_MM - 1e-9),
             evidence=dict(height_count=audit['height_count'],
                           min_pitch_mm=audit['min_pitch_mm'])),
        dict(id='Q7_orbits',
             question='whole C4 orbits on one plane for non-manual routes?',
             answer=any(check['id'] == 'nonmanual_orbit_single_plane'
                        and check['passed'] for check in checks),
             evidence=dict(non_manual_orbits=164)),
        dict(id='Q8_port_pairs',
             question='port pairs identical to common.routes()?',
             answer=any(check['id'] == 'port_pairs_identical_to_true_routes'
                        and check['passed'] for check in checks),
             evidence=dict(routes=len(rows))),
        dict(id='Q9_baseline_readonly',
             question='baseline RUN_DIR untouched (read-only)?',
             answer=bool(audit.get('baseline_untouched', False)),
             evidence=dict(baseline_sha256=audit['baseline']['sha256'])),
        dict(id='Q10_plane_counts',
             question='per-plane counts exactly as SPEC section 2?',
             answer=any(check['id'] == 'plane_counts_exact'
                        and check['passed'] for check in checks),
             evidence=dict(plane_counts=plane_counts)),
    ]
    experiment_audit = dict(
        schema='reheight21_experiment_A_audit_v1',
        experiment='A',
        run_dir=str(M.RUN_DIR),
        baseline_run_dir=str(M.BASELINE_RUN_DIR),
        layer_model=audit['layer_model'],
        assignment_rules=dict(
            manual='Z1-U1..U4 -> planes 2/3/4/5, Z2-U1..U4 -> planes '
                   '10/11/12/13; membership from the verified baseline',
            z1_other='64 C4 opposite orbits sorted by group_id -> '
                     'model.Z1_OTHER_PLAN 52/52/52/52/48',
            z2_other='100 C4 adjacent orbits: baseline old target layer -> '
                     'new plane via model.Z2_OTHER_OLD_TO_NEW',
            needs_transition='target_z != own interface z',
            direct_rule='direct routes have n_transitions=0 and a flat body '
                        'on their interface plane (1001 z=0.0 / 1002 z=0.5)',
        ),
        questions=questions,
        plane_table=layer_rows,
        counts=dict(
            plane_count=audit['plane_count'],
            plane_counts=plane_counts,
            manual_counts=audit['manual_counts'],
            role_counts=audit['role_counts'],
            direction_counts=audit['direction_counts'],
            direct_routes=audit['direct_routes'],
            transition_routes=audit['transition_routes'],
        ),
        baseline_diff=dict(
            baseline_sha256=audit['baseline']['sha256'],
            baseline_rows=audit['baseline']['rows'],
            baseline_layer_counts=audit['baseline']['layer_counts'],
            z2_old_to_new={str(old): int(new) for old, new
                           in M.Z2_OTHER_OLD_TO_NEW.items()},
            z1_other_plan=[[int(plane), int(capacity)] for plane, capacity
                           in M.Z1_OTHER_PLAN],
            manual_plane_ids_unchanged=all(
                item['plane_id_unchanged']
                for item in build_diff(rows)['manual']['groups']),
        ),
        invariants=checks,
        invariant_failures=failures,
        all_invariants_passed=not failures,
    )
    stage_summary = dict(
        stage='experiment_A',
        input_line_count=dict(
            true_routes=len(rows),
            baseline_assignment_rows=audit['baseline']['rows']),
        attempted=dict(assignment_rows=len(rows)),
        success=dict(
            assignment_rows=len(rows) if not failures else 0,
            invariants_passed=len(checks) - len(failures)),
        failures=dict(invariant_failures=len(failures)),
        failure_reasons={},
        validation_status='passed' if not failures else 'failed',
    )
    validation = dict(
        schema='reheight21_experiment_A_validation_v1',
        experiment='A',
        status='passed' if not failures else 'failed',
        checks_total=len(checks),
        checks_passed=len(checks) - len(failures),
        checks_failed=len(failures),
        failed_checks=failures,
        checks=checks,
        stage_summary=stage_summary,
        assignment_verdict=dict(
            rows=len(rows),
            plane_count=audit['plane_count'],
            height_count=audit['height_count'],
            min_pitch_mm=audit['min_pitch_mm'],
            plane_counts=plane_counts,
            manual_counts=audit['manual_counts'],
            direct_routes=audit['direct_routes'],
            transition_routes=audit['transition_routes'],
            all_invariants_passed=not failures,
        ),
        assignment_ready_for_stage_B=bool(not failures),
        baseline_untouched=bool(audit.get('baseline_untouched', False)),
        notes=['nothing is counted as passed unless the check is evaluated',
               'the baseline RUN_DIR is read-only and never written'],
    )
    C.write_json(M.NEW_EXPERIMENT_A / 'summary.json', summary)
    C.write_json(M.NEW_EXPERIMENT_A / 'audit.json', experiment_audit)
    C.write_json(M.NEW_EXPERIMENT_A / 'validation_status.json', validation)
    C.write_csv(M.NEW_EXPERIMENT_A / 'layer_audit.csv', layer_rows,
                fieldnames=list(layer_rows[0].keys()))
    return dict(summary=summary, audit=experiment_audit,
                validation=validation, layer_rows=layer_rows)


# ================================================================ write all
def write_all(rows=None):
    """Write every Experiment-A deliverable deterministically."""
    if rows is None:
        rows = build_assignment()
    state = _state()
    M.RUN_DIR.mkdir(parents=True, exist_ok=True)
    baseline_sha_before = _read_baseline_file_sha256()
    plane_counts = collections.Counter(int(row['target_layer'])
                                       for row in rows)
    # layer_planes.json needs the assigned counts and is used by run21 stage A
    C.write_json(M.LAYER_PLANES_JSON,
                 M.layer_planes_payload(assigned=plane_counts))
    C.write_csv(M.NEW_ASSIGNMENT, rows, fieldnames=ASSIGNMENT_COLUMNS)
    C.write_json(M.NEW_STACK_JSON, M.stack_payload())
    C.write_json(M.NEW_RULES_JSON, M.process_rules_payload())
    diff = build_diff(rows)
    C.write_json(M.NEW_ASSIGNMENT_DIFF_JSON, diff)
    M.NEW_ASSIGNMENT_DIFF_MD.write_text(diff_markdown(diff),
                                        encoding='utf-8')
    audit = build_audit(rows, state)
    baseline_sha_after = _read_baseline_file_sha256()
    audit['baseline_untouched'] = bool(
        baseline_sha_before == baseline_sha_after
        == state['baseline']['sha256'])
    experiment = _experiment_a(rows, audit)
    C.write_json(M.NEW_ASSIGNMENT_AUDIT, audit)
    # experiment_A/audit.json embeds the final baseline_untouched flag: rewrite
    # after it is known (the other experiment_A files do not depend on it)
    experiment['audit']['baseline_untouched'] = audit['baseline_untouched']
    experiment['audit']['questions'][8]['answer'] = audit['baseline_untouched']
    experiment['validation']['baseline_untouched'] = audit['baseline_untouched']
    C.write_json(M.NEW_EXPERIMENT_A / 'audit.json', experiment['audit'])
    C.write_json(M.NEW_EXPERIMENT_A / 'validation_status.json',
                 experiment['validation'])
    return dict(rows=rows, audit=audit, diff=diff, experiment=experiment)


# ================================================================ reporting
def summary_lines(rows, audit, diff):
    summary = diff['summary']
    plane_counts = audit['plane_counts']
    lines = [
        '=== 21-height experiment A: layer model + 1024 assignment + diff ===',
        f"Run dir      : {M.RUN_DIR}",
        f"Baseline     : {M.BASELINE_RUN_DIR} (read-only, sha256 "
        f"{audit['baseline']['sha256'][:16]}...)",
        f"Rows         : {len(rows)} unique ids, z1 {audit['z1']} / "
        f"z2 {audit['z2']}, 21 planes / "
        f"{audit['height_count']} distinct heights",
        f"Min pitch    : {audit['min_pitch_mm']:.3f} mm (required >= 0.05)",
        f"Manual       : {sum(audit['manual_counts'].values())} fixed "
        f"(Z1 64/64/64/64 on 2/3/4/5; Z2 16/16/40/40 on 10/11/12/13)",
        'Z1 other     : ' + ' '.join(
            f'{plane}:{count}' for plane, count
            in audit['z1_other']['routes_per_plane'].items()) + ' routes',
        'Z2 other     : ' + ' '.join(
            f'{plane}:{count}' for plane, count
            in audit['z2_other']['routes_per_new_plane'].items()) + ' routes',
        f"Direct       : {audit['direct_routes']['total']} "
        f"(Z1_INTERFACE 1001: {audit['direct_routes']['z1']}, "
        f"Z2_INTERFACE 1002: {audit['direct_routes']['z2']})",
        f"Transitions  : {audit['transition_routes']['routes']} routes -> "
        f"{audit['transition_routes']['endpoint_transitions']} endpoints",
        f"Plane counts : " + ' '.join(
            f'{plane}:{count}' for plane, count
            in sorted(plane_counts.items())),
        f"Diff         : {summary['changed_plane']} routes changed plane, "
        f"{summary['changed_z']} changed z, "
        f"{summary['direction_flip_routes']} direction flips, manual "
        f"unchanged={summary['manual_unchanged']}",
        'Invariants    : %d/%d passed%s' % (
            len(audit['invariants']) - len(audit['invariant_failures']),
            len(audit['invariants']),
            '' if audit['all_invariants_passed'] else
            ' -- FAILURES: ' + ', '.join(
                item['id'] for item in audit['invariant_failures'])),
        f"Deliverables : layer_planes.json, assignment_1024.csv, "
        f"assignment_audit.json, assignment_diff_vs_baseline.{{json,md}}, "
        f"experiment_A/{{summary.json,layer_audit.csv,audit.json,"
        f"validation_status.json}}, physical_layer_stack.json, "
        f"process_rules.json",
    ]
    return lines


def _append_log(lines):
    try:
        M.RUN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        with open(M.RUN_DIR / 'run.log', 'a', encoding='utf-8') as handle:
            handle.write(f'[{stamp}] assign21: ' + ' | '.join(lines[:5])
                         + '\n')
    except Exception:  # pragma: no cover - logging must never break output
        pass


def main(argv=None):
    """Importable no-arg entry point (run21.stage_a calls this)."""
    rows = build_assignment(force=True)
    result = write_all(rows)
    audit = result['audit']
    diff = result['diff']
    lines = summary_lines(rows, audit, diff)
    for line in lines:
        print(line)
    _append_log(lines)
    return result


if __name__ == '__main__':
    main()
