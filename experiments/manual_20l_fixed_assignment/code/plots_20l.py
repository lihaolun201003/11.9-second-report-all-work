# -*- coding: utf-8 -*-
"""Per-layer + thematic figures for the L1-L20 fixed-assignment experiment.

The module reads the same JSON artefacts as :mod:`report_20l` (never invents
numbers) and renders deterministic PNG figures:

per-layer (``plots/per_layer/``)
    L1 z1 row, L1 z2 row (Z2 interface) and L2..L20 (empty layers such as the
    reserved L6 are rendered explicitly with a ``0 routes`` label), plus a
    contact-sheet montage of every layer.

thematic (``plots/thematic/``)
    Z1 256 manual-U overview, L2-L5 manual-U comparison, L7 NS overview,
    L8 EW overview, Z2 L9-L20 per-layer summary, Z2 interface residual,
    full 1024-channel 3D view, 3D zoom on real transitions, per-layer route
    count bar chart, per-layer crossing count bar chart and the old-vs-new
    crossing comparison chart.

It also writes ``plots/manifest.json`` and (unless ``--no-report``) calls
:func:`report_20l.write_reports` so ``report.md`` / ``comparison.md`` always
describe the figures that actually exist.

CLI::

    python -m four_side_1024.manual_c4_adapt.plots_20l \
        --out-dir outputs/manual_c4_new_connectivity/MANUAL_20L_FIXED_ASSIGNMENT_FULL

Smoke test on the existing 15L fixture (writes only to ``scratch/viz``)::

    python -m four_side_1024.manual_c4_adapt.plots_20l --smoke \
        --data-dir outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_MANUAL_FIRST_FULL \
        --out-dir scratch/viz/smoke_15L

Missing artefacts are tolerated: a figure that cannot be rendered is skipped
with a recorded caveat instead of crashing the whole run (use ``--strict`` to
turn that off while developing).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402

from . import report_20l as REPORT  # noqa: E402

SCHEMA = 'manual_20l_plots_v1'
PROJECT_ROOT = REPORT.PROJECT_ROOT
BOARD_MM = REPORT.BOARD_MM
RADIAL_ORDER = ('N', 'S', 'E', 'W')

#: Chinese-capable font candidates, first available wins (graceful fallback)
FONT_CANDIDATES = ('Microsoft YaHei', 'SimHei', 'Noto Sans SC',
                   'Source Han Sans SC', 'FangSong', 'KaiTi', 'DejaVu Sans')

CATEGORY_COLORS = {
    'manual_u': '#e07b1a',
    'z1_opposite_ns': '#1f6fd6',
    'z1_opposite_ew': '#0c8599',
    'z2_fixed': '#7048e8',
    'z2_interface': '#f76707',
    'same': '#e07b1a',
    'opposite': '#1f6fd6',
    'adjacent': '#2f9e44',
    'unknown': '#495057',
}
CATEGORY_ZH = dict(REPORT.CATEGORY_LABELS_ZH)
SIDE_COLORS = {'N': '#1f6fd6', 'S': '#e03131', 'E': '#2f9e44',
               'W': '#e07b1a', '': '#495057'}
MANUAL_LAYER_COLORS = {2: '#e07b1a', 3: '#f08c00', 4: '#1f6fd6', 5: '#0c8599'}
LAYER_LINE_COLORS = ('#1f6fd6', '#0c8599', '#2f9e44', '#e07b1a', '#7048e8',
                     '#e03131', '#f08c00', '#495057')
RUN_COLORS = {'baseline': '#868e96', 'previous': '#e07b1a', 'new': '#1f6fd6'}

BASE_DPI = dict(per_layer=150, contact=110, thematic=140, three_d=130)


# ---------------------------------------------------------------------------
# fonts / style
# ---------------------------------------------------------------------------
def configure_fonts():
    """Pick a CJK-capable font (fallback to DejaVu Sans) and set rcParams."""
    from matplotlib import font_manager
    try:
        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:  # noqa: BLE001 - font cache problems must not kill plots
        available = set()
    picked = [name for name in FONT_CANDIDATES if name in available]
    if not picked:
        picked = ['DejaVu Sans']
    plt.rcParams['font.sans-serif'] = picked + ['DejaVu Sans']
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams.update({
        'font.size': 8.0,
        'axes.titlesize': 8.5,
        'axes.labelsize': 7.5,
        'xtick.labelsize': 6.5,
        'ytick.labelsize': 6.5,
        'legend.fontsize': 6.5,
        'figure.max_open_warning': 0,
        'savefig.facecolor': 'white',
    })
    return picked


CHOSEN_FONTS = configure_fonts()


def has_cjk_font():
    return any(name != 'DejaVu Sans' for name in CHOSEN_FONTS)


# ---------------------------------------------------------------------------
# geometry sampling
# ---------------------------------------------------------------------------
def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sample_primitive(primitive, arc_step_deg=4.0):
    """Polyline ``(n, 2)`` of one stored 2D primitive (line / arc)."""
    kind = primitive.get('kind')
    if kind == 'arc':
        center = primitive.get('center')
        radius = _as_float(primitive.get('radius'))
        start = _as_float(primitive.get('start_angle'))
        sweep = _as_float(primitive.get('sweep'))
        if center is not None and radius is not None and start is not None \
                and sweep is not None:
            step = math.radians(max(arc_step_deg, 0.5))
            count = max(2, int(math.ceil(abs(sweep) / step)) + 1)
            angles = start + sweep * np.linspace(0.0, 1.0, count)
            return np.column_stack([
                float(center[0]) + radius * np.cos(angles),
                float(center[1]) + radius * np.sin(angles)])
    p0 = primitive.get('p0')
    p1 = primitive.get('p1')
    if p0 is None or p1 is None:
        return None
    return np.asarray([[float(p0[0]), float(p0[1])],
                       [float(p1[0]), float(p1[1])]], dtype=float)


def transition_curve(part, step_mm=0.10):
    """3D ``(n, 3)`` samples of one stored S transition (schema L3D)."""
    start = part.get('start')
    direction = part.get('direction')
    z0 = _as_float(part.get('z0'))
    z1 = _as_float(part.get('z1'))
    radius = _as_float(part.get('radius_mm'))
    if start is None or direction is None or z0 is None or z1 is None:
        return None
    radius = radius if radius and radius > 1e-9 else 15.0
    theta = _as_float(part.get('theta_rad'))
    dz = z1 - z0
    if theta is None or theta <= 0.0:
        ratio = 1.0 - abs(dz) / (2.0 * radius)
        ratio = max(-1.0, min(1.0, ratio))
        theta = math.acos(ratio)
    if theta <= 0.0:
        footprint = _as_float(part.get('footprint_mm')) or 0.0
        norm = math.hypot(direction[0], direction[1]) or 1.0
        end = (float(start[0]) + direction[0] / norm * footprint,
               float(start[1]) + direction[1] / norm * footprint)
        return np.asarray([[float(start[0]), float(start[1]), z0],
                           [end[0], end[1], z1]])
    footprint = _as_float(part.get('footprint_mm'))
    if footprint is None:
        footprint = 2.0 * radius * math.sin(theta)
    sign = 1.0 if dz >= 0.0 else -1.0
    norm = math.hypot(direction[0], direction[1]) or 1.0
    unit = (float(direction[0]) / norm, float(direction[1]) / norm)
    arc_length = 2.0 * radius * theta
    count = max(2, int(math.ceil(arc_length / max(step_mm, 1e-6))))
    phase = np.linspace(0.0, 2.0 * theta, count + 1)
    first = phase <= theta
    u = np.where(first, radius * np.sin(phase),
                 footprint - radius * np.sin(2.0 * theta - phase))
    w = np.where(first, z0 + sign * radius * (1.0 - np.cos(phase)),
                 z1 - sign * radius * (1.0 - np.cos(2.0 * theta - phase)))
    return np.column_stack([
        float(start[0]) + u * unit[0],
        float(start[1]) + u * unit[1],
        w,
    ])


def _transition_endpoints(part):
    """``(start_xy, end_xy)`` of one transition, from its stored fields."""
    start = part.get('start')
    if start is None:
        return None
    start_xy = (float(start[0]), float(start[1]))
    direction = part.get('direction')
    footprint = _as_float(part.get('footprint_mm'))
    radius = _as_float(part.get('radius_mm')) or 15.0
    z0, z1 = _as_float(part.get('z0')), _as_float(part.get('z1'))
    if footprint is None and z0 is not None and z1 is not None:
        theta = _as_float(part.get('theta_rad'))
        if theta is None:
            ratio = max(-1.0, min(1.0, 1.0 - abs(z1 - z0) / (2.0 * radius)))
            theta = math.acos(ratio)
        footprint = 2.0 * radius * math.sin(theta)
    if direction is not None and footprint is not None:
        norm = math.hypot(direction[0], direction[1]) or 1.0
        end_xy = (start_xy[0] + direction[0] / norm * footprint,
                  start_xy[1] + direction[1] / norm * footprint)
        return start_xy, end_xy
    end = part.get('end')
    if end is not None:
        return start_xy, (float(end[0]), float(end[1]))
    return None


# ---------------------------------------------------------------------------
# experiment caches
# ---------------------------------------------------------------------------
def route_category(exp, rid):
    cache = exp.get('_categories')
    if cache is not None:
        return cache.get(rid, 'unknown')
    return _compute_category(exp, rid)


def _compute_category(exp, rid):
    assignment = exp.get('assignment')
    if assignment is not None:
        row = assignment['by_id'].get(rid)
        if row is not None:
            return str(row.get('kind') or 'unknown')
    info = exp['route_info'].get(rid)
    if info is None:
        return 'unknown'
    plane = info['plane']
    relation = info['relation']
    high = set(info.get('high_layers') or [])
    if plane == 'z1' and relation == 'same' and high \
            and high <= set(REPORT.MANUAL_LAYERS_20L):
        return 'manual_u'
    if plane == 'z1' and relation == 'opposite' and high == {7}:
        return 'z1_opposite_ns'
    if plane == 'z1' and relation == 'opposite' and high == {8}:
        return 'z1_opposite_ew'
    if plane == 'z2' and high:
        return 'z2_fixed'
    if plane == 'z2' and not high:
        return 'z2_interface'
    return relation


def manual_route_ids(exp):
    """Route ids of the Z1 manual same-side U's (assignment or heuristic)."""
    if exp.get('_manual_ids') is not None:
        return exp['_manual_ids']
    assignment = exp.get('assignment')
    ids = []
    if assignment is not None:
        for rid, row in assignment['by_id'].items():
            if str(row.get('kind')) == 'manual_u':
                ids.append(int(rid))
    else:
        for rid, info in exp['route_info'].items():
            if info['plane'] != 'z1' or info['relation'] != 'same':
                continue
            high = set(info.get('high_layers') or [])
            if high and high <= set(REPORT.MANUAL_LAYERS_20L):
                ids.append(int(rid))
    exp['_manual_ids'] = sorted(ids)
    return exp['_manual_ids']


