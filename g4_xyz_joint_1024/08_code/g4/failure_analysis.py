# -*- coding: utf-8 -*-
"""G4-5 failure analysis: aggregate the real failure counters of every G4 arm
into the SPEC_G4.md section-6 taxonomy.

Data sources (all read-only):
    <arm>/failed_attempts.json     individual failed attempts (reason per row)
    <arm>/strategy_stats.json      per stage/round counters + reason histograms
    <arm>/budget_ledger.json       real shared-engine budget counters
    <arm>/config.json              budget limits / arm configuration
    <arm>/run.log                  wall-clock log (only referenced, not parsed)

The analysis never invents numbers: every count is the sum of an integer that
exists in an arm artifact.  Missing arms are reported as "进行中/未完成".

Important epistemology (SPEC section 6, task requirement):
the taxonomy separates **"the algorithm did not find a solution within the
given budget"** from **"strictly proven infeasible"**.  This module only ever
claims the former; no lower-bound / exhaustive-cover proof is produced, so all
reported failure classes are search-side observations, never infeasibility
proofs.

Outputs (written by ``main``):
    10_reports/failure_analysis.json
    10_reports/failure_analysis.csv
    10_reports/failure_analysis.md
    09_plots/failure_analysis/failure_reasons.png   (when data exists)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

SCHEMA = 'g4_failure_analysis_v1'

#: SPEC_G4.md section 6 taxonomy (Chinese one-line definition each)
SPEC_CLASSES = OrderedDict([
    ('no_legal_xy_corridor',
     '目标高度上找不到满足严格 D56 / R15 / 引线约束的平面 XY 路径'),
    ('target_height_occupied',
     '目标物理高度已被其它 body 线路占用（同高度 D56 无法放置）'),
    ('r15_geometry_rejected',
     'R15 几何原语无法组装（圆弧 / 双弧 S 过渡 / 引线几何被拒）'),
    ('transition_3d_conflict',
     '三维 S 过渡与其它层线路 / 过渡的 3D 中心线净空 < 0.05 mm'),
    ('lead_below_minimum',
     '端口引线长度低于下限，路线几何不可用'),
    ('joint_rebuild_failed',
     '联合事务（多线 rip+plan+place）无法全体同时合法，整体回滚'),
    ('legal_but_no_crossing_improvement',
     '候选几何合法但没有降低同层交叉（不满足 min_gain，拒绝进入接受流）'),
    ('budget_exhausted',
     '达到 route_3d_checks / d56_candidate_evals / 墙钟预算上限而停止'),
    ('no_current_crossings',
     '目标线路当前没有交叉，无需优化'),
    ('structure_error',
     '状态 / 接口 / 数据结构异常导致尝试失败'),
    ('unclassified', '未归类的失败原因（保留原始 key，不丢弃）'),
])

#: raw engine / arm strings -> SPEC class
ALIASES = OrderedDict([
    ('no_legal_xy_corridor', (
        'no_legal_xy_corridor', 'no_xy_candidate', 'no_corridor',
        'no_legal_corridor', 'xy_corridor_failed', 'no_xy_path',
        'xy_corridor_missing', 'corridor_failed', 'no_candidate',
        'no_candidates', 'plan_no_candidate')),
    ('target_height_occupied', (
        'target_height_occupied', 'height_occupied', 'target_occupied',
        'occupied', 'height_full', 'target_layer_occupied',
        'layer_occupied')),
    ('r15_geometry_rejected', (
        'r15_geometry_rejected', 'geometry_rejected', 'r15_rejected',
        'r15_geometry', 'arc_rejected', 'curvature_rejected',
        'geometry_invalid', 'r15_reject', 'arc_failed', 'bend_rejected')),
    ('transition_3d_conflict', (
        'transition_3d_conflict', 'transition_vs_flat',
        'transition_vs_transition', 'transition_conflict', '3d_conflict',
        'transition_clearance', 'transition_overlap', 'world_3d_rejected',
        'true3d_rejected', 'transition_blocked', 'blocked_transition')),
    ('lead_below_minimum', (
        'lead_below_minimum', 'lead_short', 'lead_min', 'lead_too_short',
        'lead_insufficient')),
    ('joint_rebuild_failed', (
        'joint_rebuild_failed', 'transaction_failed', 'rebuild_failed',
        'tx_abort', 'tx_failed', 'plan_failed', 'place_failed',
        'transaction_rollback', 'rolled_back', 'abort', 'transaction_abort',
        'incomplete_set', 'incomplete_group', 'partial_placement',
        'partial_group', 'not_all_placed')),
    ('legal_but_no_crossing_improvement', (
        'legal_but_no_crossing_improvement', 'no_gain', 'no_improvement',
        'legal_no_gain', 'no_crossing_improvement', 'min_gain_not_met',
        'gain_too_small', 'not_improving', 'rejected_no_gain')),
    ('budget_exhausted', (
        'budget_exhausted', 'budget_stop', 'budget_limit', 'budget',
        'time_limit', 'wall_limit', 'budget_stop_curve')),
    ('no_current_crossings', (
        'no_current_crossings', 'no_targets', 'no_crossing_targets',
        'no_crossings', 'not_crossing', 'zero_crossings')),
    ('structure_error', (
        'structure_error', 'exception', 'error', 'build_error',
        'invalid_state', 'assertion_error', 'internal_error')),
])

REASON_CONTAINER_KEYS = ('reasons', 'failure_reasons', 'failed_reasons',
                         'failures', 'failed', 'abort_reasons', 'rejections',
                         'rejects', 'reason_counts', 'failure_counts',
                         'fail_reasons', 'by_reason')

#: metadata containers: never interpreted as failure-reason histograms
METADATA_CONTAINER_KEYS = {
    'ledger', 'budget_ledger', 'budget', 'config', 'cfg', 'arm', 'summary',
    'arm_summary', 'sha256', 'hashes', 'history', 'routes', 'seed', 'spec',
    'schema', 'start_snapshot', 'val', 'validation', 'stats_budget',
    'optimization_history', 'runtime', 'timing', 'timestamps', 'extra_cfg',
}

#: re-groupings of the same attempts -> split by a dimension, not new events
GROUPING_CONTAINER_KEYS = {
    'by_group', 'by_layer', 'by_arm', 'by_target', 'by_stage', 'by_phase',
    'by_round', 'per_group', 'per_layer', 'by_neighborhood', 'by_order',
}

#: attempt reasons that mean "this attempt was not a failure" (arms log them
#: in failed_attempts.json for completeness); they are counted separately and
#: are NOT added to the SPEC section-6 failure taxonomy.
OK_REASONS = {'ok', 'accepted', 'success', 'valid', 'legal', 'pass',
              'passed', 'valid_candidate', 'no_error'}

ARM_LABELS = OrderedDict([
    ('C0', 'C0 既有引擎续跑（无新自由度的公平对照）'),
    ('G4a', 'G4a 原八组固定成员、组级 XY+Z 重造'),
    ('G4b', 'G4b 人工 U 动态重分组'),
    ('G4c_frozen', 'G4c-frozen 人工 U 冻结、非人工线路联合让路 ALNS'),
    ('G4c_free', 'G4c-free 人工 U 解冻（可作目标/阻挡者）'),
    ('G4d', 'G4d 全部 1024 条大邻域全局优化'),
])


# --------------------------------------------------------------------------- #
# helpers
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


def _write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        path.write_text('', encoding='utf-8')
        return path
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})
    return path


def _to_int(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return int(round(number))


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def canonical_reason(raw):
    """Map one raw reason string onto the SPEC section-6 taxonomy."""
    text = str(raw or '').strip()
    if not text:
        return 'unclassified', ''
    key = text.lower().replace('-', '_').replace(' ', '_')
    key = key.strip('_')
    if key in SPEC_CLASSES:
        return key, text
    for canonical, aliases in ALIASES.items():
        if key in aliases:
            return canonical, text
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in key:
                return canonical, text
    return 'unclassified', text


# --------------------------------------------------------------------------- #
# discover arm artifacts
# --------------------------------------------------------------------------- #
def discover_sources(root=None):
    """``[{arm, label, dir, files:{...}, status}]`` for every arm directory."""
    root = Path(root or GP.G4_ROOT)
    specs = []
    for arm, label in ARM_LABELS.items():
        arm_dir = GP.ARM_DIRS.get(arm)
        if arm_dir is not None:
            specs.append((arm, label, Path(arm_dir)))
    for extra in ('best_valid', 'chain'):
        directory = GP.ARM_DIRS.get(extra)
        if directory is not None:
            specs.append((extra, extra, Path(directory)))
    sources = []
    seen = set()
    for arm, label, arm_dir in specs:
        candidates = [arm_dir]
        if arm_dir.exists():
            candidates.extend(sorted(path for path in arm_dir.rglob('*')
                                     if path.is_dir()
                                     and path.name in ('best_valid', 'stages')
                                     or (path.is_dir()
                                         and (path / 'failed_attempts.json').exists())))
        for directory in candidates:
            key = str(directory.resolve())
            if key in seen or not directory.exists():
                continue
            # scratch / probe directories are not formal arm artifacts
            try:
                parts = directory.relative_to(arm_dir).parts
            except ValueError:
                parts = directory.parts
            if any(part.startswith('_') for part in parts):
                continue
            seen.add(key)
            files = {}
            for filename in ('failed_attempts.json', 'strategy_stats.json',
                             'budget_ledger.json', 'config.json',
                             'group_attempts.json', 'regroup_attempts.json',
                             'attempts.json', 'failure_taxonomy.json',
                             'optimization_history.csv',
                             'summary.json', 'validation.json',
                             'routes_l3d.json'):
                direct = directory / filename
                if direct.exists():
                    files[filename] = direct
            validation = directory / 'validation' / 'validation.json'
            if validation.exists():
                files['validation/validation.json'] = validation
            if not files:
                continue
            if directory != arm_dir and not any(
                    name in files for name in
                    ('failed_attempts.json', 'strategy_stats.json',
                     'budget_ledger.json', 'group_attempts.json',
                     'regroup_attempts.json', 'attempts.json',
                     'failure_taxonomy.json')):
                # a bare checkpoint/snapshot (routes + validation only) is not
                # a separate failure-analysis source; the arm root covers it
                continue
            name = arm
            if directory != arm_dir:
                try:
                    name = '%s/%s' % (arm, directory.relative_to(arm_dir))
                except ValueError:
                    name = '%s/%s' % (arm, directory.name)
            sources.append(dict(arm=arm, label=label, name=name,
                                dir=directory, files=files,
                                status='present'))
    # arms that have not produced artifacts yet
    present_arms = {item['arm'] for item in sources}
    for arm, label in ARM_LABELS.items():
        if arm not in present_arms:
            arm_dir = GP.ARM_DIRS.get(arm)
            sources.append(dict(arm=arm, label=label, name=arm,
                                dir=Path(arm_dir) if arm_dir else None,
                                files={}, status='missing'))
    return sources


# --------------------------------------------------------------------------- #
# extract counters
# --------------------------------------------------------------------------- #
def _exact_canonical(key):
    """Exact taxonomy match of a scalar counter key (no fuzzy matching)."""
    text = str(key or '').strip().lower().replace('-', '_').replace(' ', '_')
    if text in SPEC_CLASSES:
        return text
    for canonical, aliases in ALIASES.items():
        if text in aliases:
            return canonical
    return None


def _iter_reason_counts(node, path=''):
    """Yield ``(json_path, raw_reason, count)`` from every reason histogram.

    * reason histograms live in :data:`REASON_CONTAINER_KEYS` dictionaries;
    * single counters are accepted only with an **exact** alias match and only
      outside metadata containers (``ledger`` / ``config`` / ``budget`` / ...),
      so real ledger counters such as ``rolled_back`` are never mistaken for a
      failure reason;
    * re-groupings of the same attempts (``by_group`` / ``by_layer`` / ...) are
      skipped to avoid double counting.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in GROUPING_CONTAINER_KEYS:
                continue
            if key in METADATA_CONTAINER_KEYS and isinstance(value, (dict,
                                                                     list)):
                continue
            if key in REASON_CONTAINER_KEYS and isinstance(value, dict):
                for reason, count in value.items():
                    if isinstance(count, dict):
                        count = (count.get('count') or count.get('n')
                                 or count.get('total'))
                    number = _to_int(count)
                    if number is not None:
                        yield ('%s/%s' % (path, key), str(reason), number)
                continue
            canonical = _exact_canonical(key)
            if canonical and not isinstance(value, (dict, list)):
                number = _to_int(value)
                if number is not None and number > 0:
                    yield ('%s/%s' % (path, key), key, number)
                    continue
            yield from _iter_reason_counts(value, '%s/%s' % (path, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _iter_reason_counts(item, '%s[%d]' % (path, index))


#: aggregate histograms: one counter per whole arm / stage set
AGG_REASON_KEYS = ('reason_totals', 'by_reason', 'reason_counts',
                   'failure_counts', 'fail_reasons',
                   'failure_reason_totals', 'reason_total')
#: per-round / per-stage histograms (same attempts, split by round)
ROUND_REASON_KEYS = ('reasons', 'failure_reasons', 'abort_reasons')
#: per-operator histograms (same attempts, split by operator)
OPERATOR_REASON_KEYS = ('failures', 'failure_by_operator',
                        'operator_failures')


def _add_reason_mapping(target, mapping):
    """Add one ``{reason: count}`` mapping into ``target``; return ok count."""
    ok = 0
    if not isinstance(mapping, dict):
        return ok
    for reason, count in mapping.items():
        if isinstance(count, dict):
            count = (count.get('count') or count.get('n')
                     or count.get('total'))
        number = _to_int(count)
        if number is None:
            continue
        if str(reason).strip().lower() in OK_REASONS:
            ok += number
            continue
        canonical, _unused = canonical_reason(reason)
        target[canonical] += number
    return ok


def _payload_histogram(payload):
    """De-duplicated failure histogram of one JSON payload.

    The same attempts are often reported three ways: one aggregate histogram
    (``reason_totals`` / ``by_reason``), per-round histograms (``reasons`` in
    each stage) and per-operator histograms (``failures``).  This function
    computes each way separately and then takes the **per-class maximum**, so
    a single attempt is never counted three times while no class is lost.
    """
    sources = OrderedDict((name, Counter())
                          for name in ('aggregate', 'round', 'operator'))
    ok_counts = dict(aggregate=0, round=0, operator=0)

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in GROUPING_CONTAINER_KEYS:
                    continue
                if isinstance(value, dict) and key in AGG_REASON_KEYS:
                    ok_counts['aggregate'] += _add_reason_mapping(
                        sources['aggregate'], value)
                    continue
                if isinstance(value, dict) and key in ROUND_REASON_KEYS:
                    ok_counts['round'] += _add_reason_mapping(
                        sources['round'], value)
                    continue
                if isinstance(value, dict) and key in OPERATOR_REASON_KEYS:
                    ok_counts['operator'] += _add_reason_mapping(
                        sources['operator'], value)
                    continue
                if key in METADATA_CONTAINER_KEYS and isinstance(
                        value, (dict, list)):
                    continue
                canonical = _exact_canonical(key)
                if canonical and not isinstance(value, (dict, list)):
                    number = _to_int(value)
                    if number is not None and number > 0:
                        sources['aggregate'][canonical] += number
                        continue
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    histogram = Counter()
    for counts in sources.values():
        for canonical, count in counts.items():
            histogram[canonical] = max(histogram.get(canonical, 0),
                                       int(count))
    return histogram, max(ok_counts.values())


def _iter_stage_rows(node, path=''):
    counters = ('accepted', 'accepted_transactions', 'accepted_changes',
                'gain', 'total_after', 'candidates_tried', 'tried',
                'neighborhood', 'order')
    if isinstance(node, dict):
        looks_like_stage = any(key in node for key in counters) and any(
            key in node for key in ('label', 'stage', 'name', 'round',
                                    'neighborhood'))
        if looks_like_stage:
            yield path, node
        for key, value in node.items():
            if key in REASON_CONTAINER_KEYS:
                continue
            yield from _iter_stage_rows(value, '%s/%s' % (path, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _iter_stage_rows(item, '%s[%d]' % (path, index))


def _load_attempts(path):
    payload = _read_json(path)
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ('attempts', 'failures', 'items', 'failed_attempts',
                    'records'):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [dict(item, _key=name) for name, item in value.items()
                        if isinstance(item, dict)]
    return []


def _attempt_reason(attempt):
    for key in ('reason', 'failure_reason', 'reason_key', 'status',
                'abort_reason', 'why', 'cause', 'error', 'note'):
        value = attempt.get(key)
        if value not in (None, ''):
            return value
    return 'unclassified'


def _arm_budget(source):
    files = source.get('files') or {}
    ledger = _read_json(files.get('budget_ledger.json'), {}) or {}
    config = _read_json(files.get('config.json'), {}) or {}
    limits = {}
    for container in (config.get('budget'), config.get('limits'),
                      config.get('arm_budget')):
        if isinstance(container, dict):
            limits.update({key: value for key, value in container.items()
                           if isinstance(value, (int, float))})
    for key in ('route_3d_checks', 'd56_candidate_evals', 'wall_seconds'):
        value = config.get(key)
        if isinstance(value, (int, float)):
            limits[key] = value
    used = {}
    for key in ('route_3d_checks', 'd56_candidate_evals', 'transactions',
                'world_builds', 'valid_candidates', 'rejected_3d',
                'accepted_transactions', 'accepted_changes', 'gain',
                'no_candidate', 'rolled_back', 'wall_seconds'):
        if key in ledger:
            used[key] = ledger[key]
    over = []
    for key in ('route_3d_checks', 'd56_candidate_evals'):
        if key in limits and key in used:
            try:
                if float(used[key]) >= float(limits[key]):
                    over.append(key)
            except (TypeError, ValueError):
                continue
    if 'wall_seconds' in limits and 'wall_seconds' in used:
        try:
            if float(used['wall_seconds']) >= float(limits['wall_seconds']):
                over.append('wall_seconds')
        except (TypeError, ValueError):
            pass
    return dict(ledger_present=bool(ledger), limits=limits, used=used,
                over_budget=bool(over), over_budget_dimensions=over,
                extras=ledger.get('extras') or {})


def analyse_source(source):
    if source.get('status') == 'missing':
        result = dict(**source)
        result.update(
            failed_attempts_count=0, failed_attempts_file_count=None,
            attempt_reason_counts={}, attempt_raw_reason_counts={},
            strategy_reason_counts={}, stage_rows=[], reason_counts={},
            budget=dict(ledger_present=False, limits={}, used={},
                        over_budget=False, over_budget_dimensions=[],
                        extras={}))
        return result
    files = source.get('files') or {}
    result = dict(**source)
    attempts = _load_attempts(files['failed_attempts.json']) \
        if 'failed_attempts.json' in files else []
    result['failed_attempts_count'] = len(attempts)
    result['failed_attempts_file_count'] = (
        (_read_json(files['failed_attempts.json'], {}) or {}).get('count')
        if 'failed_attempts.json' in files else None)
    reason_counts = Counter()
    raw_counts = Counter()
    ok_attempts = 0
    for attempt in attempts:
        raw_reason = _attempt_reason(attempt)
        if str(raw_reason).strip().lower() in OK_REASONS:
            ok_attempts += 1
            continue
        canonical, raw = canonical_reason(raw_reason)
        reason_counts[canonical] += 1
        raw_counts['%s -> %s' % (str(raw)[:120], canonical)] += 1
    result['failed_attempts_count'] = len(attempts) - ok_attempts
    result['failed_attempts_rows'] = len(attempts)
    result['ok_attempts'] = ok_attempts
    result['attempt_reason_counts'] = dict(reason_counts)
    result['attempt_raw_reason_counts'] = dict(raw_counts)

    strategy_hist = Counter()
    strategy_ok = 0
    stage_rows = []
    if 'strategy_stats.json' in files:
        payload = _read_json(files['strategy_stats.json'])
        if payload is not None:
            strategy_hist, strategy_ok = _payload_histogram(payload)
            seen = set()
            for path, node in _iter_stage_rows(payload):
                key = json.dumps(node, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                row = dict(arm=source['name'], stage=path or '(root)')
                for field in ('label', 'stage', 'name', 'round',
                              'neighborhood', 'order', 'seconds',
                              'accepted', 'accepted_transactions',
                              'accepted_changes', 'candidates_tried', 'tried',
                              'total_after', 'gain', 'targets',
                              'xy_generated', 'built', 'rejected_3d',
                              'evaluated', 'no_gain', 'budget_stop',
                              'no_candidate', 'rolled_back'):
                    if field in node and node[field] is not None:
                        row[field] = node[field]
                stage_rows.append(row)
    # optional per-group attempts files (G4a/G4b) carry a richer histogram
    # describing the same attempts -> per-class max, never summed twice.
    extra_hist = Counter()
    extra_ok = 0
    for extra_name in ('group_attempts.json', 'regroup_attempts.json',
                       'attempts.json'):
        if extra_name not in files:
            continue
        extra_payload = _read_json(files[extra_name])
        if extra_payload is None:
            continue
        histogram, ok = _payload_histogram(extra_payload)
        for canonical, count in histogram.items():
            extra_hist[canonical] = max(extra_hist.get(canonical, 0),
                                        int(count))
        extra_ok = max(extra_ok, ok)
    # G4b-style explicit failure taxonomy (SPEC section 6 keys with counts)
    taxonomy_counts = Counter()
    taxonomy_candidate = Counter()
    if 'failure_taxonomy.json' in files:
        payload = _read_json(files['failure_taxonomy.json']) or {}
        for key, value in (payload.get('failure_classes') or {}).items():
            canonical, _unused = canonical_reason(key)
            if isinstance(value, dict):
                count = _to_int(value.get('count')) or 0
                candidate_count = _to_int(value.get('candidate_level_count'))
                if _to_int(value.get('probe_count')):
                    taxonomy_candidate[canonical + '_probe'] = int(
                        _to_int(value.get('probe_count')))
            else:
                count = _to_int(value) or 0
                candidate_count = None
            taxonomy_counts[canonical] += int(count)
            if candidate_count is not None:
                taxonomy_candidate[canonical] += int(candidate_count)
    histogram_side = Counter()
    for key in set(strategy_hist) | set(extra_hist) | set(taxonomy_counts):
        histogram_side[key] = max(int(strategy_hist.get(key, 0)),
                                  int(extra_hist.get(key, 0)),
                                  int(taxonomy_counts.get(key, 0)))
    result['strategy_reason_counts'] = dict(histogram_side)
    result['group_attempt_reason_counts'] = dict(extra_hist)
    result['taxonomy_reason_counts'] = dict(taxonomy_counts)
    result['taxonomy_candidate_counts'] = dict(taxonomy_candidate)
    result['stage_rows'] = stage_rows
    result['ok_attempts'] = max(ok_attempts, strategy_ok, extra_ok)
    # The same failure can appear both in failed_attempts.json (per attempt,
    # capped at 2000) and in a reason histogram (strategy_stats / group
    # attempts).  Taking the per-class MAXIMUM of the two sides avoids double
    # counting; the source table below reports both raw totals for transparency.
    merged = {}
    for key in set(reason_counts) | set(histogram_side):
        merged[key] = max(int(reason_counts.get(key, 0)),
                          int(histogram_side.get(key, 0)))
    result['reason_counts'] = merged
    result['attempt_reason_total'] = int(sum(reason_counts.values()))
    result['strategy_reason_total'] = int(sum(histogram_side.values()))
    result['reason_count_method'] = ('max(per-attempt, per-histogram); '
                                     'histograms are per-class max of '
                                     'strategy_stats and group_attempts')
    result['budget'] = _arm_budget(source)
    result['status'] = ('present' if (attempts or strategy_hist
                                      or result['budget']['ledger_present']
                                      or stage_rows
                                      or result['ok_attempts'])
                        else 'present_no_failures')
    return result


# --------------------------------------------------------------------------- #
# analysis + documents
# --------------------------------------------------------------------------- #
def analyse(root=None):
    sources = discover_sources(root)
    arms = [analyse_source(source) for source in sources]
    totals = Counter()
    by_arm = OrderedDict()
    for item in arms:
        for reason, count in (item.get('reason_counts') or {}).items():
            totals[reason] += int(count)
        by_arm[item['name']] = dict(
            arm=item['arm'], name=item['name'], label=item['label'],
            status=item['status'],
            dir=_rel(item['dir']) if item.get('dir') else None,
            files=sorted((item.get('files') or {}).keys()),
            failed_attempts=item.get('failed_attempts_count'),
            failed_attempts_rows=item.get('failed_attempts_rows'),
            ok_attempts=item.get('ok_attempts'),
            attempt_reason_total=item.get('attempt_reason_total'),
            strategy_reason_total=item.get('strategy_reason_total'),
            reason_count_method=item.get('reason_count_method'),
            reason_counts=item.get('reason_counts') or {},
            budget=item.get('budget') or {},
            stage_rows=item.get('stage_rows') or [],
        )
    return dict(
        schema=SCHEMA, generated_at=_now(), root=_rel(root or GP.G4_ROOT),
        spec_classes={key: definition
                      for key, definition in SPEC_CLASSES.items()},
        aliases={key: list(value) for key, value in ALIASES.items()},
        arms=by_arm,
        totals=dict(totals),
        total_failures=sum(totals.values()),
        unclassified_total=int(totals.get('unclassified', 0)),
        claim_level='search_side_only',
        strict_infeasibility_proven=False,
        infeasibility_note=(
            '本分析只记录“在给定算法与预算下未找到候选/未接受”，不声称任何'
            '目标严格无解；未做下界证明或穷举覆盖证明。'),
    )


def _class_zh(key):
    return SPEC_CLASSES.get(key, key)


def write_markdown(payload, path, root=None):
    arms = payload['arms']
    totals = payload['totals']
    present = [item for item in arms.values() if item['status'] != 'missing']
    missing = [item for item in arms.values() if item['status'] == 'missing']
    lines = ['# G4 失败原因分析（SPEC_G4.md 第 6 节 8+ 类）', '',
             '- 生成时间: %s' % payload['generated_at'],
             '- 归档根: `%s`' % payload['root'],
             '- 数据来源: 各臂 `failed_attempts.json` / '
             '`strategy_stats.json` / `budget_ledger.json` / `config.json` '
             '（全部来自真实臂产物，未使用搜索中间候选图）',
             '- 结论口径: **所有失败分类都是“搜索侧未找到/未接受”，不是'
             '“严格证明无解”**；本报告不做下界证明，也不声称任何目标'
             '不可达。', '']
    if missing:
        lines.append('> 状态：以下臂尚无产物（进行中/未完成，非“无失败”）：')
        for item in missing:
            lines.append('> - `%s` — %s' % (item['arm'], item['label']))
        lines.append('')
    lines.append('## 1. 数据源与可用性')
    lines.append('')
    lines.append('| 臂 | 状态 | 失败尝试数 | 尝试原因合计 | strategy 原因合计 '
                 '| 合并口径合计 | ok（非失败） | budget_ledger | 说明 |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    for name, item in arms.items():
        reason_sum = sum(int(value) for value in
                         (item.get('reason_counts') or {}).values())
        ledger = item.get('budget') or {}
        lines.append('| `%s` | %s | %s | %s | %s | %d | %s | %s | %s |'
                     % (name, '已产出' if item['status'] != 'missing'
                        else '未完成',
                        item.get('failed_attempts'),
                        item.get('attempt_reason_total', 0),
                        item.get('strategy_reason_total', 0),
                        reason_sum,
                        item.get('ok_attempts', 0),
                        '有' if ledger.get('ledger_present') else '无',
                        item.get('label', '')))
    lines.append('')
    lines.append('计数口径：同一失败尝试可能同时出现在 `failed_attempts.json`'
                 '（逐条，最多 2000 条）与 `strategy_stats.json` 的原因直方图中；'
                 '本报告对**每个大类取两来源的 max 值**（`max(per-attempt, '
                 'per-strategy-histogram)`），避免重复计数，并保留两列原始合计。'
                 '`ok` 记录表示“尝试未失败”（臂为完整性写入），**不计入失败分类**。')
    lines.append('')
    lines.append('## 2. 失败原因分类（SPEC 第 6 节定义）')
    lines.append('')
    lines.append('| 原因 key | 定义 | 本轮计数 | 性质 |')
    lines.append('|---|---|---|---|')
    for key, definition in SPEC_CLASSES.items():
        count = int(totals.get(key, 0))
        if key == 'unclassified':
            nature = '待归类'
        elif key == 'budget_exhausted':
            nature = '预算界（终止条件，不等于无解）'
        elif key == 'legal_but_no_crossing_improvement':
            nature = '合法但无收益（搜索接受流拒绝）'
        else:
            nature = '搜索侧未找到（不构成无解证明）'
        lines.append('| `%s` | %s | %d | %s |'
                     % (key, definition, count, nature))
    lines.append('')
    lines.append('合计失败计数：**%d**（其中未归类 %d）'
                 % (payload['total_failures'],
                    payload['unclassified_total']))
    lines.append('')
    lines.append('## 3. 分臂 × 原因计数')
    lines.append('')
    columns = [key for key in SPEC_CLASSES if int(totals.get(key, 0))]
    header = ['臂'] + ['`%s`' % key for key in columns] + ['合计']
    lines.append('| ' + ' | '.join(header) + ' |')
    lines.append('|' + '---|' * len(header))
    for name, item in arms.items():
        if item['status'] == 'missing':
            continue
        counts = item.get('reason_counts') or {}
        row = [name] + [str(int(counts.get(key, 0))) for key in columns]
        row.append(str(sum(int(value) for value in counts.values())))
        lines.append('| ' + ' | '.join(row) + ' |')
    if not present:
        lines.append('| _（暂无臂产物，等待各臂结束后重跑本脚本）_ '
                     + ' | ' * (len(header) - 1) + ' |')
    lines.append('')
    lines.append('## 4. “算法找不到解” vs “严格证明无解”')
    lines.append('')
    lines.append('| 判据 | 本轮证据 |')
    lines.append('|---|---|')
    lines.append('| 算法在预算内找不到合法/更优候选 | **是**（上表全部计数）|')
    lines.append('| 严格无解证明（下界 / 穷举覆盖）| **否**：无任何下界证明，'
                 '不声称不可达 |')
    lines.append('| 是否可断言“该目标在更长时间下也无解” | **否**：预算耗尽'
                 '（`budget_exhausted`）只说明本轮预算边界 |')
    lines.append('')
    lines.append('因此任何“达不到目标”的表述必须写成：*在给定共享引擎、'
                 '算法族与预算下未达到*，而不是“无解”。')
    lines.append('')
    lines.append('## 5. 预算耗尽证据（budget_ledger 真实计数）')
    lines.append('')
    lines.append('| 臂 | route_3d_checks | d56_candidate_evals | '
                 'wall_seconds | 预算上限 | 是否触顶 |')
    lines.append('|---|---|---|---|---|---|')
    for name, item in arms.items():
        budget = item.get('budget') or {}
        if not budget.get('ledger_present'):
            continue
        used = budget.get('used') or {}
        limits = budget.get('limits') or {}
        lines.append('| %s | %s | %s | %s | %s | %s |'
                     % (name, used.get('route_3d_checks', '-'),
                        used.get('d56_candidate_evals', '-'),
                        used.get('wall_seconds', '-'),
                        ', '.join('%s=%s' % (key, value)
                                  for key, value in limits.items()) or '-',
                        '是（%s）' % ', '.join(
                            budget.get('over_budget_dimensions') or []) or '否'
                        if budget.get('over_budget') else '否'))
    lines.append('')
    lines.append('## 6. 解读（负结果如实保留）')
    lines.append('')
    if present:
        ranked = sorted(((key, int(value)) for key, value in totals.items()
                         if int(value) > 0), key=lambda item: -item[1])
        if ranked:
            lines.append('按计数排序的失败主因：')
            for key, count in ranked[:8]:
                lines.append('- `%s`（%s）：%d 次' % (key, _class_zh(key), count))
        else:
            lines.append('- 目前各臂产物中的失败原因计数均为 0 或尚未写入，'
                         '需在各臂结束后重跑。')
    else:
        lines.append('- 各臂尚未产出失败产物（进行中/未完成）。本文件是'
                     '分析框架；待各臂结束后会自动重跑得到真实计数。')
    lines.append('')
    lines.append('## 7. 后续需要的数据（若某类计数为 0）')
    lines.append('')
    lines.append('- 臂结束后确认 `failed_attempts.json` 的 `count` 与 '
                 '`strategy_stats.json` 的 `reasons` 均已写入；')
    lines.append('- 若 `strategy_stats.json` 使用自定义 reason key，需在 '
                 '`failure_analysis.py` 的 `ALIASES` 中补充映射（当前未归类'
                 '计数会保留在 `unclassified`，不会丢失数据）。')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def plot_failure_reasons(payload, out_path):
    totals = {key: int(value) for key, value in payload['totals'].items()
              if int(value) > 0}
    if not totals:
        return None
    ordered = sorted(totals.items(), key=lambda item: -item[1])
    labels = [key for key, _count in ordered]
    values = [count for _key, count in ordered]
    display = [SPEC_CLASSES.get(key, key)[:28] for key in labels]
    fig, axes = plt.subplots(1, 2, figsize=(14.6, 6.2),
                             gridspec_kw=dict(width_ratios=[1.25, 1.0]))
    ax = axes[0]
    colors = plt.get_cmap('tab20').colors
    bars = ax.barh(range(len(labels)), values,
                   color=[colors[index % 20] for index in range(len(labels))],
                   edgecolor='#37474f', linewidth=0.4)
    for bar, value in zip(bars, values):
        ax.text(value, bar.get_y() + bar.get_height() / 2.0, ' %d' % value,
                va='center', fontsize=7.4)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7.2)
    ax.invert_yaxis()
    ax.set_xlabel('failure count (real arm artifacts)')
    ax.set_title('failure reasons — all arms (SPEC section 6 taxonomy)')
    ax.grid(axis='x', linewidth=0.3, color='#e0e0e0')
    ax = axes[1]
    arms = [item for item in payload['arms'].values()
            if item['status'] != 'missing'
            and any(int(value) for value in
                    (item.get('reason_counts') or {}).values())]
    if arms:
        arm_names = [item['name'] for item in arms]
        reason_keys = [key for key, _count in ordered]
        bottom = np.zeros(len(arms), dtype=float)
        for index, key in enumerate(reason_keys):
            values_arm = np.asarray(
                [int((item.get('reason_counts') or {}).get(key, 0))
                 for item in arms], dtype=float)
            if not values_arm.any():
                continue
            ax.bar(range(len(arms)), values_arm, bottom=bottom,
                   label=key, color=colors[index % 20], edgecolor='white',
                   linewidth=0.3)
            bottom += values_arm
        ax.set_xticks(range(len(arms)))
        ax.set_xticklabels(arm_names, rotation=25, fontsize=7.4)
        ax.set_ylabel('failure count')
        ax.set_title('failure reasons per arm')
        ax.legend(fontsize=6.6, loc='upper right')
        ax.grid(axis='y', linewidth=0.3, color='#e0e0e0')
    fig.suptitle('G4 failure taxonomy — search-side counts only, '
                 'no infeasibility proof claimed', fontsize=11.0, y=0.985)
    fig.text(0.5, 0.005,
             'source: arm failed_attempts.json / strategy_stats.json / '
             'budget_ledger.json — generated %s'
             % payload['generated_at'], ha='center', fontsize=6.6,
             color='#546e7a')
    fig.subplots_adjust(left=0.19, right=0.99, top=0.91, bottom=0.10,
                        wspace=0.42)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, facecolor='white')
    plt.close(fig)
    if not out_path.exists() or out_path.stat().st_size <= 0:
        return None
    return dict(path=_rel(out_path), bytes=out_path.stat().st_size)


def run(root=None, reports_dir=None, plots_dir=None):
    root = Path(root or GP.G4_ROOT)
    reports_dir = Path(reports_dir or (root / '10_reports'))
    plots_dir = Path(plots_dir or (root / '09_plots' / 'failure_analysis'))
    payload = analyse(root)
    json_path = _write_json(reports_dir / 'failure_analysis.json', payload)
    rows = []
    for name, item in payload['arms'].items():
        counts = item.get('reason_counts') or {}
        row = dict(arm=name, status=item['status'],
                   dir=item.get('dir') or '',
                   failed_attempts=item.get('failed_attempts'),
                   reason_total=sum(int(value) for value in counts.values()))
        for key in SPEC_CLASSES:
            row[key] = int(counts.get(key, 0))
        rows.append(row)
    csv_path = _write_csv(reports_dir / 'failure_analysis.csv', rows)
    md_path = write_markdown(payload, reports_dir / 'failure_analysis.md', root)
    figure = None
    try:
        figure = plot_failure_reasons(payload,
                                      plots_dir / 'failure_reasons.png')
    except Exception as exc:  # noqa: BLE001 - figure is optional
        payload['figure_error'] = repr(exc)
    payload['outputs'] = dict(
        json=_rel(json_path), csv=_rel(csv_path), markdown=_rel(md_path),
        figure=figure['path'] if figure else None)
    _write_json(json_path, payload)
    return payload


def _build_parser():
    parser = argparse.ArgumentParser(
        description='G4 failure analysis (SPEC section 6 taxonomy)')
    parser.add_argument('--root', default=None,
                        help='G4 archive root (default experiments/xyz_joint_g4_1024)')
    parser.add_argument('--reports-dir', default=None)
    parser.add_argument('--plots-dir', default=None)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    payload = run(args.root, args.reports_dir, args.plots_dir)
    print(json.dumps(dict(
        total_failures=payload['total_failures'],
        unclassified=payload['unclassified_total'],
        arms={name: dict(status=item['status'],
                         reason_total=sum(int(value) for value in
                                          (item.get('reason_counts') or {}).values()))
              for name, item in payload['arms'].items()},
        outputs=payload.get('outputs')), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
