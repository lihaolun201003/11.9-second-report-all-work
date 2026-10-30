# -*- coding: utf-8 -*-
"""Scientific figures for the strict-C4 1024-channel multilayer experiments.

Every figure in this module is computed from the **stored XYZ route data**
(``record['parts']`` with real flat primitives and S-transition start/end/z0/z1)
and from :func:`four_side_1024.e1.core.audit` crossing statistics.  Nothing is
copied or rotated from a single quadrant: the 2D / 3D views plot all 1024 real
routes, and every rotation overlay is obtained by actually rotating the stored
centreline samples with ``R(x, y) = (150 - y, x)`` about the board centre
``(75, 75)``.

The drawing style is the one of :mod:`four_side_1024.e1.plots`
(``sample_primitives``, ``color_for_z``, ``_style_xy``, ``_save``,
``make_contact_sheet``); the helpers are reused where the E1 versions apply and
re-implemented (vectorised) where the C4 layer stack needs L2..L13 heights or
``LineCollection`` speed.

Public API (consumed by the C4 experiment driver)::

    geometry_figures(folder, records, ctx, *, name, c4_report=None,
                     baseline_records=None, baseline_name='E1-BASE') -> dict
    summary_figures(folder, rows, *, e1_row=None) -> dict
    orbit_overlay_figure(folder, records, ctx, name, orbit_ids=None) -> str

* ``folder`` is the per-experiment output directory; geometry figures are
  written to ``<folder>/figures/`` and the four summary figures to ``<folder>/``.
* all returned paths are absolute path strings (JSON friendly).
* ``c4_report`` is the dict produced by the independent C4 validator.  When it
  is ``None`` (or lacks a key) the figure renders ``not provided`` / ``n/a`` --
  numbers are never invented.
* ``rows`` for :func:`summary_figures` are dicts with the keys
  ``experiment, layers, unique_crossing_pairs, total_length_mm,
  fabrication_hours, max_z_mm, transitions`` (extra keys are ignored).
"""
from __future__ import annotations

import json
import math
import re
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from four_side_1024.e1 import core as C
from four_side_1024.e1 import plots as P
from four_side_1024.c4 import layers as LY
from four_side_1024.c4 import orbits as O

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.max_open_warning'] = 0

__all__ = ['geometry_figures', 'summary_figures', 'orbit_overlay_figure']

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
DPI = 180
DPI_TILE = 170
Z1 = float(LY.Z1)
Z2 = float(LY.Z2)
MAX_LAYER = int(max(LY.HEIGHTS))          # 13
PLANE_COLORS = {Z1: '#1f6fd6', Z2: '#e07b1a'}
ROUTING_COLORS = list(P.ROUTING_COLORS)
MEMBER_COLORS = ['#1f6fd6', '#2f9e44', '#e8590c', '#7048e8']
ROTATION_CENTER = (75.0, 75.0)
X_RANGE = (0.0, 150.0)
Y_RANGE = (0.0, 150.0)
C4_ERROR_KEYS = ['orbit_size_errors', 'endpoint_rotation_errors',
                 'layer_symmetry_errors', 'transition_symmetry_errors',
                 'geometry_symmetry_errors']
LAYER_EXPERIMENT_COLORS = {7: '#1f6fd6', 9: '#2f9e44', 11: '#e8590c',
                           13: '#7048e8'}
CATEGORY_PRIORITY = [('z1', 'opposite'), ('z1', 'adjacent'), ('z2', 'adjacent'),
                     ('z2', 'same'), ('z1', 'same'), ('z2', 'opposite')]

_AUDIT_CACHE = {}
_ORBIT_CACHE = None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _ensure_dir(path):
    return C.ensure_dir(Path(path))


def _slug(text):
    out = re.sub(r'[^0-9A-Za-z_.-]+', '_', str(text)).strip('_.-')
    return out or 'c4'


def _as_records(records):
    """Accept a record list, a payload dict or None; keep routed records."""
    if records is None:
        return []
    if isinstance(records, dict):
        records = records.get('routes') or []
    out = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get('status', 'routed')) != 'routed':
            continue
        out.append(record)
    return out


def _records_by_id(records):
    return {int(record['route_id']): record for record in records}


def _layer_count_from_name(name):
    """'C4-11L' -> 11; 'C4-BASE'/'E1-BASE' -> None."""
    if not name:
        return None
    values = []
    for token in re.findall(r'(\d+)\s*[lL](?![0-9A-Za-z])', str(name)):
        try:
            value = int(token)
        except ValueError:
            continue
        if 2 <= value <= MAX_LAYER:
            values.append(value)
    return max(values) if values else None


def _observed_flat_heights(records):
    """routing layer id -> observed physical z (mm), from the real records."""
    observed = {}
    for record in records:
        for part in record.get('parts') or []:
            if part.get('kind') != 'flat':
                continue
            try:
                layer = int(part.get('layer_id', 1))
            except (TypeError, ValueError):
                continue
            if layer <= 1:
                continue
            observed.setdefault(layer, round(float(part['z_mm']), 6))
    return observed


def _stack_layer_z(layer, observed=None):
    layer = int(layer)
    if observed and layer in observed:
        return float(observed[layer])
    if layer in LY.HEIGHTS:
        return float(LY.layer_z(layer))
    return float(LY.BASE_Z + (layer - 2) * LY.PITCH)


def _max_routing_layer(name, records, c4_report=None, max_layer=None):
    """Highest routing layer id of the stack (interface L1 + L2..L_n).

    Resolution order: explicit ``max_layer`` -> ``<n>L`` token in ``name`` ->
    ``c4_report['layers']`` -> the default frozen stack (``e1.core.LAYERS``,
    i.e. L2..L7) widened by any higher routing layer actually observed in the
    records.
    """
    if max_layer is not None:
        return max(2, min(MAX_LAYER, int(max_layer)))
    parsed = _layer_count_from_name(name)
    if parsed is not None:
        return int(parsed)
    if isinstance(c4_report, dict) and c4_report.get('layers'):
        try:
            return max(2, min(MAX_LAYER, int(c4_report['layers'])))
        except (TypeError, ValueError):
            pass
    try:
        default = int(max(C.LAYERS))
    except Exception:
        default = 7
    observed = _observed_flat_heights(records)
    return max(2, min(MAX_LAYER, max(default, max(observed) if observed else 0)))


def _z_info(max_layer, records):
    """Ordered [(label, z)] for the interface rows then L2..L_max."""
    observed = _observed_flat_heights(records)
    info = [dict(label='L1-Z1', z=Z1, layer=None),
            dict(label='L1-Z2', z=Z2, layer=None)]
    for layer in range(2, int(max_layer) + 1):
        info.append(dict(label='L%d' % layer,
                         z=_stack_layer_z(layer, observed), layer=layer))
    return info


def _z_label_map(zinfo):
    return {round(float(item['z']), 6): item['label'] for item in zinfo}


def c4_color_for_z(z):
    """Stable colour per physical height (interface rows + L2..L13)."""
    z = round(float(z), 6)
    if abs(z - Z1) <= 1e-9:
        return PLANE_COLORS[Z1]
    if abs(z - Z2) <= 1e-9:
        return PLANE_COLORS[Z2]
    for layer in sorted(LY.HEIGHTS):
        if abs(float(LY.HEIGHTS[layer]) - z) <= 1e-9:
            return ROUTING_COLORS[(int(layer) - 2) % len(ROUTING_COLORS)]
    return P.color_for_z(z)


def _records_max_z(records):
    value = 0.0
    for record in records:
        for part in record.get('parts') or []:
            if part.get('kind') == 'flat':
                value = max(value, float(part['z_mm']))
    return float(value)


def _route_max_z(record):
    value = 0.0
    for part in record.get('parts') or []:
        if part.get('kind') == 'flat':
            value = max(value, float(part['z_mm']))
    return float(value)


def _transition_count(records):
    total = 0
    for record in records:
        for part in record.get('parts') or []:
            if part.get('kind') == 'transition':
                total += 1
    return total


def _flat_index(records):
    """z -> [(route_id, primitives)] plus per-height unique route/segment sets."""
    index = defaultdict(list)
    route_ids = defaultdict(set)
    segments = Counter()
    for record in records:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part.get('kind') != 'flat':
                continue
            primitives = part.get('primitives') or []
            if not primitives:
                continue
            z = round(float(part['z_mm']), 6)
            index[z].append((rid, primitives))
            route_ids[z].add(rid)
            segments[z] += 1
    return index, route_ids, segments


def _transition_segments_3d(records):
    segments = []
    for record in records:
        for part in record.get('parts') or []:
            if part.get('kind') != 'transition':
                continue
            start, end = part.get('start'), part.get('end')
            if start is None or end is None:
                continue
            segments.append(np.asarray(
                [[float(start[0]), float(start[1]), float(part['z0'])],
                 [float(end[0]), float(end[1]), float(part['z1'])]],
                dtype=float))
    return segments