def prepare_geometry(exp):
    """Cache sampled polylines / transition geometry / categories on ``exp``."""
    if exp.get('_prepared'):
        return exp
    exp['_curve_cache'] = {}
    exp['_categories'] = {rid: _compute_category(exp, rid)
                          for rid in exp['route_info']}
    for entries in exp['data']['flat_by_layer'].values():
        for entry in entries:
            polylines = []
            for primitive in entry.get('primitives') or []:
                polyline = sample_primitive(primitive)
                if polyline is not None and len(polyline) >= 2:
                    polylines.append(polyline)
            entry['polylines'] = polylines
    transitions = []
    for item in exp['data']['transitions']:
        endpoints = _transition_endpoints(item['part'])
        transitions.append(dict(
            rid=item['rid'], plane=item['plane'], from_layer=item['from_layer'],
            to_layer=item['to_layer'],
            z0=_as_float(item['part'].get('z0')),
            z1=_as_float(item['part'].get('z1')),
            start_xy=endpoints[0] if endpoints else None,
            end_xy=endpoints[1] if endpoints else None,
            part=item['part'],
        ))
    exp['_transition_geom'] = transitions
    transitions_by_rid = defaultdict(list)
    for item in transitions:
        transitions_by_rid[item['rid']].append(item)
    exp['_transitions_by_rid'] = dict(transitions_by_rid)
    exp['_rows_by_key'] = {row['key']: row for row in exp['per_layer']}
    exp['_manual_ids'] = None
    exp['_prepared'] = True
    return exp


def curve_for(exp, part, step_mm=0.10):
    """Cached transition curve (one S-curve is used by several figures)."""
    cache = exp.setdefault('_curve_cache', {})
    key = (id(part), round(float(step_mm), 4))
    if key not in cache:
        cache[key] = transition_curve(part, step_mm=step_mm)
    return cache[key]


