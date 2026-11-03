# -*- coding: utf-8 -*-
"""Tests for the 21-height experiment figure generator (``plots21.py``).

Run with the project interpreter from the project root::

    .venv\\Scripts\\python.exe four_side_1024\\fanout1024\\reheight21\\tests_plots21.py

What is verified
----------------
1. **Plane/z-order contract** - the 21 per-height images follow ``PLANE_IDS``
   (2,3,4,5,6,7,20,1001,8,9,...,1002,17,18,19), i.e. physical z order, and the
   plane heights match ``layer_planes.json`` / ``reheight21.model``.
2. **Crossing engine** - the crossings computed from the real primitives
   reproduce the baseline validator numbers plane by plane (read dynamically
   from the baseline ``validation.json``, never hard-coded).
3. **Mapped-baseline pipeline** - the baseline 18-layer artifacts mapped onto
   the 21-plane model generate all 21 per-height images plus the comparison /
   3D figures; the drawing data recorded in the manifest equals the independent
   count of real flat primitives of the source ``routes_l3d.json`` per plane;
   the PNGs are non-trivial, high-resolution (dpi >= 150) images.
4. **Synthetic interface-direct dataset** - a tiny synthetic run (clearly a test
   fixture, never a deliverable) exercises the interface-direct zoom figure and
   the ``crossing_stats.json`` adapter; all 8 figure groups are generated with
   no skips.
5. **Graceful degradation** - an empty run directory produces a manifest with
   ``skipped`` rows instead of crashing.

The system temp directory is not writable in this sandbox, so scratch data goes
to ``RUN_DIR/plots/_tests_tmp/<uuid>/`` (inside the plots owner's own write
scope) and is removed at the end unless ``PLOTS21_TEST_KEEP=1`` is set.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
import traceback
import uuid
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402  (used to read the PNGs)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from four_side_1024.fanout1024.reheight21 import plots21 as P21  # noqa: E402

NEW_RUN_DIR = P21.DEFAULT_RUN_DIR
BASELINE_RUN_DIR = P21.DEFAULT_BASELINE_DIR
SCRATCH_ROOT = NEW_RUN_DIR / 'plots' / '_tests_tmp'
KEEP_SCRATCH = str(os.environ.get('PLOTS21_TEST_KEEP', '')).strip() not in ('', '0', 'false')

_RESULTS = []
_CREATED = []


# --------------------------------------------------------------------------
# tiny test harness
# --------------------------------------------------------------------------
def check(condition, message):
    if not condition:
        raise AssertionError(message)


def check_close(actual, expected, tolerance, message):
    check(abs(float(actual) - float(expected)) <= float(tolerance),
          f'{message}: expected {expected}, got {actual}')


def test(name):
    def decorator(function):
        _RESULTS.append(dict(name=name, function=function))
        return function
    return decorator


def _scratch(name):
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_ROOT / f'{name}_{uuid.uuid4().hex[:8]}'
    path.mkdir(parents=True, exist_ok=True)
    _CREATED.append(path)
    return path


def _read_json(path):
    with Path(path).open('r', encoding='utf-8') as handle:
        return json.load(handle)


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _png_size(path):
    image = plt.imread(str(path))
    check(image.ndim >= 2, f'{path.name} is not a readable image')
    return int(image.shape[1]), int(image.shape[0])


def _assert_png(path, min_bytes=15000, min_width=1000, min_height=1000):
    path = Path(path)
    check(path.exists(), f'missing figure {path}')
    size = path.stat().st_size
    check(size >= min_bytes, f'{path.name} is too small ({size} bytes)')
    with path.open('rb') as handle:
        signature = handle.read(8)
    check(signature == b'\x89PNG\r\n\x1a\n', f'{path.name} is not a real PNG')
    width, height = _png_size(path)
    check(width >= min_width and height >= min_height,
          f'{path.name} resolution too low: {width}x{height}')


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _copy_baseline_artifacts_into(run_dir):
    """Baseline 18-layer artifacts mapped onto the new 21-plane model."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ('routes_l3d.json', 'assignment_1024.csv'):
        source = BASELINE_RUN_DIR / name
        check(source.exists(), f'baseline artifact missing: {source}')
        shutil.copy2(source, run_dir / name)
    layerwise_source = BASELINE_RUN_DIR / 'layerwise_routes' / 'routes.json'
    if layerwise_source.exists():
        (run_dir / 'layerwise_routes').mkdir(exist_ok=True)
        shutil.copy2(layerwise_source, run_dir / 'layerwise_routes' / 'routes.json')
    # NOTE: validation.json is intentionally NOT copied - its baseline z values
    # would map onto the new plane model by z (e.g. baseline L7 z=-0.05 ->
    # new L20), which is not the point of this fixture.
    model, plane_source = P21.load_planes(NEW_RUN_DIR)
    check(len(model) == 21, f'expected 21 planes in the new model, got {len(model)}')
    payload = dict(schema='fanout_first_reheight21_layer_planes_v1',
                   experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
                   plane_count=len(model), plane_order=model.order(),
                   planes=[dict(plane) for plane in model.planes])
    (run_dir / 'layer_planes.json').write_text(
        json.dumps(payload, indent=1, default=P21._json_default), encoding='utf-8')
    return run_dir


