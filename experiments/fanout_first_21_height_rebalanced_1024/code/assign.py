# -*- coding: utf-8 -*-
"""P1 1024-route target-layer assignment (Fanout-First project).

Owner: data-verifier.  Contract: ``DESIGN.md`` sections 1, 3.2 and 4.

The assignment has three parts
-----------------------------
1. the 368 manual-U routes are fixed on their user-mandated layers:
   Z1-U1..Z1-U4 (256 routes) -> L2..L5 and Z2-U1..Z2-U4 (112 routes) ->
   L10..L13 (taken from the verified CSVs produced by :mod:`verify`);
2. the 256 Z1 ``opposite`` routes (64 C4 rotation orbits) -> L6 / L7,
   whole orbits per layer, 32 orbits each;
3. the 400 Z2 ``adjacent`` routes (100 C4 rotation orbits) -> L8, L9,
   L14..L19, whole orbits per layer, balanced 12/13 orbits (312/4 = 78 and
   612/4 = 153 -> 13 orbits on the four layers closest to the Z2 interface:
   L16 (z=0.45), L17 (z=0.55), L15 (z=0.40), L18 (z=0.60); 12 on L14 (0.35),
   L19 (0.65), L9 (0.10), L8 (0.05)).

Every non-manual C4 orbit keeps all four of its routes on one layer, because a
rotation orbit is one geometric bundle class; splitting it across layers would
destroy the C4 symmetry of the layer stack.  The ordering is deterministic:
orbits are sorted by ``rotation_groups()[i]['group_id']`` and consumed
sequentially from the documented layer plan; rows are sorted by route id.

Deliverables (RUN_DIR): ``assignment_1024.csv``, ``assignment_audit.json``,
``physical_layer_stack.json``, ``process_rules.json`` and ``experiment_A/``
(``input_counts.json``, ``audit.json``, ``manual_group_audit.csv``,
``assignment_layer_audit.csv``, ``validation_status.json``).

Entry point::

    .venv\\Scripts\\python.exe -m four_side_1024.fanout1024.assign
"""
from __future__ import annotations

import collections
import csv
import json
import math
import time
from pathlib import Path

from . import common as C
from . import verify as V

# ---------------------------------------------------------------- file contract
RUN_DIR = C.RUN_DIR
ASSIGNMENT_CSV = RUN_DIR / 'assignment_1024.csv'
ASSIGNMENT_AUDIT_JSON = RUN_DIR / 'assignment_audit.json'
STACK_JSON = RUN_DIR / 'physical_layer_stack.json'
RULES_JSON = RUN_DIR / 'process_rules.json'
EXPERIMENT_A = RUN_DIR / 'experiment_A'

#: exactly the columns required by DESIGN.md 3.2 (source_row/target_row are
#: appended because ``run_all.read_assignment`` consumes them)
ASSIGNMENT_COLUMNS = [
    'route_id', 'plane', 'relation', 'manual_group', 'manual_pattern',
    'target_layer', 'target_z_mm', 'interface_z_mm', 'direction', 'layer_role',
    'c4_group_id', 'rotation_phase', 'source_endpoint', 'target_endpoint',
    'source_side', 'target_side', 'source_connector', 'target_connector',
    'source_x_mm', 'source_y_mm', 'target_x_mm', 'target_y_mm',
    'source_row', 'target_row',
]

#: layer plans (layer id, number of whole C4 orbits on that layer)
Z1_OPPOSITE_PLAN = ((6, 32), (7, 32))
#: four closest-to-interface layers first (13 orbits each), then the rest
Z2_ADJACENT_PLAN = ((16, 13), (17, 13), (15, 13), (18, 13),
                    (14, 12), (19, 12), (9, 12), (8, 12))
Z2_ADJACENT_THIRTEEN_LAYERS = tuple(layer for layer, capacity in
                                   Z2_ADJACENT_PLAN if capacity == 13)

MANUAL_LAYERS = tuple(sorted({int(spec['layer'])
                              for spec in C.MANUAL_GROUPS.values()}))
NON_MANUAL_LAYERS = tuple(sorted(set(C.ROUTING_LAYER_IDS) - set(MANUAL_LAYERS)))

VERIFY_DELIVERABLES = (
    V.EXCEL_AUDIT_JSON, V.Z1_CSV, V.Z2_CSV, V.MATCH_AUDIT_CSV,
    V.UNMATCHED_CSV, V.CONFLICTS_CSV, V.SUMMARY_JSON, V.Z1_AUDIT_CSV,
)

_ROWS = None
_AUDIT = None


# ================================================================ allocation
def _manual_lookup(state):
    z1 = {int(row['route_id']): row for row in state['z1_csv_rows']}
    z2 = {int(row['route_id']): row for row in state['z2_csv_rows']}
    overlap = sorted(set(z1) & set(z2))
    return z1, z2, overlap


def _allocate_orbits(groups, plan):
    """Map every route id of ``groups`` to one layer, whole orbits only."""
    ordered = sorted(groups, key=lambda group: int(group['group_id']))
    expected = sum(capacity for _layer, capacity in plan)
    if expected != len(ordered):
        raise ValueError(f'layer plan covers {expected} orbits but '
                         f'{len(ordered)} groups exist')
    allocation = {}
    orbit_layer = {}
    layer_groups = collections.OrderedDict((int(layer), [])
                                           for layer, _capacity in plan)
    index = 0
    for layer, capacity in plan:
        for _ in range(int(capacity)):
            group = ordered[index]
            index += 1
            gid = int(group['group_id'])
            layer_groups[int(layer)].append(gid)
            orbit_layer[gid] = int(layer)
            for phase, route_id in enumerate(group['route_ids']):
                allocation[int(route_id)] = dict(
                    layer=int(layer), orbit_group_id=gid,
                    rotation_phase=int(phase))
    if index != len(ordered):
        raise ValueError('orbit allocation did not consume all groups')
    return allocation, orbit_layer, layer_groups


def _route_endpoint_coordinates(route):
    endpoints = C.endpoints()
    source = endpoints[str(route['source_endpoint'])]
    target = endpoints[str(route['target_endpoint'])]
    return (float(source['routing_xy'][0]), float(source['routing_xy'][1]),
            float(target['routing_xy'][0]), float(target['routing_xy'][1]))


def _direction(target_z_mm, interface_z_mm):
    return 'down' if float(target_z_mm) < float(interface_z_mm) else 'up'