# ---------------------------------------------------------------------------
# figure helpers
# ---------------------------------------------------------------------------
def _relative(path, out_dir):
    path = Path(path)
    try:
        return path.resolve().relative_to(Path(out_dir).resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _save(fig, path, dpi):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path


def _setup_board(ax, *, title_fontsize=8.0, tick_fontsize=6.0):
    ax.add_patch(Rectangle((0.0, 0.0), BOARD_MM, BOARD_MM, fill=False,
                           linewidth=0.9, color='#343a40', zorder=6))
    ax.set_xlim(-3.0, BOARD_MM + 3.0)
    ax.set_ylim(-3.0, BOARD_MM + 3.0)
    ax.set_aspect('equal')
    ax.grid(alpha=0.12, linewidth=0.35)
    ax.tick_params(labelsize=tick_fontsize)
    ax.set_xlabel('x (mm)', fontsize=title_fontsize - 1.0)
    ax.set_ylabel('y (mm)', fontsize=title_fontsize - 1.0)


def _plane_entries(exp, spec):
    flat = exp['data']['flat_by_layer']
    if spec['kind'] == 'interface':
        return [entry for entry in flat.get(1, [])
                if entry.get('z_mm') is not None
                and abs(float(entry['z_mm']) - spec['z']) <= 1e-6]
    return flat.get(spec['layer'], [])


def _context_entries(exp, spec):
    """Interface rows shown as grey context on routing-layer panels."""
    flat = exp['data']['flat_by_layer']
    if spec['kind'] == 'interface':
        return [entry for entry in flat.get(1, [])
                if entry.get('z_mm') is not None
                and abs(float(entry['z_mm']) - spec['z']) > 1e-6]
    return flat.get(1, [])


def draw_route_polylines(ax, exp, route_ids, entries, *, colors=None,
                         color_by='category', linewidth=0.85, alpha=0.9,
                         zorder=3):
    """Draw the flat polylines of the given routes, coloured by category/side."""
    groups = defaultdict(list)
    wanted = None if route_ids is None else set(route_ids)
    for entry in entries:
        if wanted is not None and entry['rid'] not in wanted:
            continue
        if color_by == 'category':
            key = route_category(exp, entry['rid'])
        elif color_by == 'side':
            info = exp['route_info'].get(entry['rid']) or {}
            key = str(info.get('source_side') or '')
        elif color_by == 'layer':
            key = entry.get('layer_id')
        else:
            key = 'unknown'
        for polyline in entry.get('polylines') or []:
            groups[key].append(polyline)
    handles = []
    for key, polylines in groups.items():
        if colors is not None and isinstance(colors, dict):
            color = colors.get(key, '#495057')
        else:
            color = CATEGORY_COLORS.get(str(key), '#495057')
        label = CATEGORY_ZH.get(str(key), f'侧面 {key}' if color_by == 'side'
                                else f'层 {key}' if color_by == 'layer'
                                else str(key))
        ax.add_collection(LineCollection(
            polylines, colors=color, linewidths=linewidth, alpha=alpha,
            zorder=zorder, label=label))
        handles.append(Line2D([0], [0], color=color, linewidth=1.5,
                              label=label))
    return handles


def _draw_transition_markers(ax, exp, spec, *, size=6.0):
    points = []
    for item in exp['_transition_geom']:
        for z_value, xy in ((item['z0'], item['start_xy']),
                            (item['z1'], item['end_xy'])):
            if z_value is None or xy is None:
                continue
            if abs(float(z_value) - spec['z']) <= 1e-6:
                points.append(xy)
    if not points:
        return 0
    array = np.asarray(points)
    ax.scatter(array[:, 0], array[:, 1], s=size, c='#e03131', alpha=0.75,
               zorder=5, label='升降段端点')
    return len(points)


def _assigned_text(exp, spec, row):
    """Label for the assignment count (interface rows: plane total)."""
    if row.get('assigned') is None:
        return None
    if spec['kind'] == 'interface':
        return f"分配平面 {row['assigned']}"
    return f"分配 {row['assigned']}"


def _crossings_text(row):
    """Crossing count for titles; em dash when crossings_after.json is absent."""
    value = row.get('crossings_pairs')
    return '—' if value is None else str(value)


def _plane_title(exp, spec):
    row = exp['_rows_by_key'].get(spec['key'], {})
    parts = [f"{spec['label']}  z={spec['z']:.3f} mm",
             f"{row.get('routes', 0)} 条线路"]
    assigned_text = _assigned_text(exp, spec, row)
    if assigned_text:
        parts.append(assigned_text)
    if row.get('crossings_pairs') is not None:
        parts.append(f"交叉 {row['crossings_pairs']}")
    title = ' | '.join(parts)
    notes = []
    if row.get('reserved'):
        notes.append('L6 保留层（无新布线）')
    if row.get('empty'):
        notes.append('0 routes（空层）')
    if notes:
        title += '\n' + '；'.join(notes)
    return title


def draw_plane_panel(ax, exp, spec, *, context=True, linewidth=0.85,
                     fontsize=8.0, tick_fontsize=6.0, show_legend=False,
                     markers=True):
    """Draw one physical layer plane on ``ax`` and return its info dict."""
    _setup_board(ax, title_fontsize=fontsize, tick_fontsize=tick_fontsize)
    entries = _plane_entries(exp, spec)
    if context:
        context_entries = _context_entries(exp, spec)
        context_polylines = [polyline for entry in context_entries
                             for polyline in entry.get('polylines') or []]
        if context_polylines:
            ax.add_collection(LineCollection(
                context_polylines, colors='#adb5bd', linewidths=0.14,
                alpha=0.10, zorder=1))
    handles = draw_route_polylines(ax, exp, None, entries,
                                   linewidth=linewidth, alpha=0.9)
    marker_count = 0
    if markers:
        marker_count = _draw_transition_markers(ax, exp, spec)
    if not entries:
        ax.text(0.5, 0.5, '0 routes\n（本层无布线）', transform=ax.transAxes,
                ha='center', va='center', fontsize=10.0, color='#868e96',
                bbox=dict(boxstyle='round,pad=0.45', facecolor='white',
                          alpha=0.92, edgecolor='#ced4da'))
    ax.set_title(_plane_title(exp, spec), fontsize=fontsize)
    if show_legend and handles:
        ax.legend(handles=handles + (
            [Line2D([0], [0], marker='o', color='none',
                    markerfacecolor='#e03131', markersize=4,
                    label='升降段端点')] if marker_count else []),
            loc='upper left', fontsize=5.8, framealpha=0.88)
    row = exp['_rows_by_key'].get(spec['key'], {})
    return dict(key=spec['key'], entries=len(entries),
                routes=row.get('routes', 0), markers=marker_count)


# ---------------------------------------------------------------------------
# per-layer figures + contact sheet
# ---------------------------------------------------------------------------
def render_per_layer(exp, out_dir, dpi, caveats):
    per_dir = Path(out_dir) / 'plots' / 'per_layer'
    per_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    for spec in exp['planes']:
        fig, ax = plt.subplots(figsize=(6.2, 6.0))
        info = draw_plane_panel(ax, exp, spec, context=True, linewidth=0.80,
                                fontsize=8.5, tick_fontsize=6.0,
                                show_legend=spec['kind'] == 'interface')
        safe_key = spec['key'].replace('-', '_')
        path = per_dir / f'{safe_key}.png'
        _save(fig, path, dpi)
        row = exp['_rows_by_key'].get(spec['key'], {})
        title_zh = (f"{spec['label']} 平面布线图（z={spec['z']:.3f} mm）"
                    f"{'，空层 0 条' if row.get('empty') else ''}"
                    f"{'，保留层' if row.get('reserved') else ''}")
        assigned_text = _assigned_text(exp, spec, row)
        figures.append(dict(
            file=_relative(path, out_dir), group='per_layer', key=spec['key'],
            title_zh=title_zh, title_en=f"{spec['short']} layer map",
            description=(f"{spec['label']} z={spec['z']:.3f} mm："
                         f"{row.get('routes', 0)} 条线路"
                         + (f"，{assigned_text}" if assigned_text else '')
                         + (f"，唯一交叉对 {row['crossings_pairs']}" if row.get('crossings_pairs') is not None else '')
                         + ('（空层，显式标注 0 routes）' if row.get('empty') else '')),
            routes=row.get('routes', 0),
            empty=bool(row.get('empty')),
            reserved=bool(row.get('reserved')),
        ))
    return figures


def render_contact_sheet(exp, out_dir, dpi, caveats):
    specs = list(exp['planes'])
    columns = 4
    rows = max(1, int(math.ceil(len(specs) / float(columns))))
    fig, axes = plt.subplots(rows, columns,
                             figsize=(4.35 * columns, 3.95 * rows))
    axes = np.atleast_2d(axes)
    for index, spec in enumerate(specs):
        ax = axes.ravel()[index]
        draw_plane_panel(ax, exp, spec, context=False, linewidth=0.5,
                         fontsize=6.8, tick_fontsize=4.8, show_legend=False,
                         markers=True)
        row = exp['_rows_by_key'].get(spec['key'], {})
        flags = []
        if row.get('reserved'):
            flags.append('保留层')
        if row.get('empty') and not row.get('reserved'):
            flags.append('0 routes')
        suffix = (' | ' + '、'.join(flags)) if flags else ''
        ax.set_title(f"{spec['short']}  z={spec['z']:.3f} mm\n"
                     f"{row.get('routes', 0)} 条线路"
                     f" | 交叉 {_crossings_text(row)}{suffix}",
                     fontsize=6.6)
        ax.tick_params(labelsize=4.6)
        ax.set_xlabel('')
        ax.set_ylabel('')
    for index in range(len(specs), axes.size):
        axes.ravel()[index].axis('off')
    model = exp['layer_model']
    fig.suptitle(
        'L1–L20 固定人工分配实验：全部物理层平面布线总览\n'
        f"层模型：L1 双接口行 z1={model['interface']['z1']:.3f} / "
        f"z2={model['interface']['z2']:.3f} mm；L2={model['routing'].get(2, 0.0):.3f} mm "
        f"起，0.150 mm 步距；共 {len(specs)} 个物理层；空层显式标注 0 routes"
        '（灰色为接口平面上下文，红点为升降段端点）',
        fontsize=10.0, y=0.995)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
    path = Path(out_dir) / 'plots' / 'layer_contact_sheet.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='overview',
                 key='contact_sheet',
                 title_zh='全部物理层布线总览（接触表）',
                 title_en='all-layer contact sheet',
                 description=(f'{len(specs)} 个物理层平面拼接总览；'
                              '每个子图为该层平面布线图，空层标注 0 routes'),
                 routes=None)]


# ---------------------------------------------------------------------------
# thematic: manual U
# ---------------------------------------------------------------------------
def _per_layer_counts(route_ids, exp):
    counter = Counter()
    for rid in route_ids:
        for entry in exp['data']['entries_by_route'].get(rid, []):
            if int(entry['layer_id']) != 1:
                counter[int(entry['layer_id'])] += 1
    return counter


def _route_geometry(exp, route_ids, layers=None):
    """Flat entries belonging to the given routes, optionally on given layers."""
    entries = []
    for rid in route_ids:
        for entry in exp['data']['entries_by_route'].get(rid, []):
            layer = int(entry['layer_id'])
            if layers is not None and layer not in layers:
                continue
            entries.append(entry)
    return entries


def _manual_target_layers(exp):
    """Manual-U target layers: from the assignment when available."""
    assignment = exp.get('assignment')
    layers = set()
    if assignment is not None:
        for row in assignment['by_id'].values():
            if str(row.get('kind')) == 'manual_u':
                layer = _as_int(row.get('layer'))
                if layer is not None:
                    layers.add(layer)
    if not layers:
        layers = set(REPORT.MANUAL_LAYERS_20L)
    return sorted(layers)


