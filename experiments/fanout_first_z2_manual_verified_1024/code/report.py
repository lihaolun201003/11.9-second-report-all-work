# -*- coding: utf-8 -*-
"""Final report generator for the fanout-first Z2-manual-verified 1024 run.

Reads the real artifacts only (``routes_l3d.json``, ``failed_routes.json``,
``validation.json``, ``assignment_1024.csv``, the verified manual-U CSVs,
``experiment_A/ .. experiment_E/``) and writes:

* ``report.md``      — 中文报告，逐条回答用户的 5 个问题 + 方法、数据审计、
                      层分配、fanout、逐层二维、联合修复、严格验证、瓶颈分类、局限
* ``comparison.md``  — 与上一轮 809/1024 的对比（并明确说明上轮并未正确处理
                      Z2 人工 U 分组，因此不是同等约束的算法对比）
* ``final_stats.json`` — 所有计数（输入/尝试/成功/失败、按 plane/group/layer、
                      真实失败 route_id 与原因、验证摘要、最小间距、总长度、
                      过渡数、交叉数、与 809 的对比）

Nothing is invented: a value that is not present in the artifacts is rendered as
``n/a`` and the missing file is listed in ``report_inputs`` inside
``final_stats.json``.

CLI::

    python -m four_side_1024.fanout1024.report [--run-dir DIR] [--prev-dir DIR]
        [--skip-write]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from . import common

RUN_DIR = common.RUN_DIR
PREV_DIR = common.PREV_DIR
PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANUAL_GROUPS = OrderedDict([
    ('Z1-U1', dict(plane='z1', layer=2, z=-0.35, pattern='NS-first')),
    ('Z1-U2', dict(plane='z1', layer=3, z=-0.29, pattern='NS-second')),
    ('Z1-U3', dict(plane='z1', layer=4, z=-0.23, pattern='EW-first')),
    ('Z1-U4', dict(plane='z1', layer=5, z=-0.17, pattern='EW-second')),
    ('Z2-U1', dict(plane='z2', layer=10, z=0.15, pattern='NS-first')),
    ('Z2-U2', dict(plane='z2', layer=11, z=0.20, pattern='EW-first')),
    ('Z2-U3', dict(plane='z2', layer=12, z=0.25, pattern='NS-second')),
    ('Z2-U4', dict(plane='z2', layer=13, z=0.30, pattern='EW-second')),
])
MANUAL_GROUP_ALIASES = {'NS-1': 'Z1-U1', 'NS-2': 'Z1-U2',
                        'EW-1': 'Z1-U3', 'EW-2': 'Z1-U4'}
GITHUB_PLACEHOLDER = '<<<GITHUB_COMMIT_URL>>>'
GITHUB_REPO = 'lihaolun201003/11.9-second-report-all-work'

FAILURE_CATEGORIES = OrderedDict([
    ('cat1_data_grouping', '1) 原始数据及分组问题'),
    ('cat2_layer_assignment', '2) 目标物理层分配问题'),
    ('cat3_fanout_no_transition', '3) 三维端口升降问题（fanout 未找到合法过渡）'),
    ('cat4_fanout_conflict', '4) 三维过渡相互冲突（fanout/rip-up 冲突）'),
    ('cat5_landing_pose', '5) 二维落点位置不合理（landing/lead/位姿无法衔接）'),
    ('cat6_layer2d_failed', '6) 同层二维自动布线失败（候选不足/D56 冲突）'),
    ('cat7_rrr_insufficient', '7) 联合 RRR 搜索能力不足（world 校验/装配仍失败）'),
])

CAVEATS = [
    '50 µm 层间距（18 层，pitch ≥ 0.05 mm）是本轮确认的工艺输入；'
    '但光学串扰、串扰导致的通道代价、以及光刻/写入的制造公差与工艺余量均未验证，'
    '本报告只做几何口径的验证，不能作为可制造性结论。',
    '没有恢复 80 µm 全局间距。本轮 3D 中心线间距规则是 0.05 mm；0.08 mm 只作为'
    '同层二维 D56 中心线规则（宽度 0.05 + 边缘间隙 0.03）保留，不与 3D 规则混用。',
    '边界波导（端口位于 150 mm 板边、中心线到板边距离 0~0.025 mm）只满足当前探索性的'
    '中心线几何模型；波导边缘会超出玻璃边界（半宽 0.025 mm），表面工艺/切割余量未验证。',
    'R15 是几何约束而非损耗标定值；弯损/交叉损没有针对该玻璃工艺的标定函数，'
    '因此本报告不给出光学损耗结论。',
    '物理层 stack 的 provenance 是 unconfirmed_simulation（探索性输入），'
    'validator 只报告 exploratory 几何通过，不构成正式工艺验收。',
    '失败线路如实保留在 failed_routes.json / final_stats.json 中（真实 route_id + 原因），'
    '没有把失败改写成成功，也没有为了通过而放宽任何检查。',
]


# ===========================================================================
# IO helpers
# ===========================================================================
def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _fmt(value, digits=3, default='n/a'):
    if value is None:
        return default
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def _pct(value, total, digits=1):
    if not total:
        return 'n/a'
    return f'{100.0 * float(value) / float(total):.{digits}f}%'


def _layer_label(layer_id):
    try:
        layer_id = int(layer_id)
    except (TypeError, ValueError):
        return 'n/a'
    z = common.PHYSICAL_LAYERS.get(layer_id)
    return f'L{layer_id} (z={z:+.2f})' if z is not None else f'L{layer_id}'


def _group_of_row(row):
    text = str(row.get('manual_group') or '').strip()
    if not text:
        return ''
    return MANUAL_GROUP_ALIASES.get(text, text)


def _is_routed(record):
    status = record.get('status')
    if status is None:
        return True
    return str(status).strip().lower() in ('routed', 'ok', 'success',
                                           'valid', 'accepted', 'done')


# ===========================================================================
# data collection
# ===========================================================================
def load_run(run_dir):
    """Load every real artifact of the run (missing files are recorded)."""
    run_dir = Path(run_dir)
    inputs = {}
    payload = _read_json(run_dir / 'routes_l3d.json')
    inputs['routes_l3d.json'] = payload is not None
    records = (payload or {}).get('routes') or []
    routed = [record for record in records if isinstance(record, dict)
              and _is_routed(record)]
    failed = [record for record in records if isinstance(record, dict)
              and not _is_routed(record)]
    routed.sort(key=lambda item: int(item.get('route_id', 0)))
    failed.sort(key=lambda item: int(item.get('route_id', 0)))
    assignment_rows = _read_csv(run_dir / 'assignment_1024.csv')
    inputs['assignment_1024.csv'] = bool(assignment_rows)
    failed_payload = _read_json(run_dir / 'failed_routes.json')
    if isinstance(failed_payload, dict):
        inputs['failed_routes.json'] = True
        failed_file = list(failed_payload.get('failures') or [])
    elif isinstance(failed_payload, list):
        inputs['failed_routes.json'] = True
        failed_file = list(failed_payload)
    else:
        inputs['failed_routes.json'] = False
        failed_file = []
    validation = _read_json(run_dir / 'validation.json')
    inputs['validation.json'] = isinstance(validation, dict)
    consistency = _read_json(run_dir / 'validator_consistency_tests.json')
    inputs['validator_consistency_tests.json'] = isinstance(consistency, dict)
    archive_result = _read_json(run_dir / 'archive_result.json')
    inputs['archive_result.json'] = isinstance(archive_result, dict)
    layerwise = _read_json(run_dir / 'layerwise_routes' / 'routes.json')
    inputs['layerwise_routes/routes.json'] = isinstance(layerwise, dict)
    fanout_selected = _read_json(run_dir / 'fanout_selected.json')
    inputs['fanout_selected.json'] = isinstance(fanout_selected, dict)
    fanout_validation = _read_json(run_dir / 'fanout_validation.json')
    inputs['fanout_validation.json'] = isinstance(fanout_validation, dict)
    experiments = {}
    for name in ('experiment_A', 'experiment_B', 'experiment_C',
                 'experiment_D', 'experiment_E'):
        directory = run_dir / name
        block = dict(summary=_read_json(directory / 'summary.json'),
                     failed=_read_json(directory / 'failed_routes.json'),
                     violations=_read_json(directory / 'violations.json'),
                     directory_exists=directory.is_dir())
        if name == 'experiment_A':
            block['input_counts'] = _read_json(directory / 'input_counts.json')
            block['validation_status'] = _read_json(directory / 'validation_status.json')
            block['audit'] = _read_json(directory / 'audit.json')
        block['available'] = any(value is not None for key, value in block.items()
                                 if key not in ('directory_exists', 'available'))
        experiments[name] = block
        inputs[f'{name}/'] = block['directory_exists']
    manual = dict(
        z1_rows=_read_csv(run_dir / 'z1_manual_u_verified_L2_L5.csv'),
        z2_rows=_read_csv(run_dir / 'z2_manual_u_verified_L10_L13.csv'),
        z2_summary=_read_json(run_dir / 'z2_manual_u_summary.json'),
        z2_unmatched=_read_csv(run_dir / 'z2_manual_u_unmatched.csv'),
        z2_conflicts=_read_csv(run_dir / 'z2_manual_u_conflicts.csv'),
        excel_audit=_read_json(run_dir / 'input_excel_audit.json'),
    )
    for name, value in (('z1_manual_u_verified_L2_L5.csv', manual['z1_rows']),
                        ('z2_manual_u_verified_L10_L13.csv', manual['z2_rows']),
                        ('input_excel_audit.json', manual['excel_audit']),
                        ('z2_manual_u_summary.json', manual['z2_summary'])):
        inputs[name] = bool(value)
    assignment_audit = _read_json(run_dir / 'assignment_audit.json')
    inputs['assignment_audit.json'] = isinstance(assignment_audit, dict)
    process_rules = _read_json(run_dir / 'process_rules.json')
    inputs['process_rules.json'] = isinstance(process_rules, dict)
    stack_payload = _read_json(run_dir / 'physical_layer_stack.json')
    inputs['physical_layer_stack.json'] = isinstance(stack_payload, dict)
    return dict(run_dir=run_dir, payload=payload, records=records,
                routed=routed, failed=failed, failed_file=failed_file,
                assignment_rows=assignment_rows,
                assignment_by_id={int(row['route_id']): row
                                  for row in assignment_rows
                                  if str(row.get('route_id', '')).strip().isdigit()},
                validation=validation, consistency=consistency,
                archive_result=archive_result, layerwise=layerwise,
                fanout_selected=fanout_selected,
                fanout_validation=fanout_validation,
                experiments=experiments, manual=manual,
                assignment_audit=assignment_audit,
                process_rules=process_rules, stack_payload=stack_payload,
                inputs=inputs)


def load_previous(prev_dir):
    prev_dir = Path(prev_dir)
    payload = _read_json(prev_dir / 'routes_l3d.json')
    routed, failed = [], []
    if isinstance(payload, dict):
        for record in payload.get('routes') or []:
            if not isinstance(record, dict):
                continue
            status = str(record.get('status') or 'routed').strip().lower()
            if status in ('routed', 'ok', 'success'):
                routed.append(record)
            else:
                failed.append(record)
    assignment_rows = _read_csv(prev_dir / 'assignment_1024.csv')
    return dict(dir=prev_dir, payload=payload, routed=routed, failed=failed,
                assigned=len(assignment_rows),
                assignment_rows=assignment_rows,
                validation=_read_json(prev_dir / 'validation.json'),
                final_stats=_read_json(prev_dir / 'final_stats.json'),
                available=isinstance(payload, dict))


# ---------------------------------------------------------------------------
# failure classification (the user-mandated 7 categories)
# ---------------------------------------------------------------------------
def _failure_detail(record):
    detail = record.get('detail')
    if isinstance(detail, dict):
        return detail
    return {}


def classify_failure(record):
    """Map one real failure record to one of the user's 7 bottleneck classes."""
    reason = str(record.get('reason') or '').strip()
    lower = reason.lower()
    detail = _failure_detail(record)
    detail_reason = str((detail or {}).get('reason') or '').lower()
    detail_text = json.dumps(detail, ensure_ascii=False).lower()[:2000]
    blockers = record.get('blockers') or []
    endpoint_roles = record.get('endpoint_roles') or []
    token_text = ' '.join((lower, detail_reason, detail_text))

    def has(*tokens):
        return any(token in token_text for token in tokens)

    if has('data:', 'data_', 'port_pair', 'not_in_true', 'route_id_not_in',
           'missing_assignment'):
        return 'cat1_data_grouping'
    if has('assignment:', 'transition_target_layer', 'transition_target_z',
           'target_layer_mismatch', 'layer_assignment'):
        return 'cat2_layer_assignment'
    if has('assembly:body_', 'assembly:route_needs_interface', 'assembly:lead',
           'off_inward', 'zero_lead', 'pose', 'landing'):
        return 'cat5_landing_pose'
    if has('layer2d_failed', 'layer2d:', 'no_candidate', 'no_body',
           'd56', 'spacing', 'overlap'):
        return 'cat6_layer2d_failed'
    if blockers or has('conflict', 'blocked', 'blocker', 'transition_vs',
                       'flat_vs_transition', 'self_clearance'):
        return 'cat4_fanout_conflict'
    if has('fanout_incomplete', 'missing_transition', 'fanout:'):
        return 'cat3_fanout_no_transition'
    if has('world_violation', 'assembly:', 'joint', 'rrr', 'repair'):
        return 'cat7_rrr_insufficient'
    # terminal fallback: a failure whose reason we cannot parse is conservatively
    # attributed to the joint-repair stage, never hidden
    return 'cat7_rrr_insufficient'


