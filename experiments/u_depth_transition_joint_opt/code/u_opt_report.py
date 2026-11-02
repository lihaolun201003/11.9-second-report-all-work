# -*- coding: utf-8 -*-
"""Chinese ``report.md`` / ``comparison.md`` for the U-depth joint optimization.

The report is generated **only** from the data files described in
:mod:`four_side_1024.manual_c4_adapt.u_opt_plots`; every number is either read
from a JSON/CSV artefact or computed deterministically from the stored route
geometry (in which case the report says so).  Missing artefacts are listed
explicitly and rendered as ``（缺失）`` - nothing is invented, no placeholder
value pretends to be a measurement.

CLI::

    python -m four_side_1024.manual_c4_adapt.u_opt_report \
        --data-dir <experiment dir> --out-dir <output dir>

    # smoke test against the frozen 20L checkpoint (baseline only)
    python -m four_side_1024.manual_c4_adapt.u_opt_report --smoke
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from . import u_opt_plots as PLOTS

SCHEMA = 'u_opt_report_v1'
DATA_STATUS_NAME = 'data_status.json'
MAX_TABLE_ROWS = 120
SUMMARY_KEYS = re.compile(
    r'(recover|success|ok$|_ok|fail|depth|length|transition|clearance|count|'
    r'total|rate|z2|u_|blocker|change)', re.IGNORECASE)
MISSING = '（缺失）'


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------
def _number(value, digits=3, unit=''):
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, int):
        return f'{value}{unit}'
    return f'{value:.{digits}f}{unit}'


def _int(value):
    return MISSING if value is None else f'{int(value)}'


def _md_table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(
            str(cell).replace('|', '\\|').replace('\n', ' ')
            for cell in row) + ' |')
    return '\n'.join(lines)


def _quote(value):
    return '—' if value in (None, '') else str(value).replace('|', '\\|')


def flatten_numbers(payload, prefix=''):
    """All ``(dotted.path, number)`` pairs in a JSON payload (order kept)."""
    result = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                result.append((path, value))
            elif isinstance(value, (dict, list)):
                result.extend(flatten_numbers(value, path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if isinstance(item, (dict, list)):
                result.extend(flatten_numbers(item, f'{prefix}[{index}]'))
    return result


SUMMARY_SKIP_PATTERN = re.compile(
    r'(^|\.)(?:changes|blockers|events|items|results|violations)\[')


def _summary_numbers(summary):
    if not summary:
        return []
    numbers = []
    for path, value in flatten_numbers(summary):
        if SUMMARY_SKIP_PATTERN.search(path):
            continue
        if not SUMMARY_KEYS.search(path.split('.')[-1]):
            continue
        numbers.append((path, value))
    return numbers[:40]


def _describe_payload(payload, max_lines=45):
    """Readable bullet list for an arbitrary JSON payload (no invented values)."""
    if payload is None:
        return ['（缺失）']

    def walk(node, prefix, depth, lines):
        if len(lines) >= max_lines:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                path = f'{prefix}.{key}' if prefix else str(key)
                if isinstance(value, bool):
                    lines.append(f'- `{path}`: {"是" if value else "否"}')
                elif isinstance(value, (int, float)):
                    text = f'{value:.6f}' if isinstance(value, float) else str(value)
                    lines.append(f'- `{path}`: {text}')
                elif isinstance(value, str):
                    lines.append(f'- `{path}`: {value}')
                elif isinstance(value, dict) and depth < 2:
                    lines.append(f'- `{path}`: dict（{len(value)} 项）')
                    walk(value, path, depth + 1, lines)
                elif isinstance(value, list) and depth < 2:
                    lines.append(f'- `{path}`: list（{len(value)} 项）')
                    for index, item in enumerate(value[:4]):
                        if isinstance(item, (dict, list)):
                            walk(item, f'{path}[{index}]', depth + 1, lines)
                        else:
                            lines.append(f'  - `{path}[{index}]`: {str(item)[:80]}')
                else:
                    lines.append(f'- `{path}`: {type(value).__name__}')
                if len(lines) >= max_lines:
                    lines.append('- ...（截断）')
                    return
        elif isinstance(node, list):
            for index, item in enumerate(node[:min(6, max_lines)]):
                if isinstance(item, (dict, list)):
                    walk(item, f'{prefix}[{index}]', depth + 1, lines)
                else:
                    lines.append(f'- `{prefix}[{index}]`: {str(item)[:80]}')

    lines = []
    walk(payload, '', 0, lines)
    if len(lines) >= max_lines:
        lines.append('- ...（截断）')
    return lines or ['（空）']


# ---------------------------------------------------------------------------
# data assembly
# ---------------------------------------------------------------------------
ID_COLUMN_NAMES = {'id', 'route_id', 'transition_index', 'group_id', 'index',
                   'pair_id', 'cable_id', 'channel', 'channel_index',
                   'source_channel', 'target_channel'}


def _change_csv_stats(rows):
    """Numeric statistics of one CSV table (computed from the file itself)."""
    if not rows:
        return []
    stats = []
    headers = list(rows[0])
    n = len(rows)
    for header in headers:
        if str(header).strip().lower() in ID_COLUMN_NAMES:
            continue
        values = [PLOTS.to_float(row.get(header)) for row in rows]
        values = [value for value in values if value is not None]
        if len(values) < max(2, n // 2):
            continue
        stats.append(dict(
            column=header, n=len(values),
            mean=float(sum(values) / len(values)),
            minimum=float(min(values)),
            maximum=float(max(values)),
        ))
    return stats


def _file_present(bundle, key, filename):
    """Whether an expected file of an experiment folder is present."""
    folder = PLOTS.EXPERIMENT_DIRS[key]
    target = PLOTS.relpath(Path(bundle.data_dir) / folder / filename)
    for entry in bundle.inventory:
        if entry['path'] == target:
            return bool(entry['present'])
    return (Path(bundle.data_dir) / folder / filename).is_file()


def _count_or_missing(bundle, key, route_or_result_count, filename):
    """0 with a present file is real data; 0 without the file is ``缺失``."""
    if route_or_result_count:
        return route_or_result_count
    return route_or_result_count if _file_present(bundle, key, filename) else None


def _summary_metric(summary, *keys):
    """First scalar value of the given key names inside a summary payload."""
    if not isinstance(summary, dict):
        return None
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    for value in summary.values():
        if isinstance(value, dict):
            found = _summary_metric(value, *keys)
            if found is not None:
                return found
    return None


SUMMARY_METRIC_KEYS = (
    ('summary.json: success', ('success', 'success_count', 'z2_ok')),
    ('summary.json: recovered', ('recovered', 'recovered_count')),
    ('summary.json: baseline_success',
     ('baseline_success', 'baseline_ok')),
    ('summary.json: total_interface', ('total_interface', 'total')),
    ('summary.json: changed_u', ('changed_u', 'changed_routes')),
    ('summary.json: deepened_u', ('deepened_u',)),
    ('summary.json: total_depth_increase_mm',
     ('total_depth_increase_mm', 'depth_increase_mm')),
    ('summary.json: candidates', ('candidates', 'candidate_count')),
)


def _route_metrics_rows(bundle):
    """Core computed metric comparison rows (baseline / A / B)."""
    route_sets = {key: bundle.routes.get(key) or {} for key in PLOTS.RUN_ORDER}
    u_routes = {}
    for key in PLOTS.RUN_ORDER:
        u_routes[key] = {rid: route for rid, route in route_sets[key].items()
                         if route.get('layer') in PLOTS.U_LAYERS}
    summaries = {key: PLOTS.summarize_routes(u_routes[key], u_only=True)
                 for key in PLOTS.RUN_ORDER}
    deltas = {}
    for key in ('A', 'B'):
        deltas[key] = PLOTS.delta_summary(u_routes['baseline'], u_routes[key])
    z2_all = {key: PLOTS.summarize_results(bundle.results.get(key) or [])
              for key in PLOTS.RUN_ORDER}
    z2_interface = {
        key: PLOTS.summarize_results(bundle.results.get(key) or [],
                                     bundle.z2_interface_ids)
        for key in PLOTS.RUN_ORDER}
    rows = []

    def row(metric, values, note=''):
        rows.append([metric] + [value if value is not None else MISSING
                                for value in values] + [note])

    u_count = {key: _count_or_missing(bundle, key, summaries[key]['count'],
                                      'u_routes.json')
               for key in PLOTS.RUN_ORDER}
    z2_count = {key: _count_or_missing(bundle, key, z2_all[key]['total'],
                                       'z2_results.json')
                for key in PLOTS.RUN_ORDER}
    row('U 线路数（L2–L5）',
        [u_count[key] for key in PLOTS.RUN_ORDER],
        '由 u_routes.json 统计，仅计目标层 L2–L5；文件缺失显示为缺失')
    layer_ids = list(PLOTS.U_LAYERS)
    for layer in layer_ids:
        values = []
        for key in PLOTS.RUN_ORDER:
            if u_count[key] is None:
                values.append(None)
            else:
                values.append(summaries[key]['layers'].get(layer, 0))
        row(f'L{layer} U 条数', values)
    row('U 目标层高均值 z (mm)',
        [_number(summaries[key]['layer_z_mean']) for key in PLOTS.RUN_ORDER],
        '由几何计算')
    row('U XY 嵌套深度均值 (mm)',
        [_number(summaries[key]['bulge_mean']) for key in PLOTS.RUN_ORDER],
        '同侧 U 端口连线到目标层 flat 几何的最大垂距，由几何计算')
    row('U 平均路径长度 (mm)',
        [_number(summaries[key]['length_mean'])
         for key in PLOTS.RUN_ORDER], '由 length_mm 字段/几何计算')
    row('U 总路径长度 (mm)',
        [_number(summaries[key]['length_total'], 1)
         for key in PLOTS.RUN_ORDER], '')
    row('Z2 结果总数',
        [z2_count[key] for key in PLOTS.RUN_ORDER],
        'z2_results.json 条数；文件缺失显示为缺失')
    row('Z2 ok 数',
        [None if z2_count[key] is None else z2_all[key]['ok']
         for key in PLOTS.RUN_ORDER], 'status == ok')
    row('Z2 fail 数',
        [None if z2_count[key] is None else z2_all[key]['fail']
         for key in PLOTS.RUN_ORDER], 'status == fail')
    row('Z2 recovered_by 条数',
        [None if z2_count[key] is None else z2_all[key]['recovered_count']
         for key in PLOTS.RUN_ORDER],
        'recovered_by 非空的结果条数')
    row('Z2 接口面结果条数',
        [None if z2_count[key] is None else z2_interface[key]['total']
         for key in PLOTS.RUN_ORDER],
        '仅统计 68 条 Z2 接口线路')
    row('Z2 接口面 ok 数',
        [None if z2_count[key] is None else z2_interface[key]['ok']
         for key in PLOTS.RUN_ORDER], '')
    row('Z2 接口面 recovered_by 条数',
        [None if z2_count[key] is None
         else z2_interface[key]['recovered_count']
         for key in PLOTS.RUN_ORDER], '')
    # computed deltas
    for label, metric in (('U 平均层高增量 Δz (mm)', 'layer_delta_mean'),
                          ('U XY 深度增量均值 (mm)', 'bulge_delta_mean'),
                          ('U 平均路径长度增量 (mm)', 'length_delta_mean'),
                          ('U 过渡位置平均偏移 (mm)', 'transition_shift_mean')):
        values = [None, None, None]
        for index, key in enumerate(('A', 'B'), start=1):
            delta = deltas.get(key)
            values[index] = (None if delta is None
                             else _number(delta.get(metric)))
        row(label, values, '由同 route_id 前后配对几何计算（baseline 为基准 0）')
    row('发生层高变化的 U 条数',
        [None, (deltas['A'] or {}).get('changed_layer_count'),
         (deltas['B'] or {}).get('changed_layer_count')], '')
    row('发生过渡位置变化的 U 条数',
        [None, (deltas['A'] or {}).get('changed_transition_count'),
         (deltas['B'] or {}).get('changed_transition_count')],
        '沿路径位置偏移 > 0.2 mm')
    row('匹配上的 U 条数（与 baseline 同 id）',
        [None, (deltas['A'] or {}).get('matched'),
         (deltas['B'] or {}).get('matched')], '')
    # summary.json 中记录的原始指标（逐字读取，缺失即缺失）
    for label, keys in SUMMARY_METRIC_KEYS:
        values = []
        for key in PLOTS.RUN_ORDER:
            value = _summary_metric(bundle.summaries.get(key), *keys)
            values.append(None if value is None else value)
        if any(value is not None for value in values):
            row(label, values, '逐字读取 summary.json（含 baseline_summary.json）')
    return rows, dict(summaries=summaries, deltas=deltas, z2_all=z2_all,
                      z2_interface=z2_interface, u_routes=u_routes)


BLOCKER_PREVIEW = 5


def _blocker_cell(blockers):
    """Compact rendering of a blocker list (route ids, capped preview)."""
    ids = sorted({blocker['route_id'] for blocker in blockers
                  if blocker['route_id'] is not None})
    kinds = Counter(blocker['kind'] for blocker in blockers)
    if not ids and not kinds:
        return '—'
    if ids:
        preview = ', '.join(str(rid) for rid in ids[:BLOCKER_PREVIEW])
        more = f' …(+{len(ids) - BLOCKER_PREVIEW})' if len(ids) > BLOCKER_PREVIEW else ''
        return f'{len(blockers)} 条（唯一 Z1 route {len(ids)} 个: {preview}{more}）'
    return f'{len(blockers)} 条（{", ".join(kinds)}）'


def _recovered_rows(bundle):
    rows = []
    interface_table = PLOTS.interface_recovery_table(bundle,
                                                     bundle.z2_interface_ids)
    for row in interface_table:
        baseline = row['baseline']
        A = row['A']
        B = row['B']
        recovered = row['recovered_by']
        if baseline is None and A is None and B is None:
            continue
        if not (recovered or A == 'ok' or B == 'ok'
                or row['baseline_blockers']):
            continue
        baseline_blockers = _blocker_cell(row['baseline_blockers'])
        rows.append([
            row['route_id'], _quote(baseline), _quote(A), _quote(B),
            _quote(', '.join(recovered) if recovered else ''),
            _quote(baseline_blockers or row['baseline_reason']),
        ])
    return rows, interface_table


def _blocker_rows(bundle, interface_table):
    """Blocker summary rows + per-interface-route blocker changes."""
    changed = []
    for row in interface_table:
        baseline_ids = {blocker['route_id']
                        for blocker in row['baseline_blockers']
                        if blocker['route_id'] is not None}
        a_ids = {blocker['route_id'] for blocker in row['A_blockers']
                 if blocker['route_id'] is not None}
        b_ids = {blocker['route_id'] for blocker in row['B_blockers']
                 if blocker['route_id'] is not None}
        baseline_count = len(row['baseline_blockers'])
        a_count = len(row['A_blockers'])
        b_count = len(row['B_blockers'])
        if (baseline_count, baseline_ids) != (a_count, a_ids) or \
                (baseline_count, baseline_ids) != (b_count, b_ids):
            changed.append([
                row['route_id'],
                _quote(_blocker_cell(row['baseline_blockers'])),
                _quote(_blocker_cell(row['A_blockers'])),
                _quote(_blocker_cell(row['B_blockers'])),
            ])
    summary_rows = []
    for key in PLOTS.RUN_ORDER:
        results = PLOTS.summarize_results(bundle.results.get(key) or [],
                                          bundle.z2_interface_ids)
        summary_rows.append([
            PLOTS.EXPERIMENT_LABELS[key],
            results['blocked_routes'], results['blocker_entries'],
            len({blocker['route_id']
                 for result in bundle.z2_interface_results(key)
                 for blocker in result['blockers']
                 if blocker['route_id'] is not None}),
        ])
    return summary_rows, changed


def _parameters_lines(bundle, out_lines):
    """``u_parameters.json`` (current optimizer implementation) summary."""
    rows = []
    for key in PLOTS.RUN_ORDER:
        payload = bundle.parameters.get(key)
        if not isinstance(payload, dict) or not payload:
            continue
        entries = [value for value in payload.values()
                   if isinstance(value, dict)]
        if not entries:
            continue
        layers = Counter(int(value['layer']) for value in entries
                         if PLOTS.to_int(value.get('layer')) is not None)
        arms = [PLOTS.to_float(value.get('current_arm_mm'))
                for value in entries]
        arms = [value for value in arms if value is not None]
        depths = [PLOTS.to_float(value.get('current_depth_mm'))
                  for value in entries]
        depths = [value for value in depths if value is not None]
        rises = [PLOTS.to_float(value.get('current_rise_start'))
                 for value in entries]
        rises = [value for value in rises if value is not None]
        falls = [PLOTS.to_float(value.get('current_fall_start'))
                 for value in entries]
        falls = [value for value in falls if value is not None]

        def mean(values):
            return f'{sum(values) / len(values):.3f}' if values else MISSING

        rows.append([
            PLOTS.EXPERIMENT_LABELS[key], len(entries),
            ', '.join(f'L{layer}:{layers[layer]}' for layer in sorted(layers)),
            mean(arms), mean(depths), mean(rises), mean(falls),
        ])
    if rows:
        out_lines.append(_md_table(
            ['实验', 'U 参数条数', '目标层分布', '平均 arm (mm)',
             '平均 depth (mm)', '平均 rise 位置 (mm)', '平均 fall 位置 (mm)'],
            rows))
        out_lines.append('')
    else:
        out_lines.append(f'{MISSING}（没有 u_parameters.json）')
        out_lines.append('')


def _validation_summary_lines(bundle, out_lines):
    rows = []
    for key in PLOTS.RUN_ORDER:
        payload = bundle.validation_summaries.get(key)
        if not payload:
            continue
        counts = payload.get('counts') if isinstance(payload, dict) else None
        rows.append([
            PLOTS.EXPERIMENT_LABELS[key],
            _quote(payload.get('status')),
            _quote(payload.get('geometry_pass')),
            (counts or {}).get('violations', MISSING) if counts else MISSING,
            (counts or {}).get('clearance_violations', MISSING)
            if counts else MISSING,
        ])
    if rows:
        out_lines.append(_md_table(
            ['实验', 'status', 'geometry_pass', 'violations',
             'clearance_violations'], rows))
        out_lines.append('')
    else:
        out_lines.append(f'{MISSING}（没有 validation_summary.json）')
        out_lines.append('')


def _change_csv_sections(bundle, out_lines):
    sources = []
    for key in ('A', 'B'):
        for source, rows in (bundle.changes.get(key) or {}).items():
            sources.append((f'{PLOTS.EXPERIMENT_DIRS[key]}/{source}.csv', rows))
    for source, rows in (bundle.global_changes or {}).items():
        sources.append((f'{source}.csv', rows))
    if not sources:
        out_lines.append('（缺失：没有找到任何 changes CSV）')
        return
    for name, rows in sources:
        out_lines.append(f'#### `{name}`（{len(rows or [])} 行）')
        out_lines.append('')
        if not rows:
            out_lines.append('（空表）')
            out_lines.append('')
            continue
        stats = _change_csv_stats(rows)
        if stats:
            out_lines.append(_md_table(
                ['数值列', '非空数', '均值', '最小', '最大'],
                [[stat['column'], stat['n'], f'{stat["mean"]:.3f}',
                  f'{stat["minimum"]:.3f}', f'{stat["maximum"]:.3f}']
                 for stat in stats]))
            out_lines.append('')
        else:
            out_lines.append('（没有可统计的数值列）')
            out_lines.append('')
        preview_rows = []
        for row in rows[:12]:
            preview_rows.append([str(value)[:40] for value in
                                 list(row.values())[:8]])
        if preview_rows:
            headers = list(rows[0].keys())[:8]
            out_lines.append(_md_table(headers, preview_rows))
            if len(rows) > 12:
                out_lines.append(f'（仅显示前 12 行，共 {len(rows)} 行）')
            out_lines.append('')


def _integration_lines(bundle, out_lines):
    integration = bundle.integration
    z2_results = integration.get('results') or []
    l7_results = integration.get('l7_l8_results') or []
    summary = integration.get('summary')
    out_lines.append(f'- 集成 Z2 结果条数：{len(z2_results)}'
                     + (f'（ok={sum(1 for r in z2_results if r["status"] == "ok")}）'
                        if z2_results else ''))
    out_lines.append(f'- L7/L8 结果条数：{len(l7_results)}'
                     + (f'（ok={sum(1 for r in l7_results if r["status"] == "ok")}）'
                        if l7_results else ''))
    if summary:
        out_lines.append('- integration summary 中的数值（原文读取）：')
        for path, value in _summary_numbers(summary):
            out_lines.append(f'  - `{path}` = {value}')
    if not z2_results and not l7_results and not summary:
        out_lines.append(f'- {MISSING}（integration_L7_L8/ 没有任何结果文件）')


def _figure_index_lines(bundle):
    manifest_path = Path(bundle.out_dir) / 'plots' / 'manifest.json'
    if not manifest_path.is_file():
        return [f'{MISSING}（先运行 u_opt_plots 生成 plots/manifest.json）']
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as exc:  # noqa: BLE001
        return [f'读取 plots/manifest.json 失败：{exc}']
    lines = []
    figures = manifest.get('figures') or []
    for figure in figures:
        files = figure.get('files') or []
        lines.append(f'- 图{figure.get("index"):02d} {figure.get("title")}'
                     f'：`{figure.get("status")}`'
                     + (f'，文件 {", ".join("`" + name + "`" for name in files)}'
                        if files else ''))
        if figure.get('note'):
            lines.append(f'  - 说明：{str(figure["note"]).splitlines()[0][:300]}')
    if not figures:
        lines.append('（manifest 中没有图记录）')
    return lines


# ---------------------------------------------------------------------------
# report rendering
# ---------------------------------------------------------------------------
def _now_rows(bundle):
    """``(u_route_row_count, z2_result_row_count)`` helper for the summary."""
    u_counts = {key: len({rid: route for rid, route in
                          (bundle.routes.get(key) or {}).items()
                          if route.get('layer') in PLOTS.U_LAYERS})
                for key in PLOTS.RUN_ORDER}
    z2_counts = {key: len(bundle.results.get(key) or [])
                 for key in PLOTS.RUN_ORDER}
    return u_counts, z2_counts


def _conclusion_lines(bundle, metrics):
    """Data-driven, conditional conclusion sentences (no invented claims)."""
    z2 = metrics['z2_interface']
    deltas = metrics['deltas']
    lines = []
    lines.append(
        f'- baseline 的 68 条 Z2 接口线路中，`z2_results.json` 记录 ok='
        f'{z2["baseline"]["ok"]}、recovered_by='
        f'{z2["baseline"]["recovered_count"]}。')
    for key in ('A', 'B'):
        label = PLOTS.EXPERIMENT_LABELS[key]
        if not bundle.results.get(key):
            lines.append(f'- {label}：{MISSING}（未找到 z2_results.json）。')
            continue
        ok = z2[key]['ok']
        diff = ok - z2['baseline']['ok']
        delta = deltas.get(key)
        cost = []
        if delta is not None:
            if delta.get('layer_delta_mean') is not None:
                cost.append(f'平均层高变化 {delta["layer_delta_mean"]:+.3f} mm')
            if delta.get('bulge_delta_mean') is not None:
                cost.append(f'平均 XY 深度变化 {delta["bulge_delta_mean"]:+.3f} mm')
            if delta.get('length_delta_mean') is not None:
                cost.append(f'平均路径长度变化 {delta["length_delta_mean"]:+.3f} mm')
            if delta.get('transition_shift_mean') is not None:
                cost.append(f'平均过渡位置偏移 {delta["transition_shift_mean"]:.3f} mm')
        lines.append(f'- {label}：接口线路 ok={ok}（相对 baseline '
                     f'{diff:+d}），recovered_by={z2[key]["recovered_count"]}'
                     + (f'；几何代价：{"，".join(cost)}' if cost else '')
                     + '。')
    return lines


def build_report(bundle, out_dir=None):
    """Return ``(report_markdown, comparison_markdown, data_status)``."""
    out_dir = Path(out_dir) if out_dir is not None else bundle.out_dir
    metric_rows, metrics = _route_metrics_rows(bundle)
    recovered_rows, interface_table = _recovered_rows(bundle)
    blocker_summary_rows, blocker_changed_rows = _blocker_rows(
        bundle, interface_table)
    missing = bundle.missing_inputs()
    counts = bundle.counts()
    u_counts, z2_counts = _now_rows(bundle)
    report = []
    report.append('# U 深度 / S 过渡位置联合优化实验报告')
    report.append('')
    report.append('> 本报告由 `four_side_1024.manual_c4_adapt.u_opt_report` '
                  '自动生成；所有数值来自实验目录中的 JSON/CSV，或由存储的'
                  '路由几何确定性计算得到（会明确标注）。缺失数据一律标记为'
                  f'`{MISSING}`，不虚构数值。')
    report.append('')
    report.append(f'- 模式：`{"smoke（冻结 20L checkpoint，A/B 数据缺失）" if bundle.smoke else "production"}`')
    report.append(f'- 数据目录：`{PLOTS.relpath(bundle.data_dir)}`')
    report.append(f'- 输出目录：`{PLOTS.relpath(out_dir)}`')
    report.append(f'- 中文字体：`{", ".join(PLOTS.CHOSEN_FONTS)}`'
                  f'（CJK={PLOTS.HAS_CJK_FONT}）')
    if bundle.smoke:
        report.append('- smoke 模式：baseline 来自冻结的 20L checkpoint / 2D '
                      'campaign / failed_routes.json；实验 A/B 结果不存在。')
    report.append('')

    # ---- 1. data completeness -------------------------------------------
    report.append('## 1. 数据完整性')
    report.append('')
    inventory_rows = []
    for entry in bundle.inventory:
        inventory_rows.append([
            '`' + entry['path'] + '`', entry['role'],
            '存在' if entry['present'] else '**缺失**',
            entry['bytes'] if entry['present'] else '—',
        ])
    report.append(_md_table(['文件', '用途', '状态', '字节'], inventory_rows))
    report.append('')
    report.append(f'缺失文件数：**{len(missing)}**'
                  + ('；全部缺失文件已在第 1 节表格中标记。' if missing else '。'))
    report.append('')

    # ---- 2. metrics ------------------------------------------------------
    report.append('## 2. 指标对比（baseline / 实验 A / 实验 B）')
    report.append('')
    report.append(_md_table(
        ['指标', 'baseline', '实验 A 固定深度', '实验 B 自适应深度', '说明'],
        metric_rows))
    report.append('')
    report.append('说明：`U` 指标只统计目标层为 L2–L5 的 U 路由；'
                  '`Z2` 指标来自 `z2_results.json`；'
                  '当前优化器把恢复信息写在文件级 `recovered_ids` 列表中，'
                  '本报告将其计入 recovered_by 统计；'
                  '增量类指标由同一 `route_id` 的前后几何配对计算，'
                  'baseline 一列为空表示基准值。')
    report.append('')

    # ---- 3. recovered routes --------------------------------------------
    report.append('## 3. Z2 接口线路恢复清单')
    report.append('')
    with_2d = len(bundle.z2_interface_2d)
    report.append(f'Z2 接口线路共 {len(bundle.z2_interface_ids)} 条，'
                  f'其中 {with_2d} 条有冻结 2D 几何，'
                  f'{len(bundle.z2_interface_2d_missing)} 条无 2D 几何。')
    report.append('')
    if recovered_rows:
        report.append(_md_table(
            ['route_id', 'baseline', 'A', 'B', 'recovered_by',
             'baseline blocker / 原因'], recovered_rows[:MAX_TABLE_ROWS]))
        if len(recovered_rows) > MAX_TABLE_ROWS:
            report.append(f'（截断：共 {len(recovered_rows)} 行）')
    else:
        report.append(f'{MISSING}：没有可列出的接口线路结果'
                      '（z2_results.json 缺失或为空）。')
    report.append('')

    # ---- 4. blocker changes ---------------------------------------------
    report.append('## 4. Blocker 变化')
    report.append('')
    report.append('`z2_results.json` 中每条失败接口线路的 `blockers` 是阻挡它的 '
                  'Z1 route id 列表；下表统计受阻线路数与 blocker 条目。')
    report.append('')
    report.append('### 4.1 blocker 统计（接口线路）')
    report.append('')
    report.append(_md_table(
        ['实验', '受阻接口线路数', 'blocker 条目总数', '涉及唯一 Z1 route 数'],
        blocker_summary_rows))
    report.append('')
    report.append('### 4.2 逐线路 blocker 变化（前后 blocker 集合不同者）')
    report.append('')
    if not bundle.results.get('A') and not bundle.results.get('B'):
        report.append('（实验 A/B 的 `z2_results.json` 缺失：下表 A/B 两列'
                      '只能显示为空，「变化」不代表 blocker 被消除。）')
        report.append('')
    if blocker_changed_rows:
        report.append(_md_table(
            ['route_id', 'baseline blockers', 'A blockers', 'B blockers'],
            blocker_changed_rows[:MAX_TABLE_ROWS]))
        if len(blocker_changed_rows) > MAX_TABLE_ROWS:
            report.append(f'（截断：共 {len(blocker_changed_rows)} 行）')
    else:
        report.append('（没有 blocker 变化记录，或 A/B 数据缺失。）')
    report.append('')
    if bundle.blocker_analysis is not None:
        report.append('### 4.3 `blocker_analysis.json`（原文结构摘要）')
        report.append('')
        report.extend(_describe_payload(bundle.blocker_analysis))
        report.append('')
    else:
        report.append(f'`blocker_analysis.json`：{MISSING}')
        report.append('')

    # ---- 5. changes ------------------------------------------------------
    report.append('## 5. U 深度 / 过渡位置变化')
    report.append('')
    report.append('### 5.1 由前后路由几何计算的增量')
    report.append('')
    delta_rows = []
    for key in ('A', 'B'):
        delta = metrics['deltas'].get(key)
        if delta is None:
            delta_rows.append([PLOTS.EXPERIMENT_LABELS[key]] + [MISSING] * 6)
            continue
        delta_rows.append([
            PLOTS.EXPERIMENT_LABELS[key], delta['matched'],
            _number(delta['changed_layer_count']), _number(delta['layer_delta_mean']),
            _number(delta['bulge_delta_mean']),
            _number(delta['length_delta_mean']),
            _number(delta['transition_shift_mean']),
        ])
    report.append(_md_table(
        ['实验', '匹配 U 数', '层高变化条数', '平均 Δz (mm)',
         '平均 XY 深度增量 (mm)', '平均路径长度增量 (mm)',
         '平均过渡位置偏移 (mm)'], delta_rows))
    report.append('')
    report.append('### 5.2 changes CSV 统计（`u_depth_changes.csv` / '
                  '`transition_position_changes.csv` / `route_changes.csv`）')
    report.append('')
    _change_csv_sections(bundle, report)

    # ---- 5.3 current optimizer parameter dump ---------------------------
    report.append('### 5.3 `u_parameters.json` 摘要（当前优化器输出的 U 参数）')
    report.append('')
    _parameters_lines(bundle, report)

    # ---- 6. integration + validation ------------------------------------
    report.append('## 6. L7/L8 集成结果与验证摘要')
    report.append('')
    _integration_lines(bundle, report)
    report.append('')
    report.append('### 6.2 `validation_summary.json`')
    report.append('')
    _validation_summary_lines(bundle, report)

    # ---- 7. figures ------------------------------------------------------
    report.append('## 7. 图表索引（plots/manifest.json）')
    report.append('')
    report.extend(_figure_index_lines(bundle))
    report.append('')

    # ---- 8. summary numbers ---------------------------------------------
    report.append('## 8. summary / optimization_summary 中的原文数值')
    report.append('')
    any_summary = False
    for key in PLOTS.RUN_ORDER:
        summary = bundle.summaries.get(key)
        if not summary:
            continue
        any_summary = True
        source_note = ''
        if bundle.smoke and key == 'baseline':
            source_note = '（smoke 模式：实际读取的是冻结 20L 的 `final_stats.json`）'
        elif key == 'baseline':
            top_level = Path(bundle.data_dir) / 'baseline_summary.json'
            if top_level.is_file() and not (
                    Path(bundle.data_dir) / 'baseline' / 'summary.json').is_file():
                source_note = '（实际读取的是顶层 `baseline_summary.json`）'
        report.append(f'### {PLOTS.EXPERIMENT_LABELS[key]} summary.json'
                      f'{source_note}')
        report.append('')
        numbers = _summary_numbers(summary)
        if not numbers:
            report.append('（summary 中没有匹配的关键数值）')
        else:
            report.append(_md_table(
                ['字段', '值'],
                [[f'`{path}`', f'{value:.6f}' if isinstance(value, float)
                  else str(value)] for path, value in numbers]))
        report.append('')
    if bundle.optimization_summary is not None:
        any_summary = True
        report.append('### optimization_summary.json')
        report.append('')
        numbers = _summary_numbers(bundle.optimization_summary)
        if numbers:
            report.append(_md_table(
                ['字段', '值'],
                [[f'`{path}`', f'{value:.6f}' if isinstance(value, float)
                  else str(value)] for path, value in numbers]))
        else:
            report.append('（没有匹配的关键数值）')
        report.append('')
    if not any_summary:
        report.append(f'{MISSING}：summary.json / optimization_summary.json 均不存在。')
        report.append('')

    # ---- 9. caveats ------------------------------------------------------
    report.append('## 9. 缺失数据与假设 / 局限')
    report.append('')
    if missing:
        report.append('以下输入文件缺失，相关指标/图已标记为缺失，未用占位值替代：')
        report.append('')
        for entry in missing:
            report.append(f'- `{entry["path"]}`（用途：{entry["role"]}）')
        report.append('')
    else:
        report.append('所有预期输入文件均存在。')
        report.append('')
    report.append('- 由本仓库脚本计算的量（几何采样距离、z=0.5 穿越点、'
                  'XY 嵌套深度、层高/长度增量）均标注为“由几何计算”；'
                  '它们不是优化器官方指标。')
    report.append('- 采样最近距离使用固定采样步长，仅用于定位/解释局部视图，'
                  '不作为正式净空判定。')
    report.append('- 未做任何端点配对、分组、目标层或 R15/净空修改的假设；'
                  '报告只描述文件中记录的结果。')
    report.append('- Z2 接口 2D 几何缺失的线路无法给出地图线段，已在第 3 节计数。')
    report.append('')

    # ---- comparison.md ---------------------------------------------------
    comparison = []
    comparison.append('# 优化前后对比（baseline / 实验 A / 实验 B）')
    comparison.append('')
    comparison.append('> 数值来源：`u_routes.json` / `z2_results.json` / '
                      '`summary.json` 等实验文件；缺失项标记为 `'
                      f'{MISSING}`。')
    comparison.append('')
    comparison.append('## 核心对比表')
    comparison.append('')
    core_rows = []
    for row in metric_rows:
        metric, values = row[0], row[1:4]
        if metric in ('U 线路数（L2–L5）', 'U 目标层高均值 z (mm)',
                      'U XY 嵌套深度均值 (mm)', 'U 平均路径长度 (mm)',
                      'Z2 ok 数', 'Z2 recovered_by 条数',
                      'Z2 接口面 ok 数', 'Z2 接口面 recovered_by 条数',
                      'U 平均层高增量 Δz (mm)',
                      'U XY 深度增量均值 (mm)',
                      'U 平均路径长度增量 (mm)',
                      'U 过渡位置平均偏移 (mm)') \
                or metric.startswith('summary.json:'):
            core_rows.append([metric] + list(values))
    comparison.append(_md_table(
        ['指标', 'baseline', '实验 A', '实验 B'], core_rows))
    comparison.append('')
    comparison.append('## 结论（由上述数据推导）')
    comparison.append('')
    comparison.extend(_conclusion_lines(bundle, metrics))
    comparison.append('')
    comparison.append('## 数据状态')
    comparison.append('')
    comparison.append(f'- U 路由条数：baseline={u_counts["baseline"]}，'
                      f'A={u_counts["A"]}，B={u_counts["B"]}')
    comparison.append(f'- Z2 结果条数：baseline={z2_counts["baseline"]}，'
                      f'A={z2_counts["A"]}，B={z2_counts["B"]}')
    if missing:
        comparison.append(f'- 缺失输入文件 {len(missing)} 个：'
                          + ', '.join('`' + entry['path'] + '`'
                                      for entry in missing[:10])
                          + (' ...' if len(missing) > 10 else ''))
    comparison.append(f'- 图表索引：`plots/manifest.json`'
                      + ('（存在）' if (Path(out_dir) / 'plots'
                                        / 'manifest.json').is_file()
                         else '（尚未生成）'))
    comparison.append('')

    data_status = dict(
        schema=SCHEMA,
        mode='smoke' if bundle.smoke else 'production',
        data_dir=PLOTS.relpath(bundle.data_dir),
        out_dir=PLOTS.relpath(out_dir),
        counts=counts,
        missing_input_count=len(missing),
        missing_inputs=[entry['path'] for entry in missing],
        present_inputs=[entry['path'] for entry in bundle.inventory
                        if entry['present']],
        notes=bundle.notes,
        fonts=PLOTS.CHOSEN_FONTS,
        has_cjk_font=PLOTS.HAS_CJK_FONT,
    )
    return '\n'.join(report), '\n'.join(comparison), data_status


def write_reports(bundle=None, out_dir=None, data_dir=None, smoke=False):
    """Write ``report.md`` / ``comparison.md`` / ``data_status.json``.

    Either pass an already loaded *bundle* (used by ``u_opt_plots --report``)
    or a *data_dir* (a fresh load happens here).
    """
    if bundle is None:
        bundle = PLOTS.build_bundle(data_dir=data_dir, out_dir=out_dir,
                                    smoke=smoke)
    out = Path(out_dir) if out_dir is not None else Path(bundle.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_text, comparison_text, data_status = build_report(bundle, out)
    report_path = out / 'report.md'
    comparison_path = out / 'comparison.md'
    status_path = out / DATA_STATUS_NAME
    report_path.write_text(report_text, encoding='utf-8')
    comparison_path.write_text(comparison_text, encoding='utf-8')
    status_path.write_text(json.dumps(data_status, ensure_ascii=False, indent=1),
                           encoding='utf-8')
    return [PLOTS.relpath(report_path), PLOTS.relpath(comparison_path),
            PLOTS.relpath(status_path)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m four_side_1024.manual_c4_adapt.u_opt_report',
        description='Chinese report/comparison for the U-depth joint '
                    'optimization experiment (reads existing artefacts only).')
    parser.add_argument('--data-dir', type=str, default=None,
                        help='experiment directory '
                             '(default: outputs/.../U_DEPTH_TRANSITION_JOINT_OPT)')
    parser.add_argument('--out-dir', type=str, default=None,
                        help='output directory (default: --data-dir, or '
                             'scratch/uopt_viz/smoke with --smoke)')
    parser.add_argument('--smoke', action='store_true',
                        help='use the frozen 20L checkpoint as baseline '
                             '(A/B data are marked missing)')
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    PLOTS._configure_console_encoding()
    args = parse_args(argv)
    data_dir = (Path(args.data_dir) if args.data_dir
                else (PLOTS.SMOKE_BASE_DIR if args.smoke
                      else PLOTS.DEFAULT_DATA_DIR))
    out_dir = Path(args.out_dir) if args.out_dir else (
        PLOTS.DEFAULT_SMOKE_OUT if args.smoke else data_dir)
    bundle = PLOTS.build_bundle(data_dir, out_dir, smoke=args.smoke)
    files = write_reports(bundle=bundle, out_dir=out_dir)
    if not args.quiet:
        print(f'[report] mode={"smoke" if args.smoke else "production"} '
              f'data_dir={PLOTS.relpath(bundle.data_dir)}')
        missing = bundle.missing_inputs()
        print(f'[report] 缺失输入 {len(missing)} 个（已在报告中标记）')
        for name in files:
            print(f'[report] written: {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
