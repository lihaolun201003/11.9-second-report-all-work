# -*- coding: utf-8 -*-
"""Self-tests of the per-layer 2D R15 body router (``fanout1024.layer2d``).

Run with::

    .venv\\Scripts\\python.exe four_side_1024\\fanout1024\\tests_layer2d.py

The tests are also pytest-compatible (functions named ``test_*``).

Coverage
--------
A. synthetic per-class poses (same-side U / opposite / adjacent): full routing,
   exact start/end poses, exact R=15 arcs, board bounds, strict-D56 re-check and
   byte-level determinism.
B. the 8 real manual-U layers (L2-L5, L10-L13, 368 routes) from the verified
   assignment: every route must be routed.
C. synthetic opposite (L6, 128 routes) and adjacent (L8, 50 routes) layers built
   from the true z1-opposite / z2-adjacent connections: high success + reasons.
D. integration smoke test against the live fanout artifacts (if present): all
   18 layers, reporting per-layer counts (read-only use of the run directory).
E. the ``initial_routes`` joint-repair primitive (frozen layout insertion).
"""
from __future__ import annotations

import csv
import json
import math
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from four_side_1024.fanout1024 import common, layer2d  # noqa: E402
from four_side_1024.d56.index import D56Index, prepare as d56_prepare  # noqa: E402
from four_side_1024.fsd25d.world25d import primitive_bbox  # noqa: E402

