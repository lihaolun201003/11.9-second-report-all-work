# -*- coding: utf-8 -*-
"""Acceptance tests for ``four_side_1024/fanout1024/fanout.py`` (P2).

Run with::

    .venv\\Scripts\\python.exe -m pytest four_side_1024/fanout1024/tests_fanout.py -v

The tests exercise the four acceptance criteria of the fanout-planner task:

1. every candidate transition is the exact R15 two-arc S-curve (start point at
   ``Q = P + lead*d``, end point at ``Q + footprint*d``, correct z0/z1,
   independent min-radius >= 15 - 1e-6 from dense true-3D curvature sampling,
   G1 tangents, footprint formula);
2. ``plan_fanout`` on the 368 manual-U routes (experiment B) succeeds and the
   selected partial routes survive an independent fresh ``l3d.world.World``
   re-check with zero clearance violations; artifacts ``fanout_*.json``,
   ``layerwise_endpoints/`` and ``experiment_B/`` are written;
3. ``plan_fanout`` on all 1024 routes reports honest counts / reasons / time;
4. selected transitions of different routes keep >= 0.05 mm true 3D distance,
   transitions stay >= 0.05 mm from other routes' interface leads, and every
   route endpoint appears exactly once in ``selected``.

The tests always use the authoritative assignment table when it exists
(``RUN_DIR/assignment_1024.csv`` from the data-verifier); otherwise they fall
back to the verified manual CSVs plus the DESIGN.md target-layer rules and,
failing that, skip with an explicit message instead of inventing data.
"""
from __future__ import annotations

import csv
import math
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024 import common as C          # noqa: E402
from four_side_1024.fanout1024 import fanout as F         # noqa: E402
from four_side_1024.fsd25d.path3d import (                # noqa: E402
    make_transition, transition_samples)
from four_side_1024.fslw.geom import line                  # noqa: E402
from four_side_1024.l3d.world import World                 # noqa: E402

RUN_DIR = C.RUN_DIR
RADIUS_MM = 15.0
CLEARANCE_MM = 0.05
LEADS = (0.25, 1.0, 2.0, 4.0, 8.0, 16.0)
MANUAL_LAYERS = (2, 3, 4, 5, 10, 11, 12, 13)
ASSIGNMENT_KEYS = ('relation', 'layer_role', 'target_layer', 'target_z_mm')
_NUMERIC_FLOAT = ('target_z_mm', 'interface_z_mm', 'source_x_mm', 'source_y_mm',
                  'target_x_mm', 'target_y_mm')


# ---------------------------------------------------------------- test data
def _read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def _coerce_assignment_row(raw):
    row = dict(raw)
    row['route_id'] = int(row['route_id'])
    row['target_layer'] = int(row['target_layer'])
    for key in _NUMERIC_FLOAT:
        if row.get(key) not in (None, ''):
            row[key] = float(row[key])
    return row


def _historical_assignment():
    """Any historical assignment CSV with the manual groups (last resort)."""
    candidates = []
    outputs = ROOT / 'outputs'
    if outputs.is_dir():
        candidates = sorted(outputs.glob('**/assignment_1024.csv'))
    for path in candidates:
        try:
            rows = _read_csv(path)
        except Exception:      # pragma: no cover - unreadable historical file
            continue
        if len(rows) != 1024 or 'manual_group' not in rows[0]:
            continue
        if 'target_layer' not in rows[0]:
            continue
        coerced = []
        for raw in rows:
            if raw.get('target_layer') in (None, ''):
                coerced = []
                break
            try:
                coerced.append(_coerce_assignment_row(raw))
            except (TypeError, ValueError):
                coerced = []
                break
        if len(coerced) == 1024:
            return coerced, str(path)
    return None, None