# ================================================================ build rows
def build_assignment(force=False):
    """Return the 1024-row assignment (deterministic; cached)."""
    global _ROWS
    if _ROWS is not None and not force:
        return _ROWS
    state = V.compute_all()
    z1_manual, z2_manual, overlap = _manual_lookup(state)
    if overlap:
        raise ValueError(f'manual route ids appear on both planes: {overlap}')
    groups = C.rotation_groups()
    z1_opposite = [group for group in groups
                   if group['plane'] == 'z1' and group['kind'] == 'opposite']
    z2_adjacent = [group for group in groups
                   if group['plane'] == 'z2' and group['kind'] == 'adjacent']
    z1_alloc, _z1_orbit_layer, z1_layer_groups = _allocate_orbits(
        z1_opposite, Z1_OPPOSITE_PLAN)
    z2_alloc, _z2_orbit_layer, z2_layer_groups = _allocate_orbits(
        z2_adjacent, Z2_ADJACENT_PLAN)
    group_of = C.route_group_map()
    rows = []
    for route in sorted(C.routes(), key=lambda item: int(item['route_id'])):
        rid = int(route['route_id'])
        plane = str(route['plane'])
        interface_z = float(C.INTERFACE_Z[plane])
        source_x, source_y, target_x, target_y = _route_endpoint_coordinates(
            route)
        record = collections.OrderedDict((column, '') for column in
                                         ASSIGNMENT_COLUMNS)
        if rid in z1_manual:
            manual = z1_manual[rid]
            layer = int(manual['target_layer'])
            record.update(dict(
                manual_group=str(manual['manual_group']),
                manual_pattern=str(manual['manual_pattern']),
                layer_role='z1_manual_u',
            ))
        elif rid in z2_manual:
            manual = z2_manual[rid]
            layer = int(manual['target_layer'])
            record.update(dict(
                manual_group=str(manual['manual_group']),
                manual_pattern=str(manual['manual_pattern']),
                layer_role='z2_manual_u',
            ))
        elif plane == 'z1':
            allocation = z1_alloc[rid]
            layer = int(allocation['layer'])
            record.update(dict(layer_role='z1_other'))
        else:
            allocation = z2_alloc[rid]
            layer = int(allocation['layer'])
            record.update(dict(layer_role='z2_other'))
        group = group_of[rid]
        target_z = float(C.PHYSICAL_LAYERS[layer])
        record.update(dict(
            route_id=rid,
            plane=plane,
            relation=str(route['relation']),
            target_layer=int(layer),
            target_z_mm=target_z,
            interface_z_mm=interface_z,
            direction=_direction(target_z, interface_z),
            c4_group_id=int(group['group_id']),
            rotation_phase=int(group['route_ids'].index(rid)),
            source_endpoint=str(route['source_endpoint']),
            target_endpoint=str(route['target_endpoint']),
            source_side=str(route['source_side']),
            target_side=str(route['target_side']),
            source_connector=str(route['source_connector']),
            target_connector=str(route['target_connector']),
            source_x_mm=source_x,
            source_y_mm=source_y,
            target_x_mm=target_x,
            target_y_mm=target_y,
            source_row=int(route['source_row']),
            target_row=int(route['target_row']),
        ))
        rows.append(record)
    _check_hard_invariants(rows, state, z1_manual, z2_manual)
    _ROWS = rows
    return rows


def _rows_by_layer(rows):
    by_layer = collections.OrderedDict()
    for row in rows:
        by_layer.setdefault(int(row['target_layer']), []).append(row)
    return by_layer


def _orbit_count(rows):
    return len({int(row['c4_group_id']) for row in rows})


def _check_hard_invariants(rows, state, z1_manual, z2_manual):
    """Fail fast: these are the DESIGN.md 3.2 hard invariants."""
    routes = C.routes()
    if len(rows) != 1024:
        raise ValueError(f'expected 1024 assignment rows, got {len(rows)}')
    ids = [int(row['route_id']) for row in rows]
    if len(set(ids)) != 1024:
        raise ValueError('assignment route ids are not unique')
    planes = collections.Counter(row['plane'] for row in rows)
    if planes != {'z1': 512, 'z2': 512}:
        raise ValueError(f'plane split wrong: {dict(planes)}')
    true_by_id = {int(route['route_id']): route for route in routes}
    for row in rows:
        route = true_by_id[int(row['route_id'])]
        if (row['source_endpoint'], row['target_endpoint']) != (
                route['source_endpoint'], route['target_endpoint']):
            raise ValueError(f'route {row["route_id"]}: endpoint pair changed')
        expected_z = float(C.PHYSICAL_LAYERS[int(row['target_layer'])])
        if abs(float(row['target_z_mm']) - expected_z) > 1e-9:
            raise ValueError(f'route {row["route_id"]}: wrong target_z_mm')
        if abs(float(row['interface_z_mm'])
               - float(C.INTERFACE_Z[str(row['plane'])])) > 1e-9:
            raise ValueError(f'route {row["route_id"]}: wrong interface_z_mm')
        expected_direction = _direction(expected_z, row['interface_z_mm'])
        if row['direction'] != expected_direction:
            raise ValueError(f'route {row["route_id"]}: wrong direction')
    for rid, manual in z1_manual.items():
        row = next(item for item in rows if int(item['route_id']) == rid)
        if int(row['target_layer']) != int(manual['target_layer']):
            raise ValueError(f'manual route {rid}: layer overwritten')
    for rid, manual in z2_manual.items():
        row = next(item for item in rows if int(item['route_id']) == rid)
        if int(row['target_layer']) != int(manual['target_layer']):
            raise ValueError(f'manual route {rid}: layer overwritten')
    by_layer = _rows_by_layer(rows)
    manual_counts = collections.Counter(row['manual_group'] for row in rows
                                        if row['manual_group'])
    for group, spec in C.MANUAL_GROUPS.items():
        expected = len([manual for manual in z1_manual.values()
                        if manual['manual_group'] == group]) \
            if group.startswith('Z1') else len(
                [manual for manual in z2_manual.values()
                 if manual['manual_group'] == group])
        if manual_counts[group] != expected:
            raise ValueError(f'manual group {group}: count mismatch')
        layer_rows = by_layer[int(spec['layer'])]
        if any(row['layer_role'] not in ('z1_manual_u', 'z2_manual_u')
               for row in layer_rows):
            raise ValueError(f'manual layer {spec["layer"]} got non-manual rows')
        if len(layer_rows) != expected:
            raise ValueError(f'manual layer {spec["layer"]}: row count mismatch')
    for layer in NON_MANUAL_LAYERS:
        if any(row['layer_role'] in ('z1_manual_u', 'z2_manual_u')
               for row in by_layer.get(layer, [])):
            raise ValueError(f'non-manual layer {layer} got manual rows')
    # whole orbits on one layer for every non-manual orbit
    group_of = C.route_group_map()
    orbit_layers = collections.defaultdict(set)
    for row in rows:
        if row['layer_role'] in ('z1_manual_u', 'z2_manual_u'):
            continue
        orbit_layers[int(row['c4_group_id'])].add(int(row['target_layer']))
    bad_orbits = [gid for gid, layers in orbit_layers.items()
                  if len(layers) != 1]
    if bad_orbits:
        raise ValueError(f'orbits spanning several layers: {bad_orbits[:5]}')
    return True


# ================================================================ audit
def _invariant_state(condition, detail=None):
    return dict(passed=bool(condition), detail=detail)


def _layer_plan_report(plan, groups_by_layer, interface_z):
    report = collections.OrderedDict()
    for layer, capacity in plan:
        gids = groups_by_layer[int(layer)]
        target_z = float(C.PHYSICAL_LAYERS[int(layer)])
        report[str(layer)] = dict(
            planned_orbits=int(capacity), actual_orbits=len(gids),
            routes=4 * len(gids),
            target_z_mm=target_z,
            direction=_direction(target_z, interface_z),
            orbit_group_ids=list(gids),
        )
    return report