def _audit(records, ctx):
    """Crossing audit with a per-process cache (id + size + endpoints key)."""
    if not records:
        return C.audit([], ctx)
    key = (id(records), len(records), int(records[0]['route_id']),
           int(records[-1]['route_id']))
    hit = _AUDIT_CACHE.get(key)
    if hit is not None:
        return hit
    result = C.audit(records, ctx)
    if len(_AUDIT_CACHE) > 12:
        _AUDIT_CACHE.clear()
    _AUDIT_CACHE[key] = result
    return result


def _per_height(analysis, z):
    return analysis['per_height'].get(
        round(float(z), 6),
        dict(routes=0, segments=0, pairs=0, events=0, violations=0,
             breakdown={}))


# ---------------------------------------------------------------------------
# vectorised 2D drawing helpers (LineCollection based)
# ---------------------------------------------------------------------------
def _polyline(primitives, n_arc=16):
    xs, ys = P.sample_primitives(primitives, n_arc=n_arc)
    if len(xs) < 2:
        return None
    array = np.column_stack([np.asarray(xs, dtype=float),
                             np.asarray(ys, dtype=float)])
    return array


def _add_xy_collection(ax, chains, color, lw=0.35, alpha=0.35, zorder=2):
    segments = []
    for primitives in chains:
        line = _polyline(primitives)
        if line is not None and len(line) >= 2:
            segments.append(line)
    if segments:
        ax.add_collection(LineCollection(segments, colors=color,
                                         linewidths=lw, alpha=alpha,
                                         zorder=zorder))
    return len(segments)


def _add_xy_transitions(ax, records, color='#8c8c8c', lw=0.25, alpha=0.2,
                        zorder=1):
    segments = []
    for record in records:
        for part in record.get('parts') or []:
            if part.get('kind') != 'transition':
                continue
            start, end = part.get('start'), part.get('end')
            if start is None or end is None:
                continue
            segments.append(np.asarray(
                [[float(start[0]), float(start[1])],
                 [float(end[0]), float(end[1])]], dtype=float))
    if segments:
        ax.add_collection(LineCollection(segments, colors=color,
                                         linewidths=lw, alpha=alpha,
                                         zorder=zorder))
    return len(segments)


def _add_event_points(ax, events, color='#c92a2a', size=4.5):
    if not events:
        return
    ax.scatter([event['x'] for event in events],
               [event['y'] for event in events], marker='x', s=size,
               c=color, linewidths=0.5, zorder=6)


def _draw_rotation_guides_2d(ax, color='#adb5bd'):
    ax.axvline(ROTATION_CENTER[0], color=color, lw=0.5, alpha=0.45, zorder=0)
    ax.axhline(ROTATION_CENTER[1], color=color, lw=0.5, alpha=0.45, zorder=0)
    ax.plot([ROTATION_CENTER[0]], [ROTATION_CENTER[1]], marker='+',
            color=color, ms=7, mew=0.8, zorder=0)


# ---------------------------------------------------------------------------
# 3D drawing helpers (Line3DCollection based)
# ---------------------------------------------------------------------------
def _style_3d(ax, max_z):
    ax.set_xlim(*X_RANGE)
    ax.set_ylim(*Y_RANGE)
    ax.set_zlim(-0.05, float(max_z) + 0.12)
    try:
        ax.set_box_aspect((1.0, 1.0, 0.55))
    except Exception:
        pass
    ax.set_xlabel('x (mm)', fontsize=8)
    ax.set_ylabel('y (mm)', fontsize=8)
    ax.set_zlabel('z (mm)', fontsize=8)
    ax.tick_params(labelsize=6.5)
    ax.view_init(elev=24, azim=-58)
    ax.grid(alpha=0.15)


def _add_board_frame_3d(ax, z=0.0):
    frame = np.asarray([[0.0, 0.0], [150.0, 0.0], [150.0, 150.0],
                        [0.0, 150.0], [0.0, 0.0]])
    ax.plot(frame[:, 0], frame[:, 1], np.full(len(frame), float(z)),
            color='#868e96', lw=0.8, alpha=0.55)
    ax.plot([ROTATION_CENTER[0]] * 2, [ROTATION_CENTER[1]] * 2,
            [float(z), float(z) + 0.05], color='#495057', lw=0.8, alpha=0.6)


def _add_flats_3d(ax, index, alpha=0.4, lw=0.3):
    """Add the flat geometry of every physical height as 3D line segments.

    Each sampled polyline is split into two-point segments: ``Line3DCollection``
    / numpy 2.x cannot consume ragged segment arrays, and two-point segments also
    keep the 3D auto-scaling vectorised and fast for 1024 routes.
    """
    for z in sorted(index):
        segments = []
        for _rid, primitives in index[z]:
            line = _polyline(primitives, n_arc=10)
            if line is None:
                continue
            for position in range(len(line) - 1):
                segments.append(np.asarray(
                    [[line[position][0], line[position][1], float(z)],
                     [line[position + 1][0], line[position + 1][1], float(z)]],
                    dtype=float))
        if not segments:
            continue
        collection = Line3DCollection(segments, colors=[c4_color_for_z(z)],
                                      linewidths=lw, alpha=alpha)
        ax.add_collection3d(collection)
    return True


def _add_transitions_3d(ax, records, color='#8c8c8c', lw=0.35, alpha=0.3):
    segments = _transition_segments_3d(records)
    if segments:
        collection = Line3DCollection(segments, colors=[color],
                                      linewidths=lw, alpha=alpha)
        ax.add_collection3d(collection)
    return len(segments)


def _z_legend_patches(zinfo, z_present):
    handles = []
    for item in zinfo:
        z = round(float(item['z']), 6)
        if z not in z_present:
            continue
        handles.append(Patch(facecolor=c4_color_for_z(z), edgecolor='none',
                             label='%s  z=%.2f' % (item['label'], z)))
    return handles


# ---------------------------------------------------------------------------
# per-figure renderers
# ---------------------------------------------------------------------------
def _figure_overall_3d(path, records, analysis, ctx, name, zinfo, max_layer,
                       stats):
    index, route_ids, segments = _flat_index(records)
    max_z = _records_max_z(records)
    n_trans = _transition_count(records)
    fig = plt.figure(figsize=(10.6, 8.4))
    ax = fig.add_subplot(111, projection='3d')
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.91)
    _add_board_frame_3d(ax)
    _add_flats_3d(ax, index, alpha=0.42, lw=0.3)
    _add_transitions_3d(ax, records, color='#8c8c8c', lw=0.28, alpha=0.22)
    _style_3d(ax, max(max_z, 0.6))
    handles = _z_legend_patches(zinfo, set(index))
    if handles:
        ax.legend(handles=handles, loc='upper left', fontsize=6.0,
                  framealpha=0.7, title='physical height',
                  title_fontsize=6.5)
    ax.set_title(
        '%s: 1024-route 3D view (%d routed, %d S transitions)\n'
        'strict C4 about (75,75): R(x,y,z)=(150-y,x,z) | unique crossings %d'
        ' | length %.0f mm | max z %.2f mm'
        % (name, len(records), n_trans, analysis['n_unique_pairs'],
           stats['total_length_mm'], max_z), fontsize=9.0, pad=4)
    _finish(fig, path, tight=False, bbox=None)


def _figure_overall_xy(path, records, analysis, name, zinfo, stats):
    index, route_ids, segments = _flat_index(records)
    fig, ax = plt.subplots(figsize=(8.6, 8.2))
    _add_xy_transitions(ax, records, color='#8c8c8c', lw=0.22, alpha=0.15,
                        zorder=1)
    for z in sorted(index):
        _add_xy_collection(ax, [prims for _rid, prims in index[z]],
                           c4_color_for_z(z), lw=0.32, alpha=0.3, zorder=2)
    _draw_rotation_guides_2d(ax)
    P._style_xy(ax)
    ax.set_title('%s: top view (XY projection of all physical layers)\n'
                 '%d routes | %d flat segments | unique crossings %d'
                 % (name, len(records), sum(segments.values()),
                    analysis['n_unique_pairs']), fontsize=9.2)
    handles = _z_legend_patches(zinfo, set(index))
    if handles:
        ax.legend(handles=handles, loc='upper right', fontsize=5.8,
                  ncol=2, framealpha=0.75, title='physical height',
                  title_fontsize=6.0)
    _finish(fig, path)


def _load_orbits(ctx):
    global _ORBIT_CACHE
    if _ORBIT_CACHE is None:
        _ORBIT_CACHE = O.load_orbits(ctx if ctx is not None else C.load_ctx())
    return _ORBIT_CACHE


def _orbit_member_id(orbit, k):
    k = int(k)
    if k == 0:
        return int(orbit['rep'])
    return int(orbit['rotation'][k]['route_id'])


def _orbit_member_direction(orbit, k):
    k = int(k)
    if k == 0:
        return 'rep'
    return str(orbit['rotation'][k].get('direction', '?'))


def _centerline_2d(record, step=0.12):
    if record is None:
        return None
    points = np.asarray(O.centerline_points(record, step=step), dtype=float)
    if points.ndim != 2 or len(points) < 2:
        return None
    return points


