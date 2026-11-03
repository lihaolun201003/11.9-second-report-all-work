# -*- coding: utf-8 -*-
"""Self-tests for the P0/P1 data verification + 1024 assignment deliverables.

Run with::

    .venv\\Scripts\\python.exe -m four_side_1024.fanout1024.tests_data

The module regenerates the artifacts through the public entry points (both are
deterministic and idempotent) and then asserts the contracts of DESIGN.md
sections 0, 1, 3.1 and 3.2 against the true data set, the 2048-port table and
the input Excel.  Every test prints PASS/FAIL; the process exits non-zero when
any test fails.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import traceback
from pathlib import Path

from . import assign as A
from . import common as C
from . import verify as V

PASSED = []
FAILED = []


def _test(name):
    def wrap(function):
        def runner():
            try:
                detail = function()
                PASSED.append(name)
                print(f'PASS {name}' + (f'  [{detail}]' if detail else ''))
            except Exception as error:  # noqa: BLE001 - report every failure
                FAILED.append((name, repr(error)))
                print(f'FAIL {name}: {error!r}')
                traceback.print_exc(limit=3)
        runner.__name__ = function.__name__
        return runner
    return wrap


def _finite_xy(endpoint_record):
    try:
        x, y = endpoint_record['routing_xy']
        x, y = float(x), float(y)
    except Exception:  # pragma: no cover - defensive
        return False
    import math
    return math.isfinite(x) and math.isfinite(y)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ================================================================ state
def _state():
    """Full deterministic regeneration of every P0/P1 artifact."""
    state = V.compute_all(force=True)
    V.write_verified(state)
    rows = A.build_assignment(force=True)
    audit = A.build_audit(rows, state)
    A.write_assignment(rows, audit, state)
    return state, rows, audit


# ================================================================ tests
@_test('test_excel_workbook_is_raw_z1_data')
def test_excel_workbook_is_raw_z1_data():
    excel = V.load_excel()
    assert len(excel['sheet_names']) == 1, 'Excel must have exactly one sheet'
    assert excel['data_rows'] == 112, f"expected 112 data rows, got {excel['data_rows']}"
    assert excel['column_count'] == 26, f"expected 26 columns, got {excel['column_count']}"
    records = excel['records']
    layer_counts = collections.Counter(str(record['layer']) for record in records)
    assert layer_counts == {'z1': 112}, layer_counts
    group_counts = collections.Counter(str(record['manual_group'])
                                       for record in records)
    assert group_counts == {'Z2-U1': 16, 'Z2-U2': 16,
                            'Z2-U3': 40, 'Z2-U4': 40}, group_counts
    assert len({int(record['route_id']) for record in records}) == 112
    assert all(int(record['route_id']) <= 512 for record in records), \
        'all Excel route ids must be in the true Z1 route-id range'
    plane_indexes = collections.Counter()
    for record in records:
        plane_indexes[V._port_plane_index(record['source_port_id'])] += 1
        plane_indexes[V._port_plane_index(record['target_port_id'])] += 1
    assert plane_indexes == {1: 224}, plane_indexes
    return f'1 sheet, 112 rows, all layer=z1 / plane index 1, groups {dict(group_counts)}'


@_test('test_excel_route_id_is_not_authoritative')
def test_excel_route_id_is_not_authoritative():
    audit = V.audit_excel()
    evidence = audit['route_id_authority']
    assert evidence['exact_endpoint_pair_agreement_with_true_route_of_same_id'] == 0, \
        'Excel route_id unexpectedly agrees with the true route of the same id'
    assert evidence['all_excel_ids_in_true_z1_id_range'] is True
    relations = evidence['true_relation_of_same_id_routes']
    assert set(relations) == {'same', 'opposite'}, relations
    assert evidence['duplicate_route_ids'] == []
    plane = audit['z1_plane_copy_evidence']
    assert plane['plane2_corrected_matches_true_z2_same'] == 112
    assert plane['plane2_corrected_matches_true_z1_any'] == 0
    return ('0/112 same-id agreement; plane index 1 -> 2 correction maps all '
            '112 rows onto true z2 same routes (48 literal z1-pattern overlaps '
            'are documented)')


@_test('test_z2_matched_count_equals_true_z2_same_112_and_16_16_40_40')
def test_z2_matched_count_equals_true_z2_same_112_and_16_16_40_40():
    state = V.compute_all()
    match = state['z2']
    summary = match['summary']
    true_z2_same = [route for route in C.routes()
                    if route['plane'] == 'z2' and route['relation'] == 'same']
    assert len(true_z2_same) == 112
    assert summary['excel_rows_matched'] == 112, summary['excel_rows_matched']
    assert summary['excel_rows_matched'] == len(true_z2_same)
    per_group = summary['per_group_counts']
    assert per_group == {'Z2-U1': 16, 'Z2-U2': 16,
                         'Z2-U3': 40, 'Z2-U4': 40}, per_group
    assert per_group['Z2-U1'] + per_group['Z2-U2'] + per_group['Z2-U3'] \
        + per_group['Z2-U4'] == summary['excel_rows_matched']
    assert summary['unmatched'] == 0, summary['unmatched']
    assert summary['conflicts'] == 0, summary['conflicts']
    assert summary['true_z2_same_routes_not_matched'] == []
    assert summary['matched_routes_not_in_true_z2_same'] == []
    assert summary['unique_matched_route_ids'] == 112
    assert summary['template_group_agreement'] == 112
    assert summary['true_z2_connections_satisfying_template'] == 112
    return 'matched 112 == true z2 same 112 == 16+16+40+40'


@_test('test_z2_match_has_no_duplicate_route_ids')
def test_z2_match_has_no_duplicate_route_ids():
    state = V.compute_all()
    summary = state['z2']['summary']
    ids = [int(row['matched_route_id']) for row in state['z2']['matched']]
    assert len(ids) == len(set(ids)), 'duplicate matched route ids'
    assert summary['duplicate_matched_route_ids'] == []
    assert summary['routes_in_two_groups'] == []
    assert summary['duplicate_route_ids_in_two_groups'] == 0
    return '112 unique ids, no route in two groups'


@_test('test_z2_c4_orbit_structure')
def test_z2_c4_orbit_structure():
    state = V.compute_all()
    orbit = state['z2']['summary']['orbit_structure']
    assert orbit['z2_same_orbits'] == 28
    assert orbit['covered_orbits'] == 28
    assert orbit['orbit_side_composition'] == {'EE,NN,SS,WW': 28}
    assert orbit['orbit_group_composition'] == {
        'Z2-U1,Z2-U1,Z2-U2,Z2-U2': 8,
        'Z2-U3,Z2-U3,Z2-U4,Z2-U4': 20,
    }, orbit['orbit_group_composition']
    for record in orbit['orbits']:
        assert record['complete'] is True, record
        assert record['numbering'] in ('first', 'second'), record
        if record['numbering'] == 'first':
            assert sorted(record['matched_group_composition']) == [
                'Z2-U1', 'Z2-U1', 'Z2-U2', 'Z2-U2']
        else:
            assert sorted(record['matched_group_composition']) == [
                'Z2-U3', 'Z2-U3', 'Z2-U4', 'Z2-U4']
    return '28/28 orbits complete, 8 first-numbering + 20 second-numbering'


@_test('test_z2_template_grouping_matches_excel_groups')
def test_z2_template_grouping_matches_excel_groups():
    state = V.compute_all()
    for row in state['z2']['matched']:
        group, _pair = V._template_group(row['_route'])
        assert group == str(row['excel_manual_group']), (
            row['matched_route_id'], group, row['excel_manual_group'])
        assert bool(row['group_agreement']) is True
    missing = state['z2']['summary'][
        'template_pairs_with_no_real_z2_route']
    assert missing == [], missing
    coverage = state['z2']['summary']['template_coverage']
    for group, sides in coverage.items():
        for key, count in sides.items():
            assert int(count) > 0, (group, key, count)
    return ('all 112 rows grouped by the connector-number template; no empty '
            'template pair')


@_test('test_all_matched_endpoints_have_real_coordinates')
def test_all_matched_endpoints_have_real_coordinates():
    state = V.compute_all()
    endpoints = C.endpoints()
    assert len(endpoints) == 2048
    checked = 0
    for row in state['z2']['matched']:
        route = row['_route']
        for endpoint_id in (route['source_endpoint'],
                            route['target_endpoint']):
            assert endpoint_id in endpoints, endpoint_id
            assert _finite_xy(endpoints[endpoint_id]), endpoint_id
            checked += 2
    assert state['z2']['summary'][
        'all_confirmed_routes_have_coordinates'] is True
    assert state['z2']['summary']['coordinate_missing_route_ids'] == []
    for row in state['z1_csv_rows']:
        for endpoint_id in (row['source_endpoint'], row['target_endpoint']):
            assert endpoint_id in endpoints, endpoint_id
            assert _finite_xy(endpoints[endpoint_id]), endpoint_id
            checked += 2
    for row in state['z1']['rows']:
        assert row['source_endpoint'] in endpoints
        assert row['target_endpoint'] in endpoints
    return f'{checked} endpoints checked in the 2048-port table'


@_test('test_z1_manual_u_verification')
def test_z1_manual_u_verification():
    state = V.compute_all()
    z1 = state['z1']['summary']
    true_z1_same = {int(route['route_id']) for route in C.routes()
                    if route['plane'] == 'z1' and route['relation'] == 'same'}
    assert len(true_z1_same) == 256
    rows = state['z1']['rows']
    assert len(rows) == 256, len(rows)
    ids = {int(row['route_id']) for row in rows}
    assert ids == true_z1_same, 'Z1 manual set != true z1 same routes'
    counts = collections.Counter(row['delivered_manual_group'] for row in rows)
    assert counts == {'Z1-U1': 64, 'Z1-U2': 64,
                      'Z1-U3': 64, 'Z1-U4': 64}, counts
    orbit = z1['orbit_structure']
    assert orbit['z1_same_orbits'] == 64
    assert orbit['covered_orbits'] == 64
    assert orbit['orbit_group_composition'] == {
        'Z1-U1,Z1-U1,Z1-U3,Z1-U3': 32,
        'Z1-U2,Z1-U2,Z1-U4,Z1-U4': 32,
    }, orbit['orbit_group_composition']
    assert z1['missing_true_z1_same_routes'] == []
    assert z1['layer_mapping_mismatches'] == []
    for row in rows:
        spec = C.MANUAL_GROUPS[row['delivered_manual_group']]
        assert int(row['target_layer']) == int(spec['layer'])
        assert row['manual_pattern'] == spec['pattern']
    if z1['prior_assignment_reference'].get('available') \
            and z1['user_640_csv_reference'].get('available'):
        assert z1['crosscheck_agreement'] is True
        assert z1['prior_vs_user_640_mismatches'] == []
    return '256/256 z1 same routes, 64 per group, 64 orbits, 32/32 numbering'


@_test('test_verified_csv_files_exist_and_match_schema')
def test_verified_csv_files_exist_and_match_schema():
    state = V.compute_all()
    expected_columns = V.CSV_COLUMNS
    checks = [
        (V.Z1_CSV, 256, 'z1', {'Z1-U1': 64, 'Z1-U2': 64,
                               'Z1-U3': 64, 'Z1-U4': 64}),
        (V.Z2_CSV, 112, 'z2', {'Z2-U1': 16, 'Z2-U2': 16,
                               'Z2-U3': 40, 'Z2-U4': 40}),
    ]
    detail = []
    for path, expected_rows, plane, expected_groups in checks:
        assert path.is_file(), path
        rows, _digest = C.read_csv_rows(path)
        assert len(rows) == expected_rows, (path.name, len(rows))
        assert list(rows[0].keys()) == expected_columns, path.name
        assert all(row['plane'] == plane for row in rows)
        counts = collections.Counter(row['manual_group'] for row in rows)
        assert dict(counts) == expected_groups, (path.name, counts)
        assert len({row['route_id'] for row in rows}) == expected_rows
        for row in rows:
            assert row['source_endpoint'] and row['target_endpoint']
            assert float(row['source_x_mm']) == float(row['source_x_mm'])
            assert float(row['target_y_mm']) == float(row['target_y_mm'])
        detail.append(f'{path.name}={len(rows)}')
    match_rows, _digest = C.read_csv_rows(V.MATCH_AUDIT_CSV)
    assert len(match_rows) == 112, 'match audit must have one row per Excel row'
    assert all(row['match_status'] == 'matched_unique'
               for row in match_rows)
    assert list(match_rows[0].keys()) == V.MATCH_AUDIT_COLUMNS
    unmatched, _d1 = C.read_csv_rows(V.UNMATCHED_CSV)
    conflicts, _d2 = C.read_csv_rows(V.CONFLICTS_CSV)
    assert unmatched == [], unmatched
    assert conflicts == [], conflicts
    assert V.Z1_AUDIT_CSV.is_file()
    return ', '.join(detail) + f', {len(match_rows)} audited, 0 unmatched, 0 conflicts'


@_test('test_assignment_invariants_1024')
def test_assignment_invariants_1024():
    state, rows, audit = _state()
    assert len(rows) == 1024, len(rows)
    ids = [int(row['route_id']) for row in rows]
    assert len(set(ids)) == 1024
    planes = collections.Counter(row['plane'] for row in rows)
    assert planes == {'z1': 512, 'z2': 512}, planes
    roles = collections.Counter(row['layer_role'] for row in rows)
    assert roles == {'z1_manual_u': 256, 'z2_manual_u': 112,
                     'z1_other': 256, 'z2_other': 400}, roles
    manual = collections.Counter(row['manual_group'] for row in rows
                                 if row['manual_group'])
    assert manual == {'Z1-U1': 64, 'Z1-U2': 64, 'Z1-U3': 64, 'Z1-U4': 64,
                      'Z2-U1': 16, 'Z2-U2': 16, 'Z2-U3': 40, 'Z2-U4': 40}
    manual_layers = {int(spec['layer']) for spec in C.MANUAL_GROUPS.values()}
    true_by_id = {int(route['route_id']): route for route in C.routes()}
    group_of = C.route_group_map()
    orbit_layers = collections.defaultdict(set)
    for row in rows:
        rid = int(row['route_id'])
        route = true_by_id[rid]
        assert (row['source_endpoint'], row['target_endpoint']) == (
            route['source_endpoint'], route['target_endpoint']), rid
        layer = int(row['target_layer'])
        target_z = float(C.PHYSICAL_LAYERS[layer])
        assert abs(float(row['target_z_mm']) - target_z) <= 1e-9, rid
        assert abs(float(row['interface_z_mm'])
                   - float(C.INTERFACE_Z[str(row['plane'])])) <= 1e-9, rid
        expected_direction = 'down' if target_z < row['interface_z_mm'] \
            else 'up'
        assert row['direction'] == expected_direction, rid
        if row['manual_group']:
            spec = C.MANUAL_GROUPS[row['manual_group']]
            assert layer == int(spec['layer']), rid
            assert row['manual_pattern'] == spec['pattern'], rid
            assert layer in manual_layers
        else:
            assert layer not in manual_layers, \
                f'non-manual route {rid} on manual layer {layer}'
            orbit_layers[int(row['c4_group_id'])].add(layer)
        assert int(row['rotation_phase']) in (0, 1, 2, 3)
        assert row['source_row'] != '' and row['target_row'] != ''
    for gid, layers in orbit_layers.items():
        assert len(layers) == 1, f'non-manual C4 orbit {gid} spans {layers}'
    by_layer = collections.Counter(int(row['target_layer']) for row in rows)
    expected_layer_counts = {
        2: 64, 3: 64, 4: 64, 5: 64, 6: 128, 7: 128, 8: 48, 9: 48,
        10: 16, 11: 16, 12: 40, 13: 40, 14: 48, 15: 52, 16: 52,
        17: 52, 18: 52, 19: 48,
    }
    assert dict(by_layer) == expected_layer_counts, dict(by_layer)
    orbit_by_layer = collections.defaultdict(set)
    for row in rows:
        orbit_by_layer[int(row['target_layer'])].add(int(row['c4_group_id']))
    expected_orbits = {
        2: 32, 3: 32, 4: 32, 5: 32, 6: 32, 7: 32, 8: 12, 9: 12,
        10: 8, 11: 8, 12: 20, 13: 20, 14: 12, 15: 13, 16: 13,
        17: 13, 18: 13, 19: 12,
    }
    for layer, expected in expected_orbits.items():
        assert len(orbit_by_layer[layer]) == expected, (layer,
                                                        len(orbit_by_layer[layer]))
    assert audit['all_invariants_passed'] is True, audit['invariant_failures']
    assert audit['invariant_failures'] == []
    return '1024 rows / 512-512 planes / 18 layers / 18 invariants'


@_test('test_assignment_matches_verified_manual_csvs')
def test_assignment_matches_verified_manual_csvs():
    state, rows, audit = _state()
    crosscheck = audit['verified_csv_crosscheck']
    assert crosscheck['z1']['consumed'] is True, crosscheck['z1']
    assert crosscheck['z2']['consumed'] is True, crosscheck['z2']
    assignment = {int(row['route_id']): row for row in rows}
    for path, role in ((V.Z1_CSV, 'z1_manual_u'), (V.Z2_CSV, 'z2_manual_u')):
        csv_rows, _digest = C.read_csv_rows(path)
        for csv_row in csv_rows:
            rid = int(csv_row['route_id'])
            row = assignment[rid]
            assert row['layer_role'] == role, rid
            assert row['manual_group'] == csv_row['manual_group'], rid
            assert int(row['target_layer']) == int(csv_row['target_layer']), rid
    return '256 + 112 manual rows match the verified CSVs exactly'


@_test('test_assignment_target_z_and_13_orbit_layers')
def test_assignment_target_z_and_13_orbit_layers():
    state, rows, audit = _state()
    orbit_counts = audit['physical_layer_orbit_counts']
    assert all(orbit_counts[str(layer)] == capacity
               for layer, capacity in A.Z2_ADJACENT_PLAN), orbit_counts
    thirteen = {layer for layer, capacity in A.Z2_ADJACENT_PLAN
                if capacity == 13}
    assert thirteen == {15, 16, 17, 18}, thirteen
    distances = {layer: abs(float(C.PHYSICAL_LAYERS[layer])
                            - C.Z2_INTERFACE_MM) for layer in thirteen}
    for layer in thirteen:
        for other, capacity in A.Z2_ADJACENT_PLAN:
            if other in thirteen:
                continue
            assert distances[layer] <= abs(float(C.PHYSICAL_LAYERS[other])
                                           - C.Z2_INTERFACE_MM) + 1e-12, (
                layer, other)
    assert all(orbit_counts[str(layer)] in (12, 13)
               for layer in (8, 9, 14, 15, 16, 17, 18, 19))
    return '13-orbit layers are exactly the four closest to z=0.5'


@_test('test_experiment_a_files_and_verdicts')
def test_experiment_a_files_and_verdicts():
    expected = ['input_counts.json', 'audit.json', 'manual_group_audit.csv',
                'assignment_layer_audit.csv', 'validation_status.json']
    for name in expected:
        path = A.EXPERIMENT_A / name
        assert path.is_file(), path
    validation = json.loads((A.EXPERIMENT_A / 'validation_status.json')
                            .read_text(encoding='utf-8'))
    assert validation['status'] == 'passed', validation['failed_checks']
    assert validation['checks_failed'] == 0
    assert validation['assignment_ready_for_stage_B'] is True
    assert validation['data_audit_verdict']['claim_112_confirmed'] is True
    audit = json.loads((A.EXPERIMENT_A / 'audit.json').read_text(encoding='utf-8'))
    questions = audit['data_audit_questions']
    assert len(questions) == 9, len(questions)
    by_id = {question['id']: question for question in questions}
    for name in ('Q1_excel_raw_rows', 'Q2_excel_rows_that_are_z1_data',
                 'Q3_z2_connections_satisfying_template',
                 'Q4_per_group_totals', 'Q5_duplicate_route_ids',
                 'Q6_routes_in_two_groups',
                 'Q7_template_pairs_without_real_route',
                 'Q8_coordinate_availability', 'Q9_claim_112_confirmed'):
        assert name in by_id, name
    assert by_id['Q1_excel_raw_rows']['evidence']['data_rows'] == 112
    assert by_id['Q4_per_group_totals']['evidence']['z2'] == {
        'Z2-U1': 16, 'Z2-U2': 16, 'Z2-U3': 40, 'Z2-U4': 40}
    assert by_id['Q9_claim_112_confirmed']['evidence']['confirmed'] is True
    manual = A.EXPERIMENT_A / 'manual_group_audit.csv'
    manual_rows, _digest = C.read_csv_rows(manual)
    assert len(manual_rows) == 8, len(manual_rows)
    layer_rows, _digest = C.read_csv_rows(
        A.EXPERIMENT_A / 'assignment_layer_audit.csv')
    assert len(layer_rows) == 18, len(layer_rows)
    return '5 files, 9 audit questions, validation passed'


@_test('test_summary_answers_all_required_questions')
def test_summary_answers_all_required_questions():
    state = V.compute_all()
    summary = state['summary']
    required = ['q1_excel_raw_rows', 'q2_excel_rows_that_are_z1_data',
                'q3_true_z2_connections_satisfying_manual_template',
                'q4_per_group_totals', 'q5_duplicate_route_ids',
                'q6_routes_in_two_groups',
                'q7_template_pairs_with_no_real_z2_route',
                'q8_coordinate_availability', 'claim_112_confirmed',
                'excel_rows_matched', 'unmatched_rows', 'conflict_rows',
                'z1_manual_u', 'orbit_structure']
    for key in required:
        assert key in summary, key
    assert summary['q1_excel_raw_rows'] == 112
    assert summary['claim_112_confirmed']['confirmed'] is True
    assert summary['claim_112_confirmed']['answer'].startswith('CONFIRMED')
    z1 = summary['z1_manual_u']
    assert z1['z1_manual_routes'] == 256
    assert z1['per_group_counts'] == {'Z1-U1': 64, 'Z1-U2': 64,
                                      'Z1-U3': 64, 'Z1-U4': 64}
    assert z1['all_routes_have_coordinates'] is True
    assert summary['previous_round_z2_csv_comparison']['present'] is True
    assert summary['previous_round_z2_csv_comparison'][
        'route_id_set_identical'] is True
    return 'summary answers Q1-Q8 + the 112 claim + Z1 truth'


@_test('test_artifacts_are_deterministic')
def test_artifacts_are_deterministic():
    state = V.compute_all(force=True)
    V.write_verified(state)
    deliverables = [V.EXCEL_AUDIT_JSON, V.Z1_CSV, V.Z2_CSV,
                    V.MATCH_AUDIT_CSV, V.UNMATCHED_CSV, V.CONFLICTS_CSV,
                    V.SUMMARY_JSON, V.Z1_AUDIT_CSV]
    first = {path.name: _sha256(path) for path in deliverables}
    rows_one = A.build_assignment(force=True)
    audit_one = A.build_audit(rows_one, state)
    A.write_assignment(rows_one, audit_one, state)
    assignment_files = [A.ASSIGNMENT_CSV, A.ASSIGNMENT_AUDIT_JSON,
                        A.STACK_JSON, A.RULES_JSON]
    assignment_files.extend(sorted(A.EXPERIMENT_A.iterdir()))
    first.update({path.name: _sha256(path) for path in assignment_files})
    # second, completely fresh regeneration through the entry points
    state2 = V.compute_all(force=True)
    V.write_verified(state2)
    rows_two = A.build_assignment(force=True)
    audit_two = A.build_audit(rows_two, state2)
    A.write_assignment(rows_two, audit_two, state2)
    second = {path.name: _sha256(path) for path in deliverables}
    second.update({path.name: _sha256(path) for path in assignment_files})
    differences = {name: (first[name], second[name]) for name in first
                   if first.get(name) != second.get(name)}
    assert not differences, differences
    assert rows_one == rows_two, 'assignment rows rebuilt differently'
    return f'{len(first)} deliverable files byte-identical after two runs'


@_test('test_assignment_columns_contract')
def test_assignment_columns_contract():
    design_columns = [
        'route_id', 'plane', 'relation', 'manual_group', 'manual_pattern',
        'target_layer', 'target_z_mm', 'interface_z_mm', 'direction',
        'layer_role', 'c4_group_id', 'rotation_phase', 'source_endpoint',
        'target_endpoint', 'source_side', 'target_side', 'source_connector',
        'target_connector', 'source_x_mm', 'source_y_mm', 'target_x_mm',
        'target_y_mm']
    assert A.ASSIGNMENT_COLUMNS[:len(design_columns)] == design_columns, \
        A.ASSIGNMENT_COLUMNS
    rows, _digest = C.read_csv_rows(A.ASSIGNMENT_CSV)
    assert len(rows) == 1024
    assert list(rows[0].keys()) == A.ASSIGNMENT_COLUMNS
    for key in ('route_id', 'target_layer', 'source_row', 'target_row'):
        int(float(rows[0][key]))
    for key in ('target_z_mm', 'interface_z_mm', 'source_x_mm',
                'source_y_mm', 'target_x_mm', 'target_y_mm'):
        float(rows[0][key])
    stack = json.loads(A.STACK_JSON.read_text(encoding='utf-8'))
    assert stack['schema'] == 'fanout_first_physical_layer_stack_v1'
    assert stack['route_count'] == 1024
    rules = json.loads(A.RULES_JSON.read_text(encoding='utf-8'))
    assert rules['schema'] == 'fanout_first_process_rules_v1'
    assert rules['min_layer_pitch_mm'] == 0.05
    assert rules['min_bend_radius_mm'] == 15.0
    return 'DESIGN 3.2 columns + stack/rules payloads verified'


def main(argv=None):
    print('=== fanout1024 data/assignment self-tests ===')
    tests = [
        test_excel_workbook_is_raw_z1_data,
        test_excel_route_id_is_not_authoritative,
        test_z2_matched_count_equals_true_z2_same_112_and_16_16_40_40,
        test_z2_match_has_no_duplicate_route_ids,
        test_z2_c4_orbit_structure,
        test_z2_template_grouping_matches_excel_groups,
        test_all_matched_endpoints_have_real_coordinates,
        test_z1_manual_u_verification,
        test_verified_csv_files_exist_and_match_schema,
        test_assignment_invariants_1024,
        test_assignment_matches_verified_manual_csvs,
        test_assignment_target_z_and_13_orbit_layers,
        test_experiment_a_files_and_verdicts,
        test_summary_answers_all_required_questions,
        test_artifacts_are_deterministic,
        test_assignment_columns_contract,
    ]
    for test in tests:
        test()
    print('-' * 60)
    print(f'TESTS: {len(PASSED)} passed, {len(FAILED)} failed '
          f'(of {len(tests)})')
    if FAILED:
        for name, error in FAILED:
            print(f'  FAILED {name}: {error}')
        return 1
    print('RESULT: ALL TESTS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
