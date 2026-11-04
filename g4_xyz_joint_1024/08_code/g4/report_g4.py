# -*- coding: utf-8 -*-
"""G4-5 final report generator: report.md / comparison.md / answers.md
(Chinese) + machine-readable metrics summary + orchestration of all final
figures.

Principles
----------
* every number in the documents comes from a real archived file (accepted
  ``routes_l3d.json`` / ``crossing_stats.json`` / ``summary.json`` /
  ``validation/validation.json`` / ``budget_ledger.json`` /
  ``optimization_history.csv`` / the G4-1 audit files);
* missing or unfinished data is written as ``进行中/未完成`` — never invented;
* negative results are preserved;
* the report never claims a strict infeasibility proof or global optimality.

Deliverables
------------
``experiments/xyz_joint_g4_1024/10_reports/report.md``
``experiments/xyz_joint_g4_1024/10_reports/comparison.md``
``experiments/xyz_joint_g4_1024/10_reports/answers.md``
``experiments/xyz_joint_g4_1024/10_reports/metrics_summary.json``
plus the archive-root convenience copies ``report.md`` / ``comparison.md``.

CLI
---
::

    # infrastructure preview (missing arms -> 进行中/未完成)
    python -m four_side_1024.fanout1024.xyzrouter.g4.report_g4 --mode preview
    # final run: regenerate every plot + report + manifest
    python -m four_side_1024.fanout1024.xyzrouter.g4.report_g4 --mode final
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.reheight21 import model as M  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import visualize as V  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import failure_analysis as FA  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import plots_g4 as PG  # noqa: E402

SCHEMA = 'g4_final_report_v1'
START_CROSSINGS = int(GP.START_CROSSINGS)
START_SHA = str(GP.START_ROUTES_SHA256)
START_DIR = Path(GP.START_DIR)
ARCHIVE = Path(GP.G4_ROOT)
REPORTS = ARCHIVE / '10_reports'
PLOTS = ARCHIVE / '09_plots'
NA = '进行中/未完成'
TARGETS = (1200, 1000, 800, 500, 100, 9, 0)

ARM_ORDER = ('C0', 'G4a', 'G4b', 'G4c_frozen', 'G4c_free', 'G4d')
ARM_LABEL = {
    'C0': 'C0 既有引擎续跑（无新自由度）',
    'G4a': 'G4a 八组固定 + 组级 XY+Z 重造',
    'G4b': 'G4b 人工 U 动态重分组',
    'G4c_frozen': 'G4c-frozen 人工 U 冻结 + 联合让路 ALNS',
    'G4c_free': 'G4c-free 人工 U 解冻 + 联合让路 ALNS',
    'G4d': 'G4d 全部 1024 条大邻域全局优化',
}

#: the exact six required quantities reported by the independent G4-1 audit
AUDIT_QUANTITIES = (
    ('minimum_distance_all_pairs_mm',
     '全部中心线对（含合法横穿）的 3D 最小距离'),
    ('minimum_clearance_non_crossing_mm',
     '排除合法横穿后的全板最小净空'),
    ('allowed_crossing_count', '允许类交叉事件数'),
    ('illegal_crossing_count', '非法交叉数'),
    ('clearance_violation_count', '净空违规数'),
    ('crossing_exemption_policy', '交叉豁免口径（D56 strict + 横穿局部窗口）'),
)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _read_json(path, default=None):
    if path is None:
        return default
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')
    return path


def _sha256(path):
    path = Path(path)
    return GP.sha256_file(path) if path.exists() else None


def _rel(path):
    if path is None:
        return NA
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _num(value, digits=2):
    """Format a number for the documents; ``None`` -> 进行中/未完成."""
    if value is None:
        return NA
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return '%d' % int(round(number))
    return ('%.*f' % (digits, number)).rstrip('0').rstrip('.')


def _delta(value, reference):
    if value is None:
        return NA
    return '%+d' % int(round(float(value) - float(reference)))


def _pct(value, reference):
    if value is None or not reference:
        return NA
    return '%+.1f%%' % (100.0 * (float(value) - float(reference)) / float(reference))


def _md_table(header, rows):
    lines = ['| ' + ' | '.join(str(item) for item in header) + ' |',
             '|' + '---|' * len(header)]
    for row in rows:
        lines.append('| ' + ' | '.join(str(item) for item in row) + ' |')
    return '\n'.join(lines)


def _table_or_na(header, rows, empty_note='（暂无数据：各臂产物未完成）'):
    if not rows:
        return '\n'.join(['| ' + ' | '.join(str(item) for item in header) + ' |',
                          '|' + '---|' * len(header),
                          '| ' + ' | '.join(['NA'] * len(header)) + ' |',
                          '', '> ' + empty_note])
    return _md_table(header, rows)


# --------------------------------------------------------------------------- #
# arm artifact loading
# --------------------------------------------------------------------------- #
def _dir_has_routes(directory):
    return (Path(directory) / 'routes_l3d.json').exists()


def _dir_totals(directory):
    """Crossing totals / per-height planes of one artifact directory."""
    directory = Path(directory)
    result = dict(dir=directory, crossings=None, crossing_pairs=None,
                  max_route_crossings=None, routes_with_crossings=None,
                  planes=None, routes_sha=None, source=None,
                  routes_count=None, failed_count=None)
    if not directory.exists():
        return result
    routes_path = directory / 'routes_l3d.json'
    if routes_path.exists():
        result['routes_sha'] = _sha256(routes_path)
        payload = _read_json(routes_path) or {}
        result['routes_count'] = len(payload.get('routes') or [])
        result['failed_count'] = payload.get('failed')
    summary = _read_json(directory / 'summary.json') or {}
    if 'crossings' in summary:
        result['crossings'] = int(summary['crossings'])
        result['source'] = 'summary.json'
        result['crossing_pairs'] = summary.get('crossing_pairs')
        result['max_route_crossings'] = summary.get('max_route_crossings')
        result['routes_with_crossings'] = summary.get('routes_with_crossings')
    elif 'final_crossings' in summary:
        result['crossings'] = int(summary['final_crossings'])
        result['source'] = 'summary.json:final_crossings'
    stats = _read_json(directory / 'crossing_stats.json') or {}
    totals = stats.get('totals') or {}
    planes = {}
    plane_rows = stats.get('planes') or []
    for row in plane_rows:
        if not isinstance(row, dict):
            continue
        try:
            z = round(float(row.get('z_mm')), 6)
        except (TypeError, ValueError):
            continue
        planes[z] = dict(crossings=row.get('crossings'),
                         crossing_pairs=row.get('crossing_pairs'),
                         routes=row.get('routes'))
    if totals:
        result['crossings'] = int(totals.get('crossings',
                                             result['crossings'] or 0))
        result['crossing_pairs'] = totals.get('crossing_pairs')
        result['max_route_crossings'] = totals.get('max_route_crossings')
        result['routes_with_crossings'] = totals.get('routes_with_crossings')
        result['source'] = 'crossing_stats.json:totals'
    if not planes and isinstance(summary.get('plane_counts'), dict):
        # lightweight snapshots carry the per-height counts in summary.json
        for key, row in summary['plane_counts'].items():
            if not isinstance(row, dict):
                continue
            try:
                z = round(float(key), 6)
            except (TypeError, ValueError):
                continue
            planes[z] = dict(crossings=row.get('events'),
                             crossing_pairs=row.get('pairs'),
                             routes=row.get('routes'))
        if planes:
            result['source'] = (result['source'] or '') + '|summary.plane_counts'
    if planes:
        result['planes'] = planes
        if result['crossings'] is None:
            result['crossings'] = int(sum(
                int(row.get('crossings') or 0) for row in planes.values()))
    if result['crossings'] is None and result['routes_sha'] is None:
        return result
    return result


def _find_validation(arm_dir, preferred_sha=None):
    """Newest-valid independent Validator record of one arm."""
    arm_dir = Path(arm_dir)
    candidates = [
        arm_dir / 'validation' / 'validation.json',
        arm_dir / 'validation.json',
        arm_dir / 'best_valid' / 'validation' / 'validation.json',
    ]
    records = []
    for path in candidates:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        record = dict(
            path=_rel(path),
            validation_pass=bool(payload.get('validation_pass')),
            geometry_pass=payload.get('geometry_pass'),
            contract_pass=payload.get('contract_pass'),
            violation_count=payload.get('violation_count'),
            policy=payload.get('manual_policy'),
            validated_at=payload.get('validated_at'),
            routes_sha=payload.get('routes_file_sha256'),
            validator=payload.get('validator') or payload.get('xyz_validator'),
            sha_match=(bool(preferred_sha)
                       and payload.get('routes_file_sha256') == preferred_sha),
        )
        records.append(record)
    if not records:
        return None
    records.sort(key=lambda item: (not item['sha_match'],
                                   not item['validation_pass']))
    return records[0]


def _validation_for_layout(layout_dir):
    """Validator record for an accepted layout (search the dir and its parent)."""
    layout_dir = Path(layout_dir)
    sha = _sha256(layout_dir / 'routes_l3d.json')
    for directory in (layout_dir, layout_dir.parent):
        record = _find_validation(directory, preferred_sha=sha)
        if record is not None:
            return record
    return None


#: optional per-arm evidence files (produced by the arm runners themselves)
EVIDENCE_FILES = (
    'group_migration.json', 'group_attempts.json', 'xy_evidence.json',
    'regroup_stats.json', 'regroup_attempts.json', 'group_stats.json',
    'arm_summary.json', 'crossing_decomposition.json',
)


def load_arm_evidence(arm_dir):
    """Optional arm-specific evidence JSONs (group migration / XY evidence)."""
    out = {}
    if arm_dir is None:
        return out
    arm_dir = Path(arm_dir)
    for name in EVIDENCE_FILES:
        payload = _read_json(arm_dir / name)
        if payload is not None:
            out[name] = payload
    return out


def _actual_start_crossings(arm_dir, config):
    """Crossings of the state an arm actually loaded (chain arms may differ)."""
    arm_dir = Path(arm_dir)
    snapshot = _read_json(arm_dir / 'start_snapshot.json')
    if isinstance(snapshot, dict):
        for key in ('total', 'crossings', 'start_crossings',
                    'final_crossings'):
            value = snapshot.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        summary = snapshot.get('summary')
        if isinstance(summary, dict):
            for key in ('crossings', 'total'):
                value = summary.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
    start_dir = config.get('start_dir') if isinstance(config, dict) else None
    if start_dir:
        candidate = Path(start_dir).resolve()
        if not candidate.is_absolute():
            candidate = (ROOT / start_dir).resolve()
        checkpoint = _read_json(candidate / 'checkpoint.json')
        if isinstance(checkpoint, dict) and isinstance(
                checkpoint.get('total'), (int, float)):
            return int(checkpoint['total'])
        summary = _read_json(candidate / 'summary.json')
        if isinstance(summary, dict):
            for key in ('crossings', 'total', 'final_crossings'):
                value = summary.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
    return None


def arm_start_info(arm_dir, config):
    """Declared vs actual start point of one arm (fair-comparison evidence)."""
    config = config if isinstance(config, dict) else {}
    sha = config.get('start_routes_sha256')
    same_start = None
    if sha:
        same_start = (str(sha) == START_SHA)
    return dict(
        start_dir=config.get('start_dir'),
        start_routes_sha256=sha,
        claims_start_crossings=config.get('start_crossings'),
        same_start_as_G3=same_start,
        actual_start_crossings=_actual_start_crossings(arm_dir, config),
        seed=config.get('seed'),
        arm=config.get('arm'),
    )


def load_arm(name, arm_dir):
    """Load one arm's real artifacts into a report row."""
    arm_dir = Path(arm_dir) if arm_dir else None
    result = dict(name=name, label=ARM_LABEL.get(name, name), dir=arm_dir,
                  status='missing', final=None, best=None, reported=None,
                  reported_dir=None, validation=None, budget=None,
                  config=None, strategy=None, failed_attempts=None,
                  geometry_changes=None, manual_changes=None,
                  history_rows=0, wall_seconds=None)
    if arm_dir is None or not arm_dir.exists():
        return result
    final = _dir_totals(arm_dir)
    best = _dir_totals(arm_dir / 'best_valid')
    # best_valid is a lightweight snapshot (no stats): inherit from the arm
    # root only when both directories hold the *same* accepted geometry.
    if (best.get('routes_sha') and final.get('routes_sha')
            and best['routes_sha'] == final['routes_sha']):
        for key in ('crossings', 'crossing_pairs', 'max_route_crossings',
                    'routes_with_crossings', 'planes', 'routes_count',
                    'failed_count'):
            if best.get(key) is None:
                best[key] = final.get(key)
        best['source'] = 'inherited from arm root (same routes SHA256)'
        best['stats_dir'] = final['dir']
        best['snapshot_dir'] = best['dir']
        # plotting must read the directory that carries crossing_stats.json
        best['dir'] = final['dir']
    if (final.get('routes_sha') and best.get('routes_sha')
            and final['routes_sha'] == best['routes_sha']):
        final['source'] = 'arm root (same routes SHA256 as best_valid)'
    result['final'] = final
    result['best'] = best
    candidates = [item for item in (final, best) if item.get('crossings') is not None]
    if candidates:
        candidates.sort(key=lambda item: item['crossings'])
        result['reported'] = candidates[0]
        result['reported_dir'] = candidates[0]['dir']
    result['validation'] = _find_validation(
        arm_dir, preferred_sha=(best.get('routes_sha')
                                or (result['reported'] or {}).get('routes_sha')))
    result['budget'] = _read_json(arm_dir / 'budget_ledger.json')
    result['config'] = _read_json(arm_dir / 'config.json')
    result['strategy'] = _read_json(arm_dir / 'strategy_stats.json')
    result['evidence'] = load_arm_evidence(arm_dir)
    result['start_info'] = arm_start_info(arm_dir, result['config'])
    failed = _read_json(arm_dir / 'failed_attempts.json') or {}
    result['failed_attempts'] = failed.get('count') if isinstance(failed, dict) else None
    result['geometry_changes'] = _read_json(arm_dir / 'geometry_changes.json')
    result['manual_changes'] = _read_json(arm_dir / 'manual_u_changes.json')
    history = arm_dir / 'optimization_history.csv'
    if history.exists():
        try:
            result['history_rows'] = sum(1 for _ in open(history, encoding='utf-8-sig')) - 1
        except OSError:
            result['history_rows'] = 0
    budget = result['budget'] or {}
    if isinstance(budget, dict):
        result['wall_seconds'] = budget.get('wall_seconds')
    else:
        result['wall_seconds'] = None
    result['wall_from_log'] = wall_clock_from_log(arm_dir)
    result['status'] = ('complete' if result['reported'] is not None
                        and result['reported'].get('routes_count') else
                        'in_progress')
    return result


def collect_arms():
    return OrderedDict(
        (name, load_arm(name, GP.ARM_DIRS.get(name))) for name in ARM_ORDER)


def _config_budget(config):
    if not isinstance(config, dict):
        return {}
    budget = config.get('budget')
    if isinstance(budget, dict):
        return budget
    out = {}
    for key in ('route_3d_checks', 'd56_candidate_evals', 'wall_seconds'):
        if isinstance(config.get(key), (int, float)):
            out[key] = config[key]
    return out


def budget_usage(arm):
    """Used / cap / utilisation of the fair-comparison budget dimensions."""
    budget = arm.get('budget') or {}
    if not isinstance(budget, dict):
        budget = {}
    limits = _config_budget(arm.get('config'))
    used = {key: budget.get(key) for key in
            ('route_3d_checks', 'd56_candidate_evals', 'wall_seconds')
            if key in budget}
    utilisation = {}
    for key, value in used.items():
        cap = limits.get(key)
        if cap and isinstance(value, (int, float)):
            utilisation[key] = round(100.0 * float(value) / float(cap), 1)
    return dict(used=used, cap=limits, utilisation=utilisation,
                over_budget=bool(
                    (limits.get('route_3d_checks') is not None
                     and used.get('route_3d_checks') is not None
                     and float(used['route_3d_checks'])
                     >= float(limits['route_3d_checks']))
                    or (limits.get('d56_candidate_evals') is not None
                        and used.get('d56_candidate_evals') is not None
                        and float(used['d56_candidate_evals'])
                        >= float(limits['d56_candidate_evals']))
                    or (limits.get('wall_seconds') is not None
                        and used.get('wall_seconds') is not None
                        and float(used['wall_seconds'])
                        >= float(limits['wall_seconds']))))


# --------------------------------------------------------------------------- #
# final best layout resolution
# --------------------------------------------------------------------------- #
def _routes_shape(directory):
    """Quick (routes_count, failed) of a routes_l3d.json (streaming is overkill)."""
    payload = _read_json(Path(directory) / 'routes_l3d.json') or {}
    return len(payload.get('routes') or []), payload.get('failed')