def _centerline_3d(record, step=0.25, transition_step=0.15):
    """Dense (x, y, z) centreline samples of one route, from the stored parts.

    Flat parts use the real 2D primitives at their stored ``z_mm``; S-transitions
    use the real third-party 3D S-curve sampler
    (:func:`four_side_1024.fsd25d.path3d.transition_samples`).
    """
    if record is None:
        return None
    from four_side_1024.fsd25d import path3d as P3
    points = []
    for part in record.get('parts') or []:
        if part.get('kind') == 'flat':
            z = float(part['z_mm'])
            chain = O.chain_points(part.get('primitives') or [], step=step)
            points.extend((float(x), float(y), z) for x, y in chain)
        elif part.get('kind') == 'transition':
            points.extend(P3.transition_samples(part, step=transition_step))
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or len(array) < 2:
        return None
    return array


def _polyline_deviation(points, polyline, chunk=512):
    """Max distance from ``points`` (N,3) to the polyline ``(M,3)`` as segments."""
    if points is None or polyline is None:
        return None
    points = np.asarray(points, dtype=float)
    polyline = np.asarray(polyline, dtype=float)
    if len(points) < 1 or len(polyline) < 2:
        return None
    starts = polyline[:-1]
    vectors = polyline[1:] - starts
    length2 = np.einsum('ij,ij->i', vectors, vectors)
    length2 = np.where(length2 < 1e-18, 1e-18, length2)
    worst = 0.0
    for begin in range(0, len(points), chunk):
        block = points[begin:begin + chunk][:, None, :]
        diff = block - starts[None, :, :]
        t = np.einsum('bmk,mk->bm', diff, vectors) / length2[None, :]
        t = np.clip(t, 0.0, 1.0)
        closest = starts[None, :, :] + t[:, :, None] * vectors[None, :, :]
        distances = np.linalg.norm(block - closest, axis=2).min(axis=1)
        worst = max(worst, float(distances.max()))
    return float(worst)


def _rotation_check(orbit, by_id, k):
    """Really rotate the stored 3D centreline of the rep by R^k, compare to member.

    ``R(x, y, z) = (150 - y, x, z)`` about the board centre ``(75, 75)``.
    The deviation is the symmetric max point-to-polyline distance (mm) between
    the rotated rep samples and the stored member samples, in full XYZ.
    """
    member = _orbit_member_id(orbit, k)
    rep_record = by_id.get(int(orbit['rep']))
    member_record = by_id.get(member)
    if rep_record is None or member_record is None:
        return None
    rep_pts = _centerline_3d(rep_record)
    member_pts = _centerline_3d(member_record)
    rep_2d = _centerline_2d(rep_record)
    member_2d = _centerline_2d(member_record)
    if rep_pts is None or member_pts is None:
        return None
    rotated = np.array(rep_pts, dtype=float, copy=True)
    for _ in range(int(k)):
        # NOTE: build new arrays first; assigning two column slices of the same
        # array from each other would alias and collapse the point set.
        x_new = 150.0 - rotated[:, 1]
        y_new = rotated[:, 0].copy()
        rotated[:, 0] = x_new
        rotated[:, 1] = y_new
    deviation = _polyline_deviation(rotated, member_pts)
    back = _polyline_deviation(member_pts, rotated)
    if deviation is not None and back is not None:
        deviation = max(deviation, back)
    rotated_2d = np.array(rep_2d, dtype=float, copy=True)
    for _ in range(int(k)):
        x_new = 150.0 - rotated_2d[:, 1]
        y_new = rotated_2d[:, 0].copy()
        rotated_2d[:, 0] = x_new
        rotated_2d[:, 1] = y_new
    deviation_2d = O.sample_deviation(rotated_2d.tolist(), member_2d.tolist())
    return dict(k=int(k), route_id=int(member), real=member_2d,
                rotated=rotated_2d, real_3d=member_pts, rotated_3d=rotated,
                deviation=float(deviation), deviation_2d=float(deviation_2d))


def _orbit_max_deviation(orbit, by_id):
    """Max full-XYZ rotation deviation over k=1..3 for one orbit."""
    cache = {}
    worst = 0.0
    for k in (1, 2, 3):
        check = _rotation_check(orbit, by_id, k)
        cache[k] = check
        if check is not None:
            worst = max(worst, check['deviation'])
    return worst, cache


def _context_polylines(records):
    """Faint full-board context for the orbit panels (real 2D route polylines)."""
    index, _route_ids, _segments = _flat_index(records)
    context = {}
    for z, entries in index.items():
        lines = []
        for _rid, primitives in entries:
            line = _polyline(primitives)
            if line is not None and len(line) >= 2:
                lines.append(line)
        if lines:
            context[z] = lines
    return context


def _add_context_xy(ax, context, lw=0.18, alpha=0.05):
    if not context:
        return
    for z in sorted(context):
        ax.add_collection(LineCollection(context[z], colors=[c4_color_for_z(z)],
                                         linewidths=lw, alpha=alpha, zorder=0))


def _z_color_setup():
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    cmap = plt.get_cmap('viridis')
    norm = Normalize(vmin=-0.05, vmax=2.35)
    return cmap, norm, ScalarMappable(norm=norm, cmap=cmap)


def _plot_centerline_by_z(ax, points3d, cmap, norm, lw=1.7, alpha=0.95,
                          zorder=4):
    """Draw a real 3D centreline in XY, coloured by its physical z."""
    if points3d is None or len(points3d) < 2:
        return False
    segments = np.stack([points3d[:-1, :2], points3d[1:, :2]], axis=1)
    z_mid = 0.5 * (points3d[:-1, 2] + points3d[1:, 2])
    collection = LineCollection(segments, cmap=cmap, norm=norm, zorder=zorder,
                                alpha=alpha)
    collection.set_array(z_mid)
    collection.set_linewidth(lw)
    ax.add_collection(collection)
    return True


def _scatter_by_z(ax, points3d, cmap, norm, size=1.6, alpha=0.55, zorder=2):
    if points3d is None or len(points3d) < 1:
        return False
    ax.scatter(points3d[:, 0], points3d[:, 1], c=points3d[:, 2], cmap=cmap,
               norm=norm, s=size, alpha=alpha, linewidths=0, zorder=zorder)
    return True


def _pick_representative_orbits(ctx, count=4):
    orbits = _load_orbits(ctx)
    picked = []
    for plane, kind in CATEGORY_PRIORITY:
        candidates = [orbit for orbit in orbits
                      if str(orbit.get('plane')) == plane
                      and str(orbit.get('kind')) == kind]
        if not candidates:
            continue

        def _length(orbit):
            try:
                return float(ctx.total(int(orbit['rep'])))
            except Exception:
                return 1e9

        candidates.sort(key=lambda orbit: (_length(orbit),
                                           int(orbit['group_id'])))
        picked.append(candidates[len(candidates) // 2])
        if len(picked) >= count:
            break
    if len(picked) < count:
        used = {int(orbit['group_id']) for orbit in picked}
        for orbit in sorted(orbits, key=lambda item: (str(item.get('plane')),
                                                      str(item.get('kind')),
                                                      int(item['group_id']))):
            if int(orbit['group_id']) in used:
                continue
            picked.append(orbit)
            used.add(int(orbit['group_id']))
            if len(picked) >= count:
                break
    return picked


def _figure_four_orbits(path, records, ctx, name):
    by_id = _records_by_id(records)
    context = _context_polylines(records)
    picked = _pick_representative_orbits(ctx, 4)
    fig, axes = plt.subplots(2, 2, figsize=(13.4, 12.6))
    axes = axes.ravel()
    for ax, orbit in zip(axes, picked):
        _add_context_xy(ax, context)
        deviations = []
        checks = {}
        for k in (1, 2, 3):
            check = _rotation_check(orbit, by_id, k)
            checks[k] = check
            if check is not None:
                deviations.append(check['deviation'])
                ax.scatter(check['rotated'][:, 0], check['rotated'][:, 1],
                           s=1.3, c='#111111', alpha=0.45, linewidths=0,
                           zorder=2)
        handles = []
        mapping = []
        for k in (0, 1, 2, 3):
            rid = _orbit_member_id(orbit, k)
            record = by_id.get(rid)
            colour = MEMBER_COLORS[k]
            if record is not None:
                line = _centerline_2d(record, step=0.15)
                if line is not None:
                    ax.plot(line[:, 0], line[:, 1], color=colour, lw=1.6,
                            alpha=0.95, zorder=4)
            direction = _orbit_member_direction(orbit, k)
            handles.append(Line2D([], [], color=colour, lw=1.6,
                                  label='R^%d -> route %d (%s)'
                                  % (k, rid, direction)))
            if k > 0:
                mapping.append('R^%d->%d' % (k, rid))
        handles.append(Line2D([], [], color='#111111', marker='o', ls='none',
                              ms=2.6, label='stored R^0 samples rotated by R^k'))
        _draw_rotation_guides_2d(ax)
        P._style_xy(ax)
        max_dev = max(deviations) if deviations else float('nan')
        ax.set_title('orbit %d: %s / %s -- four real members\n%s | max |dxyz| '
                     '%.4f mm' % (int(orbit['group_id']), orbit['plane'],
                                  orbit['kind'], '  '.join(mapping), max_dev),
                     fontsize=8.2)
        ax.legend(handles=handles, fontsize=5.6, loc='upper right',
                  framealpha=0.7)
    fig.suptitle('%s: representative C4 orbits (one per plane x kind category).\n'
                 'Thin faint grey = full 1024-route board context; solid = the '
                 'four stored members; black dots = stored R^0 centreline really '
                 'rotated by R^k (max full-XYZ deviation in the title).'
                 % name, fontsize=9.8)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.94))