def _previous_assignment_crosscheck():
    """Cross-check the previous verified assignment reference (historical JSON).

    ``MANUAL_20L_FIXED_ASSIGNMENT_FULL/assignment_1024.json`` is the previous
    round's assignment of the same 1024 true routes (``kind == 'manual_u'``
    rows carry the Z1 manual groups NS-1/NS-2/EW-1/EW-2 with old layers 1..4).
    The comparison is structural (route-id set, plane split, manual-group
    mapping to the delivered Z1-U1..U4 groups) and therefore stable across
    runs even though this round writes a new-schema CSV.
    """
    reference = V.PRIOR_ASSIGNMENT_JSON
    try:
        if not reference.is_file():
            return dict(present=False, path=str(reference),
                        note='previous verified assignment reference missing')
        payload = C.read_json(reference)
        previous_rows = payload['rows'] if isinstance(payload, dict) \
            else payload
        current_ids = {int(row['route_id']) for row in build_assignment()}
        previous_ids = {int(row['route_id']) for row in previous_rows}
        plane_split = collections.Counter(str(row.get('plane'))
                                          for row in previous_rows)
        prior_manual = {int(row['route_id']): str(row['manual_group'])
                        for row in previous_rows
                        if row.get('kind') == 'manual_u'}
        mapping = {prior: spec['group']
                   for prior, spec in V.Z1_GROUP_MAP.items()}
        current_manual = {
            int(manual['route_id']): str(manual['manual_group'])
            for manual in V.compute_all()['z1_csv_rows']}
        mismatches = []
        for route_id in sorted(set(prior_manual) | set(current_manual)):
            expected = mapping.get(prior_manual.get(route_id))
            actual = current_manual.get(route_id)
            if expected != actual:
                mismatches.append(dict(
                    route_id=route_id, previous=prior_manual.get(route_id),
                    expected_delivered_group=expected, actual=actual))
        return dict(
            present=True,
            readable=True,
            path=str(reference),
            rows=len(previous_rows),
            route_id_set_identical=sorted(previous_ids) == sorted(current_ids),
            plane_split_identical=dict(plane_split) == {'z1': 512,
                                                        'z2': 512},
            previous_plane_split=dict(plane_split),
            previous_manual_u_rows=len(prior_manual),
            delivered_manual_u_rows=len(current_manual),
            manual_group_mismatches=mismatches,
            manual_groups_identical=not mismatches,
            old_manual_layer_to_delivered_layer={
                'NS-1': 2, 'NS-2': 3, 'EW-1': 4, 'EW-2': 5},
            note='previous verified assignment reference compared structurally; '
                 'its manual_u rows are the Z1-U1..U4 truth consumed by '
                 'verify.verify_z1_manual()',
        )
    except Exception as error:  # guarded cross-check input
        return dict(present=True, readable=False, path=str(reference),
                    error=repr(error))


def _verified_csv_crosscheck(state, rows):
    """Read back the verified manual CSVs (guarded) and compare to the rows."""
    detail = {}
    for label, path, target_layer_role in (
            ('z1', V.Z1_CSV, 'z1_manual_u'),
            ('z2', V.Z2_CSV, 'z2_manual_u')):
        try:
            if not path.is_file():
                detail[label] = dict(present=False)
                continue
            csv_rows, digest = C.read_csv_rows(path)
            by_id = {int(float(row['route_id'])): row for row in csv_rows}
            assignment = {int(row['route_id']): row for row in rows
                          if row['layer_role'] == target_layer_role}
            mismatched = []
            for rid in sorted(set(by_id) | set(assignment)):
                csv_row = by_id.get(rid)
                row = assignment.get(rid)
                if csv_row is None or row is None:
                    mismatched.append(dict(route_id=rid,
                                           reason='missing_on_one_side'))
                    continue
                if (str(csv_row['manual_group']) != row['manual_group']
                        or int(float(csv_row['target_layer']))
                        != int(row['target_layer'])):
                    mismatched.append(dict(
                        route_id=rid,
                        csv_group=str(csv_row['manual_group']),
                        assignment_group=row['manual_group'],
                        csv_layer=int(float(csv_row['target_layer'])),
                        assignment_layer=int(row['target_layer'])))
            detail[label] = dict(
                present=True, path=str(path), sha256=digest,
                csv_rows=len(by_id), assignment_rows=len(assignment),
                route_ids_match=sorted(by_id) == sorted(assignment),
                group_and_layer_mismatches=mismatched,
                consumed=not mismatched and sorted(by_id) == sorted(assignment),
            )
        except Exception as error:  # guarded cross-check input
            detail[label] = dict(present=True, readable=False,
                                 error=repr(error))
    return detail