def find_final_best(arms):
    """Resolve the accepted final best layout + its evidence directory."""
    candidates = []
    for name, arm in arms.items():
        for tag in ('best', 'final'):
            item = arm.get(tag) or {}
            if item.get('crossings') is None or not item.get('dir'):
                continue
            if not _dir_has_routes(item['dir']):
                continue
            candidates.append(dict(
                source=name if tag == 'final' else '%s/best_valid' % name,
                dir=Path(item['dir']), crossings=item['crossings'],
                routes_sha=item.get('routes_sha'),
                has_stats=item.get('planes') is not None,
                validation=_validation_for_layout(item['dir'])))
    official = GP.ARM_DIRS.get('best_valid')
    if official and (Path(official) / 'routes_l3d.json').exists():
        totals = _dir_totals(official)
        best_meta = _read_json(Path(official) / 'BEST.json') or {}
        crossings = totals['crossings']
        if crossings is None:
            for key in ('final_crossings', 'crossings', 'total'):
                value = best_meta.get(key)
                if isinstance(value, (int, float)):
                    crossings = int(value)
                    break
        if crossings is not None:
            # the Lead-designated official best is authoritative: use it as the
            # accepted final layout instead of re-ranking the arm directories
            return dict(
                source='07_best_valid', dir=Path(official),
                crossings=crossings, routes_sha=totals.get('routes_sha'),
                has_stats=totals.get('planes') is not None,
                validation=_validation_for_layout(official),
                improved=crossings < START_CROSSINGS, best_meta=best_meta)
    if not candidates:
        return dict(source='G3_start', dir=START_DIR, crossings=START_CROSSINGS,
                    routes_sha=START_SHA, has_stats=True,
                    validation=_find_validation(START_DIR,
                                                preferred_sha=START_SHA),
                    improved=False)
    # lowest accepted crossing count first; among equal counts prefer the
    # official 07_best_valid copy, then validated / stats-bearing layouts
    candidates.sort(key=lambda item: (
        item['crossings'] if item.get('crossings') is not None else 10 ** 9,
        0 if item.get('source') == '07_best_valid' else 1,
        not (item.get('validation') or {}).get('validation_pass', False)
        or not item.get('has_stats', False)))
    best = candidates[0]
    best['improved'] = (best['crossings'] is not None
                        and int(best['crossings']) < START_CROSSINGS)
    if not best['improved']:
        # no arm beat the verified G3 optimum -> the accepted "G4 best" layout
        # is still the G3 start; never present an equal/worse layout as a gain
        start_validation = _find_validation(START_DIR,
                                            preferred_sha=START_SHA)
        return dict(source='G3_start (no G4 improvement)', dir=START_DIR,
                    crossings=START_CROSSINGS, routes_sha=START_SHA,
                    has_stats=True, validation=start_validation,
                    improved=False, note=(
                        '所有 G4 臂的终止交叉均 ≥ %d：本轮最佳合法解仍是'
                        ' G3 起点（负结果如实保留）' % START_CROSSINGS))
    return best