def _figure_rotation_overlay(path, records, ctx, name):
    by_id = _records_by_id(records)
    context = _context_polylines(records)
    candidates = _pick_representative_orbits(ctx, 6)
    # pick the representative orbit with the largest REAL rotation deviation so
    # the check is informative even when a scheme is nearly (but not exactly) C4.
    best_orbit = candidates[0]
    best_dev = -1.0
    best_cache = {}
    for orbit in candidates:
        worst, cache = _orbit_max_deviation(orbit, by_id)
        if worst > best_dev:
            best_dev = worst
            best_orbit = orbit
            best_cache = cache
    orbit = best_orbit
    cmap, norm, mappable = _z_color_setup()
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 12.4))
    fig.subplots_adjust(left=0.06, right=0.90, bottom=0.05, top=0.90,
                        wspace=0.18, hspace=0.20)
    axes = axes.ravel()
    deviations = []
    for k, ax in enumerate(axes):
        _add_context_xy(ax, context)
        check = best_cache.get(k) if k > 0 else _rotation_check(orbit, by_id, 0)
        rid = _orbit_member_id(orbit, k) if k > 0 else int(orbit['rep'])
        if check is None:
            ax.text(75, 75, 'route %d not routed\n(no stored data)' % rid,
                    ha='center', va='center', fontsize=10)
            _draw_rotation_guides_2d(ax)
            P._style_xy(ax)
            ax.set_title('k=%d: route %d -- no stored data' % (k, rid),
                         fontsize=9)
            continue
        _scatter_by_z(ax, check['rotated_3d'], cmap, norm, size=1.5,
                      alpha=0.5, zorder=2)
        _plot_centerline_by_z(ax, check['real_3d'], cmap, norm, lw=1.9,
                              alpha=0.95, zorder=4)
        _draw_rotation_guides_2d(ax)
        P._style_xy(ax)
        if k > 0:
            deviations.append(check['deviation'])
        ax.set_title('k=%d: route %d vs R^%d(route %d) | max |dxyz| %.4f mm '
                     '(xy %.4f)' % (k, rid, k, int(orbit['rep']),
                                    check['deviation'],
                                    check['deviation_2d']), fontsize=8.6)
        ax.legend(handles=[
            Line2D([], [], color=plt.get_cmap('viridis')(0.35), lw=1.9,
                   label='real member k=%d (coloured by z)' % k),
            Line2D([], [], color='#111111', marker='o', ls='none', ms=2.6,
                   label='R^%d(stored R^0) samples (coloured by z)' % k)],
            fontsize=6.8, loc='upper right', framealpha=0.7)
    max_dev = max(deviations) if deviations else float('nan')
    cax = fig.add_axes([0.925, 0.10, 0.014, 0.78])
    fig.colorbar(mappable, cax=cax, label='physical z (mm)')
    fig.suptitle(
        '%s: real C4 rotation check on stored XYZ routes -- orbit %d (%s/%s), '
        'max |dxyz| over k=1..3: %.4f mm\n'
        'Both the real member (line) and the really rotated stored centreline '
        'samples (dots) are coloured by physical z; rule R(x,y,z)=(150-y,x,z).'
        % (name, int(orbit['group_id']), orbit['plane'], orbit['kind'],
           max_dev), fontsize=9.2)
    _finish(fig, path, tight=False)
    return dict(orbit=int(orbit['group_id']), max_deviation=max_dev)


def _figure_layer_usage(path, records, analysis, name, zinfo):
    labels = [item['label'] for item in zinfo]
    zs = [round(float(item['z']), 6) for item in zinfo]
    routes, segs, maxz_routes = [], [], []
    counter = Counter()
    for record in records:
        counter[round(_route_max_z(record), 6)] += 1
    for z in zs:
        info = _per_height(analysis, z)
        routes.append(int(info['routes']))
        segs.append(int(info['segments']))
        maxz_routes.append(int(counter.get(z, 0)))
    positions = np.arange(len(labels))
    width = 0.27
    fig, ax = plt.subplots(figsize=(max(9.6, 0.95 * len(labels) + 5.0), 5.6))
    bars1 = ax.bar(positions - width, routes, width, label='unique routes',
                   color='#1f6fd6')
    bars2 = ax.bar(positions, segs, width, label='flat segments',
                   color='#2f9e44')
    bars3 = ax.bar(positions + width, maxz_routes, width,
                   label='routes with max z here', color='#e03131')
    for bars in (bars1, bars2, bars3):
        for rect in bars:
            height = rect.get_height()
            if height:
                ax.text(rect.get_x() + rect.get_width() / 2.0, height,
                        '%d' % int(height), ha='center', va='bottom',
                        fontsize=5.6, rotation=90)
    ax.set_xticks(positions)
    ax.set_xticklabels(['%s\nz=%.2f' % (label, z)
                        for label, z in zip(labels, zs)], fontsize=6.8)
    ax.set_ylabel('count')
    ax.set_ylim(0.0, max(routes + segs + maxz_routes) * 1.18 + 1.0)
    ax.grid(alpha=0.15, axis='y')
    ax.legend(fontsize=7.5, loc='upper right')
    used_layers = [item['label'] for item, count in zip(zinfo[2:], routes[2:])
                   if item['layer'] is not None and count]
    unused = [item['label'] for item, count in zip(zinfo[2:], routes[2:])
              if item['layer'] is not None and not count]
    ax.set_title('%s: physical-height usage (%d routes, %d flat segments)'
                 '\nrouting layers used: %s | unused: %s'
                 % (name, len(records), int(sum(segs)),
                    ', '.join(used_layers) if used_layers else 'none',
                    ', '.join(unused) if unused else 'none'), fontsize=8.8)
    _finish(fig, path)


def _draw_layer_tile(path, label, z, entries, analysis, name,
                     highlight_ids=None):
    fig, ax = plt.subplots(figsize=(5.3, 5.1))
    highlight_ids = set(highlight_ids or ())
    normal, highlight = [], []
    for rid, primitives in entries:
        if rid in highlight_ids:
            highlight.append(primitives)
        else:
            normal.append(primitives)
    _add_xy_collection(ax, normal, c4_color_for_z(z), lw=0.35, alpha=0.34,
                       zorder=2)
    if highlight:
        _add_xy_collection(ax, highlight, '#e03131', lw=0.9, alpha=0.9,
                           zorder=4)
    events = [event for event in analysis['events']
              if abs(float(event['z']) - z) <= 1e-9]
    _add_event_points(ax, events)
    _draw_rotation_guides_2d(ax)
    P._style_xy(ax)
    info = _per_height(analysis, z)
    ax.set_title('%s  z=%.2f mm\nunique routes=%d | flat segments=%d | '
                 'crossing pairs=%d | events=%d'
                 % (label, z, int(info['routes']), int(info['segments']),
                    int(info['pairs']), int(info['events'])), fontsize=8.4)
    _finish(fig, path, dpi=DPI_TILE)


def _figure_all_layers_contact_sheet(figdir, records, analysis, name, zinfo):
    index, _route_ids, _segments = _flat_index(records)
    tile_dir = _ensure_dir(Path(figdir) / '_layer_tiles')
    entries = []
    for position, item in enumerate(zinfo):
        z = round(float(item['z']), 6)
        tile_name = '%02d_%s.png' % (position, _slug(item['label']))
        tile_path = tile_dir / tile_name
        try:
            _draw_layer_tile(tile_path, item['label'], z,
                             index.get(z, []), analysis, name)
        except Exception as exc:  # keep the sheet complete
            _write_error_figure(tile_path, 'layer tile %s' % item['label'],
                                exc, name)
        entries.append((tile_name, '%s  z=%.2f' % (item['label'], z)))
    sheet_path = Path(figdir) / '06_all_layers_contact_sheet.png'
    _contact_sheet(tile_dir, entries, sheet_path,
                   title='%s: per-physical-height 2D tiles (unified 0..150 mm '
                         'x/y axes; each tile title states unique routes / flat '
                         'segments / crossing pairs / crossing events)' % name,
                   cols=3)
    return sheet_path


def _contact_sheet(image_dir, entries, out_path, title='', cols=3,
                   thumb=(780, 660)):
    """PIL contact sheet, same layout style as ``e1.plots.make_contact_sheet``.

    ``entries`` is a list of ``(relative_image_name, label)`` pairs, so the
    caption under every tile can be a human readable layer label instead of the
    file name (the e1 helper labels with the file name only).
    """
    from PIL import Image, ImageDraw, ImageFont
    image_dir = Path(image_dir)
    images = [Image.open(image_dir / name).convert('RGB') for name, _ in entries]
    width, height = thumb
    rows = int(math.ceil(len(images) / float(cols)))
    header = 40 if title else 0
    canvas = Image.new('RGB', (cols * width + 40,
                               header + rows * (height + 30) + 20), 'white')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 20)
        header_font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 22)
    except Exception:
        font = ImageFont.load_default()
        header_font = font
    if title:
        draw.text((12, 8), str(title), font=header_font, fill='#212529')
    for index, (image, (_name, label)) in enumerate(zip(images, entries)):
        image.thumbnail((width - 8, height - 8), Image.LANCZOS)
        row, col = divmod(index, cols)
        x = 10 + col * width
        y = header + 10 + row * (height + 30)
        canvas.paste(image, (x, y))
        draw.text((x + 8, y + height - 20), str(label), font=font,
                  fill='#333333')
    canvas.save(out_path, optimize=True)
    return out_path


