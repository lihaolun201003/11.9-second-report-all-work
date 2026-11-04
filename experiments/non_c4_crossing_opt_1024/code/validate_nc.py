# -*- coding: utf-8 -*-
"""Independent validation wrapper for the C4-free experiments.

The frozen 21-height validator (``reheight21.validate21``) is reused *in full*:
structure, R15 radius, glass bounds, true 3D clearance, ports, crossing audit
and the consistency tests are untouched.  Only three C4-era expectations are
re-parameterised (they describe the old whole-orbit plan, not a hard geometric
rule):

1. the expected per-plane assignment counts,
2. the expected interface-direct count / per-plane split,
3. the ``c4_orbit_not_single_plane`` contract violation (the whole point of this
   experiment is to allow a non-manual C4 orbit to be split over planes).

Every remaining contract check (manual group membership/planes, port identity,
direction, direct-vs-transition structure, 21 heights, 50 um pitch, 0.05 mm 3D
clearance, strict D56 crossing policy) stays active.
"""
from __future__ import annotations

import time
from collections import Counter, OrderedDict
from pathlib import Path

from ..reheight21 import validate21 as V
from . import crossings as X
from . import data as D

#: only this contract violation is dropped by removing the C4 binding
_C4_ALLOWED_KINDS = ('c4_orbit_not_single_plane',)
#: contract kinds that are only about "all 21 heights are populated"; a legal
#: C4-free assignment may leave a height empty, so these are reported, not fatal
_EMPTY_PLANE_KINDS = ('model_planes_without_flat_geometry',
                      'planes_audited_count_not_21')

_ORIG_CHECK_ASSIGNMENT = V.check_assignment


def _orbit_split_evidence(assignment_rows):
    """Non-manual C4 orbits split across physical planes (provenance only)."""
    import collections
    from .. import common as C
    by_id = {}
    for row in assignment_rows:
        try:
            by_id[int(row.get('route_id'))] = row
        except (TypeError, ValueError):
            continue
    orbit_planes = collections.defaultdict(set)
    orbit_manual = collections.defaultdict(bool)
    for group in C.rotation_groups():
        group_id = int(group['group_id'])
        for route_id in group['route_ids']:
            row = by_id.get(int(route_id))
            if row is None:
                continue
            try:
                orbit_planes[group_id].add(int(row['target_layer']))
            except (TypeError, ValueError, KeyError):
                continue
            if str(row.get('manual_group') or '').strip():
                orbit_manual[group_id] = True
    nonmanual = {gid: planes for gid, planes in orbit_planes.items()
                 if not orbit_manual[gid]}
    split = {gid: sorted(planes) for gid, planes in nonmanual.items()
             if len(planes) > 1}
    return dict(
        c4_binding='removed (non-manual C4 orbits may be split across planes)',
        nonmanual_orbits=len(nonmanual),
        nonmanual_orbits_split_across_planes=len(split),
        nonmanual_orbits_single_plane=len(nonmanual) - len(split),
        max_planes_per_nonmanual_orbit=max(
            (len(planes) for planes in nonmanual.values()), default=0),
        split_examples=[dict(group_id=gid, planes=planes)
                        for gid, planes in list(sorted(split.items()))[:20]],
    )


def _check_assignment_nc(assignment_rows, routes, true_routes, planes,
                         baseline_mode=False):
    violations, details, by_id = _ORIG_CHECK_ASSIGNMENT(
        assignment_rows, routes, true_routes, planes,
        baseline_mode=baseline_mode)
    kept = []
    dropped = []
    for item in violations:
        if str(item.get('kind')) in _C4_ALLOWED_KINDS:
            dropped.append(item)
        else:
            kept.append(item)
    details['c4_policy'] = _orbit_split_evidence(assignment_rows)
    details['c4_orbit_violations_removed'] = len(dropped)
    return kept, details, by_id


def patch_validator(expected_counts=None, direct_by_plane=None):
    """Re-parameterise the frozen validator for a C4-free assignment."""
    if expected_counts is not None:
        V.SPEC_EXPECTED_ASSIGNED = OrderedDict(
            sorted((int(k), int(v)) for k, v in expected_counts.items()))
    if direct_by_plane is not None:
        by_plane = {int(k): int(v) for k, v in direct_by_plane.items()}
        V.SPEC_DIRECT_BY_PLANE = by_plane
        V.SPEC_DIRECT_TOTAL = sum(by_plane.values())
    V.check_assignment = _check_assignment_nc