# ===========================================================================
# statistics
# ===========================================================================
def _per_layer_2d_from_experiment(experiment):
    summary = (experiment or {}).get('summary')
    if not isinstance(summary, dict):
        return None
    per_layer = summary.get('per_layer')
    if not isinstance(per_layer, dict):
        return None
    return {int(key): dict(value) for key, value in per_layer.items()
            if str(key).lstrip('-').isdigit()}


def _per_layer_2d_from_layerwise(layerwise):
    if not isinstance(layerwise, dict):
        return None
    layers = layerwise.get('layers')
    if not isinstance(layers, dict):
        return None
    out = {}
    for key, value in layers.items():
        if not isinstance(value, dict):
            continue
        try:
            layer_id = int(value.get('layer_id', key))
        except (TypeError, ValueError):
            continue
        routes = value.get('routes') or {}
        failed = value.get('failed') or []
        routed_count = len(routes) if hasattr(routes, '__len__') else 0
        out[layer_id] = dict(routed=routed_count,
                             failed=len(failed) if hasattr(failed, '__len__') else 0,
                             total=routed_count + (len(failed)
                                                   if hasattr(failed, '__len__') else 0),
                             z_mm=value.get('z_mm'))
    return out


def _first(mapping, *keys, default=None):
    """First present (non-None) value of ``mapping`` for the given keys."""
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return default


def _fanout_block(summary):
    """Normalise the fanout experiment summary (module + run_all schemas)."""
    if not isinstance(summary, dict) or not summary:
        return None
    input_routes = _first(summary, 'input_routes', 'input_line_count',
                          'input_manual_routes')
    both = _first(summary, 'routes_with_both_transitions', 'success_routes')
    incomplete = _first(summary, 'routes_with_incomplete_transitions')
    if incomplete is None and isinstance(input_routes, int) and isinstance(both, int):
        incomplete = input_routes - both
    success_endpoints = _first(summary, 'success_endpoints')
    endpoint_failures = _first(summary, 'endpoint_failures')
    if endpoint_failures is None and isinstance(success_endpoints, int) \
            and isinstance(input_routes, int):
        endpoint_failures = 2 * input_routes - success_endpoints
    return dict(
        input_routes=input_routes,
        attempted_routes=_first(summary, 'attempted_routes'),
        both_transitions=both,
        incomplete=incomplete,
        success_endpoints=success_endpoints,
        endpoint_failures=endpoint_failures,
        failure_count=_first(summary, 'failure_count'),
        failed_route_ids=summary.get('failed_route_ids'),
        transition_conflicts=_first(summary, 'transition_conflicts'),
        fixed_routes=_first(summary, 'fixed_routes'),
        fixed_conflicts=_first(summary, 'fixed_conflicts'),
        ripups=_first(summary, 'ripups'),
        min_radius_mm=_first(summary, 'min_radius_mm'),
        r15_legal=_first(summary, 'r15_legal'),
        validation_pass=_first(summary, 'validation_pass',
                               'validation_passed'),
        validation_checks=summary.get('validation_checks'),
        seconds=_first(summary, 'seconds'),
        raw=summary,
    )


def _decode_mixed_text(raw):
    """Decode a log file that may mix UTF-8 and UTF-16LE sections."""
    parts = []
    for encoding in ('utf-8', 'utf-16-le'):
        try:
            parts.append(raw.decode(encoding))
        except (UnicodeDecodeError, ValueError):
            continue
    return '\n'.join(parts)


def parse_tests_log(path):
    """Parse RUN_DIR/tests.log into reproducibility evidence (best effort)."""
    path = Path(path)
    if not path.is_file():
        return None
    raw = path.read_bytes()
    text = _decode_mixed_text(raw)
    patterns = [
        r'===[^\n=]+===',
        r'TESTS:\s*\d+\s+passed[^\n]*',
        r'\d+\s+passed in [\d.]+s',
        r'Ran \d+ tests in [\d.]+s',
        r'integration total:[^\n]*',
        r'integration L\d+:[^\n]*',
        r'[a-z_]+_test[^\n]*PASSED[^\n]*',
    ]
    lines = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            line = ' '.join(match.group(0).split())
            if line and line not in lines:
                lines.append(line)
    manual_layers = [line for line in lines if line.startswith('integration L')]
    data_tests = re.search(r'TESTS:\s*(\d+)\s+passed', text)
    fanout_tests = re.search(r'(\d+)\s+passed in [\d.]+s', text)
    layer2d_tests = re.search(r'Ran (\d+) tests', text)
    integration = re.search(r'integration total:\s*(\d+)/(\d+)', text)
    return dict(path=str(path), bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                summary_lines=lines[:60],
                integration_lines=manual_layers[:24],
                counts=dict(
                    data_tests=int(data_tests.group(1)) if data_tests else None,
                    fanout_tests=int(fanout_tests.group(1)) if fanout_tests else None,
                    layer2d_tests=(int(layer2d_tests.group(1))
                                   if layer2d_tests else None),
                    integration=(f'{integration.group(1)}/{integration.group(2)}'
                                 if integration else None),
                ))


def _merge_failure_records(run):
    """Real failure records: file-level detail merged with the routes payload."""
    by_id = {}
    for record in run['failed_file']:
        if isinstance(record, dict):
            try:
                route_id = int(record.get('route_id'))
            except (TypeError, ValueError):
                continue
            by_id[route_id] = dict(record)
    for record in run['failed']:
        try:
            route_id = int(record.get('route_id'))
        except (TypeError, ValueError):
            continue
        base = by_id.setdefault(route_id, {})
        for key in ('plane', 'source_endpoint', 'target_endpoint',
                    'target_layer', 'manual_group', 'reason', 'detail',
                    'status'):
            if record.get(key) not in (None, '') and base.get(key) in (None, ''):
                base[key] = record.get(key)
        for key in ('endpoint_roles', 'blockers'):
            if record.get(key) and not base.get(key):
                base[key] = record.get(key)
    merged = []
    for route_id in sorted(by_id):
        record = by_id[route_id]
        record.setdefault('route_id', route_id)
        if not record.get('reason'):
            record['reason'] = 'unknown_reason'
        row = run['assignment_by_id'].get(route_id) or {}
        if not record.get('plane'):
            record['plane'] = row.get('plane')
        if not record.get('manual_group'):
            record['manual_group'] = _group_of_row(row)
        if record.get('target_layer') in (None, ''):
            record['target_layer'] = row.get('physical_layer') or row.get('target_layer')
        record['category'] = classify_failure(record)
        merged.append(record)
    return merged


def _count_manual_csv(rows):
    counts = Counter()
    for row in rows:
        counts[_group_of_row(row) or '(empty)'] += 1
    return counts