def _figure_crossing_hotspots(path, records, analysis, name, zinfo, max_panels=12):
    label_map = _z_label_map(zinfo)
    events_by_z = defaultdict(list)
    for event in analysis['events']:
        events_by_z[round(float(event['z']), 6)].append(event)
    heights = sorted(events_by_z)
    if not heights:
        fig, ax = plt.subplots(figsize=(7.6, 6.8))
        ax.text(75, 75, 'no crossing events in the stored routes',
                ha='center', va='center', fontsize=12)
        _draw_rotation_guides_2d(ax)
        P._style_xy(ax)
        ax.set_title('%s: crossing hotspots -- no events' % name, fontsize=10)
        _finish(fig, path)
        return
    if len(heights) > max_panels:
        heights = sorted(heights,
                         key=lambda value: -len(events_by_z[value]))[:max_panels]
        heights.sort()
    cols = 2 if len(heights) <= 4 else 3
    rows = int(math.ceil(len(heights) / float(cols)))
    fig, axes = plt.subplots(rows, cols,
                             figsize=(4.45 * cols, 4.15 * rows),
                             squeeze=False)
    for ax, z in zip(axes.ravel(), heights):
        events = events_by_z[z]
        label = label_map.get(round(z, 6), 'z=%.2f' % z)
        hexbin = ax.hexbin([event['x'] for event in events],
                           [event['y'] for event in events],
                           gridsize=38, cmap='Reds', mincnt=1)
        fig.colorbar(hexbin, ax=ax, fraction=0.046, pad=0.03,
                     label='crossing events')
        P._style_xy(ax)
        info = _per_height(analysis, z)
        ax.set_title('%s  z=%.2f mm | events=%d | unique pairs=%d'
                     % (label, z, len(events), int(info['pairs'])),
                     fontsize=8.2)
    for ax in axes.ravel()[len(heights):]:
        ax.axis('off')
    fig.suptitle('%s: crossing hotspots by physical height (%d events, '
                 '%d unique crossing pairs in total)'
                 % (name, len(analysis['events']), analysis['n_unique_pairs']),
                 fontsize=10.0)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.95))


def _category_bar_pairs(analysis):
    values = [analysis['n_unique_pairs'], analysis['z1_pairs'],
              analysis['z2_pairs'], analysis['high_pairs']]
    return values


def _figure_before_after(path, records, analysis, name, baseline_records,
                         baseline_analysis, baseline_name):
    labels = ['global unique', 'Z1 pairs', 'Z2 pairs', 'high layers']
    after = _category_bar_pairs(analysis)
    if baseline_records is None or baseline_analysis is None:
        fig, ax = plt.subplots(figsize=(10.2, 5.8))
        ax.text(0.5, 0.5, 'baseline records: not provided\n'
                          '(no comparison numbers are invented)',
                ha='center', va='center', fontsize=13,
                transform=ax.transAxes)
        ax.axis('off')
        ax.set_title('%s: before/after -- baseline not provided' % name,
                     fontsize=11)
        _finish(fig, path)
        return
    before = _category_bar_pairs(baseline_analysis)
    positions = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.8))
    bars_before = axes[0].bar(positions - 0.2, before, 0.4,
                              label=baseline_name, color='#868e96')
    bars_after = axes[0].bar(positions + 0.2, after, 0.4, label=name,
                             color='#2f9e44')
    for bars in (bars_before, bars_after):
        for rect in bars:
            axes[0].text(rect.get_x() + rect.get_width() / 2.0,
                         rect.get_height(), '%d' % int(rect.get_height()),
                         ha='center', va='bottom', fontsize=7)
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(labels, fontsize=8.5)
    axes[0].set_ylabel('count')
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.15, axis='y')
    axes[0].set_title('crossing statistics', fontsize=10)
    for analysis_item, title, color in (
            (baseline_analysis, '%s z=0' % baseline_name, '#868e96'),
            (analysis, '%s z=0' % name, '#e03131')):
        z1 = [event for event in analysis_item['events']
              if abs(float(event['z']) - Z1) <= 1e-9]
        axes[1].scatter([event['x'] for event in z1],
                        [event['y'] for event in z1], s=3, alpha=0.3,
                        color=color, label='%s (%d)' % (title, len(z1)))
    axes[1].set_xlim(*X_RANGE)
    axes[1].set_ylim(*Y_RANGE)
    axes[1].set_aspect('equal')
    axes[1].grid(alpha=0.12)
    axes[1].set_title('Z1 interface crossing positions (real audit events)',
                      fontsize=10)
    axes[1].set_xlabel('x (mm)')
    axes[1].set_ylabel('y (mm)')
    axes[1].legend(fontsize=7.5, loc='upper right', framealpha=0.75)
    delta = after[0] - before[0]
    fig.suptitle('%s: before/after vs %s -- global unique crossings %d -> %d '
                 '(%+.1f%%)'
                 % (name, baseline_name, before[0], after[0],
                    100.0 * delta / before[0] if before[0] else float('nan')),
                 fontsize=10.5)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.94))


def _figure_transitions_3d(path, records, analysis, name, max_layer):
    index, _route_ids, _segments = _flat_index(records)
    max_z = _records_max_z(records)
    transitions = _transition_segments_3d(records)
    fig = plt.figure(figsize=(10.6, 8.4))
    ax = fig.add_subplot(111, projection='3d')
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.91)
    _add_board_frame_3d(ax)
    _add_flats_3d(ax, index, alpha=0.055, lw=0.18)
    if transitions:
        collection = Line3DCollection(transitions, colors=['#e8590c'],
                                      linewidths=0.8, alpha=0.55)
        ax.add_collection3d(collection)
    _style_3d(ax, max(max_z, 0.6))
    dz_values = sorted({round(abs(float(part['z1']) - float(part['z0'])), 6)
                        for record in records
                        for part in record.get('parts') or []
                        if part.get('kind') == 'transition'})
    ax.set_title(
        '%s: 3D S-transition set highlighted in orange\n'
        '%d transitions | distinct |dz| = %s mm | target layers L2..L%d | '
        'max z %.2f mm'
        % (name, len(transitions),
           ', '.join('%.2f' % value for value in dz_values[:8]),
           int(max_layer), max_z), fontsize=9.0, pad=4)
    _finish(fig, path, tight=False, bbox=None)


def _count_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    try:
        return len(value)
    except TypeError:
        return None


def _format_report_value(value):
    if value is None:
        return 'n/a'
    if isinstance(value, (bool, np.bool_)):
        return 'True' if value else 'False'
    if isinstance(value, (int, np.integer)):
        return '%d' % int(value)
    if isinstance(value, (float, np.floating)):
        return '%.6g' % float(value)
    if isinstance(value, str):
        return value[:118] + ('...' if len(value) > 118 else '')
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text[:118] + ('...' if len(text) > 118 else '')
    if isinstance(value, (list, tuple)):
        if not value:
            return '0'
        if len(value) <= 3:
            return json.dumps([_format_report_value(item) for item in value],
                              ensure_ascii=False)[:118]
        return 'n=%d' % len(value)
    return str(value)[:118]


def _report_error_count(report, key):
    """Authoritative error count: prefer ``*_error_count``, else len(list)."""
    count_key = key.replace('_errors', '_error_count')
    if count_key in report:
        value = _count_value(report.get(count_key))
        if value is not None:
            return value
    return _count_value(report.get(key))