def independent_geometry_counts(run_dir, model):
    """Count real flat primitives per plane straight from routes_l3d.json."""
    payload = _read_json(Path(run_dir) / 'routes_l3d.json')
    bodies = {plane['plane_id']: dict(routes=set(), primitives=0)
              for plane in model.planes}
    leads = {plane['plane_id']: dict(routes=set(), primitives=0)
             for plane in model.planes}
    interface_by_z = {round(plane['z_mm'], 6): plane['plane_id']
                      for plane in model.planes if plane['kind'] == 'interface_body'}
    body_by_id = {plane['plane_id']: plane['plane_id'] for plane in model.planes
                  if plane['kind'] == 'body'}
    for record in payload.get('routes') or []:
        if not isinstance(record, dict):
            continue
        if str(record.get('status') or 'routed').lower() not in P21.ROUTED_STATUS:
            continue
        route_id = P21._to_int(record.get('route_id'))
        target = P21._to_int(record.get('target_plane')
                             if record.get('target_plane') is not None
                             else record.get('target_layer'))
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            primitives = [prim for prim in (part.get('primitives') or [])
                          if isinstance(prim, dict)]
            if not primitives:
                continue
            layer_id = P21._to_int(part.get('layer_id'))
            z_mm = P21._to_float(part.get('z_mm'))
            if layer_id is not None and layer_id == target and layer_id in body_by_id:
                bodies[layer_id]['routes'].add(route_id)
                bodies[layer_id]['primitives'] += len(primitives)
            elif layer_id == 1 and z_mm is not None:
                plane_id = interface_by_z.get(round(z_mm, 6))
                check(plane_id is not None,
                      f'baseline lead z={z_mm} does not map to an interface plane')
                leads[plane_id]['routes'].add(route_id)
                leads[plane_id]['primitives'] += len(primitives)
    return bodies, leads


def _line_prim(x0, y0, x1, y1):
    return dict(kind='line', p0=[float(x0), float(y0)],
                p1=[float(x1), float(y1)], layer=0)


def _transition(start, direction, z0, z1, radius=15.0):
    dz = float(z1) - float(z0)
    if abs(dz) <= 0.0:
        theta = 0.0
    else:
        theta = math.acos(max(-1.0, min(1.0, 1.0 - dz / (2.0 * radius))))
    footprint = 2.0 * radius * math.sin(theta)
    dx, dy = float(direction[0]), float(direction[1])
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    return dict(kind='transition', start=[float(start[0]), float(start[1])],
                direction=[dx, dy], z0=float(z0), z1=float(z1), dz_mm=dz,
                radius_mm=float(radius), footprint_mm=footprint,
                theta_rad=theta,
                end=[float(start[0]) + dx * footprint,
                     float(start[1]) + dy * footprint],
                length_mm=2.0 * radius * theta, primitives=[])


def _flat(layer_id, z_mm, primitives):
    return dict(kind='flat', layer_id=int(layer_id), z_mm=float(z_mm),
                primitives=primitives, length_mm=sum(
                    P21.prim_length(prim) for prim in primitives))


