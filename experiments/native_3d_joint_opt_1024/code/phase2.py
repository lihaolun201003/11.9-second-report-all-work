# -*- coding: utf-8 -*-
"""Phase-2 (D/E/F) shared paths, baseline loading and accepted-solution bookkeeping.

Baseline for this round: the accepted Native 3D layout with **2440** same-layer
crossings (`NATIVE_3D_CROSSING_OPT_1024`, experiment_C).  It is read-only; every
new experiment writes into ``NATIVE_3D_JOINT_OPT_1024``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from .. import common as C
from . import common as N
from . import guard as G

#: accepted Phase-1 Native 3D layout (READ ONLY)
PHASE1_DIR = N.OUTPUT_ROOT / 'NATIVE_3D_CROSSING_OPT_1024'
PHASE1_RUN_DIR = PHASE1_DIR / 'experiment_C'
#: inherited baseline crossing count
BASELINE_CROSSINGS = 2440
#: new Phase-2 root
RUN2 = N.OUTPUT_ROOT / 'NATIVE_3D_JOINT_OPT_1024'


# ------------------------------------------------------------------ paths
def ensure_dirs():
    for sub in ('', 'experiment_D', 'experiment_E', 'experiment_F',
                'analysis', 'plots', 'validation', 'checkpoints',
                'best_valid', 'baseline', 'configs', 'scratch', 'logs'):
        (RUN2 / sub).mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ io
def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    return C.write_json(Path(path), payload)


def load_baseline_routes():
    """The accepted 2440-crossing layout (list of route records)."""
    payload = load_json(PHASE1_RUN_DIR / 'routes_l3d.json')
    return payload, list(payload['routes'])


def copy_model_files(target_dir):
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ('assignment_1024.csv', 'layer_planes.json',
                 'process_rules.json', 'physical_layer_stack.json'):
        source = PHASE1_RUN_DIR / name
        if not source.is_file():
            source = PHASE1_DIR / name
        if not source.is_file():
            source = N.E5_DIR / name
        if source.is_file():
            (target_dir / name).write_bytes(source.read_bytes())


# ------------------------------------------------------------------ payloads
def build_payload(routes, experiment, note='', extra=None):
    base_payload = load_json(PHASE1_RUN_DIR / 'routes_l3d.json')
    ordered = [routes[rid] for rid in sorted(routes)] \
        if isinstance(routes, dict) else list(routes)
    native = [route for route in ordered
              if int(route.get('n_mid_transitions') or 0) > 0]
    payload = dict(base_payload)
    payload['schema'] = 'native3d_phase2_routes_l3d_v1'
    payload['experiment'] = experiment
    payload['parent_experiment'] = ('NATIVE_3D_CROSSING_OPT_1024/experiment_C '
                                    '(2440 crossings)')
    payload['native_3d'] = dict(
        model='multi-height bodies with mid-body R15 layer changes (Phase 2)',
        routes_with_mid_transitions=len(native),
        mid_transitions=sum(int(route.get('n_mid_transitions') or 0)
                            for route in native),
        geometry='exact R15 S-curves (fsd25d.path3d.make_transition)')
    if extra:
        payload['native_3d'].update(extra)
    payload['route_count'] = len(ordered)
    payload['routed'] = len(ordered)
    payload['failed'] = 0
    payload['routes'] = ordered
    payload['crossing_definition'] = (
        'every flat part grouped by its physical z; fslw strict D56 audit '
        '(identical to the freeze baseline)')
    if note:
        payload['note'] = note
    return payload


def save_experiment(routes, experiment, log=print, note='', extra=None):
    exp = RUN2 / experiment
    exp.mkdir(parents=True, exist_ok=True)
    route_list = [routes[rid] for rid in sorted(routes)] \
        if isinstance(routes, dict) else list(routes)
    route_list = [reconcile_route(route) for route in route_list]
    payload = build_payload(route_list, experiment, note=note, extra=extra)
    write_json(exp / 'routes_l3d.json', payload)
    copy_model_files(exp)
    report, cache = crossing_report(route_list)
    report['experiment'] = experiment
    report['routed'] = len(route_list)
    report['failed'] = 0
    write_json(exp / 'crossing_stats.json', report)
    log('[save] %s: routes=%d crossings=%d pairs=%d'
        % (experiment, len(route_list), report['totals']['crossings'],
           report['totals']['crossing_pairs']))
    return report


def save_best_valid(routes, validation, log=print, tag='best_valid'):
    target = RUN2 / tag
    target.mkdir(parents=True, exist_ok=True)
    route_list = [routes[rid] for rid in sorted(routes)] \
        if isinstance(routes, dict) else list(routes)
    route_list = [reconcile_route(route) for route in route_list]
    payload = build_payload(route_list, tag, note='current validated best')
    write_json(target / 'routes_l3d.json', payload)
    copy_model_files(target)
    report, _cache = crossing_report(route_list)
    write_json(target / 'crossing_stats.json', report)
    write_json(target / 'validation.json', validation)
    write_json(target / 'config.json', dict(
        created_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        routes_file_sha256=sha256_file(target / 'routes_l3d.json'),
        crossings=report['totals']['crossings'],
        crossing_pairs=report['totals']['crossing_pairs'],
        validation_pass=validation.get('validation_pass'),
        violations=validation.get('violations')))
    log('[save] best_valid: crossings=%d (sha %s)'
        % (report['totals']['crossings'],
           sha256_file(target / 'routes_l3d.json')[:16]))
    return report


# ------------------------------------------------------------------ statistics
def crossing_report(routes):
    """Exact multi-height crossing report (same definition as the baseline)."""
    from ..nonc4 import crossings as X
    from . import crossing_cache as CC
    route_list = list(routes)
    report = X.crossing_report(route_list, planes=None, assignment_by_id={},
                               include_events=True, routes_path=None)
    return report, None


def exact_total(routes):
    report, _ = crossing_report(routes)
    return int(report['totals']['crossings']), report


def per_route_crossings(report):
    counter = Counter()
    for event in report.get('crossing_events') or ():
        counter[int(event['route_a'])] += 1
        counter[int(event['route_b'])] += 1
    return counter


def route_lengths(routes):
    return {int(route['route_id']): float(route.get('length_mm') or 0.0)
            for route in routes}


def transition_stats(routes):
    route_list = list(routes)
    native = [route for route in route_list
              if int(route.get('n_mid_transitions') or 0) > 0]
    by_height = Counter()
    per_route = {}
    for route in native:
        entries = []
        for excursion in route.get('excursions') or ():
            entries.append(dict(from_z=excursion.get('from_z'),
                                to_z=excursion.get('to_z'),
                                footprint_mm=excursion.get('footprint_mm'),
                                middle_mm=excursion.get('middle_mm'),
                                s_start_mm=excursion.get('s_start_mm'),
                                s_end_mm=excursion.get('s_end_mm'),
                                kind=excursion.get('kind', 'excursion')))
            by_height['%+.3f' % float(excursion.get('from_z'))] += 1
        per_route[str(route['route_id'])] = entries
    return dict(schema='native3d_phase2_transition_stats_v1',
                routes_with_mid_transitions=len(native),
                mid_transitions=sum(int(route.get('n_mid_transitions') or 0)
                                    for route in native),
                excursions=sum(len(value) for value in per_route.values()),
                by_from_height=dict(sorted(by_height.items())),
                per_route=per_route)


# ------------------------------------------------------------------ metadata
def derive_excursions(route):
    """Rebuild the declared `excursions` records from the real parts chain.

    The independent validator re-derives every mid-body excursion from the
    geometry; after several optimisation passes the stored bookkeeping can lag
    behind, so every saved payload is reconciled here (geometry untouched).
    """
    parts = route.get('parts') or []
    records = []
    existing = list(route.get('excursions') or ())
    index = 0
    while index + 4 < len(parts):
        first = parts[index]
        up = parts[index + 1]
        middle = parts[index + 2]
        down = parts[index + 3]
        last = parts[index + 4]
        matched = False
        if (first.get('kind') == 'flat' and up.get('kind') == 'transition'
                and middle.get('kind') == 'flat'
                and down.get('kind') == 'transition'
                and last.get('kind') == 'flat'
                and str(up.get('tag') or '') == 'mid'
                and str(down.get('tag') or '') == 'mid'):
            z_first = round(float(first['z_mm']), 9)
            z_middle = round(float(middle['z_mm']), 9)
            if (abs(round(float(up['z0']), 9) - z_first) < 1e-9
                    and abs(round(float(up['z1']), 9) - z_middle) < 1e-9
                    and abs(round(float(down['z0']), 9) - z_middle) < 1e-9
                    and abs(round(float(down['z1']), 9) - z_first) < 1e-9):
                record = dict(
                    up_part_index=index + 1, middle_part_index=index + 2,
                    down_part_index=index + 3, prefix_part_index=index,
                    suffix_part_index=index + 4,
                    from_z=z_first, to_z=z_middle,
                    from_plane=N.plane_of_z(z_first),
                    to_plane=N.plane_of_z(z_middle),
                    footprint_mm=float(up.get('footprint_mm') or 0.0),
                    middle_mm=float(middle.get('length_mm') or 0.0),
                    contains_arc=any(prim.get('kind') == 'arc'
                                     for prim in middle.get('primitives') or ()),
                    kind='excursion')
                if len(records) < len(existing):
                    old = existing[len(records)] or {}
                    record['s_start_mm'] = old.get('s_start_mm', 0.0)
                    record['s_end_mm'] = old.get('s_end_mm', 0.0)
                    for key in ('n_steps', 'step_mm'):
                        if key in old:
                            record[key] = old[key]
                else:
                    record['s_start_mm'] = 0.0
                    record['s_end_mm'] = 0.0
                records.append(record)
                index += 4
                matched = True
        if not matched:
            index += 1
    return records


def reconcile_route(route):
    route = dict(route)
    records = derive_excursions(route)
    if records:
        route['excursions'] = records
    return route


# ------------------------------------------------------------------ accepted
def validate(routes, log=print):
    """Fresh-world full validation + minimum 3D clearance of the whole set."""
    route_list = [routes[rid] for rid in sorted(routes)] \
        if isinstance(routes, dict) else list(routes)
    validation = G.full_validate(route_list, log=log)
    clearance = G.measure_min_clearance(route_list, log=log)
    validation = dict(validation)
    validation['min_3d_clearance'] = clearance
    validation['validation_pass'] = (validation.get('violations') == 0)
    return validation


def snapshot(routes):
    return {int(route['route_id']): copy.deepcopy(route) for route in routes} \
        if not isinstance(routes, dict) else \
        {int(rid): copy.deepcopy(route) for rid, route in routes.items()}