def render_manual_u_overview(exp, out_dir, dpi, caveats):
    ids = manual_route_ids(exp)
    manual = exp['manual']
    counts = _per_layer_counts(ids, exp)
    expected = manual.get('expected')
    manual_layers = _manual_target_layers(exp)
    fig = plt.figure(figsize=(16.4, 9.4))
    grid = fig.add_gridspec(2, len(manual_layers), height_ratios=(1.25, 1.0))
    ax_all = fig.add_subplot(grid[0, :])
    _setup_board(ax_all, title_fontsize=8.5, tick_fontsize=6.0)
    entries_all = _route_geometry(exp, ids, set(manual_layers))
    groups = defaultdict(list)
    for entry in entries_all:
        groups[int(entry['layer_id'])].extend(entry.get('polylines') or [])
    handles = []
    for layer in manual_layers:
        polylines = groups.get(layer) or []
        color = MANUAL_LAYER_COLORS.get(layer, '#495057')
        if polylines:
            ax_all.add_collection(LineCollection(
                polylines, colors=color, linewidths=0.75, alpha=0.85,
                zorder=3, label=f'L{layer}（{counts.get(layer, 0)} 条）'))
        handles.append(Line2D([0], [0], color=color, linewidth=1.8,
                              label=f'L{layer}（{counts.get(layer, 0)} 条）'))
    ax_all.legend(handles=handles, loc='upper right', fontsize=8.0,
                  framealpha=0.9)
    expected_text = (f"目标 {expected} 条" if expected is not None
                     else '目标 256 条（assignment 缺失，启发式识别）')
    ax_all.set_title(
        f'Z1 人工 256 条同侧 U：按目标层着色的总览（识别 {len(ids)} 条 / '
        f'{expected_text}）\n'
        + '，'.join(f'L{layer}={counts.get(layer, 0)} 条'
                   for layer in manual_layers), fontsize=9.0)
    for column, layer in enumerate(manual_layers):
        ax = fig.add_subplot(grid[1, column])
        _setup_board(ax, title_fontsize=7.0, tick_fontsize=5.0)
        layer_entries = _route_geometry(exp, ids, {layer})
        side_handles = draw_route_polylines(
            ax, exp, set(ids), layer_entries, color_by='side',
            colors=SIDE_COLORS, linewidth=0.9, alpha=0.9)
        if side_handles:
            ax.legend(handles=side_handles, loc='upper left', fontsize=5.0,
                      framealpha=0.85)
        else:
            ax.text(0.5, 0.5, '0 条（该层无人工 U）', transform=ax.transAxes,
                    ha='center', va='center', fontsize=7.0, color='#868e96')
        expected_layer = None
        if manual.get('by_layer', {}).get(layer):
            expected_layer = manual['by_layer'][layer].get('assigned')
        title = (f"L{layer}  z={exp['layer_model']['routing'].get(layer, 0.0):.3f} mm"
                 f" | {len(layer_entries)} parts")
        if expected_layer is not None:
            title += f" | 分配 {expected_layer}"
        ax.set_title(title, fontsize=7.2)
        ax.tick_params(labelsize=4.8)
    fig.suptitle('Z1 manual U overview / 人工 U 总览（上：全部 U 按目标层着色；下：逐层按来源侧 N/S/E/W）', fontsize=11.0)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.955))
    path = Path(out_dir) / 'plots' / 'thematic' / '01_z1_manual_u_overview.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    caveat = ''
    if manual.get('heuristic'):
        caveat = '（assignment_1024.json 缺失：启发式识别，接口平面上的 64 条无法区分）'
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='z1_manual_u_overview',
                 title_zh='Z1 人工 256 条同侧 U 总览',
                 title_en='Z1 manual-U overview',
                 description=(f"识别到 {len(ids)} 条人工 U；"
                              + '，'.join(f'L{layer}={counts.get(layer, 0)}'
                                          for layer in manual_layers)
                              + caveat),
                 routes=len(ids))]


def render_manual_u_comparison(exp, out_dir, dpi, caveats):
    ids = set(manual_route_ids(exp))
    manual = exp['manual']
    layers = list(REPORT.MANUAL_LAYERS_20L)
    fig, axes = plt.subplots(1, len(layers), figsize=(4.4 * len(layers), 4.9))
    axes = np.atleast_1d(axes)
    summary = []
    for ax, layer in zip(axes, layers):
        _setup_board(ax, title_fontsize=7.2, tick_fontsize=5.0)
        entries = _route_geometry(exp, ids, {layer})
        draw_route_polylines(ax, exp, ids, entries, color_by='side',
                             colors=SIDE_COLORS, linewidth=0.95)
        routed = len({entry['rid'] for entry in entries})
        slot = (manual.get('by_layer') or {}).get(layer) or {}
        assigned = slot.get('assigned')
        title = (f"L{layer}  z={exp['layer_model']['routing'].get(layer, 0.0):.3f} mm\n"
                 f"布通 {routed} 条")
        if assigned is not None:
            title += f" / 分配 {assigned}"
        ax.set_title(title, fontsize=7.4)
        handles = [
            Line2D([0], [0], color=SIDE_COLORS[side], linewidth=1.8,
                   label=f'{side} 侧起')
            for side in RADIAL_ORDER]
        ax.legend(handles=handles, loc='upper left', fontsize=5.4,
                  framealpha=0.85)
        ax.tick_params(labelsize=4.8)
        summary.append(routed)
    fig.suptitle('L2–L5 人工 U 分层对比：每层平面 U 按起点侧着色\n'
                 '（左到右 L2=0.650 mm, L3=0.800 mm, L4=0.950 mm, L5=1.100 mm）',
                 fontsize=11.0)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    path = Path(out_dir) / 'plots' / 'thematic' / '02_l2_l5_manual_u_comparison.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='l2_l5_manual_u_comparison',
                 title_zh='L2–L5 人工 U 分层对比',
                 title_en='L2-L5 manual-U comparison',
                 description=('四个 0.150 mm 间距的人工 U 层逐层对比：'
                              + '，'.join(f'L{layer} 布通 {routed}'
                                          for layer, routed in zip(layers, summary))),
                 routes=sum(summary))]


# ---------------------------------------------------------------------------
# thematic: Z1 opposite layers L7 / L8
# ---------------------------------------------------------------------------
def render_opposite_overview(exp, out_dir, dpi, layer, index, caveats):
    spec = None
    for candidate in exp['planes']:
        if candidate['kind'] == 'routing' and candidate['layer'] == layer:
            spec = candidate
            break
    if spec is None:
        caveats.append(f'L{layer} 不在层模型中，跳过对应总览图')
        return []
    entries = _plane_entries(exp, spec)
    row = exp['_rows_by_key'].get(spec['key'], {})
    fig, ax = plt.subplots(figsize=(8.4, 7.6))
    _setup_board(ax, title_fontsize=9.0, tick_fontsize=6.0)
    context_entries = _context_entries(exp, spec)
    ax.add_collection(LineCollection(
        [polyline for entry in context_entries
         for polyline in entry.get('polylines') or []],
        colors='#adb5bd', linewidths=0.12, alpha=0.08, zorder=1))
    handles = draw_route_polylines(ax, exp, None, entries, color_by='side',
                                   colors=SIDE_COLORS, linewidth=1.0)
    marker_count = _draw_transition_markers(ax, exp, spec, size=7.0)
    if marker_count:
        handles.append(Line2D([0], [0], marker='o', color='none',
                              markerfacecolor='#e03131', markersize=4,
                              label='升降段端点'))
    ax.legend(handles=handles, loc='upper right', fontsize=7.5,
              framealpha=0.9)
    opposite = '南北（N-S）' if layer == 7 else '东西（E-W）'
    title = (f"Z1 {opposite} 对穿连接总览 — L{layer} z={spec['z']:.3f} mm\n"
             f"{row.get('routes', 0)} 条线路")
    if row.get('assigned') is not None:
        title += f" / 分配 {row['assigned']}"
    title += (f" | 逐层唯一交叉对 {_crossings_text(row)}"
              f" | 升降段端点 {marker_count}")
    ax.set_title(title, fontsize=9.5)
    fig.tight_layout()
    filename = (f'{index:02d}_l7_ns_overview.png' if layer == 7
                else f'{index:02d}_l8_ew_overview.png')
    path = Path(out_dir) / 'plots' / 'thematic' / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    title_zh = ('L7 128 条南北对穿总览' if layer == 7
                else 'L8 128 条东西对穿总览')
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key=f'l{layer}_opposite_overview',
                 title_zh=title_zh,
                 title_en=f'L{layer} opposite overview',
                 description=(f"L{layer} z={spec['z']:.3f} mm："
                              f"{row.get('routes', 0)} 条线路"
                              + (f"，分配 {row['assigned']}" if row.get('assigned') is not None else '')
                              + f"，交叉 {_crossings_text(row)}"),
                 routes=row.get('routes', 0))]


# ---------------------------------------------------------------------------
# thematic: Z2 high layers L9-L20 + interface residual
# ---------------------------------------------------------------------------
def render_z2_high_summary(exp, out_dir, dpi, caveats):
    specs = [spec for spec in exp['planes']
             if spec['kind'] == 'routing' and spec['layer'] >= 9]
    if not specs:
        caveats.append('层模型中没有 L9–L20，跳过 Z2 高层分层总览图')
        return []
    columns = 3
    rows = int(math.ceil(len(specs) / float(columns)))
    fig, axes = plt.subplots(rows, columns,
                             figsize=(4.6 * columns, 4.2 * rows))
    axes = np.atleast_2d(axes)
    total_routes = 0
    for index, spec in enumerate(specs):
        ax = axes.ravel()[index]
        _setup_board(ax, title_fontsize=6.8, tick_fontsize=4.8)
        entries = _plane_entries(exp, spec)
        draw_route_polylines(ax, exp, None, entries, color_by='side',
                             colors=SIDE_COLORS, linewidth=0.75)
        _draw_transition_markers(ax, exp, spec, size=4.0)
        row = exp['_rows_by_key'].get(spec['key'], {})
        total_routes += row.get('routes', 0) or 0
        title = (f"L{spec['layer']}  z={spec['z']:.3f} mm\n"
                 f"{row.get('routes', 0)} 条")
        if row.get('assigned') is not None:
            title += f" / 分配 {row['assigned']}"
        title += f" | 交叉 {_crossings_text(row)}"
        ax.set_title(title, fontsize=6.8)
        ax.tick_params(labelsize=4.6)
        ax.set_xlabel('')
        ax.set_ylabel('')
        if not entries:
            ax.text(0.5, 0.5, '0 routes', transform=ax.transAxes,
                    ha='center', va='center', fontsize=8.0, color='#868e96')
    for index in range(len(specs), axes.size):
        axes.ravel()[index].axis('off')
    fig.suptitle('Z2 高层分配逐层总览（L9–L20）：每层平面布线，颜色按起点侧\n'
                 f'合计 {total_routes} 条 Z2 高层线路', fontsize=10.0, y=0.995)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.925))
    path = Path(out_dir) / 'plots' / 'thematic' / '05_z2_l9_l20_summary.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='z2_l9_l20_summary',
                 title_zh='Z2 L9–L20 逐层总览',
                 title_en='Z2 L9-L20 per-layer summary',
                 description=(f"{len(specs)} 个 Z2 高层逐层平面图，"
                              f"合计 {total_routes} 条高层线路"),
                 routes=total_routes)]