def _figure_c4_validation(path, name, c4_report):
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 6.2),
                             gridspec_kw={'width_ratios': [1.0, 1.05]})
    ax_bar, ax_text = axes
    if not isinstance(c4_report, dict) or not c4_report:
        for ax in axes:
            ax.axis('off')
        ax_text.text(0.5, 0.55,
                     'C4 validation report: not provided\n\n'
                     'The independent C4 validator did not return a report for '
                     'this scheme.\nNo numbers are invented in this figure.',
                     ha='center', va='center', fontsize=12.5,
                     transform=ax_text.transAxes)
        fig.suptitle('%s: strict-C4 validation audit -- not provided' % name,
                     fontsize=11)
        _finish(fig, path)
        return
    counts = {key: _report_error_count(c4_report, key)
              for key in C4_ERROR_KEYS}
    labels = ['orbit size', 'endpoint rotation', 'layer symmetry',
              'transition symmetry', 'geometry symmetry']
    values = [counts[key] if counts[key] is not None else 0
              for key in C4_ERROR_KEYS]
    numeric = [1 if counts[key] is not None else 0 for key in C4_ERROR_KEYS]
    positions = np.arange(len(labels))
    colours = ['#2f9e44' if value == 0 else '#e03131' for value in values]
    bars = ax_bar.bar(positions, values, 0.55, color=colours)
    for rect, count in zip(bars, counts.values()):
        ax_bar.text(rect.get_x() + rect.get_width() / 2.0,
                    max(rect.get_height(), 0.04),
                    'n/a' if count is None else '%d' % int(count),
                    ha='center', va='bottom', fontsize=9.5)
    ax_bar.set_xticks(positions)
    ax_bar.set_xticklabels(labels, fontsize=7.6, rotation=18, ha='right')
    ax_bar.set_ylabel('error count', fontsize=9)
    ax_bar.set_title('validator error counts (green = 0)', fontsize=10)
    ax_bar.grid(alpha=0.15, axis='y')
    all_zero = bool(numeric) and all(value == 0 for value in values)
    ax_bar.set_ylim(0.0, 1.15 if all_zero else max(values + [1]) * 1.25)
    if all_zero:
        ax_bar.text(0.5, 0.72,
                    'all five C4 error counts are 0\n(symmetry PASS)',
                    ha='center', va='center', fontsize=11.5, color='#2b8a3e',
                    transform=ax_bar.transAxes)
    if not any(numeric):
        ax_bar.text(0.5, 0.5, 'report provided but no numeric error fields\n'
                              '(see summary on the right)',
                    ha='center', va='center', fontsize=10,
                    transform=ax_bar.transAxes)
    symmetry_pass = c4_report.get('symmetry_pass')
    pass_text = ('PASS' if symmetry_pass is True else
                 ('FAIL' if symmetry_pass is False else 'n/a'))
    max_dev = c4_report.get('maximum_xyz_deviation_mm')
    headline = ('total routes: %s | total orbits: %s | max |dxyz|: %s mm'
                % (_format_report_value(c4_report.get('total_routes')),
                   _format_report_value(c4_report.get('total_orbits')),
                   _format_report_value(max_dev)))
    curated = [
        ('schema', c4_report.get('schema')),
        ('validator', c4_report.get('validator')),
        ('total_routes', c4_report.get('total_routes')),
        ('total_orbits', c4_report.get('total_orbits')),
        ('max_layer', c4_report.get('max_layer')),
        ('maximum_xyz_deviation_mm', max_dev),
        ('symmetry_pass', symmetry_pass),
        ('failed_orbit_count', c4_report.get('failed_orbit_count')),
        ('failed_orbit_ids', c4_report.get('failed_orbit_ids')),
        ('worst_geometry_pair', c4_report.get('worst_geometry_pair')),
        ('skipped_check_count', c4_report.get('skipped_check_count')),
        ('unrouted_route_ids', c4_report.get('unrouted_route_ids')),
        ('tolerances', c4_report.get('tolerances')),
    ]
    lines = []
    for key in C4_ERROR_KEYS:
        lines.append('%-30s %s' % (key, _format_report_value(
            _report_key_value(c4_report, key))))
    for key, value in curated:
        if value is None:
            continue
        lines.append('%-30s %s' % (key, _format_report_value(value)))
    ax_text.axis('off')
    ax_text.set_title('audit summary (symmetry_pass = %s)' % pass_text,
                      fontsize=10,
                      color=('#2b8a3e' if symmetry_pass is True else
                             ('#c92a2a' if symmetry_pass is False else
                              '#495057')))
    ax_text.text(0.01, 0.99, 'maximum_xyz_deviation_mm = %s'
                 % _format_report_value(max_dev), ha='left', va='top',
                 fontsize=10.5, transform=ax_text.transAxes,
                 color='#212529')
    ax_text.text(0.01, 0.90, '\n'.join(lines), ha='left', va='top',
                 fontsize=7.2, family='monospace', transform=ax_text.transAxes)
    fig.suptitle('%s: strict-C4 validation audit -- %s\n%s'
                 % (name, pass_text, headline), fontsize=10.5)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.93))


def _report_key_value(report, key):
    """Compact value of a report key (lists -> count + first few ids)."""
    value = report.get(key)
    if isinstance(value, (list, tuple)):
        if not value:
            return 0
        head = ', '.join(str(item) for item in value[:4])
        return 'n=%d [%s%s]' % (len(value), head,
                                ', ...' if len(value) > 4 else '')
    return value


# ---------------------------------------------------------------------------
# save / fallback
# ---------------------------------------------------------------------------
def _finish(fig, path, dpi=DPI, rect=None, tight=True, bbox='tight'):
    try:
        if rect is not None:
            fig.tight_layout(rect=rect)
        elif tight:
            fig.tight_layout()
    except Exception:
        pass
    try:
        if bbox:
            fig.savefig(path, dpi=dpi, bbox_inches=bbox)
        else:
            fig.savefig(path, dpi=dpi)
    finally:
        plt.close(fig)


def _write_error_figure(path, title, exc, name=''):
    """Fallback PNG so the mandatory figure set is always complete."""
    try:
        fig, ax = plt.subplots(figsize=(8.0, 5.0))
        ax.axis('off')
        text = '%s\n%s\n\nERROR while drawing: %s\n%s' % (
            name, title, type(exc).__name__, str(exc))
        ax.text(0.5, 0.5, text, ha='center', va='center', fontsize=9,
                transform=ax.transAxes, wrap=True)
        _finish(fig, path, dpi=110)
    except Exception:
        plt.close('all')


# ---------------------------------------------------------------------------
# public: geometry figures
# ---------------------------------------------------------------------------
def geometry_figures(folder, records, ctx, *, name, c4_report=None,
                     baseline_records=None, baseline_name='E1-BASE',
                     max_layer=None, highlight_ids=None, log=print):
    """Write the 10 mandatory per-scheme C4 figures under ``folder/figures/``.

    Parameters
    ----------
    folder : str | Path
        Per-experiment output directory (``figures/`` is created inside).
    records : list[dict]
        Real routed records of this scheme (``status='routed'``), with
        ``parts`` carrying the XYZ geometry.
    ctx : four_side_1024.e1.core.Ctx
        Shared context (route categories used by the crossing audit).
    name : str
        Scheme label used in titles (e.g. ``'C4-11L'``).  A ``<n>L`` token also
        fixes the number of stack layers (and therefore the per-layer tiles).
    c4_report : dict | None
        Report of the independent strict-C4 validator.  ``None`` renders
        "not provided"; values are never invented.
    baseline_records : list[dict] | None
        Baseline routes for the before/after comparison (e.g. E1-BASE).
    baseline_name : str
        Label of the baseline.
    max_layer : int | None
        Optional override of the highest routing layer (default: parsed from
        ``name``, else the highest layer observed in the records).
    highlight_ids : iterable[int] | None
        Optional route ids highlighted red in the per-layer tiles.
    log : callable
        Progress logger (``print`` by default).

    Returns
    -------
    dict
        ``{figure_stem: absolute path}`` for the 10 mandatory figures plus
        ``'_figures_dir'`` and, only when something failed, ``'_errors'``.
    """
    started = time.perf_counter()
    folder = _ensure_dir(folder)
    figdir = _ensure_dir(folder / 'figures')
    records = _as_records(records)
    if not records:
        raise ValueError('geometry_figures: no routed records given')
    baseline = _as_records(baseline_records) if baseline_records is not None \
        else None
    if baseline is not None and not baseline:
        baseline = None
    max_layer = _max_routing_layer(name, records, c4_report, max_layer)
    zinfo = _z_info(max_layer, records)
    analysis = _audit(records, ctx)
    baseline_analysis = _audit(baseline, ctx) if baseline is not None else None
    stats = C.bar(records)
    errors = {}
    outputs = {'_figures_dir': str(figdir)}

    def render(key, filename, draw):
        path = figdir / filename
        started_figure = time.perf_counter()
        try:
            draw(path)
            outputs[key] = str(path.resolve())
            log('[c4 plots] %-32s %6.2fs' % (filename,
                                             time.perf_counter() - started_figure))
        except Exception as exc:  # never let one figure abort the set
            errors[key] = '%s: %s' % (type(exc).__name__, exc)
            _write_error_figure(path, key, exc, name)
            outputs[key] = str(path.resolve())
            log('[c4 plots] %-32s FAILED %s' % (filename, errors[key]))
            log(traceback.format_exc())

    render('01_overall_3d', '01_overall_3d.png',
           lambda path: _figure_overall_3d(path, records, analysis, ctx, name,
                                           zinfo, max_layer, stats))
    render('02_overall_xy', '02_overall_xy.png',
           lambda path: _figure_overall_xy(path, records, analysis, name,
                                           zinfo, stats))
    render('03_c4_four_orbits', '03_c4_four_orbits.png',
           lambda path: _figure_four_orbits(path, records, ctx, name))
    render('04_c4_rotation_overlay', '04_c4_rotation_overlay.png',
           lambda path: _figure_rotation_overlay(path, records, ctx, name))
    render('05_layer_usage', '05_layer_usage.png',
           lambda path: _figure_layer_usage(path, records, analysis, name,
                                            zinfo))
    render('06_all_layers_contact_sheet', '06_all_layers_contact_sheet.png',
           lambda path: _figure_all_layers_contact_sheet(
               figdir, records, analysis, name, zinfo))
    render('07_crossing_hotspots', '07_crossing_hotspots.png',
           lambda path: _figure_crossing_hotspots(path, records, analysis,
                                                  name, zinfo))
    render('08_before_after', '08_before_after.png',
           lambda path: _figure_before_after(path, records, analysis, name,
                                             baseline, baseline_analysis,
                                             baseline_name))
    render('09_transitions_3d', '09_transitions_3d.png',
           lambda path: _figure_transitions_3d(path, records, analysis, name,
                                               max_layer))
    render('10_c4_validation', '10_c4_validation.png',
           lambda path: _figure_c4_validation(path, name, c4_report))
    if highlight_ids:
        (figdir / '_highlight_ids.txt').write_text(
            '\n'.join(str(int(rid)) for rid in sorted(highlight_ids)),
            encoding='utf-8')
    if errors:
        outputs['_errors'] = dict(errors)
    log('[c4 plots] geometry_figures(%s) done in %.1fs -> %s'
        % (name, time.perf_counter() - started, figdir))
    return outputs