def _synthesise_from_verified_csvs():
    """Manual groups from the verified CSVs + DESIGN.md rules for the rest."""
    z1_csv = RUN_DIR / 'z1_manual_u_verified_L2_L5.csv'
    z2_csv = RUN_DIR / 'z2_manual_u_verified_L10_L13.csv'
    if not z1_csv.is_file() or not z2_csv.is_file():
        return None
    manual = {}
    for path in (z1_csv, z2_csv):
        for raw in _read_csv(path):
            manual[int(raw['route_id'])] = (str(raw['manual_group']).strip(),
                                            int(raw['target_layer']))
    if len(manual) != 368:
        return None
    routes = C.route_by_id()
    groups = C.rotation_groups()
    rows = []
    # non-manual assignment: whole C4 rotation orbits per DESIGN.md section 3.2
    z1_orbits = sorted((group for group in groups if group['plane'] == 'z1'
                        and group['kind'] != 'same'),
                       key=lambda group: group['group_id'])
    z2_orbits = sorted((group for group in groups if group['plane'] == 'z2'
                        and group['kind'] != 'same'),
                       key=lambda group: group['group_id'])
    layer_of_group = {}
    for index, group in enumerate(z1_orbits):
        layer_of_group[group['group_id']] = 6 if index < len(z1_orbits) // 2 else 7
    z2_layers = [16, 17, 15, 18, 14, 19, 9, 8]
    capacity = {layer: (13 if index < 4 else 12)
                for index, layer in enumerate(z2_layers)}
    counts = Counter()
    pointer = 0
    for group in z2_orbits:
        layer = z2_layers[pointer]
        while counts[layer] >= capacity[layer]:
            pointer = (pointer + 1) % len(z2_layers)
            layer = z2_layers[pointer]
        counts[layer] += 1
        layer_of_group[group['group_id']] = layer
        pointer = (pointer + 1) % len(z2_layers)
    group_of_route = C.route_group_map()
    for route in sorted(routes, key=lambda item: item['route_id']):
        route_id = route['route_id']
        if route_id in manual:
            manual_group, target_layer = manual[route_id]
        else:
            manual_group = ''
            target_layer = layer_of_group[group_of_route[route_id]['group_id']]
        rows.append(dict(
            route_id=route_id,
            plane=route['plane'],
            relation=route['relation'],
            manual_group=manual_group,
            target_layer=int(target_layer),
            target_z_mm=C.layer_z(target_layer),
            source_endpoint=route['source_endpoint'],
            target_endpoint=route['target_endpoint'],
            source_side=route['source_side'],
            target_side=route['target_side'],
            layer_role=('manual' if manual_group else 'other'),
        ))
    return rows


def _assignment_rows():
    path = RUN_DIR / 'assignment_1024.csv'
    if path.is_file():
        raw_rows = _read_csv(path)
        if raw_rows and all(key in raw_rows[0] for key in ASSIGNMENT_KEYS):
            if len(raw_rows) != 1024:
                raise AssertionError(
                    f'authoritative assignment has {len(raw_rows)} rows, expected 1024')
            return [_coerce_assignment_row(raw) for raw in raw_rows]
    rows = _synthesise_from_verified_csvs()
    if rows is not None:
        return rows
    rows, source = _historical_assignment()
    if rows is not None:
        return rows
    pytest.skip('no authoritative assignment_1024.csv / verified manual CSVs '
                'available yet; fanout planning tests need the data-verifier '
                'outputs')


# ---------------------------------------------------------------- geometry
def _circum_radius(a, b, c):
    ab = math.dist(a, b)
    bc = math.dist(b, c)
    ca = math.dist(c, a)
    us = [b[i] - a[i] for i in range(3)]
    vs = [c[i] - a[i] for i in range(3)]
    cross = [us[1] * vs[2] - us[2] * vs[1],
             us[2] * vs[0] - us[0] * vs[2],
             us[0] * vs[1] - us[1] * vs[0]]
    area = 0.5 * math.sqrt(sum(value * value for value in cross))
    if area <= 1e-15:
        return float('inf')
    return ab * bc * ca / (4.0 * area)


def _min_curvature_radius(samples):
    minimum = float('inf')
    for index in range(1, len(samples) - 1):
        minimum = min(minimum, _circum_radius(samples[index - 1],
                                              samples[index],
                                              samples[index + 1]))
    return minimum