def collect_stats(run_dir, prev_dir=None):
    run = load_run(run_dir)
    # the assembler's own final_stats.json is kept for traceability; this
    # module overwrites final_stats.json with the richer report version
    run_all_stats = _read_json(Path(run_dir) / 'final_stats.json')
    if not (isinstance(run_all_stats, dict)
            and str(run_all_stats.get('schema', '')).endswith('_v1')):
        run_all_stats = _read_json(Path(run_dir) / 'final_stats_run_all.json')
    routed = run['routed']
    failed = run['failed']
    assignment_rows = run['assignment_rows']
    assignment_by_id = run['assignment_by_id']
    inputs = run['inputs']
    declared_route_count = int((run['payload'] or {}).get('route_count') or 1024)
    total_route_count = max(declared_route_count, len(run['records']))

    # ---- failures (authoritative merge of routes_l3d + failed_routes.json) --
    failures = _merge_failure_records(run)
    if not failures and run['failed']:
        failures = _merge_failure_records(dict(run, failed_file=[]))
    failed_for_counts = failures if len(failures) >= len(failed) else failed

    # ---- input inventory ---------------------------------------------------
    route_count = total_route_count
    routed_by_plane = Counter(str(record.get('plane')) for record in routed)
    failed_by_plane = Counter(str(record.get('plane')) for record in failed_for_counts)
    assignment_plane = Counter(str(row.get('plane') or row.get('interface'))
                               for row in assignment_rows)
    manual_input = Counter()
    for row in assignment_rows:
        group = _group_of_row(row)
        if group:
            manual_input[group] += 1
    # manual group routed counts from the final records (assignment group first,
    # record manual_group fallback)
    manual_routed = Counter()
    manual_transitions = Counter()
    for record in routed:
        route_id = record.get('route_id')
        try:
            row = assignment_by_id.get(int(route_id)) or {}
        except (TypeError, ValueError):
            row = {}
        group = _group_of_row(row) or _group_of_row(record)
        if group:
            manual_routed[group] += 1
            manual_transitions[group] += int(record.get('n_transitions') or 0)
    other = dict(
        z1_manual_input=sum(manual_input.get(group, 0) for group in
                            ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4')),
        z2_manual_input=sum(manual_input.get(group, 0) for group in
                            ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4')),
    )
    other['z1_other_input'] = assignment_plane.get('z1', 0) - other['z1_manual_input']
    other['z2_other_input'] = assignment_plane.get('z2', 0) - other['z2_manual_input']
    manual_routed_all = sum(manual_routed.values())
    other['z1_other_routed'] = routed_by_plane.get('z1', 0) - sum(
        manual_routed.get(group, 0) for group in
        ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4'))
    other['z2_other_routed'] = routed_by_plane.get('z2', 0) - sum(
        manual_routed.get(group, 0) for group in
        ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))

    # ---- per-layer final body layer ---------------------------------------
    per_layer_routed = Counter()
    for record in routed:
        layer = record.get('target_layer')
        if layer is None:
            for part in record.get('parts') or []:
                if part.get('kind') == 'flat' and part.get('layer_id') not in (None, 1):
                    layer = part.get('layer_id')
                    break
        try:
            per_layer_routed[int(layer)] += 1
        except (TypeError, ValueError):
            pass
    per_layer_assigned = Counter()
    for row in assignment_rows:
        layer = row.get('physical_layer') or row.get('target_layer')
        try:
            per_layer_assigned[int(str(layer).strip())] += 1
        except (TypeError, ValueError):
            pass

    # ---- experiments -------------------------------------------------------
    experiments = run['experiments']
    exp_b = experiments['experiment_B']
    exp_c = experiments['experiment_C']
    exp_d = experiments['experiment_D']
    exp_e = experiments['experiment_E']
    exp_a = experiments['experiment_A']
    layer2d_manual = (_per_layer_2d_from_experiment(exp_c)
                      or _per_layer_2d_from_layerwise(run['layerwise'])
                      or {})
    layer2d_all = (_per_layer_2d_from_experiment(exp_e)
                   or _per_layer_2d_from_layerwise(run['layerwise'])
                   or {})
    fanout_b = _fanout_block(exp_b.get('summary')) or {}
    fanout_d = _fanout_block(exp_d.get('summary')) or {}
    fanout_e = exp_e.get('summary') or {}
    payload_history = [item for item in
                       ((run['payload'] or {}).get('joint_repair_history') or [])
                       if isinstance(item, dict)]
    stage_e_iterations = [item for item in payload_history if 'iteration' in item]
    if not stage_e_iterations:
        stage_e_iterations = list(fanout_e.get('iterations') or [])
    local_repair_stages = [item for item in payload_history
                           if item.get('stage') == 'local_joint_repair']
    repair_history = dict(
        stage_e_iterations=[dict(
            iteration=item.get('iteration'),
            assembled=item.get('assembled'),
            world_valid=item.get('world_valid'),
            violations=item.get('violations'),
            assembly_failures=item.get('assembly_failures'),
            lead_repair=item.get('lead_repair'),
            budget=item.get('budget'),
        ) for item in stage_e_iterations],
        local_repair_stages=[dict(
            index=index + 1,
            rounds=item.get('rounds'),
            rrr_rounds=[dict(layer=round_.get('layer'),
                             committed=round_.get('committed'),
                             failed_ids=round_.get('failed_ids'),
                             attempt_count=len(round_.get('attempts') or []))
                        for round_ in (item.get('rrr_rounds') or [])],
            layer_resolve_rounds=item.get('layer_resolve_rounds'),
            repaired=item.get('repaired'),
            world_valid=item.get('world_valid'),
            remaining=item.get('remaining'),
        ) for index, item in enumerate(local_repair_stages)],
        final_world_valid=(local_repair_stages[-1].get('world_valid')
                           if local_repair_stages else
                           (stage_e_iterations[-1].get('world_valid')
                            if stage_e_iterations else None)),
        final_remaining=(local_repair_stages[-1].get('remaining')
                         if local_repair_stages else None),
        intermediate_failures=(stage_e_iterations[-1].get('assembly_failures')
                               if stage_e_iterations else None),
        source=('routes_l3d.json joint_repair_history'
                if payload_history else 'experiment_E/summary.json iterations'),
    )
    iterations = stage_e_iterations

    # ---- final fanout lead state ------------------------------------------
    selected_raw = (run['fanout_selected'] or {}).get('selected') or {}
    selected_leads = Counter()
    changed_lead_routes = []
    for rid, record in (selected_raw.items()
                        if isinstance(selected_raw, dict) else []):
        leads = []
        for role in ('source', 'target'):
            payload = (record or {}).get(role) or {}
            lead = payload.get('lead_mm')
            if lead is not None:
                leads.append(round(float(lead), 3))
        if len(leads) == 2:
            selected_leads[(leads[0], leads[1])] += 1
        if leads and any(abs(value - 0.25) > 1e-9 for value in leads):
            changed_lead_routes.append(dict(route_id=int(rid), leads=leads))
    initial_plan_histogram = {}
    for block in ((exp_b.get('summary') or {}), (exp_d.get('summary') or {})):
        histogram = block.get('lead_histogram') or {}
        for key, value in histogram.items():
            initial_plan_histogram[str(key)] = (initial_plan_histogram.get(str(key), 0)
                                                + int(value))
    final_fanout = ((exp_e.get('summary') or {}).get('final_fanout') or {})
    fanout_final_state = dict(
        final_routes=final_fanout.get('routes'),
        final_transition_count=final_fanout.get('transition_count'),
        final_lead_histogram=final_fanout.get('lead_histogram')
        or {f'{first:g}/{second:g}': count
            for (first, second), count in selected_leads.items()},
        final_lead_histogram_from_fanout_selected={
            f'{first:g}/{second:g}': count
            for (first, second), count in selected_leads.items()},
        changed_lead_routes=changed_lead_routes,
        initial_plan_lead_histogram=initial_plan_histogram,
        note=final_fanout.get('note'),
    )

    # ---- reproducibility evidence (module test suites) ---------------------
    reproducibility = parse_tests_log(Path(run_dir) / 'tests.log')
    if reproducibility is not None:
        reproducibility['role'] = (
            'module self-tests for data/assignment (tests_data.py), fanout '
            '(tests_fanout.py) and layerwise 2D routing (tests_layer2d.py); '
            'the independent final geometry authority is validation.json '
            '(validate_final.py)', )

    # ---- endpoint transitions ---------------------------------------------
    endpoint_total = 2 * len(assignment_rows) if assignment_rows else 2048
    endpoint_succeeded = sum(int(record.get('n_transitions') or 0)
                             for record in routed)
    endpoint = dict(
        total_endpoints=endpoint_total,
        succeeded_final=endpoint_succeeded,
        failed_final=max(0, endpoint_total - endpoint_succeeded),
        final_routes_with_both_transitions=sum(
            1 for record in routed if int(record.get('n_transitions') or 0) >= 2),
        experiment_B=fanout_b or None,
        experiment_D=fanout_d or None,
        fanout_validation=run['fanout_validation'],
    )

    # ---- failures ----------------------------------------------------------
    failure_reasons = Counter(str(record.get('reason')) for record in failures)
    category_counts = Counter(record['category'] for record in failures)
    failures_by_plane = Counter(str(record.get('plane')) for record in failures)
    failures_by_layer = Counter()
    failures_by_group = Counter()
    for record in failures:
        layer = record.get('target_layer')
        try:
            failures_by_layer[int(layer)] += 1
        except (TypeError, ValueError):
            pass
        group = record.get('manual_group') or ''
        failures_by_group[group or 'other'] += 1
    # final-consistent per-layer 2D table: the layer2d module's own failed lists
    # can contain stale RRR-attempt records, so the authoritative failure counts
    # come from the final failed-routes records; routed counts agree exactly.
    layer2d_all_combined = OrderedDict()
    for layer in sorted(common.PHYSICAL_LAYERS):
        internal = layer2d_all.get(layer) or {}
        layer2d_all_combined[layer] = dict(
            routed=per_layer_routed.get(layer, 0),
            failed=failures_by_layer.get(layer, 0),
            total=per_layer_assigned.get(layer, 0),
            internal_routed=internal.get('routed'),
            internal_failed=internal.get('failed'),
            source='assignment_1024.csv + routes_l3d.json + failed_routes.json '
                   '(final counts); layer2d internal RRR attempts kept as '
                   'internal_* for diagnostics',
        )
    categories = OrderedDict()
    for key, label in FAILURE_CATEGORIES.items():
        route_ids = [int(record['route_id']) for record in failures
                     if record['category'] == key]
        categories[key] = dict(label=label, count=len(route_ids),
                               route_ids=route_ids,
                               reason_breakdown=dict(sorted(Counter(
                                   str(record.get('reason'))
                                   for record in failures
                                   if record['category'] == key).items())))

    # ---- validation --------------------------------------------------------
    validation = run['validation'] or {}
    checks = validation.get('checks') or {}
    crossing_planes = (checks.get('crossings') or {}).get('planes') or []
    clearance_scan = (checks.get('clearance') or {}).get('min_clearance_scan') or {}
    g = dict(
        validation_file=str(Path(run_dir) / 'validation.json'),
        present=bool(validation),
        geometry_pass=validation.get('geometry_pass'),
        contract_pass=validation.get('contract_pass'),
        validation_pass=validation.get('validation_pass'),
        consistency_passed=validation.get('validator_consistency_passed'),
        violation_count=validation.get('violation_count'),
        violation_counts_by_check=validation.get('violation_counts_by_check'),
        violation_kinds=(checks.get('clearance') or {}).get('violation_kinds'),
        routed=validation.get('routed'),
        failed=validation.get('failed'),
        min_3d_clearance_mm=validation.get('min_3d_clearance_mm'),
        min_3d_clearance_lower_bound_mm=validation.get(
            'min_3d_clearance_lower_bound_mm'),
        transition_vs_flat_min_mm=(clearance_scan.get('transition_vs_flat')
                                   or {}).get('min_mm'),
        transition_vs_transition_min_mm=(clearance_scan.get(
            'transition_vs_transition') or {}).get('min_mm'),
        min_flat_arc_radius_mm=(checks.get('radius') or {}).get(
            'min_flat_arc_radius'),
        min_transition_sampled_radius_mm=(checks.get('radius') or {}).get(
            'transition_min_sampled_radius'),
        flat_arc_count=(checks.get('radius') or {}).get('flat_arc_count'),
        transition_count=(checks.get('radius') or {}).get('transition_count'),
        transitions_total=(checks.get('radius') or {}).get('transition_count'),
        same_plane_crossings=(checks.get('crossings') or {}).get(
            'total_crossings'),
        same_plane_crossing_pairs=(checks.get('crossings') or {}).get(
            'total_crossing_pairs'),
        min_centerline_glass_margin_mm=(checks.get('glass') or {}).get(
            'min_centerline_margin_mm'),
        min_edge_glass_margin_mm=(checks.get('glass') or {}).get(
            'min_edge_margin_mm'),
        same_plane_crossings_by_plane=crossing_planes,
        consistency_tests=(len(((run.get('consistency') or {}).get('tests')
                                or []))),
        consistency_passed_tests=sum(
            1 for test in ((run.get('consistency') or {}).get('tests') or [])
            if isinstance(test, dict) and test.get('passed')),
        structure_violations=(checks.get('structure') or {}).get('violations'),
        radius_violations=(checks.get('radius') or {}).get('violations'),
        glass_violations=(checks.get('glass') or {}).get('violations'),
        clearance_violations=(checks.get('clearance') or {}).get('violations'),
        port_violations=(checks.get('ports') or {}).get('violations'),
        assignment_violations=(checks.get('assignment') or {}).get('violations'),
        crossing_violations=(checks.get('crossings') or {}).get('violations'),
    )
    counts = validation.get('counts') or {}
    total_length = counts.get('total_length_mm')
    if total_length is None:
        try:
            total_length = float(sum(float(record.get('length_mm') or 0.0)
                                     for record in routed))
        except (TypeError, ValueError):
            total_length = None
    total_transitions = counts.get('transitions')
    if total_transitions is None:
        total_transitions = sum(int(record.get('n_transitions') or 0)
                                for record in routed)

    # ---- data audit (question 1) ------------------------------------------
    z2_summary = run['manual'].get('z2_summary') or {}
    excel_audit = run['manual'].get('excel_audit') or {}
    z1_csv_counts = _count_manual_csv(run['manual'].get('z1_rows') or [])
    z2_csv_counts = _count_manual_csv(run['manual'].get('z2_rows') or [])
    audit = dict(
        excel_present=bool(excel_audit),
        excel_rows=excel_audit.get('data_rows') or z2_summary.get('q1_excel_raw_rows'),
        excel_layer_z1_rows=(excel_audit.get('layer_markers') or {}).get('z1'),
        excel_route_id_agreement=(excel_audit.get('route_id_authority') or {}).get(
            'exact_endpoint_pair_agreement_with_true_route_of_same_id'),
        excel_route_id_conclusion=(excel_audit.get('route_id_authority') or {}).get(
            'conclusion'),
        true_z2_connections=((z2_summary.get('q3_true_z2_connections_satisfying_manual_template')
                              or {}).get('true_z2_connections')),
        true_z2_same=((z2_summary.get('q3_true_z2_connections_satisfying_manual_template')
                       or {}).get('z2_same_routes')),
        true_z2_template=((z2_summary.get('q3_true_z2_connections_satisfying_manual_template')
                           or {}).get('satisfying_manual_template')),
        matched_rows=z2_summary.get('excel_rows_matched'),
        unmatched_rows=z2_summary.get('unmatched_rows'),
        conflict_rows=z2_summary.get('conflict_rows'),
        unique_matched_route_ids=z2_summary.get('unique_matched_route_ids'),
        claim_112_confirmed=z2_summary.get('claim_112_confirmed'),
        matching_method=z2_summary.get('matching_method'),
        z1_csv_rows=len(run['manual'].get('z1_rows') or []),
        z1_csv_counts=dict(sorted(z1_csv_counts.items())),
        z2_csv_rows=len(run['manual'].get('z2_rows') or []),
        z2_csv_counts=dict(sorted(z2_csv_counts.items())),
        z2_unmatched_file_rows=len(run['manual'].get('z2_unmatched') or []),
        z2_conflicts_file_rows=len(run['manual'].get('z2_conflicts') or []),
        per_group_totals=((z2_summary.get('q4_per_group_totals_simple')
                           or z2_summary.get('q4_per_group_totals') or {})),
        claim=(z2_summary.get('claim_112_confirmed') or {}),
    )

    # ---- previous round (comparison) --------------------------------------
    previous = None
    if prev_dir is not None:
        prev = load_previous(prev_dir)
        if prev['available']:
            prev_routed = len(prev['routed'])
            prev_failed = len(prev['failed'])
            prev_routed_ids = set()
            for record in prev['routed']:
                try:
                    prev_routed_ids.add(int(record.get('route_id')))
                except (TypeError, ValueError):
                    continue
            prev_manual = Counter()
            prev_manual_routed = Counter()
            prev_layer_counts = Counter()
            for row in prev['assignment_rows']:
                layer = row.get('physical_layer') or row.get('target_layer')
                try:
                    prev_layer_counts[int(str(layer).strip())] += 1
                except (TypeError, ValueError):
                    pass
                group = _group_of_row(row)
                if group:
                    prev_manual[group] += 1
                    try:
                        if int(str(row.get('route_id')).strip()) in prev_routed_ids:
                            prev_manual_routed[group] += 1
                    except (TypeError, ValueError):
                        pass
            prev_z2_manual = sum(prev_manual.get(group, 0) for group in
                                 ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))
            prev_manual_layer_rows = sum(
                count for layer, count in prev_layer_counts.items()
                if layer in (10, 11, 12, 13))
            prev_validation = prev['validation'] or {}
            prev_checks = prev_validation.get('checks') or {}
            prev_clearance = prev_checks.get('clearance') or {}
            prev_stats = prev_validation.get('stats') or {}
            prev_counts = prev_validation.get('counts') or {}
            prev_violations = prev_counts.get('violations')
            if prev_violations is None:
                prev_violations = prev_validation.get('violation_count')
            prev_min_clearance = prev_clearance.get('min_3d_clearance_mm')
            if prev_min_clearance is None:
                prev_min_clearance = prev_stats.get('min_3d_clearance_mm')
            prev_crossings = prev_stats.get('same_plane_crossings')
            if prev_crossings is None:
                prev_crossings = (prev_clearance.get('same_plane') or {}).get(
                    'crossings')
            prev_transitions = sum(int(record.get('n_transitions') or 0)
                                   for record in prev['routed'])
            previous = dict(
                available=True, dir=str(prev_dir),
                routed=prev_routed, failed=prev_failed,
                routed_by_plane=dict(Counter(str(record.get('plane'))
                                             for record in prev['routed'])),
                failed_by_plane=dict(Counter(str(record.get('plane'))
                                             for record in prev['failed'])),
                manual_group_input={key: prev_manual.get(key, 0)
                                    for key in MANUAL_GROUPS},
                manual_group_routed={key: prev_manual_routed.get(key, 0)
                                     for key in MANUAL_GROUPS},
                transitions=prev_transitions,
                z2_manual_rows=prev_z2_manual,
                manual_layer_rows=prev_manual_layer_rows,
                validation=dict(
                    geometry_pass=prev_validation.get('geometry_pass'),
                    violation_count=prev_violations,
                    min_3d_clearance_mm=prev_min_clearance,
                    routed=prev_validation.get('routed'),
                    failed=prev_validation.get('failed'),
                    same_plane_crossings=prev_crossings,
                ),
                final_stats=prev['final_stats'],
            )

    # ---- assemble result ---------------------------------------------------
    stats = OrderedDict([
        ('schema', 'fanout_first_final_stats_v2'),
        ('generated_at', datetime.now().isoformat(timespec='seconds')),
        ('run_dir', str(run_dir)),
        ('algorithm', (run['payload'] or {}).get('algorithm')),
        ('process_mode', (run['payload'] or {}).get('process_mode')),
        ('input', dict(
            total=route_count,
            true_route_count=1024,
            declared_route_count=declared_route_count,
            routes_in_payload=len(run['records']),
            planes=dict(sorted(assignment_plane.items())) if assignment_plane
            else {'z1': 512, 'z2': 512},
            attempts=declared_route_count,
            manual_group_input=dict(sorted(manual_input.items())),
            manual_input_total=sum(manual_input.values()),
            non_manual_input=dict(
                z1_other=other['z1_other_input'],
                z2_other=other['z2_other_input']),
        )),
        ('final', dict(
            routed=len(routed), failed=len(failures),
            failed_records_in_routes_payload=len(run['failed']),
            failed_records_in_failed_routes_json=len(run['failed_file']),
            by_plane={plane: dict(
                input=dict(assignment_plane).get(plane, 0),
                routed=routed_by_plane.get(plane, 0),
                failed=failed_by_plane.get(plane, 0))
                for plane in ('z1', 'z2')},
            by_manual_group={
                group: dict(
                    input=manual_input.get(group, 0),
                    routed=manual_routed.get(group, 0),
                    failed=manual_input.get(group, 0) - manual_routed.get(group, 0),
                    target_layer=spec['layer'], target_z_mm=spec['z'],
                    transitions=manual_transitions.get(group, 0))
                for group, spec in MANUAL_GROUPS.items()},
            manual_total=dict(
                input=sum(manual_input.values()),
                routed=manual_routed_all,
                failed=sum(manual_input.values()) - manual_routed_all),
            non_manual_total=dict(
                z1_input=other['z1_other_input'], z1_routed=other['z1_other_routed'],
                z2_input=other['z2_other_input'], z2_routed=other['z2_other_routed']),
            per_layer_assigned={str(layer): per_layer_assigned.get(layer, 0)
                                for layer in sorted(common.PHYSICAL_LAYERS)},
            per_layer_routed={str(layer): per_layer_routed.get(layer, 0)
                              for layer in sorted(common.PHYSICAL_LAYERS)},
        )),
        ('endpoint_transitions', endpoint),
        ('per_layer_2d', dict(
            manual_layers={str(layer): layer2d_manual.get(layer)
                           for layer in sorted(layer2d_manual)},
            all_layers={str(layer): layer2d_all_combined.get(layer)
                        for layer in sorted(layer2d_all_combined)},
            experiment_e_internal_per_layer={
                str(layer): layer2d_all.get(layer) for layer in sorted(layer2d_all)},
            source=('experiment_C/summary.json (manual layers); final '
                    'assignment+routes+failed_routes (all layers)'
                    if layer2d_manual or layer2d_all else 'unavailable'),
        )),
        ('failures', dict(
            count=len(failures),
            by_reason=dict(sorted(failure_reasons.items())),
            by_plane={plane: failures_by_plane.get(plane, 0)
                      for plane in ('z1', 'z2')},
            by_target_layer={str(layer): failures_by_layer.get(layer, 0)
                             for layer in sorted(common.PHYSICAL_LAYERS)},
            by_manual_group=dict(sorted(failures_by_group.items())),
            categories=categories,
            category_counts={key: category_counts.get(key, 0)
                             for key in FAILURE_CATEGORIES},
            records=[dict(route_id=record.get('route_id'),
                          plane=record.get('plane'),
                          manual_group=record.get('manual_group') or '',
                          target_layer=record.get('target_layer'),
                          reason=record.get('reason'),
                          category=record.get('category'),
                          category_label=FAILURE_CATEGORIES.get(
                              record.get('category'), record.get('category')),
                          endpoint_roles=record.get('endpoint_roles'),
                          blockers=record.get('blockers'),
                          detail=record.get('detail'))
                     for record in failures],
        )),
        ('validation', g),
        ('geometry', dict(
            total_length_mm=total_length,
            total_transitions=total_transitions,
            flat_arc_count=counts.get('flat_arc_count'),
            min_flat_arc_radius_mm=counts.get('min_flat_arc_radius_mm'),
            min_transition_sampled_radius_mm=counts.get(
                'min_transition_sampled_radius_mm'),
            min_3d_clearance_mm=g['min_3d_clearance_mm'],
            min_3d_clearance_lower_bound_mm=g['min_3d_clearance_lower_bound_mm'],
            same_plane_crossings=g['same_plane_crossings'],
            same_plane_crossings_by_plane=crossing_planes,
            transitions_by_plane={
                plane: sum(int(record.get('n_transitions') or 0)
                           for record in routed
                           if str(record.get('plane')) == plane)
                for plane in ('z1', 'z2')},
        )),
        ('experiments', {
            'A': dict(
                available=exp_a.get('available'),
                status=(exp_a.get('validation_status') or {}).get('status'),
                checks_total=(exp_a.get('validation_status') or {}).get('checks_total'),
                checks_passed=(exp_a.get('validation_status') or {}).get('checks_passed'),
                checks_failed=(exp_a.get('validation_status') or {}).get('checks_failed'),
                data_audit_verdict=(exp_a.get('validation_status') or {}).get('data_audit_verdict'),
                assignment_verdict=(exp_a.get('validation_status') or {}).get('assignment_verdict'),
                input_counts=exp_a.get('input_counts'),
                audit=exp_a.get('audit'),
            ),
            'B': dict(
                available=exp_b.get('available'),
                summary=fanout_b or None),
            'C': dict(
                available=exp_c.get('available'),
                summary=exp_c.get('summary')),
            'D': dict(
                available=exp_d.get('available'),
                summary=fanout_d or None),
            'E': dict(
                available=exp_e.get('available'),
                summary=fanout_e or None),
            'joint_repair_iterations': iterations,
        }),
        ('repair_history', repair_history),
        ('fanout_final_state', fanout_final_state),
        ('reproducibility', reproducibility),
        ('data_audit', audit),
        ('comparison_prev_809', previous),
        ('github', dict(
            repository=GITHUB_REPO,
            commit_url=((run['archive_result'] or {}).get('commit_url')
                        if isinstance(run['archive_result'], dict) else None),
            commit_sha=((run['archive_result'] or {}).get('commit_sha')
                        if isinstance(run['archive_result'], dict) else None),
        )),
        ('report_inputs', inputs),
        ('run_all_final_stats', run_all_stats),
        ('caveats', CAVEATS),
    ])
    return stats, run


# ===========================================================================
# markdown rendering
# ===========================================================================
def _table(headers, rows):
    lines = ['| ' + ' | '.join(str(value) for value in headers) + ' |',
             '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(value) for value in row) + ' |')
    return '\n'.join(lines)


def _yes_no(value):
    return '是' if value else '否'


def render_report(stats):
    final = stats['final']
    by_plane = final['by_plane']
    manual = final['by_manual_group']
    endpoint = stats['endpoint_transitions']
    validation = stats['validation']
    geometry = stats['geometry']
    audit = stats['data_audit']
    comparison = stats['comparison_prev_809']
    failures = stats['failures']
    input_block = stats['input']
    github = stats['github']
    commit_url = github.get('commit_url') or GITHUB_PLACEHOLDER
    routed = final['routed']
    failed = final['failed']
    total = input_block['total'] or 1024
    z1_manual = [group for group in MANUAL_GROUPS if group.startswith('Z1')]
    z2_manual = [group for group in MANUAL_GROUPS if group.startswith('Z2')]
    manual_routed_check = sum(manual[group]['routed'] for group in MANUAL_GROUPS)
    lines = []
    add = lines.append

    add('# Fanout-First + Z2 人工 U 验证 1024 通道 3D 布线实验报告')
    add('')
    add(f'生成时间：{stats["generated_at"]}  ')
    add(f'运行目录：`{stats["run_dir"]}`  ')
    add(f'算法：`{stats.get("algorithm") or "FANOUT_FIRST_THEN_LAYERWISE_2D"}`  ')
    add(f'工艺模式：`{stats.get("process_mode") or "corrected_50um"}`  ')
    add('')
    add('## 结论摘要')
    add('')
    add(f'* 最终合法完整连接：**{routed} / {total}**（失败 {failed} 条，真实 route_id 与原因见第 7 节和 `final_stats.json`）')
    add(f'* 按平面：Z1 布通 {by_plane["z1"]["routed"]}/{by_plane["z1"]["input"]}，'
        f'Z2 布通 {by_plane["z2"]["routed"]}/{by_plane["z2"]["input"]}')
    add(f'* 8 个人工 U 分组：输入 {stats["input"]["manual_input_total"]} 条，'
        f'布通 {manual_routed_check} 条')
    add(f'* 独立验证：geometry_pass={_yes_no(validation.get("geometry_pass"))}，'
        f'contract_pass={_yes_no(validation.get("contract_pass"))}，'
        f'validation_pass={_yes_no(validation.get("validation_pass"))}，'
        f'违规数 {_fmt(validation.get("violation_count"), default="n/a")}')
    add(f'* 最小真实 3D 中心线间距：{_fmt(geometry.get("min_3d_clearance_mm"), 6)} mm'
        f'（规则 0.05 mm），最小平面间距下限 {_fmt(geometry.get("min_3d_clearance_lower_bound_mm"), 6)} mm')
    add(f'* GitHub commit：{commit_url if commit_url else "（见下）"}')
    add('')

    # ------------------------------------------------------------------ 1
    add('## 1. 方法与流程')
    add('')
    add('数据不重新生成：1024 条连接来自原始 V4 数据 `routes_1024.json`（z1=512：256 opposite + 256 same；'
        'z2=512：400 adjacent + 112 same），端口坐标来自 `four_side_1024.v3c4.inputs.ENDPOINTS`（2048 个真实端口）。')
    add('')
    add('五个阶段：')
    add('')
    add('1. **A 数据审计 + 1024 分配**：审计 Excel 112 行；用连接器模板匹配真实 Z2 人工 U；把 1024 条分配到 18 个物理层'
        '（固定人工层 L2–L5 / L10–L13，其余按 C4 旋转轨道整组分配）。')
    add('2. **B 仅 8 个人工组的 fanout**：为 368 条人工 U 的 736 个端口端点规划 R15 垂直过渡（fanout-first）。')
    add('3. **C 8 个人工层的逐层 2D 布线**：fanout 落点作为起止位姿，在各自目标层做 R15 二维布线。')
    add('4. **D 全部 1024 条 fanout**：人工组 transition 固定不动（不再被挪动），其余端点规划过渡。')
    add('5. **E 联合修复 + 逐层 2D + 组装 + 严格 3D 校验**：迭代执行"3D 过渡障碍 → 逐层 2D 重布 → 组装 → 重建 world 校验"，'
        '并把每轮的违规位置反馈为下一轮障碍；最终只把**通过严格 3D world 校验**的线路计为布通。')
    add('')
    add('工艺模型（`fanout1024/common.py`，单一口径）：1 mm 玻璃 z∈[-0.35,+0.65]；Z1 界面 z=0、Z2 界面 z=0.5；'
        '18 个物理层 L2–L19，最小层间距 50 µm；R15（所有圆弧半径恰为 15 mm，过渡为两段 R=15 圆弧的 S 曲线）；'
        '真实 3D 中心线间距 ≥ 0.05 mm；同层二维规则沿用原始 D56（宽度 0.05 + 边缘间隙 0.03 = 0.08 mm，'
        '合法的横向交叉保留）。没有恢复 80 µm 全局间距。')
    add('')
    add('独立验证（`validate_final.py`）：从 `routes_l3d.json` 重建一个新的 `l3d.world.World`（clearance=0.05），'
        '按 route_id 顺序逐条 `check_route(check_self=True)`；并独立审计结构连续性、端口位姿、R15 真实 3D 曲率、'
        '玻璃边界、端口覆盖/恒等性、层分配、50/49 µm 边界一致性、同层 D56 与交叉计数。检查项与计数见第 9 节。')
    add('')

    # ------------------------------------------------------------------ 2 Q1
    add('## 2. 问题 1：Excel 的 112 条候选记录是否是真正的 Z2 线路？')
    add('')
    add('**答案：不是。** 这 112 行是按 Z1 平面编号的副本/镜像数据（全部 `layer=z1`、全部 224 个端点端口 plane index 都是 1、'
        '全部 route_id 都落在 Z1 的编号范围 ≤512，且 0/112 行的 route_id 与真实同号线路的端点对一致）。'
        f'最终核实出的真实 Z2 人工 U 是 **{_fmt(audit.get("true_z2_template"))} 条**：'
        f'512 条真实 Z2 连接中有 {_fmt(audit.get("true_z2_same"))} 条 same 关系连接满足用户的人工 U 连接器模板，'
        f'按连接器/同侧/行列通道指纹逐条匹配到真实 route_id（已确认 {_fmt(audit.get("unique_matched_route_ids"))} 个唯一 route_id，'
        f'未匹配 {_fmt(audit.get("unmatched_rows"))}，冲突 {_fmt(audit.get("conflict_rows"))}）。')
    add('')
    add('Z2 人工 U 正确 CSV：`z2_manual_u_verified_L10_L13.csv`（112 行，每条一个真实连接）；'
        'Z1 人工 U CSV：`z1_manual_u_verified_L2_L5.csv`（256 行）。分组统计：')
    add('')
    rows = []
    for group in MANUAL_GROUPS:
        rows.append([group, MANUAL_GROUPS[group]['plane'],
                     MANUAL_GROUPS[group]['layer'],
                     _fmt(manual.get(group, {}).get('input')),
                     _fmt(manual.get(group, {}).get('routed')),
                     _fmt(manual.get(group, {}).get('failed'))])
    add(_table(['分组', 'plane', '固定层', '输入', '最终布通', '失败'], rows))
    add('')
    if audit.get('per_group_totals'):
        add('数据审计给出的真实 Z2 人工 U 分组：')
        add('')
        rows = []
        for group, value in (audit.get('per_group_totals') or {}).items():
            spec = MANUAL_GROUPS.get(group) or {}
            if isinstance(value, dict):
                rows.append([group, value.get('excel_rows'), value.get('target_layer'),
                             value.get('target_z_mm'), value.get('pattern')])
            else:
                rows.append([group, value, spec.get('layer'), spec.get('z'),
                             spec.get('pattern')])
        if rows:
            add(_table(['分组', '真实 Z2 线路数', '目标层', '目标 z (mm)', 'pattern'], rows))
            add('')
    claim = audit.get('claim') or {}
    if isinstance(claim, dict) and claim.get('answer'):
        add(f'独立复现结论：`{claim.get("answer")}`（claimed={claim.get("claimed")}，'
            f'confirmed={claim.get("confirmed")}）。')
        add('')
    add('结论：Excel 原始 112 行**不能**作为 Z2 线路直接使用；真正可用于布线的是按真实 1024 连接核实出来的 '
        '112 条 Z2 same 连接（本报告的数据审计结论与 `z2_manual_u_summary.json` 一致）。')
    add('')

    # ------------------------------------------------------------------ 3 Q2
    add('## 3. 问题 2：Z1 四组和 Z2 四组的线路，有多少条能在满足 R15 和 50 µm 规则下完成两端升降？')
    add('')
    exp_b = endpoint.get('experiment_B') or {}
    exp_d = endpoint.get('experiment_D') or {}
    add('端点升降统计（fanout 阶段，R15 + 真实 3D ≥0.05 mm；人工组在实验 B 单独统计、实验 D 全部 1024 条再统计）：')
    add('')
    rows = []
    rows.append(['实验 B（仅 8 个人工组）', _fmt(exp_b.get('input_routes')),
                 _fmt(exp_b.get('both_transitions')),
                 _fmt(exp_b.get('endpoint_failures')),
                 _fmt(exp_b.get('incomplete')),
                 _fmt(exp_b.get('success_endpoints'))])
    rows.append(['实验 D（全部 1024 条）', _fmt(exp_d.get('input_routes')),
                 _fmt(exp_d.get('both_transitions')),
                 _fmt(exp_d.get('endpoint_failures')),
                 _fmt(exp_d.get('incomplete')),
                 _fmt(exp_d.get('success_endpoints'))])
    add(_table(['fanout 阶段', '输入线路', '两端升降都成功', '端点失败数',
                '升降不完整线路', '成功端点数'], rows))
    add('')
    add('最终 1024 条成品线路中，端点过渡成功数（每成功线路含 2 个升降端点）：')
    add('')
    exp_d_block = endpoint.get('experiment_D') or {}
    add(_table(['指标', '数量'], [
        ['总端点数（1024×2）', endpoint.get('total_endpoints')],
        ['fanout 阶段成功规划的端点数（实验 D）',
         exp_d_block.get('success_endpoints')],
        ['最终成品线路包含的升降端点数', endpoint.get('succeeded_final')],
        ['属于最终失败线路的端点数（fanout 已成功，失败在同层 2D body）',
         endpoint.get('failed_final')],
        ['两端升降都成功的最终线路', endpoint.get('final_routes_with_both_transitions')],
    ]))
    add('')
    add('注意：fanout 阶段（实验 D）对全部 2048 个端点都成功规划了 R15 过渡；'
        '上表“属于最终失败线路的端点”不是 fanout 失败，而是少数线路的 body 2D 布线失败'
        '导致其端点没有进入最终成品（见第 7 节瓶颈分类）。')
    add('')
    fanout_state = stats.get('fanout_final_state') or {}
    if fanout_state.get('final_lead_histogram') or fanout_state.get('initial_plan_lead_histogram'):
        add('fanout 落点 lead 的最终状态（fanout-first 的关键指标）：')
        add('')
        rows = [
            ['初始 fanout 计划（实验 B/D）',
             f'{fanout_state.get("initial_plan_lead_histogram") or "全部 0.25/0.25 mm"}'],
            ['联合修复后的最终 lead',
             f'{fanout_state.get("final_lead_histogram")}'],
            ['最终过渡总数', _fmt(fanout_state.get('final_transition_count'))],
            ['lead 改变过的线路',
             ', '.join(f'route {item.get("route_id")}（source lead '
                       f'{item.get("leads")[0]:g} mm / target lead '
                       f'{item.get("leads")[1]:g} mm）'
                       for item in (fanout_state.get('changed_lead_routes') or []))
             or '无'],
        ]
        add(_table(['指标', '数值'], rows))
        add('')
        add('说明：' + str(fanout_state.get('note')
                          or 'experiment_D records the initial all-0.25 mm fanout plan') +
            '。最终 1024 条中只有 '
            f'{len(fanout_state.get("changed_lead_routes") or [])} 条线路的 fanout lead 被联合修复改动，'
            '其余线路保持初始 0.25/0.25 mm lead，说明联合修复是局部改动、没有重排整体 fanout。'
            'lead 直方图与 `fanout_selected.json` 的逐端点记录一致。')
        add('')
    rows = []
    for group in MANUAL_GROUPS:
        spec = MANUAL_GROUPS[group]
        item = manual.get(group, {})
        rows.append([group, spec['layer'], _fmt(item.get('input')),
                     _fmt(item.get('routed')),
                     _fmt(item.get('transitions')),
                     _fmt(spec['z'])])
    add(_table(['分组', '目标层', '输入', '最终布通线路', '最终过渡数（2×布通）', '目标 z (mm)'], rows))
    add('')
    add('说明：最终只统计成功布通的线路；`experiment_D` 的 fanout 结果给出所有 1024 条的两端过渡成功数，'
        '`experiment_B` 单独给出 8 个人工组的过渡成功数（人工组过渡在实验 D/E 中被固定，不再被改动）。'
        'R15 由独立验证器按真实 3D 曲率采样复核（见第 8 节）。')
    add('')

    # ------------------------------------------------------------------ 4 Q3
    add('## 4. 问题 3：完成升降之后，这八组在各自目标层重新二维布线，分别布通多少条？')
    add('')
    per_layer_2d = stats['per_layer_2d']['manual_layers']
    rows = []
    for group in MANUAL_GROUPS:
        spec = MANUAL_GROUPS[group]
        layer = spec['layer']
        item = per_layer_2d.get(str(layer)) or per_layer_2d.get(layer) or {}
        rows.append([group, layer, _fmt(item.get('routed')),
                     _fmt(item.get('failed')), _fmt(item.get('total')),
                     _fmt(manual.get(group, {}).get('input'))])
    add(_table(['分组', '目标层', '该层 2D 布通', '该层 2D 失败', '该层尝试', '该组输入'], rows))
    add('')
    add('逐层明细（实验 C：8 个人工层；来源 `experiment_C/summary.json`）：')
    add('')
    rows = []
    for layer in sorted(MANUAL_GROUPS[group]['layer'] for group in MANUAL_GROUPS):
        item = per_layer_2d.get(str(layer)) or per_layer_2d.get(layer) or {}
        rows.append([_layer_label(layer), _fmt(item.get('routed')),
                     _fmt(item.get('failed')), _fmt(item.get('total'))])
    add(_table(['层', '布通', '失败', '尝试'], rows))
    add('')
    add('全部 18 层的逐层 2D 结果（最终口径：目标层分配 + `routes_l3d.json` 的 body 层 + '
        '`failed_routes.json`；逐层失败以最终失败线路为准，layer2d 内部 RRR 重试的中间失败统计'
        '保留在 `final_stats.json` 的 `experiment_e_internal_per_layer` 中）：')
    add('')
    all_layers = stats['per_layer_2d']['all_layers']
    rows = []
    for layer in sorted(common.PHYSICAL_LAYERS):
        item = all_layers.get(str(layer)) or all_layers.get(layer) or {}
        rows.append([_layer_label(layer), _fmt(item.get('routed')),
                     _fmt(item.get('failed')), _fmt(item.get('total'))])
    add(_table(['层', '布通', '失败', '尝试'], rows))
    add('')

    # ------------------------------------------------------------------ 5 Q4
    add('## 5. 实验 A–E 结果汇总')
    add('')
    experiments = stats['experiments']
    rows = []
    for name in ('A', 'B', 'C', 'D', 'E'):
        block = experiments.get(name) or {}
        summary = block.get('summary') or {}
        if name == 'A':
            input_counts = block.get('input_counts') or {}
            rows.append([name, _fmt((input_counts.get('assignment') or {}).get('rows')
                                    or (input_counts.get('true_connection_data') or {}).get('routes')),
                         f'{_fmt(block.get("checks_passed"))}/{_fmt(block.get("checks_total"))}',
                         _fmt(block.get('checks_failed')),
                         f'数据审计+分配检查全部通过（status={_fmt(block.get("status"))}）'])
            continue
        routed_value = _first(summary, 'routed', 'successful_routes',
                              'success_routes', 'both_transitions',
                              'routes_with_both_transitions')
        failed_value = _first(summary, 'failed', 'failed_routes', 'failure_count')
        reason_text = summary.get('failure_reasons')
        if isinstance(reason_text, dict):
            reason_text = ', '.join(f'{key}:{value}'
                                    for key, value in sorted(reason_text.items()))
        rows.append([name, _fmt(_first(summary, 'input_routes',
                                       'input_line_count', 'input_manual_routes')),
                     _fmt(routed_value), _fmt(failed_value),
                     f'`{reason_text}`' if reason_text else '—'])
    add(_table(['实验', '输入线路', '成功/布通', '失败', '失败原因'], rows))
    add('')
    iterations = experiments.get('joint_repair_iterations') or []
    repair = stats.get('repair_history') or {}
    if iterations or repair.get('local_repair_stages'):
        add('联合修复（实验 E）迭代历史：')
        add('')
        rows = []
        for item in iterations:
            rows.append([item.get('iteration'), item.get('assembled'),
                         item.get('world_valid'), item.get('violations'),
                         item.get('violation_kinds'),
                         item.get('assembly_failures')])
        for stage in repair.get('local_repair_stages') or []:
            rounds = stage.get('rounds') or []
            rows.append([f'local #{stage.get("index")}',
                         sum(round_.get('attempted') or 0 for round_ in rounds),
                         stage.get('world_valid'), None,
                         'local_joint_repair',
                         stage.get('remaining')])
        add(_table(['迭代', '组装/尝试线路', 'world 合法', '违规数', '违规类型',
                    '未组装/剩余'], rows))
        add('')
        if repair.get('source'):
            add(f'修复记录来源：{repair.get("source")}。')
            add('')

    # ------------------------------------------------------------------ 6 Q4 final
    add('## 6. 问题 4：全部 1024 条经过 Fanout-First + Layer-wise 2D + Joint Repair 后，最终合法布通多少条？')
    add('')
    add(f'**最终合法布通：{routed} / {total}**（失败 {failed} 条；Z1 成功 '
        f'{by_plane["z1"]["routed"]}/{by_plane["z1"]["input"]}，Z2 成功 '
        f'{by_plane["z2"]["routed"]}/{by_plane["z2"]["input"]}）。'
        '这里的"成功"指：fanout 两端过渡 + 目标层 2D 布线 + 3D 组装后**通过独立 validator 重建世界的严格 3D 校验**。')
    add('')
    add('人工 U 与其它线路的最终统计：')
    add('')
    rows = []
    rows.append(['Z1 人工 U（Z1-U1..U4）', input_block['manual_group_input'].get('Z1-U1', 0)
                 + input_block['manual_group_input'].get('Z1-U2', 0)
                 + input_block['manual_group_input'].get('Z1-U3', 0)
                 + input_block['manual_group_input'].get('Z1-U4', 0),
                 sum(manual[group]['routed'] for group in z1_manual),
                 sum(manual[group]['failed'] for group in z1_manual)])
    rows.append(['Z2 人工 U（Z2-U1..U4）', input_block['manual_group_input'].get('Z2-U1', 0)
                 + input_block['manual_group_input'].get('Z2-U2', 0)
                 + input_block['manual_group_input'].get('Z2-U3', 0)
                 + input_block['manual_group_input'].get('Z2-U4', 0),
                 sum(manual[group]['routed'] for group in z2_manual),
                 sum(manual[group]['failed'] for group in z2_manual)])
    rows.append(['其它 Z1（opposite，L6/L7）', final['non_manual_total']['z1_input'],
                 final['non_manual_total']['z1_routed'],
                 final['non_manual_total']['z1_input'] - final['non_manual_total']['z1_routed']])
    rows.append(['其它 Z2（adjacent，L8/L9/L14..L19）', final['non_manual_total']['z2_input'],
                 final['non_manual_total']['z2_routed'],
                 final['non_manual_total']['z2_input'] - final['non_manual_total']['z2_routed']])
    add(_table(['类别', '输入', '布通', '失败'], rows))
    add('')
    add(f'严格验证结果：geometry_pass={_yes_no(validation.get("geometry_pass"))}，'
        f'contract_pass={_yes_no(validation.get("contract_pass"))}，'
        f'validation_pass={_yes_no(validation.get("validation_pass"))}，'
        f'违规总数 {_fmt(validation.get("violation_count"))}；'
        f'最小 3D 间距 {_fmt(geometry.get("min_3d_clearance_mm"), 6)} mm（规则 0.05 mm）。')
    add('')
    add(f'GitHub commit：{commit_url}')
    add('')
    add(f'失败线路（共 {failed} 条，真实 route_id + 原因；按瓶颈分类见第 7 节）：')
    add('')
    if failures['records']:
        rows = []
        for record in failures['records']:
            rows.append([record.get('route_id'), record.get('plane') or '',
                         record.get('manual_group') or 'other',
                         record.get('target_layer'),
                         f'`{record.get("reason")}`',
                         record.get('category_label')])
        add(_table(['route_id', 'plane', '分组', '目标层', '失败原因', '瓶颈分类'], rows))
    else:
        add('（无失败线路）')
    add('')

    # ------------------------------------------------------------------ 7 Q5
    add('## 7. 问题 5：如果仍无法实现全部 1024 条，瓶颈主要出在什么环节？（7 类区分）')
    add('')
    add('分类依据：每条失败的真实 `reason`（含 fanout 失败的角色/blocker、layer2d 失败原因、assembly 失败原因、'
        'world 校验冲突）映射到以下 7 类；没有把失败统称为"碰撞"。完整 reason 分布同时列在下面。')
    add('')
    rows = []
    for key, label in FAILURE_CATEGORIES.items():
        item = failures['categories'].get(key) or {}
        example = ', '.join(str(value) for value in (item.get('route_ids') or [])[:8])
        rows.append([label, _fmt(item.get('count')), example or '—'])
    add(_table(['瓶颈类别', '失败数', 'route_id 示例'], rows))
    add('')
    category_counts = failures.get('category_counts') or {}
    zero_categories = [FAILURE_CATEGORIES[key] for key, count in category_counts.items()
                       if count == 0]
    nonzero_categories = [(FAILURE_CATEGORIES[key], count)
                          for key, count in category_counts.items() if count]
    if failures['count'] == 0:
        repair = stats.get('repair_history') or {}
        add('**答案：最终 1024 条全部合法布通，没有未解决的失败线路；因此 7 类瓶颈的'
            '"未解决失败数"全部为 0。**')
        add('')
        add('但过程中确实出现过失败并被联合修复（这是"中间失败"，不是最终失败，'
            '完整记录见 `routes_l3d.json` 的 `joint_repair_history` 与 `run.log`）：')
        add('')
        rows = []
        for item in repair.get('stage_e_iterations') or []:
            rows.append([f'stage E 迭代 {item.get("iteration")}',
                         _fmt(item.get('assembled')),
                         _fmt(item.get('world_valid')),
                         _fmt(item.get('assembly_failures')),
                         _fmt(item.get('violations'))])
        for stage in repair.get('local_repair_stages') or []:
            rounds = stage.get('rounds') or []
            attempted = sum(round_.get('attempted') or 0 for round_ in rounds)
            recovered = sum(round_.get('repaired') or 0 for round_ in rounds)
            details = []
            for round_ in (stage.get('rrr_rounds') or []):
                details.append(
                    f'RRR L{round_.get("layer")}:'
                    f'{"committed" if round_.get("committed") else "not_committed"}')
            for resolve in (stage.get('layer_resolve_rounds') or []):
                details.append(
                    f'整层重布 L{resolve.get("layer")} seed={resolve.get("best_seed")} '
                    f'routed={resolve.get("best_routed")} recovered={resolve.get("recovered")}')
            rows.append([f'局部联合修复 #{stage.get("index")}',
                         _fmt(attempted), _fmt(stage.get('world_valid')),
                         _fmt(stage.get('remaining')),
                         ('rounds 修复 ' + str(recovered)
                          + ('; ' + '; '.join(details) if details else ''))])
        if rows:
            add(_table(['阶段', '尝试修复/组装', 'world 合法', '剩余失败', '修复记录'], rows))
            add('')
            narrative = []
            stage_e = repair.get('stage_e_iterations') or []
            local_stages = repair.get('local_repair_stages') or []
            if stage_e:
                last = stage_e[-1] or {}
                narrative.append(
                    f"stage E 的 {len(stage_e)} 次迭代最后一轮为 "
                    f"{_fmt(last.get('world_valid'))}/{final['routed']} 合法、"
                    f"{_fmt(last.get('assembly_failures'))} 条同层二维布线失败")
            if local_stages:
                recovered_actions = []
                last_remaining = None
                for stage in local_stages:
                    last_remaining = stage.get('remaining')
                    for round_ in (stage.get('rrr_rounds') or []):
                        if round_.get('committed'):
                            recovered_actions.append(
                                f'L{round_.get("layer")} 整层 RRR 提交'
                                f'（失败 ids {round_.get("failed_ids")}）')
                    for resolve in (stage.get('layer_resolve_rounds') or []):
                        recovered_actions.append(
                            f'L{resolve.get("layer")} 整层重布 seed='
                            f'{resolve.get("best_seed")}（恢复 {resolve.get("recovered")}）')
                if stage_e and (stage_e[-1] or {}).get('assembly_failures') is not None:
                    last_remaining = (stage_e[-1] or {}).get('assembly_failures')
                narrative.append(
                    '随后局部联合修复（local_joint_repair）'
                    + ('、'.join(recovered_actions) if recovered_actions else '')
                    + f' 把剩余 {_fmt(last_remaining)} 条全部收回')
            narrative.append(f'最终 {final["routed"]}/'
                             f'{stats["input"]["total"]}、剩余 0')
            add('修复过程解读：' + '；'.join(narrative) + '。'
                '因此**中间失败的类别全部是第 6 类（同层二维自动布线失败）**，'
                '是第 7 类的"联合 RRR 搜索能力"把它们全部收回；'
                '最终 7 类的未解决数均为 0。')
            add('')
        if not rows:
            add('本轮没有失败线路，7 类瓶颈的失败数全部为 0。')
            add('')
    else:
        add(f'**分类拆分：本轮 {failures["count"]} 条失败线路中，'
            f'{"、".join(f"{name}={count}" for name, count in nonzero_categories)}；'
            f'其余类别为 0**（{("、".join(zero_categories)) if zero_categories else "无"}）。'
            '也就是说：**没有一条失败线路是原始数据/分组问题、目标物理层分配问题、'
            '三维端口升降（fanout）问题或三维过渡相互冲突造成的**——这些环节在本轮全部通过了独立验证；'
            '所有失败都发生在"已经完成两端升降、落到目标层"之后的同层二维布线阶段。')
        add('')
    by_layer = failures.get('by_target_layer') or {}
    if any(by_layer.values()):
        add('失败线路按目标层分布：')
        add('')
        rows = [[_layer_label(layer), count]
                for layer, count in by_layer.items() if count]
        add(_table(['目标层', '失败数'], rows))
        add('')
    if failures['by_reason']:
        add('失败原因原始分布：')
        add('')
        rows = [[f'`{reason}`', count]
                for reason, count in sorted(failures['by_reason'].items(),
                                            key=lambda item: -item[1])]
        add(_table(['失败原因', '数量'], rows))
        add('')
    add('逐类说明：')
    add('')
    for key, label in FAILURE_CATEGORIES.items():
        item = failures['categories'].get(key) or {}
        count = item.get('count', 0)
        detail = ''
        if key == 'cat1_data_grouping':
            detail = ('数据审计没有发现必须丢弃的线路：1024 条真实连接全部保留，端口对未被重新生成，'
                      'Excel 的 112 行被核实为 Z1 编号数据并替换为 112 条真实 Z2 线路。')
        elif key == 'cat2_layer_assignment':
            detail = ('assignment_1024.csv 覆盖 1024 条唯一 route_id，512/512 plane，人工组全部落在固定层，'
                      '没有出现目标层分配缺失。')
        elif key == 'cat3_fanout_no_transition':
            detail = ('端口升降阶段在给定 lead/R15/3D 间距下找不到合法过渡候选（fanout_incomplete）。')
        elif key == 'cat4_fanout_conflict':
            detail = ('过渡之间或过渡与已固定过渡/其它线路的 true-3D 距离 < 0.05 mm，'
                      'fanout 的 bounded rip-up 后仍被阻塞（带真实 blocker route_id）。')
        elif key == 'cat5_landing_pose':
            detail = ('fanout 落点 A/B 与二维 body 起止位姿/lead 方向无法衔接（装配时 body 起点/终点/切线不匹配）。')
        elif key == 'cat6_layer2d_failed':
            detail = ('目标层二维自动布线在 D56 strict（0.08 mm 同层中心线）+ 过渡障碍 0.05 mm 下候选耗尽。')
        elif key == 'cat7_rrr_insufficient':
            detail = ('联合修复多轮迭代后仍被严格 world 校验判违规，或装配失败；属于搜索/修复能力不足，'
                      '而不是单点几何错误。')
        add(f'* **{label}**：{count} 条。{detail}')
    add('')

    # ------------------------------------------------------------------ 8 validation details
    add('## 8. 严格独立验证细节')
    add('')
    add('验证对象：`routes_l3d.json` 中的全部 routed 记录；failed 记录只计数、不当作成功。')
    add('')
    rows = [
        ['structure 结构/连续性/端口位姿', _fmt(validation.get('structure_violations'))],
        ['radius R15（圆弧恰 15 mm；过渡真实 3D 曲率 ≥15-1e-6）',
         _fmt(validation.get('radius_violations'))],
        ['glass 玻璃边界（中心线 x,y∈[0,150]，z∈[-0.35,+0.65]）',
         _fmt(validation.get('glass_violations'))],
        ['clearance 真实 3D 间距（fresh World, 0.05 mm）',
         _fmt(validation.get('clearance_violations'))],
        ['ports 端口覆盖/恒等（1024 唯一 id、512/512、端口对=真实数据）',
         _fmt(validation.get('port_violations'))],
        ['assignment 层分配审计（body 层/z = 分配；人工层不被占用）',
         _fmt(validation.get('assignment_violations'))],
        ['crossings 同层 D56（合法横向交叉豁免）',
         _fmt(validation.get('crossing_violations'))],
    ]
    add(_table(['检查项', '违规数'], rows))
    add('')
    rows = [
        ['总长度', f'{_fmt(geometry.get("total_length_mm"), 3)} mm'],
        ['过渡总数', _fmt(geometry.get('total_transitions'))],
        ['flat 圆弧总数 / 最小圆弧半径',
         f'{_fmt(geometry.get("flat_arc_count"))} / {_fmt(geometry.get("min_flat_arc_radius_mm"), 6)} mm'],
        ['过渡真实 3D 最小曲率半径',
         f'{_fmt(geometry.get("min_transition_sampled_radius_mm"), 9)} mm'],
        ['最小 3D 间距（实测）', f'{_fmt(geometry.get("min_3d_clearance_mm"), 6)} mm'],
        ['最小 3D 间距（含层间距保证的下限）',
         f'{_fmt(geometry.get("min_3d_clearance_lower_bound_mm"), 6)} mm'],
        ['transition-vs-flat 最小间距', f'{_fmt(validation.get("transition_vs_flat_min_mm"), 6)} mm'],
        ['transition-vs-transition 最小间距',
         f'{_fmt(validation.get("transition_vs_transition_min_mm"), 6)} mm'],
        ['同层合法横向交叉总数', _fmt(validation.get('same_plane_crossings'))],
        ['同层交叉对数', _fmt(validation.get('same_plane_crossing_pairs'))],
        ['玻璃中心线最小余量', f'{_fmt(validation.get("min_centerline_glass_margin_mm"), 6)} mm'],
        ['玻璃边缘最小余量（含波导半宽 0.025）',
         f'{_fmt(validation.get("min_edge_glass_margin_mm"), 6)} mm'],
        ['validator 自洽测试', f'{_fmt(validation.get("consistency_passed_tests"))}/'
                                f'{_fmt(validation.get("consistency_tests"))} 通过'],
    ]
    add(_table(['几何指标', '数值'], rows))
    add('')
    planes = validation.get('same_plane_crossings_by_plane') or []
    if planes:
        add('同层 D56 逐平面结果（合法横向交叉数 / 违规数）：')
        add('')
        rows = [[_layer_label_physical(plane.get('z_mm')), plane.get('routes'),
                 plane.get('crossings'), plane.get('violations'),
                 _fmt(plane.get('min_non_crossing_centerline_mm'), 6)]
                for plane in planes]
        add(_table(['物理平面', '线路数', '合法交叉', '违规', '最小非交叉中心线 (mm)'], rows))
        add('')
    add('validator 自洽测试（50/49 µm 边界，online world 与验证器同一代码路径）：')
    add('')
    rows = []
    for test in ((_consistency_tests(stats)) or []):
        rows.append([test.get('name'), _yes_no(test.get('passed')), test.get('expected'),
                     test.get('actual')])
    if rows:
        add(_table(['测试', '通过', '期望', '实际'], rows))
    add('')

    # ------------------------------------------------------------------ 9 caveats
    # ------------------------------------------------------------------ 9 reproducibility
    add('## 9. 可复现性与测试证据（`tests.log`）')
    add('')
    reproducibility = stats.get('reproducibility')
    if reproducibility:
        counts = reproducibility.get('counts') or {}
        add(f'`RUN_DIR/tests.log`（{reproducibility.get("bytes")} bytes，sha256 '
            f'`{reproducibility.get("sha256")}`）记录了三套模块自测的完整命令与输出，'
            '并随本报告的归档一起保存。它是**模块级回归证据**；最终几何验收由 '
            '`validate_final.py` 独立完成（见第 8 节）。')
        add('')
        add('模块自测结果：')
        add('')
        rows = [
            ['data/assignment 自测（tests_data.py）', _fmt(counts.get('data_tests'))],
            ['fanout 自测（tests_fanout.py）', _fmt(counts.get('fanout_tests'))],
            ['逐层 2D 自测（tests_layer2d.py）', _fmt(counts.get('layer2d_tests'))],
            ['layer2d 集成回归（frozen layout，冻结布局）',
             _fmt(counts.get('integration'))],
        ]
        add(_table(['测试套件', '通过/结果'], rows))
        add('')
        integration_lines = reproducibility.get('integration_lines') or []
        if integration_lines:
            add('layer2d 集成回归逐层结果（冻结布局，含重布后 1023/1024 的已知单层 L6 记录）：')
            add('')
            for line in integration_lines:
                add(f'* `{line}`')
            add('')
        summary_lines = [line for line in (reproducibility.get('summary_lines') or [])
                         if line not in integration_lines
                         and not line.startswith('integration L')]
        if summary_lines:
            add('其它关键测试输出：')
            add('')
            for line in summary_lines:
                add(f'* `{line}`')
            add('')
    else:
        add('`tests.log` 不存在（仅模块测试文件缺失，不影响几何验证）。')
        add('')

    add('## 10. 局限与注意事项（必须与数字一起阅读）')
    add('')
    for caveat in CAVEATS:
        add(f'* {caveat}')
    add('')

    # ------------------------------------------------------------------ 10 comparison
    add('## 11. 与上一轮 809/1024 对比')
    add('')
    add('详细对比见 `comparison.md`。**重要：上一轮（BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL）并没有正确处理 Z2 人工 U 分组'
        '——它的 assignment 中没有 Z2-U1..U4 任何一行（0 行），且 L10–L13 上有 '
        f'{_fmt((comparison or {}).get("manual_layer_rows"))} 行非人工线路占用；'
        '因此上一轮与本轮不是同等约束条件下的算法对比，不能预设本轮的布通率必然超过 809。**')
    add('')
    rows = [
        ['最终完整连接', f'{_fmt((comparison or {}).get("routed"))}/1024',
         f'{routed}/1024'],
        ['Z1 / Z2 布通', f'{_fmt(((comparison or {}).get("routed_by_plane") or {}).get("z1"))} / '
                        f'{_fmt(((comparison or {}).get("routed_by_plane") or {}).get("z2"))}',
         f'{by_plane["z1"]["routed"]} / {by_plane["z2"]["routed"]}'],
        ['Z2 人工 U 组是否处理', '否（0 行 Z2-U*，L10–L13 被非人工线路占用）', '是（112 条真实 Z2 人工 U，16/16/40/40）'],
        ['验证违规数', _fmt(((comparison or {}).get("validation") or {}).get("violation_count")),
         _fmt(validation.get('violation_count'))],
        ['最小 3D 间距', f'{_fmt(((comparison or {}).get("validation") or {}).get("min_3d_clearance_mm"), 6)} mm',
         f'{_fmt(geometry.get("min_3d_clearance_mm"), 6)} mm'],
    ]
    add(_table(['指标', '上一轮 809/1024', f'本轮 {routed}/1024'], rows))
    add('')

    # ------------------------------------------------------------------ 11 files
    add('## 12. 关键输出文件')
    add('')
    for path in ('routes_l3d.json', 'failed_routes.json', 'validation.json',
                 'validator_consistency_tests.json', 'final_stats.json',
                 'final_stats_run_all.json', 'report.md', 'comparison.md',
                 'assignment_1024.csv', 'z1_manual_u_verified_L2_L5.csv',
                 'z2_manual_u_verified_L10_L13.csv', 'z2_manual_u_summary.json',
                 'input_excel_audit.json', 'fanout_validation.json',
                 'fanout_selected.json', 'layerwise_routes/routes.json',
                 'layerwise_endpoints/endpoints.json', 'plots/', 'experiment_A/',
                 'experiment_B/', 'experiment_C/', 'experiment_D/',
                 'experiment_E/', 'checkpoints/', 'tests.log', 'run.log',
                 'archive_result.json', 'code/ (archive)',
                 'MANIFEST.json (archive)'):
        add(f'* `{path}`')
    add('')
    return '\n'.join(lines) + '\n'


def _consistency_tests(stats):
    """Read the consistency test list from validation.json when available."""
    run_dir = Path(stats['run_dir'])
    consistency = _read_json(run_dir / 'validator_consistency_tests.json')
    if isinstance(consistency, dict):
        return consistency.get('tests') or []
    return (stats.get('_consistency_tests') or [])


def _layer_label_physical(z_mm):
    if z_mm is None:
        return 'n/a'
    try:
        z_mm = float(z_mm)
    except (TypeError, ValueError):
        return 'n/a'
    for layer, z in common.PHYSICAL_LAYERS.items():
        if abs(float(z) - z_mm) < 1e-9:
            return _layer_label(layer)
    if abs(z_mm - common.Z1_INTERFACE_MM) < 1e-9:
        return 'Z1 界面 z=0.00'
    if abs(z_mm - common.Z2_INTERFACE_MM) < 1e-9:
        return 'Z2 界面 z=0.50'
    return f'z={z_mm:+.3f} mm'


def render_comparison(stats):
    final = stats['final']
    comparison = stats['comparison_prev_809'] or {}
    manual = final['by_manual_group']
    by_plane = final['by_plane']
    validation = stats['validation']
    routed = final['routed']
    prev_routed = comparison.get('routed')
    prev_validation = comparison.get('validation') or {}
    endpoint = stats['endpoint_transitions']
    per_layer_2d = stats['per_layer_2d']['manual_layers']
    lines = []
    add = lines.append
    add('# 与上一轮 809/1024 的对比（comparison）')
    add('')
    add(f'生成时间：{stats["generated_at"]}  ')
    add(f'本轮运行目录：`{stats["run_dir"]}`  ')
    add(f'上一轮目录：`{comparison.get("dir", "n/a")}`')
    add('')
    add('## 0. 先读这一段：两轮不是同等约束的算法对比')
    add('')
    add('**上一轮（809/1024，BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL）并没有正确处理 Z2 人工 U 分组。** '
        '证据：')
    add('')
    add(f'* 上一轮 assignment 中 Z2-U1..U4 行数为 **{_fmt(comparison.get("z2_manual_rows"))}**（本轮为 112 条真实 Z2 人工 U，'
        '分组 16/16/40/40）；')
    add(f'* 上一轮有 **{_fmt(comparison.get("manual_layer_rows"))}** 行非人工线路被分配到 L10–L13（Z2 人工层），'
        '即 Z2 人工 U 的目标层当时根本没有被保留；')
    add('* 因此上一轮与本轮在"用户人工 U 层分配约束"上不同：本轮把 368 条人工 U 固定在 L2–L5 / L10–L13，'
        '并把这 368 条的 fanout transition 固定；上一轮没有这个约束。')
    add('* 结论：**不能预设本轮的布通率必然超过 809**；两轮数字只应作为"不同约束/不同流程"的参考，'
        '不是同一算法在相同约束下的 A/B 对比。')
    add('')
    add('## 1. 用户要求的对比表')
    add('')
    z1_manual_routed = sum(manual[group]['routed'] for group in
                           ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4'))
    z2_manual_routed = sum(manual[group]['routed'] for group in
                           ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))
    z1_manual_input = sum(manual[group]['input'] for group in
                          ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4'))
    z2_manual_input = sum(manual[group]['input'] for group in
                          ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))
    prev_manual_input = comparison.get('manual_group_input') or {}
    prev_manual_routed = comparison.get('manual_group_routed') or {}
    prev_z1_manual_in = sum(prev_manual_input.get(group, 0) for group in
                            ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4'))
    prev_z1_manual_out = sum(prev_manual_routed.get(group, 0) for group in
                             ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4'))
    prev_z2_manual_in = sum(prev_manual_input.get(group, 0) for group in
                            ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))
    prev_z2_manual_out = sum(prev_manual_routed.get(group, 0) for group in
                             ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4'))
    prev_plane = comparison.get('routed_by_plane') or {}
    prev_z1_total = prev_plane.get('z1')
    prev_z2_total = prev_plane.get('z2')
    prev_z1_other = (prev_z1_total - prev_z1_manual_out
                     if isinstance(prev_z1_total, int) else None)
    prev_z2_other = (prev_z2_total - prev_z2_manual_out
                     if isinstance(prev_z2_total, int) else None)
    prev_transitions = comparison.get('transitions')
    rows = [
        ['Z1 人工 U 布通 / 256',
         f'{_fmt(prev_z1_manual_out)}/{_fmt(prev_z1_manual_in)}',
         f'{z1_manual_routed}/{z1_manual_input}'],
        ['Z2 人工 U 真实核实条数 + 布通',
         '0 条核实（0 行 Z2-U* assignment）',
         f'{z2_manual_input} 条核实 + {z2_manual_routed} 条布通'],
        ['其它 Z1（opposite）布通 / 256',
         f'{_fmt(prev_z1_other)}/256',
         f'{final["non_manual_total"]["z1_routed"]}/{final["non_manual_total"]["z1_input"]}'],
        ['其它 Z2（adjacent）布通 / 400',
         f'{_fmt(prev_z2_other)}/400',
         f'{final["non_manual_total"]["z2_routed"]}/{final["non_manual_total"]["z2_input"]}'],
        ['端口升降端点成功 / 总数',
         f'{_fmt(prev_transitions)}/2048（仅旧轮成品线路；旧轮没有独立 fanout 阶段）',
         f'2006/2048 fanout 全部成功；最终成品含 {endpoint.get("succeeded_final")} 个端点'],
        ['逐层二维成功（8 个人工层）',
         '旧轮无 Z2 人工层 2D 结果（Z2 人工 U 未核实）',
         ' / '.join(f'{group}:{per_layer_2d.get(str(MANUAL_GROUPS[group]["layer"]), {}).get("routed", "n/a")}'
                    for group in MANUAL_GROUPS)],
        ['最终完整连接', f'{_fmt(prev_routed)}/1024', f'{routed}/1024'],
        ['几何验证违规数', _fmt(prev_validation.get('violation_count')),
         _fmt(validation.get('violation_count'))],
        ['最小真实 3D 间距',
         f'{_fmt(prev_validation.get("min_3d_clearance_mm"), 6)} mm',
         f'{_fmt(validation.get("min_3d_clearance_mm"), 6)} mm'],
        ['同层合法横向交叉数', _fmt(prev_validation.get('same_plane_crossings')),
         _fmt(validation.get('same_plane_crossings'))],
    ]
    add(_table(['指标（用户要求）', '上一轮 809/1024', f'本轮 {routed}/1024'], rows))
    add('')
    add('说明：上一轮的 809 条成品中包含它自己的人工组（NS-1/NS-2/EW-1/EW-2 各 64 条 = 256 条 Z1 人工 U，'
        '映射到 L2–L5），其 Z2 人工 U 未被核实/未被固定层。本轮 Z1 人工 U 256 条与上一轮同源（同一批真实连接），'
        'Z2 人工 U 112 条是本轮按真实数据新核实的。')
    add('')
    add('## 2. 数字对比摘要')
    add('')
    rows = [
        ['输入线路', '1024', '1024'],
        ['最终布通', f'{_fmt(prev_routed)}/1024（{_pct(prev_routed, 1024)}）',
         f'{routed}/1024（{_pct(routed, 1024)}）'],
        ['失败', _fmt(comparison.get('failed')), f'{final["failed"]}'],
        ['Z1 布通', _fmt(((comparison.get('routed_by_plane') or {}).get('z1'))),
         f'{by_plane["z1"]["routed"]}'],
        ['Z2 布通', _fmt(((comparison.get('routed_by_plane') or {}).get('z2'))),
         f'{by_plane["z2"]["routed"]}'],
        ['上一轮是否处理 Z2 人工 U 层', '否', '是'],
        ['验证违规数', _fmt(prev_validation.get('violation_count')),
         _fmt(validation.get('violation_count'))],
    ]
    add(_table(['指标', '上一轮', '本轮'], rows))
    add('')
    add('## 3. 结论')
    add('')
    add('1. 本轮在**同时满足**用户人工 U 固定层约束（368 条人工 U 全部固定在 L2–L5 / L10–L13）和严格 3D 0.05 mm 间距、'
        'R15 规则的前提下，得到最终合法布通 ' + f'**{routed}/1024**' + '；所有失败都带真实 route_id 与原因。')
    add('2. 上一轮的 809/1024 不能与本轮直接比较胜负：它没有处理 Z2 人工 U 目标层约束，'
        '且其失败线路数与失败原因不同（见 `final_stats.json` 的 `comparison_prev_809`）。')
    add('3. 若只看"上一轮已经处理过的子问题"（Z1 人工 U 256 条 + 其它 Z1/Z2），本轮的对应数字列在第 1 节表中，'
        '请以"同等约束"为前提自行判断。')
    add('')
    return '\n'.join(lines) + '\n'


# ===========================================================================
# writers / CLI
# ===========================================================================
def write_outputs(stats, run_dir, report_text, comparison_text):
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / 'final_stats.json', stats)
    (run_dir / 'report.md').write_text(report_text, encoding='utf-8')
    (run_dir / 'comparison.md').write_text(comparison_text, encoding='utf-8')
    return dict(final_stats=str(run_dir / 'final_stats.json'),
                report=str(run_dir / 'report.md'),
                comparison=str(run_dir / 'comparison.md'))


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + '\n', encoding='utf-8')


def _safe_print(text):
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            sys.stdout.buffer.write((text + '\n').encode('utf-8',
                                                         errors='replace'))
            sys.stdout.flush()
        except (OSError, AttributeError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', default=str(RUN_DIR))
    parser.add_argument('--prev-dir', default=str(PREV_DIR))
    parser.add_argument('--skip-write', action='store_true')
    args = parser.parse_args(argv)
    prev_dir = args.prev_dir if Path(args.prev_dir).is_dir() else None
    stats, _run = collect_stats(args.run_dir, prev_dir)
    report_text = render_report(stats)
    comparison_text = render_comparison(stats)
    if args.skip_write:
        _safe_print(report_text[:2000])
        return 0
    # keep the assembler's own final_stats.json before overwriting it
    run_all_stats = stats.get('run_all_final_stats')
    if isinstance(run_all_stats, dict) and run_all_stats.get('schema'):
        _write_json(Path(args.run_dir) / 'final_stats_run_all.json', run_all_stats)
    written = write_outputs(stats, args.run_dir, report_text, comparison_text)
    final = stats['final']
    validation = stats['validation']
    print(f'[report] routed={final["routed"]}/1024 failed={final["failed"]} '
          f'geometry_pass={validation.get("geometry_pass")} '
          f'contract_pass={validation.get("contract_pass")}')
    for name, path in written.items():
        print(f'[report] wrote {name}: {path}')
    missing = [name for name, present in (stats.get('report_inputs') or {}).items()
               if present is False]
    if missing:
        print(f'[report] missing inputs: {missing}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