# ---------------------------------------------------------------------------
# public: orbit overlay
# ---------------------------------------------------------------------------
def orbit_overlay_figure(folder, records, ctx, name, orbit_ids=None,
                         log=print):
    """Overlay figure: real members vs really-rotated stored centrelines.

    Each row is one C4 orbit, each column one rotation power k=0..3.  The
    coloured line is the stored centreline of member *k*; the black dots are the
    stored centreline of the orbit representative actually rotated by ``k``
    applications of ``R(x, y) = (150 - y, x)``.  Deviations are the symmetric
    max nearest-point distance between those point sets (mm).

    Parameters
    ----------
    folder : str | Path
        Per-experiment output directory (figure goes to ``folder/figures/``).
    orbit_ids : iterable[int] | None
        C4 orbit (group) ids to show; default = 2 representative orbits.

    Returns
    -------
    str
        Absolute path of the written PNG.
    """
    folder = _ensure_dir(folder)
    figdir = _ensure_dir(folder / 'figures')
    records = _as_records(records)
    by_id = _records_by_id(records)
    orbits = _load_orbits(ctx)
    wanted = [int(value) for value in (orbit_ids or [])]
    if wanted:
        mapping = {int(orbit['group_id']): orbit for orbit in orbits}
        selected = [mapping[gid] for gid in wanted if gid in mapping]
    else:
        selected = _pick_representative_orbits(ctx, 2)
    selected = selected[:4]
    if not selected:
        raise ValueError('orbit_overlay_figure: no matching orbits')
    rows = len(selected)
    fig, axes = plt.subplots(rows, 4, figsize=(16.0, 3.75 * rows),
                             squeeze=False)
    context = _context_polylines(records)
    for row, orbit in enumerate(selected):
        deviations = []
        checks = {k: _rotation_check(orbit, by_id, k) for k in range(4)}
        for k in range(4):
            ax = axes[row][k]
            check = checks.get(k)
            rid = _orbit_member_id(orbit, k)
            _add_context_xy(ax, context)
            if check is None:
                ax.text(75, 75, 'route %d\nnot routed' % rid,
                        ha='center', va='center', fontsize=9)
                _draw_rotation_guides_2d(ax)
                P._style_xy(ax)
                ax.set_title('orbit %d | k=%d -- no data'
                             % (int(orbit['group_id']), k), fontsize=7.6)
                continue
            ax.scatter(check['rotated'][:, 0], check['rotated'][:, 1], s=1.2,
                       c='#111111', alpha=0.45, linewidths=0, zorder=2)
            ax.plot(check['real'][:, 0], check['real'][:, 1],
                    color=MEMBER_COLORS[k], lw=1.7, alpha=0.95, zorder=4)
            _draw_rotation_guides_2d(ax)
            P._style_xy(ax)
            ax.set_title('R^%d: route %d vs rotated store | max |dxyz| %.4f mm'
                         % (k, rid, check['deviation']), fontsize=7.6)
            if k > 0:
                deviations.append(check['deviation'])
        max_dev = max(deviations) if deviations else float('nan')
        axes[row][0].set_ylabel(
            'orbit %d\n%s/%s\nmax |dxyz| %.4f mm'
            % (int(orbit['group_id']), orbit['plane'], orbit['kind'], max_dev),
            fontsize=8.0)
    fig.suptitle('%s: C4 orbit overlay -- real stored members vs really rotated '
                 'centrelines (faint grey = full board context)\n'
                 'Black dots = stored 3D centreline of R^0 rotated k times by '
                 'R(x,y,z)=(150-y,x,z); max |dxyz| is a full-XYZ point-to-curve '
                 'distance. No symmetry is fabricated.'
                 % name, fontsize=9.4)
    path = figdir / ('c4_orbit_overlay_%s.png' % _slug(name))
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.94))
    log('[c4 plots] orbit overlay -> %s' % path)
    return str(path.resolve())


# ---------------------------------------------------------------------------
# public: summary figures
# ---------------------------------------------------------------------------
def _as_rows(rows):
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    out = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def _normalise_rows(rows):
    normalised = []
    for row in _as_rows(rows):
        item = dict(row)
        layers = item.get('layers')
        if layers is None:
            layers = _layer_count_from_name(item.get('experiment'))
        if layers is None:
            max_layer = item.get('max_layer') or item.get('layer_count')
            try:
                layers = int(max_layer)
            except (TypeError, ValueError):
                layers = 7
        try:
            item['layers'] = int(layers)
        except (TypeError, ValueError):
            item['layers'] = 7
        if item.get('transitions') is None:
            item['transitions'] = item.get('n_transitions')
        if item.get('max_z_mm') is None:
            item['max_z_mm'] = item.get('max_physical_z_mm')
        normalised.append(item)
    normalised.sort(key=lambda item: (int(item['layers']),
                                      str(item.get('experiment', ''))))
    return normalised


def _row_color(row):
    layers = int(row.get('layers') or 7)
    if layers in LAYER_EXPERIMENT_COLORS:
        return LAYER_EXPERIMENT_COLORS[layers]
    return ROUTING_COLORS[(layers - 2) % len(ROUTING_COLORS)]


def _numeric_rows(rows, key):
    out = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            out.append((row, float(value)))
        except (TypeError, ValueError):
            continue
    return out


def _e1_reference(e1_row, key):
    if not isinstance(e1_row, dict):
        return None
    value = e1_row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _layer_axis(ax, rows, xlabel='total stack layers (L1 interface + L2..L_n)'):
    values = sorted({int(row['layers']) for row in rows})
    ax.set_xticks(values)
    ax.set_xticklabels([('%dL' % value) for value in values], fontsize=8.5)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.grid(alpha=0.18)


def _placeholder_figure(path, title, message):
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    ax.axis('off')
    ax.text(0.5, 0.5, message, ha='center', va='center', fontsize=12,
            transform=ax.transAxes, wrap=True)
    ax.set_title(title, fontsize=11)
    _finish(fig, path)


def _figure_layer_count_vs_crossings(path, rows, e1_row):
    numeric = _numeric_rows(rows, 'unique_crossing_pairs')
    if not numeric:
        _placeholder_figure(path, 'C4 layer-count vs crossings',
                            'no rows with unique_crossing_pairs provided')
        return
    fig, ax = plt.subplots(figsize=(8.8, 5.8))
    xs = [row['layers'] for row, _value in numeric]
    ys = [value for _row, value in numeric]
    ax.plot(xs, ys, '-o', color='#e03131', lw=1.6, ms=8, zorder=3)
    for row, value in numeric:
        ax.annotate('%d' % int(value), (row['layers'], value),
                    textcoords='offset points', xytext=(0, 9),
                    ha='center', fontsize=8.2)
    e1_value = _e1_reference(e1_row, 'unique_crossing_pairs')
    if e1_value is not None:
        ax.axhline(e1_value, ls='--', color='#868e96', lw=1.3,
                   label='%s reference (%.0f)'
                   % (e1_row.get('experiment', 'E1'), e1_value))
        ax.legend(fontsize=8.5, loc='best')
    for layer in sorted({row['layers'] for row, _value in numeric}):
        points = [(row, value) for row, value in numeric
                  if row['layers'] == layer]
        row, value = points[0]
        ax.scatter([layer], [value], s=95, color=_row_color(row),
                   edgecolor='white', linewidth=0.8, zorder=4)
    _layer_axis(ax, rows)
    ax.set_ylabel('unique crossing pairs', fontsize=9.5)
    ax.set_title('C4 layer-count study: unique crossing pairs vs number of '
                 'stack layers\n(lower is better; E1 asymmetric 3594 is the '
                 'reference)', fontsize=10.2)
    _finish(fig, path)