def _chord_angle(first, second):
    norm_first = math.sqrt(sum(value * value for value in first))
    norm_second = math.sqrt(sum(value * value for value in second))
    if norm_first <= 0.0 or norm_second <= 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(first, second)) / (norm_first * norm_second)
    return math.acos(max(-1.0, min(1.0, dot)))


def _dense_samples(transition, step=0.01):
    return [tuple(float(value) for value in sample)
            for sample in transition_samples(transition, step=step)]


# ---------------------------------------------------------------- partials
def _flat_lead(row, role, record):
    endpoint_id = row['source_endpoint' if role == 'source' else 'target_endpoint']
    port, _inward, _z = C.endpoint_pose(endpoint_id)
    start_xy = (float(record['start_xy'][0]), float(record['start_xy'][1]))
    primitive = line(port, start_xy) if role == 'source' else line(start_xy, port)
    return dict(kind='flat', layer_id=1, z_mm=float(record['z0']),
                length_mm=math.dist(port, start_xy), primitives=[primitive])


def _test_partial(row, role, record, world_id):
    flat = _flat_lead(row, role, record)
    if role == 'source':
        parts = [flat, dict(record['transition'])]
    else:
        parts = [dict(record['reverse_transition']), flat]
    return dict(route_id=int(world_id), plane=row.get('plane'),
                start_z_mm=float(record['z0']), end_z_mm=float(record['z1']),
                parts=parts)


def _fresh_world_violations(selected, rows):
    """Rebuild a fresh World from the selected partial routes, reversed order."""
    row_by_id = {int(row['route_id']): row for row in F.normalize_rows(rows)}
    entries = []
    for route_id in sorted(selected):
        row = row_by_id[route_id]
        pair = selected[route_id]
        for role in ('source', 'target'):
            world_id = 2 * route_id + (0 if role == 'source' else 1)
            entries.append(_test_partial(row, role, pair[role], world_id))
    world = World(C.layer_stack(), clearance=CLEARANCE_MM)
    violations = []
    for route in reversed(entries):
        found = world.check_route(route)
        if found:
            violations.append(dict(route_id=route['route_id'],
                                   violations=found[:3]))
        world.add_route(route)
    return violations


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope='module')
def assignment_rows():
    return _assignment_rows()


@pytest.fixture(scope='module')
def manual_rows(assignment_rows):
    return [row for row in assignment_rows
            if str(row.get('manual_group') or '').strip().startswith(('Z1-U', 'Z2-U'))
            and int(row['target_layer']) in MANUAL_LAYERS]


@pytest.fixture(scope='module')
def manual_result(manual_rows):
    result = F.plan_manual_groups(manual_rows, log=None)
    result['_elapsed'] = result['stats']['seconds']
    return result


@pytest.fixture(scope='module')
def all_result(assignment_rows):
    return F.plan_fanout(assignment_rows, log=None)