def build_audit(rows=None, state=None):
    """Assignment audit with per-plane / per-layer / per-orbit counts."""
    global _AUDIT
    if _AUDIT is not None and rows is None:
        return _AUDIT
    rows = rows if rows is not None else build_assignment()
    state = state or V.compute_all()
    z1_manual, z2_manual, _overlap = _manual_lookup(state)
    by_layer = _rows_by_layer(rows)
    by_plane = collections.Counter(row['plane'] for row in rows)
    role_counts = collections.Counter(row['layer_role'] for row in rows)
    manual_counts = collections.Counter(row['manual_group'] for row in rows
                                        if row['manual_group'])
    direction_counts = collections.Counter(row['direction'] for row in rows)
    layer_counts = collections.OrderedDict(
        (str(layer), len(by_layer.get(layer, []))) for layer in
        C.ROUTING_LAYER_IDS)
    layer_orbit_counts = collections.OrderedDict()
    for layer in C.ROUTING_LAYER_IDS:
        layer_rows = by_layer.get(layer, [])
        layer_orbit_counts[str(layer)] = _orbit_count(layer_rows)
    groups = C.rotation_groups()
    z1_opposite = sorted([group for group in groups
                          if group['plane'] == 'z1'
                          and group['kind'] == 'opposite'],
                         key=lambda group: int(group['group_id']))
    z2_adjacent = sorted([group for group in groups
                          if group['plane'] == 'z2'
                          and group['kind'] == 'adjacent'],
                         key=lambda group: int(group['group_id']))
    _z1_alloc, _z1_orbit_layer, z1_layer_groups = _allocate_orbits(
        z1_opposite, Z1_OPPOSITE_PLAN)
    _z2_alloc, _z2_orbit_layer, z2_layer_groups = _allocate_orbits(
        z2_adjacent, Z2_ADJACENT_PLAN)

    routes = C.routes()
    true_by_id = {int(route['route_id']): route for route in routes}
    group_of = C.route_group_map()
    layer_of = {int(row['route_id']): int(row['target_layer']) for row in rows}
    non_manual_orbits = 0
    spanning_orbits = []
    orphan_orbits = []
    for group in groups:
        is_manual = any(int(route_id) in z1_manual or int(route_id) in z2_manual
                        for route_id in group['route_ids'])
        if is_manual:
            continue
        non_manual_orbits += 1
        layers = {layer_of[int(route_id)] for route_id in group['route_ids']}
        if len(layers) != 1:
            spanning_orbits.append(dict(c4_group_id=int(group['group_id']),
                                        layers=sorted(layers)))
        else:
            layer = layers.pop()
            if layer in MANUAL_LAYERS:
                orphan_orbits.append(dict(
                    c4_group_id=int(group['group_id']), layer=layer))
    endpoint_mismatches = []
    for row in rows:
        route = true_by_id[int(row['route_id'])]
        if (row['source_endpoint'], row['target_endpoint']) != (
                route['source_endpoint'], route['target_endpoint']):
            endpoint_mismatches.append(int(row['route_id']))
    manual_layer_overwrites = []
    manual_layer_owner = {int(spec['layer']): group for group, spec
                          in C.MANUAL_GROUPS.items()}
    for layer, owner in manual_layer_owner.items():
        for row in by_layer.get(layer, []):
            if row['manual_group'] != owner or row['layer_role'] not in (
                    'z1_manual_u', 'z2_manual_u'):
                manual_layer_overwrites.append(dict(
                    layer=layer, route_id=int(row['route_id']),
                    manual_group=row['manual_group'],
                    layer_role=row['layer_role']))
    csv_crosscheck = _verified_csv_crosscheck(state, rows)
    previous_assignment = _previous_assignment_crosscheck()
    # deterministic rebuild: build again and compare the serialized rows
    rebuilt = build_assignment(force=True)
    deterministic = _serialize_rows(rebuilt) == _serialize_rows(rows)

    invariants = [
        dict(id='rows_1024', description='exactly 1024 assignment rows',
             passed=len(rows) == 1024),
        dict(id='route_ids_unique',
             description='1024 unique route ids',
             passed=len({int(row['route_id']) for row in rows}) == 1024),
        dict(id='plane_split',
             description='512 z1 + 512 z2 routes',
             passed=dict(by_plane) == {'z1': 512, 'z2': 512},
             detail=dict(by_plane)),
        dict(id='manual_total',
             description='368 manual routes (256 z1 + 112 z2)',
             passed=(role_counts['z1_manual_u'] == 256
                     and role_counts['z2_manual_u'] == 112),
             detail=dict(role_counts)),
        dict(id='manual_group_counts',
             description='Z1 64/64/64/64 and Z2 16/16/40/40',
             passed=dict(manual_counts) == {
                 'Z1-U1': 64, 'Z1-U2': 64, 'Z1-U3': 64, 'Z1-U4': 64,
                 'Z2-U1': 16, 'Z2-U2': 16, 'Z2-U3': 40, 'Z2-U4': 40},
             detail=dict(manual_counts)),
        dict(id='manual_routes_fixed_layer',
             description='every manual route on its user-mandated layer',
             passed=all(
                 int(row['target_layer'])
                 == int(C.MANUAL_GROUPS[row['manual_group']]['layer'])
                 for row in rows if row['manual_group'])),
        dict(id='manual_layer_not_overwritten',
             description='no non-manual row on a manual layer',
             passed=not manual_layer_overwrites,
             detail=manual_layer_overwrites),
        dict(id='endpoint_pairs_preserved',
             description='port pairs identical to common.routes()',
             passed=not endpoint_mismatches,
             detail=endpoint_mismatches),
        dict(id='target_z_matches_layer',
             description='target_z_mm equals PHYSICAL_LAYERS[target_layer]',
             passed=all(abs(float(row['target_z_mm'])
                            - float(C.PHYSICAL_LAYERS[int(row['target_layer'])]))
                        <= 1e-9 for row in rows)),
        dict(id='interface_z_matches_plane',
             description='interface_z_mm equals 0.0 (z1) / 0.5 (z2)',
             passed=all(abs(float(row['interface_z_mm'])
                            - float(C.INTERFACE_Z[str(row['plane'])]))
                        <= 1e-9 for row in rows)),
        dict(id='direction_rule',
             description="direction == 'down' iff target_z < interface_z",
             passed=all(row['direction'] == _direction(
                 row['target_z_mm'], row['interface_z_mm']) for row in rows)),
        dict(id='nonmanual_orbit_single_layer',
             description='each non-manual C4 orbit keeps all 4 routes on '
                         'one layer',
             passed=not spanning_orbits, detail=spanning_orbits),
        dict(id='nonmanual_orbits_avoid_manual_layers',
             description='no non-manual orbit on a manual layer',
             passed=not orphan_orbits, detail=orphan_orbits),
        dict(id='z1_opposite_orbit_split',
             description='64 z1 opposite orbits -> L6 32 / L7 32',
             passed=(layer_orbit_counts['6'] == 32
                     and layer_orbit_counts['7'] == 32
                     and layer_counts['6'] == 128
                     and layer_counts['7'] == 128)),
        dict(id='z2_adjacent_orbit_split',
             description='100 z2 adjacent orbits -> 12/13 per layer, 13 on '
                         'the four layers closest to the Z2 interface',
             passed=all(layer_orbit_counts[str(layer)] == capacity
                        for layer, capacity in Z2_ADJACENT_PLAN),
             detail={str(layer): layer_orbit_counts[str(layer)]
                     for layer, _capacity in Z2_ADJACENT_PLAN}),
        dict(id='verified_csv_crosscheck',
             description='assignment consumes the verified manual CSVs',
             passed=all(csv_crosscheck[label].get('consumed', False)
                        for label in ('z1', 'z2')),
             detail=csv_crosscheck),
        dict(id='deterministic_rebuild',
             description='two consecutive builds are byte-identical',
             passed=bool(deterministic)),
        dict(id='manual_csv_route_ids_equal_manual_assignment',
             description='verified-CSV route ids == manual route ids in the '
                         'assignment',
             passed=sorted(z1_manual) == sorted(
                 int(row['route_id']) for row in rows
                 if row['layer_role'] == 'z1_manual_u')
                    and sorted(z2_manual) == sorted(
                 int(row['route_id']) for row in rows
                 if row['layer_role'] == 'z2_manual_u')),
    ]
    failures = [item for item in invariants if not item['passed']]
    audit = dict(
        schema='fanout_first_assignment_audit_v1',
        run_dir=str(RUN_DIR),
        assignment_csv=str(ASSIGNMENT_CSV),
        rows=len(rows),
        z1=int(by_plane['z1']),
        z2=int(by_plane['z2']),
        unique_route_ids=len({int(row['route_id']) for row in rows}),
        relation_counts=dict(collections.Counter(row['relation']
                                                 for row in rows)),
        manual_counts=dict(manual_counts),
        layer_role_counts=dict(role_counts),
        direction_counts=dict(direction_counts),
        physical_layer_counts=dict(layer_counts),
        physical_layer_orbit_counts=dict(layer_orbit_counts),
        manual_layer_fixed={group: dict(
            layer=int(spec['layer']),
            target_z_mm=float(C.PHYSICAL_LAYERS[int(spec['layer'])]),
            pattern=spec['pattern'],
            routes=int(manual_counts.get(group, 0)))
            for group, spec in C.MANUAL_GROUPS.items()},
        non_manual_orbits=non_manual_orbits,
        non_manual_routes=sum(1 for row in rows
                              if row['layer_role'] in
                              ('z1_other', 'z2_other')),
        orbit_allocations=dict(
            z1_opposite=_layer_plan_report(Z1_OPPOSITE_PLAN,
                                           z1_layer_groups,
                                           C.INTERFACE_Z['z1']),
            z2_adjacent=_layer_plan_report(Z2_ADJACENT_PLAN,
                                           z2_layer_groups,
                                           C.INTERFACE_Z['z2']),
        ),
        allocation_policy=dict(
            z1_opposite='64 C4 opposite orbits sorted by rotation group_id, '
                        'first 32 -> L6, next 32 -> L7',
            z2_adjacent='100 C4 adjacent orbits sorted by rotation group_id, '
                        'consumed sequentially from the layer plan '
                        '(L16 13, L17 13, L15 13, L18 13, L14 12, L19 12, '
                        'L9 12, L8 12); the four 13-orbit layers are the '
                        'layers closest to the Z2 interface (z=0.5)',
            ordering='deterministic, no randomness',
        ),
        manual_reference=dict(
            z1=state['z1']['summary']['prior_assignment_reference'],
            z1_user_640=state['z1']['summary']['user_640_csv_reference'],
            z2=dict(rows=int(state['summary']['q1_excel_raw_rows']),
                    matched=int(state['summary']['excel_rows_matched']),
                    per_group=dict(state['summary']
                                   ['q4_per_group_totals_simple'])),
        ),
        connection_endpoints_preserved=not endpoint_mismatches,
        c4_orbit_single_layer=not spanning_orbits,
        manual_layers_not_overwritten=not manual_layer_overwrites,
        verified_csv_crosscheck=csv_crosscheck,
        previous_assignment_crosscheck=previous_assignment,
        deterministic_rebuild=bool(deterministic),
        invariants=invariants,
        invariant_failures=failures,
        all_invariants_passed=not failures,
        layer_stack=dict(
            physical_layers={str(layer): float(z) for layer, z
                             in C.PHYSICAL_LAYERS.items()},
            manual_layers=list(MANUAL_LAYERS),
            non_manual_layers=list(NON_MANUAL_LAYERS),
            z1_interface_mm=float(C.Z1_INTERFACE_MM),
            z2_interface_mm=float(C.Z2_INTERFACE_MM),
            min_pitch_mm=float(C.MIN_LAYER_PITCH_MM),
            min_3d_clearance_mm=float(C.MIN_3D_CLEARANCE_MM),
        ),
    )
    _AUDIT = audit
    return audit