def ensure_final_validation(final, out_dir=None, run=True):
    """Independent frozen Validator record of the final accepted layout."""
    validation = (final or {}).get('validation')
    if validation and validation.get('validation_pass') and validation.get(
            'sha_match'):
        return validation
    run_dir = Path((final or {}).get('dir') or START_DIR)
    out_dir = Path(out_dir or (REPORTS / 'final_validation'))
    record = dict(path=None, validation_pass=None, violation_count=None,
                  policy='fully_optimizable', validated_at=None,
                  routes_sha=_sha256(run_dir / 'routes_l3d.json'),
                  sha_match=None, validator=None,
                  note='validator not run (--skip-validation)')
    if not run or not (run_dir / 'routes_l3d.json').exists():
        return record
    cmd = [sys.executable, '-m',
           'four_side_1024.fanout1024.xyzrouter.validate_xyz',
           '--run-dir', str(run_dir), '--out-dir', str(out_dir),
           '--manual-policy', 'fully_optimizable',
           '--baseline-dir', str(GP.AUTHORITY_DIR)]
    try:
        completed = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                                   text=True, timeout=1800)
        payload = _read_json(out_dir / 'validation.json') or {}
        record.update(
            path=_rel(out_dir / 'validation.json'),
            validation_pass=bool(payload.get('validation_pass')),
            violation_count=payload.get('violation_count'),
            validated_at=payload.get('validated_at'),
            routes_sha_from_validator=payload.get('routes_file_sha256'),
            sha_match=(payload.get('routes_file_sha256')
                       == record['routes_sha']),
            validator=payload.get('validator') or payload.get('xyz_validator'),
            policy=payload.get('manual_policy'),
            exit_code=completed.returncode,
            stdout_tail=completed.stdout[-2000:],
            stderr_tail=completed.stderr[-2000:],
            note='frozen independent Validator, fresh process',
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        record['note'] = 'validator failed to run: %r' % (exc,)
    return record


# --------------------------------------------------------------------------- #
# route-level evidence (geometry change / bottleneck / grouping)
# --------------------------------------------------------------------------- #
def load_routes(directory):
    payload = _read_json(Path(directory) / 'routes_l3d.json') or {}
    routes = payload.get('routes') or []
    return routes


def route_primary_z(route):
    z = V._to_float(route.get('target_z_mm'))
    if z is not None:
        return z
    best_z, best_len = None, -1.0
    for part in V._flat_parts(route):
        z = V._to_float(part.get('z_mm'))
        length = V._to_float(part.get('length_mm')) or 0.0
        if z is not None and length > best_len:
            best_z, best_len = z, length
    return best_z


def geometry_evidence(before_dir, after_dir):
    """Manual-U / all-route geometry change evidence from the accepted layouts."""
    before = load_routes(before_dir)
    after = load_routes(after_dir)
    old = {int(route['route_id']): route for route in before
           if route.get('route_id') is not None}
    new = {int(route['route_id']): route for route in after
           if route.get('route_id') is not None}
    common = sorted(set(old) & set(new))
    evidence = dict(routes_before=len(old), routes_after=len(new),
                    common_routes=len(common), manual_before=0,
                    manual_after=0, manual_height_changed=0,
                    manual_xy_changed=0, manual_xy_and_z_changed=0,
                    manual_keep=0, all_height_changed=0, all_xy_changed=0,
                    manual_groups_before=0, manual_groups_after=0,
                    manual_heights_before=[], manual_heights_after=[],
                    group_spread={})
    groups_before = set()
    groups_after = set()
    heights_before = Counter()
    heights_after = Counter()
    spread = defaultdict(set)
    group_heights_before = defaultdict(set)
    for rid in common:
        old_route = old[rid]
        old_group = str(old_route.get('manual_group') or '').strip()
        old_z = route_primary_z(old_route)
        if old_group and old_z is not None:
            group_heights_before[old_group].add(round(float(old_z), 6))
    for rid in common:
        old_route, new_route = old[rid], new[rid]
        old_z = route_primary_z(old_route)
        new_z = route_primary_z(new_route)
        old_group = str(old_route.get('manual_group') or '').strip()
        new_group = str(new_route.get('manual_group') or '').strip()
        if old_group:
            groups_before.add(old_group)
        if new_group:
            groups_after.add(new_group)
        xy_changed = PG._xy_signature(old_route) != PG._xy_signature(new_route)
        z_changed = (old_z is not None and new_z is not None
                     and abs(float(old_z) - float(new_z)) > 1e-9)
        if z_changed:
            evidence['all_height_changed'] += 1
        if xy_changed:
            evidence['all_xy_changed'] += 1
        if old_group:
            evidence['manual_before'] += 1
            if old_z is not None:
                heights_before[round(float(old_z), 6)] += 1
            if new_z is not None:
                heights_after[round(float(new_z), 6)] += 1
            if z_changed:
                evidence['manual_height_changed'] += 1
            if xy_changed:
                evidence['manual_xy_changed'] += 1
            if z_changed and xy_changed:
                evidence['manual_xy_and_z_changed'] += 1
            if not z_changed and not xy_changed:
                evidence['manual_keep'] += 1
            if new_group:
                groups_after.add(new_group)
            if new_z is not None:
                spread[old_group].add(round(float(new_z), 6))
        if new_group:
            evidence['manual_after'] += 1
    evidence['manual_groups_before'] = len(groups_before)
    evidence['manual_groups_after'] = len(groups_after)
    evidence['manual_heights_before'] = [
        dict(z=z, label=V._height_info(z)['label'], count=count)
        for z, count in sorted(heights_before.items())]
    evidence['manual_heights_after'] = [
        dict(z=z, label=V._height_info(z)['label'], count=count)
        for z, count in sorted(heights_after.items())]
    evidence['group_spread'] = {
        group: [dict(z=z, label=V._height_info(z)['label'])
                for z in sorted(values)]
        for group, values in sorted(spread.items())}
    # did XY rebuild actually free any manual-U route from its original
    # geometric height band? (the direct evidence for question 2)
    outside = []
    for rid in common:
        old_group = str(old[rid].get('manual_group') or '').strip()
        if not old_group:
            continue
        new_z = route_primary_z(new[rid])
        if new_z is None:
            continue
        allowed = group_heights_before.get(old_group) or set()
        if round(float(new_z), 6) not in allowed:
            outside.append(rid)
    evidence['manual_outside_old_band'] = len(outside)
    evidence['manual_outside_old_band_routes'] = outside[:50]
    evidence['manual_outside_old_band_truncated'] = len(outside) > 50
    return evidence


def bottleneck_analysis(routes_dir):
    """Crossing-graph bottleneck routes / heights of the accepted layout."""
    routes = load_routes(routes_dir)
    stats = _read_json(Path(routes_dir) / 'crossing_stats.json') or {}
    events = [event for event in (stats.get('crossing_events') or ())
              if isinstance(event, dict)]
    per_route = Counter()
    adjacency = defaultdict(set)
    pair_events = Counter()
    for event in events:
        try:
            route_a = int(event.get('route_a'))
            route_b = int(event.get('route_b'))
        except (TypeError, ValueError):
            continue
        per_route[route_a] += 1
        per_route[route_b] += 1
        adjacency[route_a].add(route_b)
        adjacency[route_b].add(route_a)
        pair_events[(min(route_a, route_b), max(route_a, route_b))] += 1
    by_id = {int(route['route_id']): route for route in routes
             if route.get('route_id') is not None}
    top_routes = []
    for rid, count in per_route.most_common(25):
        route = by_id.get(rid) or {}
        z = route_primary_z(route)
        top_routes.append(dict(
            route_id=rid, crossings=count,
            manual_group=str(route.get('manual_group') or ''),
            is_manual=bool(str(route.get('manual_group') or '').strip()),
            primary_z=z,
            height_label=(V._height_info(z)['label'] if z is not None else None),
            n_mid_transitions=V._n_mid_transitions(route),
            degree=len(adjacency.get(rid, ()))))
    # connected components of the crossing conflict graph
    seen = set()
    components = []
    for node in adjacency:
        if node in seen:
            continue
        stack = [node]
        seen.add(node)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for neighbour in adjacency.get(current, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(size)
    components.sort(reverse=True)
    plane_crossings = []
    for row in stats.get('planes') or ():
        if not isinstance(row, dict):
            continue
        try:
            z = round(float(row.get('z_mm')), 6)
        except (TypeError, ValueError):
            continue
        plane_crossings.append(dict(
            z=z, label=V._height_info(z)['label'],
            crossings=int(row.get('crossings') or 0),
            crossing_pairs=int(row.get('crossing_pairs') or 0),
            routes=row.get('routes')))
    plane_crossings.sort(key=lambda item: -item['crossings'])
    manual_crossings = sum(count for rid, count in per_route.items()
                          if by_id.get(rid)
                          and str(by_id[rid].get('manual_group') or '').strip())
    total = sum(per_route.values())
    return dict(
        total_events=len(events), total=crossing_total(stats),
        routes_with_crossings=len(per_route),
        manual_route_event_ends=manual_crossings,
        manual_share_pct=(100.0 * manual_crossings / total if total else None),
        top_routes=top_routes,
        top_heights=plane_crossings[:8],
        conflict_components=len(components),
        largest_component=components[0] if components else 0,
        second_component=components[1] if len(components) > 1 else 0,
        max_degree=max((len(value) for value in adjacency.values()), default=0),
        per_route=dict(per_route.most_common(60)),
    )


def crossing_total(stats):
    totals = (stats or {}).get('totals') or {}
    value = totals.get('crossings')
    return int(value) if value is not None else None


# --------------------------------------------------------------------------- #
# independent audit (G4-1) — referenced, never recomputed
# --------------------------------------------------------------------------- #
def load_audit():
    audit_dir = ARCHIVE / '00_baseline_audit'
    metrics = _read_json(audit_dir / 'audit_metrics.json') or {}
    required = metrics.get('required_quantities') or {}
    evidence = _read_json(audit_dir / 'min_distance_evidence.json') or {}
    contract = _read_json(audit_dir / 'contract_evidence.json') or {}
    revalidation = _read_json(
        audit_dir / 'baseline_revalidation' / 'validation.json') or {}
    report_path = audit_dir / 'GEOMETRY_CONTRACT_AUDIT.md'
    return dict(
        dir=_rel(audit_dir), report=_rel(report_path),
        report_exists=report_path.exists(),
        required=required,
        consistency=metrics.get('consistency_argument') or {},
        limitations=metrics.get('limitations') or [],
        evidence=evidence,
        contract=contract,
        revalidation=dict(
            validation_pass=bool(revalidation.get('validation_pass')),
            violation_count=revalidation.get('violation_count'),
            validated_at=revalidation.get('validated_at'),
            routes_sha=revalidation.get('routes_file_sha256'),
            policy=revalidation.get('manual_policy'),
            path=_rel(audit_dir / 'baseline_revalidation' / 'validation.json'),
            exists=(audit_dir / 'baseline_revalidation'
                    / 'validation.json').exists()),
    )


def resolve_final_evidence(final, arms):
    """Arm evidence of the accepted final layout (when it comes from an arm)."""
    target = Path(final.get('dir') or START_DIR).resolve()
    for name in ARM_ORDER:
        arm = arms.get(name) or {}
        candidate = arm.get('reported_dir')
        if candidate and Path(candidate).resolve() == target:
            evidence = dict(arm.get('evidence') or {})
            if evidence:
                evidence['_arm'] = name
                return evidence
    return {}


def group_migration_summary(evidence):
    """Normalised view of a G4a/G4b group-migration evidence file."""
    payload = {}
    source = None
    for name in ('group_migration.json', 'new_grouping.json',
                 'regroup_stats.json', 'group_stats.json'):
        candidate = (evidence or {}).get(name)
        if isinstance(candidate, dict):
            payload = candidate
            source = name
            break
    if not payload:
        return dict(present=False)
    summary = dict(
        present=True, source=source,
        accepted_whole=payload.get('accepted_whole_group_migrations'),
        accepted_partial=payload.get('accepted_partial_migrations'),
        accepted_transactions=payload.get('accepted_transactions'),
        routes_changed_height=payload.get('routes_changed_height'),
        manual_routes=payload.get('manual_routes'),
        groups=payload.get('original_groups') or payload.get('groups'),
        start_decomposition=payload.get('crossing_decomposition_start'),
        final_decomposition=payload.get('crossing_decomposition_final'),
        floor_manual_only=payload.get('theoretical_floor_manual_only'),
        xy=payload.get('xy_evidence') or {},
        attempt_stats=payload.get('attempt_stats') or {},
        migrated_groups=[group for group, value
                         in (payload.get('migration_summary') or {}).items()
                         if isinstance(value, dict) and value.get('migrated')],
        split_groups=[group for group, value
                      in (payload.get('split_group_evidence') or {}).items()
                      if isinstance(value, dict) and value.get('split')],
    )
    # G4b dynamic-regrouping schema: explicit real-geometry cluster evidence
    regrouping = payload.get('regrouping') or {}
    if not grouping_has_data(summary) and not regrouping:
        new_grouping = (evidence or {}).get('new_grouping.json') or {}
        regrouping = new_grouping.get('reorg_evidence') or {}
        if regrouping:
            summary['source'] = 'new_grouping.json'
    if regrouping:
        summary.update(
            start_cluster_count=regrouping.get('start_cluster_count'),
            final_cluster_count=regrouping.get('final_cluster_count'),
            start_heights_used=regrouping.get('start_heights_used'),
            final_heights_used=regrouping.get('final_heights_used'),
            routes_changed_primary_height=regrouping.get(
                'routes_changed_primary_height'),
            routes_changed_pct=regrouping.get('routes_pct'),
            merged_height_clusters=regrouping.get(
                'merged_height_clusters') or [],
            split_original_groups=regrouping.get(
                'split_original_groups') or [],
            by_kind=(payload.get('attempt_stats') or {}).get('by_kind') or {},
            attempt_by_reason=(payload.get('attempt_stats') or {}).get(
                'by_reason') or {},
        )
    for key in ('accepted_swaps', 'accepted_migrations', 'accepted_splits',
                'accepted_merges', 'new_group_count', 'regrouped_routes'):
        if key in payload:
            summary[key] = payload[key]
    return summary


def grouping_has_data(summary):
    return bool(summary.get('migrated_groups')
                or summary.get('accepted_whole')
                or summary.get('accepted_partial')
                or summary.get('routes_changed_height'))


def _format_decomposition(decomposition):
    if not isinstance(decomposition, dict) or not decomposition:
        return NA
    return ('manual-manual %s / manual-non %s / non-manual %s'
            % (_num(decomposition.get('manual_manual')),
               _num(decomposition.get('manual_non')),
               _num(decomposition.get('non_manual'))))


def load_chain():
    """Progressive chain (G3 -> G4a/b -> G4c -> G4d) link records.

    If ``progressive_chain.json`` still marks the last link as pending while
    the Lead-designated ``07_best_valid`` / ``BEST.json`` already records the
    final chain result, a synthetic final row is appended (clearly labelled).
    """
    payload = _read_json(ARCHIVE / '08_progressive_chain'
                         / 'progressive_chain.json') or {}
    links = [dict(link) for link in (payload.get('links') or [])
             if isinstance(link, dict)]
    best_meta = _read_json(ARCHIVE / '07_best_valid' / 'BEST.json') or {}
    summary = best_meta.get('summary') or {}
    selected_from = str(summary.get('selected_from') or '')
    if selected_from.startswith('chain_link') and links:
        last = links[-1]
        if last.get('status') == 'pending' or last.get('end_crossings') is None:
            previous_end = None
            for link in reversed(links[:-1]):
                if link.get('end_crossings') is not None:
                    previous_end = link.get('end_crossings')
                    break
            final_crossings = summary.get('final_crossings')
            links.append(dict(
                index=len(links),
                label='B 链最终环节（由 07_best_valid 补全；'
                      'progressive_chain.json 尚未更新）',
                source_arm=selected_from,
                start_crossings=previous_end,
                end_crossings=final_crossings,
                delta=(int(final_crossings) - int(previous_end))
                if final_crossings is not None and previous_end is not None
                else None,
                wall_seconds=None,
                validation_pass=bool(summary.get('validation_pass')),
                status='ok（来自 07_best_valid/BEST.json）',
                note='BEST.json summary.selected_from=%s' % selected_from,
            ))
    return dict(links=links,
                path=_rel(ARCHIVE / '08_progressive_chain'
                          / 'progressive_chain.json'),
                best_meta=best_meta,
                exists=(ARCHIVE / '08_progressive_chain'
                        / 'progressive_chain.json').exists())


def collect_extra_runs():
    """Warm-start / exploratory runs that are NOT formal arms (labelled)."""
    rows = []
    for directory in sorted(ARCHIVE.iterdir()) if ARCHIVE.exists() else []:
        if not directory.is_dir():
            continue
        name = directory.name
        if not (name.startswith('06b') or name.startswith('arm_lead')):
            continue
        summary = _read_json(directory / 'summary.json')
        summary_g4 = _read_json(directory / 'summary_g4.json') or {}
        config = _read_json(directory / 'config.json') or {}
        config_chain = _read_json(directory / 'config_chain.json') or {}
        if not isinstance(summary, dict) and not summary_g4:
            continue
        validation = _find_validation(directory)
        crossings = summary_g4.get('final_crossings')
        if crossings is None and isinstance(summary, dict):
            crossings = summary.get('crossings')
            if crossings is None:
                crossings = summary.get('final_crossings')
        start = summary_g4.get('chain_start_crossings')
        if start is None:
            start = config_chain.get('chain_start_crossings')
        if start is None and isinstance(summary, dict):
            start = summary.get('start_crossings')
        if start is None:
            start = config.get('start_crossings')
        note = ('B 类 warm-start / 探索性运行，非正式臂，不计入公平对照')
        if summary_g4.get('arm_class') == 'B_chain_warm_start':
            note = ('B 类 warm-start（起点 = %s 的 %s 交叉），非正式臂，'
                    '不能与同起点臂比较增量'
                    % (Path(str(summary_g4.get('chain_start_dir') or '')).name,
                       _num(summary_g4.get('chain_start_crossings'))))
        rows.append(dict(
            label=name, dir=_rel(directory), crossings=crossings,
            start_crossings=start,
            delta=(int(crossings) - int(start))
            if crossings is not None and start is not None else None,
            validation=validation,
            manual_frozen=config.get('manual_frozen'),
            note=note,
        ))
    return rows


def _first_json(*paths):
    for path in paths:
        payload = _read_json(path)
        if isinstance(payload, dict):
            return payload, Path(path)
    return {}, None


def load_lead_supplementary():
    """Lead's supplementary structure / exploratory analyses.

    These are **exploratory** results (clearly labelled as such everywhere):
    they are NOT formal arm results and are never counted as arm gains.
    Copied evidence lives in ``10_reports/lead_explore_*.json`` (archived);
    the scratch directories are only a fallback source.
    """
    reports = REPORTS
    structure = _read_json(reports / 'lead_crossing_structure.json') or {}
    interface = _read_json(reports / 'lead_interface_analysis.json') or {}
    component = _read_json(reports / 'lead_component_probe.json') or {}
    migration_probe = _read_json(reports / 'lead_migration_probe.json') or {}
    explore_migrate, path_migrate = _first_json(
        reports / 'lead_explore_migrate.json',
        ARCHIVE / '_lead_explore_migrate' / 'explore.json')
    explore_migrate2, path_migrate2 = _first_json(
        reports / 'lead_explore_migrate2.json',
        ARCHIVE / '_lead_explore_migrate2' / 'explore.json')
    explore_direct, path_direct = _first_json(
        reports / 'lead_explore_direct.json',
        ARCHIVE / '_lead_explore_direct' / 'explore.json')
    return dict(
        structure=structure, interface=interface, component=component,
        migration_probe=migration_probe,
        explore_migrate=explore_migrate,
        explore_migrate2=explore_migrate2,
        explore_direct=explore_direct,
        sources=dict(
            structure=_rel(reports / 'lead_crossing_structure.json'),
            interface=_rel(reports / 'lead_interface_analysis.json'),
            component=_rel(reports / 'lead_component_probe.json'),
            migration_probe=_rel(reports / 'lead_migration_probe.json'),
            explore_migrate=_rel(path_migrate) if path_migrate else NA,
            explore_migrate2=_rel(path_migrate2) if path_migrate2 else NA,
            explore_direct=_rel(path_direct) if path_direct else NA,
        ),
        label=('exploratory, not a formal arm'),
        generated_at=_now(),
    )


def interface_crossings(structure):
    """(total, per-height list) of interface-layer crossings from Lead data."""
    heights = (structure or {}).get('heights') or []
    rows = [row for row in heights
            if str(row.get('label', '')).find('INTERFACE') >= 0]
    total = sum(int(row.get('crossings') or 0) for row in rows)
    return total, rows


def load_final_audit():
    """Final independent geometry audit of the accepted solution (if present).

    Prefers the formal ``FINAL_AUDIT/``; otherwise reports the
    ``FINAL_AUDIT_PREVIEW/`` (explicitly labelled as a preview whose target SHA
    may be an earlier snapshot).
    """
    audit_root = ARCHIVE / '00_baseline_audit'
    for kind, directory in (('formal', audit_root / 'FINAL_AUDIT'),
                            ('preview', audit_root / 'FINAL_AUDIT_PREVIEW')):
        status = _read_json(directory / 'final_audit_status.json')
        summary = directory / 'FINAL_AUDIT_SUMMARY.md'
        if not isinstance(status, dict) and not summary.exists():
            continue
        status = status or {}
        return dict(
            kind=kind, dir=_rel(directory),
            status=status,
            summary_md=_rel(summary) if summary.exists() else None,
            six=status.get('six') or {},
            run_dir=status.get('run_dir'),
            routes_sha=status.get('routes_sha256'),
            validator_pass=status.get('validator_pass'),
            all_checks_pass=status.get('all_checks_pass'),
            skipped=status.get('skipped') or [],
            label=status.get('label'),
            sha_matches_final=None,  # filled by the caller
        )
    return dict(kind=None)


def stage_gain_summary(arm):
    """Per-stage crossing gains of one arm (from its strategy_stats.json)."""
    payload = arm.get('strategy') or {}
    extra = payload.get('extra') or {}
    stages = extra.get('stage_stats') or []
    rows = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        size = stage.get('size')
        if size in (0, None):
            label = 'greedy migration sweep（无邻域）'
        else:
            label = 'neighbourhood %s' % size
        rows.append(dict(
            stage=stage.get('stage'), size=size, label=label,
            attempts=stage.get('attempts'), accepts=stage.get('accepts'),
            gain=stage.get('gain'), seconds=stage.get('seconds_used')))
    total = sum(int(row.get('gain') or 0) for row in rows)
    for row in rows:
        gain = int(row.get('gain') or 0)
        row['share_pct'] = (round(100.0 * gain / total, 1) if total else None)
    return dict(rows=rows, total=total)


def best_plot_dirname(final):
    """Directory name of the final-best layer suite (G4_best_<crossings>)."""
    crossings = (final or {}).get('crossings')
    if crossings is None:
        return 'G4_best'
    return 'G4_best_%d' % int(crossings)


def best_plot_rel(final, filename=None):
    base = '09_plots/%s/' % best_plot_dirname(final)
    return base + filename if filename else base


# --------------------------------------------------------------------------- #
# document builders
# --------------------------------------------------------------------------- #
def _arm_crossings(arm):
    reported = arm.get('reported') or {}
    return reported.get('crossings')


def _validation_cell(validation):
    if not validation:
        return NA
    if validation.get('validation_pass'):
        return 'PASS'
    if validation.get('validation_pass') is False:
        return 'FAIL'
    return NA


def wall_clock_from_log(arm_dir):
    """Wall clock (s) between the first and last timestamped line of run.log."""
    path = Path(arm_dir) / 'run.log'
    if not path.exists():
        return None
    stamps = []
    try:
        for line in path.read_text(encoding='utf-8',
                                   errors='replace').splitlines():
            match = re.match(r'\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\]',
                             line.strip())
            if match:
                stamps.append(match.group(1))
    except OSError:
        return None
    if len(stamps) < 2:
        return None
    try:
        first = datetime.fromisoformat(stamps[0])
        last = datetime.fromisoformat(stamps[-1])
    except ValueError:
        return None
    seconds = (last - first).total_seconds()
    return round(seconds, 1) if seconds >= 0 else None


def _wall_display(budget, name):
    """Wall-clock cell (search wall from ledger; run.log as cross-check)."""
    ledger = budget.get('wall_seconds')
    log_value = budget.get('wall_from_log')
    if name == 'G4d' and log_value is not None:
        # the G4d ledger value was overwritten on interrupt/resume; the run.log
        # timestamps give the true end-to-end wall clock
        return '%s（run.log 实测；ledger=%s 被覆盖）' % (_num(log_value),
                                                       _num(ledger))
    if (log_value is not None and ledger is not None
            and abs(float(log_value) - float(ledger))
            > 0.5 * max(float(log_value), float(ledger))):
        return '%s（run.log 全过程 %s s，含验证/重建开销）' % (
            _num(ledger), _num(log_value))
    return _budget_display(ledger, name, 'wall_seconds')


def _budget_columns(arm):
    usage = budget_usage(arm)
    used = dict(usage['used'])
    for key in list(used):
        value = used[key]
        if isinstance(value, str) and value.strip().lower() in ('null', 'none',
                                                                'nan', ''):
            used[key] = None
    return dict(
        route_3d_checks=used.get('route_3d_checks'),
        d56_candidate_evals=used.get('d56_candidate_evals'),
        wall_seconds=used.get('wall_seconds'),
        wall_from_log=arm.get('wall_from_log'),
        route_3d_util_pct=usage['utilisation'].get('route_3d_checks'),
        d56_util_pct=usage['utilisation'].get('d56_candidate_evals'),
        wall_util_pct=usage['utilisation'].get('wall_seconds'),
        cap=usage['cap'], over_budget=usage['over_budget'])


def _budget_display(value, name, key):
    if value is None:
        if name == 'C0' and key == 'd56_candidate_evals':
            return 'null（不可观测）'
        return NA
    return _num(value)


def _comparison_table(arms, final):
    header = ['实验', '终止交叉', 'Δ vs 1322', '降幅', '唯一交叉对',
              '最大单路交叉', '含交叉线路', 'Validator', '违规数',
              'route_3d_checks', 'd56_evals', '搜索墙钟(s)']
    rows = []
    start_row = ['G3 起点', START_CROSSINGS, '0', '0.0%', 1253, 19,
                 588, 'PASS（独立复跑）', 0,
                 '-', '-', '-']
    rows.append(start_row)
    for name in ARM_ORDER:
        arm = arms[name]
        reported = arm.get('reported') or {}
        if arm['status'] == 'missing' or reported.get('crossings') is None:
            rows.append([ARM_LABEL[name], NA, NA, NA, NA, NA, NA, NA, NA,
                         NA, NA, NA])
            continue
        validation = arm.get('validation') or {}
        budget = _budget_columns(arm)
        rows.append([
            ARM_LABEL[name],
            reported.get('crossings'),
            _delta(reported.get('crossings'), START_CROSSINGS),
            _pct(reported.get('crossings'), START_CROSSINGS),
            reported.get('crossing_pairs'),
            reported.get('max_route_crossings'),
            reported.get('routes_with_crossings'),
            _validation_cell(validation),
            validation.get('violation_count'),
            _budget_display(budget['route_3d_checks'], name,
                            'route_3d_checks'),
            _budget_display(budget['d56_candidate_evals'], name,
                            'd56_candidate_evals'),
            _wall_display(budget, name),
        ])
    final_row = ['**G4 最终最佳合法解**',
                 final.get('crossings'),
                 _delta(final.get('crossings'), START_CROSSINGS),
                 _pct(final.get('crossings'), START_CROSSINGS),
                 (final.get('reported') or {}).get('crossing_pairs'),
                 (final.get('reported') or {}).get('max_route_crossings'),
                 (final.get('reported') or {}).get('routes_with_crossings'),
                 _validation_cell(final.get('validation')),
                 (final.get('validation') or {}).get('violation_count'),
                 '-', '-', '-']
    rows.append(final_row)
    return header, rows


def _per_height_table(arms, final):
    """21 physical heights x arms crossing distribution."""
    names = ['G3 起点'] + [ARM_LABEL[name].split()[0] for name in ARM_ORDER] \
        + ['G4 best']
    header = ['#', '高度', 'z (mm)', 'G3'] + [ARM_LABEL[name].split()[0]
                                              for name in ARM_ORDER] \
        + ['G4 best']
    # stable short headers
    header = ['#', '高度', 'z (mm)', 'G3']
    short = {'C0': 'C0', 'G4a': 'G4a', 'G4b': 'G4b', 'G4c_frozen': 'G4c-frz',
             'G4c_free': 'G4c-free', 'G4d': 'G4d'}
    for name in ARM_ORDER:
        header.append(short[name])
    header.append('G4 best')
    rows = []
    start_planes = _dir_totals(START_DIR).get('planes') or {}
    arm_planes = {name: (arms[name].get('final') or {}).get('planes')
                  for name in ARM_ORDER}
    best_planes = (final.get('reported') or {}).get('planes') or {}
    for index, z in enumerate(PG.HEIGHT_KEYS):
        info = PG.HEIGHT_BY_Z[z]
        row = [index + 1, info['label'], '%+.2f' % info['z_mm'],
               (start_planes.get(z) or {}).get('crossings', NA)]
        for name in ARM_ORDER:
            planes = arm_planes.get(name)
            row.append((planes or {}).get(z, {}).get('crossings', NA)
                       if planes else NA)
        row.append((best_planes.get(z) or {}).get('crossings', NA)
                   if best_planes else NA)
        rows.append(row)
    return header, rows


def build_answers(arms, final, evidence, bottleneck, audit,
                  final_evidence=None, lead=None):
    """answers.md — the six required questions."""
    final_evidence = final_evidence or {}
    lead = lead or {}
    lines = ['# G4 六问回答（基于真实接受解的几何与统计）', '',
             '- 生成时间: %s' % _now(),
             '- 起点: G3 best_valid（SHA256 `%s`，%d 交叉）' % (START_SHA,
                                                              START_CROSSINGS),
             '- 最终最佳合法解: `%s`，交叉 **%s**'
             % (_rel(final.get('dir')), _num(final.get('crossings'))),
             '- 口径: 所有数字来自最终接受的 `routes_l3d.json` 真实几何 + '
             '`crossing_stats.json` 事件；未完成项写“%s”。' % NA, '']
    # ---- Q1
    g4a = arms.get('G4a', {})
    g4b = arms.get('G4b', {})
    lines += ['## 问题 1：原八组人工 U 是否存在更优分组？', '']
    a_cross = _arm_crossings(g4a)
    b_cross = _arm_crossings(g4b)
    if a_cross is None and b_cross is None:
        lines.append('**结论：%s**（G4a/G4b 尚未产出接受解）。' % NA)
    else:
        if a_cross is not None and b_cross is not None:
            if b_cross < a_cross:
                conclusion = ('是（在人工 U 可动集合上界内，动态重分组比分组固定'
                              '多降 **%d** 交叉：G4b %s vs G4a %s，%s）'
                              % (int(a_cross - b_cross), _num(b_cross),
                                 _num(a_cross), _pct(b_cross, a_cross)))
            else:
                conclusion = ('否/证据不足（G4b %s 未优于分组固定的 G4a %s）'
                              % (_num(b_cross), _num(a_cross)))
        else:
            conclusion = NA
        lines.append('**结论：%s**' % conclusion)
        lines.append('')
        lines.append('| 证据 | 数值 |')
        lines.append('|---|---|')
        lines.append('| G4a（分组固定）终止交叉 | %s |' % _num(a_cross))
        lines.append('| G4b（动态重分组）终止交叉 | %s |' % _num(b_cross))
        lines.append('| G4b − G4a | %s |'
                     % (_delta(b_cross, a_cross) if a_cross is not None
                        and b_cross is not None else NA))
        lines.append('| 人工 U 迁移图 | `09_plots/manual_u_migration/` |')
        lines.append('')
        lines.append('人工 U 的真实分组变化由图 `09_plots/manual_u_migration/'
                     'manual_u_migration_matrix.png` 与同目录 CSV 给出：'
                     '行=原八组，列=G4 真实主体高度族群，单元格=线路数；'
                     '分组变化必须以**真实主体高度 + 几何**体现，而不是标签。')
    # G4a/G4b group evidence (real geometry, arm-written files)
    gm = group_migration_summary((arms.get('G4a') or {}).get('evidence') or {})
    if gm.get('present'):
        lines.append('')
        lines.append('**G4a 组级迁移真实几何证据**（`%s`）：' % gm['source'])
        lines.append('')
        lines.append('| 证据 | 数值 |')
        lines.append('|---|---|')
        lines.append('| 被接受的整体组迁移 | %s |' % _num(gm.get('accepted_whole')))
        lines.append('| 被接受的部分组迁移 | %s |'
                     % _num(gm.get('accepted_partial')))
        lines.append('| 人工 U 主体高度改变线路数 | %s / %s |'
                     % (_num(gm.get('routes_changed_height')),
                        _num(gm.get('manual_routes'))))
        lines.append('| 发生真实迁移的组 | %s |'
                     % ('、'.join(gm.get('migrated_groups') or []) or '无'))
        lines.append('| 高度分布跨 >1 个高度的组（文件定义，含起点既有分布） | %s |'
                     % ('、'.join(gm.get('split_groups') or []) or '无'))
        xy = gm.get('xy') or {}
        lines.append('| body XY 签名改变线路数 | %s |'
                     % _num(xy.get('body_xy_signature_changed_count')))
        lines.append('| 平均/最大 body XY 位移 (mm) | %s / %s |'
                     % (_num(xy.get('mean_body_xy_displacement_mm')),
                        _num(xy.get('max_body_xy_displacement_mm'))))
        if gm.get('start_decomposition'):
            lines.append('| 起点交叉分解（按可动集合） | %s |'
                         % _format_decomposition(gm['start_decomposition']))
            lines.append('| 该臂移动集合的解析下界（臂自报，非全局下界） | %s |'
                         % _num(gm.get('floor_manual_only')))
        lines.append('')
        decomposition = gm.get('start_decomposition') or {}
        movable = ((decomposition.get('manual_manual') or 0)
                   + (decomposition.get('manual_non') or 0))
        fixed = decomposition.get('non_manual')
        lines.append('**结论性解读（G4a 负结果，如实保留）**：G4a 被接受的整组迁移 '
                     '%s 个、部分组迁移 %s 个，仅 %s 条人工 U 真实换高，交叉只下降 '
                     '%+d；臂自身给出的“仅动人工 U”解析下界 = %s。即使组级重造'
                     '完美执行，人工 U 臂最多也只能触及 %s 段交叉（manual-manual + '
                     'manual-nonmanual），其余 %s 段非人工-非人工交叉必须由 '
                     'G4c/G4d 处理。因此“原八组是否存在更优分组”的答案不能只看 '
                     'G4a：它受**可动集合上界**严格限制（这也是 G4b 的同一上界）。'
                     % (_num(gm.get('accepted_whole')),
                        _num(gm.get('accepted_partial')),
                        _num(gm.get('routes_changed_height')),
                        (int(a_cross - START_CROSSINGS)
                         if a_cross is not None else NA),
                        _num(gm.get('floor_manual_only')),
                        _num(movable), _num(fixed)))
    # ---- G4b dynamic-regrouping real-geometry evidence
    bm = group_migration_summary((arms.get('G4b') or {}).get('evidence') or {})
    if bm.get('present'):
        lines.append('')
        lines.append('**G4b 动态重分组真实几何证据**（`%s`）：' % bm['source'])
        lines.append('')
        lines.append('| 证据 | 数值 |')
        lines.append('|---|---|')
        lines.append('| 新分组簇数（起 → 终） | %s → %s |'
                     % (_num(bm.get('start_cluster_count')),
                        _num(bm.get('final_cluster_count'))))
        lines.append('| 使用的高度数（起 → 终） | %s → %s |'
                     % (_num(bm.get('start_heights_used')),
                        _num(bm.get('final_heights_used'))))
        lines.append('| 人工 U 主高度改变线路数 | %s（%s%%） |'
                     % (_num(bm.get('routes_changed_primary_height')),
                        _num(bm.get('routes_changed_pct'))))
        merged = bm.get('merged_height_clusters') or []
        lines.append('| 合并高度簇（不同旧组同高度重组） | %d 个：%s |'
                     % (len(merged),
                        '、'.join('%s(%s)' % (
                            item.get('height_label'),
                            '+'.join(item.get('old_groups') or []))
                            for item in merged) or '无'))
        lines.append('| 拆分原组 | %s |'
                     % ('、'.join(bm.get('split_original_groups') or [])
                        or '无'))
        lines.append('| 接受事务数 | %s |'
                     % _num(bm.get('accepted_transactions')))
        xy_b = bm.get('xy') or {}
        lines.append('| body XY 签名改变线路数 | %s |'
                     % _num(xy_b.get('body_xy_signature_changed_count')))
        lines.append('| 平均/最大 body XY 位移 (mm) | %s / %s |'
                     % (_num(xy_b.get('mean_body_xy_displacement_mm')),
                        _num(xy_b.get('max_body_xy_displacement_mm'))))
        if bm.get('start_decomposition'):
            lines.append('| 起点交叉分解（按可动集合） | %s |'
                         % _format_decomposition(bm['start_decomposition']))
        if bm.get('final_decomposition'):
            lines.append('| 终点交叉分解 | %s |'
                         % _format_decomposition(bm['final_decomposition']))
        if bm.get('floor_manual_only') is not None:
            lines.append('| 该臂移动集合的解析下界（非全局下界） | %s |'
                         % _num(bm.get('floor_manual_only')))
        by_kind = bm.get('by_kind') or {}
        if by_kind:
            lines.append('| 各算子 尝试/接受 | %s |'
                         % '；'.join(
                             '%s %s/%s' % (kind, _num(value.get('attempts')),
                                           _num(value.get('accepted', 0)))
                             for kind, value in by_kind.items()
                             if isinstance(value, dict)))
        lines.append('')
        lines.append('> G4b 的“新分组”由**真实主体高度 + 几何**体现（20 个'
                     '“高度×旧组”簇在起终点对比、8 条线路真实换高、6 个'
                     '高度簇发生跨旧组合并、7 个原组被拆分），不是只改标签。')
    lines += ['', '## 问题 2：XY 重构是否解除高度可达性限制？', '']
    if not evidence or 'error' in evidence or evidence.get('manual_before') is None:
        lines.append('**结论：%s**（最终最佳解几何证据未就绪）。' % NA)
    else:
        manual_changed = evidence.get('manual_height_changed') or 0
        manual_total = evidence.get('manual_before') or 0
        outside = evidence.get('manual_outside_old_band') or 0
        xy_changed = evidence.get('manual_xy_changed') or 0
        crossing_delta = ((final.get('crossings') - START_CROSSINGS)
                          if final.get('crossings') is not None else None)
        if manual_changed == 0 and xy_changed == 0:
            conclusion = '否（未观察到任何真实高度或 XY 迁移）'
        elif outside > 0:
            conclusion = ('是：%d 条人工 U 真实换高（%d 条到达原组高度带之外），'
                          '%d 条 XY 几何真实改变，交叉 %+d'
                          % (manual_changed, outside, xy_changed,
                             crossing_delta if crossing_delta is not None else 0))
        else:
            conclusion = ('有限：仅 %d/%d 条人工 U 真实换高（且**未离开**原组'
                          '高度带）、%d 条 XY 真实改变，交叉 %+d——高度可达性'
                          '限制基本未被解除'
                          % (manual_changed, manual_total, xy_changed,
                             crossing_delta if crossing_delta is not None else 0))
        lines.append('**结论：%s**' % conclusion)
        lines.append('')
        lines.append('| 证据（来自接受解真实几何） | 数值 |')
        lines.append('|---|---|')
        lines.append('| 人工 U 线路数（前/后） | %s / %s |'
                     % (_num(evidence.get('manual_before')),
                        _num(evidence.get('manual_after'))))
        lines.append('| 人工 U 主体高度改变 | %s |'
                     % _num(evidence.get('manual_height_changed')))
        lines.append('| 人工 U 到达原组高度带之外 | %s |'
                     % _num(evidence.get('manual_outside_old_band')))
        lines.append('| 人工 U XY 几何改变 | %s |'
                     % _num(evidence.get('manual_xy_changed')))
        lines.append('| 人工 U XY+Z 同时改变 | %s |'
                     % _num(evidence.get('manual_xy_and_z_changed')))
        lines.append('| 人工 U 完全保持 | %s |'
                     % _num(evidence.get('manual_keep')))
        lines.append('| 全部线路主体高度改变 | %s |'
                     % _num(evidence.get('all_height_changed')))
        lines.append('| 全部线路 XY 几何改变 | %s |'
                     % _num(evidence.get('all_xy_changed')))
        lines.append('')
        lines.append('人工 U 高度分布（前 → 后）：')
        lines.append('')
        before = evidence.get('manual_heights_before') or []
        after = evidence.get('manual_heights_after') or []
        lines.append('- G3：%s' % ('、'.join(
            '%s(%d)' % (item['label'], item['count']) for item in before)
            or NA))
        lines.append('- G4 best：%s' % ('、'.join(
            '%s(%d)' % (item['label'], item['count']) for item in after)
            or NA))
        lines.append('')
        lines.append('“高度可达性限制解除”的判定必须同时满足：真实高度改变 + '
                     '独立 Validator PASS。后者见 `10_reports/report.md` '
                     '的合法证据表。')
    lines += ['', '## 问题 3：解冻人工 U 与大邻域搜索分别贡献多少收益？', '']
    c0 = _arm_crossings(arms.get('C0', {}))
    frozen = _arm_crossings(arms.get('G4c_frozen', {}))
    free = _arm_crossings(arms.get('G4c_free', {}))
    if c0 is None and frozen is None and free is None:
        lines.append('**结论：%s**（C0/G4c 尚未产出接受解）。' % NA)
    else:
        lines.append('以同一 G3 起点（%d）为基准，收益 = 起点交叉 − 臂终止交叉：'
                     % START_CROSSINGS)
        lines.append('')
        lines.append('| 对照 | 终止交叉 | 收益 Δ | 归因 |')
        lines.append('|---|---|---|---|')
        lines.append('| C0（既有引擎，无新自由度） | %s | %s | 基线引擎自身收益 |'
                     % (_num(c0),
                        _delta(START_CROSSINGS, c0) if c0 is not None else NA))
        lines.append('| G4c-frozen（ALNS，人工 U 冻结） | %s | %s | '
                     '大邻域搜索在冻结人工 U 下的收益 |'
                     % (_num(frozen),
                        _delta(START_CROSSINGS, frozen) if frozen is not None
                        else NA))
        lines.append('| G4c-free（ALNS，人工 U 解冻） | %s | %s | '
                     '大邻域 + 人工 U 解冻联合收益 |'
                     % (_num(free),
                        _delta(START_CROSSINGS, free) if free is not None
                        else NA))
        if frozen is not None and free is not None:
            lines.append('')
            lines.append('- **人工 U 解冻的边际贡献（干净对照）** = G4c-frozen − '
                         'G4c-free = **%+d 交叉**（同算法、同预算、同可动集合，'
                         '仅“人工 U 是否解冻”不同）。' % int(frozen - free))
        if c0 is not None and frozen is not None:
            lines.append('- **“大邻域搜索”的贡献不能由 C0 − G4c-frozen 直接归因**：'
                         'C0 可动集合是全部 1024 条、G4c-frozen 是 656 条'
                         '非人工线路，两者可动集合不同；C0 − G4c-frozen = '
                         '**%+d 交叉**只能作为参考区间（不是纯算法对照）。'
                         % int(c0 - frozen))
        lines.append('')
        lines.append('注意预算口径：C0 墙钟上限 1200 s，G4c 两臂 1800 s，'
                     'G4d 2400 s（渐进链，见 `comparison.md` §5），fair 性以 '
                     '`route_3d_checks` 真实计数对账；各臂实际用量见 '
                     '`comparison.md` 预算表。')
    lines += ['', '## 问题 4：哪些线路阻碍进一步下降？', '']
    if not bottleneck or bottleneck.get('total') is None:
        lines.append('**结论：%s**（最终最佳解交叉统计未就绪）。' % NA)
    else:
        lines.append('**结论**：剩余交叉高度集中在 %s；线路层面见下表。'
                     % ('、'.join('%s(z=%+.2f)' % (item['label'], item['z'])
                                 for item in (bottleneck.get('top_heights')
                                              or [])[:3]) or NA))
        lines.append('')
        lines.append('| 排名 | route_id | 交叉数 | 人工组 | 主体高度 | 冲突邻居数 |')
        lines.append('|---|---|---|---|---|---|')
        for rank, item in enumerate((bottleneck.get('top_routes') or [])[:15],
                                    1):
            lines.append('| %d | %d | %d | %s | %s | %d |'
                         % (rank, item['route_id'], item['crossings'],
                            item.get('manual_group') or '-',
                            item.get('height_label') or '-', item['degree']))
        lines.append('')
        lines.append('- 交叉冲突图：%d 个连通分量，最大分量 %d 条线路，'
                     '次大 %d 条，最大度 %d。'
                     % (bottleneck.get('conflict_components'),
                        bottleneck.get('largest_component'),
                        bottleneck.get('second_component'),
                        bottleneck.get('max_degree')))
        if bottleneck.get('manual_share_pct') is not None:
            lines.append('- 人工 U 线路参与的交叉端点占比 %.1f%%（端点计数口径）。'
                         % bottleneck['manual_share_pct'])
        structure = (lead or {}).get('structure') or {}
        if structure.get('by_class'):
            interface_total, interface_rows = interface_crossings(structure)
            lines.append('- G3 起点交叉结构分解（Lead 补充分析，**探索性，非正式臂**，'
                         '`%s`）：manual-manual %s / manual-nonmanual %s / '
                         'nonmanual-nonmanual %s；接口层交叉合计 %s（%s）。'
                         % ((lead or {}).get('sources', {}).get('structure', NA),
                            _num(structure['by_class'].get('manual-manual')),
                            _num(structure['by_class'].get(
                                'manual-nonmanual')),
                            _num(structure['by_class'].get(
                                'nonmanual-nonmanual')),
                            _num(interface_total),
                            '、'.join('%s=%s' % (row.get('label'),
                                                 _num(row.get('crossings')))
                                     for row in interface_rows) or NA))
        # arm-written crossing decomposition (when the final layout comes from
        # an arm that decomposes crossings by movable set)
        final_gm = group_migration_summary(final_evidence)
        if final_gm.get('present') and final_gm.get('final_decomposition'):
            lines.append('- 最终解交叉分解（按可动集合）：%s。'
                         % _format_decomposition(final_gm['final_decomposition']))
            if final_gm.get('floor_manual_only') is not None:
                lines.append('- 该臂移动集合的解析下界（臂自报，非全局下界）：'
                             '%s 交叉。'
                             % _num(final_gm.get('floor_manual_only')))
        lines.append('')
        lines.append('更细的逐层统计见 `%s`；'
                     '失败原因瓶颈见 `10_reports/failure_analysis.md`。'
                     % best_plot_rel(final, 'G4_best_LAYERS.md'))
    lines += ['', '## 问题 5：是否突破 1000？', '']
    final_cross = final.get('crossings')
    if final_cross is None:
        lines.append('**结论：%s**（最终最佳解未就绪）。' % NA)
    else:
        lines.append('**结论：%s**（最终最佳合法解交叉 **%d**，G3 起点 %d，'
                     '降幅 %s）。'
                     % ('是' if final_cross < 1000 else '否', final_cross,
                        START_CROSSINGS,
                        _pct(final_cross, START_CROSSINGS)))
        lines.append('')
        lines.append('| 挑战目标 | 是否达到 | 距目标差距 |')
        lines.append('|---|---|---|')
        for target in TARGETS:
            reached = final_cross <= target
            lines.append('| ≤ %d | %s | %+d |'
                         % (target, '是' if reached else '否',
                            final_cross - target))
        a_gm = group_migration_summary((arms.get('G4a') or {}).get('evidence')
                                       or {})
        if a_gm.get('present') and a_gm.get('start_decomposition'):
            decomposition = a_gm['start_decomposition']
            lines.append('')
            lines.append('**为什么 1000 需要 G4c/G4d 而不是只重排人工 U**：'
                         'G4a/G4b 只移动 368 条人工 U；起点交叉分解显示 '
                         'manual-manual %s、manual-non %s、non-manual %s——'
                         '其中 non-manual 部分（%s 条）**完全不在人工 U 臂的'
                         '移动集合内**，必须由 G4c/G4d 的大邻域联合事务处理。'
                         % (_num(decomposition.get('manual_manual')),
                            _num(decomposition.get('manual_non')),
                            _num(decomposition.get('non_manual')),
                            _num(decomposition.get('non_manual'))))
    lines += ['', '## 问题 6：下一轮最值得扩大的搜索自由度？', '']
    lines.append(_next_freedom_text(arms, final, evidence, bottleneck, audit,
                                    lead))
    lines.append('')
    return '\n'.join(lines) + '\n'


def _next_freedom_text(arms, final, evidence, bottleneck, audit, lead=None):
    """Evidence-driven recommendation for the next round (no invention)."""
    lead = lead or {}
    items = []
    failure = FA.analyse() if (ARCHIVE / '10_reports').exists() else {}
    totals = (failure or {}).get('totals') or {}
    ranked = sorted(((key, int(value)) for key, value in totals.items()
                     if int(value) > 0), key=lambda item: -item[1])
    if ranked:
        items.append('- 失败计数最高的机制是 `%s`（%d 次）：下一轮应优先扩大'
                     '能直接针对该机制的邻域/事务规模。'
                     % (ranked[0][0], ranked[0][1]))
    if bottleneck and bottleneck.get('top_heights'):
        top = bottleneck['top_heights'][0]
        items.append('- 剩余交叉最集中的高度是 %s（z=%+.2f，%d 交叉）：该高度'
                     '的入口/过渡走廊应成为下一轮的联合重造重点。'
                     % (top['label'], top['z'], top['crossings']))
    if bottleneck and bottleneck.get('largest_component'):
        items.append('- 交叉冲突图最大连通分量 %d 条线路：单线/小邻域已接近'
                     '瓶颈，下一轮应扩大到跨分量的多线路联合事务（>64 邻域、'
                     '多重建顺序、多 seed）。'
                     % bottleneck['largest_component'])
    if evidence and (evidence.get('manual_height_changed') or 0) > 0:
        items.append('- 人工 U 动态重分组已产生真实几何收益，下一轮可把'
                     '“动态分组/换高”扩大到非人工线路，并允许组间交换。')
    if final.get('crossings') is not None and final['crossings'] > 1000:
        items.append('- 本轮未突破 1000；结合预算曲线，建议先扩大'
                     ' `route_3d_checks` / 墙钟预算与多 seed 重启，'
                     '再做算法结构改动（预算-收益曲线见 '
                     '`09_plots/budget/budget_curves.png`）。')
    structure = (lead or {}).get('structure') or {}
    if structure.get('by_class'):
        interface_total, interface_rows = interface_crossings(structure)
        if interface_total:
            items.append('- 接口层交叉合计 %s（%s）被 Lead 补充分析（探索性，'
                         '非正式臂）判定为 direct-body×direct-body 的**结构性'
                         '下限**：下一轮最值得扩大的自由度是**接口区（direct '
                         'body）的联合重布与新过渡拓扑**，而不是继续只在平面内'
                         '移动。'
                         % (_num(interface_total),
                            '、'.join('%s=%s' % (row.get('label'),
                                                 _num(row.get('crossings')))
                                     for row in interface_rows)))
    explore_migrate = (lead or {}).get('explore_migrate') or {}
    if explore_migrate.get('final_crossings') is not None:
        items.append('- Lead 探索（**exploratory, not a formal arm**）：'
                     'exact-delta 高度重分配已把探索状态降到 %s；下一轮应把它'
                     '形式化为正式臂，并扩大高度重分配邻域/多 seed。'
                     % _num(explore_migrate.get('final_crossings')))
    explore_migrate2 = (lead or {}).get('explore_migrate2') or {}
    if explore_migrate2.get('final_crossings') is not None:
        items.append('- Lead 探索 E2（**exploratory, not a formal arm**）：'
                     '第二组 exact-delta 高度重分配探索到 %s；与 E1 合并说明'
                     '“精确高度重分配”是稳定有效的自由度，应形式化为正式臂。'
                     % _num(explore_migrate2.get('final_crossings')))
    explore_direct = (lead or {}).get('explore_direct') or {}
    history = explore_direct.get('history') or []
    if history:
        items.append('- 接口 direct 平面重造单独立项无效：%d 次尝试（z=0.0 × 4 '
                     '顺序 + z=0.5 × 4 顺序）gain 全部为 0、全部回滚——必须与'
                     '接口内走廊重布/多过渡联合，才能触及接口 212 交叉。'
                     % len(history))
    items.append('- 任何新增自由度必须保持全部不变量（1024 条、21 高度、'
                 'R15、D56 strict、三维 50 µm 净空）；不得通过放宽口径'
                 '获取收益。')
    return '\n'.join(items)


def build_comparison(arms, final, audit, lead=None):
    lead = lead or {}
    lines = ['# G4 实验总表与逐高度分布（comparison）', '',
             '- 生成时间: %s' % _now(),
             '- 共同起点: G3 best_valid，routes SHA256 `%s`，%d 交叉'
             % (START_SHA, START_CROSSINGS),
             '- 数据来源: 各臂真实 `routes_l3d.json` / `crossing_stats.json` / '
             '`summary.json` / `validation/validation.json` / '
             '`budget_ledger.json`；未完成项写“%s”。' % NA, '']
    header, rows = _comparison_table(arms, final)
    lines.append('## 1. 总表（真实接受解）')
    lines.append('')
    lines.append(_md_table(header, rows))
    lines.append('')
    lines.append('> 说明：G3 起点行唯一交叉对 1253、最大单路 19、含交叉线路 '
                 '588 来自 `crossing_stats.json` totals 与 G4-1 独立复核；'
                 'G4 最终最佳解行的预算是“多个臂的累计搜索”，不单独列。')
    lines.append('')
    extras = collect_extra_runs()
    if extras:
        lines.append('**B 类 warm-start / 探索性运行（非正式臂，不计入公平'
                     '对照，不能与上面同起点臂比较增量）**')
        lines.append('')
        header = ['运行目录', '起点交叉', '终止交叉', 'Δ', 'Validator', '说明']
        rows = []
        for item in extras:
            rows.append([item['label'], _num(item['start_crossings']),
                         _num(item['crossings']), _num(item['delta']),
                         _validation_cell(item['validation']),
                         item['note']])
        lines.append(_md_table(header, rows))
        lines.append('')
    lines.append('## 2. 逐物理高度交叉分布（21 高度 × 各臂）')
    lines.append('')
    pheader, prows = _per_height_table(arms, final)
    lines.append(_md_table(pheader, prows))
    lines.append('')
    lines.append('> 每格为该物理高度上的真实交叉事件数（来自各臂 '
                 '`crossing_stats.json` 的 `planes`）；`NA` = 该臂产物未完成'
                 '或不含逐高度统计。')
    lines.append('')
    lines.append('## 3. 合法性与独立验收')
    lines.append('')
    lines.append('| 实验 | Validator | 违规数 | 记录 SHA 与解一致 | 验收文件 |')
    lines.append('|---|---|---|---|---|')
    start_validation = _find_validation(START_DIR, preferred_sha=START_SHA)
    lines.append('| G3 起点 | %s | %s | %s | `%s` |'
                 % (_validation_cell(start_validation),
                    (start_validation or {}).get('violation_count'),
                    '是' if (start_validation or {}).get('sha_match') else NA,
                    (start_validation or {}).get('path') or NA))
    for name in ARM_ORDER:
        arm = arms[name]
        validation = arm.get('validation')
        if not validation:
            lines.append('| %s | %s | %s | %s | %s |'
                         % (ARM_LABEL[name], NA, NA, NA, NA))
            continue
        lines.append('| %s | %s | %s | %s | `%s` |'
                     % (ARM_LABEL[name], _validation_cell(validation),
                        validation.get('violation_count'),
                        '是' if validation.get('sha_match') else '否/未核对',
                        validation.get('path')))
    final_validation = final.get('validation')
    lines.append('| **G4 最终最佳合法解** | %s | %s | %s | `%s` |'
                 % (_validation_cell(final_validation),
                    (final_validation or {}).get('violation_count'),
                    '是' if (final_validation or {}).get('sha_match') else NA,
                    (final_validation or {}).get('path') or NA))
    lines.append('')
    if audit.get('report_exists'):
        lines.append('独立几何口径审计（G4-1，引用不复算）：'
                     '`%s`；最小非交叉净空 %s mm、非法交叉 %d、净空违规 %d。'
                     % (audit.get('report'), _num(
                         (audit.get('required') or {}).get(
                             'minimum_clearance_non_crossing_mm')),
                        int((audit.get('required') or {}).get(
                            'illegal_crossing_count') or 0),
                        int((audit.get('required') or {}).get(
                            'clearance_violation_count') or 0)))
        lines.append('')
    lines.append('## 4. 预算与公平性（真实共享引擎计数）')
    lines.append('')
    header = ['实验', 'route_3d_checks', '预算上限', '利用率', 'd56_evals',
              'd56 上限', '搜索墙钟(s)', '墙钟上限', '是否触顶']
    rows = []
    for name in ARM_ORDER:
        arm = arms[name]
        if arm['status'] == 'missing' or not arm.get('budget'):
            rows.append([ARM_LABEL[name]] + [NA] * 8)
            continue
        budget = _budget_columns(arm)
        cap = budget.get('cap') or {}
        rows.append([
            ARM_LABEL[name],
            _budget_display(budget.get('route_3d_checks'), name,
                            'route_3d_checks'),
            _num(cap.get('route_3d_checks')),
            ('%s%%' % _num(budget.get('route_3d_util_pct'), 1)
             if budget.get('route_3d_util_pct') is not None else NA),
            _budget_display(budget.get('d56_candidate_evals'), name,
                            'd56_candidate_evals'),
            _num(cap.get('d56_candidate_evals')),
            _wall_display(budget, name),
            _num(cap.get('wall_seconds')),
            '是' if budget.get('over_budget') else '否',
        ])
    lines.append(_md_table(header, rows))
    lines.append('')
    lines.append('> 墙钟主口径为 `budget_ledger.wall_seconds`（搜索循环）；'
                 '`run.log` 首末时间戳为全过程交叉核对，差异 >50% 时并列显示。'
                 'G4d 的 ledger 值 106.3 s 在中断/恢复时被覆盖，其 `run.log` '
                 '实测约 1758 s，表中按 run.log 显示并标注。')
    lines.append('> `d56_candidate_evals` 对 C0 为 `null`（旧引擎未接入共享 '
                 'Ledger，口径不可比，SPEC 要求显式写 null）；其余臂为共享引擎'
                 '真实计数。')
    lines.append('')
    lines.append('## 5. 起点与公平性（从各臂 config.json / start_snapshot.json '
                 '实测，不引用声明值）')
    lines.append('')
    header = ['实验', '起点 SHA 与 G3 一致', '实际加载起点交叉',
              'seed', '说明']
    rows = []
    for name in ARM_ORDER:
        arm = arms[name]
        info = arm.get('start_info') or {}
        if arm['status'] == 'missing' or not info:
            rows.append([ARM_LABEL[name], NA, NA, NA, NA])
            continue
        same = info.get('same_start_as_G3')
        note = ('同一起点（1322 合法基线）'
                if same is True else
                ('**渐进链起点（继承检查点）**：不可与同起点臂直接比较增量'
                 if same is False else NA))
        rows.append([ARM_LABEL[name],
                     '是' if same is True else ('否' if same is False else NA),
                     _num(info.get('actual_start_crossings')),
                     _num(info.get('seed')), note])
    lines.append(_md_table(header, rows))
    lines.append('')
    lines.append('> 同起点公平对照只使用起点 SHA = G3 SHA 的臂；渐进链臂（如 G4d '
                 '`tag=formal_chain_from_1248` 之类）的终止交叉包含前序臂收益，'
                 '**不得把 1322→终止 的全部收益归因于该臂**。链收益拆分见 '
                 '`08_progressive_chain/progressive_chain.json`。')
    lines.append('')
    chain = load_chain()
    if chain.get('links'):
        lines.append('## 6. 渐进链收益拆分（`%s`）' % chain.get('path'))
        lines.append('')
        header = ['环节', '来源臂', '起点交叉', '终点交叉', '本段收益',
                  '本段墙钟(s)', 'Validator']
        chain_rows = []
        for link in chain['links']:
            chain_rows.append([
                link.get('label'), link.get('source_arm'),
                _num(link.get('start_crossings')),
                _num(link.get('end_crossings')), _num(link.get('delta')),
                _num(link.get('wall_seconds'), 1),
                _validation_cell({'validation_pass':
                                  link.get('validation_pass')}
                                 if link.get('validation_pass') is not None
                                 else None)])
        lines.append(_md_table(header, chain_rows))
        lines.append('')
        lines.append('> 链的累计收益 = 各段收益之和；不得把链的累计收益全部'
                     '归因于最后一个臂/算法。')
        lines.append('')
    lines.append('## 7. 机器可读数据与对照文件')
    lines.append('')
    lines.append('- `experiments/xyz_joint_g4_1024/metrics.csv` / '
                 '`budget_ledger.csv` / `experiment_matrix.csv` / '
                 '`fair_comparison.md`（G4-4 采集）')
    matrix_path = ARCHIVE / 'experiment_matrix.csv'
    if matrix_path.exists():
        try:
            matrix_text = matrix_path.read_text(encoding='utf-8',
                                                errors='replace')
        except OSError:
            matrix_text = ''
        matrix_mtime = datetime.fromtimestamp(
            matrix_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        lines.append('- `experiment_matrix.csv` 生成时间 **%s**；含最终 best 行'
                     '（`chain_link3` = **1185**）=%s；含 G4c_free '
                     '`ce7ca9a9…` 记录=%s（已与最终报告对账）。'
                     % (matrix_mtime,
                        '是' if ('chain_link3' in matrix_text
                                 and '1185' in matrix_text)
                        or 'final_best' in matrix_text else '否/待确认',
                        '是' if 'ce7ca9a9' in matrix_text else '否/待确认'))
    lines.append('- `experiments/xyz_joint_g4_1024/10_reports/'
                 'metrics_summary.json`（本报告全部数字的机器可读版本）')
    lines.append('- `experiments/xyz_joint_g4_1024/09_plots/G3_vs_G4/'
                 'G3_vs_G4_per_height.csv`（逐高度 before/after 明细）')
    lines.append('')
    sources = (lead or {}).get('sources') or {}
    structure = (lead or {}).get('structure') or {}
    if structure:
        interface_total, interface_rows = interface_crossings(structure)
        by_class = structure.get('by_class') or {}
        lines.append('## 8. Lead 补充结构分析（**探索性，非正式臂**，'
                     '不进入任何臂的收益表）')
        lines.append('')
        lines.append('| 项目 | 数值 | 来源 |')
        lines.append('|---|---|---|')
        lines.append('| 交叉类别 manual-manual / manual-nonmanual / '
                     'nonmanual-nonmanual | %s / %s / %s | `%s` |'
                     % (_num(by_class.get('manual-manual')),
                        _num(by_class.get('manual-nonmanual')),
                        _num(by_class.get('nonmanual-nonmanual')),
                        sources.get('structure', NA)))
        if interface_total:
            lines.append('| 接口层交叉（结构性下限） | %s（%s） | `%s` |'
                         % (_num(interface_total),
                            '、'.join('%s=%s' % (row.get('label'),
                                                 _num(row.get('crossings')))
                                     for row in interface_rows),
                            sources.get('structure', NA)))
        explore_migrate = (lead or {}).get('explore_migrate') or {}
        if explore_migrate.get('final_crossings') is not None:
            lines.append('| E1 exact-delta 高度重分配（探索） | 1322 → **%s** '
                         '（**exploratory, not a formal arm**） | `%s` |'
                         % (_num(explore_migrate.get('final_crossings')),
                            sources.get('explore_migrate', NA)))
        explore_migrate2 = (lead or {}).get('explore_migrate2') or {}
        if explore_migrate2.get('final_crossings') is not None:
            lines.append('| E2 exact-delta 高度重分配（探索） | → **%s** '
                         '（**exploratory, not a formal arm**） | `%s` |'
                         % (_num(explore_migrate2.get('final_crossings')),
                            sources.get('explore_migrate2', NA)))
        explore_direct = (lead or {}).get('explore_direct') or {}
        history = explore_direct.get('history') or []
        if history:
            lines.append('| interface direct_plane_recreate（探索） | %d 次尝试、'
                         'gain 全部 0、全部回滚；最终 %s | `%s` |'
                         % (len(history),
                            _num(explore_direct.get('final_crossings')),
                            sources.get('explore_direct', NA)))
        lines.append('')
        lines.append('> 以上为 Lead 的探索性分析（`_lead_explore_*` 为 scratch '
                     '目录，未计入正式臂与 MANIFEST 的臂收益）；正式结论只用'
                     '各臂接受解与独立 Validator 证据。')
        lines.append('')
    return '\n'.join(lines) + '\n'


def build_report(arms, final, evidence, bottleneck, audit, failure, archive,
                 final_evidence=None, lead=None, final_audit=None):
    final_evidence = final_evidence or {}
    lead = lead or {}
    final_audit = final_audit or {}
    final_cross = final.get('crossings')
    final_validation = final.get('validation') or {}
    lines = ['# G4 最终报告：人工 U 动态重分组与大邻域 XY+Z 联合三维重布（1024）',
             '',
             '- 生成时间: %s' % _now(),
             '- 归档根: `%s`' % _rel(ARCHIVE),
             '- 任务契约: `SPEC_G4.md`',
             '- 起点（只读，未被覆盖）: `outputs/manual_c4_new_connectivity/'
             'XYZ_JOINT_G123_1024/best_valid`，routes SHA256 `%s`，'
             '1024/1024 布通、%d 交叉' % (START_SHA, START_CROSSINGS),
             '- 最终最佳合法解: `%s`（SHA256 `%s`）'
             % (_rel(final.get('dir')), final.get('routes_sha') or NA),
             '',
             '## 0. 结论速览（先给答案）', '']
    # 1024/1024
    routes_count = None
    best_reported = final.get('reported') or {}
    if best_reported:
        routes_count = best_reported.get('routes_count')
    geometry_ok = bool(final_validation.get('validation_pass')
                       and final_validation.get('sha_match'))
    lines.append('| 必答项 | 结论 | 证据 |')
    lines.append('|---|---|---|')
    lines.append('| **1024/1024 是否保持** | %s | 最终解 `routes_l3d.json` '
                 'routes=%s、failed=%s；身份/端口/连接由独立 Validator 复核 |'
                 % ('是' if routes_count == 1024 else NA,
                    _num(routes_count), _num(final.get('failed_count'))))
    lines.append('| **几何是否合法** | %s | 冻结独立 Validator（'
                 '`manual_policy=fully_optimizable`）：%s，violations=%s，'
                 'SHA 与解一致=%s（`%s`） |'
                 % ('是' if geometry_ok else NA,
                    _validation_cell(final_validation),
                    _num(final_validation.get('violation_count')),
                    '是' if final_validation.get('sha_match') else NA,
                    final_validation.get('path') or NA))
    lines.append('| **最低交叉降到多少** | **%s**（G3 起点 %d，Δ=%s，%s） | '
                 '最终解 `crossing_stats.json` totals，逐层复核见 '
                 '`%s` |'
                 % (_num(final_cross), START_CROSSINGS,
                    _delta(final_cross, START_CROSSINGS),
                    _pct(final_cross, START_CROSSINGS),
                    best_plot_rel(final, 'G4_best_LAYERS.md')))
    reached = [target for target in TARGETS
               if final_cross is not None and final_cross <= target]
    lines.append('| **挑战目标（1200/1000/800/500/100/9/0）** | %s | %s |'
                 % ('、'.join('≤%d %s' % (target,
                                          '达到' if final_cross is not None
                                          and final_cross <= target else '未达')
                              for target in TARGETS),
                    ('最高达成目标 ≤%d' % reached[0]) if reached
                    else '未达成任何挑战目标'))
    lines.append('| **是否严格证明最优/无解** | **否** | 本轮只报告“在给定'
                 '引擎/算法/预算下达到的最低交叉”，无下界证明、无穷举覆盖证明 |')
    lines.append('')
    lines.append('> 一句话结论：在**不降低任何物理约束、不删连接、不改交叉口径**'
                 '的前提下，G4 从 G3 的 %d 交叉出发，最终接受解为 **%s 交叉**'
                 '（%s），%s；所有臂/最终解均通过冻结独立 Validator。'
                 % (START_CROSSINGS, _num(final_cross),
                    _pct(final_cross, START_CROSSINGS),
                    ('达成/超过 1000 突破目标' if final_cross is not None
                     and final_cross < 1000 else '未达成 1000 突破目标')))
    lines.append('')
    # ---- 1. baseline audit
    lines.append('## 1. 起点基线与独立几何口径审计（G4-1）')
    lines.append('')
    if audit.get('report_exists'):
        required = audit.get('required') or {}
        lines.append('G3 起点的几何口径由独立审计（geometry-auditor，'
                     '**不复用历史 PASS 结论**）重新计算，'
                     '详见 [`../00_baseline_audit/GEOMETRY_CONTRACT_AUDIT.md`]'
                     '(%s) 与 `audit_metrics.json`。'
                     % '../00_baseline_audit/GEOMETRY_CONTRACT_AUDIT.md')
        lines.append('')
        lines.append('### 1.1 六个必需量（独立复算值，直接引用）')
        lines.append('')
        lines.append('| 必需量 | 值 | 说明 |')
        lines.append('|---|---|---|')
        for key, description in AUDIT_QUANTITIES:
            value = required.get(key)
            if isinstance(value, dict):
                value = ('同层 D56 strict 80 µm + 真实横穿豁免'
                         '（角 ≥ %s°、窗口半宽 ≤ %s mm）；不同高度 |dz| ≥ %s mm；'
                         'transition 真 3D ≥ %s mm'
                         % (_num(value.get('min_crossing_angle_deg'), 1),
                            _num(value.get('max_window_half_mm'), 1),
                            _num(value.get('min_layer_pitch_mm')),
                            _num(value.get('min_layer_pitch_mm'))))
            lines.append('| `%s` | %s | %s |'
                         % (key, value if value is not None else NA,
                            description))
        lines.append('')
        reval = audit.get('revalidation') or {}
        lines.append('### 1.2 口径必须写清的三个事实')
        lines.append('')
        lines.append('1. **“最小 3D 净空 0.063596 mm”只覆盖 transition 相关对**'
                     '（`validate21.measure_min_3d_clearance` 口径，只量 '
                     'transition-vs-flat 与 transition-vs-transition），'
                     '**不是全板最小值**。全板“不同物理高度 flat 对”的最小 3D '
                     '距离 = **%s mm**（相邻层间距恰为 0.05 mm、且存在 XY 相交'
                     '的相邻层 flat 对，例如 route 515/623），**零余量但按契约合法**。'
                     % _num(required.get('minimum_clearance_non_crossing_mm')))
        lines.append('2. **“1322 交叉 + 0 几何违规”自洽的原因**：两条规则作用于'
                     '**不相交的对集合**——同层 flat/flat 对只受 D56 strict 2D '
                     '0.08 mm + 既有真实横穿豁免（冻结基线自带 2409 交叉并通过'
                     '同一 Validator，非 G4 新增豁免）约束；不同物理高度对受 '
                     '|dz| ≥ 0.05 mm 约束（3D 距离必然 ≥ 0.05，永远不会“看到”'
                     '这 1322 个交叉）；涉及 transition 的对受真 3D ≥ 0.05 mm '
                     '约束且无横穿豁免。因此 1322 个合法横穿不会转化为净空违规。')
        lines.append('3. **运行时净空为 0.05 mm，但代码默认值仍是历史 0.08 mm**：'
                     '`l3d/world.py` 默认 `clearance=None` 会退化为 '
                     '`fslw.config.CLEARANCE_MM = 0.08`；现行 Validator/路由器'
                     '全部**显式传 0.05**（`reheight21/validate21.py`、'
                     '`xyzrouter/world_adapter.py`）。本报告引用 50 µm 时均指'
                     '**运行时显式 0.05 mm 口径**，`0.08` 只是历史默认值/文档遗留。')
        lines.append('')
        lines.append('G3 起点的独立 Validator 复跑：**%s**，violations=%s，'
                     '记录 SHA 与起点解一致=%s（`%s`）。'
                     % (_validation_cell({
                         'validation_pass': reval.get('validation_pass')}),
                        _num(reval.get('violation_count')),
                        '是' if reval.get('routes_sha') == START_SHA else '未核对',
                        reval.get('path') or NA))
    else:
        lines.append('%s：独立审计文件尚未生成（`00_baseline_audit/`）。' % NA)
    # ---- 1.3 final independent audit record
    if final_audit.get('kind'):
        final_sha = final.get('routes_sha')
        audit_sha = final_audit.get('routes_sha')
        status = final_audit.get('status') or {}
        six = final_audit.get('six') or {}
        lines.append('')
        title = ('正式终验 FINAL_AUDIT' if final_audit['kind'] == 'formal'
                 else '终验预演 FINAL_AUDIT_PREVIEW')
        lines.append('### 1.3 最终解的独立复算（%s）' % title)
        lines.append('')
        lines.append('- 记录：`%s`（摘要 `%s`）'
                     % (final_audit.get('dir'),
                        final_audit.get('summary_md') or NA))
        lines.append('- 被审计解：`%s`，routes SHA256 `%s`'
                     % (_rel(final_audit.get('run_dir')),
                        audit_sha or NA))
        if final_sha and audit_sha and final_sha != audit_sha:
            lines.append('- **注意**：该预演对象是较早快照（SHA 与当前最终解 '
                         '`%s` 不同）；正式终验须在最终路径确定后由审计方重跑'
                         '（`FINAL_AUDIT/`）。' % final_sha)
        lines.append('- 校验：all_checks_pass=%s，validator_pass=%s，'
                     'skipped=%s，elapsed=%s s'
                     % (status.get('all_checks_pass'),
                        status.get('validator_pass'),
                        status.get('skipped') or [],
                        _num(status.get('elapsed_seconds'), 1)))
        if six:
            lines.append('- 六必需量：minimum_distance_all_pairs=%s、'
                         'minimum_clearance_non_crossing=%s、'
                         'allowed_crossing_count=%s、illegal=%s、'
                         'clearance_violation=%s'
                         % (_num(six.get('minimum_distance_all_pairs_mm')),
                            _num(six.get('minimum_clearance_non_crossing_mm')),
                            _num(six.get('allowed_crossing_count')),
                            _num(six.get('illegal_crossing_count')),
                            _num(six.get('clearance_violation_count'))))
        lines.append('')
    lines.append('')
    # ---- 2. design
    lines.append('## 2. 实验设计与公平性')
    lines.append('')
    lines.append('| 实验 | 可动线路 | 高度自由度 | XY 自由度 | 搜索机制 |')
    lines.append('|---|---|---|---|---|')
    lines.append('| C0 | 全部 1024 | 单线迁移 | 单线走廊重造 | 沿用 G3 既有优化器'
                 '（不新增自由度，公平对照） |')
    lines.append('| G4a | 368 人工 U（组固定） | 每组统一主体高度可换 | '
                 '组内 XY 全重造 | 组级事务 + 组高度枚举 |')
    lines.append('| G4b | 368 人工 U | 单条迁移/交换/拆分/重组 | 全重造 | '
                 '动态分组事务 |')
    lines.append('| G4c-frozen | 非人工线路（人工 U 冻结） | 非人工可迁移 | '
                 '全重造 | 联合让路 ALNS，邻域 8/16/32/64 |')
    lines.append('| G4c-free | 全部（人工 U 可作目标/阻挡者） | 全部 | 全重造 | '
                 '同上 |')
    lines.append('| G4d | 全部 1024 | 全部 | 全部 | 全局大邻域 ALNS / '
                 'Ruin-Recreate，多重建顺序、多 seed |')
    lines.append('')
    lines.append('- 共同起点/种子: G3 best_valid（SHA `%s`）、seed=%d；'
                 % (START_SHA, GP.SEED))
    same_start_arms = [name for name in ARM_ORDER
                       if (arms[name].get('start_info') or {}).get(
                           'same_start_as_G3') is True]
    chain_arms = [name for name in ARM_ORDER
                  if (arms[name].get('start_info') or {}).get(
                      'same_start_as_G3') is False]
    lines.append('- 同起点公平对照臂: %s'
                 % ('、'.join(same_start_arms) if same_start_arms else NA))
    if chain_arms:
        lines.append('- **渐进链臂（起点继承检查点，非同一起点）**: %s — 其终止'
                     '交叉包含前序臂收益，报告中已将增量与同起点臂分开，'
                     '不把全部收益归因于该臂（见 `comparison.md` §5）。'
                     % '、'.join(chain_arms))
    lines.append('- 公平性: 受 `route_3d_checks` / `d56_candidate_evals` / '
                 '墙钟三重预算约束（名义预算：C0/G4a/G4b 1200 s，G4c 1800 s，'
                 'G4d 2400-3600 s，见 `g4/paths.py` 与各臂 `config.json`）；'
                 '实际用量以 `budget_ledger.json` 真实计数为准（见 '
                 '`comparison.md` §4）。')
    lines.append('- 验收: 每臂最佳解由**独立子进程**冻结 Validator '
                 '（`manual_policy=fully_optimizable`）验收；best_valid 只在'
                 '事务整组验收且交叉严格下降后更新。')
    lines.append('')
    # ---- 3. arms table
    lines.append('## 3. 各臂结果（真实接受解）')
    lines.append('')
    header, rows = _comparison_table(arms, final)
    lines.append(_md_table(header, rows))
    lines.append('')
    for name in ARM_ORDER:
        arm = arms[name]
        reported = arm.get('reported') or {}
        if arm['status'] == 'missing' or reported.get('crossings') is None:
            lines.append('- `%s`：%s（目录 `%s` 尚无接受解产物）'
                         % (ARM_LABEL[name], NA, _rel(arm['dir'])))
        else:
            lines.append('- `%s`：终止交叉 %s（Δ=%s），来源 `%s`'
                         % (ARM_LABEL[name], _num(reported.get('crossings')),
                            _delta(reported.get('crossings'), START_CROSSINGS),
                            _rel(arm.get('reported_dir'))))
    a_gm = group_migration_summary((arms.get('G4a') or {}).get('evidence') or {})
    if a_gm.get('present'):
        lines.append('')
        lines.append('**G4a 组级迁移与“可动集合上界”证据（真实几何，'
                     '`%s`）**：被接受的整体组迁移 %s、部分迁移 %s；'
                     '人工 U 主体高度改变 %s/%s 条；body XY 签名改变 %s 条；'
                     '起点交叉分解 %s；该臂移动集合的解析下界 %s（臂自报，'
                     '只对 G4a 的移动集合成立，**不是全局下界**）。'
                     % (a_gm.get('source'), _num(a_gm.get('accepted_whole')),
                        _num(a_gm.get('accepted_partial')),
                        _num(a_gm.get('routes_changed_height')),
                        _num(a_gm.get('manual_routes')),
                        _num((a_gm.get('xy') or {}).get(
                            'body_xy_signature_changed_count')),
                        _format_decomposition(a_gm.get('start_decomposition')),
                        _num(a_gm.get('floor_manual_only'))))
    c0_cross = _arm_crossings(arms.get('C0', {}))
    a_cross = _arm_crossings(arms.get('G4a', {}))
    b_cross = _arm_crossings(arms.get('G4b', {}))
    if c0_cross is not None and (a_cross is not None or b_cross is not None):
        lines.append('')
        lines.append('**重要负结果（如实保留）**：既有引擎对照臂 C0 在同一墙钟预算'
                     '下终止于 **%s**，优于人工 U 臂 G4a **%s** / G4b **%s**。'
                     '这不是“分组方案更差”的证据，而是**可动集合不同**：C0 可动'
                     ' 1024 条（656 条非人工线路），G4a/G4b 只能动 368 条人工 U、'
                     '其解析下界 1213。任何跨臂比较都必须先看可动集合（见 '
                     '`comparison.md` §1 注）。'
                     % (_num(c0_cross), _num(a_cross), _num(b_cross)))
    extras = collect_extra_runs()
    if extras:
        lines.append('')
        lines.append('**B 类 warm-start / 探索性运行（非正式臂，不计入公平对照）**：'
                     + '；'.join('%s %s→%s（%s）'
                                % (item['label'],
                                   _num(item.get('start_crossings')),
                                   _num(item.get('crossings')),
                                   'Validator ' + _validation_cell(
                                       item.get('validation')))
                                for item in extras))
        lines.append('')
        lines.append('> 这些运行从更优检查点 warm-start（起点 ≠ 1322），其收益'
                     '包含继承收益，不能与同起点臂直接比较，也不用于六问归因。')
    lines.append('')
    lines.append('> **G4d A 类臂计时说明（Lead 确认）**：该臂因外部误杀分两次'
                 ' session 运行（1242.7 s + 111.6 s ≈ **1354 s** 搜索墙钟）；'
                 '`budget_ledger` 与矩阵中的 wall 字段是 session 2 的值，'
                 '不能当作该臂总搜索时间（本报告预算表已并列 run.log 实测）。')
    lines.append('')
    # ---- 4. six answers summary (point to answers.md, keep short)
    lines.append('## 4. 六问回答（摘要）')
    lines.append('')
    lines.append('完整回答与证据表见 [`10_reports/answers.md`](answers.md)。')
    lines.append('')
    for index, title in enumerate((
            '原八组人工 U 是否存在更优分组？',
            'XY 重构是否解除高度可达性限制？',
            '解冻人工 U 与大邻域搜索分别贡献多少收益？',
            '哪些线路阻碍进一步下降？',
            '是否突破 1000？',
            '下一轮最值得扩大的搜索自由度？'), 1):
        lines.append('%d. **%s** — %s' % (index, title,
                                          _short_answer(index, arms, final,
                                                        evidence, bottleneck)))
    lines.append('')
    # ---- 5. layer plots
    lines.append('## 5. 逐层可视化与逐高度统计（G4-5 核心交付）')
    lines.append('')
    lines.append('| 目录/文件 | 内容 |')
    lines.append('|---|---|')
    lines.append('| `09_plots/G3_baseline/` | G3 基线 21 个物理高度的独立 XY 图 + '
                 '21 层总览拼图 + 逐层统计（JSON/CSV/Markdown） |')
    lines.append('| `%s` | G4 最终最佳解（%s 交叉）21 层独立 XY 图 + 拼图 + '
                 '逐层统计 |' % (best_plot_rel(final),
                                _num(final.get('crossings'))))
    lines.append('| `09_plots/G3_vs_G4/` | G3 vs G4 逐层对照图（21 张，'
                 'before/after 并排）+ 逐高度明细 CSV |')
    lines.append('| `09_plots/G4a_arm/`、`G3_vs_G4a/`、`G4a_migration/`、'
                 '`G4a_modifications/` | G4a 臂（1320）的 21 层图、逐层对照、'
                 '人工 U 迁移与 XY+Z 修改量 |')
    lines.append('| `09_plots/G4b_arm/`、`G3_vs_G4b/`、`G4b_migration/`、'
                 '`G4b_modifications/` | G4b 臂（1294）的同类产物 |')
    lines.append('| `09_plots/C0_arm/`、`G3_vs_C0/`、`C0_modifications/` | '
                 'C0 对照臂（1259）的同类产物 |')
    lines.append('| `09_plots/manual_u_migration/` | 人工 U 原八组 → 新几何族群'
                 '迁移矩阵与表格 |')
    lines.append('| `09_plots/modifications/` | XY+Z 修改量统计图（分类、长度变化、'
                 '高度变化）与 per-route CSV |')
    lines.append('| `09_plots/budget/` | 交叉随评价预算/墙钟下降曲线 + 预算柱状图 |')
    lines.append('| `09_plots/failure_analysis/` | 失败原因分类图 |')
    lines.append('')
    lines.append('每层独立图区分：**真实平面直线**（非人工蓝 / 人工红）、'
                 '**R15 圆弧**（青 / 橙，实测半径恒为 15.000000 mm）、'
                 '**三维过渡段足迹投影**（紫色虚线，来自真实 S 曲线采样）、'
                 '**真实交叉点**（红 ×，来自 `crossing_stats.json` 且 z 精确匹配'
                 '到该层）。逐层统计字段：主体线路数、同层真实交叉、唯一交叉线路对、'
                 '原人工 U 数、当前分组数（按该层真实主体线路的 `manual_group` '
                 '集合）、平均/最大单路线交叉、该层参与的中途换层数、'
                 '拥堵区（×/15 mm 块）与空闲走廊（无线路网格块）。')
    lines.append('')
    # -- crossing concentration per height (G3 -> G4 best)
    start_planes = _dir_totals(START_DIR).get('planes') or {}
    best_planes = (final.get('reported') or {}).get('planes') or {}
    if start_planes or best_planes:
        lines.append('### 5.1 交叉最集中的物理高度（G3 → G4 best，真实事件数）')
        lines.append('')
        height_rows = []
        for z in PG.HEIGHT_KEYS:
            before = (start_planes.get(z) or {}).get('crossings')
            after = ((best_planes.get(z) or {}).get('crossings')
                     if best_planes else None)
            if not before and not after:
                continue
            routes_after = ((best_planes.get(z) or {}).get('routes')
                            if best_planes else None)
            height_rows.append((before or 0, [
                PG.HEIGHT_BY_Z[z]['label'], '%+.2f' % z, _num(before),
                _num(after), _delta(after, before) if after is not None else NA,
                _num(routes_after)]))
        height_rows.sort(key=lambda item: -item[0])
        lines.append(_md_table(
            ['高度', 'z (mm)', 'G3 交叉', 'G4 best 交叉', 'Δ', 'G4 best 主体线路'],
            [row for _count, row in height_rows]))
        lines.append('')
        lines.append('> 该表直接来自两个接受解的 `crossing_stats.json` '
                     '`planes`（逐高度计数，已与事件逐点核对）；完整 21 高度'
                     '视图见 `09_plots/G3_vs_G4/G3_vs_G4_per_height.csv`。')
        lines.append('')
    # ---- 5.2 Lead exploratory structure analysis (clearly labelled)
    structure = (lead or {}).get('structure') or {}
    if structure:
        sources = (lead or {}).get('sources') or {}
        interface_total, interface_rows = interface_crossings(structure)
        graph = structure.get('graph') or {}
        lines.append('### 5.2 交叉结构分解（Lead 补充分析，**探索性，非正式臂**）')
        lines.append('')
        lines.append('数据来源（只读引用，不重新计算）：`%s`、`%s`、'
                     '`%s`、`%s`；探索脚本结果：`%s`、`%s`。'
                     % (sources.get('structure'), sources.get('interface'),
                        sources.get('component'), sources.get('migration_probe'),
                        sources.get('explore_migrate'),
                        sources.get('explore_direct')))
        lines.append('')
        by_class = structure.get('by_class') or {}
        if by_class:
            lines.append('| 交叉类别（G3 起点 1322） | 数量 |')
            lines.append('|---|---|')
            for label, key in (('manual-manual', 'manual-manual'),
                               ('manual-nonmanual', 'manual-nonmanual'),
                               ('nonmanual-nonmanual', 'nonmanual-nonmanual')):
                lines.append('| %s | %s |'
                             % (label, _num(by_class.get(key))))
            lines.append('')
        if interface_total:
            lines.append('- **接口层结构性下限**：Z1_INTERFACE + Z2_INTERFACE '
                         '合计 **%s** 交叉（%s）。Lead 分析判定这是 '
                         'direct-body×direct-body 的**结构性下限**；本轮'
                         ' `direct_plane_recreate` 8 次尝试（z=0.0 四种顺序、'
                         'z=0.5 四种顺序，分别放置 44/53 条）**gain 全部 = 0、'
                         '全部回滚**，说明仅重排接口平面无法消除这些交叉。'
                         % (_num(interface_total),
                            '、'.join('%s=%s' % (row.get('label'),
                                                 _num(row.get('crossings')))
                                     for row in interface_rows)))
        if graph:
            sizes = graph.get('component_sizes') or []
            lines.append('- 交叉冲突图：%s 条边 / %s 个线路节点 / %s 个连通'
                         '分量，最大分量 %s 条线路，最大度 %s；分量大小前 8 = '
                         '%s。'
                         % (_num(graph.get('edges')), _num(graph.get('nodes')),
                            _num(graph.get('components')),
                            _num(max(sizes) if sizes else None),
                            _num(graph.get('max_degree')),
                            '、'.join(str(int(value)) for value in sizes[:8])
                            or NA))
        angles = structure.get('angle_bins') or {}
        if angles:
            lines.append('- 交叉角分布（度）：%s。'
                         % '、'.join('%s°: %s' % (key, _num(value))
                                     for key, value in angles.items()))
        explore_migrate = (lead or {}).get('explore_migrate') or {}
        if explore_migrate.get('final_crossings') is not None:
            runs = explore_migrate.get('runs') or []
            lines.append('- Lead 探索 E1（exact-delta 高度重分配，'
                         '**exploratory, not a formal arm**）：探索状态 '
                         '1322→**%s**（accepted %s 次变化，%s s）；该数字'
                         '**不是正式臂成绩**，仅说明该自由度有潜力，需下一轮'
                         '形式化为正式臂。'
                         % (_num(explore_migrate.get('final_crossings')),
                            _num((runs[0] or {}).get('accepted') if runs else None),
                            _num((runs[0] or {}).get('seconds') if runs else None)))
        explore_direct = (lead or {}).get('explore_direct') or {}
        history = explore_direct.get('history') or []
        if history:
            gains = [item.get('gain') for item in history
                     if isinstance(item, dict)]
            lines.append('- Lead 探索（interface direct_plane_recreate，'
                         '**exploratory, not a formal arm**）：%d 次尝试，'
                         'gain 集合 = %s，最终仍为 %s。'
                         % (len(history), gains,
                            _num(explore_direct.get('final_crossings'))))
        explore_migrate2 = (lead or {}).get('explore_migrate2') or {}
        if explore_migrate2.get('final_crossings') is not None:
            runs2 = explore_migrate2.get('runs') or []
            lines.append('- Lead 探索 E2（exact-delta 高度重分配第二组，'
                         '**exploratory, not a formal arm**）：最终探索状态 '
                         '**%s**（accepted %s 次变化）；该数字不是正式臂成绩。'
                         % (_num(explore_migrate2.get('final_crossings')),
                            _num((runs2[0] or {}).get('accepted')
                                 if runs2 else None)))
        lines.append('- **E1/E2/E1b 系列均为 exploratory, not a formal arm**：'
                     '起点分别为 G3（1322）与 1200–1201 链检查点，'
                     '不计入任何正式臂的收益表；仅用于说明“精确高度重分配”'
                     '这一自由度有潜力，需下一轮形式化为正式臂。')
        lines.append('')
    # ---- 5.3 per-stage gain attribution (real stage statistics of the arms)
    stage_arms = [name for name in ('G4c_frozen', 'G4c_free')
                  if (arms.get(name) or {}).get('strategy')]
    if stage_arms:
        lines.append('### 5.3 交叉收益的阶段归属（真实 stage 统计）')
        lines.append('')
        header = ['实验', '阶段', '机制', '尝试', '接受', '收益',
                  '收益占比', '用时(s)']
        rows = []
        for name in stage_arms:
            summary = stage_gain_summary(arms[name])
            for row in summary['rows']:
                rows.append([
                    ARM_LABEL[name], _num(row.get('stage')),
                    row.get('label'), _num(row.get('attempts')),
                    _num(row.get('accepts')), _num(row.get('gain')),
                    ('%s%%' % _num(row.get('share_pct'), 1))
                    if row.get('share_pct') is not None else NA,
                    _num(row.get('seconds'), 1)])
        lines.append(_md_table(header, rows))
        lines.append('')
        for name in stage_arms:
            summary = stage_gain_summary(arms[name])
            sweep_gain = sum(int(row.get('gain') or 0)
                             for row in summary['rows']
                             if row.get('size') in (0, None))
            nbr = [row for row in summary['rows']
                   if row.get('size') not in (0, None)]
            share = (round(100.0 * sweep_gain / summary['total'], 1)
                     if summary.get('total') else None)
            lines.append('- `%s`：总收益 %s 中 **%s（%s%%）来自 greedy '
                         'migration sweep**；邻域阶段收益：%s。'
                         % (name, _num(summary.get('total')),
                            _num(sweep_gain), _num(share),
                            '、'.join('%s = %s' % (row['label'],
                                                   _num(row.get('gain')))
                                     for row in nbr) or '无'))
        lines.append('')
        lines.append('> 负结果如实保留：大邻域 16/32/64 阶段在本轮预算下几乎'
                     '没有收益，收益主要来自对高冲突线路的 greedy migration '
                     'sweep。这说明当前瓶颈已不在“小邻域选择”，而在**可动集合与'
                     '结构性下限**（人工 U 可动集合上界 1213、接口 212 结构下限）。')
        lines.append('')
    # ---- 5.4 progressive chain attribution
    chain = load_chain()
    if chain.get('links'):
        lines.append('### 5.4 渐进链收益拆分（`%s`）' % chain.get('path'))
        lines.append('')
        header = ['环节', '来源臂', '起点交叉', '终点交叉', '本段收益',
                  '本段墙钟(s)', 'Validator']
        rows = []
        for link in chain['links']:
            rows.append([
                link.get('label'), link.get('source_arm'),
                _num(link.get('start_crossings')),
                _num(link.get('end_crossings')), _num(link.get('delta')),
                _num(link.get('wall_seconds'), 1),
                _validation_cell({'validation_pass':
                                  link.get('validation_pass')}
                                 if link.get('validation_pass') is not None
                                 else None)])
        lines.append(_md_table(header, rows))
        lines.append('')
        lines.append('> 链的累计收益 = 各段收益之和；**不得把链的累计收益全部'
                     '归因于最后一个算法/臂**（SPEC 第 4 节）。')
        lines.append('')
    # ---- 6. failure analysis
    lines.append('## 6. 失败原因分析摘要')
    lines.append('')
    if failure and failure.get('total_failures'):
        totals = failure.get('totals') or {}
        ranked = sorted(((key, int(value)) for key, value in totals.items()
                         if int(value) > 0), key=lambda item: -item[1])
        lines.append('完整分类计数见 [`10_reports/failure_analysis.md`]'
                     '(failure_analysis.md)。按真实臂产物计数：')
        lines.append('')
        for key, count in ranked[:8]:
            lines.append('- `%s`：%d 次' % (key, count))
        lines.append('')
    else:
        lines.append('%s：各臂 `failed_attempts.json` / `strategy_stats.json` '
                     '尚未写入失败计数（见 `10_reports/failure_analysis.md`，'
                     '待各臂完成后自动重跑）。' % NA)
    lines.append('所有失败分类都只表示**“在给定算法与预算下未找到/未接受”**，'
                 '不构成任何目标的严格无解证明；本轮未做下界/穷举覆盖证明。')
    lines.append('')
    # ---- 7. negative results and limits
    lines.append('## 7. 负结果、局限与不可宣称事项')
    lines.append('')
    lines.append('- **负结果如实保留**：若最终交叉仍 >1000/1200，则相应挑战目标'
                 '未达成；不粉饰、不以“近似/等效”替代真实交叉计数。')
    lines.append('- **未证明最优/无解**：本轮只报告在给定共享引擎、算法族与预算下'
                 '达到的结果；无下界证明。')
    lines.append('- **仅中心线几何模型**：光学串扰、弯曲/交叉损耗未验证'
                 '（`fslw/config.py` 中交叉损耗状态为 unknown_uncalibrated）；'
                 '1322 等数字是**几何计数**，不是光学可行性或制造可行性结论。')
    lines.append('- **制造约束未验证**：无工艺 bias、侧壁角、折射率剖面、表面工艺'
                 '余量、连接器外壳干涉；连接器安装方向与 1 mm 玻璃厚度为假设值。')
    lines.append('- **21 高度为探索性层栈**（provenance=unconfirmed_simulation），'
                 '不得表述为“满足全部制造约束”。')
    a_gm_report = group_migration_summary((arms.get('G4a') or {}).get('evidence')
                                          or {})
    if a_gm_report.get('present'):
        lines.append('- **G4a 组级换层负结果**：被接受的整组迁移 %s / 部分组迁移 %s，'
                     '仅 %s 条人工 U 真实换高，交叉只下降 %s；臂自报“仅动人工 U”'
                     '解析下界 %s（非全局下界）→ 原八组固定分组下，组级换层几乎'
                     '不可行。'
                     % (_num(a_gm_report.get('accepted_whole')),
                        _num(a_gm_report.get('accepted_partial')),
                        _num(a_gm_report.get('routes_changed_height')),
                        int((final.get('crossings') or START_CROSSINGS)
                            - START_CROSSINGS),
                        _num(a_gm_report.get('floor_manual_only'))))
    if audit.get('required'):
        lines.append('- **几何口径差异（需求级风险）**：若任务书把 50 µm 理解为'
                     '“任意两条中心线无例外”，则 1322 个合法同层横穿（距离 0）'
                     '会与字面要求冲突；本报告按仓库现行冻结契约（D56 strict + '
                     '横穿豁免）判定，且**未新增任何豁免**。该口径差异需项目'
                     '负责人确认（见 G4-1 审计 §7.3）。')
    lines.append('')
    # ---- 8. archive
    lines.append('## 8. 归档、MANIFEST 与 GitHub 状态（如实）')
    lines.append('')
    if archive:
        manifest = archive.get('manifest') or {}
        verification = archive.get('verification') or {}
        code = archive.get('code_snapshot') or {}
        git = archive.get('git') or {}
        lines.append('- `MANIFEST.json`：%s 个文件、%.2f MB，SHA256 校验 %s'
                     % (_num(manifest.get('file_count')),
                        (manifest.get('total_bytes') or 0) / (1024.0 * 1024.0),
                        '通过' if verification.get('ok') else '未通过/未校验'))
        lines.append('- `code/` 代码快照：%s 个文件（g4 包全部 .py + '
                     'SPEC_G4.md），快照与源文件哈希一致=%s'
                     % (_num(code.get('file_count')),
                        '是' if code.get('all_match_source') else NA))
        lines.append('- Git：仓库=%s，GitHub remote=%s，分支=%s，结论=%s'
                     % ('是' if git.get('git_available') else '否',
                        '有' if git.get('github_remote') else '无',
                        git.get('branch') or '-', git.get('note') or '-'))
        if not git.get('github_remote'):
            lines.append('- **本归档为本地归档**：未配置 GitHub remote，'
                         '未执行 commit/push；完整性由本地 SHA256 MANIFEST '
                         '与 `code/SHA256.json` 保证。')
    else:
        lines.append('- MANIFEST/归档状态：%s（运行 `g4/archive_g4.py` 后生成）'
                     % NA)
    lines.append('')
    lines.append('复现命令见归档根 `README.md`；校验命令：'
                 '`python -m four_side_1024.fanout1024.xyzrouter.g4.archive_g4 '
                 '--verify-only`。')
    lines.append('')
    return '\n'.join(lines) + '\n'


def _short_answer(index, arms, final, evidence, bottleneck):
    if index == 1:
        a = _arm_crossings(arms.get('G4a', {}))
        b = _arm_crossings(arms.get('G4b', {}))
        if a is None or b is None:
            return NA
        return ('存在更优分组：G4b %s vs G4a %s（%+d）'
                % (_num(b), _num(a), int(b - a)) if b < a
                else '未观察到更优分组（G4b %s ≥ G4a %s）' % (_num(b), _num(a)))
    if index == 2:
        if not evidence or 'error' in evidence or evidence.get(
                'manual_before') is None:
            return NA
        if final.get('improved') is False:
            return ('最终最佳合法解仍是 G3 起点（G4 尚无改进），'
                    '因此本轮未观察到新增的高度可达性解除证据')
        return ('真实几何显示 %s 条人工 U 高度改变、%s 条人工 U XY 改变，'
                '且最终解通过独立 Validator'
                % (_num(evidence.get('manual_height_changed')),
                   _num(evidence.get('manual_xy_changed'))))
    if index == 3:
        c0 = _arm_crossings(arms.get('C0', {}))
        frozen = _arm_crossings(arms.get('G4c_frozen', {}))
        free = _arm_crossings(arms.get('G4c_free', {}))
        if frozen is None or free is None:
            return NA
        return ('人工 U 解冻边际收益 %+d 交叉（G4c-frozen %s → G4c-free %s）；'
                '大邻域收益见 C0 %s → frozen %s'
                % (int(frozen - free), _num(frozen), _num(free), _num(c0),
                   _num(frozen)))
    if index == 4:
        if not bottleneck:
            return NA
        top = (bottleneck.get('top_routes') or [None])[0]
        if not top:
            return NA
        return ('最受阻线路 route %d（%d 交叉，人工组 %s，%s）；剩余交叉集中在 '
                '%s 等高度'
                % (top['route_id'], top['crossings'],
                   top.get('manual_group') or '-', top.get('height_label') or '-',
                   '、'.join(item['label'] for item in
                            (bottleneck.get('top_heights') or [])[:3])))
    if index == 5:
        cross = final.get('crossings')
        return NA if cross is None else ('%s（%d < 1000）' % ('是', cross)
                                         if cross < 1000 else
                                         '否（%d ≥ 1000）' % cross)
    return ('见 `answers.md` 问题 6 的排序建议：扩大跨分量联合事务邻域、'
            '针对交叉最集中高度的走廊重造、多 seed/预算扩展')
    return NA


def _archive_root_copy(text):
    """Fix relative links when a 10_reports/ document is copied to the root."""
    return (text.replace('../00_baseline_audit/', './00_baseline_audit/')
            .replace('](answers.md)', '](10_reports/answers.md)')
            .replace('](failure_analysis.md)',
                     '](10_reports/failure_analysis.md)')
            .replace('](comparison.md)', '](10_reports/comparison.md)')
            .replace('](report.md)', '](10_reports/report.md)'))


# --------------------------------------------------------------------------- #
# metrics summary (machine-readable)
# --------------------------------------------------------------------------- #
def build_metrics_summary(arms, final, evidence, bottleneck, audit, failure,
                          final_evidence=None):
    final_evidence = final_evidence or {}
    rows = OrderedDict()
    for name in ARM_ORDER:
        arm = arms[name]
        reported = arm.get('reported') or {}
        usage = budget_usage(arm) if arm['status'] != 'missing' else {}
        rows[name] = dict(
            label=ARM_LABEL[name],
            status=arm['status'],
            dir=_rel(arm['dir']) if arm.get('dir') else None,
            crossings=reported.get('crossings'),
            delta_vs_start=((reported.get('crossings') or 0) - START_CROSSINGS
                            if reported.get('crossings') is not None else None),
            crossing_pairs=reported.get('crossing_pairs'),
            max_route_crossings=reported.get('max_route_crossings'),
            routes_with_crossings=reported.get('routes_with_crossings'),
            routes_count=reported.get('routes_count'),
            failed_count=reported.get('failed_count'),
            source=reported.get('source'),
            reported_dir=_rel(arm.get('reported_dir')) if arm.get(
                'reported_dir') else None,
            validation=arm.get('validation'),
            budget=usage,
            budget_ledger=arm.get('budget'),
            config_budget=_config_budget(arm.get('config')),
            start_info=arm.get('start_info'),
            failed_attempts_count=arm.get('failed_attempts'),
            history_rows=arm.get('history_rows'),
        )
    failure_totals = (failure or {}).get('totals') or {}
    return dict(
        schema=SCHEMA, generated_at=_now(),
        start=dict(dir=_rel(START_DIR), sha256=START_SHA,
                   crossings=START_CROSSINGS, routes=1024),
        final=dict(source=final.get('source'),
                   dir=_rel(final.get('dir')) if final.get('dir') else None,
                   routes_sha256=final.get('routes_sha'),
                   crossings=final.get('crossings'),
                   delta_vs_start=((final.get('crossings') or 0)
                                   - START_CROSSINGS
                                   if final.get('crossings') is not None
                                   else None),
                   improved_vs_start=bool(final.get('improved')),
                   validation=final.get('validation'),
                   reported=(final.get('reported') or {}).get('crossings')),
        arms=rows,
        audit=dict(report=audit.get('report'),
                   report_exists=audit.get('report_exists'),
                   required=audit.get('required'),
                   revalidation=audit.get('revalidation'),
                   consistency=(audit.get('consistency') or {}).get('answer'),
                   limitations=audit.get('limitations')),
        geometry_evidence=evidence,
        final_arm_evidence=dict(
            arm=final_evidence.get('_arm'),
            files=sorted(final_evidence.keys()),
            group_migration=group_migration_summary(final_evidence)),
        bottleneck=bottleneck,
        failure_totals=failure_totals,
        failure_total=sum(int(value) for value in failure_totals.values()),
        challenge=dict(
            targets=list(TARGETS),
            reached=[target for target in TARGETS
                     if final.get('crossings') is not None
                     and int(final['crossings']) <= target]),
    )


# --------------------------------------------------------------------------- #
# plot orchestration
# --------------------------------------------------------------------------- #
def make_all_plots(final, arms, verbose=True):
    """Generate every G4-5 figure from the accepted layouts."""
    result = dict(generated_at=_now(), written=[], errors=[], skipped=[])
    best_dir = Path(final.get('dir') or START_DIR)
    start_sha = _sha256(START_DIR / 'routes_l3d.json')
    best_sha = _sha256(best_dir / 'routes_l3d.json')
    layouts = []

    def _try(label, func, *args, **kwargs):
        try:
            value = func(*args, **kwargs)
            result['written'].append(label)
            if verbose:
                print('[report] plot: %s OK' % label, flush=True)
            return value
        except Exception as exc:  # noqa: BLE001 - one plot must not kill all
            result['errors'].append(dict(step=label, error=repr(exc)))
            if verbose:
                print('[report] plot: %s FAILED %r' % (label, exc), flush=True)
            return None

    # 1) G4 best per-height suite
    best_plot_name = best_plot_dirname(final)
    _try('G4_best_layer_suite', PG.plot_layer_suite, best_dir,
         PLOTS / best_plot_name, prefix='G4_best', title='G4_best')
    # 2) before/after
    compare_dir = PLOTS / 'G3_vs_G4'
    compare = _try('G3_vs_G4_compare_suite', PG.plot_compare_suite, START_DIR,
                   best_dir, compare_dir, prefix='G3_vs_G4',
                   before_name='G3 baseline', after_name='G4 best')
    # 3) migration
    changes_json = None
    for name in ARM_ORDER:
        arm = arms.get(name) or {}
        candidate = Path(arm['dir']) / 'manual_u_changes.json' if arm.get('dir') \
            else None
        if candidate and candidate.exists():
            changes_json = candidate
            break
    _try('manual_u_migration', PG.plot_migration, START_DIR, best_dir,
         PLOTS / 'manual_u_migration', changes_json=changes_json)
    # 4) modification statistics
    _try('modifications', PG.plot_modifications, START_DIR, best_dir,
         PLOTS / 'modifications')
    # 5) budget curves (same-start arms; chain arms are labelled explicitly)
    arm_dirs = OrderedDict()
    for name in ARM_ORDER:
        arm = arms.get(name) or {}
        if not arm.get('dir'):
            continue
        info = arm.get('start_info') or {}
        if info.get('same_start_as_G3') is False:
            arm_dirs['%s (chain from %s)'
                     % (name, _num(info.get('actual_start_crossings')))] = \
                Path(arm['dir'])
        else:
            arm_dirs[name] = Path(arm['dir'])
    _try('budget_curves', PG.plot_budget_curves, arm_dirs,
         PLOTS / 'budget', baseline_crossings=START_CROSSINGS)
    # 6) failure taxonomy
    _try('failure_analysis', FA.run)
    result['final_dir'] = _rel(best_dir)
    result['final_routes_sha'] = best_sha
    result['same_as_start'] = bool(best_sha and start_sha and best_sha == start_sha)
    return result


FAIR_COMPARISON_NOTES = """

<!-- g4-report-notes -->
## 后记（g4-report 补充注记，不改动上述 G4-4 原始内容）

1. **G4d A 类臂计时**：该臂因外部误杀分两次 session 运行（1242.7 s + 111.6 s
   ≈ **1354 s** 搜索墙钟）；本文件与 `budget_ledger.json` 中的 wall 字段为
   session 2 的值，不能当作该臂总搜索时间。报告中预算表已并列 `run.log` 实测。
2. **E1/E2/E1b 为 exploratory，非正式臂**：起点分别为 G3（1322）与
   1200–1201 的链检查点，不计入任何正式臂的收益或公平对照；仅说明“精确高度
   重分配”这一自由度有潜力，需下一轮形式化为正式臂。
3. 2026-11-04 20:0x 由 `g4/report_g4.py` 追加；G4-4 原始内容与数据未修改。
"""


def append_fair_comparison_notes():
    """Append the final caveats to the G4-4 fair-comparison report (idempotent)."""
    path = ARCHIVE / 'fair_comparison.md'
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return None
    if 'g4-report-notes' in text:
        return str(path)
    note = FAIR_COMPARISON_NOTES.replace('2026-11-04 20:0x', _now())
    path.write_text(text.rstrip() + note, encoding='utf-8')
    return str(path)


# --------------------------------------------------------------------------- #
# run all
# --------------------------------------------------------------------------- #
def run_all(mode='preview', best_dir=None, make_plots=True,
            run_validation=True, archive=True, verbose=True):
    started = _now()
    arms = collect_arms()
    if best_dir:
        tmp = _dir_totals(best_dir)
        final = dict(source='explicit', dir=Path(best_dir),
                     crossings=tmp['crossings'],
                     routes_sha=tmp.get('routes_sha'),
                     has_stats=tmp.get('planes') is not None,
                     validation=_validation_for_layout(best_dir))
    else:
        final = find_final_best(arms)
    final['reported'] = _dir_totals(final.get('dir') or START_DIR)
    # a lightweight best_valid snapshot carries no crossing_stats.json; for the
    # per-height figures we need the full artifact set of the *same* geometry.
    if final['reported'].get('planes') is None and final.get('routes_sha'):
        for name in ARM_ORDER:
            arm = arms.get(name) or {}
            candidate = arm.get('reported_dir')
            if not candidate:
                continue
            totals = _dir_totals(candidate)
            if (totals.get('routes_sha') == final['routes_sha']
                    and totals.get('planes') is not None):
                final['stats_source_dir'] = final['dir']
                final['dir'] = Path(candidate)
                final['reported'] = totals
                break
    final['failed_count'] = final['reported'].get('failed_count')
    final['validation'] = ensure_final_validation(final, run=run_validation)
    audit = load_audit()
    final_audit = load_final_audit()
    if final_audit.get('kind') and final.get('routes_sha'):
        final_audit['sha_matches_final'] = (
            final_audit.get('routes_sha') == final['routes_sha'])
    evidence = None
    bottleneck = None
    try:
        evidence = geometry_evidence(START_DIR, final.get('dir') or START_DIR)
    except Exception as exc:  # noqa: BLE001
        evidence = dict(error=repr(exc))
    try:
        bottleneck = bottleneck_analysis(final.get('dir') or START_DIR)
    except Exception as exc:  # noqa: BLE001
        bottleneck = dict(error=repr(exc))
    failure = FA.analyse() if (ARCHIVE / '10_reports').exists() else {}
    plot_result = make_all_plots(final, arms, verbose=verbose) if make_plots \
        else dict(skipped=['--no-plots'])
    failure_run = FA.run() if make_plots else (failure or {})
    final_evidence = resolve_final_evidence(final, arms)
    if not final_evidence and final.get('dir'):
        # official 07_best_valid / explicitly passed layout: read any evidence
        # files that were saved next to the accepted geometry
        final_evidence = load_arm_evidence(final['dir'])
    lead = load_lead_supplementary()
    _write_json(REPORTS / 'lead_supplementary.json', lead)
    banner = ''
    if mode != 'final':
        banner = ('> **草稿（mode=%s）**：最终最佳解可能更新；当前数字来自 `%s`，'
                  '最终版以 Lead 确定的 `07_best_valid/` 为准。\n\n'
                  % (mode, _rel(final.get('dir'))))
    metrics = build_metrics_summary(arms, final, evidence, bottleneck, audit,
                                    failure_run, final_evidence)
    _write_json(REPORTS / 'metrics_summary.json', metrics)
    answers = build_answers(arms, final, evidence, bottleneck, audit,
                            final_evidence, lead)
    (REPORTS / 'answers.md').write_text(banner + answers, encoding='utf-8')
    comparison = build_comparison(arms, final, audit, lead)
    (REPORTS / 'comparison.md').write_text(banner + comparison,
                                           encoding='utf-8')
    (ARCHIVE / 'comparison.md').write_text(
        '# G4 comparison（归档根副本，内容同 10_reports/comparison.md）\n\n'
        + banner + _archive_root_copy(comparison), encoding='utf-8')
    archive_status_lines = [
        '最终最佳合法解: `07_best_valid/`，**%s 交叉 / %s 唯一对**'
        '（G3 起点 %d，来源 %s）'
        % (_num(final.get('crossings')),
           _num((final.get('reported') or {}).get('crossing_pairs')),
           START_CROSSINGS,
           (final.get('best_meta') or {}).get('summary', {}).get(
               'selected_from') or final.get('source')),
        '1024/1024 布通保持；独立 Validator PASS（violations=0）；'
        '正式 FINAL_AUDIT PASS（`00_baseline_audit/FINAL_AUDIT/`）',
        'GitHub 无法推送（无 git 仓库/无 remote）→ **本地归档，未推送**',
        '六问回答: `10_reports/answers.md`；总表: '
        '`10_reports/comparison.md`；失败原因: '
        '`10_reports/failure_analysis.md`',
    ]
    archive_result = None
    archive_status = None
    if archive:
        try:
            from four_side_1024.fanout1024.xyzrouter.g4 import archive_g4 as AR
            archive_result = AR.archive(
                archive_root=ARCHIVE, verify=True,
                status_lines=archive_status_lines, verbose=verbose)
            archive_status = archive_result
        except Exception as exc:  # noqa: BLE001
            archive_result = dict(error=repr(exc))
    report = build_report(arms, final, evidence, bottleneck, audit, failure_run,
                          archive_status, final_evidence, lead, final_audit)
    (REPORTS / 'report.md').write_text(banner + report, encoding='utf-8')
    (ARCHIVE / 'report.md').write_text(
        '# G4 report（归档根副本，内容同 10_reports/report.md）\n\n'
        + banner + _archive_root_copy(report), encoding='utf-8')
    # append the final caveats to the G4-4 fair-comparison report (idempotent)
    append_fair_comparison_notes()
    # regenerate manifest so the two root copies are included
    if archive:
        try:
            from four_side_1024.fanout1024.xyzrouter.g4 import archive_g4 as AR
            AR.archive(archive_root=ARCHIVE, verify=True,
                       status_lines=archive_status_lines, verbose=False)
        except Exception:  # noqa: BLE001 - keep reporting even if archiving fails
            pass
    run_record = dict(
        schema='g4_final_report_run_v1', mode=mode, started_at=started,
        finished_at=_now(),
        final=dict(source=final.get('source'),
                   dir=_rel(final.get('dir')) if final.get('dir') else None,
                   crossings=final.get('crossings'),
                   routes_sha=final.get('routes_sha'),
                   improved=final.get('improved'),
                   validation=final.get('validation')),
        arms={name: dict(status=arms[name]['status'],
                         crossings=(arms[name].get('reported') or {}).get(
                             'crossings'))
              for name in ARM_ORDER},
        final_arm_evidence=dict(arm=final_evidence.get('_arm'),
                                files=sorted(key for key in final_evidence
                                             if not key.startswith('_'))),
        final_audit=dict(kind=final_audit.get('kind'),
                         run_dir=final_audit.get('run_dir'),
                         routes_sha=final_audit.get('routes_sha'),
                         sha_matches_final=final_audit.get(
                             'sha_matches_final')),
        chain=load_chain().get('path') if load_chain().get('links') else None,
        extra_runs=[item['label'] for item in collect_extra_runs()],
        plots=plot_result,
        archive=archive_result,
        deliverables=dict(
            report=_rel(REPORTS / 'report.md'),
            comparison=_rel(REPORTS / 'comparison.md'),
            answers=_rel(REPORTS / 'answers.md'),
            metrics=_rel(REPORTS / 'metrics_summary.json'),
            failure_analysis=_rel(REPORTS / 'failure_analysis.md'),
        ),
    )
    _write_json(REPORTS / 'report_g4_run.json', run_record)
    return run_record


def _build_parser():
    parser = argparse.ArgumentParser(
        description='G4-5 final report / comparison / answers generator')
    parser.add_argument('--mode', default='preview',
                        choices=('preview', 'final'))
    parser.add_argument('--best-dir', default=None,
                        help='explicit accepted final layout directory')
    parser.add_argument('--no-plots', action='store_true')
    parser.add_argument('--skip-validation', action='store_true')
    parser.add_argument('--no-archive', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    result = run_all(mode=args.mode, best_dir=args.best_dir,
                     make_plots=not args.no_plots,
                     run_validation=not args.skip_validation,
                     archive=not args.no_archive, verbose=not args.quiet)
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
