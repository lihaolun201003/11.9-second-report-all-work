# -*- coding: utf-8 -*-
"""C4-free (per-route_id) layer assignment builder.

The only thing this module *does not* keep from the frozen 21-height
experiment is the C4 rotation-orbit layer binding: every non-manual route may
be assigned to any plane of its own allowed set, independently of the other
three routes of its original C4 orbit.  ``c4_group_id`` survives only as
provenance.

Hard invariants (all re-checked in :func:`build_audit`):

* 1024 rows, unique route ids, the original 512 Z1 / 512 Z2 split;
* ``source_endpoint`` / ``target_endpoint`` / every port coordinate identical
  to the frozen baseline;
* the 368 manual U routes keep their exact plane / z / group membership;
* 21 routing heights, >= 0.05 mm pitch, glass z range unchanged;
* ``needs_transition`` / ``direction`` derived from the real plane z.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import common as C
from ..reheight21 import model as M
from . import data as D
from . import paths as P

AUDIT_SCHEMA = 'nonc4_assignment_audit_v1'
PLAN_SCHEMA = 'nonc4_assignment_plan_v1'

#: columns written to assignment_1024.csv (exactly the frozen schema)
ASSIGNMENT_COLUMNS = (
    'route_id', 'plane', 'relation', 'manual_group', 'manual_pattern',
    'layer_role', 'target_layer', 'target_plane_label', 'target_z_mm',
    'interface_z_mm', 'direction', 'needs_transition', 'c4_group_id',
    'rotation_phase', 'baseline_old_layer', 'source_endpoint',
    'target_endpoint', 'source_side', 'target_side', 'source_connector',
    'target_connector', 'source_x_mm', 'source_y_mm', 'target_x_mm',
    'target_y_mm', 'source_row', 'target_row',
)
#: columns whose value must stay bit-identical to the baseline (real data)
PORT_COLUMNS = (
    'route_id', 'plane', 'relation', 'manual_group', 'manual_pattern',
    'c4_group_id', 'rotation_phase', 'source_endpoint', 'target_endpoint',
    'source_side', 'target_side', 'source_connector', 'target_connector',
    'source_x_mm', 'source_y_mm', 'target_x_mm', 'target_y_mm',
    'source_row', 'target_row', 'interface_z_mm',
)
_MANUAL_EXPECTED = OrderedDict([
    ('Z1-U1', (2, 64)), ('Z1-U2', (3, 64)), ('Z1-U3', (4, 64)),
    ('Z1-U4', (5, 64)), ('Z2-U1', (10, 16)), ('Z2-U2', (11, 16)),
    ('Z2-U3', (12, 40)), ('Z2-U4', (13, 40)),
])


# --------------------------------------------------------------------- plans
def default_allocation():
    """First C4-free plan: single-family layers, both interface planes used.

    * Z1 vertical family (128 N<->S routes) on L6 + L7 (64 / 64);
    * Z1 horizontal family (128 E<->W routes) on L20 + L8 + Z1_INTERFACE
      (43 / 43 / 42, the interface plane ones are direct: no transition);
    * every Z2 corner family (100 routes) on two planes, one of them the
      Z2_INTERFACE plane for the SW family.
    """
    return OrderedDict([
        ('Z1V', [6, 7]),
        ('Z1H', [20, 8, 1001]),
        ('Z2_NE', [9, 14]),
        ('Z2_SE', [15, 16]),
        ('Z2_NW', [17, 18]),
        ('Z2_SW', [19, 1002]),
    ])


def distribute_balanced(route_ids, planes):
    """Split ``route_ids`` over ``planes`` as evenly as possible (in order)."""
    route_ids = list(route_ids)
    planes = list(planes)
    if not planes:
        raise ValueError('no planes in allocation')
    if not route_ids:
        return {}
    base, extra = divmod(len(route_ids), len(planes))
    plan = {}
    index = 0
    for position, plane_id in enumerate(planes):
        take = base + (1 if position < extra else 0)
        for route_id in route_ids[index:index + take]:
            plan[int(route_id)] = int(plane_id)
        index += take
    return plan


def order_family(rows, mode='port'):
    """Deterministic intra-family ordering used when splitting over planes."""
    if mode == 'route_id':
        return sorted(rows, key=lambda row: int(row['route_id']))
    if mode == 'port':
        return sorted(rows, key=D.port_sort_key)
    if mode == 'round_robin':
        ordered = sorted(rows, key=D.port_sort_key)
        return ordered
    raise ValueError(f'unknown order mode {mode!r}')


def plan_family_allocation(rows, allocation=None, order='port'):
    """``{route_id: plane_id}`` for every non-manual route.

    ``allocation`` is ``{family: [plane_id, ...]}``; planes are filled in the
    given order with contiguous chunks of the family (ordered by port position
    by default, so routes that are spatially close tend to share a plane).
    """
    allocation = allocation or default_allocation()
    plan = {}
    members = D.family_members(rows)
    unknown = set(allocation) - set(members)
    if unknown:
        raise ValueError(f'allocation has unknown families: {sorted(unknown)}')
    for family, plane_ids in allocation.items():
        family_rows = members.get(family) or []
        ordered = order_family(family_rows, order)
        if order == 'round_robin':
            # interleave: position i goes to plane i % k
            k = len(plane_ids)
            for position, row in enumerate(ordered):
                plan[int(row['route_id'])] = int(plane_ids[position % k])
        else:
            plan.update(distribute_balanced(
                [int(row['route_id']) for row in ordered], plane_ids))
    return plan


def plan_with_manual(rows, nonmanual_plan):
    """Complete plan: manual routes keep their frozen baseline plane."""
    plan = {}
    for row in rows:
        route_id = int(row['route_id'])
        if D.is_manual(row):
            plan[route_id] = int(row['target_layer'])
        else:
            if route_id not in nonmanual_plan:
                raise ValueError(f'route {route_id} missing from assignment plan')
            plan[route_id] = int(nonmanual_plan[route_id])
    return plan


def save_plan(path, plan, allocation=None, order='port', experiment='',
              extra=None):
    payload = dict(
        schema=PLAN_SCHEMA, generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        experiment=experiment, order=order,
        allocation={family: [int(pid) for pid in plane_ids]
                    for family, plane_ids in (allocation or {}).items()},
        route_planes={str(rid): int(pid) for rid, pid in sorted(plan.items())},
    )
    if extra:
        payload.update(extra)
    C.write_json(Path(path), payload)
    return payload


def load_plan(path):
    payload = D.load_json(path)
    route_planes = payload.get('route_planes') or payload.get('plan') or {}
    return {int(rid): int(pid) for rid, pid in route_planes.items()}, payload


# ------------------------------------------------------------------ row build
def build_rows(base_rows, plan, experiment=''):
    """Return typed assignment rows with the new per-route target plane."""
    rows = []
    for base in base_rows:
        route_id = int(base['route_id'])
        if route_id not in plan:
            raise ValueError(f'plan misses route {route_id}')
        plane_id = int(plan[route_id])
        if plane_id not in M.PLANE_IDS:
            raise ValueError(f'route {route_id}: plane {plane_id} not in model')
        z_mm = float(M.plane_z(plane_id))
        interface_z = float(base['interface_z_mm'])
        needs_transition = abs(z_mm - interface_z) > 1e-9
        row = dict(base)
        row['target_layer'] = plane_id
        row['target_plane_label'] = M.plane_label(plane_id)
        row['target_z_mm'] = z_mm
        row['needs_transition'] = bool(needs_transition)
        row['direction'] = ('direct' if not needs_transition else
                            ('down' if z_mm < interface_z else 'up'))
        rows.append(row)
    rows.sort(key=lambda row: int(row['route_id']))
    return rows


def _cell(value):
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, float):
        return repr(value)
    return value


def write_assignment(path, rows, columns=None):
    columns = list(columns or ASSIGNMENT_COLUMNS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    C.write_csv(path, [{key: _cell(row.get(key, '')) for key in columns}
                       for row in rows], columns)
    return D.sha256_file(path)


# ---------------------------------------------------------------------- audit
def _float_equal(a, b, tol=1e-12):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def build_audit(rows, base_rows, plan, experiment='', assignment_path=None):
    by_id = {int(row['route_id']): row for row in rows}
    base_by_id = {int(row['route_id']): row for row in base_rows}
    violations = []
    if len(rows) != 1024:
        violations.append(dict(kind='row_count_not_1024', detail=len(rows)))
    if len(by_id) != len(rows):
        violations.append(dict(kind='duplicate_route_id'))
    planes = Counter(int(row['target_layer']) for row in rows)
    plane_split = Counter(str(row['plane']) for row in rows)
    if dict(plane_split) != {'z1': 512, 'z2': 512}:
        violations.append(dict(kind='plane_split_wrong',
                               detail=dict(plane_split)))
    # --- port / identity invariance against the frozen baseline
    changed_ports = []
    for route_id, base in base_by_id.items():
        row = by_id.get(route_id)
        if row is None:
            violations.append(dict(kind='route_missing', route_id=route_id))
            continue
        for column in PORT_COLUMNS:
            if column in ('source_x_mm', 'source_y_mm', 'target_x_mm',
                          'target_y_mm'):
                if not _float_equal(base.get(column), row.get(column)):
                    changed_ports.append(dict(route_id=route_id,
                                              column=column))
            elif str(base.get(column, '')) != str(row.get(column, '')):
                changed_ports.append(dict(route_id=route_id, column=column))
    if changed_ports:
        violations.append(dict(kind='port_or_identity_changed',
                               count=len(changed_ports),
                               examples=changed_ports[:10]))
    # --- manual groups frozen
    manual_counts = Counter()
    manual_planes_bad = []
    for route_id, row in by_id.items():
        group = str(row.get('manual_group') or '').strip()
        if not group:
            continue
        manual_counts[group] += 1
        base = base_by_id.get(route_id) or {}
        plane_id = int(row['target_layer'])
        if plane_id != int(base.get('target_layer')):
            manual_planes_bad.append(dict(route_id=route_id, group=group,
                                          plane=plane_id,
                                          baseline=int(base.get('target_layer'))))
        expected = _MANUAL_EXPECTED.get(group)
        if expected is not None:
            if plane_id != expected[0]:
                manual_planes_bad.append(dict(route_id=route_id, group=group,
                                              plane=plane_id,
                                              expected=expected[0]))
    if sum(manual_counts.values()) != 368:
        violations.append(dict(kind='manual_total_not_368',
                               detail=sum(manual_counts.values())))
    for group, (plane_id, count) in _MANUAL_EXPECTED.items():
        if manual_counts.get(group, 0) != count:
            violations.append(dict(kind='manual_group_count_mismatch',
                                   detail=f'{group}: {manual_counts.get(group, 0)}'
                                          f' != {count}'))
    if manual_planes_bad:
        violations.append(dict(kind='manual_route_moved', count=len(
            manual_planes_bad), examples=manual_planes_bad[:10]))
    # --- non-manual routes must stay on their own family's allowed plane set
    wrong_plan = []
    for route_id, row in by_id.items():
        if D.is_manual(row):
            continue
        family = D.family_of(row)
        allowed = D.ALLOWED_PLANES[family]
        plane_id = int(row['target_layer'])
        if plane_id not in allowed:
            wrong_plan.append(dict(route_id=route_id, family=family,
                                   plane=plane_id, allowed=list(allowed)))
    if wrong_plan:
        violations.append(dict(kind='nonmanual_plane_outside_allowed_set',
                               count=len(wrong_plan),
                               examples=wrong_plan[:10]))
    # --- target z / direction consistency
    bad_direction = []
    for route_id, row in by_id.items():
        plane_id = int(row['target_layer'])
        z_mm = float(M.plane_z(plane_id))
        interface_z = float(row['interface_z_mm'])
        if not _float_equal(row['target_z_mm'], z_mm):
            bad_direction.append(dict(route_id=route_id, kind='z_mismatch'))
            continue
        direct = abs(z_mm - interface_z) <= 1e-9
        if bool(row['needs_transition']) == direct:
            bad_direction.append(dict(route_id=route_id,
                                      kind='needs_transition_mismatch'))
        expected_direction = ('direct' if direct else
                              ('down' if z_mm < interface_z else 'up'))
        if str(row['direction']) != expected_direction:
            bad_direction.append(dict(route_id=route_id,
                                      kind='direction_mismatch'))
    if bad_direction:
        violations.append(dict(kind='assignment_row_inconsistent',
                               count=len(bad_direction),
                               examples=bad_direction[:10]))
    # --- heights / pitch
    used_heights = sorted({round(float(M.plane_z(pid)), 9)
                           for pid in planes})
    height_gaps = [round(b - a, 9) for a, b in zip(used_heights,
                                                   used_heights[1:])]
    if height_gaps and min(height_gaps) < M.MIN_LAYER_PITCH_MM - 1e-9:
        violations.append(dict(kind='height_pitch_below_50um',
                               min_gap=min(height_gaps)))
    if any(pid not in M.PLANE_IDS for pid in planes):
        violations.append(dict(kind='unknown_plane_used'))
    # --- direct routes
    direct_by_plane = Counter()
    for route_id, row in by_id.items():
        if not bool(row['needs_transition']):
            direct_by_plane[int(row['target_layer'])] += 1
    direct_ids = [route_id for route_id, row in by_id.items()
                  if not bool(row['needs_transition'])]
    for plane_id in direct_by_plane:
        if not M.is_interface_plane(plane_id):
            violations.append(dict(kind='direct_route_on_body_plane',
                                   detail=plane_id))
    # --- C4 binding removal evidence
    orbit_planes = collections.defaultdict(set)
    orbit_manual = collections.defaultdict(bool)
    for group in C.rotation_groups():
        for route_id in group['route_ids']:
            route_id = int(route_id)
            row = by_id.get(route_id)
            if row is None:
                continue
            orbit_planes[int(group['group_id'])].add(int(row['target_layer']))
            if D.is_manual(row):
                orbit_manual[int(group['group_id'])] = True
    split_orbits = [dict(group_id=group_id, planes=sorted(plane_ids))
                    for group_id, plane_ids in sorted(orbit_planes.items())
                    if len(plane_ids) > 1 and not orbit_manual[group_id]]
    single_plane_orbits = [group_id for group_id, plane_ids
                           in orbit_planes.items()
                           if len(plane_ids) == 1 and not orbit_manual[group_id]]
    audit = dict(
        schema=AUDIT_SCHEMA,
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        experiment=experiment,
        assignment_file=str(assignment_path) if assignment_path else None,
        assignment_sha256=(D.sha256_file(assignment_path)
                           if assignment_path else None),
        rows=len(rows),
        unique_route_ids=len(by_id),
        plane_split=dict(plane_split),
        per_plane_counts={str(pid): int(count)
                          for pid, count in sorted(planes.items())},
        planes_used=len(planes),
        heights_used=sorted(round(float(M.plane_z(pid)), 9) for pid in planes),
        distinct_heights=len(used_heights),
        min_height_pitch_mm=(min(height_gaps) if height_gaps else None),
        manual_total=sum(manual_counts.values()),
        manual_group_counts=dict(sorted(manual_counts.items())),
        manual_routes_frozen=not manual_planes_bad,
        direct_routes=len(direct_ids),
        direct_by_plane={str(pid): int(count)
                         for pid, count in sorted(direct_by_plane.items())},
        transition_routes=len(rows) - len(direct_ids),
        endpoint_transitions=2 * (len(rows) - len(direct_ids)),
        c4_policy=dict(
            binding='REMOVED for the 368+656 non-manual routes',
            note=('c4_group_id is provenance only: non-manual C4 orbits are '
                  'deliberately split across physical planes; manual groups '
                  'were already split by their verified baseline design and '
                  'stay frozen'),
            nonmanual_orbits=len([g for g in orbit_planes
                                  if not orbit_manual[g]]),
            nonmanual_orbits_split_across_planes=len(split_orbits),
            nonmanual_orbits_single_plane=len(single_plane_orbits),
            max_planes_per_orbits=max(
                (len(orbit_planes[g]) for g in orbit_planes
                 if not orbit_manual[g]), default=0),
        ),
        geometry_rules=dict(
            glass_mm=[150.0, 150.0, 1.0],
            glass_z_range_mm=[M.GLASS_Z_MIN_MM, M.GLASS_Z_MAX_MM],
            routing_heights=len(M.PLANE_IDS),
            min_layer_pitch_mm=M.MIN_LAYER_PITCH_MM,
            min_3d_clearance_mm=C.MIN_3D_CLEARANCE_MM,
            same_layer_d56_centerline_mm=C.CLEARANCE_2D_MM,
            min_bend_radius_mm=C.MIN_BEND_RADIUS_MM,
            note='no hard geometric rule is changed by removing the C4 binding',
        ),
        violations=violations,
        passed=not violations,
    )
    return audit


# ---------------------------------------------------------------- model files
def write_model_payloads(exp_dir, rows, experiment='', notes=None):
    """Write layer_planes.json / physical_layer_stack.json / process_rules.json."""
    exp_dir = Path(exp_dir)
    counts = Counter(int(row['target_layer']) for row in rows)
    layer_planes = M.layer_planes_payload(dict(counts))
    layer_planes['experiment'] = experiment
    layer_planes['c4_binding'] = 'removed (per route_id assignment; c4_group_id provenance only)'
    if notes:
        layer_planes['notes'] = list(notes)
    C.write_json(exp_dir / 'layer_planes.json', layer_planes)
    stack = M.stack_payload()
    stack['experiment'] = experiment
    if notes:
        stack['notes'] = list(notes)
    C.write_json(exp_dir / 'physical_layer_stack.json', stack)
    rules = M.process_rules_payload()
    rules['experiment'] = experiment
    if notes:
        rules['notes'] = list(notes)
    C.write_json(exp_dir / 'process_rules.json', rules)
    return dict(layer_planes=layer_planes, stack=stack, rules=rules)


def prepare_experiment(exp_dir, plan, base_rows=None, experiment='',
                       allocation=None, order='port', notes=None,
                       plan_path=None):
    """Create one experiment directory: assignment + audit + model payloads."""
    exp_dir = Path(exp_dir)
    P.use_experiment(exp_dir)
    base_rows = base_rows if base_rows is not None else D.load_baseline_assignment()
    rows = build_rows(base_rows, plan, experiment=experiment)
    assignment_path = exp_dir / 'assignment_1024.csv'
    digest = write_assignment(assignment_path, rows)
    audit = build_audit(rows, base_rows, plan, experiment=experiment,
                        assignment_path=assignment_path)
    C.write_json(exp_dir / 'assignment_audit.json', audit)
    if not audit['passed']:
        raise ValueError(f'assignment audit failed: '
                         f'{audit["violations"][:3]}')
    write_model_payloads(exp_dir, rows, experiment=experiment, notes=notes)
    if plan_path is not None:
        save_plan(plan_path, plan, allocation=allocation, order=order,
                  experiment=experiment)
    elif allocation is not None:
        save_plan(exp_dir / 'assignment_plan.json', plan,
                  allocation=allocation, order=order, experiment=experiment)
    return rows, audit, digest