# ============================================================ test 1
def test_candidate_transitions_geometry(assignment_rows):
    """Candidate transitions are exact R15 two-arc S-curves (acceptance 1)."""
    routes = C.route_by_id()
    rows = sorted(assignment_rows, key=lambda row: int(row['route_id']))
    representatives = {}
    for row in rows:
        representatives.setdefault(int(row['target_layer']), row)
    assert set(representatives) == set(C.PHYSICAL_LAYERS), \
        'every physical body layer must be representable in the test set'
    checked = 0
    for layer in sorted(representatives):
        row = representatives[layer]
        route = routes[int(row['route_id'])]
        target_layer = int(row['target_layer'])
        z_interface = C.interface_z(route['plane'])
        z_target = C.layer_z(target_layer)
        for role in ('source', 'target'):
            endpoint_id = route['source_endpoint' if role == 'source'
                               else 'target_endpoint']
            port, inward, _z = C.endpoint_pose(endpoint_id)
            candidates = F.candidate_transitions(route, role, target_layer)
            assert [record['lead_mm'] for record in candidates] == list(LEADS)
            assert all(record['geometry'] == 'two_arc_S' for record in candidates)
            assert all(record['radius_mm'] == RADIUS_MM for record in candidates)
            for lead, record in zip(LEADS, candidates):
                record['route_id'] = int(route['route_id'])
                # ---- start point == Q = P + lead * d
                expected_start = (port[0] + inward[0] * lead,
                                  port[1] + inward[1] * lead)
                assert math.dist(record['start_xy'], expected_start) <= 1e-12
                assert abs(record['lead_mm'] - lead) <= 1e-12
                assert math.dist(record['start_xyz'],
                                 (*expected_start, z_interface)) <= 1e-12
                # ---- z0/z1
                assert abs(record['z0'] - z_interface) <= 1e-12
                assert abs(record['z1'] - z_target) <= 1e-12
                assert abs(record['target_z_mm'] - z_target) <= 1e-12
                assert int(record['target_layer']) == target_layer
                # ---- footprint / theta / length formulas
                dz = abs(z_target - z_interface)
                theta = math.acos(max(-1.0, min(1.0, 1.0 - dz / (2.0 * RADIUS_MM))))
                footprint = 2.0 * RADIUS_MM * math.sin(theta)
                assert abs(record['theta_rad'] - theta) <= 1e-12
                assert abs(record['footprint_mm'] - footprint) <= 1e-9
                assert abs(record['length_mm']
                           - 2.0 * RADIUS_MM * theta) <= 1e-9
                # ---- end point == Q + footprint * d
                expected_end = (expected_start[0] + inward[0] * footprint,
                                expected_start[1] + inward[1] * footprint)
                assert math.dist(record['end_xy'], expected_end) <= 1e-9
                assert math.dist(record['end_xyz'],
                                 (*expected_end, z_target)) <= 1e-9
                # ---- make_transition dict consistency
                transition = record['transition']
                assert transition['kind'] == 'transition'
                assert math.dist(transition['start'], expected_start) <= 1e-12
                assert math.dist(transition['end'], expected_end) <= 1e-9
                assert abs(transition['z0'] - z_interface) <= 1e-12
                assert abs(transition['z1'] - z_target) <= 1e-12
                assert abs(transition['radius_mm'] - RADIUS_MM) <= 1e-12
                # ---- reversed transition (target-role traversal)
                reverse = record['reverse_transition']
                assert reverse['kind'] == 'transition'
                assert math.dist(reverse['start'], expected_end) <= 1e-9
                assert math.dist(reverse['end'], expected_start) <= 1e-9
                assert abs(reverse['z0'] - z_target) <= 1e-12
                assert abs(reverse['z1'] - z_interface) <= 1e-12
                assert reverse['direction'][0] == pytest.approx(-inward[0])
                assert reverse['direction'][1] == pytest.approx(-inward[1])
                # ---- independent dense true-3D R15 audit
                samples = _dense_samples(record['transition'])
                min_radius = _min_curvature_radius(samples)
                assert min_radius >= RADIUS_MM - 1e-6, \
                    f'route {route["route_id"]} {role} lead {lead}: ' \
                    f'min radius {min_radius} < 15'
                reverse_min_radius = _min_curvature_radius(
                    _dense_samples(record['reverse_transition']))
                assert reverse_min_radius >= RADIUS_MM - 1e-6
                # ---- G1: start/end tangents follow the inward direction and the
                # chord direction changes by only one sample step of arc angle.
                assert _chord_angle(
                    [samples[1][axis] - samples[0][axis] for axis in range(3)],
                    (inward[0], inward[1], 0.0)) <= 5e-3
                assert _chord_angle(
                    [samples[-1][axis] - samples[-2][axis] for axis in range(3)],
                    (inward[0], inward[1], 0.0)) <= 5e-3
                max_turn = max(
                    _chord_angle([samples[index + 1][axis] - samples[index][axis]
                                  for axis in range(3)],
                                 [samples[index + 2][axis] - samples[index + 1][axis]
                                  for axis in range(3)])
                    for index in range(len(samples) - 2))
                assert max_turn <= 1e-2
                # ---- the interface lead is a positive flat on L1
                lead_part = record['lead_part']
                assert lead_part['kind'] == 'flat'
                assert int(lead_part['layer_id']) == 1
                assert abs(float(lead_part['z_mm']) - z_interface) <= 1e-12
                assert abs(float(lead_part['length_mm']) - lead) <= 1e-12
                assert len(lead_part['primitives']) == 1
                assert lead_part['primitives'][0]['kind'] == 'line'
                checked += 1
    assert checked == len(representatives) * 2 * len(LEADS)


