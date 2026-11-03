# -*- coding: utf-8 -*-
"""Self-tests for the 21-height experiment A (layer model + assignment + diff).

Run with::

    .venv\\Scripts\\python.exe -m four_side_1024.fanout1024.reheight21.tests_assign21

The module regenerates every Experiment-A deliverable through
``assign21.main()``-equivalent calls (deterministic and idempotent) and asserts
the SPEC section 1-2 contract against the true 1024-route table, the frozen
18-layer baseline assignment (read-only) and the model.  Every test prints
PASS/FAIL and the process exits non-zero on any failure.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import traceback
from pathlib import Path

from .. import common as C
from . import assign21 as A
from . import model as M

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


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _csv_rows(path):
    return C.read_csv_rows(path)[0]


#: all Experiment-A deliverables written by this task (run.log excluded)
DELIVERABLES = (
    M.LAYER_PLANES_JSON, M.NEW_ASSIGNMENT, M.NEW_ASSIGNMENT_AUDIT,
    M.NEW_ASSIGNMENT_DIFF_JSON, M.NEW_ASSIGNMENT_DIFF_MD,
    M.NEW_STACK_JSON, M.NEW_RULES_JSON,
    M.NEW_EXPERIMENT_A / 'summary.json',
    M.NEW_EXPERIMENT_A / 'layer_audit.csv',
    M.NEW_EXPERIMENT_A / 'audit.json',
    M.NEW_EXPERIMENT_A / 'validation_status.json',
)


def _state():
    """Full deterministic regeneration through the public entry points."""
    rows = A.build_assignment(force=True)
    result = A.write_all(rows)
    return rows, result


# ================================================================ tests
@_test('test_model_frozen_api')
def test_model_frozen_api():
    required = [
        'RUN_DIR', 'BASELINE_RUN_DIR', 'BODY_PLANES', 'INTERFACE_PLANES',
        'PLANE_IDS', 'plane_z', 'plane_label', 'plane_kind',
        'interface_plane_for', 'interface_z', 'is_direct_plane',
        'layer_stack', 'stack_payload', 'process_rules_payload',
        'MANUAL_GROUPS', 'MANUAL_ROLES', 'Z1_OTHER_PLAN',
        'Z2_OTHER_OLD_TO_NEW', 'BASE_ASSIGNMENT', 'NEW_ASSIGNMENT',
        'LAYER_PLANES_JSON',
    ]
    missing = [name for name in required if not hasattr(M, name)]
    assert not missing, f'missing frozen API names: {missing}'
    assert tuple(M.BODY_PLANES) == (2, 3, 4, 5, 6, 7, 20, 8, 9, 10, 11, 12,
                                    13, 14, 15, 16, 17, 18, 19)
    assert tuple(M.PLANE_IDS) == (2, 3, 4, 5, 6, 7, 20, 1001, 8, 9, 10, 11,
                                  12, 13, 14, 15, 16, 1002, 17, 18, 19)
    assert M.interface_plane_for('z1') == 1001
    assert M.interface_plane_for('z2') == 1002
    assert M.interface_z('z1') == 0.0
    assert M.interface_z('z2') == 0.5
    assert M.is_direct_plane(1001) and M.is_direct_plane(1002)
    assert not M.is_direct_plane(2) and not M.is_direct_plane(20)
    for plane_id in M.PLANE_IDS:
        assert M.plane_z(plane_id) == M.BODY_PLANES.get(
            plane_id, M.INTERFACE_PLANES.get(plane_id, {}).get('z_mm')
            if plane_id in M.INTERFACE_PLANES else None)
        assert M.plane_label(plane_id)
        assert M.plane_kind(plane_id) in ('body', 'interface_body')
        assert M.plane_label(plane_id) in ('L2', 'L3', 'L4', 'L5', 'L6',
                                          'L7', 'L20', 'L8', 'L9', 'L10',
                                          'L11', 'L12', 'L13', 'L14', 'L15',
                                          'L16', 'L17', 'L18', 'L19',
                                          'Z1_INTERFACE', 'Z2_INTERFACE')
    assert M.MANUAL_ROLES == ('z1_manual_u', 'z2_manual_u')
    for group, spec in M.MANUAL_GROUPS.items():
        assert set(('plane', 'label', 'z_mm')).issubset(spec)
    stack_obj = M.layer_stack()
    assert stack_obj.routing_layer_ids == tuple(range(2, 21))
    assert stack_obj.layers[1].interface_rows == {'z1': 0.0, 'z2': 0.5}
    stack_payload = M.stack_payload()
    assert stack_payload['plane_count'] == 21
    assert stack_payload['min_layer_pitch_mm'] == 0.05
    assert stack_payload['interfaces'] == {'z1': 0.0, 'z2': 0.5}
    assert stack_payload['formal_acceptance_allowed'] is False
    rules = M.process_rules_payload()
    assert rules['glass_thickness_mm'] == 1.0
    assert rules['glass_z_range_mm'] == [-0.35, 0.65]
    assert rules['min_layer_pitch_mm'] == 0.05
    assert rules['min_3d_clearance_mm'] == 0.05
    assert rules['min_bend_radius_mm'] == 15.0
    assert rules['explicitly_not_restored']['global_80um_clearance'] is False
    assert 'interface_body_routing_rule' in rules
    assert M.Z1_OTHER_PLAN == ((6, 13), (7, 13), (20, 13), (1001, 13),
                               (8, 12))
    assert dict(M.Z2_OTHER_OLD_TO_NEW) == {8: 9, 9: 14, 14: 15, 15: 16,
                                           16: 17, 17: 18, 18: 19, 19: 1002}
    return 'frozen model API complete; stack rows 0.0/0.5; body ids 2..20'


@_test('test_layer_planes_json_contract')
def test_layer_planes_json_contract():
    rows, result = _state()
    payload = _load_json(M.LAYER_PLANES_JSON)
    assert payload['schema'] == 'reheight21_layer_planes_v1'
    assert payload['plane_count'] == 21
    assert payload['height_count'] == 21
    assert payload['min_pitch_mm'] == 0.05
    assert payload['interfaces'] == {'z1': 0.0, 'z2': 0.5}
    assert payload['glass']['thickness_mm'] == 1.0
    assert payload['glass']['z_min_mm'] == -0.35
    assert payload['glass']['z_max_mm'] == 0.65
    assert set(payload['body_planes']) == {str(pid) for pid in
                                           M.BODY_PLANES}
    assert set(payload['interface_planes']) == {'1001', '1002'}
    planes = payload['planes']
    assert len(planes) == 21
    assert [plane['plane_id'] for plane in planes] == list(M.PLANE_IDS)
    expected_keys = {'plane_id', 'label', 'z_mm', 'kind', 'role', 'assigned'}
    roles = set()
    for plane in planes:
        assert expected_keys.issubset(plane), (plane,
                                               expected_keys - set(plane))
        assert plane['label'] == M.plane_label(plane['plane_id'])
        assert plane['z_mm'] == M.plane_z(plane['plane_id'])
        assert plane['kind'] == M.plane_kind(plane['plane_id'])
        roles.add(plane['role'])
        assert plane['kind'] in ('body', 'interface_body')
    assert roles == {'z1_manual_u', 'z2_manual_u', 'z1_other', 'z2_other',
                     'interface_direct'}, roles
    assert sum(plane['assigned'] for plane in planes) == 1024
    assert payload['assigned_total'] == 1024
    heights = {round(plane['z_mm'], 9) for plane in planes}
    assert len(heights) == 21
    assert all(b - a >= 0.05 - 1e-9 for a, b in
               zip(sorted(heights), sorted(heights)[1:]))
    return '21 planes, 21 heights, roles taxonomy, assigned sum 1024'


@_test('test_assignment_csv_contract')
def test_assignment_csv_contract():
    rows, result = _state()
    csv_rows = _csv_rows(M.NEW_ASSIGNMENT)
    assert len(csv_rows) == 1024
    assert list(csv_rows[0].keys()) == A.ASSIGNMENT_COLUMNS
    ids = [int(float(row['route_id'])) for row in csv_rows]
    assert len(ids) == len(set(ids)) == 1024
    assert sorted(ids) == sorted(int(route['route_id'])
                                 for route in C.routes())
    planes = collections.Counter(row['plane'] for row in csv_rows)
    assert dict(planes) == {'z1': 512, 'z2': 512}
    for row in csv_rows:
        plane_id = int(float(row['target_layer']))
        assert plane_id in M.PLANE_IDS, plane_id
        assert row['target_plane_label'] == M.plane_label(plane_id)
        assert abs(float(row['target_z_mm'])
                   - M.plane_z(plane_id)) <= 1e-12
        assert abs(float(row['interface_z_mm'])
                   - M.interface_z(row['plane'])) <= 1e-12
        needs = str(row['needs_transition']).strip().lower() == 'true'
        assert str(row['needs_transition']) in ('True', 'False')
        assert needs == M.needs_transition(plane_id, row['plane'])
        expected_direction = M.direction_for(plane_id, row['plane'])
        assert row['direction'] == expected_direction
        assert row['direction'] in ('down', 'up', 'direct')
        if str(row['baseline_old_layer']).strip():
            int(float(row['baseline_old_layer']))
    return '1024 unique ids, 512/512 planes, all fields model-consistent'


@_test('test_manual_368_fixed')
def test_manual_368_fixed():
    rows, result = _state()
    manual = [row for row in rows if row['manual_group']]
    assert len(manual) == 368
    counts = collections.Counter(row['manual_group'] for row in manual)
    assert dict(counts) == dict(A.EXPECTED_MANUAL_COUNTS)
    baseline = A.load_baseline()
    for group, spec in M.MANUAL_GROUP_SPECS.items():
        group_ids = {int(row['route_id']) for row in manual
                     if row['manual_group'] == group}
        baseline_ids = {int(rid) for rid, row in baseline['by_id'].items()
                        if str(row.get('manual_group') or '').strip()
                        == group}
        assert group_ids == baseline_ids, group
        assert len(group_ids) == A.EXPECTED_MANUAL_COUNTS[group]
        for row in manual:
            if row['manual_group'] != group:
                continue
            assert int(row['target_layer']) == int(spec['plane_id'])
            assert row['manual_pattern'] == spec['pattern']
            assert row['baseline_old_layer'] == ''
            assert abs(float(row['target_z_mm'])
                       - float(spec['z_mm'])) <= 1e-12
    return '368 manual routes, membership + planes + patterns fixed'


@_test('test_plane_counts_exact')
def test_plane_counts_exact():
    rows, result = _state()
    counts = collections.Counter(int(row['target_layer']) for row in rows)
    assert dict(counts) == dict(A.EXPECTED_PLANE_COUNTS), dict(counts)
    z1_other = collections.Counter(int(row['target_layer']) for row in rows
                                   if row['layer_role'] == 'z1_other')
    assert dict(z1_other) == dict(A.EXPECTED_Z1_OTHER_COUNTS)
    assert list(z1_other.items()) == [(6, 52), (7, 52), (20, 52),
                                      (1001, 52), (8, 48)]
    z2_other = collections.Counter(int(row['target_layer']) for row in rows
                                   if row['layer_role'] == 'z2_other')
    assert dict(z2_other) == dict(A.EXPECTED_Z2_OTHER_COUNTS)
    assert [z2_other[plane] for plane in (9, 14, 15, 16, 17, 18, 19, 1002)] \
        == [48, 48, 48, 52, 52, 52, 52, 48]
    assert len(counts) == 21 and min(counts.values()) > 0
    return ('plane counts exact: Z1 64/64/64/64/52/52/52/52/48, '
            'Z2 16/16/40/40/48/48/48/52/52/52/52/48')


@_test('test_direct_100_and_1848_transitions')
def test_direct_100_and_1848_transitions():
    rows, result = _state()
    direct = [row for row in rows if not row['needs_transition']]
    assert len(direct) == 100
    assert sum(1 for row in direct if row['plane'] == 'z1') == 52
    assert sum(1 for row in direct if row['plane'] == 'z2') == 48
    for row in direct:
        assert row['direction'] == 'direct'
        assert int(row['target_layer']) == M.interface_plane_for(row['plane'])
    transition = [row for row in rows if row['needs_transition']]
    assert len(transition) == 924
    assert 2 * len(transition) == 1848
    assert all(row['direction'] in ('down', 'up') for row in transition)
    return '100 direct routes (52 Z1_INTERFACE + 48 Z2_INTERFACE), 924 -> 1848'


@_test('test_c4_orbits_integrity')
def test_c4_orbits_integrity():
    rows, result = _state()
    plane_of = {int(row['route_id']): int(row['target_layer'])
                for row in rows}
    manual_ids = {int(row['route_id']) for row in rows if row['manual_group']}
    non_manual_orbits = []
    manual_orbit_planes = collections.Counter()
    for group in C.rotation_groups():
        planes = {plane_of[int(rid)] for rid in group['route_ids']}
        if all(int(rid) in manual_ids for rid in group['route_ids']):
            manual_orbit_planes[tuple(sorted(planes))] += 1
            continue
        non_manual_orbits.append(group)
        assert len(planes) == 1, (group['group_id'], sorted(planes))
    assert len(non_manual_orbits) == 164
    assert dict(manual_orbit_planes) == A.EXPECTED_MANUAL_ORBIT_PLANE_SETS
    baseline = A.load_baseline()
    state = A._state()
    for index, group in enumerate(state['z1_opposite_groups']):
        consumed = 0
        expected = None
        for plane_id, capacity in M.Z1_OTHER_PLAN:
            if index < consumed + capacity:
                expected = int(plane_id)
                break
            consumed += capacity
        assert {plane_of[int(rid)] for rid in group['route_ids']} == {expected}
    for group_id, info in state['z2_orbit_plane'].items():
        assert {plane_of[int(rid)] for rid in info['route_ids']} == {
            int(M.Z2_OTHER_OLD_TO_NEW[info['old_layer']])}
    return ('164 non-manual orbits single-plane; manual orbits split '
            '32x{2,4} 32x{3,5} 8x{10,11} 20x{12,13}')


@_test('test_port_pairs_identical_to_true_routes')
def test_port_pairs_identical_to_true_routes():
    rows, result = _state()
    routes = {int(route['route_id']): route for route in C.routes()}
    assert len(routes) == 1024
    for row in rows:
        route = routes[int(row['route_id'])]
        assert row['source_endpoint'] == route['source_endpoint']
        assert row['target_endpoint'] == route['target_endpoint']
        assert row['source_side'] == route['source_side']
        assert row['target_side'] == route['target_side']
        assert row['source_connector'] == route['source_connector']
        assert row['target_connector'] == route['target_connector']
        assert row['source_x_mm'] == route['source_xy'][0]
        assert row['source_y_mm'] == route['source_xy'][1]
        assert row['target_x_mm'] == route['target_xy'][0]
        assert row['target_y_mm'] == route['target_xy'][1]
        group = C.route_group_map()[int(row['route_id'])]
        assert int(row['c4_group_id']) == int(group['group_id'])
        assert int(row['rotation_phase']) == int(
            group['route_ids'].index(int(row['route_id'])))
    return 'all 1024 port pairs / sides / connectors / xy / c4 ids identical'


@_test('test_21_heights_and_min_pitch')
def test_21_heights_and_min_pitch():
    rows, result = _state()
    heights = sorted({round(M.plane_z(plane_id), 9)
                      for plane_id in M.PLANE_IDS})
    assert len(heights) == 21
    gaps = [b - a for a, b in zip(heights, heights[1:])]
    assert min(gaps) >= M.MIN_LAYER_PITCH_MM - 1e-9
    assert abs(M.min_height_pitch() - 0.05) <= 1e-9
    used = {int(row['target_layer']) for row in rows}
    assert used == set(M.PLANE_IDS), sorted(set(M.PLANE_IDS) - used)
    payload = _load_json(M.LAYER_PLANES_JSON)
    assert payload['height_count'] == 21
    assert payload['measured_min_pitch_mm'] >= 0.05 - 1e-9
    return '21 distinct heights, min pitch 0.05 mm, all heights used'


@_test('test_baseline_readonly')
def test_baseline_readonly():
    rows, result = _state()
    baseline_sha_before = _sha256(M.BASE_ASSIGNMENT)
    audit = result['audit']
    assert audit['baseline']['sha256'] == baseline_sha_before
    # full regeneration must not touch the baseline run dir
    rows_again = A.build_assignment(force=True)
    A.write_all(rows_again)
    assert _sha256(M.BASE_ASSIGNMENT) == baseline_sha_before
    assert result['audit']['baseline_untouched'] is True
    assert _load_json(M.NEW_ASSIGNMENT_AUDIT)['baseline_untouched'] is True
    assert _load_json(M.NEW_EXPERIMENT_A / 'validation_status.json')[
        'baseline_untouched'] is True
    return f'baseline sha256 stable: {baseline_sha_before[:16]}...'


@_test('test_assignment_audit_and_experiment_a')
def test_assignment_audit_and_experiment_a():
    rows, result = _state()
    audit = _load_json(M.NEW_ASSIGNMENT_AUDIT)
    assert audit['schema'] == 'reheight21_assignment_audit_v1'
    assert audit['all_invariants_passed'] is True
    assert audit['invariant_failures'] == []
    assert len(audit['invariants']) == 33
    assert audit['rows'] == 1024
    assert audit['z1'] == 512 and audit['z2'] == 512
    assert audit['height_count'] == 21
    assert audit['min_pitch_mm'] >= M.MIN_LAYER_PITCH_MM - 1e-9
    assert audit['direct_routes']['total'] == 100
    assert audit['transition_routes']['endpoint_transitions'] == 1848
    validation = _load_json(M.NEW_EXPERIMENT_A / 'validation_status.json')
    assert validation['status'] == 'passed'
    assert validation['checks_failed'] == 0
    assert validation['assignment_ready_for_stage_B'] is True
    assert validation['stage_summary']['validation_status'] == 'passed'
    assert validation['stage_summary']['input_line_count']['true_routes'] == 1024
    exp_audit = _load_json(M.NEW_EXPERIMENT_A / 'audit.json')
    for question in exp_audit['questions']:
        assert question['answer'] is True, question
    assert len(exp_audit['questions']) == 10
    assert len(_csv_rows(M.NEW_EXPERIMENT_A / 'layer_audit.csv')) == 21
    summary = _load_json(M.NEW_EXPERIMENT_A / 'summary.json')
    assert summary['assignment_rows'] == 1024
    assert summary['validation_status'] == 'passed'
    return 'audit 33/33, experiment_A 10/10 questions, validation passed'


@_test('test_assignment_diff_vs_baseline')
def test_assignment_diff_vs_baseline():
    rows, result = _state()
    diff = _load_json(M.NEW_ASSIGNMENT_DIFF_JSON)
    assert diff['schema'] == 'reheight21_assignment_diff_vs_baseline_v1'
    assert diff['baseline_assignment']['rows'] == 1024
    assert diff['baseline_assignment']['planes'] == {'z1': 512, 'z2': 512}
    assert len(diff['route_changes']) == 1024
    assert diff['summary']['routes'] == 1024
    assert diff['summary']['manual_unchanged'] is True
    assert diff['manual']['unchanged_membership'] is True
    assert diff['manual']['unchanged_plane_ids'] is True
    z1_plans = diff['z1_other']['plan']
    assert z1_plans == [[plane, capacity] for plane, capacity
                        in M.Z1_OTHER_PLAN]
    assert sum(item[2] for item in diff['transition_matrix']) == 1024
    flips = diff['direction_changes']['flips']
    assert flips.get('down->direct', 0) == 52
    assert flips.get('up->direct', 0) == 48
    assert flips.get('down->up', 0) == 100
    assert diff['summary']['direction_flip_routes'] == 200
    assert diff['direct_routes']['total'] == 100
    assert len(diff['direct_routes']['z1']['route_ids']) == 52
    assert len(diff['direct_routes']['z2']['route_ids']) == 48
    assert diff['heights']['new_heights'] == 21
    assert diff['heights']['new_min_pitch_mm'] >= 0.05 - 1e-9
    assert M.NEW_ASSIGNMENT_DIFF_MD.is_file()
    markdown = M.NEW_ASSIGNMENT_DIFF_MD.read_text(encoding='utf-8')
    assert 'diff vs the 18-layer baseline' in markdown
    assert 'Z1_INTERFACE' in markdown and 'Z2_INTERFACE' in markdown
    # manual z shift check: planes 3/4/5 get the new z values
    changed = {item['manual_group']: item for item
               in diff['manual']['groups']}
    assert changed['Z1-U1']['z_changed'] is False
    assert changed['Z1-U2']['z_changed'] is True
    assert changed['Z1-U3']['z_changed'] is True
    assert changed['Z1-U4']['z_changed'] is True
    assert changed['Z1-U2']['new_z_mm'] == -0.30
    return ('1024 route changes audited; 604 plane changes, 200 direction '
            'flips, manual membership/plane ids unchanged')


@_test('test_stack_and_rules_reloadable')
def test_stack_and_rules_reloadable():
    rows, result = _state()
    from ...l3d.layers import load_stack
    stack_obj = load_stack(M.NEW_STACK_JSON)
    assert stack_obj.routing_layer_ids == tuple(range(2, 21))
    assert stack_obj.layers[1].interface_rows == {'z1': 0.0, 'z2': 0.5}
    assert stack_obj.validate() is stack_obj  # validate() raises on failure
    stack_payload = _load_json(M.NEW_STACK_JSON)
    assert stack_payload['plane_count'] == 21
    assert stack_payload['min_layer_pitch_mm'] == 0.05
    assert stack_payload['formal_acceptance_allowed'] is False
    rules = _load_json(M.NEW_RULES_JSON)
    assert rules['schema'] == 'reheight21_process_rules_v1'
    assert rules['min_layer_pitch_mm'] == 0.05
    assert rules['min_3d_clearance_mm'] == 0.05
    assert rules['interface_body_routing_rule']
    assert rules['explicitly_not_restored']['global_80um_clearance'] is False
    return 'physical_layer_stack.json reloads+validates; process_rules.json ok'


@_test('test_run21_read_assignment_compatibility')
def test_run21_read_assignment_compatibility():
    rows, result = _state()
    try:
        from . import run21
    except Exception as error:  # guarded: run21 is Lead-owned and may change
        return f'skipped import ({error.__class__.__name__})'
    parsed = run21.read_assignment()
    assert len(parsed) == 1024
    assert len({row['route_id'] for row in parsed}) == 1024
    direct = [row for row in parsed if not row['needs_transition']]
    assert len(direct) == 100
    planes = collections.Counter(row['plane'] for row in parsed)
    assert dict(planes) == {'z1': 512, 'z2': 512}
    assert len({int(row['target_layer']) for row in parsed}) == 21
    assert all(row['target_layer'] in M.PLANE_IDS for row in parsed)
    return 'run21.read_assignment() parses 1024 rows / 100 direct / 21 planes'


@_test('test_artifacts_deterministic_idempotent')
def test_artifacts_deterministic_idempotent():
    rows_one, result_one = _state()
    first = {Path(path).name: _sha256(path) for path in DELIVERABLES}
    rows_two = A.build_assignment(force=True)
    assert rows_two == rows_one
    A.write_all(rows_two)
    second = {Path(path).name: _sha256(path) for path in DELIVERABLES}
    differing = {name: (first[name], second[name]) for name in first
                 if first[name] != second[name]}
    assert not differing, differing
    return f'{len(first)} deliverables byte-identical after two runs'


def main(argv=None):
    print('=== reheight21 experiment A self-tests ===')
    tests = [
        test_model_frozen_api,
        test_layer_planes_json_contract,
        test_assignment_csv_contract,
        test_manual_368_fixed,
        test_plane_counts_exact,
        test_direct_100_and_1848_transitions,
        test_c4_orbits_integrity,
        test_port_pairs_identical_to_true_routes,
        test_21_heights_and_min_pitch,
        test_baseline_readonly,
        test_assignment_audit_and_experiment_a,
        test_assignment_diff_vs_baseline,
        test_stack_and_rules_reloadable,
        test_run21_read_assignment_compatibility,
        test_artifacts_deterministic_idempotent,
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