def _serialize_rows(rows):
    return [tuple(items) for items in
            (row.items() for row in rows)]


# ================================================================ experiment A
def _write_experiment_a(state, rows, audit):
    EXPERIMENT_A.mkdir(parents=True, exist_ok=True)
    summary = state['summary']
    inventory = state['inventory']
    z1 = state['z1']['summary']
    z2_summary = state['z2']['summary']
    layer_counts = audit['physical_layer_counts']

    input_counts = dict(
        schema='fanout_first_experiment_A_input_counts_v1',
        run_dir=str(RUN_DIR),
        excel=dict(
            path=state['excel']['path'],
            sha256=state['excel']['sha256'],
            sheet_names=state['excel']['sheet_names'],
            data_rows=int(state['excel']['data_rows']),
            columns=int(state['excel']['column_count']),
            layer_markers=dict(state['excel_audit']['layer_markers']),
            per_group_counts=dict(state['excel_audit']['per_group_counts']),
        ),
        true_connection_data=dict(
            source=str(C.V4_ROUTES_JSON),
            routes=int(inventory['total']),
            z1=int(inventory['z1']),
            z2=int(inventory['z2']),
            z1_same=int(inventory['z1_same']),
            z1_opposite=int(inventory['z1_opposite']),
            z2_same=int(inventory['z2_same']),
            z2_adjacent=int(inventory['z2_adjacent']),
            rotation_orbits=int(inventory['rotation_orbits']),
            orbit_counts=dict(inventory['orbit_counts']),
        ),
        physical_port_table=dict(
            source='four_side_1024.v3c4.inputs.ENDPOINTS',
            ports=int(inventory['physical_ports']),
        ),
        manual_u_inputs=dict(
            z1_manual_routes=int(z1['z1_manual_routes']),
            z1_groups={group: int(count) for group, count in
                       z1['per_group_counts'].items()},
            z1_source='user original 640-row manual CSV + previous verified '
                      'assignment (cross-checked against true routes)',
            z2_manual_routes=int(z2_summary['excel_rows_matched']),
            z2_groups={group: int(count) for group, count in
                       summary['q4_per_group_totals_simple'].items()},
            z2_source='input Excel 112 rows independently matched to the '
                      'true Z2 same-side routes (plane index corrected 1->2)',
            manual_total=int(z1['z1_manual_routes'])
                         + int(z2_summary['excel_rows_matched']),
        ),
        non_manual_inputs=dict(
            z1_opposite_routes=int(inventory['z1_opposite']),
            z1_opposite_orbits=int(
                state['inventory']['orbit_counts'].get('z1_opposite', 0)),
            z2_adjacent_routes=int(inventory['z2_adjacent']),
            z2_adjacent_orbits=int(
                state['inventory']['orbit_counts'].get('z2_adjacent', 0)),
        ),
        assignment=dict(
            csv=str(ASSIGNMENT_CSV),
            rows=len(rows),
            unique_route_ids=audit['unique_route_ids'],
            z1=audit['z1'],
            z2=audit['z2'],
            manual_counts=dict(audit['manual_counts']),
            layer_role_counts=dict(audit['layer_role_counts']),
            direction_counts=dict(audit['direction_counts']),
        ),
    )

    def question(question_id, text, answer, evidence=None):
        return dict(id=question_id, question=text, answer=answer,
                    evidence=evidence or {})

    questions = [
        question(
            'Q1_excel_raw_rows',
            'Excel 原始数据行数是多少？',
            f"{int(state['excel']['data_rows'])} data rows in one sheet "
            f"({int(state['excel']['column_count'])} columns).",
            dict(data_rows=int(state['excel']['data_rows']),
                 sheet_names=state['excel']['sheet_names'],
                 column_count=int(state['excel']['column_count']))),
        question(
            'Q2_excel_rows_that_are_z1_data',
            'Excel 中有多少行实际上是 Z1 数据？',
            summary['q2_excel_rows_that_are_z1_data']['answer'],
            summary['q2_excel_rows_that_are_z1_data']),
        question(
            'Q3_z2_connections_satisfying_template',
            '512 条真实 Z2 连接中有多少条符合人工 U 型模板？',
            summary['q3_true_z2_connections_satisfying_manual_template'][
                'answer'],
            summary['q3_true_z2_connections_satisfying_manual_template']),
        question(
            'Q4_per_group_totals',
            '各个分组的总数是多少？',
            'Z2: Z2-U1=16, Z2-U2=16, Z2-U3=40, Z2-U4=40.  '
            'Z1: Z1-U1=Z1-U2=Z1-U3=Z1-U4=64.',
            dict(z2=summary['q4_per_group_totals_simple'],
                 z1=dict(z1['per_group_counts']))),
        question(
            'Q5_duplicate_route_ids',
            '是否存在重复的 route id？',
            summary['q5_duplicate_route_ids']['answer'],
            summary['q5_duplicate_route_ids']),
        question(
            'Q6_routes_in_two_groups',
            '是否存在同时属于两个分组的连接？',
            summary['q6_routes_in_two_groups']['answer'],
            summary['q6_routes_in_two_groups']),
        question(
            'Q7_template_pairs_without_real_route',
            '是否有模板端口对在真实 Z2 数据中没有对应连接？',
            summary['q7_template_pairs_with_no_real_z2_route']['answer'],
            dict(pairs=summary['q7_template_pairs_with_no_real_z2_route'][
                'pairs'],
                coverage=summary['q7_template_pairs_with_no_real_z2_route'][
                    'coverage'])),
        question(
            'Q8_coordinate_availability',
            '确认的每条连接是否都有真实坐标？',
            summary['q8_coordinate_availability']['answer'],
            summary['q8_coordinate_availability']),
        question(
            'Q9_claim_112_confirmed',
            '112 条 Z2 人工 U 的结论是否得到确认？',
            summary['claim_112_confirmed']['answer'],
            summary['claim_112_confirmed']),
    ]
    audit_payload = dict(
        schema='fanout_first_experiment_A_audit_v1',
        run_dir=str(RUN_DIR),
        data_audit_questions=questions,
        z1_manual_u_truth=dict(
            routes=int(z1['z1_manual_routes']),
            per_group={group: int(count) for group, count in
                       z1['per_group_counts'].items()},
            group_to_layer=z1['group_to_layer'],
            per_group_side_counts=z1['per_group_side_counts'],
            per_group_pair_counts=z1['per_group_pair_counts'],
            all_true_z1_same=int(z1['covered_true_z1_same_routes']) == int(
                z1['true_z1_same_routes']),
            missing_true_routes=z1['missing_true_z1_same_routes'],
            orbit_structure=dict(
                z1_same_orbits=int(z1['orbit_structure']['z1_same_orbits']),
                covered_orbits=int(z1['orbit_structure']['covered_orbits']),
                orbit_group_composition=z1['orbit_structure'][
                    'orbit_group_composition']),
            prior_assignment_reference=z1['prior_assignment_reference'],
            user_640_csv_reference=z1['user_640_csv_reference'],
            prior_vs_user_640_mismatches=z1['prior_vs_user_640_mismatches'],
            crosscheck_agreement=bool(z1['crosscheck_agreement']),
            all_routes_have_coordinates=bool(
                z1['all_routes_have_coordinates']),
        ),
        z2_manual_u_truth=dict(
            excel_rows=int(state['excel']['data_rows']),
            matched_rows=int(z2_summary['excel_rows_matched']),
            unmatched_rows=int(z2_summary['unmatched']),
            conflict_rows=int(z2_summary['conflicts']),
            per_group={group: int(count) for group, count in
                       z2_summary['per_group_counts'].items()},
            true_z2_same_routes=int(z2_summary['true_z2_same_route_count']),
            true_z2_same_routes_not_matched=z2_summary[
                'true_z2_same_routes_not_matched'],
            template_group_agreement=int(
                z2_summary['template_group_agreement']),
            orbit_structure=dict(
                z2_same_orbits=int(
                    z2_summary['orbit_structure']['z2_same_orbits']),
                covered_orbits=int(
                    z2_summary['orbit_structure']['covered_orbits']),
                orbit_group_composition=z2_summary['orbit_structure'][
                    'orbit_group_composition'],
                orbit_side_composition=z2_summary['orbit_structure'][
                    'orbit_side_composition'],
            ),
            all_confirmed_routes_have_coordinates=bool(
                z2_summary['all_confirmed_routes_have_coordinates']),
        ),
        route_id_authority=state['excel_audit']['route_id_authority'],
        z1_plane_copy_evidence=state['excel_audit']['z1_plane_copy_evidence'],
        assignment=dict(
            rows=int(audit['rows']),
            z1=int(audit['z1']),
            z2=int(audit['z2']),
            manual_counts=dict(audit['manual_counts']),
            layer_role_counts=dict(audit['layer_role_counts']),
            physical_layer_counts=dict(audit['physical_layer_counts']),
            physical_layer_orbit_counts=dict(
                audit['physical_layer_orbit_counts']),
            orbit_allocations=audit['orbit_allocations'],
            direction_counts=dict(audit['direction_counts']),
            all_invariants_passed=bool(audit['all_invariants_passed']),
            invariant_failures=audit['invariant_failures'],
        ),
        previous_round_crosscheck=state['previous_comparison'],
        previous_assignment_crosscheck=audit[
            'previous_assignment_crosscheck'],
        stage_summary=dict(
            stage='experiment_A',
            input_line_count=dict(
                excel_rows=int(state['excel']['data_rows']),
                true_routes=int(inventory['total']),
                physical_ports=int(inventory['physical_ports'])),
            attempted=dict(
                excel_rows_to_match=int(state['excel']['data_rows']),
                assignment_rows=int(audit['rows'])),
            success=dict(
                excel_rows_matched=int(z2_summary['excel_rows_matched']),
                z1_manual_routes=int(z1['z1_manual_routes']),
                assignment_rows=int(audit['rows'])),
            failures=dict(
                excel_rows_unmatched=int(z2_summary['unmatched']),
                excel_rows_conflicts=int(z2_summary['conflicts']),
                missing_true_z2_same_routes=len(
                    z2_summary['true_z2_same_routes_not_matched']),
                assignment_invariant_failures=len(
                    audit['invariant_failures'])),
            failure_reasons={},
            validation_status='passed' if (
                audit['all_invariants_passed']
                and z2_summary['unmatched'] == 0
                and z2_summary['conflicts'] == 0) else 'failed',
        ),
        notes=[
            'Every number in this experiment-A audit is recomputed from the '
            'true route table, the 2048-port table and the input Excel; the '
            'previous round files are read-only cross-check inputs.',
            'The Z2 Excel rows are Z1-plane-numbered: the interface plane '
            'index is corrected 1 -> 2; side/connector/row/column/channel are '
            'preserved and the Excel route_id is never used.',
        ],
    )

    manual_group_rows = []
    z1_group_order = [spec['group'] for spec in V.Z1_GROUP_MAP.values()]
    for group in z1_group_order:
        spec = C.MANUAL_GROUPS[group]
        layer = int(spec['layer'])
        layer_rows = [row for row in rows
                      if row['manual_group'] == group]
        manual_group_rows.append(dict(
            manual_group=group,
            plane='z1',
            manual_pattern=spec['pattern'],
            numbering=('first' if spec['pattern'].endswith('first')
                       else 'second'),
            side_kind=spec['sides'],
            target_layer=layer,
            target_z_mm=float(C.PHYSICAL_LAYERS[layer]),
            direction=_direction(float(C.PHYSICAL_LAYERS[layer]),
                                 C.INTERFACE_Z['z1']),
            route_count=len(layer_rows),
            orbit_count=_orbit_count(layer_rows),
            side_counts=json.dumps(
                dict(sorted(collections.Counter(
                    row['source_side'] for row in layer_rows).items())),
                ensure_ascii=False),
            connector_pairs=json.dumps(
                z1['per_group_pair_counts'].get(group, {}), ensure_ascii=False),
            route_id_min=min(int(row['route_id']) for row in layer_rows),
            route_id_max=max(int(row['route_id']) for row in layer_rows),
            evidence_source='user original 640-row manual CSV, crosschecked '
                            'with the previous verified assignment and the '
                            'true route table',
        ))
    for group in V.Z2_GROUP_ORDER:
        spec = C.MANUAL_GROUPS[group]
        layer = int(spec['layer'])
        layer_rows = [row for row in rows if row['manual_group'] == group]
        detail = summary['q4_per_group_totals'][group]
        manual_group_rows.append(dict(
            manual_group=group,
            plane='z2',
            manual_pattern=spec['pattern'],
            numbering=('first' if spec['pattern'].endswith('first')
                       else 'second'),
            side_kind=spec['sides'],
            target_layer=layer,
            target_z_mm=float(C.PHYSICAL_LAYERS[layer]),
            direction=_direction(float(C.PHYSICAL_LAYERS[layer]),
                                 C.INTERFACE_Z['z2']),
            route_count=len(layer_rows),
            orbit_count=_orbit_count(layer_rows),
            side_counts=json.dumps(detail['sides'], ensure_ascii=False),
            connector_pairs=json.dumps(detail['connector_pairs'],
                                       ensure_ascii=False),
            route_id_min=min(int(row['route_id']) for row in layer_rows),
            route_id_max=max(int(row['route_id']) for row in layer_rows),
            evidence_source='input Excel 112 rows matched one-to-one onto '
                            'true Z2 same-side routes (plane index corrected '
                            '1->2); connector template agreement 112/112',
        ))
    manual_group_columns = [
        'manual_group', 'plane', 'manual_pattern', 'numbering', 'side_kind',
        'target_layer', 'target_z_mm', 'direction', 'route_count',
        'orbit_count', 'side_counts', 'connector_pairs', 'route_id_min',
        'route_id_max', 'evidence_source',
    ]

    layer_rows = []
    per_layer = _rows_by_layer(rows)
    manual_layer_map = {int(spec['layer']): group for group, spec
                        in C.MANUAL_GROUPS.items()}
    for layer in C.ROUTING_LAYER_IDS:
        layer_items = per_layer.get(layer, [])
        if not layer_items:
            continue
        planes = sorted({row['plane'] for row in layer_items})
        roles = sorted({row['layer_role'] for row in layer_items})
        layer_rows.append(dict(
            target_layer=int(layer),
            z_mm=float(C.PHYSICAL_LAYERS[int(layer)]),
            planes=','.join(planes),
            direction=_direction(float(C.PHYSICAL_LAYERS[int(layer)]),
                                 C.INTERFACE_Z[planes[0]]),
            layer_role=','.join(roles),
            manual_group=manual_layer_map.get(int(layer), ''),
            route_count=len(layer_items),
            orbit_count=_orbit_count(layer_items),
            route_id_min=min(int(row['route_id']) for row in layer_items),
            route_id_max=max(int(row['route_id']) for row in layer_items),
            note=('manual group layer (fixed)' if int(layer) in MANUAL_LAYERS
                  else 'non-manual: whole C4 rotation orbits only'),
        ))
    layer_columns = [
        'target_layer', 'z_mm', 'planes', 'direction', 'layer_role',
        'manual_group', 'route_count', 'orbit_count', 'route_id_min',
        'route_id_max', 'note',
    ]

    checks = []
    for item in audit['invariants']:
        checks.append(dict(id=item['id'], description=item['description'],
                           status='passed' if item['passed'] else 'failed',
                           detail=item.get('detail')))
    data_checks = [
        dict(id='excel_rows_112',
             description='Excel has exactly 112 raw data rows',
             status='passed' if int(state['excel']['data_rows']) == 112
             else 'failed',
             detail=dict(rows=int(state['excel']['data_rows']))),
        dict(id='z2_match_complete',
             description='112/112 Excel rows matched to unique true z2 same '
                         'routes with no unmatched/conflict row',
             status='passed' if (int(z2_summary['excel_rows_matched']) == 112
                                 and int(z2_summary['unmatched']) == 0
                                 and int(z2_summary['conflicts']) == 0)
             else 'failed',
             detail=dict(matched=int(z2_summary['excel_rows_matched']),
                         unmatched=int(z2_summary['unmatched']),
                         conflicts=int(z2_summary['conflicts']))),
        dict(id='z2_template_agreement',
             description='connector template reproduces the Excel grouping '
                         'for all 112 rows',
             status='passed' if int(
                 z2_summary['template_group_agreement']) == 112 else 'failed',
             detail=dict(agreement=int(
                 z2_summary['template_group_agreement']))),
        dict(id='z2_orbits_complete',
             description='all 28 z2 same C4 orbits fully covered',
             status='passed' if int(
                 z2_summary['orbit_structure']['covered_orbits']) == int(
                 z2_summary['orbit_structure']['z2_same_orbits']) else 'failed',
             detail=dict(covered=int(
                 z2_summary['orbit_structure']['covered_orbits']),
                 total=int(z2_summary['orbit_structure']['z2_same_orbits']))),
        dict(id='z2_coordinates_available',
             description='all confirmed z2 routes have real coordinates',
             status='passed' if bool(
                 z2_summary['all_confirmed_routes_have_coordinates'])
             else 'failed'),
        dict(id='z1_manual_complete',
             description='256 true z1 same routes == Z1 manual-U set, 64 per '
                         'group',
             status='passed' if (int(z1['z1_manual_routes']) == 256
                                 and int(z1['covered_true_z1_same_routes'])
                                 == 256
                                 and dict(z1['per_group_counts'])
                                 == {'Z1-U1': 64, 'Z1-U2': 64, 'Z1-U3': 64,
                                     'Z1-U4': 64}) else 'failed',
             detail=dict(routes=int(z1['z1_manual_routes']),
                         per_group=dict(z1['per_group_counts']))),
        dict(id='z1_prior_vs_640_csv',
             description='previous verified assignment and the user 640-row '
                         'CSV agree on all z1 manual routes',
             status='passed' if bool(z1['crosscheck_agreement'])
             else 'failed',
             detail=dict(mismatches=z1['prior_vs_user_640_mismatches'])),
        dict(id='z1_coordinates_available',
             description='all 256 z1 manual routes have real coordinates',
             status='passed' if bool(z1['all_routes_have_coordinates'])
             else 'failed'),
        dict(id='claim_112_confirmed',
             description='the 112-row Z2 manual-U claim is confirmed',
             status='passed' if bool(
                 summary['claim_112_confirmed']['confirmed']) else 'failed'),
    ]
    checks.extend(data_checks)
    failed = [check for check in checks if check['status'] != 'passed']
    validation = dict(
        schema='fanout_first_experiment_A_validation_v1',
        status='passed' if not failed else 'failed',
        checks_total=len(checks),
        checks_passed=len(checks) - len(failed),
        checks_failed=len(failed),
        failed_checks=failed,
        checks=checks,
        data_audit_verdict=dict(
            excel_rows=int(state['excel']['data_rows']),
            excel_rows_that_are_z1_data=int(
                summary['q2_excel_rows_that_are_z1_data']['excel_rows']),
            z2_manual_rows_matched=int(z2_summary['excel_rows_matched']),
            z2_unmatched=int(z2_summary['unmatched']),
            z2_conflicts=int(z2_summary['conflicts']),
            z2_groups=dict(summary['q4_per_group_totals_simple']),
            claim_112_confirmed=bool(
                summary['claim_112_confirmed']['confirmed']),
            z1_manual_routes=int(z1['z1_manual_routes']),
            z1_manual_groups=dict(z1['per_group_counts']),
        ),
        assignment_verdict=dict(
            rows=int(audit['rows']),
            unique_route_ids=int(audit['unique_route_ids']),
            z1=int(audit['z1']),
            z2=int(audit['z2']),
            manual_counts=dict(audit['manual_counts']),
            physical_layer_counts=dict(audit['physical_layer_counts']),
            physical_layer_orbit_counts=dict(
                audit['physical_layer_orbit_counts']),
            all_invariants_passed=bool(audit['all_invariants_passed']),
            invariant_failures=audit['invariant_failures'],
        ),
        assignment_ready_for_stage_B=bool(
            audit['all_invariants_passed']
            and summary['claim_112_confirmed']['confirmed']
            and z1['z1_manual_routes'] == 256),
        stage_summary=dict(
            stage='experiment_A',
            input_line_count=dict(
                excel_rows=int(state['excel']['data_rows']),
                true_routes=int(inventory['total'])),
            attempted=dict(excel_rows=int(state['excel']['data_rows']),
                           assignment_rows=int(audit['rows'])),
            success=dict(
                excel_rows_matched=int(z2_summary['excel_rows_matched']),
                assignment_rows=int(audit['rows'])),
            failures=dict(
                excel_rows_unmatched=int(z2_summary['unmatched']),
                excel_rows_conflicts=int(z2_summary['conflicts']),
                assignment_invariant_failures=len(
                    audit['invariant_failures'])),
            failure_reasons={},
            validation_status='passed' if not failed else 'failed',
        ),
        notes=['experienced failures are listed explicitly; nothing is '
               'counted as passed unless the check is evaluated'],
    )

    C.write_json(EXPERIMENT_A / 'input_counts.json',
                 V._json_ready(input_counts))
    C.write_json(EXPERIMENT_A / 'audit.json', V._json_ready(audit_payload))
    C.write_json(EXPERIMENT_A / 'validation_status.json',
                 V._json_ready(validation))
    C.write_csv(EXPERIMENT_A / 'manual_group_audit.csv', manual_group_rows,
                fieldnames=manual_group_columns)
    C.write_csv(EXPERIMENT_A / 'assignment_layer_audit.csv', layer_rows,
                fieldnames=layer_columns)
    return dict(input_counts=input_counts, audit=audit_payload,
                validation_status=validation)