def test_candidate_transitions_rejects_short_leads_and_accepts_route_records():
    route = C.routes()[0]
    with pytest.raises(ValueError):
        F.candidate_transitions(route, 'source', 6, leads=(0.1,))
    candidates = F.candidate_transitions(route, 'source', 6)
    assert len(candidates) == len(LEADS)
    # the original true-route record is a supported input form
    port, inward, _z = C.endpoint_pose(route['source_endpoint'])
    assert math.dist(candidates[0]['start_xy'],
                     (port[0] + inward[0] * LEADS[0],
                      port[1] + inward[1] * LEADS[0])) <= 1e-12
    with pytest.raises(ValueError):
        F.candidate_transitions(route, 'middle', 6)


# ============================================================ test 2
def test_manual_experiment_b(manual_rows, manual_result, tmp_path):
    """368 manual-U routes: plan, independent fresh-world re-check, artifacts."""
    assert len(manual_rows) == 368, (
        f'experiment B expects 368 manual-U routes, got {len(manual_rows)}')
    group_counter = Counter(str(row['manual_group']) for row in manual_rows)
    assert set(group_counter) == set(C.MANUAL_GROUPS)
    for row in manual_rows:
        group = str(row['manual_group'])
        assert int(row['target_layer']) == C.MANUAL_GROUPS[group]['layer']
    result = manual_result
    assert len(result['selected']) == 368
    assert result['failures'] == [], result['failures']
    assert result['stats']['success_endpoints'] == 736
    assert result['stats']['seconds'] < 600
    for route_id, pair in result['selected'].items():
        assert pair['source']['endpoint_role'] == 'source'
        assert pair['target']['endpoint_role'] == 'target'
        assert float(pair['source']['lead_mm']) >= F.MIN_LEAD_MM
        assert float(pair['target']['lead_mm']) >= F.MIN_LEAD_MM
    # same-side manual U pairs: joint equal-lead variant preferred in this
    # dataset (the whole 368-route stage fits with the 0.25 mm minimum lead)
    same_side_leads = [(float(pair['source']['lead_mm']),
                        float(pair['target']['lead_mm']))
                       for route_id, pair in result['selected'].items()
                       if result['selected'][route_id]['source']['endpoint_role']
                       == 'source']
    assert same_side_leads, 'no selected fanout'
    # ---- independent fresh World re-check (reversed insertion order)
    violations = _fresh_world_violations(result['selected'], result['rows'])
    assert violations == [], f'fresh world violations: {violations[:3]}'
    # ---- artifacts (top level + experiment_B/)
    art = F.write_artifacts(result, tmp_path, experiment_name='experiment_B',
                            log=None)
    for relative in ('fanout_candidates.json', 'fanout_selected.json',
                     'fanout_validation.json',
                     'layerwise_endpoints/endpoints.json',
                     'experiment_B/summary.json',
                     'experiment_B/per_group.json',
                     'experiment_B/failed_routes.json',
                     'experiment_B/manual_group_summary.json'):
        assert (tmp_path / relative).is_file(), f'missing artifact {relative}'
    validation = art['validation']
    assert validation['passed'], validation['checks']
    assert validation['checks']['fresh_world_ok']
    assert validation['fresh_world_recheck']['violation_count'] == 0
    assert validation['pair_distance_audit']['pass_clearance']
    assert validation['coverage']['all_rows_selected']
    assert validation['radius_audit']['min_radius_mm'] >= RADIUS_MM - 1e-6
    # ---- experiment_B per-group report: every group fully successful
    manual_groups = art['per_group']
    for group, bucket in manual_groups.items():
        if group not in C.MANUAL_GROUPS:
            continue
        assert bucket['input_routes'] == group_counter[group]
        assert bucket['endpoints_needing_transition'] == 2 * group_counter[group]
        assert bucket['success_routes'] == bucket['input_routes']
        assert bucket['success_endpoints'] == 2 * bucket['input_routes']
        assert bucket['failed_routes'] == 0
        assert bucket['r15_legal_routes'] == bucket['success_routes']
        assert bucket['min_radius_mm'] >= RADIUS_MM - 1e-6
    print('[experiment_B] groups:',
          {group: bucket['success_routes']
           for group, bucket in manual_groups.items()
           if group in C.MANUAL_GROUPS})