def write_synthetic_run(run_dir):
    """Tiny synthetic fixture: 2 interface-direct routes + 2 lifted routes.

    This is a *test fixture only* - it is created in the scratch directory and
    never used for a deliverable figure.  It exercises the interface-direct
    zoom path (crossing direct bodies against frozen leads), the transition
    sampling path and the authoritative ``crossing_stats.json`` adapter.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    model, _source = P21.load_planes(NEW_RUN_DIR)
    payload = dict(schema='fanout_first_reheight21_layer_planes_v1',
                   plane_count=len(model), plane_order=model.order(),
                   planes=[dict(plane) for plane in model.planes])
    (run_dir / 'layer_planes.json').write_text(
        json.dumps(payload, indent=1, default=P21._json_default), encoding='utf-8')

    routes = [
        dict(route_id=1, plane='z1', status='routed',
             source_endpoint='N01:1:1', target_endpoint='N02:1:1',
             target_plane=1001, target_plane_label='Z1_INTERFACE',
             target_z_mm=0.0, needs_transition=False, n_transitions=0,
             length_mm=30.0,
             parts=[_flat(1001, 0.0, [_line_prim(15.0, 149.5, 45.0, 149.5)])]),
        dict(route_id=2, plane='z2', status='routed',
             source_endpoint='S01:1:1', target_endpoint='S02:1:1',
             target_plane=1002, target_plane_label='Z2_INTERFACE',
             target_z_mm=0.5, needs_transition=False, n_transitions=0,
             length_mm=60.0,
             parts=[_flat(1002, 0.5, [_line_prim(60.0, 1.5, 120.0, 1.5)])]),
        dict(route_id=3, plane='z1', status='routed',
             source_endpoint='N01:1:2', target_endpoint='S01:1:2',
             target_plane=6, target_plane_label='L6',
             target_z_mm=-0.15, needs_transition=True, n_transitions=2,
             length_mm=150.0,
             parts=[
                 _flat(1, 0.0, [_line_prim(20.0, 150.0, 20.0, 148.0)]),
                 _transition((20.0, 148.0), (0.0, -1.0), 0.0, -0.15),
                 _flat(6, -0.15, [_line_prim(20.0, 146.4, 20.0, 3.6)]),
                 _transition((20.0, 3.6), (0.0, -1.0), -0.15, 0.0),
                 _flat(1, 0.0, [_line_prim(20.0, 1.2, 20.0, -0.8)]),
             ]),
        dict(route_id=4, plane='z2', status='routed',
             source_endpoint='S02:1:2', target_endpoint='N02:1:2',
             target_plane=9, target_plane_label='L9',
             target_z_mm=0.10, needs_transition=True, n_transitions=2,
             length_mm=200.0,
             parts=[
                 _flat(1, 0.5, [_line_prim(100.0, 0.0, 100.0, 2.0)]),
                 _transition((100.0, 2.0), (0.0, 1.0), 0.5, 0.10),
                 _flat(9, 0.10, [_line_prim(100.0, 3.6, 100.0, 146.4)]),
                 _transition((100.0, 146.4), (0.0, 1.0), 0.10, 0.5),
                 _flat(1, 0.5, [_line_prim(100.0, 149.5, 100.0, 152.0)]),
             ]),
    ]
    (run_dir / 'routes_l3d.json').write_text(
        json.dumps(dict(schema='fanout_first_routes_l3d_v1', route_count=len(routes),
                        routed=len(routes), failed=0, routes=routes), indent=1),
        encoding='utf-8')
    assignment_rows = [
        dict(route_id=1, plane='z1', relation='opposite', manual_group='',
             manual_pattern='', layer_role='z1_other', target_layer='1001',
             target_plane_label='Z1_INTERFACE', target_z_mm='0.0',
             interface_z_mm='0.0', direction='direct', needs_transition='False',
             c4_group_id='1', rotation_phase='0', source_endpoint='N01:1:1',
             target_endpoint='N02:1:1', source_side='N', target_side='N',
             source_x_mm='15.0', source_y_mm='150.0', target_x_mm='45.0',
             target_y_mm='150.0'),
        dict(route_id=2, plane='z2', relation='opposite', manual_group='',
             manual_pattern='', layer_role='z2_other', target_layer='1002',
             target_plane_label='Z2_INTERFACE', target_z_mm='0.5',
             interface_z_mm='0.5', direction='direct', needs_transition='False',
             c4_group_id='2', rotation_phase='0', source_endpoint='S01:1:1',
             target_endpoint='S02:1:1', source_side='S', target_side='S',
             source_x_mm='60.0', source_y_mm='0.0', target_x_mm='120.0',
             target_y_mm='0.0'),
        dict(route_id=3, plane='z1', relation='opposite', manual_group='',
             manual_pattern='', layer_role='z1_other', target_layer='6',
             target_plane_label='L6', target_z_mm='-0.15',
             interface_z_mm='0.0', direction='down', needs_transition='True',
             c4_group_id='3', rotation_phase='0', source_endpoint='N01:1:2',
             target_endpoint='S01:1:2', source_side='N', target_side='S',
             source_x_mm='20.0', source_y_mm='150.0', target_x_mm='20.0',
             target_y_mm='0.0'),
        dict(route_id=4, plane='z2', relation='opposite', manual_group='',
             manual_pattern='', layer_role='z2_other', target_layer='9',
             target_plane_label='L9', target_z_mm='0.10',
             interface_z_mm='0.5', direction='down', needs_transition='True',
             c4_group_id='4', rotation_phase='0', source_endpoint='S02:1:2',
             target_endpoint='N02:1:2', source_side='S', target_side='N',
             source_x_mm='100.0', source_y_mm='0.0', target_x_mm='100.0',
             target_y_mm='150.0'),
    ]
    fieldnames = list(assignment_rows[0].keys())
    with (run_dir / 'assignment_1024.csv').open('w', encoding='utf-8-sig',
                                                newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(assignment_rows)
    (run_dir / 'failed_routes.json').write_text(
        json.dumps(dict(failed_routes=[]), indent=1), encoding='utf-8')
    # authoritative crossing stats fixture for the two interface planes
    (run_dir / 'crossing_stats.json').write_text(json.dumps(dict(
        schema='fanout_first_reheight21_crossing_stats_v1',
        planes=[
            dict(plane_id=1001, z_mm=0.0, routes=1, parts=1, crossings=3,
                 crossing_pairs=2,
                 crossing_points=[[20.0, 149.5], [20.1, 149.5], [19.9, 149.5]]),
            dict(plane_id=1002, z_mm=0.5, routes=1, parts=1, crossings=1,
                 crossing_pairs=1, crossing_points=[[100.0, 1.5]]),
        ],
        totals=dict(same_plane_crossings=4, same_plane_crossing_pairs=3),
    ), indent=1), encoding='utf-8')
    return run_dir


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------
@test('plane/z-order contract (21 heights, L20 at -0.05, routable interfaces)')
def test_plane_model():
    model, source = P21.load_planes(NEW_RUN_DIR)
    check(source == 'layer_planes.json',
          f'expected layer_planes.json as the plane source, got {source}')
    check(len(model) == 21, f'expected 21 routing heights, got {len(model)}')
    expected_order = [2, 3, 4, 5, 6, 7, 20, 1001, 8, 9, 10, 11, 12, 13, 14, 15,
                      16, 1002, 17, 18, 19]
    check(model.order() == expected_order,
          f'unexpected plane order: {model.order()}')
    z_values = [plane['z_mm'] for plane in model.planes]
    check(z_values == sorted(z_values), 'planes are not in physical z order')
    check_close(model.get(20)['z_mm'], -0.05, 1e-12, 'L20 must sit at z=-0.05')
    check_close(model.get(1001)['z_mm'], 0.0, 1e-12, 'Z1_INTERFACE z')
    check_close(model.get(1002)['z_mm'], 0.5, 1e-12, 'Z2_INTERFACE z')
    check(model.get(1001)['kind'] == 'interface_body'
          and model.get(1002)['kind'] == 'interface_body',
          'both interface heights must be routable interface bodies')
    check_close(model.min_pitch, 0.05, 1e-6, 'minimum routing-height pitch')
    check(model.height_count == 21, 'the 21 heights must be distinct')
    # cross-check against the frozen model module when importable
    module = P21._load_model_module()
    if module is not None:
        for plane_id in module.PLANE_IDS:
            check_close(model.get(plane_id)['z_mm'], module.plane_z(plane_id),
                        1e-12, f'plane {plane_id} z vs reheight21.model')
            check(model.get(plane_id)['label'] == module.plane_label(plane_id),
                  f'plane {plane_id} label vs reheight21.model')
    # baseline stack model (read-only comparison source)
    base_model, base_source = P21.load_baseline_planes(BASELINE_RUN_DIR)
    check(len(base_model) == 20,
          f'baseline model should be 18 layers + 2 interfaces, got {len(base_model)}')
    base_stack = _read_json(BASELINE_RUN_DIR / 'physical_layer_stack.json')
    heights = base_stack['routing_heights_mm']
    for layer in (6, 7, 19):
        check_close(base_model.get(layer)['z_mm'], float(heights[str(layer)]),
                    1e-12, f'baseline L{layer} z from physical_layer_stack.json')
    return dict(plane_source=source, baseline_source=base_source)


@test('crossing engine reproduces the baseline validator per plane (dynamic)')
def test_crossing_engine():
    base_model, _source = P21.load_baseline_planes(BASELINE_RUN_DIR)
    dataset = P21.build_dataset(BASELINE_RUN_DIR, planes=base_model,
                               label='baseline')
    validation = _read_json(BASELINE_RUN_DIR / 'validation.json')
    expected_planes = (validation.get('checks', {})
                       .get('crossings', {}).get('planes') or [])
    check(bool(expected_planes), 'baseline validation.json has no crossing planes')
    z_to_layer = {round(float(value), 6): int(layer)
                  for layer, value in
                  (validation.get('checks', {}).get('layer_stack', {})
                   .get('expected_routing_heights') or {}).items()}
    compared = 0
    positive = 0
    for entry in expected_planes:
        z_mm = P21._to_float(entry.get('z_mm'))
        if z_mm is None:
            continue
        layer = z_to_layer.get(round(z_mm, 6))
        if layer is None:
            continue  # interface row of the baseline
        stat = dataset['plane_stats'].get(layer) or {}
        expected_count = P21._to_int(entry.get('crossings'))
        expected_pairs = P21._to_int(entry.get('crossing_pairs'))
        check(stat.get('crossings_computed') == expected_count,
              f'computed crossings plane L{layer}: expected {expected_count}, '
              f'got {stat.get("crossings_computed")}')
        if expected_pairs is not None:
            check(stat.get('crossing_pairs_computed') == expected_pairs,
                  f'computed crossing pairs plane L{layer}: expected '
                  f'{expected_pairs}, got {stat.get("crossing_pairs_computed")}')
        compared += 1
        positive += 1 if (expected_count or 0) > 0 else 0
    check(compared >= 18, f'only {compared} baseline planes compared')
    check(positive >= 2, 'expected at least L6/L7 to have crossings')
    # total counts from the validator must match the per-plane sum
    counts = validation.get('counts') or {}
    if counts.get('same_plane_crossings') is not None:
        check(dataset['crossing_totals'].get('crossings')
              == int(counts['same_plane_crossings']),
              'baseline total crossings do not match validation counts')
    # authoritative adapter: plane id mapping from the baseline model
    adapter, source, totals = P21.load_crossing_info(BASELINE_RUN_DIR, base_model)
    check(source == 'validation.json',
          f'expected validation.json adapter source, got {source!r}')
    check(adapter.get(6, {}).get('crossings') is not None,
          'validation adapter did not map baseline L6')
    check(adapter[6]['crossings'] == dataset['plane_stats'][6]['crossings_computed'],
          'validation adapter L6 count differs from the computed count')
    check(bool(totals), 'validation adapter extracted no totals')
    return dict(planes_compared=compared, planes_with_crossings=positive)


@test('mapped-baseline pipeline: 21 high-res per-height images + data equality')
def test_mapped_baseline_pipeline():
    scratch = _scratch('mapped')
    run_dir = _copy_baseline_artifacts_into(scratch / 'run')
    out_dir = scratch / 'plots'
    manifest = P21.generate_plots(run_dir, BASELINE_RUN_DIR, out_dir=out_dir,
                                  dpi=150)
    check(manifest.get('schema') == P21.MANIFEST_SCHEMA, 'bad manifest schema')
    check((out_dir / P21.MANIFEST_NAME).exists(), 'plots_manifest.json missing')
    skipped_names = {item['name'] for item in manifest['skipped']}
    # the mapped baseline has no interface-direct bodies -> the zoom figure is
    # the only legitimate skip for this fixture (the synthetic fixture below
    # exercises it; the real run must have zero skips and is checked then).
    check(skipped_names <= {'08_interface_direct_zoom'},
          f'unexpected skips on the mapped dataset: {skipped_names}')
    figure_groups = [figure['group'] for figure in manifest['figures']]
    for group in ('per_height', 'layer_stack_comparison',
                  'z1_other_comparison', 'crossings_per_plane',
                  'total_crossings', 'path_length_distribution', '3d_all_routes'):
        check(group in figure_groups, f'missing figure group {group}')
    per_height_entries = [figure for figure in manifest['figures']
                          if figure['group'] == 'per_height']
    check(len(per_height_entries) == 21,
          f'expected 21 per-height images, got {len(per_height_entries)}')
    names = [figure['path'] for figure in per_height_entries]
    check(names == sorted(names), 'per-height file names do not sort in z order')
    check(names[0].startswith('per_height/01_L2_z-0.350'),
          f'unexpected first per-height name: {names[0]}')
    check(names[6].startswith('per_height/07_L20_z-0.050'),
          f'L20 must be image 07: {names[6]}')
    check(names[7].startswith('per_height/08_Z1_INTERFACE_z+0.000'),
          f'Z1_INTERFACE must be image 08: {names[7]}')
    check(names[17].startswith('per_height/18_Z2_INTERFACE_z+0.500'),
          f'Z2_INTERFACE must be image 18: {names[17]}')
    check(names[20].startswith('per_height/21_L19_z+0.650'),
          f'last per-height image must be L19: {names[20]}')
    for name in names:
        _assert_png(out_dir / name, min_bytes=15000, min_width=1000,
                    min_height=1000)
    # ---- drawing data equals the independent count of real primitives
    model, _source = P21.load_planes(run_dir)
    bodies, leads = independent_geometry_counts(run_dir, model)
    plane_rows = {row['plane_id']: row for row in manifest['counts']['plane_rows']}
    check(len(plane_rows) == 21, 'manifest plane rows must cover all 21 heights')
    for plane in model.planes:
        plane_id = plane['plane_id']
        row = plane_rows[plane_id]
        check(row['body_primitives'] == bodies[plane_id]['primitives'],
              f'{plane["label"]}: manifest body primitives '
              f'{row["body_primitives"]} != source {bodies[plane_id]["primitives"]}')
        check(row['body_routes'] == len(bodies[plane_id]['routes']),
              f'{plane["label"]}: manifest body routes {row["body_routes"]} != '
              f'source {len(bodies[plane_id]["routes"])}')
        check(row['lead_primitives'] == leads[plane_id]['primitives'],
              f'{plane["label"]}: manifest lead primitives '
              f'{row["lead_primitives"]} != source {leads[plane_id]["primitives"]}')
        check(row['lead_routes'] == len(leads[plane_id]['routes']),
              f'{plane["label"]}: manifest lead routes {row["lead_routes"]} != '
              f'source {len(leads[plane_id]["routes"])}')
    # ---- crossings recorded per plane match the baseline validator (dynamic)
    validation = _read_json(BASELINE_RUN_DIR / 'validation.json')
    z_to_layer = {round(float(value), 6): int(layer)
                  for layer, value in
                  (validation.get('checks', {}).get('layer_stack', {})
                   .get('expected_routing_heights') or {}).items()}
    validation_planes = (validation.get('checks', {})
                         .get('crossings', {}).get('planes') or [])
    for entry in validation_planes:
        z_mm = P21._to_float(entry.get('z_mm'))
        layer = z_to_layer.get(round(z_mm, 6)) if z_mm is not None else None
        if layer is None:
            continue
        row = plane_rows[layer]
        check(row['crossings'] == P21._to_int(entry.get('crossings')),
              f'mapped plane L{layer} crossings {row["crossings"]} != '
              f'validation {entry.get("crossings")}')
        check(row['crossings_computed'] == P21._to_int(entry.get('crossings')),
              f'mapped plane L{layer} computed crossings mismatch')
    # ---- comparison figures and their real data payloads
    for name in ('02_layer_stack_comparison', '03_z1_other_comparison',
                 '04_crossings_per_plane', '05_total_crossings',
                 '06_path_length_distribution', '07_3d_all_routes'):
        matches = [figure for figure in manifest['figures']
                   if figure['name'] == name]
        check(len(matches) == 1, f'missing figure {name}')
        _assert_png(out_dir / matches[0]['path'], min_bytes=10000,
                    min_width=800, min_height=500)
    figure_data = {item['name']: item for item in manifest['figure_data']}
    routed_count = len(P21.load_routes(run_dir)['routed'])
    check(routed_count == 1024, f'expected 1024 baseline routes, got {routed_count}')
    check(figure_data['07_3d_all_routes']['routes_drawn'] == routed_count,
          '3D figure did not draw every routed route')
    check(figure_data['06_path_length_distribution']['n_new'] == routed_count,
          'path-length figure does not cover every routed route')
    validation_counts = validation.get('counts') or {}
    if validation_counts.get('same_plane_crossings') is not None:
        check(figure_data['05_total_crossings']['baseline']['crossings']
              == int(validation_counts['same_plane_crossings']),
              '05 baseline total crossings != validation.json')
    expected_l6 = None
    for entry in validation_planes:
        if P21._to_float(entry.get('z_mm')) == -0.11:
            expected_l6 = P21._to_int(entry.get('crossings'))
    if expected_l6 is not None:
        check(figure_data['04_crossings_per_plane']['baseline_l6'] == expected_l6,
              '04 baseline L6 crossing count != validation.json')
    # ---- manifest integrity: sha256 for every figure
    for figure in manifest['figures']:
        check(isinstance(figure.get('sha256'), str)
              and len(figure['sha256']) == 64,
              f'bad sha256 for {figure["name"]}')
        check((out_dir / figure['path']).exists(),
              f'manifest lists missing file {figure["path"]}')
    # ---- deterministic output (same inputs -> same bytes)
    second = scratch / 'plots_again'
    manifest_again = P21.generate_plots(run_dir, BASELINE_RUN_DIR,
                                        out_dir=second, dpi=150, only=['04'])
    first_png = None
    for figure in manifest['figures']:
        if figure['name'] == '04_crossings_per_plane':
            first_png = out_dir / figure['path']
    second_png = next(second / figure['path'] for figure in manifest_again['figures']
                      if figure['name'] == '04_crossings_per_plane')
    check(_sha256(first_png) == _sha256(second_png),
          'figure output is not deterministic (04 differs between runs)')
    return dict(figures=len(manifest['figures']),
                per_height=len(per_height_entries),
                skipped=sorted(skipped_names),
                runtime_seconds=manifest['runtime_seconds'])


@test('synthetic interface-direct fixture: all 8 figure groups, zero skips')
def test_synthetic_all_groups():
    scratch = _scratch('synthetic')
    run_dir = write_synthetic_run(scratch / 'run')
    out_dir = scratch / 'plots'
    manifest = P21.generate_plots(run_dir, BASELINE_RUN_DIR, out_dir=out_dir,
                                  dpi=110)
    check(not manifest['skipped'],
          f'synthetic run must not skip any figure: {manifest["skipped"]}')
    groups = sorted({figure['group'] for figure in manifest['figures']})
    for group in ('per_height', 'layer_stack_comparison', 'z1_other_comparison',
                  'crossings_per_plane', 'total_crossings',
                  'path_length_distribution', '3d_all_routes',
                  'interface_direct_zoom'):
        check(group in groups, f'missing figure group {group}')
    per_height_entries = [figure for figure in manifest['figures']
                          if figure['group'] == 'per_height']
    check(len(per_height_entries) == 21,
          f'expected 21 per-height images, got {len(per_height_entries)}')
    for figure in per_height_entries:
        _assert_png(out_dir / figure['path'], min_bytes=3000, min_width=600,
                    min_height=600)
    figure_data = {item['name']: item for item in manifest['figure_data']}
    panels = figure_data['08_interface_direct_zoom']['panels']
    check(len(panels) == 2, f'zoom figure must have 2 interface panels, got {len(panels)}')
    check(panels[0]['plane'] == 'Z1_INTERFACE', 'first zoom panel must be Z1')
    check(panels[1]['plane'] == 'Z2_INTERFACE', 'second zoom panel must be Z2')
    check(panels[0]['direct_bodies'] == 1,
          'synthetic Z1 direct body was not drawn')
    check(panels[0]['crossings_direct_lead'] >= 1,
          'synthetic direct-body x lead crossing was not detected')
    check(panels[1]['crossings_direct_lead'] >= 1,
          'synthetic Z2 direct-body x lead crossing was not detected')
    # the authoritative crossing_stats.json values are used for the counts
    plane_rows = {row['plane_id']: row for row in manifest['counts']['plane_rows']}
    check(plane_rows[1001]['crossings'] == 3,
          f'authoritative Z1 crossing count not used: {plane_rows[1001]["crossings"]}')
    check(plane_rows[1001]['crossings_computed'] == 1,
          f'computed Z1 crossing points should be 1: '
          f'{plane_rows[1001]["crossings_computed"]}')
    check(plane_rows[1002]['crossings'] == 1,
          'authoritative Z2 crossing count not used')
    check(figure_data['05_total_crossings']['new']['crossings'] == 4,
          'authoritative crossing total not used')
    check(figure_data['07_3d_all_routes']['routes_drawn'] == 4,
          '3D figure must draw all four synthetic routes')
    check(figure_data['06_path_length_distribution']['n_new'] == 4,
          'path-length figure must cover all four synthetic routes')
    return dict(figures=len(manifest['figures']), groups=groups)


@test('missing inputs degrade to manifest skips, never crash')
def test_missing_inputs():
    scratch = _scratch('empty')
    empty_run = scratch / 'empty_run'
    empty_run.mkdir(parents=True)
    out_dir = scratch / 'plots'
    manifest = P21.generate_plots(empty_run, BASELINE_RUN_DIR, out_dir=out_dir,
                                  dpi=100)
    check((out_dir / P21.MANIFEST_NAME).exists(),
          'manifest must be written even when all inputs are missing')
    skipped = {item['name'] for item in manifest['skipped']}
    for name in ('per_height', '06_path_length_distribution',
                 '07_3d_all_routes', '08_interface_direct_zoom'):
        check(name in skipped, f'{name} should be skipped without routes_l3d.json')
    # the plane-stack figure needs no route data at all -> must still be drawn
    groups = {figure['group'] for figure in manifest['figures']}
    check('layer_stack_comparison' in groups,
          'the layer-stack figure must work without routing artifacts')
    return dict(skipped=sorted(skipped))


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------
def main():
    print('=' * 78)
    print('plots21 tests - 21-height rebalanced figure generation')
    print(f'project root : {PROJECT_ROOT}')
    print(f'new run dir  : {NEW_RUN_DIR}')
    print(f'baseline dir : {BASELINE_RUN_DIR}')
    print(f'scratch root : {SCRATCH_ROOT}')
    print('=' * 78)
    failures = 0
    details = {}
    for item in _RESULTS:
        name = item['name']
        print(f'\n[test] {name}')
        try:
            details[name] = item['function']()
            print(f'  PASS')
        except Exception as error:  # noqa: BLE001 - a test failure must not stop the rest
            failures += 1
            print(f'  FAIL: {type(error).__name__}: {error}')
            traceback.print_exc()
    print('\n' + '=' * 78)
    print(f'{len(_RESULTS) - failures}/{len(_RESULTS)} tests passed')
    if failures:
        print('FAILED tests: ' + ', '.join(
            item['name'] for item in _RESULTS if item['name'] not in details))
    print('=' * 78)
    if KEEP_SCRATCH:
        print('scratch kept at:')
        for path in _CREATED:
            print(f'  {path}')
    else:
        for path in _CREATED:
            try:
                shutil.rmtree(path)
            except OSError as error:  # pragma: no cover
                print(f'warning: could not remove {path}: {error}')
        # remove the empty scratch root as well (keep the deliverable plots/ clean)
        try:
            if SCRATCH_ROOT.exists() and not any(SCRATCH_ROOT.iterdir()):
                SCRATCH_ROOT.rmdir()
        except OSError as error:  # pragma: no cover
            print(f'warning: could not remove {SCRATCH_ROOT}: {error}')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