# ================================================================ writing
def write_assignment(rows=None, audit=None, state=None):
    """Write assignment_1024.csv / audit / stack / rules / experiment_A."""
    state = state or V.compute_all()
    rows = rows if rows is not None else build_assignment()
    audit = audit if audit is not None else build_audit(rows, state)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    C.write_csv(ASSIGNMENT_CSV, rows, fieldnames=ASSIGNMENT_COLUMNS)
    C.write_json(ASSIGNMENT_AUDIT_JSON, V._json_ready(audit))
    C.write_json(STACK_JSON, V._json_ready(C.physical_layer_stack_payload()))
    C.write_json(RULES_JSON, V._json_ready(C.process_rules_payload()))
    experiment = _write_experiment_a(state, rows, audit)
    return dict(
        files=dict(
            assignment_csv=str(ASSIGNMENT_CSV),
            assignment_audit=str(ASSIGNMENT_AUDIT_JSON),
            physical_layer_stack=str(STACK_JSON),
            process_rules=str(RULES_JSON),
            experiment_a_input_counts=str(
                EXPERIMENT_A / 'input_counts.json'),
            experiment_a_audit=str(EXPERIMENT_A / 'audit.json'),
            experiment_a_manual_group_audit=str(
                EXPERIMENT_A / 'manual_group_audit.csv'),
            experiment_a_assignment_layer_audit=str(
                EXPERIMENT_A / 'assignment_layer_audit.csv'),
            experiment_a_validation_status=str(
                EXPERIMENT_A / 'validation_status.json'),
        ),
        audit=audit,
        experiment=experiment,
    )