def render_z2_interface_residual(exp, out_dir, dpi, caveats):
    interface_specs = [spec for spec in exp['planes']
                       if spec['kind'] == 'interface' and spec['plane'] == 'z2']
    if not interface_specs:
        caveats.append('层模型中没有 Z2 接口行，跳过接口残余图')
        return []
    spec = interface_specs[0]
    residual = exp['z2_residual']
    residual_ids = set(residual.get('residual_ids') or [])
    entries = _plane_entries(exp, spec)
    residual_entries = [entry for entry in entries
                        if entry['rid'] in residual_ids]
    lifted_entries = [entry for entry in entries
                      if entry['rid'] not in residual_ids]
    fig, ax = plt.subplots(figsize=(9.6, 8.4))
    _setup_board(ax, title_fontsize=9.0, tick_fontsize=6.0)
    lifted_ids = {entry['rid'] for entry in lifted_entries}
    residual_ids_drawn = {entry['rid'] for entry in residual_entries}
    if lifted_entries:
        ax.add_collection(LineCollection(
            [polyline for entry in lifted_entries
             for polyline in entry.get('polylines') or []],
            colors='#1f6fd6', linewidths=0.70, alpha=0.70, zorder=3))
    if residual_entries:
        ax.add_collection(LineCollection(
            [polyline for entry in residual_entries
             for polyline in entry.get('polylines') or []],
            colors='#e8590c', linewidths=0.50, alpha=0.80, zorder=4))
    marker_count = _draw_transition_markers(ax, exp, spec, size=6.0)
    handles = [
        Line2D([0], [0], color='#1f6fd6', linewidth=1.8,
               label=f'已抬升线路的接口段（{len(lifted_ids)} 条线路）'),
        Line2D([0], [0], color='#e8590c', linewidth=1.8,
               label=f'接口残余（{len(residual_ids_drawn)} 条线路）'),
    ]
    if marker_count:
        handles.append(Line2D([0], [0], marker='o', color='none',
                              markerfacecolor='#e03131', markersize=4,
                              label=f'升降段端点（{marker_count} 个）'))
    ax.legend(handles=handles, loc='upper right', fontsize=7.5, framealpha=0.9)
    expected = residual.get('expected_residual')
    title = (f"Z2 接口残余总览 — L1 z2 行 z={spec['z']:.3f} mm\n"
             f"Z2 布通 {residual.get('total', 0)} 条 = 抬升 {residual.get('lifted', 0)}"
             f" + 接口残余 {residual.get('residual', 0)} 条")
    if expected is not None:
        title += f"（固定分配目标残余 {expected} 条）"
    title += f" | 升降段端点 {marker_count}"
    ax.set_title(title, fontsize=9.5)
    fig.tight_layout()
    path = (Path(out_dir) / 'plots' / 'thematic'
            / '06_z2_interface_residual.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    text = (f"Z2 布通 {residual.get('total', 0)} 条；抬升 {residual.get('lifted', 0)} 条；"
            f"接口残余 {residual.get('residual', 0)} 条")
    if expected is not None:
        text += f"；分配目标残余 {expected} 条"
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='z2_interface_residual',
                 title_zh='Z2 接口残余总览',
                 title_en='Z2 interface residual',
                 description=text,
                 routes=residual.get('total', 0))]


# ---------------------------------------------------------------------------
# thematic: 3D views
# ---------------------------------------------------------------------------
def _flat_segments(exp, entries):
    chunks = []
    for entry in entries:
        z_mm = entry.get('z_mm')
        if z_mm is None:
            continue
        for polyline in entry.get('polylines') or []:
            points = np.column_stack(
                [polyline, np.full(len(polyline), float(z_mm))])
            if len(points) >= 2:
                chunks.append(np.stack([points[:-1], points[1:]], axis=1))
    return chunks


def route_segments_3d(exp, record, transition_step=0.14):
    rid = _as_int(record.get('route_id'))
    if rid is None:
        return None
    chunks = _flat_segments(exp, exp['data']['entries_by_route'].get(rid, []))
    for item in exp['_transitions_by_rid'].get(rid, []):
        curve = curve_for(exp, item['part'], step_mm=transition_step)
        if curve is not None and len(curve) >= 2:
            chunks.append(np.stack([curve[:-1], curve[1:]], axis=1))
    if not chunks:
        return None
    return np.concatenate(chunks, axis=0)


def _setup_3d_axes(ax, model, *, xlim=(-5.0, 155.0), ylim=(-5.0, 155.0),
                   z_aspect=0.55, elev=28.0, azim=-58.0):
    heights = list(model['routing'].values()) if model.get('routing') else [0.0]
    z_lo = min([model['interface']['z1'], model['interface']['z2']] + heights)
    z_hi = max([model['interface']['z1'], model['interface']['z2']] + heights)
    pad = 0.10 * (z_hi - z_lo) if z_hi > z_lo else 0.1
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_zlim(z_lo - pad, z_hi + pad)
    ax.set_box_aspect((1.0, 1.0, z_aspect))
    ax.set_xlabel('x (mm)', fontsize=7.0)
    ax.set_ylabel('y (mm)', fontsize=7.0)
    ax.set_zlabel('physical z (mm)', fontsize=7.0)
    ax.tick_params(labelsize=5.0)
    ax.view_init(elev=elev, azim=azim)
    return z_lo, z_hi


def _board_3d_frame(ax, z_value, color='#343a40', linewidth=0.9):
    xs = [0.0, BOARD_MM, BOARD_MM, 0.0, 0.0]
    ys = [0.0, 0.0, BOARD_MM, BOARD_MM, 0.0]
    ax.plot(xs, ys, [z_value] * len(xs), color=color, linewidth=linewidth,
            alpha=0.85)


def render_full_3d(exp, out_dir, dpi, caveats):
    model = exp['layer_model']
    records = [record for record in exp['data']['routed']]
    chunks = []
    for record in records:
        segments = route_segments_3d(exp, record, transition_step=0.16)
        if segments is not None and len(segments):
            chunks.append(segments)
    if not chunks:
        caveats.append('没有可绘制的 3D 路线段，跳过 full_1024_3d 图')
        return []
    segments = np.concatenate(chunks, axis=0)
    mean_z = segments[:, :, 2].mean(axis=1)
    heights = list(model['routing'].values())
    norm = Normalize(vmin=min(heights + [0.0]),
                     vmax=max(heights + [model['interface']['z2']]))
    cmap = plt.get_cmap('plasma')
    colors = cmap(norm(mean_z))
    fig = plt.figure(figsize=(16.0, 9.6))
    ax = fig.add_axes([-0.03, -0.10, 1.03, 1.20], projection='3d')
    ax.add_collection3d(Line3DCollection(
        segments, colors=colors, linewidths=0.28, alpha=0.68))
    for z_value, color in ((model['interface']['z1'], '#1f6fd6'),
                           (model['interface']['z2'], '#c92a2a')):
        _board_3d_frame(ax, z_value, color=color, linewidth=0.8)
    _setup_3d_axes(ax, model, z_aspect=0.52)
    cax = fig.add_axes([0.905, 0.20, 0.012, 0.56])
    colorbar = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax)
    colorbar.set_label('physical z (mm)', fontsize=8.0)
    colorbar.ax.tick_params(labelsize=5.5)
    fig.suptitle(
        f"全 1024 通道真实 3D 布线总览（{exp['metrics']['routed']} / 1024 条布通，"
        f"颜色=物理高度，含升降 S 曲线段）\n"
        f"L1 双接口行 z1={model['interface']['z1']:.3f} / "
        f"z2={model['interface']['z2']:.3f} mm；L2–L{model['max_layer']} "
        f"固定分配层（L6 为保留层）；R=15 mm 升降过渡",
        fontsize=10.0, y=0.995)
    path = Path(out_dir) / 'plots' / 'thematic' / '07_full_1024_3d.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='full_1024_3d',
                 title_zh='1024 通道全 3D 总览',
                 title_en='full 1024-channel 3D view',
                 description=(f"{exp['metrics']['routed']} 条布通线路的完整 3D 路径；"
                              f"颜色表示物理高度，两种颜色板框为 L1 z1/z2 接口行"),
                 routes=exp['metrics']['routed'])]


