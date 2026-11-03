# -*- coding: utf-8 -*-
"""Unit tests for the 21-height independent validator (validate21.py).

Run with the project venv from the project root::

    .venv\\Scripts\\python.exe four_side_1024/fanout1024/reheight21/tests_validate21.py

or with pytest::

    .venv\\Scripts\\python.exe -m pytest four_side_1024/fanout1024/reheight21/tests_validate21.py

The tests use synthetic geometry only (no real RUN_DIR artifact is required),
except that the frozen true port table / true route table are read from
``fanout1024.common`` for identity helpers.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from four_side_1024.fsd25d import path3d as P  # noqa: E402
from four_side_1024.fanout1024 import common  # noqa: E402
from four_side_1024.fanout1024.reheight21 import validate21 as V  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic geometry helpers
# ---------------------------------------------------------------------------
def _line(p0, p1):
    return dict(kind='line', p0=[float(p0[0]), float(p0[1])],
                p1=[float(p1[0]), float(p1[1])])


def _flat_part(layer_id, z_mm, primitives):
    primitives = [dict(prim) for prim in primitives]
    return dict(kind='flat', layer_id=int(layer_id), z_mm=float(z_mm),
                length_mm=float(P.path_length(primitives)),
                primitives=primitives)


def _transition_part(start_xy, direction, z0, z1):
    part = P.make_transition(start_xy, direction, z0, z1, radius=15.0)
    part['kind'] = 'transition'
    return part


def _endpoint(xy, inward, plane='z1', z_mm=0.0):
    return dict(endpoint_id='SYN', routing_xy=[float(xy[0]), float(xy[1])],
                inward=[float(inward[0]), float(inward[1])],
                plane=plane, z_mm=float(z_mm))


def _synthetic_direct_route(route_id=1, source=(10.0, 10.0),
                            target=(20.0, 10.0), z=0.0, plane='z1',
                            layer_id=1001, n_transitions=0):
    """Horizontal direct body: start heading +x, target inward -x."""
    body = _flat_part(layer_id, z, [_line(source, target)])
    return dict(route_id=int(route_id), plane=plane,
                source_endpoint='SRC', target_endpoint='TGT',
                start_z_mm=float(z), end_z_mm=float(z),
                n_transitions=int(n_transitions), lifted=False,
                z_span_mm=0.0, layer_sequence=[int(layer_id)],
                layer_z_sequence=[float(z)], layers_used=[int(layer_id)],
                target_layer=int(layer_id), target_z_mm=float(z),
                target_plane=int(layer_id), needs_transition=False,
                length_mm=float(P.path_length(body['primitives'])),
                parts=[body])


def _synthetic_non_direct_route(route_id=2, interface_z=0.0,
                                target_plane=3, target_z=-0.30,
                                lead=1.0, radius=15.0):
    """Five-part route P_s -> lead -> S(z0->zt) -> body -> S(zt->z0) -> lead -> P_t."""
    source = (10.0, 10.0)
    target = (50.0, 10.0)
    d_s = (1.0, 0.0)
    d_t = (-1.0, 0.0)
    q_s = (source[0] + lead * d_s[0], source[1] + lead * d_s[1])
    q_t = (target[0] + lead * d_t[0], target[1] + lead * d_t[1])
    up = _transition_part(q_s, d_s, interface_z, target_z)
    footprint = float(up['footprint_mm'])
    a = (q_s[0] + d_s[0] * footprint, q_s[1] + d_s[1] * footprint)
    b = (q_t[0] + d_t[0] * footprint, q_t[1] + d_t[1] * footprint)
    down = _transition_part(b, (1.0, 0.0), target_z, interface_z)
    lead_s = _flat_part(1, interface_z, [_line(source, q_s)])
    body = _flat_part(target_plane, target_z, [_line(a, b)])
    lead_t = _flat_part(1, interface_z, [_line(q_t, target)])
    parts = [lead_s, up, body, down, lead_t]
    transition_length = float(up['length_mm']) + float(down['length_mm'])
    flat_length = (float(P.path_length(lead_s['primitives']))
                   + float(P.path_length(body['primitives']))
                   + float(P.path_length(lead_t['primitives'])))
    xy_length = flat_length + 2.0 * footprint
    return dict(
        route_id=int(route_id), plane='z1',
        source_endpoint='SRC', target_endpoint='TGT',
        start_z_mm=float(interface_z), end_z_mm=float(interface_z),
        n_transitions=2, lifted=True,
        z_span_mm=abs(target_z - interface_z),
        layer_sequence=[1, int(target_plane), 1],
        layer_z_sequence=[float(interface_z), float(target_z), float(interface_z)],
        layers_used=[1, int(target_plane)],
        target_layer=int(target_plane), target_z_mm=float(target_z),
        target_plane=int(target_plane), needs_transition=True,
        length_mm=flat_length + transition_length,
        xy_length_mm=xy_length,
        parts=parts,
        lead_source_mm=lead, lead_target_mm=lead,
    )


ENDPOINTS = {
    'SRC': _endpoint((10.0, 10.0), (1.0, 0.0)),
    'TGT': _endpoint((20.0, 10.0), (-1.0, 0.0)),
}
NON_DIRECT_ENDPOINTS = {
    'SRC': _endpoint((10.0, 10.0), (1.0, 0.0)),
    'TGT': _endpoint((50.0, 10.0), (-1.0, 0.0)),
}


# ---------------------------------------------------------------------------
# model / layer_planes
# ---------------------------------------------------------------------------
class TestModel(unittest.TestCase):
    def test_spec_model_21_planes(self):
        planes = V._spec_model()
        self.assertEqual(len(planes), 21)
        details = V.check_model(planes, 'spec')[1]
        self.assertEqual(details['plane_count'], 21)
        self.assertEqual(details['body_plane_count'], 19)
        self.assertEqual(details['interface_plane_count'], 2)
        self.assertEqual(planes[20]['z_mm'], -0.05)
        # id 20 is NOT monotone with z: its height is below the id-19 plane
        self.assertLess(planes[20]['z_mm'], planes[19]['z_mm'])
        self.assertGreater(planes[20]['z_mm'], planes[7]['z_mm'])
        self.assertEqual(planes[1001]['z_mm'], 0.0)
        self.assertEqual(planes[1002]['z_mm'], 0.5)
        self.assertAlmostEqual(details['min_pitch_mm'], 0.05, places=9)

    def test_check_model_accepts_spec(self):
        violations, _details = V.check_model(V._spec_model(), 'spec')
        self.assertEqual(violations, [])

    def test_check_model_rejects_wrong_z(self):
        planes = V._spec_model()
        planes[3]['z_mm'] = -0.29
        violations, _details = V.check_model(planes, 'spec')
        kinds = {item['kind'] for item in violations}
        self.assertIn('model_plane_z_mismatch', kinds)

    def test_check_model_rejects_pitch(self):
        planes = V._spec_model()
        planes[3]['z_mm'] = planes[2]['z_mm'] + 0.049
        violations, details = V.check_model(planes, 'spec')
        kinds = {item['kind'] for item in violations}
        self.assertIn('min_plane_pitch_below_50um', kinds)
        self.assertLess(details['min_pitch_mm'], 0.05)

    def test_derive_baseline_model_18_planes(self):
        planes = V.derive_baseline_model()
        self.assertEqual(len(planes), 18)
        self.assertAlmostEqual(planes[2]['z_mm'], -0.35)
        self.assertAlmostEqual(planes[19]['z_mm'], 0.65)
        body_z = sorted(plane['z_mm'] for plane in planes.values())
        gaps = [high - low for low, high in zip(body_z, body_z[1:])]
        self.assertGreaterEqual(min(gaps), 0.05 - 1e-9)

    def test_layer_planes_loader_list_and_dict_schema(self):
        spec = V._spec_model()
        list_payload = dict(
            schema='reheight21_layer_planes_v1',
            planes=[dict(plane_id=plane['plane_id'], label=plane['label'],
                         z_mm=plane['z_mm'], kind=plane['kind'],
                         interface=plane['interface'])
                    for plane in spec.values()])
        dict_payload = dict(planes={
            str(plane['plane_id']): dict(id=plane['plane_id'],
                                         z=plane['z_mm'],
                                         kind=plane['kind'],
                                         label=plane['label'],
                                         interface=plane['interface'])
            for plane in spec.values()})
        with tempfile.TemporaryDirectory() as directory:
            for payload in (list_payload, dict_payload):
                path = Path(directory) / 'layer_planes.json'
                path.write_text(json.dumps(payload), encoding='utf-8')
                planes, source = V.load_layer_planes(path)
                self.assertEqual(source, 'layer_planes.json')
                self.assertEqual(len(planes), 21)
                for plane_id, plane in spec.items():
                    self.assertAlmostEqual(planes[plane_id]['z_mm'],
                                           plane['z_mm'], places=9)

    def test_layer_planes_missing(self):
        planes, source = V.load_layer_planes(Path('does_not_exist_21h.json'))
        self.assertIsNone(planes)
        self.assertEqual(source, 'missing')


# ---------------------------------------------------------------------------
# direct (interface-body) routes
# ---------------------------------------------------------------------------
class TestDirectRoutes(unittest.TestCase):
    def _check(self, record, endpoints=None):
        violations = []
        V.check_direct_route(record, {}, V._spec_model(),
                             endpoints or ENDPOINTS, violations)
        return violations

    def test_valid_direct_route(self):
        record = _synthetic_direct_route()
        self.assertEqual(self._check(record), [])

    def test_wrong_interface_plane_layer(self):
        record = _synthetic_direct_route(layer_id=1002)
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('direct_route_wrong_interface_plane', kinds)

    def test_transition_part_forbidden(self):
        record = _synthetic_direct_route()
        record['parts'].append(_transition_part((20.0, 10.0), (1.0, 0.0),
                                                0.0, -0.30))
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('direct_route_parts_not_single_flat', kinds)

    def test_n_transitions_must_be_zero(self):
        record = _synthetic_direct_route(n_transitions=2)
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('direct_route_n_transitions_not_zero', kinds)

    def test_wrong_z(self):
        record = _synthetic_direct_route(z=0.5)
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('direct_route_wrong_interface_z', kinds)

    def test_wrong_heading(self):
        record = _synthetic_direct_route()
        endpoints = dict(ENDPOINTS)
        endpoints['SRC'] = _endpoint((10.0, 10.0), (-1.0, 0.0))
        kinds = {item['kind'] for item in self._check(record, endpoints)}
        self.assertIn('direct_route_start_heading_mismatch', kinds)

    def test_arc_radius_check_catches_non_r15(self):
        arc = dict(kind='arc', p0=[10.0, 10.0], p1=[10.0, 5.0],
                   center=[10.0, 5.0], radius=14.0, start_angle=math.pi / 2,
                   sweep=-math.pi / 2)
        part = _flat_part(1001, 0.0, [arc])
        record = dict(route_id=3, plane='z1', n_transitions=0, lifted=False,
                      z_span_mm=0.0, parts=[part])
        violations = []
        details = V.check_radius(record, violations)
        kinds = {item['kind'] for item in violations}
        self.assertIn('flat_arc_radius_not_r15', kinds)
        self.assertEqual(details['flat_arc_count'], 1)


# ---------------------------------------------------------------------------
# non-direct routes
# ---------------------------------------------------------------------------
class TestNonDirectRoutes(unittest.TestCase):
    def _check(self, record, interface_ids=None):
        violations = []
        model = V._spec_model()
        row = dict(target_layer=record['target_layer'],
                   target_z_mm=record['target_z_mm'],
                   needs_transition=True, plane='z1')
        V.check_non_direct_route(record, row, model, V.plane_z_map(model),
                                 interface_ids or {1001, 1002, 1},
                                 NON_DIRECT_ENDPOINTS, violations)
        return violations

    def test_valid_non_direct_route(self):
        record = _synthetic_non_direct_route()
        self.assertEqual(self._check(record), [])

    def test_body_wrong_plane(self):
        record = _synthetic_non_direct_route()
        record['parts'][2] = _flat_part(4, -0.30,
                                        record['parts'][2]['primitives'])
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('body_layer_mismatch_assignment', kinds)

    def test_body_wrong_z(self):
        record = _synthetic_non_direct_route()
        record['parts'][2] = _flat_part(3, -0.25,
                                        record['parts'][2]['primitives'])
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('body_z_mismatch_model', kinds)

    def test_missing_transition(self):
        record = _synthetic_non_direct_route()
        record['parts'] = [record['parts'][0], record['parts'][2],
                           record['parts'][4]]
        kinds = {item['kind'] for item in self._check(record)}
        self.assertIn('non_direct_parts_not_lead_trans_body_trans_lead', kinds)

    def test_negative_z_span_check(self):
        record = _synthetic_non_direct_route(target_plane=8, target_z=0.05)
        # plane 8 is z=+0.05 (upward from z1 interface); must still be valid
        self.assertEqual(self._check(record), [])

    def test_upward_transition_radius(self):
        record = _synthetic_non_direct_route(target_plane=8, target_z=0.05)
        violations = []
        details = V.check_radius(record, violations)
        self.assertEqual(violations, [])
        self.assertEqual(details['transition_count'], 2)
        self.assertGreaterEqual(details['transition_min_sampled_radius'],
                                V.MIN_R15_SAMPLED_MM)


# ---------------------------------------------------------------------------
# crossing / distribution helpers
# ---------------------------------------------------------------------------
class TestCrossings(unittest.TestCase):
    def _route(self, route_id, y, layer_id=1001, z=0.0):
        part = _flat_part(layer_id, z, [_line((10.0, y), (20.0, y))])
        return dict(route_id=int(route_id), plane='z1', n_transitions=0,
                    parts=[part])

    def test_distribution_helper(self):
        counter = Counter({1: 0, 2: 1, 3: 2, 4: 5})
        distribution = V._crossing_distribution(counter)
        self.assertEqual(distribution['max'], 5)
        self.assertEqual(distribution['routes'], 4)
        self.assertAlmostEqual(distribution['mean'], 2.0)
        self.assertEqual(distribution['routes_with_crossings'], 3)

    def test_interface_plane_merges_leads_and_direct_bodies(self):
        planes = V._spec_model()
        routed = [self._route(1, 10.0), self._route(2, 10.0)]
        assignment_by_id = {1: dict(needs_transition='False'),
                            2: dict(needs_transition='False')}
        violations, details = V.check_crossings(routed, planes,
                                                assignment_by_id)
        interface_rows = [row for row in details['planes']
                          if row['kind'] == 'interface_body']
        # only the z=0.0 interface has geometry in this synthetic case
        self.assertEqual(len(interface_rows), 1)
        z1_row = interface_rows[0]
        self.assertEqual(z1_row['z_mm'], 0.0)
        self.assertEqual(z1_row['routes'], 2)
        self.assertEqual(z1_row['direct_routes'], 2)
        self.assertGreaterEqual(len(violations), 1)   # 0 spacing < 0.08 D56

    def test_legal_transverse_crossing_not_violation(self):
        planes = V._spec_model()
        horizontal = self._route(1, 10.0)
        vertical = dict(route_id=2, plane='z1', n_transitions=0,
                        parts=[_flat_part(1001, 0.0,
                                          [_line((15.0, 5.0), (15.0, 15.0))])])
        violations, details = V.check_crossings([horizontal, vertical], planes,
                                                {})
        z1_row = next(row for row in details['planes']
                      if row['z_mm'] == 0.0)
        self.assertEqual(z1_row['crossings'], 1)
        self.assertEqual(violations, [])

    def test_unknown_height_flagged_for_21h(self):
        planes = V._spec_model()
        # -0.12 mm is not one of the 21 routing heights
        route = self._route(1, 10.0, layer_id=6, z=-0.12)
        violations, _details = V.check_crossings([route], planes, {})
        kinds = {item['kind'] for item in violations}
        self.assertIn('flat_at_unknown_height', kinds)


# ---------------------------------------------------------------------------
# consistency tests + regression guard
# ---------------------------------------------------------------------------
class TestConsistencyAndRegression(unittest.TestCase):
    def test_consistency_tests_all_pass_for_21h_model(self):
        planes = V._spec_model()
        stack = V.build_model_stack(planes)
        consistency = V.run_consistency_tests(planes, stack)
        failed = [test['name'] for test in consistency['tests']
                  if not test['passed']]
        self.assertTrue(consistency['all_passed'], f'failed: {failed}')
        self.assertGreaterEqual(len(consistency['tests']), 8)

    def test_regression_check_matches_frozen_expectations(self):
        report = dict(
            routed=1024, failed=0,
            counts=dict(routed=1024, direct_routes=0, transitions=2048,
                        same_plane_crossings=18108,
                        total_length_mm=156893.004843646),
            min_3d_clearance_mm=0.149965866,
            checks=dict(crossings=dict(planes=[
                dict(z_mm=-0.11, crossings=5610),
                dict(z_mm=-0.05, crossings=5284)])),
        )
        result = V.regression_check(report)
        self.assertTrue(result['ok'],
                        f"failed: {[c for c in result['checks'] if not c['passed']]}")

    def test_regression_check_detects_stale_transition_count(self):
        report = dict(
            routed=1024, failed=0,
            counts=dict(routed=1024, direct_routes=0, transitions=2006,
                        same_plane_crossings=18108,
                        total_length_mm=156893.004843646),
            min_3d_clearance_mm=0.149965866,
            checks=dict(crossings=dict(planes=[
                dict(z_mm=-0.11, crossings=5610),
                dict(z_mm=-0.05, crossings=5284)])),
        )
        result = V.regression_check(report)
        self.assertFalse(result['ok'])
        failed = {check['name'] for check in result['checks']
                  if not check['passed']}
        self.assertIn('transitions', failed)

    def test_expected_transition_count_1848(self):
        # 1024 - 100 direct routes -> 924 two-transition routes
        self.assertEqual(2 * (1024 - V.SPEC_DIRECT_TOTAL), 1848)
        self.assertEqual(sum(V.SPEC_DIRECT_BY_PLANE.values()), 100)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