def _ensure_verified_artifacts(state):
    missing = [str(path) for path in VERIFY_DELIVERABLES if not path.is_file()]
    if not missing:
        return False
    V.write_verified(state)
    return True


def summary_lines(rows, audit, written):
    manual = audit['manual_counts']
    orbits = audit['physical_layer_orbit_counts']
    counts = audit['physical_layer_counts']
    layer_text = ' '.join(f'L{layer}:{counts[str(layer)]}'
                          for layer in C.ROUTING_LAYER_IDS)
    role = audit['layer_role_counts']
    lines = [
        '=== fanout1024 1024-route target-layer assignment (P1) ===',
        f"Rows        : {audit['rows']} unique route ids, z1 {audit['z1']} / "
        f"z2 {audit['z2']}",
        f"Roles       : z1_manual_u {role.get('z1_manual_u', 0)}, "
        f"z2_manual_u {role.get('z2_manual_u', 0)}, "
        f"z1_other {role.get('z1_other', 0)}, "
        f"z2_other {role.get('z2_other', 0)}",
        f"Manual      : Z1-U1..U4 -> L2..L5 "
        f"(64/64/64/64); Z2-U1..U4 -> L10..L13 "
        f"({manual.get('Z2-U1', 0)}/{manual.get('Z2-U2', 0)}/"
        f"{manual.get('Z2-U3', 0)}/{manual.get('Z2-U4', 0)})",
        f"Z1 nonmanual: 64 opposite C4 orbits -> L6 {orbits['6']} orbits "
        f"({counts['6']} routes) / L7 {orbits['7']} orbits "
        f"({counts['7']} routes)",
        'Z2 nonmanual: 100 adjacent C4 orbits -> ' + ' '.join(
            f"L{layer}:{orbits[str(layer)]}" for layer in
            (8, 9, 14, 15, 16, 17, 18, 19)) + ' orbits',
        f"Directions  : down {audit['direction_counts'].get('down', 0)} / "
        f"up {audit['direction_counts'].get('up', 0)}",
        f"Layers      : {layer_text}",
        'Invariants  : %d/%d passed%s' % (
            len(audit['invariants']) - len(audit['invariant_failures']),
            len(audit['invariants']),
            '' if audit['all_invariants_passed'] else
            ' -- FAILURES: ' + ', '.join(item['id'] for item in
                                         audit['invariant_failures'])),
        f"Wrote       : {len(written['files'])} files (assignment_1024.csv, "
        f"assignment_audit.json, physical_layer_stack.json, process_rules.json,"
        f" experiment_A/ x5)",
    ]
    return lines


def _append_log(lines):
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        with open(RUN_DIR / 'run.log', 'a', encoding='utf-8') as handle:
            handle.write(f'[{stamp}] assign: ' + ' | '.join(lines[:4]) + '\n')
    except Exception:  # pragma: no cover - logging must never break output
        pass


def print_summary(rows, audit, written):
    lines = summary_lines(rows, audit, written)
    for line in lines:
        print(line)
    _append_log(lines)
    return lines


def main(argv=None):
    """Regenerate the 1024 assignment and experiment-A artifacts."""
    state = V.compute_all()
    wrote_verified = _ensure_verified_artifacts(state)
    rows = build_assignment(force=True)
    audit = build_audit(rows, state)
    written = write_assignment(rows, audit, state)
    lines = print_summary(rows, audit, written)
    if wrote_verified:
        print('note        : verified manual CSVs were missing and have been '
              'regenerated by assign.main()')
    return rows


if __name__ == '__main__':
    main()