def render_transitions_zoom(exp, out_dir, dpi, caveats):
    transitions = exp['_transition_geom']
    if not transitions:
        caveats.append('没有升降过渡段，跳过 3D 过渡放大图')
        return []
    group_counts = Counter((item['from_layer'], item['to_layer'])
                           for item in transitions
                           if item['from_layer'] is not None
                           and item['to_layer'] is not None)
    upward = [(pair, count) for pair, count in group_counts.items()
              if pair[0] < pair[1]]
    ordered = sorted(upward or list(group_counts.items()),
                     key=lambda item: (-item[1], item[0][0], item[0][1]))
    panels = ordered[:4]
    fig = plt.figure(figsize=(15.6, 9.2))
    panel_rects = ([0.035, 0.530, 0.43, 0.36], [0.525, 0.530, 0.43, 0.36],
                   [0.035, 0.065, 0.43, 0.36], [0.525, 0.065, 0.43, 0.36])
    for index, (pair, count) in enumerate(panels):
        ax = fig.add_axes(panel_rects[index], projection='3d')
        items = sorted([item for item in transitions
                        if (item['from_layer'], item['to_layer']) == pair],
                       key=lambda item: item['rid'])[:3]
        palette = ('#1f6fd6', '#e07b1a', '#2f9e44')
        all_points = []
        for color, item in zip(palette, items):
            curve = curve_for(exp, item['part'], step_mm=0.05)
            if curve is None or len(curve) < 2:
                continue
            ax.plot(curve[:, 0], curve[:, 1], curve[:, 2], color=color,
                    linewidth=2.4, alpha=0.95)
            all_points.append(curve)
            start_xy = item['start_xy']
            end_xy = item['end_xy']
            direction = item['part'].get('direction')
            if start_xy is not None and end_xy is not None and direction:
                norm = math.hypot(direction[0], direction[1]) or 1.0
                unit = (direction[0] / norm * 2.5, direction[1] / norm * 2.5)
                stub_start = np.asarray([
                    [start_xy[0] - unit[0], start_xy[1] - unit[1], item['z0']],
                    [start_xy[0], start_xy[1], item['z0']]])
                stub_end = np.asarray([
                    [end_xy[0], end_xy[1], item['z1']],
                    [end_xy[0] + unit[0], end_xy[1] + unit[1], item['z1']]])
                ax.plot(stub_start[:, 0], stub_start[:, 1], stub_start[:, 2],
                        color='#868e96', linewidth=1.0, linestyle='--')
                ax.plot(stub_end[:, 0], stub_end[:, 1], stub_end[:, 2],
                        color='#868e96', linewidth=1.0, linestyle='--')
                all_points.extend([stub_start, stub_end])
        if all_points:
            points = np.concatenate(all_points, axis=0)
            xs, ys, zs = points[:, 0], points[:, 1], points[:, 2]
            span_xy = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-6)
            span_z = max(zs.max() - zs.min(), 1e-6)
            margin_xy = max(1.2, 0.14 * span_xy)
            margin_z = max(0.05, 0.20 * span_z)
            ax.set_xlim(xs.min() - margin_xy, xs.max() + margin_xy)
            ax.set_ylim(ys.min() - margin_xy, ys.max() + margin_xy)
            ax.set_zlim(zs.min() - margin_z, zs.max() + margin_z)
            z_aspect = min(0.95, max(0.25, 3.0 * span_z / span_xy))
            ax.set_box_aspect((1.0, 1.0, z_aspect))
            ax.set_xlabel('x (mm)', fontsize=6.5)
            ax.set_ylabel('y (mm)', fontsize=6.5)
            ax.set_zlabel('z (mm)', fontsize=6.5)
            ax.tick_params(labelsize=4.6)
            ax.view_init(elev=22.0, azim=-62.0)
        else:
            ax.text2D(0.5, 0.5, '无可用几何', transform=ax.transAxes,
                      ha='center', va='center')
        from_layer, to_layer = pair
        routes_text = ', '.join(str(item['rid']) for item in items)
        if items:
            dz = (items[0]['z1'] or 0.0) - (items[0]['z0'] or 0.0)
            dz_text = f'Δz = {dz:+.3f} mm'
        else:
            dz_text = 'Δz = —'
        ax.set_title(
            f"L{from_layer} → L{to_layer}：共 {count} 段"
            f"（显示 {len(items)} 段；route {routes_text}）\n{dz_text}",
            fontsize=8.5, pad=2)
    fig.suptitle('真实升降 S 曲线 3D 放大（每层对取 route_id 最小的 3 段；'
                 '虚线为前后平面段延伸；z 方向按比例放大显示）',
                 fontsize=10.5, y=0.985)
    path = Path(out_dir) / 'plots' / 'thematic' / '08_transitions_3d_zoom.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='transitions_3d_zoom',
                 title_zh='真实升降过渡 3D 放大',
                 title_en='3D zoom on real transitions',
                 description=(f"共 {len(transitions)} 个升降段；按层对取前 4 组"
                              f"（{', '.join(f'L{a}→L{b}' for (a, b), _ in panels)}）"
                              '各显示 3 段'),
                 routes=None)]


# ---------------------------------------------------------------------------
# thematic: bar charts
# ---------------------------------------------------------------------------
def render_route_count_bars(exp, out_dir, dpi, caveats):
    roles = exp['per_layer']
    interface_rows = [row for row in roles if row['kind'] == 'interface']
    routing_rows = [row for row in roles if row['kind'] == 'routing']
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(16.0, 6.4), gridspec_kw={'width_ratios': (1.0, 3.2)})
    # -- interface rows ---------------------------------------------------
    labels = [row['short'] for row in interface_rows]
    actual = [row['routes'] for row in interface_rows]
    expected = [row['assigned'] for row in interface_rows]
    x = np.arange(len(labels))
    width = 0.36
    ax_left.bar(x - (width / 2 if any(v is not None for v in expected) else 0.0),
                actual, width=width, color='#1f6fd6', label='实际布通（物理平面）')
    if any(value is not None for value in expected):
        expected_values = [value if value is not None else 0 for value in expected]
        ax_left.bar(x + width / 2, expected_values, width=width,
                    color='#e07b1a', label='固定分配（接口行线路数）')
        for index, value in enumerate(expected_values):
            if expected[index] is not None:
                ax_left.text(x[index] + width / 2, value + 3, str(value),
                             ha='center', fontsize=6.5)
    for index, value in enumerate(actual):
        ax_left.text(x[index] - (width / 2 if any(v is not None for v in expected) else 0.0),
                     value + 3, str(value), ha='center', fontsize=6.5)
    ax_left.set_xticks(x)
    ax_left.set_xticklabels(labels, fontsize=7.0)
    ax_left.set_ylabel('线路数', fontsize=8.0)
    ax_left.set_title('接口两排布线数（Z1 / Z2）', fontsize=8.5)
    ax_left.legend(fontsize=6.5, framealpha=0.9)
    ax_left.grid(axis='y', alpha=0.2)
    # -- routing layers ---------------------------------------------------
    labels = [row['short'] for row in routing_rows]
    actual = [row['routes'] for row in routing_rows]
    expected = [row['assigned'] for row in routing_rows]
    x = np.arange(len(labels))
    has_expected = any(value is not None for value in expected)
    ax_right.bar(x - (width / 2 if has_expected else 0.0), actual,
                 width=width, color='#1f6fd6', label='实际布通（该层平面波导）')
    if has_expected:
        expected_values = [value if value is not None else 0 for value in expected]
        ax_right.bar(x + width / 2, expected_values, width=width,
                     color='#e07b1a', label='固定分配（目标层）')
        for index, value in enumerate(expected_values):
            if expected[index] is not None:
                ax_right.text(x[index] + width / 2, value + 1.0, str(value),
                              ha='center', fontsize=5.6)
    for index, value in enumerate(actual):
        ax_right.text(x[index] - (width / 2 if has_expected else 0.0),
                      value + 1.0, str(value), ha='center', fontsize=5.6)
    labels_display = []
    for row in routing_rows:
        label = row['short']
        if row['reserved']:
            label += '\n(保留)'
        labels_display.append(label)
    ax_right.set_xticks(x)
    ax_right.set_xticklabels(labels_display, fontsize=5.6, rotation=90)
    ax_right.set_ylabel('线路数', fontsize=8.0)
    ax_right.set_title('L2–L20 逐层布线数：实际 vs 固定分配'
                       '（L6 保留层不分配新线路）', fontsize=8.5)
    ax_right.legend(fontsize=6.8, framealpha=0.9)
    ax_right.grid(axis='y', alpha=0.2)
    empty = [row['short'] for row in routing_rows if row['empty']]
    note = ('空层：' + '、'.join(empty)) if empty else '所有分配层均有布线'
    fig.suptitle('逐层布线数（per-layer route count）：'
                 '实际布通取自 routes_l3d.json，分配数取自 '
                 'layer_stats.json / assignment_1024.json\n' + note,
                 fontsize=10.0)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    path = (Path(out_dir) / 'plots' / 'thematic'
            / '09_per_layer_route_count.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='per_layer_route_count',
                 title_zh='逐层布线数柱状图',
                 title_en='per-layer route count',
                 description=('接口两排 + L2–L20 逐层实际布通数与固定分配数对比；'
                              + note),
                 routes=sum(actual))]