# ============================================================ test 3
def test_all_1024_fanout(assignment_rows, all_result):
    """All 1024 routes: honest success/failure counts, reasons and runtime."""
    result = all_result
    assert len(assignment_rows) == 1024
    assert len(result['selected']) + len(result['failures']) == 1024
    if result['failures']:
        print('[all-1024] failures:')
        for failure in result['failures'][:20]:
            print('  ', failure)
    assert result['failures'] == [], (
        'the verified 1024-route assignment is expected to fan out completely; '
        f'{len(result["failures"])} failures: '
        f'{[(item["route_id"], item["reason"]) for item in result["failures"][:10]]}')
    assert result['stats']['success_endpoints'] == 2048
    assert result['stats']['seconds'] < 600, (
        f'performance target exceeded: {result["stats"]["seconds"]:.1f}s')
    rows_by_id = {int(row['route_id']): row for row in assignment_rows}
    transition_count = 0
    leads = Counter()
    for route_id, pair in result['selected'].items():
        row = rows_by_id[route_id]
        for role in ('source', 'target'):
            record = pair[role]
            assert int(record['route_id']) == route_id
            assert int(record['target_layer']) == int(row['target_layer'])
            assert abs(float(record['z1']) - C.layer_z(int(row['target_layer']))) <= 1e-12
            assert float(record['lead_mm']) >= F.MIN_LEAD_MM - 1e-12
            assert float(record['lead_mm']) <= max(F.LEAD_CANDIDATES) + 1e-12
            leads[round(float(record['lead_mm']), 6)] += 1
            transition_count += 1
    assert transition_count == 2048
    print('[all-1024] success_routes=', len(result['selected']),
          'failures=', len(result['failures']),
          'seconds=', result['stats']['seconds'],
          'lead_histogram=', dict(leads))