RUN_DIR = common.RUN_DIR
ASSIGNMENT_CSV = RUN_DIR / 'assignment_1024.csv'
FANOUT_SELECTED = RUN_DIR / 'fanout_selected.json'
BATCH_LIMIT = 20000      # deterministic per-test bound on candidate evaluations


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def load_assignment_rows():
    if not ASSIGNMENT_CSV.is_file():
        return None
    rows = []
    with open(ASSIGNMENT_CSV, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            record = dict(row)
            record['route_id'] = int(row['route_id'])
            record['target_layer'] = int(row['target_layer'])
            record['target_z_mm'] = float(row['target_z_mm'])
            rows.append(record)
    return rows


def load_fanout_selected():
    if not FANOUT_SELECTED.is_file():
        return None
    payload = json.loads(FANOUT_SELECTED.read_text(encoding='utf-8'))
    selected = payload.get('selected') if isinstance(payload, dict) else None
    if selected is None:
        return None
    return {int(key): value for key, value in selected.items()}


def tasks_for_rows(rows, lead=2.0):
    """Landing tasks for assignment rows with a fixed lead (synthetic fanout)."""
    landings = layer2d.synthesize_landings(rows, lead=lead)
    return layer2d.make_tasks_from_assignment(rows, landings)


def body_errors(body, task, label='body'):
    """Independent structural audit of one routed body chain."""
    prims = body['primitives']
    errors = []
    if not prims:
        return [f'{label}:empty']
    A = (float(task['A'][0]), float(task['A'][1]))
    B = (float(task['B'][0]), float(task['B'][1]))
    dA = (float(task['dA'][0]), float(task['dA'][1]))
    dB = (float(task['dB'][0]), float(task['dB'][1]))
    # exact endpoint poses
    if math.hypot(prims[0]['p0'][0] - A[0], prims[0]['p0'][1] - A[1]) > 1e-6:
        errors.append(f'{label}:start_point_mismatch')
    if math.hypot(prims[-1]['p1'][0] - B[0], prims[-1]['p1'][1] - B[1]) > 1e-6:
        errors.append(f'{label}:end_point_mismatch')
    start_tangent = layer2d._start_tangent(prims[0])
    end_tangent = layer2d._end_tangent(prims[-1])
    if layer2d._tangent_gap(start_tangent, dA) > 1e-4:
        errors.append(f'{label}:start_tangent_mismatch')
    if layer2d._tangent_gap(end_tangent, (-dB[0], -dB[1])) > 1e-4:
        errors.append(f'{label}:end_tangent_mismatch')
    # chain continuity, radius, orthogonal lines, board bounds
    for index, prim in enumerate(prims):
        if prim['kind'] == 'arc':
            if abs(float(prim['radius']) - 15.0) > 1e-9:
                errors.append(f'{label}:arc_radius:{index}')
            if abs(float(prim['sweep'])) > math.pi / 2.0 + 1e-9:
                errors.append(f'{label}:arc_sweep:{index}')
            center = prim['center']
            radius = float(prim['radius'])
            start_angle = float(prim['start_angle'])
            sweep = float(prim['sweep'])
            for key, angle in (('p0', start_angle), ('p1', start_angle + sweep)):
                calc = (center[0] + radius * math.cos(angle),
                        center[1] + radius * math.sin(angle))
                if math.hypot(calc[0] - prim[key][0],
                              calc[1] - prim[key][1]) > 1e-7:
                    errors.append(f'{label}:arc_inconsistent:{index}')
        elif prim['kind'] == 'line':
            dx = abs(prim['p1'][0] - prim['p0'][0])
            dy = abs(prim['p1'][1] - prim['p0'][1])
            if dx > 1e-9 and dy > 1e-9:
                errors.append(f'{label}:diagonal_line:{index}')
            if math.hypot(prim['p1'][0] - prim['p0'][0],
                          prim['p1'][1] - prim['p0'][1]) < 1e-12:
                errors.append(f'{label}:zero_line:{index}')
        else:
            errors.append(f'{label}:unknown_primitive:{index}')
        box = primitive_bbox(prim)
        if box[0] < -1e-6 or box[1] < -1e-6 or box[2] > 150.0 + 1e-6 \
                or box[3] > 150.0 + 1e-6:
            errors.append(f'{label}:outside_board:{index}')
        if index:
            previous = prims[index - 1]
            if math.hypot(previous['p1'][0] - prim['p0'][0],
                          previous['p1'][1] - prim['p0'][1]) > 1e-9:
                errors.append(f'{label}:discontinuous:{index}')
            if layer2d._tangent_gap(layer2d._end_tangent(previous),
                                    layer2d._start_tangent(prim)) > 1e-6:
                errors.append(f'{label}:tangent_kink:{index}')
    return errors


def recheck_layer_conflicts(routed, label='layer'):
    """Rebuild a fresh strict D56 index over the routed bodies (order check)."""
    index = D56Index(width=0.05, gap=0.03, sagitta=0.0005,
                     min_cross_angle_deg=5.0, crossing_policy='strict')
    errors = []
    for route_id in sorted(routed):
        prims = routed[route_id]['primitives']
        evaluation = index.evaluate(d56_prepare(prims))
        if not evaluation.valid:
            errors.append(f'{label}:conflict:{route_id}:{evaluation.reason}')
            break
        index.add(route_id, d56_prepare(prims))
    return errors


def assert_bodies(testcase, result, task_map, label):
    routed = result['routed']
    for route_id, body in routed.items():
        task = task_map[int(route_id)]
        errors = body_errors(body, task, f'{label}:{route_id}')
        testcase.assertFalse(errors, errors[:5])
    errors = recheck_layer_conflicts(routed, label)
    testcase.assertFalse(errors, errors[:5])


# ---------------------------------------------------------------------------
# A. synthetic per-class poses
# ---------------------------------------------------------------------------
class TestSyntheticClasses(unittest.TestCase):
    """12 realistic synthetic tasks per layer class, fully routed and audited."""

    @classmethod
    def setUpClass(cls):
        cls.rows = load_assignment_rows()
        if cls.rows is None:
            raise unittest.SkipTest('assignment_1024.csv not available')
        by_relation = {}
        for row in cls.rows:
            by_relation.setdefault(row['relation'], []).append(row)
        cls.by_relation = by_relation
        # landing depth 4.5..6.0 mm: choose the lead that gives such a depth
        cls.leads = {}
        for layer_id, z_mm in ((2, -0.35), (6, -0.11), (8, 0.05)):
            plane = 'z1' if layer_id < 8 else 'z2'
            footprint = layer2d.footprint_mm(
                z_mm - common.interface_z(plane))
            lead = max(0.25, 4.6 - footprint)
            cls.leads[layer_id] = round(min(lead, 6.0 - footprint), 6)

    def _tasks(self, relation, layer_id, count=12):
        rows = [row for row in self.by_relation[relation]
                if row['target_layer'] == layer_id][:count]
        self.assertEqual(len(rows), count,
                         f'not enough {relation} rows on L{layer_id}')
        lead = self.leads[layer_id]
        z_mm = common.layer_z(layer_id)
        plane = 'z1' if layer_id < 8 else 'z2'
        footprint = layer2d.footprint_mm(z_mm - common.interface_z(plane))
        depth = lead + footprint
        self.assertGreaterEqual(depth, 4.4)
        self.assertLessEqual(depth, 6.2)
        tasks_map = tasks_for_rows(rows, lead=lead)
        self.assertIn(layer_id, tasks_map)
        return tasks_map[layer_id]['tasks']

    def _check(self, relation, layer_id):
        tasks = self._tasks(relation, layer_id)
        z_mm = common.layer_z(layer_id)
        result = layer2d.route_layer(layer_id, z_mm, tasks, obstacles=[],
                                     budget=600, rr_rounds=2, log=lambda *a: None)
        stats = result['stats']
        self.assertEqual(stats['success'], len(tasks),
                         f'{relation}: routed {stats["success"]}/{len(tasks)} '
                         f'failed={result["failed"]}')
        task_map = {task['route_id']: task for task in tasks}
        assert_bodies(self, result, task_map, f'synthetic_{relation}')
        # determinism: an identical rerun must produce identical geometry
        again = layer2d.route_layer(layer_id, z_mm, tasks, obstacles=[],
                                    budget=600, rr_rounds=2,
                                    log=lambda *a: None)
        self.assertEqual(sorted(result['routed']), sorted(again['routed']))
        for route_id in result['routed']:
            first = json.dumps(result['routed'][route_id]['primitives'],
                               sort_keys=True)
            second = json.dumps(again['routed'][route_id]['primitives'],
                                sort_keys=True)
            self.assertEqual(first, second,
                             f'determinism mismatch for route {route_id}')

    def test_same_side_u(self):
        self._check('same', 2)

    def test_opposite(self):
        self._check('opposite', 6)

    def test_adjacent(self):
        self._check('adjacent', 8)


# ---------------------------------------------------------------------------
# B. the 8 real manual-U layers (368 routes)
# ---------------------------------------------------------------------------
class TestManualLayers(unittest.TestCase):
    MANUAL_LAYERS = (2, 3, 4, 5, 10, 11, 12, 13)

    def test_all_manual_layers_routed(self):
        rows = load_assignment_rows()
        if rows is None:
            self.skipTest('assignment_1024.csv not available')
        manual = [row for row in rows if row.get('manual_group')]
        self.assertEqual(len(manual), 368)
        tasks_map = tasks_for_rows(manual, lead=2.0)
        self.assertEqual(sorted(tasks_map), list(self.MANUAL_LAYERS))
        result = layer2d.route_all_layers(tasks_map, out_dir=None,
                                          log=lambda *a: None)
        self.assertEqual(len(result['layers']), 8)
        total_input = total_routed = 0
        for layer_id, layer_result in result['layers'].items():
            stats = layer_result['stats']
            total_input += stats['input']
            total_routed += stats['success']
            task_map = {task['route_id']: task
                        for task in tasks_map[layer_id]['tasks']}
            assert_bodies(self, layer_result, task_map, f'manual_L{layer_id}')
            self.assertEqual(stats['success'], stats['input'],
                             f'L{layer_id} routed {stats["success"]}'
                             f'/{stats["input"]} failed={layer_result["failed"]}')
        self.assertEqual(total_input, 368)
        self.assertEqual(total_routed, 368)
        # the failed list must be reconciled: no stale entries at all
        self.assertEqual(sum(len(layer['failed'])
                             for layer in result['layers'].values()), 0)
        # a second deterministic run gives identical geometry
        again = layer2d.route_all_layers(tasks_map, out_dir=None,
                                         log=lambda *a: None)
        for layer_id in result['layers']:
            first = result['layers'][layer_id]['routed']
            second = again['layers'][layer_id]['routed']
            self.assertEqual(sorted(first), sorted(second))
            for route_id in first:
                self.assertEqual(
                    json.dumps(first[route_id]['primitives'], sort_keys=True),
                    json.dumps(second[route_id]['primitives'], sort_keys=True))


# ---------------------------------------------------------------------------
# C. synthetic opposite / adjacent layers
# ---------------------------------------------------------------------------
class TestOppositeAdjacentLayers(unittest.TestCase):

    def test_opposite_128_routes(self):
        rows = load_assignment_rows()
        if rows is None:
            self.skipTest('assignment_1024.csv not available')
        opposite = [row for row in rows
                    if row['relation'] == 'opposite'
                    and row['target_layer'] in (6, 7)]
        self.assertEqual(len(opposite), 256)
        selected = [row for row in opposite if row['target_layer'] == 6][:128]
        self.assertEqual(len(selected), 128)
        tasks_map = tasks_for_rows(selected, lead=2.0)
        layer_id = 6
        result = layer2d.route_layer(layer_id, common.layer_z(layer_id),
                                     tasks_map[layer_id]['tasks'],
                                     obstacles=[], budget=600, rr_rounds=2,
                                     log=lambda *a: None)
        stats = result['stats']
        success = stats['success']
        rate = success / float(stats['input'])
        print(f'[test] synthetic L6 opposite: {success}/{stats["input"]} '
              f'({100.0 * rate:.1f}%) families={stats.get("families")} '
              f'reasons={ {r["reason"]: sum(1 for x in result["failed"] if x["reason"] == r["reason"]) for r in result["failed"]} }')
        self.assertGreaterEqual(rate, 0.95,
                                f'opposite layer success {success}/'
                                f'{stats["input"]} below 95%')
        task_map = {task['route_id']: task
                    for task in tasks_map[layer_id]['tasks']}
        assert_bodies(self, result, task_map, 'synthetic_opposite')
        # every failure must be a real assigned route id with a real reason
        assigned = set(task_map)
        for record in result['failed']:
            self.assertIn(int(record['route_id']), assigned)
            self.assertTrue(record['reason'])
        self.assertEqual({int(r['route_id']) for r in result['failed']},
                         assigned - set(result['routed']))

    def test_adjacent_50_routes(self):
        rows = load_assignment_rows()
        if rows is None:
            self.skipTest('assignment_1024.csv not available')
        adjacent = [row for row in rows
                    if row['relation'] == 'adjacent'
                    and row['target_layer'] == 8][:50]
        self.assertEqual(len(adjacent), 48)  # final assignment has 48 on L8
        tasks_map = tasks_for_rows(adjacent, lead=2.0)
        layer_id = 8
        result = layer2d.route_layer(layer_id, common.layer_z(layer_id),
                                     tasks_map[layer_id]['tasks'],
                                     obstacles=[], budget=600, rr_rounds=2,
                                     log=lambda *a: None)
        stats = result['stats']
        rate = stats['success'] / float(stats['input'])
        print(f'[test] synthetic L8 adjacent: {stats["success"]}/'
              f'{stats["input"]} ({100.0 * rate:.1f}%) '
              f'families={stats.get("families")}')
        self.assertGreaterEqual(rate, 0.95)
        task_map = {task['route_id']: task
                    for task in tasks_map[layer_id]['tasks']}
        assert_bodies(self, result, task_map, 'synthetic_adjacent')


# ---------------------------------------------------------------------------
# E. frozen-layout repair primitive (initial_routes)
# ---------------------------------------------------------------------------
class TestInitialRoutesRepair(unittest.TestCase):

    def test_repair_into_frozen_layout(self):
        rows = load_assignment_rows()
        if rows is None:
            self.skipTest('assignment_1024.csv not available')
        manual = [row for row in rows if row['target_layer'] == 2]
        tasks_map = tasks_for_rows(manual, lead=2.0)
        layer_id = 2
        z_mm = common.layer_z(layer_id)
        full = layer2d.route_layer(layer_id, z_mm,
                                   tasks_map[layer_id]['tasks'],
                                   obstacles=[], log=lambda *a: None)
        self.assertEqual(full['stats']['success'], len(tasks_map[layer_id]['tasks']))
        route_ids = list(full['routed'])
        frozen = {rid: full['routed'][rid]['primitives']
                  for rid in route_ids[:-1]}
        target = route_ids[-1]
        task = next(item for item in tasks_map[layer_id]['tasks']
                    if item['route_id'] == target)
        repair = layer2d.route_layer(
            layer_id, z_mm, [task], obstacles=[], budget=1200,
            rr_rounds=0, initial_routes=frozen, log=lambda *a: None)
        self.assertEqual(repair['stats']['initial_routes'], len(frozen))
        self.assertEqual(set(repair['routed']), {target})
        self.assertEqual(repair['stats']['input'], 1)
        self.assertEqual(repair['stats']['success'], 1)
        # frozen bodies must be acting as strict blockers
        index = D56Index(width=0.05, gap=0.03, sagitta=0.0005,
                         min_cross_angle_deg=5.0, crossing_policy='strict')
        for rid, prims in frozen.items():
            index.add(rid, d56_prepare(prims))
        evaluation = index.evaluate(
            d56_prepare(repair['routed'][target]['primitives']))
        self.assertTrue(evaluation.valid, evaluation.reason)
        # route_all_layers must forward a per-layer initial_routes map
        subset = {layer_id: dict(layer_id=layer_id, z_mm=z_mm, tasks=[task],
                                 obstacles=[])}
        aggregated = layer2d.route_all_layers(
            subset, out_dir=None, initial_routes={layer_id: frozen},
            log=lambda *a: None)
        self.assertEqual(
            aggregated['layers'][layer_id]['stats']['initial_routes'],
            len(frozen))
        self.assertEqual(len(aggregated['layers'][layer_id]['routed']), 1)


# ---------------------------------------------------------------------------
# D. integration smoke test (read-only against the live run directory)
# ---------------------------------------------------------------------------
class TestIntegration(unittest.TestCase):
    """Route all 18 layers using the live fanout landings + layer obstacles."""

    def test_all_layers_integration(self):
        rows = load_assignment_rows()
        selected = load_fanout_selected()
        if rows is None or selected is None:
            self.skipTest('fanout_selected.json not available yet')
        from four_side_1024.fanout1024 import fanout
        landings = fanout.landings(selected)
        layers = {}
        for row in rows:
            layer_id = int(row['target_layer'])
            pose = landings.get(int(row['route_id']))
            if pose is None:
                continue
            entry = layers.setdefault(
                layer_id, dict(layer_id=layer_id,
                               z_mm=common.layer_z(layer_id),
                               tasks=[], obstacles=[]))
            entry['tasks'].append(dict(
                route_id=int(row['route_id']),
                manual_group=row.get('manual_group') or '',
                relation=row.get('relation') or '',
                source_side=row.get('source_side'),
                target_side=row.get('target_side'),
                A=tuple(pose['A']), dA=tuple(pose['dA']),
                B=tuple(pose['B']), dB=tuple(pose['dB'])))
        for layer_id in layers:
            layers[layer_id]['obstacles'] = fanout.layer_obstacles(
                selected, layer_id)
        result = layer2d.route_all_layers(layers, out_dir=None,
                                          log=lambda *a: None)
        total_input = total_routed = 0
        for layer_id, layer_result in result['layers'].items():
            stats = layer_result['stats']
            total_input += stats['input']
            total_routed += stats['success']
            print(f'[test] integration L{layer_id}: {stats["success"]}/'
                  f'{stats["input"]} failed={stats["failed"]} '
                  f'{stats["seconds"]:.1f}s')
        print(f'[test] integration total: {total_routed}/{total_input}')
        # every failure record is a real route id with a real reason
        for layer_result in result['layers'].values():
            for record in layer_result['failed']:
                self.assertTrue(record['reason'])
                self.assertLessEqual(len(record['blockers']), 64)
        self.assertGreaterEqual(total_routed, 1000,
                                f'integration rolled back to {total_routed}/'
                                f'{total_input}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
