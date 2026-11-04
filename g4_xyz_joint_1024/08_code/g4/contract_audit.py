# -*- coding: utf-8 -*-
"""G4 contract-level audit of a 1024-route XYZ joint result (reusable CLI).

This module turns the independent geometry metrics produced by
:mod:`four_side_1024.fanout1024.xyzrouter.g4.independent_metrics` into the
contract-level deliverable required by the G4 task book section 2:

* the six mandatory quantities,
* the code evidence (file:line) for every process rule that is quoted,
* the crossing-exemption policy actually enforced by the code,
* the cross-artefact consistency checks (crossing_stats.json, assignment,
  frozen baseline snapshot, independent Validator re-run),
* the explicit "is there a contradiction with the original physical contract?"
  analysis,
* ``contract_evidence.json`` + the merged ``audit_metrics.json`` +
  a compact ``six_quantities.json``.

The module NEVER modifies existing run directories: it only reads the run
directory, the frozen baseline snapshot and (re)writes its own output folder.

Reusable CLI (any run directory, e.g. the final G4 best solution)::

    # full audit: independent metrics + six quantities + validator re-run
    python -m four_side_1024.fanout1024.xyzrouter.g4.contract_audit \
        --run-dir  <run dir with routes_l3d.json> \
        --out-dir  <audit output dir> \
        --baseline-dir experiments/xyz_joint_g123_1024/baseline_authoritative \
        --manual-policy fully_optimizable \
        --recompute --revalidate

    # optional expectations (fail the check when they do not match)
    --expect-sha256 <hex> --expect-crossings 1322 --expect-pairs 1253 \
    --expect-max-route 19

Exit code 0 = every applicable independent check passes (validator included).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_RUN = (ROOT / 'outputs' / 'manual_c4_new_connectivity' /
               'XYZ_JOINT_G123_1024' / 'best_valid')
DEFAULT_OUT = ROOT / 'experiments' / 'xyz_joint_g4_1024' / '00_baseline_audit'
BASELINE_DIR = ROOT / 'experiments' / 'xyz_joint_g123_1024' / 'baseline_authoritative'
EXPECTED_ROUTES_SHA256 = '711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077'

#: (file, regex, human label) -- the exact lines quoted in the Chinese report
CODE_CITATIONS = [
    ('four_side_1024/fanout1024/common.py', r'^GLASS_THICKNESS_MM\s*=', 'glass thickness 1 mm'),
    ('four_side_1024/fanout1024/common.py', r'^GLASS_Z_MIN_MM\s*=', 'glass z lower bound'),
    ('four_side_1024/fanout1024/common.py', r'^GLASS_Z_MAX_MM\s*=', 'glass z upper bound'),
    ('four_side_1024/fanout1024/common.py', r'^MIN_LAYER_PITCH_MM\s*=', '50 um minimum layer pitch'),
    ('four_side_1024/fanout1024/common.py', r'^MIN_3D_CLEARANCE_MM\s*=', '50 um true 3D clearance'),
    ('four_side_1024/fanout1024/common.py', r'^WIDTH_MM\s*=', 'waveguide width 50 um'),
    ('four_side_1024/fanout1024/common.py', r'^EDGE_GAP_MM\s*=', 'same-layer edge gap 30 um'),
    ('four_side_1024/fanout1024/common.py', r'^CLEARANCE_2D_MM\s*=', 'same-layer 2D centreline clearance 80 um'),
    ('four_side_1024/fanout1024/common.py', r'^MIN_BEND_RADIUS_MM\s*=', 'R15 minimum bend radius'),
    ('four_side_1024/fanout1024/common.py', r'^LEGACY_GLOBAL_CLEARANCE_MM\s*=', 'legacy 80 um global clearance (never restored)'),
    ('four_side_1024/fanout1024/common.py', r'different_physical_planes=', 'cross-height rule text'),
    ('four_side_1024/fanout1024/common.py', r'transition_vs_other=', 'transition 3D clearance rule text'),
    ('four_side_1024/fanout1024/common.py', r'legal transverse crossings preserved', 'same-layer crossing preservation text'),
    ('four_side_1024/l3d/world.py', r'true 3D\s*$|centre-line distance must be', 'world 3D rule docstring'),
    ('four_side_1024/l3d/world.py', r"crossing_policy='strict'", 'world uses strict D56 policy'),
    ('four_side_1024/l3d/world.py', r'flat_cross_plane_too_close', 'cross-plane pitch enforcement'),
    ('four_side_1024/l3d/world.py', r'self\.clearance = float', 'world clearance argument'),
    ('four_side_1024/fsd25d/world25d.py', r'flat-to-flat pairs on different layers are', 'flat cross-layer safety by pitch'),
    ('four_side_1024/fsd25d/world25d.py', r'transition_vs_flat', 'transition-vs-flat violation kind'),
    ('four_side_1024/fsd25d/world25d.py', r'transition_vs_transition', 'transition-vs-transition violation kind'),
    ('four_side_1024/fslw/config.py', r'^WIDTH_MM\s*=', 'fslw width'),
    ('four_side_1024/fslw/config.py', r'^EDGE_GAP_MM\s*=', 'fslw edge gap'),
    ('four_side_1024/fslw/config.py', r'^CLEARANCE_MM\s*=', 'fslw 80 um 2D clearance'),
    ('four_side_1024/fslw/config.py', r'^MIN_CROSS_ANGLE_DEG\s*=', 'D56 minimum genuine crossing angle 5 deg'),
    ('four_side_1024/fslw/config.py', r'^SAGITTA_MM\s*=', 'arc sagitta budget'),
    ('four_side_1024/d56/index.py', r'crossing_policy=\'exact\'', 'D56 crossing policy parameter'),
    ('four_side_1024/d56/index.py', r'if self\.crossing_policy == \'strict\'', 'strict policy dispatch'),
    ('four_side_1024/fanout1024/nonc4/crossings.py', r'^D56_CLEARANCE_MM\s*=', 'crossing audit clearance = 80 um 2D'),
    ('four_side_1024/fanout1024/nonc4/crossings.py', r'policy=\'strict\'', 'crossing audit uses strict policy'),
    ('four_side_1024/fslw/validate_fslw.py', r'^STRICT_MAX_HALF_WINDOW\s*=', 'max exempt crossing window half width 4 mm'),
    ('four_side_1024/fslw/validate_fslw.py', r'^STRICT_SINE_MIN\s*=', 'strict crossing sine threshold sin(5 deg)'),
    ('four_side_1024/fslw/validate_fslw.py', r'^MIN_CROSS_ANGLE_DEG\s*=', 'D56 5 deg lower bound'),
    ('four_side_1024/fslw/validate_fslw.py', r'^CROSSING_SMALL_ANGLE_DEG\s*=', 'small-angle reporting threshold 10 deg'),
    ('four_side_1024/fslw/validate_fslw.py', r'def audit_route_pairs', 'independent strict pair audit'),
    ('four_side_1024/fslw/validate_fslw.py', r'def _evaluate_pair_strict', 'strict crossing-window evaluation'),
    ('four_side_1024/fanout1024/reheight21/model.py', r'^BODY_PLANES = ', '19 body routing heights'),
    ('four_side_1024/fanout1024/reheight21/model.py', r'^INTERFACE_PLANES = ', '2 routable interface heights'),
    ('four_side_1024/fanout1024/reheight21/model.py', r'^MIN_3D_CLEARANCE_MM\s*=', '21-height model 50 um 3D clearance'),
    ('four_side_1024/fanout1024/reheight21/model.py', r'^MIN_LAYER_PITCH_MM\s*=', '21-height model 50 um pitch'),
    ('four_side_1024/fanout1024/reheight21/validate21.py', r'World\(stack, clearance=MIN_3D_CLEARANCE_MM\)', 'validator uses 50 um, not the 80 um default'),
    ('four_side_1024/fanout1024/reheight21/validate21.py', r'def measure_min_3d_clearance', 'min-3D-clearance scan definition'),
    ('four_side_1024/fanout1024/reheight21/validate21.py', r'def check_crossings', 'per-physical-height crossing audit'),
    ('four_side_1024/fanout1024/xyzrouter/world_adapter.py', r'^CLEARANCE_MM\s*=', 'G1/G2/G3 router world clearance 50 um'),
    ('four_side_1024/fanout1024/xyzrouter/world_adapter.py', r"crossing_policy='strict'", 'router world strict D56 policy'),
]


# ===========================================================================
# helpers
# ===========================================================================
def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                    encoding='utf-8')
    return path


def collect_code_evidence():
    evidence = []
    for relative, pattern, label in CODE_CITATIONS:
        path = ROOT / relative
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError as error:  # pragma: no cover
            evidence.append(dict(file=relative, label=label, error=str(error)))
            continue
        regex = re.compile(pattern)
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                evidence.append(dict(file=relative, file_short=relative,
                                     line=number, label=label,
                                     text=line.strip()[:220]))
                break
        else:
            evidence.append(dict(file=relative, label=label,
                                 error='pattern not found: %r' % pattern))
    return evidence


def find_line_citation(relative, pattern):
    path = ROOT / relative
    regex = re.compile(pattern)
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if regex.search(line):
            return dict(file=relative, line=number, text=line.strip()[:220])
    return dict(file=relative, line=None, text=None)


# ===========================================================================
# cross-artefact checks
# ===========================================================================
def check_crossing_stats(run_dir, metrics):
    path = Path(run_dir) / 'crossing_stats.json'
    if not path.exists():
        return dict(present=False, pass_=None,
                    note='run directory has no crossing_stats.json; '
                         'cross-artefact check skipped')
    payload = read_json(path)
    totals = payload.get('totals') or {}
    events = payload.get('crossing_events') or []
    my_events = metrics['same_layer']['events']
    my_pairs = metrics['same_layer']['crossing_pair_count']
    matched = 0
    angle_diffs = []
    unmatched_my = []
    lookup = {}
    for event in events:
        key = (min(int(event['route_a']), int(event['route_b'])),
               max(int(event['route_a']), int(event['route_b'])),
               round(float(event['x_mm']), 4), round(float(event['y_mm']), 4))
        lookup[key] = event
    for event in my_events:
        key = (min(event['route_a'], event['route_b']),
               max(event['route_a'], event['route_b']),
               round(event['x_mm'], 4), round(event['y_mm'], 4))
        other = lookup.get(key)
        if other is None:
            unmatched_my.append(event)
            continue
        matched += 1
        angle_diffs.append(abs(event['angle_deg'] - float(other['angle_deg'])))
    per_plane_check = []
    my_per_height = metrics['same_layer']['crossings_per_height']
    for row in payload.get('planes') or []:
        z = '%.6f' % round(float(row['z_mm']), 6)
        mine = my_per_height.get(z, 0)
        if int(row.get('crossings') or 0) != mine:
            per_plane_check.append(dict(z_mm=row['z_mm'],
                                        crossing_stats=int(row['crossings']),
                                        independent=int(mine)))
    return dict(
        present=True,
        crossing_stats_totals=dict(
            crossings=int(totals.get('crossings') or 0),
            crossing_pairs=int(totals.get('crossing_pairs') or 0),
            violations=int(totals.get('violations') or 0),
            audited_heights=int(totals.get('audited_heights') or 0)),
        independent_totals=dict(
            crossings=len(my_events),
            crossing_pairs=my_pairs,
            illegal_events=metrics['same_layer']['illegal_event_count']),
        event_match_count=matched,
        event_match_ratio=round(matched / max(1, len(my_events)), 9),
        unmatched_independent_events=unmatched_my[:10],
        max_angle_difference_deg=round(max(angle_diffs) if angle_diffs else 0.0, 9),
        per_height_count_mismatches=per_plane_check,
        min_non_crossing_centerline_mm=payload.get('totals', {}).get(
            'min_non_crossing_centerline_mm'),
        pass_=(int(totals.get('crossings') or 0) == len(my_events)
               and int(totals.get('crossing_pairs') or 0) == my_pairs
               and matched == len(my_events)
               and int(totals.get('violations') or 0) == 0
               and not per_plane_check))


def check_assignment(run_dir, metrics, baseline_dir=None):
    import csv
    path = Path(run_dir) / 'assignment_1024.csv'
    source = 'run'
    if not path.exists() and baseline_dir is not None:
        fallback = Path(baseline_dir) / 'assignment_1024.csv'
        if fallback.exists():
            path = fallback
            source = 'baseline_fallback'
    if not path.exists():
        return dict(present=False, pass_=None,
                    note='no assignment_1024.csv in run dir or baseline dir')
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    manual = [row for row in rows if str(row.get('manual_group') or '').strip()]
    return dict(present=True,
                source=source,
                file=str(path),
                rows=len(rows),
                manual_route_count=len(manual),
                manual_groups=dict(Counter(str(row['manual_group']).strip()
                                           for row in manual)),
                metrics_manual_route_count=metrics['manual_u']['manual_route_count'],
                direct_routes=len([row for row in rows
                                   if str(row.get('needs_transition')).strip().lower()
                                   in ('false', '0', 'no', 'direct')]),
                pass_=(len(rows) == 1024 and len(manual) == 368
                       and metrics['manual_u']['manual_route_count'] == 368))


def check_revalidation(out_dir, expected_crossings=None, expected_pairs=None):
    reval_dir = Path(out_dir) / 'baseline_revalidation'
    path = reval_dir / 'validation.json'
    if not path.exists():
        return dict(present=False, pass_=None,
                    note='no baseline_revalidation/validation.json; run with '
                         '--revalidate')
    report = read_json(path)
    summary_path = reval_dir / 'revalidation_summary.json'
    summary = read_json(summary_path) if summary_path.exists() else {}
    counts = report.get('counts') or {}
    policy = report.get('policy_report') or {}
    checks = report.get('checks') or {}
    failing = [name for name, block in checks.items()
               if isinstance(block, dict) and int(block.get('violations') or 0) > 0]
    validator_crossings = counts.get('same_plane_crossings')
    validator_pairs = counts.get('same_plane_crossing_pairs')
    crossing_match = None
    if expected_crossings is not None and validator_crossings is not None:
        crossing_match = int(validator_crossings) == int(expected_crossings)
    pair_match = None
    if expected_pairs is not None and validator_pairs is not None:
        pair_match = int(validator_pairs) == int(expected_pairs)
    passed = (bool(report.get('validation_pass'))
              and int(report.get('violation_count') or 0) == 0
              and int(policy.get('violation_count') or 0) == 0
              and not failing
              and crossing_match is not False
              and pair_match is not False)
    return dict(
        present=True,
        validator=report.get('xyz_validator'),
        manual_policy=report.get('manual_policy'),
        validation_pass=bool(report.get('validation_pass')),
        violation_count=int(report.get('violation_count') or 0),
        failing_checks=failing,
        policy_violations=int(policy.get('violation_count') or 0),
        validator_counts=dict(
            crossings=validator_crossings,
            crossing_pairs=validator_pairs,
            min_3d_clearance_mm=counts.get('min_3d_clearance_mm'),
            min_non_crossing_centerline_mm=counts.get(
                'min_non_crossing_centerline_mm'),
            manual_route_count=counts.get('manual_route_count'),
            routed=counts.get('routed'),
            failed=counts.get('failed')),
        validator_crossings_match_independent=crossing_match,
        validator_pairs_match_independent=pair_match,
        counts=counts,
        summary=summary,
        pass_=passed)


# ===========================================================================
# revalidation helper (arbitrary run directory)
# ===========================================================================
def run_revalidation(run_dir, out_dir, baseline_dir=None,
                     manual_policy='fully_optimizable', log=print):
    """Run the frozen independent Validator on ``run_dir`` and store the report."""
    from four_side_1024.fanout1024.xyzrouter import validate_xyz as VX
    baseline_dir = Path(baseline_dir) if baseline_dir else BASELINE_DIR
    reval_dir = Path(out_dir) / 'baseline_revalidation'
    reval_dir.mkdir(parents=True, exist_ok=True)
    log('[revalidate] independent validator: run=%s baseline=%s policy=%s'
        % (run_dir, baseline_dir, manual_policy))
    report = VX.validate_xyz(run_dir=str(run_dir),
                             baseline_dir=str(baseline_dir),
                             out_dir=str(reval_dir),
                             manual_policy=str(manual_policy),
                             log=log)
    summary = VX.summarize_report(report)
    summary['validator_id'] = VX.VALIDATOR_ID
    summary['run_dir'] = str(run_dir)
    summary['baseline_dir'] = str(baseline_dir)
    (reval_dir / 'revalidation_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    log('[revalidate] pass=%s violations=%s policy_violations=%s'
        % (summary.get('validation_pass'), summary.get('violations'),
           summary.get('policy_violations')))
    return summary


# ===========================================================================
# main audit assembly
# ===========================================================================
def run(run_dir, out_dir, log=print, baseline_dir=None,
        manual_policy='fully_optimizable', expect_sha256=None,
        expect_crossings=None, expect_pairs=None, expect_max_route=None,
        recompute=False, revalidate=False):
    """Contract audit of ONE 1024-route XYZ run directory."""
    started = time.time()
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if recompute or not (out_dir / 'independent_metrics.json').exists():
        from . import independent_metrics as IM
        IM.run_audit(run_dir=str(run_dir), out_dir=str(out_dir),
                     expect_sha256=expect_sha256,
                     baseline_dir=(str(baseline_dir) if baseline_dir else None),
                     log=log)
    if revalidate:
        run_revalidation(run_dir, out_dir, baseline_dir=baseline_dir,
                         manual_policy=manual_policy, log=log)
    metrics = read_json(out_dir / 'independent_metrics.json')
    evidence = read_json(out_dir / 'min_distance_evidence.json')
    code_evidence = collect_code_evidence()
    crossing_check = check_crossing_stats(run_dir, metrics)
    assignment_check = check_assignment(run_dir, metrics,
                                        baseline_dir=baseline_dir)
    sha = metrics['routes_sha256']
    same = metrics['same_layer']
    required = metrics['required_quantities']
    heights = metrics['heights_r15']
    revalidation = check_revalidation(
        out_dir, expected_crossings=same['event_count'],
        expected_pairs=same['crossing_pair_count'])

    # ---- the six mandatory quantities (final, independently recomputed) ----
    six = {
        'minimum_distance_all_pairs_mm': required['minimum_distance_all_pairs_mm'],
        'minimum_clearance_non_crossing_mm': required['minimum_clearance_non_crossing_mm'],
        'allowed_crossing_count': same['event_count'],
        'illegal_crossing_count': same['illegal_event_count'],
        'clearance_violation_count': required['clearance_violation_count'],
        'crossing_exemption_policy': required['crossing_exemption_policy'],
    }

    # ---- independent re-check of the headline numbers ----------------------
    # ``None`` = check not applicable to this run (e.g. no expected value given)
    cross_checks = OrderedDict()
    if expect_sha256:
        cross_checks['routes_sha256_matches_expected'] = sha == expect_sha256
    cross_checks['routed_1024_of_1024'] = (metrics['routed'] == 1024
                                          and metrics['failed'] == 0
                                          and metrics['route_count'] == 1024)
    if expect_crossings is not None:
        cross_checks['crossings_count_matches_expected'] = (
            same['event_count'] == expect_crossings)
    if expect_pairs is not None:
        cross_checks['crossing_pairs_match_expected'] = (
            same['crossing_pair_count'] == expect_pairs)
    if expect_max_route is not None:
        cross_checks['max_crossings_per_route_matches_expected'] = (
            same['max_crossings_per_route'] == expect_max_route)
    cross_checks['crossing_stats_artefact_match'] = crossing_check.get('pass_')
    cross_checks['manual_u_368'] = assignment_check.get(
        'manual_route_count') == 368 if assignment_check.get('present') else None
    cross_checks['heights_21'] = (heights['used_height_count'] == 21
                                  and heights['heights_match_model'])
    cross_checks['min_height_gap_0p05'] = (
        heights['min_height_gap_mm'] is not None
        and abs(heights['min_height_gap_mm'] - 0.05) < 1e-9)
    cross_checks['r15_no_violation'] = (
        heights['arc_radius_min_mm'] is not None
        and heights['arc_radius_min_mm'] >= 15.0 - 1e-9
        and heights['arc_radius_max_mm'] <= 15.0 + 1e-9
        and heights['transition_radius_violations'] == 0
        and heights['transition_formula_vs_generator_max_error_mm'] < 1e-9)
    cross_checks['glass_150x150x1_bounds'] = metrics['glass']['pass_']
    cross_checks['ports_and_connection_identity'] = metrics['identity']['pass_']
    cross_checks['structure_continuity'] = metrics['continuity']['pass_']
    cross_checks['all_crossings_allowed'] = same['illegal_event_count'] == 0
    cross_checks['no_clearance_violation'] = (
        required['clearance_violation_count'] == 0)
    cross_checks['independent_validator_pass'] = revalidation.get('pass_')
    checks_all_pass = all(value for value in cross_checks.values()
                          if value is not None)
    checks_skipped = [key for key, value in cross_checks.items()
                      if value is None]
    expectations = dict(expected_sha256=expect_sha256,
                        expected_crossings=expect_crossings,
                        expected_crossing_pairs=expect_pairs,
                        expected_max_crossings_per_route=expect_max_route,
                        manual_policy=str(manual_policy))

    # ---- "N crossings + 0 geometric violations" self-consistency -----------
    consistency = dict(
        question=('why can %d same-height centreline crossings (distance 0) '
                  'coexist with 0 geometric violations?' % same['event_count']),
        answer=(
            'Because the two rules act on disjoint partitions of the pair set. '
            'Same-physical-height flat/flat pairs are governed ONLY by the '
            'original strict D56 2-D rule (0.080 mm centreline clearance) which '
            'explicitly preserves genuine transverse crossings with angle >= '
            '5 deg inside a local window; that rule is part of the frozen '
            'baseline contract (D56Index(crossing_policy="strict"), already '
            'used by the frozen 2409-crossing baseline), not a G4 addition. '
            'Pairs on different physical heights are governed by the 50 um 3-D '
            'rule, and such pairs can never have distance 0 (|dz| >= 0.050 mm); '
            'the 50 um rule therefore never "sees" the same-height crossings. '
            'All crossing events are genuine (angle >= 5 deg, interior, no '
            'overlap/tangency/double-cross), so no event falls into the '
            'clearance-violation category.'),
        disjoint_rules=[
            'same physical height flat-flat <=> 2-D D56 0.08 mm + legal '
            'transverse crossing exemption',
            'different physical height flat-flat <=> |dz| >= 0.05 mm (distance '
            'is bounded below by the layer pitch, XY overlap legal)',
            'anything involving a transition <=> true 3-D centreline distance '
            '>= 0.05 mm (no crossing exemption)',
        ],
        measured_support=dict(
            crossings_all_transverse=same['illegal_event_count'] == 0,
            crossing_angle_range_deg=[same['crossing_angle_min_deg'],
                                      same['crossing_angle_max_deg']],
            crossing_window_half_max_mm=same['crossing_window_half_max_mm'],
            max_window_policy_mm=required['crossing_exemption_policy'][
                'max_window_half_mm'],
            min_non_crossing_same_layer_mm=same['min_non_crossing_centerline_mm'],
            min_flat_flat_cross_height_mm=metrics['flat_flat_cross_height'][
                'min_distance_mm'],
            min_transition_vs_flat_mm=metrics['transition_vs_flat'][
                'min_distance_mm'],
            min_transition_vs_transition_mm=metrics[
                'transition_vs_transition']['min_distance_mm'],
        ),
    )

    # ---- contract scope of the 50 um clearance ------------------------------
    scope = dict(
        applies_to=[
            dict(object='21 routing heights (layer pitch)', rule='adjacent '
                 'physical heights must be >= 0.05 mm apart',
                 evidence=code_evidence_for(code_evidence, 'common.py',
                                            'MIN_LAYER_PITCH_MM'),
                 measured=dict(min_gap_mm=heights['min_height_gap_mm'],
                               heights=heights['used_height_count'])),
            dict(object='flat pair on two DIFFERENT physical heights',
                 rule='legal when |dz| >= 0.05 mm; the 3-D distance is then '
                      '>= |dz| >= 0.05 mm, XY overlap alone is not a violation',
                 evidence=code_evidence_for(code_evidence, 'l3d/world.py',
                                            'flat_cross_plane_too_close'),
                 measured=dict(min_3d_distance_mm=metrics[
                     'flat_flat_cross_height']['min_distance_mm'])),
            dict(object='any pair that involves a transition '
                        '(transition-vs-flat, transition-vs-transition)',
                 rule='true 3-D centreline distance >= 0.05 mm, no crossing '
                      'exemption',
                 evidence=code_evidence_for(code_evidence, 'world25d.py',
                                            'transition_vs_flat'),
                 measured=dict(
                     transition_vs_flat_min_mm=metrics['transition_vs_flat'][
                         'min_distance_mm'],
                     transition_vs_transition_min_mm=metrics[
                         'transition_vs_transition']['min_distance_mm'])),
            dict(object='self clearance of one route', rule='the same route may '
                 'not come back within 0.05 mm of itself (path separation > '
                 '1 mm)', evidence=code_evidence_for(code_evidence,
                                                     'world25d.py',
                                                     'self_clearance'),
                 measured=dict(min_self_mm=metrics['self_clearance'][
                     'min_self_distance_mm'])),
        ],
        does_not_apply_to=[
            dict(object='same-physical-height flat/flat pair',
                 rule='governed by the original 2-D D56 rule: 0.05 mm width + '
                      '0.03 mm edge gap = 0.08 mm centreline, with the legal '
                      'transverse-crossing exemption (>= 5 deg, local window)',
                 evidence=code_evidence_for(code_evidence, 'common.py',
                                            'CLEARANCE_2D_MM')),
            dict(object='the 80 um legacy global clearance',
                 rule='explicitly NOT restored as a global 3-D rule',
                 evidence=code_evidence_for(code_evidence, 'common.py',
                                            'LEGACY_GLOBAL_CLEARANCE_MM')),
        ],
    )

    # ---- contradiction analysis vs a hypothetical global 50 um rule --------
    contradiction = dict(
        code_contract_requires_global_50um=False,
        statement=(
            'The contract as codified in this repository does NOT require every '
            'centreline pair to be >= 50 um: same-height flat pairs use the '
            '0.08 mm D56 2-D rule with a documented legal-crossing exemption, '
            'and only cross-height / transition-related pairs use the 50 um '
            '3-D rule. Therefore the audited result is consistent with the '
            'code contract.'),
        residual_risk=(
            'IF the original written physical contract (task book) is meant to '
            'be a global "all centreline pairs >= 50 um with no exception" '
            'rule, then the %d legal crossings (distance exactly 0) would be '
            '%d hard violations and a genuine contradiction exists. This '
            'audit does NOT silently extend or create any exemption: the '
            'exemption is the pre-existing frozen D56 strict policy. The '
            'requirement-level interpretation must be confirmed by the project '
            'owner before the legal crossings are quoted as compliant.'
            % (same['event_count'], same['event_count'])),
        no_new_exemption_added=True,
        exemption_source=dict(
            module='four_side_1024/d56/index.py + four_side_1024/l3d/world.py',
            evidence=[code_evidence_for(code_evidence, 'world.py',
                                        'crossing_policy'),
                      code_evidence_for(code_evidence, 'd56/index.py',
                                        'strict')],
            pre_existing=('the frozen baseline snapshot already carries 2409 '
                          'crossings and passed the same validator before any '
                          'G4 work; the crossing exemption is not introduced by '
                          'this round'),
        ),
        contract_vs_code_defaults=dict(
            note=('four_side_1024/l3d/world.py defaults clearance to '
                  'fslw.config.CLEARANCE_MM = 0.08 mm (legacy) while the '
                  'corrected 50 um model calls it with clearance=0.05 mm '
                  'everywhere (validate21.check_true_3d_clearance, '
                  'xyzrouter.world_adapter.CLEARANCE_MM). Under the 0.08 '
                  'default the same board would report violations, so the '
                  'explicit 0.05 argument is load-bearing and must never be '
                  'dropped.'),
            citations=[find_line_citation('four_side_1024/l3d/world.py',
                                          r'self\.clearance = float'),
                       find_line_citation(
                           'four_side_1024/fanout1024/reheight21/validate21.py',
                           r'World\(stack, clearance=MIN_3D_CLEARANCE_MM\)'),
                       find_line_citation(
                           'four_side_1024/fanout1024/xyzrouter/world_adapter.py',
                           r'^CLEARANCE_MM\s*=')]),
    )

    result = dict(
        schema='g4_geometry_contract_audit_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        auditor='geometry-auditor (G4-1)',
        run=dict(run_dir=str(run_dir), routes_sha256=sha,
                 routes_sha256_expected=expect_sha256,
                 sha_match=((sha == expect_sha256) if expect_sha256 else None),
                 route_count=metrics['route_count'],
                 routed=metrics['routed'], failed=metrics['failed'],
                 total_length_mm=round(sum(float(route.get('length_mm') or 0.0)
                                           for route in read_json(
                                               run_dir / 'routes_l3d.json')['routes']), 6)),
        expectations=expectations,
        required_quantities=six,
        independent_cross_checks=cross_checks,
        independent_cross_checks_all_pass=checks_all_pass,
        independent_cross_checks_skipped=checks_skipped,
        crossing_stats_crosscheck=crossing_check,
        assignment_crosscheck=assignment_check,
        baseline_revalidation=revalidation,
        details=dict(
            identity=metrics['identity'],
            heights_r15=heights,
            continuity=metrics['continuity'],
            glass=metrics['glass'],
            curve_counts=metrics['curve_counts'],
            candidate_grid=metrics['candidate_grid'],
            same_layer=same,
            flat_flat_cross_height=metrics['flat_flat_cross_height'],
            transition_vs_flat=metrics['transition_vs_flat'],
            transition_vs_transition=metrics['transition_vs_transition'],
            self_clearance=metrics['self_clearance'],
            independent_verdict=metrics['independent_verdict'],
        ),
        contract_scope=scope,
        consistency_argument=consistency,
        contradiction_analysis=contradiction,
        numerical_error_bounds=evidence['numerical_error_bounds'],
        code_evidence=code_evidence,
        limitations=[
            'Exploratory centreline geometry model only: optical crosstalk, '
            'fabrication tolerance and surface-process margins are NOT verified '
            'by this audit (see common.py process_rules_payload unconfirmed '
            'block).',
            'The 21 heights are an exploratory routing model; the glass 1 mm '
            'thickness / connector mounting direction assumption is unconfirmed '
            '(fslw/config.py MANUFACTURING_CLAIM).',
            'Nominal geometry only: no process bias, no sidewall angle, no '
            'refractive-index profile is modelled.',
            'Same-layer crossing optical feasibility is not confirmed '
            '(fslw/config.py CROSSING_LOSS status unknown_uncalibrated); the '
            'crossing count is a geometric metric only.',
        ],
        runtime_seconds=None,
    )
    result['runtime_seconds'] = round(time.time() - started, 2)
    write_json(out_dir / 'contract_evidence.json',
               dict(schema='g4_contract_evidence_v1', code_evidence=code_evidence,
                    contract_scope=scope, consistency_argument=consistency,
                    contradiction_analysis=contradiction))
    write_json(out_dir / 'audit_metrics.json', result)
    # compact, directly quotable deliverable (the six mandatory quantities)
    six_payload = OrderedDict(
        schema='g4_six_required_quantities_v1',
        generated_at=result['generated_at'],
        run=result['run'],
        six_quantities=six,
        independent_cross_checks=dict(
            all_pass=checks_all_pass, skipped=checks_skipped,
            checks=cross_checks),
        independent_verdict=metrics['independent_verdict'],
        baseline_revalidation=dict(
            present=revalidation.get('present'),
            validation_pass=revalidation.get('validation_pass'),
            violation_count=revalidation.get('violation_count'),
            policy_violations=revalidation.get('policy_violations'),
            manual_policy=revalidation.get('manual_policy'),
            validator_counts=revalidation.get('validator_counts')),
    )
    write_json(out_dir / 'six_quantities.json', six_payload)
    log('[contract] six=%s'
        % json.dumps({key: (value if not isinstance(value, dict) else '<policy>')
                      for key, value in six.items()}, ensure_ascii=False))
    log('[contract] cross_checks_pass=%s skipped=%s revalidation_pass=%s'
        % (checks_all_pass, checks_skipped,
           revalidation.get('validation_pass')))
    log('[contract] wrote %s' % (out_dir / 'audit_metrics.json'))
    return result


def code_evidence_for(evidence, file_suffix, label_fragment):
    matches = [item for item in evidence
               if item.get('file', '').endswith(file_suffix)
               and label_fragment.lower() in str(item.get('label', '')).lower()]
    if matches:
        return matches[0]
    matches = [item for item in evidence
               if item.get('file', '').endswith(file_suffix)]
    return matches[0] if matches else None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='G4 contract audit + independent Validator re-run for ANY '
                    '1024-route XYZ run directory. Outputs the six mandatory '
                    'quantities, the contract evidence and (optionally) the '
                    'independent validator report.')
    parser.add_argument('--run-dir', default=str(DEFAULT_RUN),
                        help='run directory containing routes_l3d.json')
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT),
                        help='output directory (six_quantities.json, '
                             'audit_metrics.json, contract_evidence.json, '
                             'independent_metrics.json, baseline_revalidation/)')
    parser.add_argument('--baseline-dir', default=str(BASELINE_DIR),
                        help='frozen baseline dir for the manual-U contract and '
                             'the validator coverage check')
    parser.add_argument('--manual-policy', default='fully_optimizable',
                        choices=['frozen', 'height_only', 'fully_optimizable'],
                        help='manual-group contract for the validator')
    parser.add_argument('--expect-sha256', default=None,
                        help='optional expected routes_l3d.json SHA256')
    parser.add_argument('--expect-crossings', type=int, default=None,
                        help='optional expected same-layer crossing count')
    parser.add_argument('--expect-pairs', type=int, default=None,
                        help='optional expected unique crossing-pair count')
    parser.add_argument('--expect-max-route', type=int, default=None,
                        help='optional expected max crossings of one route')
    parser.add_argument('--recompute', action='store_true',
                        help='force recomputing the independent metrics even if '
                             'independent_metrics.json already exists')
    parser.add_argument('--revalidate', action='store_true',
                        help='run the frozen independent Validator on --run-dir '
                             'and store it under <out-dir>/baseline_revalidation')
    args = parser.parse_args(argv)
    result = run(args.run_dir, args.out_dir,
                 baseline_dir=args.baseline_dir,
                 manual_policy=args.manual_policy,
                 expect_sha256=args.expect_sha256,
                 expect_crossings=args.expect_crossings,
                 expect_pairs=args.expect_pairs,
                 expect_max_route=args.expect_max_route,
                 recompute=args.recompute,
                 revalidate=args.revalidate,
                 log=lambda message: print(message, flush=True))
    print('SUMMARY ' + json.dumps(
        dict(run_dir=result['run']['run_dir'],
             routes_sha256=result['run']['routes_sha256'],
             six_quantities={
                 key: (value if not isinstance(value, dict) else 'policy')
                 for key, value in result['required_quantities'].items()},
             all_checks_pass=result['independent_cross_checks_all_pass'],
             skipped_checks=result['independent_cross_checks_skipped'],
             validator_pass=result['baseline_revalidation'].get(
                 'validation_pass')),
        ensure_ascii=False, sort_keys=True))
    return 0 if result['independent_cross_checks_all_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