def render_crossing_bars(exp, out_dir, dpi, caveats):
    crossings = exp['crossings']
    rows = exp['per_layer']
    labels = [row['short'] for row in rows]
    pairs = [row['crossings_pairs'] for row in rows]
    points = [row['crossings_points'] for row in rows]
    fig, ax = plt.subplots(figsize=(16.0, 6.2))
    if crossings is None:
        ax.axis('off')
        ax.text(0.5, 0.5, 'crossings_after.json 缺失，无法绘制逐层交叉统计',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=13.0, color='#868e96')
        fig.suptitle('逐层交叉统计（缺失数据）', fontsize=11.0)
    else:
        x = np.arange(len(labels))
        width = 0.38
        pair_values = [value if value is not None else 0 for value in pairs]
        point_values = [value if value is not None else 0 for value in points]
        ax.bar(x - width / 2, pair_values, width=width, color='#1f6fd6',
               label='逐高度唯一交叉对')
        ax.bar(x + width / 2, point_values, width=width, color='#e07b1a',
               label='逐高度交叉点')
        peak = max(pair_values + point_values + [1])
        # the interface planes dominate by orders of magnitude -> symlog y
        ax.set_yscale('symlog', linthresh=1.0)
        ax.set_ylim(0, peak * 1.8)
        for index, value in enumerate(pair_values):
            if value:
                ax.text(x[index] - width / 2, value * 1.15, f'{value}',
                        ha='center', fontsize=5.2, rotation=90)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=6.0, rotation=90)
        ax.set_ylabel('交叉数量（symlog 对数轴）', fontsize=8.0)
        ax.legend(fontsize=7.5, framealpha=0.9)
        ax.grid(axis='y', alpha=0.2)
        total_pairs = sum(pair_values)
        fig.suptitle(
            '逐层交叉统计（per-layer crossing count）：交叉按物理高度分到层平面\n'
            f'逐高度唯一对合计 {total_pairs}；'
            f"全局唯一交叉对 {exp['metrics']['crossing_pairs']}"
            f"（同一对可能在多层出现，逐层合计与全局值口径不同；"
            'y 轴 symlog 以便同时显示接口层与高层的小数值）',
            fontsize=10.0)
        fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    path = (Path(out_dir) / 'plots' / 'thematic'
            / '10_per_layer_crossing_count.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='per_layer_crossing_count',
                 title_zh='逐层交叉数柱状图',
                 title_en='per-layer crossing count',
                 description=('按物理高度统计的唯一交叉对与交叉点数量；'
                              '数据来自 crossings_after.json'),
                 routes=None)]


# ---------------------------------------------------------------------------
# thematic: old vs new crossing comparison
# ---------------------------------------------------------------------------
def _cross_plane_series(run_metrics, key):
    if not run_metrics:
        return None
    value = (run_metrics.get('crossing_by_plane') or {}).get(key)
    return None if value is None else int(value)


def render_old_vs_new_crossings(exp, out_dir, dpi, caveats):
    runs = [
        ('baseline', exp.get('baseline') or {}, '旧 15L 自动算法基线'),
        ('previous', exp.get('previous') or {}, '15L 人工优先（上一轮）'),
        ('new', dict(available=True, label='新 L1–L20',
                     metrics=exp['metrics'], model=exp['layer_model'],
                     crossings=exp['crossings']),
         '新 L1–L20 固定分配'),
    ]
    categories = [
        ('全局唯一交叉对', lambda metrics: metrics.get('crossing_pairs')),
        ('交叉点总数', lambda metrics: metrics.get('crossing_points')),
        ('Z1×Z1', lambda metrics: _cross_plane_series(metrics, 'z1xz1')),
        ('Z2×Z2', lambda metrics: _cross_plane_series(metrics, 'z2xz2')),
        ('Z1×Z2 混合', lambda metrics: _cross_plane_series(metrics, 'z1xz2')),
    ]
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(16.6, 6.6), gridspec_kw={'width_ratios': (1.45, 1.0)})
    x = np.arange(len(categories))
    width = 0.26
    present_runs = 0
    for run_index, (role, run, label) in enumerate(runs):
        values = []
        available = bool(run.get('available') and run.get('metrics'))
        if not available:
            continue
        present_runs += 1
        for _title, getter in categories:
            try:
                values.append(int(getter(run['metrics']) or 0))
            except (KeyError, TypeError):
                values.append(0)
        positions = x + (run_index - 1) * width
        ax_left.bar(positions, values, width=width,
                    color=RUN_COLORS.get(role, '#495057'), label=label)
        for position, value in zip(positions, values):
            if value:
                ax_left.text(position, value + max(values) * 0.015,
                             f'{value}', ha='center', fontsize=5.4,
                             rotation=90)
    ax_left.set_xticks(x)
    ax_left.set_xticklabels([title for title, _ in categories], fontsize=7.5)
    ax_left.set_ylabel('交叉数量', fontsize=8.0)
    ax_left.set_title('全局与平面分解交叉对比', fontsize=9.0)
    ax_left.legend(fontsize=7.0, framealpha=0.9)
    ax_left.grid(axis='y', alpha=0.2)
    missing = [label for _role, run, label in runs
               if not (run.get('available') and run.get('metrics'))]
    note_lines = []
    if missing:
        note_lines.append('缺失参考运行：' + '、'.join(missing))
    if exp.get('smoke'):
        note_lines.append('smoke 数据：新数据即 15L 文件，与上一轮相同')
    if note_lines:
        ax_left.text(0.02, 0.98, '\n'.join(note_lines), transform=ax_left.transAxes,
                     fontsize=6.5, va='top', color='#c92a2a')
    # -- per-height lines -------------------------------------------------
    height_pairs = []
    for run_index, (role, run, label) in enumerate(runs):
        if not (run.get('available') and run.get('crossings')):
            continue
        crossings = run['crossings']
        mapping = crossings.get('pair_by_height') or {}
        if not mapping:
            continue
        heights = sorted(mapping)
        values = [mapping[height] for height in heights]
        ax_right.plot(heights, values, marker='o', markersize=3.0,
                      linewidth=1.2, color=RUN_COLORS.get(role, '#495057'),
                      label=label)
        height_pairs.append((role, heights, values))
    ax_right.set_xlabel('物理 z (mm)', fontsize=8.0)
    ax_right.set_ylabel('逐高度唯一交叉对', fontsize=8.0)
    ax_right.set_title('逐物理高度唯一交叉对（15L vs 20L）', fontsize=9.0)
    ax_right.legend(fontsize=7.0, framealpha=0.9)
    ax_right.grid(alpha=0.2)
    if not height_pairs:
        ax_right.text(0.5, 0.5, 'crossings_after.json 缺失，无法绘制逐高度曲线',
                      transform=ax_right.transAxes, ha='center', va='center',
                      fontsize=10.0, color='#868e96')
    fig.suptitle('旧 15L vs 新 L1–L20 交叉对比（全部数值来自各目录 '
                 'crossings_after.json / routes_l3d.json）', fontsize=10.5)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.92))
    path = (Path(out_dir) / 'plots' / 'thematic'
            / '11_old_vs_new_crossings.png')
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(fig, path, dpi)
    return [dict(file=_relative(path, out_dir), group='thematic',
                 key='old_vs_new_crossings',
                 title_zh='旧 15L vs 新 L1–L20 交叉对比',
                 title_en='old-vs-new crossing comparison',
                 description=('旧 15L 自动算法基线 / 15L 人工优先 / 新 L1–L20 '
                              '的全局、平面分解与逐高度交叉对比；'
                              '缺失参考运行不估算'),
                 routes=None)]