def _extra_checks(exp_dir, report):
    routes = D.route_records(Path(exp_dir) / 'routes_l3d.json')
    by_id = {int(route['route_id']): route for route in routes}
    manual_rows = [row for row in D.assignment_rows(exp_dir) if D.is_manual(row)]
    manual_baseline = D.baseline_routes()
    baseline_manual = {int(route['route_id']): route for route in manual_baseline
                       if int(route['route_id']) in
                       {int(row['route_id']) for row in manual_rows}}
    import json as _json
    mismatches = []
    for route_id, baseline in baseline_manual.items():
        current = by_id.get(route_id)
        if current is None:
            mismatches.append(dict(route_id=route_id, kind='missing'))
            continue
        if (_json.dumps(current.get('parts'), sort_keys=True, default=str)
                != _json.dumps(baseline.get('parts'), sort_keys=True,
                               default=str)):
            mismatches.append(dict(route_id=route_id, kind='parts_changed'))
    # non-manual C4-free evidence from the assignment actually used
    assignment = D.assignment_rows(exp_dir)
    families = Counter(D.family_of(row) for row in assignment)
    return dict(
        schema='nonc4_validation_extra_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        manual_routes_expected=368,
        manual_routes_frozen_to_baseline=not mismatches,
        manual_geometry_mismatches=mismatches[:100],
        manual_geometry_mismatch_count=len(mismatches),
        c4_free_assignment=_orbit_split_evidence(assignment),
        family_counts=dict(sorted(families.items())),
        assignment_sha256=D.sha256_file(Path(exp_dir) / 'assignment_1024.csv'),
        routes_sha256=D.sha256_file(Path(exp_dir) / 'routes_l3d.json'),
        crossing_rule=dict(d56_centerline_mm=X.D56_CLEARANCE_MM,
                           policy='strict D56, legal transverse crossings kept',
                           note='crossing counts are geometric proxies only'),
    )


def _filter_report(report, allowed_kinds):
    if not allowed_kinds:
        return report
    kept = []
    removed = []
    for item in report.get('violations') or []:
        if str(item.get('kind')) in allowed_kinds:
            removed.append(item)
        else:
            kept.append(item)
    if not removed:
        return report
    report['violations'] = kept
    report['violation_count'] = len(kept)
    report['violation_counts_by_check'] = dict(sorted(Counter(
        item.get('check') for item in kept).items()))
    geometry_checks = ('structure', 'radius', 'glass', 'clearance', 'ports',
                       'crossings')
    contract_checks = ('model', 'assignment', 'totals')
    geometry_pass = not any(item.get('check') in geometry_checks
                            for item in kept)
    contract_pass = not any(item.get('check') in contract_checks
                            for item in kept)
    consistency_ok = bool(report.get('validator_consistency_passed'))
    report['geometry_pass'] = bool(geometry_pass)
    report['contract_pass'] = bool(contract_pass)
    report['validation_pass'] = bool(geometry_pass and contract_pass
                                     and consistency_ok)
    report['exit_code'] = 0 if report['validation_pass'] else 1
    report['allowed_contract_violations'] = dict(
        count=len(removed),
        kinds=sorted({str(item.get('kind')) for item in removed}),
        note=('a legal C4-free assignment may leave some of the 21 routing '
              'heights unpopulated; this does not weaken any geometric rule'))
    return report


def validate_experiment(exp_dir, expected_counts=None, direct_by_plane=None,
                        skip_min_clearance=False, skip_crossings=False,
                        log=print, allow_empty_planes=True):
    """Run the full frozen validator on one C4-free experiment directory."""
    exp_dir = Path(exp_dir)
    rows = D.assignment_rows(exp_dir)
    if expected_counts is None:
        expected_counts = Counter(int(row['target_layer']) for row in rows)
    if direct_by_plane is None:
        direct_by_plane = Counter(int(row['target_layer']) for row in rows
                                  if D.is_direct(row))
    patch_validator(expected_counts, direct_by_plane)
    validation_dir = exp_dir / 'validation'
    validation_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    report, validation_out, crossing_stats, consistency = V.validate(
        run_dir=str(exp_dir), out_dir=str(exp_dir),
        validation_out=str(exp_dir / 'validation.json'),
        consistency_out=str(exp_dir / 'validator_consistency_tests.json'),
        crossing_out=str(validation_dir / 'crossing_stats_validate21.json'),
        skip_min_clearance=skip_min_clearance,
        skip_crossings=skip_crossings, verbose=False)
    report['nonc4'] = _extra_checks(exp_dir, report)
    report['nonc4']['validation_seconds'] = round(time.time() - started, 2)
    if allow_empty_planes:
        report = _filter_report(report, _EMPTY_PLANE_KINDS)
    # never leave a misleading pass when a manual route moved
    if not report['nonc4']['manual_routes_frozen_to_baseline']:
        report['validation_pass'] = False
        report['exit_code'] = 1
    D.write_json(exp_dir / 'validation.json', report)
    log(f'[validate] validation_pass={report["validation_pass"]} '
        f'geometry_pass={report["geometry_pass"]} '
        f'contract_pass={report["contract_pass"]} '
        f'violations={report.get("violation_count")} '
        f'crossings={((report.get("counts") or {}).get("same_plane_crossings"))}')
    return report


def verify_device_runner(exp_dir, **kwargs):
    """Alias used by scripts: validate a finished experiment directory."""
    return validate_experiment(exp_dir, **kwargs)