# ============================================================ test 4
def test_pair_distances_and_endpoint_coverage(all_result):
    """Acceptance 4: true-3D pair clearances and endpoint uniqueness."""
    selected = all_result['selected']
    step = 0.05
    transitions = []
    leads = []
    for route_id in sorted(selected):
        pair = selected[route_id]
        for role in ('source', 'target'):
            record = pair[role]
            samples = [tuple(float(value) for value in sample)
                       for sample in transition_samples(record['transition'],
                                                        step=step)]
            transitions.append((route_id, role, samples))
            flat = record['lead_part']
            primitive = flat['primitives'][0]
            leads.append((route_id, role,
                          (float(primitive['p0'][0]), float(primitive['p0'][1]),
                           float(flat['z_mm'])),
                          (float(primitive['p1'][0]), float(primitive['p1'][1]),
                           float(flat['z_mm']))))

    def cell(point, size=0.5):
        return (int(math.floor(point[0] / size)),
                int(math.floor(point[1] / size)),
                int(math.floor(point[2] / size)))

    def neighbours(point, size=0.5):
        key = cell(point, size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    yield (key[0] + dx, key[1] + dy, key[2] + dz)

    # ---- transitions of different routes
    grid = defaultdict(set)
    for index, (_route_id, _role, samples) in enumerate(transitions):
        for sample in samples:
            grid[cell(sample)].add(index)
    min_transition = float('inf')
    worst_pair = None
    same_route_min = float('inf')
    for index, (route_id, role, samples) in enumerate(transitions):
        nearby = set()
        for sample in samples:
            for key in neighbours(sample):
                bucket = grid.get(key)
                if bucket:
                    nearby.update(bucket)
        for other_index in nearby:
            if other_index <= index:
                continue
            other_route, other_role, other_samples = transitions[other_index]
            distance = float('inf')
            for sample in samples:
                for other_sample in other_samples:
                    distance = min(distance,
                                   math.dist(sample, other_sample))
                    if distance <= 1e-12:
                        break
            if route_id == other_route:
                same_route_min = min(same_route_min, distance)
            elif distance < min_transition:
                min_transition = distance
                worst_pair = (route_id, role, other_route, other_role)
    # 1-Lipschitz certificate: true distance >= sampled minimum - 2*step/2
    certified_transition = min_transition - step
    assert certified_transition >= CLEARANCE_MM - 1e-9, (
        f'transition pair too close: sampled min {min_transition} '
        f'(certified {certified_transition}), worst pair {worst_pair}')
    if math.isfinite(same_route_min):
        assert same_route_min >= CLEARANCE_MM - 1e-9

    # ---- transitions versus foreign interface leads
    lead_grid = defaultdict(set)
    lead_samples = []
    for route_id, role, p0, p1 in leads:
        length = math.dist(p0, p1)
        count = max(1, int(math.ceil(length / step)))
        for index in range(count + 1):
            fraction = index / count
            sample = (p0[0] + (p1[0] - p0[0]) * fraction,
                      p0[1] + (p1[1] - p0[1]) * fraction, p0[2])
            lead_samples.append((route_id, role, sample))
            lead_grid[cell(sample)].add(len(lead_samples) - 1)
    min_lead = float('inf')
    worst_lead_pair = None
    for route_id, role, samples in transitions:
        nearby = set()
        for sample in samples:
            for key in neighbours(sample):
                bucket = lead_grid.get(key)
                if bucket:
                    nearby.update(bucket)
        for index in nearby:
            other_route, other_role, other_point = lead_samples[index]
            if other_route == route_id:
                continue
            for sample in samples:
                distance = math.dist(sample, other_point)
                if distance < min_lead:
                    min_lead = distance
                    worst_lead_pair = (route_id, role, other_route, other_role)
    certified_lead = min_lead - step
    assert certified_lead >= CLEARANCE_MM - 1e-9, (
        f'transition-vs-foreign-lead too close: sampled min {min_lead} '
        f'(certified {certified_lead}), worst pair {worst_lead_pair}')

    # ---- every route endpoint appears exactly once in selected
    rows = F.normalize_rows(all_result['rows'])
    assert {row['route_id'] for row in rows} == set(selected)
    seen = Counter()
    for route_id, pair in selected.items():
        assert set(pair) == {'source', 'target'}
        for role in ('source', 'target'):
            record = pair[role]
            endpoint_id = record.get('endpoint_id')
            assert endpoint_id, f'route {route_id} {role}: missing endpoint id'
            seen[(role, endpoint_id)] += 1
    assert len(seen) == 2048
    assert all(value == 1 for value in seen.values()), 'duplicate endpoint'
    print('[pair-audit] transitions min sampled=', round(min_transition, 6),
          'certified=', round(certified_transition, 6),
          'worst=', worst_pair)
    print('[pair-audit] transition-vs-foreign-lead min sampled=',
          round(min_lead, 6), 'certified=', round(certified_lead, 6),
          'worst=', worst_lead_pair)


# ============================================================ test 5
def test_landings_and_layer_obstacles(all_result):
    """Landings / layer_obstacles API of DESIGN.md 3.3."""
    selected = all_result['selected']
    landings = F.landings(selected)
    assert set(landings) == set(selected)
    for route_id, pair in selected.items():
        landing = landings[route_id]
        assert set(landing) == {'A', 'dA', 'B', 'dB'}
        assert math.dist(landing['A'],
                         tuple(pair['source']['end_xy'])) <= 1e-12
        assert math.dist(landing['B'],
                         tuple(pair['target']['end_xy'])) <= 1e-12
        assert landing['dA'] == tuple(pair['source']['direction'])
        assert landing['dB'] == tuple(pair['target']['direction'])
        assert abs(math.hypot(*landing['dA']) - 1.0) <= 1e-12
        assert abs(math.hypot(*landing['dB']) - 1.0) <= 1e-12

    F.clear_caches()
    started = time.perf_counter()
    obstacles = {}
    for layer_id in C.PHYSICAL_LAYERS:
        obstacles[int(layer_id)] = F.layer_obstacles(selected, layer_id)
    elapsed = time.perf_counter() - started
    assert elapsed < 60.0, f'layer obstacles too slow: {elapsed:.1f}s for 18 layers'
    for layer_id, samples in obstacles.items():
        layer_z = C.layer_z(layer_id)
        for sample in samples:
            assert set(sample) == {'x', 'y', 'z', 'route_id', 'role'}
            assert abs(float(sample['z']) - layer_z) <= 0.07 + 1e-12
            assert int(sample['route_id']) in selected
            assert sample['role'] in ('source', 'target')
    # a transition that crosses a layer band must contribute samples there
    route_id = sorted(selected)[0]
    record = selected[route_id]['source']
    transition = record['transition']
    for layer_id in C.PHYSICAL_LAYERS:
        layer_z = C.layer_z(layer_id)
        expected = [sample for sample in
                    transition_samples(transition, step=0.02)
                    if abs(float(sample[2]) - layer_z) <= 0.07 + 1e-12]
        found = [sample for sample in obstacles[int(layer_id)]
                 if int(sample['route_id']) == route_id
                 and sample['role'] == 'source']
        assert len(found) >= len(expected) - 1, (
            f'layer {layer_id}: {len(found)} obstacle samples < '
            f'{len(expected)} expected')
    # cached second pass returns the same data and is fast
    started = time.perf_counter()
    again = F.layer_obstacles(selected, 10)
    cached_elapsed = time.perf_counter() - started
    assert len(again) == len(obstacles[10])
    assert cached_elapsed < 5.0
    print('[layer_obstacles] counts=', {layer: len(samples)
                                        for layer, samples in obstacles.items()},
          'elapsed=', round(elapsed, 2), 'cached=', round(cached_elapsed, 3))


# ============================================================ test 6
def test_fixed_endpoints_are_immutable_and_repair_works(manual_result):
    """``fixed`` transitions are never moved; ``repair_ids`` plans only those."""
    assignment_rows = _assignment_rows()
    fixed = manual_result['selected']
    non_manual = [int(row['route_id']) for row in assignment_rows
                  if not str(row.get('manual_group') or '').strip()]
    repair_ids = non_manual[:16]
    result = F.plan_fanout(assignment_rows, fixed=fixed,
                           repair_ids=repair_ids, log=None)
    assert set(result['selected']) == set(fixed) | set(repair_ids)
    assert result['failures'] == []
    assert result['stats']['fixed_routes'] == len(fixed)
    assert result['stats']['fixed_conflicts'] == 0
    for route_id in fixed:
        for role in ('source', 'target'):
            assert (result['selected'][route_id][role]['candidate_id']
                    == fixed[route_id][role]['candidate_id'])
    # the repaired routes were really re-planned (they appear as scope rows)
    scope_ids = {int(row['route_id']) for row in result['rows']}
    assert set(repair_ids).issubset(scope_ids)
    for route_id in repair_ids:
        pair = result['selected'][route_id]
        assert float(pair['source']['lead_mm']) >= F.MIN_LEAD_MM
    # validation of the mixed fixed/repaired set passes a fresh world
    validation = F.validate_selected(result['selected'], result['rows'],
                                     fresh_world=True, pair_audit=False)
    assert validation['passed'], validation['checks']


if __name__ == '__main__':      # pragma: no cover - manual invocation
    sys.exit(pytest.main([__file__, '-v', '-s']))