def _figure_layer_count_vs_length(path, rows, e1_row):
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.6))
    numeric = _numeric_rows(rows, 'total_length_mm')
    if not numeric:
        for ax in axes:
            ax.axis('off')
        axes[0].text(0.5, 0.5, 'no rows with total_length_mm provided',
                     ha='center', va='center', fontsize=11,
                     transform=axes[0].transAxes)
        fig.suptitle('C4 layer-count study: total waveguide length', fontsize=11)
        _finish(fig, path)
        return
    xs = [row['layers'] for row, _value in numeric]
    ys = [value for _row, value in numeric]
    axes[0].plot(xs, ys, '-o', color='#2f9e44', lw=1.6, ms=8)
    for row, value in numeric:
        axes[0].annotate('%.0f' % value, (row['layers'], value),
                         textcoords='offset points', xytext=(0, 9),
                         ha='center', fontsize=8)
    e1_value = _e1_reference(e1_row, 'total_length_mm')
    if e1_value is not None:
        axes[0].axhline(e1_value, ls='--', color='#868e96', lw=1.2,
                        label='%s reference (%.0f mm)'
                        % (e1_row.get('experiment', 'E1'), e1_value))
        axes[0].legend(fontsize=8)
    _layer_axis(axes[0], rows)
    axes[0].set_ylabel('total waveguide length (mm)', fontsize=9.5)
    axes[0].set_title('total length', fontsize=10)
    hours = _numeric_rows(rows, 'fabrication_hours')
    if hours:
        hx = [row['layers'] for row, _value in hours]
        hy = [value for _row, value in hours]
        axes[1].plot(hx, hy, '-s', color='#e8590c', lw=1.6, ms=7)
        for row, value in hours:
            axes[1].annotate('%.2f' % value, (row['layers'], value),
                             textcoords='offset points', xytext=(0, 9),
                             ha='center', fontsize=8)
        e1_hours = _e1_reference(e1_row, 'fabrication_hours')
        if e1_hours is not None:
            axes[1].axhline(e1_hours, ls='--', color='#868e96', lw=1.2,
                            label='%s reference (%.2f h)'
                            % (e1_row.get('experiment', 'E1'), e1_hours))
            axes[1].legend(fontsize=8)
        _layer_axis(axes[1], rows)
        axes[1].set_ylabel('fabrication time (h @ 1 mm/s)', fontsize=9.5)
        axes[1].set_title('fabrication hours', fontsize=10)
    else:
        axes[1].axis('off')
        axes[1].text(0.5, 0.5, 'no rows with fabrication_hours',
                     ha='center', va='center', fontsize=10,
                     transform=axes[1].transAxes)
    fig.suptitle('C4 layer-count study: waveguide length and fabrication time',
                 fontsize=11)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.93))


def _figure_layer_count_vs_max_height(path, rows, e1_row):
    numeric = _numeric_rows(rows, 'max_z_mm')
    fig, ax = plt.subplots(figsize=(8.8, 5.8))
    if numeric:
        xs = [row['layers'] for row, _value in numeric]
        ys = [value for _row, value in numeric]
        ax.plot(xs, ys, '-o', color='#7048e8', lw=1.7, ms=8,
                label='max physical Z used by any route (real data)')
        for row, value in numeric:
            ax.annotate('%.2f mm' % value, (row['layers'], value),
                        textcoords='offset points', xytext=(0, 10),
                        ha='center', fontsize=8)
        for row, _value in numeric:
            layer = int(row['layers'])
            if layer in LY.HEIGHTS:
                ax.scatter([layer], [float(LY.layer_z(layer))], marker='_',
                           s=260, color='#495057', zorder=3)
        # theoretical top of the available stack L2..L_n
        layers = sorted({int(row['layers']) for row in rows
                         if int(row['layers']) in LY.HEIGHTS})
        if layers:
            ax.plot(layers, [float(LY.layer_z(layer)) for layer in layers],
                    ls=':', color='#495057', lw=1.2,
                    label='available stack top L_n (0.15 mm pitch above Z2)')
        e1_value = _e1_reference(e1_row, 'max_z_mm')
        if e1_value is not None:
            ax.axhline(e1_value, ls='--', color='#868e96', lw=1.2,
                       label='%s reference (%.2f mm)'
                       % (e1_row.get('experiment', 'E1'), e1_value))
        ax.legend(fontsize=8, loc='best')
    else:
        ax.axis('off')
        ax.text(0.5, 0.5, 'no rows with max_z_mm provided', ha='center',
                va='center', fontsize=11, transform=ax.transAxes)
    _layer_axis(ax, rows)
    ax.set_ylabel('max physical z (mm)', fontsize=9.5)
    ax.set_title('C4 layer-count study: max physical height used vs the '
                 'available stack top', fontsize=10.2)
    _finish(fig, path)


def _fmt_metric(value):
    """Compact human-readable number for figure annotations."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(value):
        return 'n/a'
    magnitude = abs(value)
    if magnitude >= 100.0:
        return '%.0f' % value
    if magnitude >= 1.0:
        return '%.2f' % value
    return '%.3g' % value


def _figure_c4_vs_e1(path, rows, e1_row):
    metrics = [('unique_crossing_pairs', 'unique crossing pairs', '#e03131'),
               ('total_length_mm', 'total length (mm)', '#2f9e44'),
               ('fabrication_hours', 'fabrication hours', '#e8590c'),
               ('max_z_mm', 'max physical Z (mm)', '#7048e8')]
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 10.2))
    axes = axes.ravel()
    e1_name = (e1_row or {}).get('experiment', 'E1') \
        if isinstance(e1_row, dict) else 'E1'
    for ax, (key, label, color) in zip(axes, metrics):
        numeric = _numeric_rows(rows, key)
        if not numeric:
            ax.axis('off')
            ax.text(0.5, 0.5, 'no rows with %s' % key, ha='center',
                    va='center', fontsize=10, transform=ax.transAxes)
            ax.set_title(label, fontsize=10)
            continue
        positions = np.arange(len(numeric))
        values = [value for _row, value in numeric]
        colors = [_row_color(row) for row, _value in numeric]
        bars = ax.bar(positions, values, 0.62, color=colors)
        for rect, value, (row, _value) in zip(bars, values, numeric):
            ax.text(rect.get_x() + rect.get_width() / 2.0,
                    rect.get_height(), _fmt_metric(value), ha='center',
                    va='bottom', fontsize=7.6)
        ax.set_xticks(positions)
        ax.set_xticklabels(['%s\n%dL' % (str(row.get('experiment', '?')),
                                         row['layers'])
                            for row, _value in numeric], fontsize=7.4)
        e1_value = _e1_reference(e1_row, key)
        if e1_value is not None:
            ax.axhline(e1_value, ls='--', color='#868e96', lw=1.3,
                       label='%s reference (%s)'
                       % (e1_name, _fmt_metric(e1_value)))
            ax.legend(fontsize=7.8, loc='best')
        ax.grid(alpha=0.15, axis='y')
        ax.set_title(label, fontsize=10)
        ax.set_ylabel(label, fontsize=8.5)
        if key in ('unique_crossing_pairs', 'total_length_mm',
                   'fabrication_hours'):
            ax.text(0.01, 0.985, 'lower is better', transform=ax.transAxes,
                    fontsize=7, va='top', color='#495057')
    fig.suptitle('C4 strict-symmetry multilayer study vs E1 asymmetric '
                 'reference (%s)\nHatched/dashed line = E1 reference value; '
                 'bars coloured by stack height' % e1_name, fontsize=10.6)
    _finish(fig, path, rect=(0.0, 0.0, 1.0, 0.95))


def summary_figures(folder, rows, *, e1_row=None, log=print):
    """Write the four comparison figures into ``folder/`` (not ``figures/``).

    Parameters
    ----------
    folder : str | Path
        Output directory for the summary figures.
    rows : list[dict]
        One row per C4 layer-count experiment; keys
        ``experiment, layers, unique_crossing_pairs, total_length_mm,
        fabrication_hours, max_z_mm, transitions`` (extra keys ignored).
    e1_row : dict | None
        The E1 asymmetric reference row (e.g. 3594 crossings).  When ``None``
        no reference line is drawn (no fabricated reference).

    Returns
    -------
    dict
        ``{figure_stem: absolute path}`` for the four summary figures.
    """
    started = time.perf_counter()
    folder = _ensure_dir(folder)
    rows = _normalise_rows(rows)
    e1 = dict(e1_row) if isinstance(e1_row, dict) else e1_row
    figures = [
        ('layer_count_vs_crossings', 'layer_count_vs_crossings.png',
         lambda path: _figure_layer_count_vs_crossings(path, rows, e1)),
        ('layer_count_vs_length', 'layer_count_vs_length.png',
         lambda path: _figure_layer_count_vs_length(path, rows, e1)),
        ('layer_count_vs_max_height', 'layer_count_vs_max_height.png',
         lambda path: _figure_layer_count_vs_max_height(path, rows, e1)),
        ('c4_vs_e1_comparison', 'c4_vs_e1_comparison.png',
         lambda path: _figure_c4_vs_e1(path, rows, e1)),
    ]
    outputs = {}
    for key, filename, draw in figures:
        path = folder / filename
        try:
            draw(path)
            outputs[key] = str(path.resolve())
            log('[c4 plots] summary %-32s ok' % filename)
        except Exception as exc:
            _write_error_figure(path, key, exc, 'summary')
            outputs[key] = str(path.resolve())
            log('[c4 plots] summary %-32s FAILED %s: %s'
                % (filename, type(exc).__name__, exc))
    log('[c4 plots] summary_figures done in %.1fs -> %s'
        % (time.perf_counter() - started, folder))
    return outputs