# ---------------------------------------------------------------------------
# manifest / orchestration
# ---------------------------------------------------------------------------
def layer_model_summary(model):
    return dict(
        interface={plane: float(model['interface'][plane])
                   for plane in REPORT.INTERFACE_ROWS},
        routing={str(layer): float(z) for layer, z in model['routing'].items()},
        max_layer=model.get('max_layer'),
        reserved=sorted(model.get('reserved') or []),
        source=model.get('source'),
        provenance=model.get('provenance'),
        note=model.get('note'),
    )


def _figure_attempt(figures, skipped, strict, kind, func, *args):
    try:
        entries = func(*args)
        if entries:
            figures.extend(entries)
    except Exception as exc:  # noqa: BLE001 - a failed figure must not kill all
        detail = f'{type(exc).__name__}: {exc}'
        skipped.append(dict(kind=kind, error=detail,
                            traceback=traceback.format_exc(limit=3)))
        print(f'[plots_20l] WARNING: figure "{kind}" failed: {detail}',
              file=sys.stderr)
        if strict:
            raise


def render_all(exp, out_dir, dpi_scale=1.0, strict=False, caveats=None,
               skip_per_layer=False, skip_thematic=False):
    prepare_geometry(exp)
    if not has_cjk_font():
        caveats.append('未找到中文字体，图中中文可能显示为方框 '
                       f'（尝试过 {", ".join(FONT_CANDIDATES)}）')
    out_dir = Path(out_dir)
    scale = float(dpi_scale)
    figures = []
    skipped = []

    def dpi(kind):
        return max(60, int(round(BASE_DPI.get(kind, 130) * scale)))

    if not skip_per_layer:
        _figure_attempt(figures, skipped, strict, 'per_layer',
                        render_per_layer, exp, out_dir, dpi('per_layer'),
                        caveats)
        _figure_attempt(figures, skipped, strict, 'contact_sheet',
                        render_contact_sheet, exp, out_dir, dpi('contact'),
                        caveats)
    if not skip_thematic:
        _figure_attempt(figures, skipped, strict, 'z1_manual_u_overview',
                        render_manual_u_overview, exp, out_dir,
                        dpi('thematic'), caveats)
        _figure_attempt(figures, skipped, strict, 'l2_l5_manual_u_comparison',
                        render_manual_u_comparison, exp, out_dir,
                        dpi('thematic'), caveats)
        _figure_attempt(figures, skipped, strict, 'l7_ns_overview',
                        render_opposite_overview, exp, out_dir, dpi('thematic'),
                        7, 3, caveats)
        _figure_attempt(figures, skipped, strict, 'l8_ew_overview',
                        render_opposite_overview, exp, out_dir, dpi('thematic'),
                        8, 4, caveats)
        _figure_attempt(figures, skipped, strict, 'z2_l9_l20_summary',
                        render_z2_high_summary, exp, out_dir,
                        dpi('thematic'), caveats)
        _figure_attempt(figures, skipped, strict, 'z2_interface_residual',
                        render_z2_interface_residual, exp, out_dir,
                        dpi('thematic'), caveats)
        _figure_attempt(figures, skipped, strict, 'full_1024_3d',
                        render_full_3d, exp, out_dir, dpi('three_d'), caveats)
        _figure_attempt(figures, skipped, strict, 'transitions_3d_zoom',
                        render_transitions_zoom, exp, out_dir,
                        dpi('three_d'), caveats)
        _figure_attempt(figures, skipped, strict, 'per_layer_route_count',
                        render_route_count_bars, exp, out_dir,
                        dpi('thematic'), caveats)
        _figure_attempt(figures, skipped, strict, 'per_layer_crossing_count',
                        render_crossing_bars, exp, out_dir, dpi('thematic'),
                        caveats)
        _figure_attempt(figures, skipped, strict, 'old_vs_new_crossings',
                        render_old_vs_new_crossings, exp, out_dir,
                        dpi('thematic'), caveats)
    return figures, skipped


def write_manifest(exp, out_dir, figures, skipped):
    manifest = dict(
        schema=SCHEMA,
        run_dir=REPORT.rel_path(exp['run_dir']),
        experiment=exp['label'],
        smoke=bool(exp.get('smoke')),
        layer_model=layer_model_summary(exp['layer_model']),
        data_sources=exp['sources'],
        metrics=dict(
            routed=exp['metrics']['routed'],
            failed=exp['metrics']['failed'],
            total_records=exp['metrics']['total_records'],
            by_plane=exp['metrics']['by_plane'],
            crossing_pairs=exp['metrics']['crossing_pairs'],
            crossing_points=exp['metrics']['crossing_points'],
            transitions=exp['metrics']['transitions'],
        ),
        per_layer=[dict(
            key=row['key'], layer=row['layer'], z_mm=row['z_mm'],
            routes=row['routes'], assigned=row['assigned'],
            crossings_pairs=row['crossings_pairs'],
            crossings_points=row['crossings_points'],
            empty=row['empty'], reserved=row['reserved'],
        ) for row in exp['per_layer']],
        figures=figures,
        skipped=skipped,
        caveats=exp.get('caveats') or [],
    )
    path = Path(out_dir) / 'plots' / 'manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                               default=str), encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description='Render per-layer + thematic PNG figures and the '
                    'report.md / comparison.md for the L1-L20 '
                    'fixed-assignment experiment.')
    parser.add_argument('--out-dir', type=Path, default=None,
                        help='run directory (read + write); default: '
                             'MANUAL_20L_FIXED_ASSIGNMENT_FULL')
    parser.add_argument('--data-dir', type=Path, default=None,
                        help='read artefacts from this directory instead '
                             '(e.g. the 15L fixture for a smoke test)')
    parser.add_argument('--baseline-dir', type=Path, default=None,
                        help='old 15L automatic run used in the comparison '
                             'chart/report (default: L15/lift baseline)')
    parser.add_argument('--previous-dir', type=Path, default=None,
                        help='previous 15L manual-first run used in the '
                             'comparison chart/report')
    parser.add_argument('--no-baseline', action='store_true',
                        help='do not read the old reference runs')
    parser.add_argument('--smoke', action='store_true',
                        help='allow the 15L smoke fallback when '
                             'routes_l3d.json does not exist yet')
    parser.add_argument('--dpi-scale', type=float, default=1.0,
                        help='multiply every figure DPI by this factor '
                             '(default 1.0)')
    parser.add_argument('--skip-per-layer', action='store_true',
                        help='skip the 21 per-layer figures + contact sheet')
    parser.add_argument('--skip-thematic', action='store_true',
                        help='skip the thematic figures')
    parser.add_argument('--no-report', action='store_true',
                        help='only render figures (do not write report.md / '
                             'comparison.md)')
    parser.add_argument('--strict', action='store_true',
                        help='raise on the first failed figure instead of '
                             'recording it as a caveat')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    try:
        paths = REPORT.resolve_input_paths(out_dir=args.out_dir,
                                           data_dir=args.data_dir,
                                           smoke=args.smoke)
    except FileNotFoundError as exc:
        print(f'[plots_20l] ERROR: {exc}', file=sys.stderr)
        return 2
    caveats = list(paths['caveats'])
    print(f'[plots_20l] data: {REPORT.rel_path(paths["data_dir"])}')
    print(f'[plots_20l] out : {REPORT.rel_path(paths["out_dir"])}')
    exp = REPORT.load_experiment(
        paths['data_dir'],
        baseline_dir=False if args.no_baseline else (
            args.baseline_dir or REPORT.BASELINE_DIR),
        previous_dir=False if args.no_baseline else (
            args.previous_dir or REPORT.PREVIOUS_15L_DIR),
        smoke=args.smoke and paths['smoke_fallback'],
    )
    exp['caveats'] = caveats + list(exp.get('caveats') or [])
    print(f"[plots_20l] routed={exp['metrics']['routed']}/1024, "
          f"planes={len(exp['planes'])}, "
          f"crossings={exp['metrics']['crossing_pairs']}, "
          f"font={'/'.join(CHOSEN_FONTS[:2])}")
    figures, skipped = render_all(
        exp, paths['out_dir'], dpi_scale=args.dpi_scale, strict=args.strict,
        caveats=exp['caveats'], skip_per_layer=args.skip_per_layer,
        skip_thematic=args.skip_thematic)
    manifest_path = write_manifest(exp, paths['out_dir'], figures, skipped)
    print(f'[plots_20l] figures: {len(figures)} '
          f'(skipped {len(skipped)}), manifest: {REPORT.rel_path(manifest_path)}')
    if not args.no_report:
        written = REPORT.write_reports(exp, paths['out_dir'], figures=figures)
        print(f'[plots_20l] report: {REPORT.rel_path(written["report"])}')
        print(f'[plots_20l] comparison: '
              f'{REPORT.rel_path(written["comparison"])}')
    elapsed = time.perf_counter() - started
    print(f'[plots_20l] done in {elapsed:.1f}s '
          f'({len(exp["caveats"])} caveats)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
