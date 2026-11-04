# -*- coding: utf-8 -*-
"""Real-geometry visualization for the Native 3D multi-height experiment.

Every figure of this module is drawn from the *stored* route records (the
``parts`` list with one physical ``z_mm`` per flat part and the exact S-curve
parameters of every transition) and from the *stored* crossing-event records
(``crossing_stats.json``).  Nothing is schematic: no invented geometry, no
hand-placed lines.

Required public API (all pure functions that take explicit paths)
------------------------------------------------------------------
``plot_route_3d(route_before, route_after, out_path, title=None)``
    3D view of one route before (dashed grey) / after (coloured by physical z),
    with every mid-body S-curve marked and its z levels labelled.

``plot_route_2d_projections(route, out_path_dir, prefix=None)``
    One XY panel per physical height the route actually occupies, highlighting
    the flat segments on that height and drawing the rest faintly.

``plot_transition_zoom(route, part_indices, neighbours, out_path, centre_xy=None, span_mm=12)``
    Zoom on selected S-curve transitions with nearby waveguides drawn faintly,
    plus a Z-Y side view and the vertical S-curve profile.

``plot_crossing_profile(route, crossing_positions, out_path)``
    Crossings along the route arc length ``s`` (colour = partner height),
    with dense clusters shaded, plus the route height profile.

``plot_experiment_b_summary(candidates, out_path)``
    Removed vs added crossings per candidate (grouped bars + net line).

``plot_experiment_c_dashboard(run_dir, out_dir)``
    The complete experiment-C figure set (21 per-height 2D views, 3D overview,
    crossing-vs-iteration curve, per-layer / top-route before-after, native
    statistics, crossing hotspot, route height profiles).

Extra (used by the CLI / the Lead's experiment runners)
-------------------------------------------------------
``plot_baseline_demo``, ``plot_experiment_a_dashboard``,
``plot_experiment_b_dashboard``, ``plot_all_experiments``,
``plot_height_panels``, ``load_routes``, ``load_crossing_stats``.

CLI
---
::

    python -m four_side_1024.fanout1024.native3d.visualize \
        --run-dir  outputs/.../NATIVE_3D_CROSSING_OPT_1024 \
        --baseline-dir outputs/.../E5_joint_repair_final \
        --out-dir  outputs/.../NATIVE_3D_CROSSING_OPT_1024/plots

    # frozen E5 baseline only (validation / reference panels)
    python -m four_side_1024.fanout1024.native3d.visualize --demo-baseline

Missing input files are reported and the corresponding figures are skipped -
the dashboard never crashes because one file is absent.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import traceback
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from mpl_toolkits.mplot3d.art3d import (Line3DCollection,  # noqa: E402
                                        Poly3DCollection)

from ...fsd25d import path3d as P  # noqa: E402
from ..reheight21 import model as H  # noqa: E402
from . import common as N  # noqa: E402

__all__ = [
    # required API
    'plot_route_3d', 'plot_route_2d_projections', 'plot_transition_zoom',
    'plot_crossing_profile', 'plot_experiment_b_summary',
    'plot_experiment_c_dashboard',
    # supporting API
    'plot_baseline_demo', 'plot_experiment_a_dashboard',
    'plot_experiment_b_dashboard', 'plot_all_experiments',
    'plot_height_panels', 'load_routes', 'load_crossing_stats',
    'transition_records', 'route_xyz', 'route_s_z', 'height_info',
    'main',
]

TOOL = 'four_side_1024.fanout1024.native3d.visualize'
SCHEMA_MANIFEST = 'native3d_plots_v1'
BOARD_MM = 150.0
DPI = 120

# --------------------------------------------------------------------------- #
# style / colours
# --------------------------------------------------------------------------- #
Z_MIN = min(float(z) for z in N.PLANE_Z.values())
Z_MAX = max(float(z) for z in N.PLANE_Z.values())
CMAP = plt.get_cmap('turbo')
NORM = Normalize(vmin=Z_MIN, vmax=Z_MAX)

C_PLANE = {'z1': '#1565c0', 'z2': '#c62828'}
C_BEFORE = '#8a8a8a'
C_OTHER = '#b0b0b0'
C_NEIGHBOUR = '#bdbdbd'
C_MID = '#d500f9'
C_CROSS = '#e00000'
C_REMOVED = '#2e7d32'
C_ADDED = '#c62828'
C_NET = '#212121'
C_BODY = '#37474f'
C_INTERFACE = '#607d8b'

INTERFACE_Z = (float(H.interface_z('z1')), float(H.interface_z('z2')))

#: set by ``--quiet`` to suppress per-figure console logging
_QUIET = False

#: physical height table, sorted by real z (NEVER by plane id)
HEIGHT_ROWS = tuple(sorted(
    ((int(pid), float(z), str(N.PLANE_LABEL[int(pid)]), str(H.plane_kind(pid)))
     for pid, z in N.PLANE_Z.items()),
    key=lambda row: (row[1], row[0])))
HEIGHT_BY_KEY = {round(row[1], 6): row for row in HEIGHT_ROWS}
HEIGHT_BY_PID = {row[0]: row for row in HEIGHT_ROWS}


def _apply_style():
    plt.rcParams.update({
        'figure.facecolor': 'white',
        'axes.facecolor': 'white',
        'savefig.facecolor': 'white',
        'font.size': 9.0,
        'axes.titlesize': 10.0,
        'axes.labelsize': 8.5,
        'xtick.labelsize': 7.5,
        'ytick.labelsize': 7.5,
        'legend.fontsize': 7.5,
        'axes.grid': False,
        'axes.linewidth': 0.6,
        'xtick.major.width': 0.5,
        'ytick.major.width': 0.5,
    })


_apply_style()


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _route_id(route):
    try:
        return int(route.get('route_id'))
    except (TypeError, ValueError):
        return None


def _parts(route):
    return [part for part in (route.get('parts') or ())
            if isinstance(part, dict)]


def _flat_parts(route):
    return [part for part in _parts(route) if part.get('kind') == 'flat']


def _transition_parts(route):
    return [part for part in _parts(route) if part.get('kind') == 'transition']


def _plane(route):
    return str(route.get('plane') or '')


def _to_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _pick(mapping, keys, default=None):
    """First non-None value of ``mapping`` among ``keys``."""
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _safe_token(text):
    token = ''.join(char if char.isalnum() else '_' for char in str(text))
    return token.strip('_') or 'x'


def _fmt_count(value):
    """Format a crossing count without a needless ``.0`` suffix."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return '%d' % int(round(number))
    return '%.3f' % number


def _height_info(z_mm):
    """``dict(plane_id, z_mm, label, kind)`` for one physical height."""
    z = _to_float(z_mm)
    if z is None:
        return dict(plane_id=None, z_mm=float('nan'), label='z=nan', kind='custom')
    key = round(z, 6)
    if key in HEIGHT_BY_KEY:
        pid, hz, label, kind = HEIGHT_BY_KEY[key]
        return dict(plane_id=int(pid), z_mm=float(hz), label=label, kind=kind)
    return dict(plane_id=None, z_mm=z, label='z=%+.3f' % z, kind='custom')


def _height_key(z_mm):
    z = _to_float(z_mm)
    if z is None:
        return None
    return round(z, 6)


def _height_text(z_mm):
    info = _height_info(z_mm)
    return '%s %+.2fmm' % (info['label'], info['z_mm'])


def _height_color(z_mm):
    z = _to_float(z_mm)
    if z is None:
        return '#7f7f7f'
    return CMAP(NORM(z))


def height_info(z_mm):
    """Public alias of :func:`_height_info` (used by the Lead / tests)."""
    return _height_info(z_mm)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _read_csv_rows(path):
    try:
        with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle))
    except (OSError, ValueError, csv.Error):
        return []


def _log(manifest, message, level='info'):
    if not _QUIET:
        print('[%s] %s: %s' % ('native3d.viz', level, message), flush=True)
    if manifest is not None:
        manifest['log'].append(dict(level=str(level), message=str(message)))


def _skip(manifest, name, reason):
    _log(manifest, 'skip %s: %s' % (name, reason), level='warn')
    if manifest is not None:
        manifest['skipped'].append(dict(name=str(name), reason=str(reason)))


def _new_manifest(kind, source_dir, out_dir):
    return dict(schema=SCHEMA_MANIFEST, tool=TOOL, kind=str(kind),
                source_dir=str(source_dir), out_dir=str(out_dir),
                data={}, figures=[], skipped=[], log=[],
                runtime_seconds=None, figure_count=0)


def _finish_manifest(manifest, out_dir, started):
    manifest['runtime_seconds'] = round(time.time() - started, 3)
    manifest['figure_count'] = len(manifest['figures'])
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / 'plots_manifest.json'
        path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False),
                        encoding='utf-8')
        manifest['manifest_path'] = str(path)
    except OSError as exc:  # pragma: no cover - defensive
        _log(manifest, 'could not write manifest: %r' % (exc,), level='warn')
    _log(manifest, 'finished: %d figures, %d skipped, %.1fs'
         % (manifest['figure_count'], len(manifest['skipped']),
            manifest['runtime_seconds']))
    return manifest


def _record_figure(manifest, name, path):
    path = Path(path)
    info = dict(name=str(name), path=str(path),
                bytes=path.stat().st_size if path.exists() else 0)
    if manifest is not None:
        manifest['figures'].append(info)
    return path


def _save_fig(fig, path, manifest=None, name=None):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=DPI, facecolor='white', bbox_inches='tight',
                    pad_inches=0.08)
    finally:
        plt.close(fig)
    _log(manifest, 'wrote %s' % path)
    _record_figure(manifest, name or path.stem, path)
    return path


def _wanted(only, name):
    if not only:
        return True
    tokens = {str(token).strip() for token in only}
    return name in tokens or 'all' in tokens


def _parse_only(text):
    if not text:
        return None
    return {token.strip() for token in str(text).split(',') if token.strip()}


def _find_path(run_dir, relative):
    """Resolve ``relative`` inside ``run_dir`` or its parent directory."""
    run_dir = Path(run_dir)
    for base in (run_dir, run_dir.parent):
        candidate = base / relative
        if candidate.exists():
            return candidate
    return None


# --------------------------------------------------------------------------- #
# loading routes / crossing statistics
# --------------------------------------------------------------------------- #
def _load_routes_file(path):
    payload = _read_json(path)
    if payload is None:
        return None
    if isinstance(payload, dict):
        records = payload.get('routes')
        if records is None and isinstance(payload.get('accepted_routes'), list):
            records = payload['accepted_routes']
    elif isinstance(payload, list):
        records = payload
    else:
        return None
    routes = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        status = str(record.get('status') or '').strip().lower()
        if status in ('failed', 'error'):
            continue
        routes.append(record)
    if not routes:
        return None
    routes.sort(key=lambda record: _route_id(record) or 0)
    return routes


def load_routes(run_dir):
    """Load routed records from ``run_dir/routes_l3d.json`` (or parent dir)."""
    path = _find_path(run_dir, 'routes_l3d.json')
    if path is None:
        return None
    return _load_routes_file(path)


def load_crossing_stats(run_dir):
    """Load ``crossing_stats.json`` (or parent dir); ``None`` when absent."""
    path = _find_path(run_dir, 'crossing_stats.json')
    if path is None:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    payload['_path'] = str(path)
    return payload


def _routes_by_id(routes):
    out = {}
    for route in routes or ():
        rid = _route_id(route)
        if rid is not None:
            out[rid] = route
    return out


def _per_route_counts(stats):
    """``{route_id: crossing count}`` from a crossing_stats payload."""
    if not isinstance(stats, dict):
        return {}
    out = {}
    raw = stats.get('per_route_crossings')
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                rid = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                value = _pick(value, ('crossings', 'count', 'n'), 0)
            try:
                out[rid] = int(value)
            except (TypeError, ValueError):
                continue
    if out:
        return out
    for event in stats.get('crossing_events') or ():
        for key in ('route_a', 'route_b'):
            try:
                rid = int(event.get(key))
            except (TypeError, ValueError):
                continue
            out[rid] = out.get(rid, 0) + 1
    return out


def _events_by_height(stats):
    """``{rounded z: [events]}`` from stored crossing events (real records)."""
    grouped = defaultdict(list)
    if not isinstance(stats, dict):
        return grouped
    for event in stats.get('crossing_events') or ():
        if not isinstance(event, dict):
            continue
        z = _to_float(event.get('z_mm'))
        if z is None:
            try:
                pid = int(event.get('plane_id'))
            except (TypeError, ValueError):
                pid = None
            if pid is not None and pid in HEIGHT_BY_PID:
                z = HEIGHT_BY_PID[pid][1]
        key = _height_key(z)
        if key is None:
            continue
        grouped[key].append(event)
    return grouped


def _plane_rows(stats):
    """``{plane_id: plane row}`` from a crossing_stats payload."""
    if not isinstance(stats, dict):
        return {}
    out = {}
    for row in stats.get('planes') or ():
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get('plane_id'))
        except (TypeError, ValueError):
            continue
        out[pid] = row
    return out


# --------------------------------------------------------------------------- #
# route geometry helpers (stored data only)
# --------------------------------------------------------------------------- #
def transition_records(route):
    """``[(part_index, part, tag)]`` for every transition of ``route``.

    ``tag`` is the stored ``'fanout'`` / ``'mid'`` tag when present.  For the
    frozen E5 baseline (no tags) the first/last transition of a route is a
    port-fanout S-curve and any intermediate transition is a mid-body S-curve.
    """
    parts = _parts(route)
    transitions = [(index, part) for index, part in enumerate(parts)
                   if part.get('kind') == 'transition']
    tags = {}
    for index, part in transitions:
        tag = str(part.get('tag') or '').strip().lower()
        tags[index] = tag if tag in ('fanout', 'mid') else None
    if any(tag is None for tag in tags.values()):
        last = len(transitions) - 1
        for offset, (index, _part) in enumerate(transitions):
            if tags[index] is not None:
                continue
            tags[index] = 'fanout' if offset in (0, last) else 'mid'
    return [(index, part, tags[index]) for index, part in transitions]


def _n_mid(route):
    value = route.get('n_mid_transitions')
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return sum(1 for _index, _part, tag in transition_records(route)
               if tag == 'mid')


def _mid_target_z(route):
    """Target height of the first mid-body excursion of ``route`` (or None)."""
    mids = [part for _index, part, tag in transition_records(route)
            if tag == 'mid']
    if not mids:
        return None
    return _to_float(mids[0].get('z1'))


def _n_transitions(route):
    value = route.get('n_transitions')
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return len(_transition_parts(route))


def _route_length(route):
    value = _to_float(route.get('length_mm'))
    if value is not None:
        return value
    return float(sum(N.part_length(part) for part in _parts(route)))


def sample_flat_xy(part, step=2.0):
    """2D polyline of one stored flat part (lines and R15 arcs)."""
    prims = part.get('primitives') or ()
    if not prims:
        return None
    try:
        points = P.path_polyline(list(prims), step=max(float(step), 0.05))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] != 2:
        return None
    if not np.isfinite(array).all():
        return None
    return array


def sample_transition_xyz(part, step=0.4):
    """3D samples of one stored S-curve transition."""
    try:
        points = P.transition_samples(part, step=max(float(step), 0.02))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] != 3:
        return None
    if not np.isfinite(array).all():
        return None
    return array


def route_xyz(route, step_flat=4.0, step_transition=0.5):
    """True 3D polyline of a route built from its stored parts."""
    chunks = []
    for part in _parts(route):
        if part.get('kind') == 'flat':
            xy = sample_flat_xy(part, step_flat)
            if xy is None:
                continue
            z = _to_float(part.get('z_mm'))
            if z is None:
                continue
            chunk = np.column_stack([xy, np.full(len(xy), z, dtype=float)])
        elif part.get('kind') == 'transition':
            chunk = sample_transition_xyz(part, step_transition)
            if chunk is None:
                continue
        else:
            continue
        if chunk is None or len(chunk) == 0:
            continue
        if chunks and _distance3(chunks[-1][-1], chunk[0]) < 1e-9:
            chunk = chunk[1:]
        if len(chunk):
            chunks.append(chunk)
    if not chunks:
        return None
    return np.vstack(chunks)


def route_s_z(route, step_flat=0.5, step_transition=0.15):
    """``(points3d, s)`` with true 3D arc length ``s`` from stored parts."""
    parts = _parts(route)
    if not parts:
        return None, None
    try:
        points, lengths = P.sample_parts(parts, step_flat=float(step_flat),
                                         step_transition=float(step_transition))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None, None
    array = np.asarray(points, dtype=float)
    s = np.asarray(lengths, dtype=float)
    if array.ndim != 2 or array.shape[0] < 2 or len(s) != len(array):
        return None, None
    if not (np.isfinite(array).all() and np.isfinite(s).all()):
        return None, None
    return array, s


def _distance3(first, second):
    return math.sqrt((first[0] - second[0]) ** 2
                     + (first[1] - second[1]) ** 2
                     + (first[2] - second[2]) ** 2)


def _decimate(points, stride):
    if points is None or len(points) <= 2 or stride <= 1:
        return points
    decimated = points[::int(stride)]
    if not np.allclose(decimated[-1], points[-1]):
        decimated = np.vstack([decimated, points[-1:]])
    return decimated


def _color_segments(points3d):
    """``(segments (N,2,3), colours (N,4))`` coloured by the segment mid z."""
    if points3d is None or len(points3d) < 2:
        return None, None
    segments = np.stack([points3d[:-1], points3d[1:]], axis=1)
    mid_z = (points3d[:-1, 2] + points3d[1:, 2]) * 0.5
    colours = CMAP(NORM(mid_z))
    return segments, colours


# --------------------------------------------------------------------------- #
# drawing helpers
# --------------------------------------------------------------------------- #
def _draw_board(ax, board=BOARD_MM, lw=0.8, color='#424242', label='board 150x150 mm'):
    ax.add_patch(Rectangle((0.0, 0.0), board, board, fill=False,
                           edgecolor=color, linewidth=lw))
    if label:
        ax.text(1.0, board - 2.0, label, fontsize=6.0, color='#616161',
                va='top', ha='left')


def _scatter_crossings(ax, events, size=20.0):
    xs, ys = [], []
    for event in events or ():
        x = _to_float(event.get('x_mm'))
        y = _to_float(event.get('y_mm'))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return 0
    ax.scatter(xs, ys, marker='x', s=size, c=C_CROSS, linewidths=0.8,
               zorder=7, label='crossing events (%d)' % len(xs))
    return len(xs)


def _set_count_ylim(ax, arrays):
    """Sane y limits for bar/line count plots (incl. all-zero / tiny data)."""
    values = []
    for array in arrays:
        values.extend(float(value) for value in array if value is not None)
    low = min([0.0] + values)
    high = max([0.0] + values)
    span = high - low
    if span <= 0.0:
        span = 1.0
    bottom = low - 0.08 * span if low < 0.0 else 0.0
    ax.set_ylim(bottom, high + 0.18 * span)


def _xy_limits(ax, xlim=(-2.0, BOARD_MM + 2.0), ylim=(-2.0, BOARD_MM + 2.0)):
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')


def _dash_patterns(kind):
    return {'fanout': (0, (4.0, 2.0)), 'mid': (0, (1.2, 1.0))}.get(
        kind, (0, (3.0, 2.0)))


# --------------------------------------------------------------------------- #
# route cache (sampled once, reused by all dashboard figures)
# --------------------------------------------------------------------------- #
class _RouteCache:
    """Sampled geometry of a route list, bucketed by real physical z."""

    def __init__(self, routes, step_flat=2.0, step_transition=0.4):
        self.routes = list(routes or ())
        self.step_flat = float(step_flat)
        self.step_transition = float(step_transition)
        self.flat_by_z = defaultdict(list)
        self.transitions = []
        self.flat_xyz = {}
        self.transition_xyz = {}
        self.route_z_keys = {}
        self.route_sample_failures = 0
        self._build()

    def _build(self):
        for route in self.routes:
            rid = _route_id(route)
            if rid is None:
                continue
            plane = _plane(route)
            z_keys = set()
            tags = {index: tag for index, _part, tag
                    in transition_records(route)}
            for index, part in enumerate(_parts(route)):
                try:
                    if part.get('kind') == 'flat':
                        xy = sample_flat_xy(part, self.step_flat)
                        z = _to_float(part.get('z_mm'))
                        if xy is None or z is None:
                            continue
                        xyz = np.column_stack(
                            [xy, np.full(len(xy), z, dtype=float)])
                        self.flat_xyz[(rid, index)] = xyz
                        key = _height_key(z)
                        z_keys.add(key)
                        self.flat_by_z[key].append(dict(
                            route_id=rid, plane=plane, index=index,
                            z_mm=z, pts=xy,
                            length=N.part_length(part)))
                    elif part.get('kind') == 'transition':
                        xyz = sample_transition_xyz(part,
                                                    self.step_transition)
                        if xyz is None:
                            continue
                        z0 = _to_float(part.get('z0'))
                        z1 = _to_float(part.get('z1'))
                        if z0 is None or z1 is None:
                            continue
                        tag = tags.get(index)
                        self.transition_xyz[(rid, index)] = xyz
                        self.transitions.append(dict(
                            route_id=rid, plane=plane, index=index,
                            z0=z0, z1=z1, tag=tag, pts=xyz,
                            length=N.part_length(part)))
                except (KeyError, TypeError, ValueError, IndexError):
                    self.route_sample_failures += 1
            self.route_z_keys[rid] = sorted(z_keys)

    def route_polyline3d(self, route, flat_stride=2):
        """3D polyline of one cached route (``flat_stride`` decimates flats)."""
        rid = _route_id(route)
        chunks = []
        for index, part in enumerate(_parts(route)):
            kind = part.get('kind')
            if kind == 'flat':
                points = self.flat_xyz.get((rid, index))
                points = _decimate(points, flat_stride)
            elif kind == 'transition':
                points = self.transition_xyz.get((rid, index))
            else:
                points = None
            if points is None or len(points) == 0:
                continue
            if chunks and _distance3(chunks[-1][-1], points[0]) < 1e-9:
                points = points[1:]
            if len(points):
                chunks.append(points)
        if not chunks:
            return None
        return np.vstack(chunks)


# --------------------------------------------------------------------------- #
# (1) single route 3D before / after
# --------------------------------------------------------------------------- #
def plot_route_3d(route_before, route_after, out_path, title=None):
    """3D view of one route: before dashed grey, after coloured by real z.

    Mid-body S-curves of the ``after`` route are marked with magenta diamonds
    and labelled with their z levels; every physical height the route visits is
    drawn as a faint reference rectangle and listed in the title.
    """
    out_path = Path(out_path)
    route_after = route_after or route_before
    if route_after is None:
        _log(None, 'plot_route_3d: no route given, nothing to draw',
             level='warn')
        return None
    rid = _route_id(route_after) or _route_id(route_before) or 0
    plane = _plane(route_after) or _plane(route_before)

    fig = plt.figure(figsize=(12.0, 9.6))
    ax = fig.add_subplot(111, projection='3d')

    # before: dashed grey (true stored geometry)
    drawn_before = False
    if route_before is not None:
        before_xyz = route_xyz(route_before, step_flat=4.0,
                               step_transition=0.5)
        if before_xyz is not None:
            ax.plot(before_xyz[:, 0], before_xyz[:, 1], before_xyz[:, 2],
                    color=C_BEFORE, linestyle='--', linewidth=1.0,
                    alpha=0.95,
                    label='before  (n_transitions=%d)'
                          % _n_transitions(route_before))
            drawn_before = True

    # after: segments coloured by physical z
    after_xyz = route_xyz(route_after, step_flat=2.0, step_transition=0.4)
    if after_xyz is None:
        _log(None, 'plot_route_3d: route %s has no drawable parts' % rid,
             level='warn')
        plt.close(fig)
        return None
    segments, colours = _color_segments(after_xyz)
    if segments is not None:
        collection = Line3DCollection(segments, colors=colours,
                                      linewidths=1.6, alpha=0.95)
        ax.add_collection3d(collection, autolim=False)

    # mid-body S-curves: markers + z-level labels
    mid_points = []
    mid_labels = []
    visited_z = set()
    for index, part, tag in transition_records(route_after):
        if tag != 'mid':
            continue
        start = part.get('start') or []
        end = part.get('end') or []
        z0 = _to_float(part.get('z0'))
        z1 = _to_float(part.get('z1'))
        if len(start) < 2 or len(end) < 2 or z0 is None or z1 is None:
            continue
        mid_points.append([(start[0] + end[0]) * 0.5,
                           (start[1] + end[1]) * 0.5,
                           (z0 + z1) * 0.5])
        mid_labels.append('mid #%d: %s -> %s'
                          % (index, _height_text(z0), _height_text(z1)))
        visited_z.add(_height_key(z0))
        visited_z.add(_height_key(z1))
    for part in _flat_parts(route_after):
        z = _to_float(part.get('z_mm'))
        if z is not None:
            visited_z.add(_height_key(z))
    if mid_points:
        points = np.asarray(mid_points, dtype=float)
        ax.scatter(points[:, 0], points[:, 1], points[:, 2], marker='D',
                   s=26, c=C_MID, edgecolors='white', linewidths=0.8,
                   depthshade=False,
                   label='mid-body S-curves (%d)' % len(mid_points))
        for point, label in zip(points, mid_labels):
            ax.text(point[0], point[1], point[2] + 0.02, label, fontsize=6.5,
                    color='#6a1b9a')

    # faint z reference rectangles for every visited physical height
    for key in sorted(z for z in visited_z if z is not None):
        z = HEIGHT_BY_KEY[key][1]
        colour = CMAP(NORM(z))
        ax.plot([0, BOARD_MM, BOARD_MM, 0, 0], [0, 0, BOARD_MM, BOARD_MM, 0],
                [z] * 5, color=colour, linewidth=0.5, linestyle=':',
                alpha=0.55)
        ax.text(0.0, -4.0, z, '%s %+.2f' % (HEIGHT_BY_KEY[key][2], z),
                fontsize=6.0, color=colour)

    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_zlim(Z_MIN - 0.05, Z_MAX + 0.05)
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.view_init(elev=26, azim=-58)
    try:
        ax.set_box_aspect((1.35, 1.35, 0.85))
    except (AttributeError, ValueError):  # pragma: no cover - old mpl
        pass

    visited_text = ', '.join(
        '%s %+.2f' % (HEIGHT_BY_KEY[key][2], HEIGHT_BY_KEY[key][1])
        for key in sorted(z for z in visited_z if z is not None))
    default_title = ('Route R%d  plane=%s  L=%.2f mm  z-span=%.3f mm\n'
                     'heights: %s' % (rid, plane or '?', _route_length(route_after),
                                      float(route_after.get('z_span_mm') or 0.0),
                                      visited_text or 'n/a'))
    ax.set_title(title or default_title, fontsize=10.0)

    handles = [Line2D([0], [0], color=C_MID, marker='D', linestyle='none',
                      markersize=6, label='mid-body S-curve')]
    if drawn_before:
        handles.insert(0, Line2D([0], [0], color=C_BEFORE, linestyle='--',
                                 linewidth=1.2, label='before'))
    handles.append(Line2D([0], [0], color='#616161', linewidth=1.2,
                          label='after (colour = z)'))
    ax.legend(handles=handles, loc='upper left', fontsize=7.5,
              framealpha=0.9)

    sm = plt.cm.ScalarMappable(norm=NORM, cmap=CMAP)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.09, shrink=0.7,
                 label='physical z (mm)')
    return _save_fig(fig, out_path)


# --------------------------------------------------------------------------- #
# (2) 2D projections, one panel per physical height
# --------------------------------------------------------------------------- #
def plot_route_2d_projections(route, out_path_dir, prefix=None):
    """One XY figure per physical height the route actually occupies.

    Returns the list of written paths.  On each panel the flat parts on that
    height are highlighted in the height colour, all other heights are faint
    grey, and transition S-curves are shown as dotted XY footprints.
    """
    if not route:
        _log(None, 'plot_route_2d_projections: empty route', level='warn')
        return []
    rid = _route_id(route) or 0
    out_dir = Path(out_path_dir)
    prefix = prefix or 'route%04d' % rid
    heights = sorted({_height_key(part.get('z_mm'))
                      for part in _flat_parts(route)
                      if _to_float(part.get('z_mm')) is not None})
    if not heights:
        _log(None, 'plot_route_2d_projections: route %s has no flat parts'
             % rid, level='warn')
        return []

    out_paths = []
    for order, key in enumerate(heights):
        info = _height_info(key)
        z = float(info['z_mm'])
        colour = CMAP(NORM(z))
        fig, ax = plt.subplots(figsize=(8.6, 8.3))
        _draw_board(ax)

        # faint context: all flat parts on other heights + transition footprints
        other_segments = []
        other_colours = []
        for part in _flat_parts(route):
            pz = _to_float(part.get('z_mm'))
            if pz is None or _height_key(pz) == key:
                continue
            xy = sample_flat_xy(part, 2.0)
            if xy is not None:
                other_segments.append(xy)
                other_colours.append(C_OTHER)
        if other_segments:
            ax.add_collection(LineCollection(
                other_segments, colors=other_colours, linewidths=0.7,
                alpha=0.45, label='other heights (faint)'))

        transition_segments = []
        for _index, part, tag in transition_records(route):
            xyz = sample_transition_xyz(part, 0.3)
            if xyz is None:
                continue
            transition_segments.append(xyz[:, :2])
        if transition_segments:
            ax.add_collection(LineCollection(
                transition_segments, colors=C_BODY, linewidths=0.6,
                linestyles=':', alpha=0.6,
                label='S-curve footprints'))

        highlighted_length = 0.0
        for part in _flat_parts(route):
            pz = _to_float(part.get('z_mm'))
            if pz is None or _height_key(pz) != key:
                continue
            xy = sample_flat_xy(part, 1.0)
            if xy is None:
                continue
            highlighted_length += N.part_length(part)
            ax.plot(xy[:, 0], xy[:, 1], color=colour, linewidth=1.7,
                    alpha=0.95, zorder=4)

        # ports (stored endpoints)
        first = _parts(route)[0] if _parts(route) else None
        last = _parts(route)[-1] if _parts(route) else None
        if first is not None and first.get('kind') == 'flat':
            xy = sample_flat_xy(first, 1.0)
            if xy is not None:
                ax.plot(xy[0, 0], xy[0, 1], marker='o', markersize=5,
                        color='#2e7d32', zorder=6, label='source port')
        if last is not None and last.get('kind') == 'flat':
            xy = sample_flat_xy(last, 1.0)
            if xy is not None:
                ax.plot(xy[-1, 0], xy[-1, 1], marker='s', markersize=5,
                        color='#b71c1c', zorder=6, label='target port')

        _xy_limits(ax)
        ax.set_title(
            'Route R%d  plane=%s  |  %s  z=%+.2f mm (%s)\n'
            'highlighted flat length on this height: %.2f mm  '
            '(route length %.2f mm, %d mid S-curves)'
            % (rid, _plane(route) or '?', info['label'], z, info['kind'],
               highlighted_length, _route_length(route), _n_mid(route)),
            fontsize=9.5)
        handles, labels = ax.get_legend_handles_labels()
        seen = OrderedDict()
        for handle, label in zip(handles, labels):
            seen.setdefault(label, handle)
        ax.legend(seen.values(), seen.keys(), loc='upper right', fontsize=7.0,
                  framealpha=0.9)
        filename = '%s_z%02d_%s.png' % (prefix, order + 1,
                                        _safe_token(info['label']))
        out_paths.append(_save_fig(fig, out_dir / filename))
    return out_paths


# --------------------------------------------------------------------------- #
# (3) zoom on mid-body S-curves
# --------------------------------------------------------------------------- #
def _selected_transitions(route, part_indices):
    parts = _parts(route)
    tags = {index: tag for index, _part, tag in transition_records(route)}
    selected = []
    indices = list(part_indices or ())
    if not indices:
        indices = [index for index, _part, tag in transition_records(route)
                   if tag == 'mid']
    for index in indices:
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(parts) and parts[index].get('kind') == 'transition':
            selected.append((index, parts[index], tags.get(index, 'fanout')))
    return selected


def _neighbour_routes(baseline_routes, route, limit=24, radius_mm=10.0,
                      sample_step=5.0):
    """Nearby frozen-baseline routes around ``route``'s primary body flat."""
    if not baseline_routes:
        return []
    route = route or {}
    rid = _route_id(route)
    body_z = None
    best_length = -1.0
    anchor = None
    for part in _flat_parts(route):
        z = _to_float(part.get('z_mm'))
        if z is None or (body_z is not None and abs(z - body_z) < 1e-9):
            continue
        xy = sample_flat_xy(part, sample_step)
        if xy is None:
            continue
        length = N.part_length(part)
        if body_z is None or length > best_length:
            body_z = z
            best_length = length
            anchor = xy[len(xy) // 2]
    if anchor is None:
        return []
    candidates = []
    for other in baseline_routes:
        if _route_id(other) == rid:
            continue
        points = []
        for part in _flat_parts(other):
            xy = sample_flat_xy(part, sample_step)
            if xy is not None:
                points.append(xy)
        if not points:
            continue
        stacked = np.vstack(points)
        distance = float(np.min(np.hypot(stacked[:, 0] - anchor[0],
                                         stacked[:, 1] - anchor[1])))
        if distance <= radius_mm:
            candidates.append((distance, other))
    candidates.sort(key=lambda item: (item[0],
                                      _route_id(item[1]) or 0))
    return [other for _distance, other in candidates[:int(limit)]]


def plot_transition_zoom(route, part_indices, neighbours, out_path,
                         centre_xy=None, span_mm=12.0):
    """Local zoom of mid-body S-curves with nearby waveguides and a Z-Y inset."""
    out_path = Path(out_path)
    if not route:
        _log(None, 'plot_transition_zoom: empty route', level='warn')
        return None
    rid = _route_id(route) or 0
    selected = _selected_transitions(route, part_indices)
    if not selected:
        _log(None, 'plot_transition_zoom: route %s has no transition parts %s'
             % (rid, list(part_indices or ())), level='warn')
        return None

    # window around the selected S-curves
    xs, ys = [], []
    for _index, part, _tag in selected:
        start = part.get('start') or []
        end = part.get('end') or []
        for point in (start, end):
            if len(point) >= 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
    if not xs:
        _log(None, 'plot_transition_zoom: no stored start/end points',
             level='warn')
        return None
    span = max(float(span_mm), 1.0)
    if centre_xy is not None and len(centre_xy) >= 2:
        cx, cy = float(centre_xy[0]), float(centre_xy[1])
    else:
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    half = max(span * 0.5, extent * 0.5 + 1.5)
    xlo, xhi = cx - half, cx + half
    ylo, yhi = cy - half, cy + half

    fig = plt.figure(figsize=(14.5, 8.2))
    ax = fig.add_axes([0.05, 0.08, 0.52, 0.84])
    ax_yz = fig.add_axes([0.63, 0.56, 0.34, 0.36])
    ax_z = fig.add_axes([0.63, 0.08, 0.34, 0.36])
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.grid(True, linewidth=0.25, color='#dddddd')

    # neighbours (frozen baseline context), faint grey
    for neighbour in neighbours or ():
        nrid = _route_id(neighbour)
        if nrid == rid:
            continue
        for part in _flat_parts(neighbour):
            xy = sample_flat_xy(part, 1.5)
            if xy is None:
                continue
            ax.plot(xy[:, 0], xy[:, 1], color=C_NEIGHBOUR, linewidth=0.5,
                    alpha=0.65, zorder=1)
        for _index, part in enumerate(_parts(neighbour)):
            if part.get('kind') != 'transition':
                continue
            xyz = sample_transition_xyz(part, 0.5)
            if xyz is None:
                continue
            ax.plot(xyz[:, 0], xyz[:, 1], color=C_NEIGHBOUR, linewidth=0.4,
                    linestyle=':', alpha=0.55, zorder=1)

    # route flats at their real z, transitions as dotted footprints
    for part in _flat_parts(route):
        z = _to_float(part.get('z_mm'))
        xy = sample_flat_xy(part, 0.8)
        if z is None or xy is None:
            continue
        ax.plot(xy[:, 0], xy[:, 1], color=CMAP(NORM(z)), linewidth=1.0,
                alpha=0.85, zorder=3)
    for _index, part, tag in transition_records(route):
        xyz = sample_transition_xyz(part, 0.3)
        if xyz is None:
            continue
        ax.plot(xyz[:, 0], xyz[:, 1], color='#546e7a', linewidth=0.9,
                linestyle=_dash_patterns(tag), alpha=0.85, zorder=3)

    # selected S-curves highlighted, with z labels
    for index, part, tag in selected:
        xyz = sample_transition_xyz(part, 0.2)
        if xyz is None:
            continue
        ax.plot(xyz[:, 0], xyz[:, 1], color=C_MID, linewidth=2.4, zorder=5,
                label='selected mid S-curve (part %d)' % index)
        start = part.get('start') or []
        end = part.get('end') or []
        if len(start) >= 2:
            ax.plot(start[0], start[1], marker='o', markersize=5.5,
                    color=C_MID, markerfacecolor='white', zorder=6)
        if len(end) >= 2:
            ax.plot(end[0], end[1], marker='s', markersize=5.5,
                    color=C_MID, markerfacecolor='white', zorder=6)
        z0 = _to_float(part.get('z0'))
        z1 = _to_float(part.get('z1'))
        if len(start) >= 2 and z0 is not None and z1 is not None:
            ax.annotate('%s -> %s\nR=%.1f mm  footprint=%.2f mm'
                        % (_height_text(z0), _height_text(z1),
                           float(part.get('radius_mm') or float('nan')),
                           float(part.get('footprint_mm') or float('nan'))),
                        xy=(start[0], start[1]), xytext=(4, 4),
                        textcoords='offset points', fontsize=7.0,
                        color='#6a1b9a')

    # neighbours / selected transition legend
    handles = [Line2D([0], [0], color=C_NEIGHBOUR, linewidth=0.8,
                      label='nearby frozen baseline routes'),
               Line2D([0], [0], color=C_MID, linewidth=2.0,
                      label='selected mid S-curve'),
               Line2D([0], [0], color='#546e7a', linewidth=0.8,
                      linestyle=':', label='other transition footprints')]
    for z_value in sorted({_to_float(part.get('z_mm'))
                           for part in _flat_parts(route)
                           if _to_float(part.get('z_mm')) is not None}):
        handles.append(Line2D([0], [0], color=CMAP(NORM(z_value)),
                              linewidth=1.2,
                              label='flat on %s' % _height_text(z_value)))
    ax.legend(handles=handles, loc='upper right', fontsize=6.5,
              framealpha=0.92)
    ax.set_title('Route R%d  plane=%s  |  S-curve zoom  %.1f x %.1f mm window'
                 % (rid, _plane(route) or '?', xhi - xlo, yhi - ylo),
                 fontsize=10.0)
    ax.text(xlo + 0.02 * (xhi - xlo), ylo + 0.02 * (yhi - ylo),
            'window centre (%.1f, %.1f) mm' % (cx, cy), fontsize=6.5,
            color='#616161')

    # ---- Z-Y side view (world Y horizontal, Z vertical) -------------------
    for neighbour in neighbours or ():
        if _route_id(neighbour) == rid:
            continue
        for part in _flat_parts(neighbour):
            z = _to_float(part.get('z_mm'))
            xy = sample_flat_xy(part, 2.0)
            if z is None or xy is None:
                continue
            ax_yz.plot(xy[:, 1], np.full(len(xy), z), color=C_NEIGHBOUR,
                       linewidth=0.5, alpha=0.55)
        for _index, part in enumerate(_parts(neighbour)):
            if part.get('kind') != 'transition':
                continue
            xyz = sample_transition_xyz(part, 0.5)
            if xyz is None:
                continue
            ax_yz.plot(xyz[:, 1], xyz[:, 2], color=C_NEIGHBOUR, linewidth=0.4,
                       linestyle=':', alpha=0.55)
    for part in _flat_parts(route):
        z = _to_float(part.get('z_mm'))
        xy = sample_flat_xy(part, 1.0)
        if z is None or xy is None:
            continue
        ax_yz.plot(xy[:, 1], np.full(len(xy), z), color=CMAP(NORM(z)),
                   linewidth=1.1, alpha=0.9)
    for _index, part, tag in transition_records(route):
        xyz = sample_transition_xyz(part, 0.3)
        if xyz is None:
            continue
        selected_flag = any(idx == _index for idx, _p, _t in selected)
        ax_yz.plot(xyz[:, 1], xyz[:, 2],
                   color=C_MID if selected_flag else '#546e7a',
                   linewidth=2.0 if selected_flag else 0.9,
                   linestyle='-' if selected_flag else _dash_patterns(tag),
                   alpha=0.95 if selected_flag else 0.8)
    for key in sorted({_height_key(part.get('z_mm'))
                       for part in _flat_parts(route)
                       if _to_float(part.get('z_mm')) is not None}):
        z = HEIGHT_BY_KEY[key][1]
        ax_yz.axhline(z, color=CMAP(NORM(z)), linewidth=0.5, linestyle=':',
                      alpha=0.6)
        ax_yz.text(yhi - 0.02 * (yhi - ylo), z, _height_text(z),
                   fontsize=5.5, color=CMAP(NORM(z)), va='bottom', ha='right')
    ax_yz.set_xlim(ylo, yhi)
    ax_yz.set_ylim(Z_MIN - 0.05, Z_MAX + 0.05)
    ax_yz.set_xlabel('Y (mm)')
    ax_yz.set_ylabel('Z (mm)')
    ax_yz.set_title('Z-Y side view (world Y vs Z)', fontsize=8.0)
    ax_yz.grid(True, linewidth=0.25, color='#dddddd')
    ax_yz.tick_params(labelsize=6.5)

    # ---- vertical S-curve profile (z vs in-plane advance u) ---------------
    for index, part, _tag in selected:
        xyz = sample_transition_xyz(part, 0.1)
        if xyz is None:
            continue
        u = np.hypot(xyz[:, 0] - xyz[0, 0], xyz[:, 1] - xyz[0, 1])
        ax_z.plot(u, xyz[:, 2], color=C_MID, linewidth=1.8,
                  label='part %d' % index)
        ax_z.plot(u[0], xyz[0, 2], marker='o', markersize=4.5, color=C_MID)
        ax_z.plot(u[-1], xyz[-1, 2], marker='s', markersize=4.5, color=C_MID)
        z0 = _to_float(part.get('z0'))
        z1 = _to_float(part.get('z1'))
        if z0 is not None:
            ax_z.text(u[0], z0, '  %s' % _height_text(z0), fontsize=5.5,
                      color=CMAP(NORM(z0)), va='bottom')
        if z1 is not None:
            ax_z.text(u[-1], z1, '  %s' % _height_text(z1), fontsize=5.5,
                      color=CMAP(NORM(z1)), va='bottom')
    ax_z.set_xlabel('u (mm): in-plane advance along S-curve')
    ax_z.set_ylabel('Z (mm)')
    ax_z.set_title('vertical S-curve profile (Z vs Y advance)', fontsize=8.0)
    ax_z.grid(True, linewidth=0.25, color='#dddddd')
    ax_z.tick_params(labelsize=6.5)
    if len(selected) > 1:
        ax_z.legend(fontsize=6.0, framealpha=0.9)

    return _save_fig(fig, out_path)


# --------------------------------------------------------------------------- #
# (4) crossings along the route arc length
# --------------------------------------------------------------------------- #
def _crossing_positions_to_s(route, crossing_positions):
    """Map crossing records to ``(s_mm, partner_z, partner_label, partner_id)``.

    Records that already contain an arc-length key are used as given.  Records
    with only real ``x_mm``/``y_mm`` are projected onto the stored route
    centreline (nearest sampled point) - never invented.
    """
    samples, s_values = route_s_z(route, step_flat=0.5,
                                  step_transition=0.15)
    route_xy = samples[:, :2] if samples is not None else None
    route_id = _route_id(route)
    rows = []
    for position in crossing_positions or ():
        if not isinstance(position, dict):
            continue
        s_value = _to_float(_pick(position, (
            's_mm', 's', 'arc_length_mm', 'position_mm', 'arc_s_mm',
            's_center_mm')))
        if s_value is None and route_xy is not None:
            x = _to_float(_pick(position, ('x_mm', 'x', 'crossing_x_mm')))
            y = _to_float(_pick(position, ('y_mm', 'y', 'crossing_y_mm')))
            if x is not None and y is not None:
                index = int(np.argmin(np.hypot(route_xy[:, 0] - x,
                                               route_xy[:, 1] - y)))
                s_value = float(s_values[index])
        if s_value is None:
            continue
        partner_z = _to_float(_pick(position, (
            'partner_z_mm', 'other_z_mm', 'partner_plane_z_mm', 'z_mm',
            'plane_z_mm', 'crossing_z_mm')))
        partner_label = _pick(position, (
            'partner_plane_label', 'partner_label', 'plane_label',
            'partner_layer', 'other_layer'), None)
        partner_route = _pick(position, (
            'partner_route', 'other_route', 'route_b', 'route_a'), None)
        try:
            partner_route = int(partner_route)
        except (TypeError, ValueError):
            partner_route = None
        if partner_route is not None and partner_route == route_id:
            partner_route = None
        rows.append(dict(s_mm=float(s_value), partner_z=partner_z,
                         partner_label=partner_label,
                         partner_route=partner_route))
    rows.sort(key=lambda row: (row['s_mm'],
                               row['partner_route'] if row['partner_route']
                               is not None else -1))
    return rows


def plot_crossing_profile(route, crossing_positions, out_path):
    """Crossings vs arc length ``s`` on one route, with cluster spans shaded."""
    out_path = Path(out_path)
    if not route:
        _log(None, 'plot_crossing_profile: empty route', level='warn')
        return None
    rid = _route_id(route) or 0
    rows = _crossing_positions_to_s(route, crossing_positions)
    samples, s_values = route_s_z(route, step_flat=0.4,
                                  step_transition=0.12)

    fig = plt.figure(figsize=(13.5, 8.0))
    ax = fig.add_axes([0.07, 0.36, 0.60, 0.57])
    axz = fig.add_axes([0.07, 0.09, 0.60, 0.22])
    axc = fig.add_axes([0.74, 0.09, 0.24, 0.84])

    cluster_gap_mm = 3.0
    clusters = []
    if rows:
        current = [rows[0]]
        for row in rows[1:]:
            if row['s_mm'] - current[-1]['s_mm'] <= cluster_gap_mm:
                current.append(row)
            else:
                clusters.append(current)
                current = [row]
        clusters.append(current)
    for cluster in clusters:
        lo = cluster[0]['s_mm'] - 0.4
        hi = cluster[-1]['s_mm'] + 0.4
        ax.axvspan(lo, hi, color=C_CROSS, alpha=0.07, zorder=0)
        axz.axvspan(lo, hi, color=C_CROSS, alpha=0.10, zorder=0)

    # transition bands (where the route changes height)
    part_offset = 0.0
    tags = {index: tag for index, _part, tag in transition_records(route)}
    for index, part in enumerate(_parts(route)):
        length = N.part_length(part)
        if part.get('kind') == 'transition':
            tag = tags.get(index, 'fanout')
            ax.axvspan(part_offset, part_offset + length,
                       color=C_MID if tag == 'mid' else '#90a4ae',
                       alpha=0.16 if tag == 'mid' else 0.10, zorder=0)
            axz.axvspan(part_offset, part_offset + length,
                        color=C_MID if tag == 'mid' else '#90a4ae',
                        alpha=0.16 if tag == 'mid' else 0.10, zorder=0)
        part_offset += length
    total_s = part_offset

    # crossings: y = ordinal, colour = partner height (real records)
    z_values = [row['partner_z'] for row in rows
                if row['partner_z'] is not None]
    height_order = []
    if z_values:
        y_values = list(range(1, len(z_values) + 1))
        ax.scatter([row['s_mm'] for row in rows
                    if row['partner_z'] is not None],
                   y_values, c=z_values, cmap=CMAP, norm=NORM,
                   marker='o', s=34, edgecolors='white',
                   linewidths=0.4, zorder=5)
        ax.set_ylabel('crossing ordinal')
        height_counts = Counter(_height_key(z) for z in z_values)
        height_order = sorted(height_counts)
        positions = [HEIGHT_BY_KEY[key][1] for key in height_order]
        counts = [height_counts[key] for key in height_order]
        axc.barh(positions, counts, height=0.03,
                 color=[CMAP(NORM(z)) for z in positions], alpha=0.9)
        for z_value, count in zip(positions, counts):
            axc.text(count + max(counts) * 0.03, z_value, '%d' % count,
                     fontsize=6.0, va='center', ha='left', color='#424242')
        axc.set_xlim(0.0, max(counts) * 1.22 + 0.2)
        axc.set_ylim(Z_MIN - 0.05, Z_MAX + 0.05)
        axc.set_xlabel('crossings')
        axc.set_ylabel('partner plane z (mm)')
        axc.set_title('crossings per partner height', fontsize=8.5)
        axc.grid(True, linewidth=0.25, color='#dddddd')
        axc.tick_params(labelsize=6.5)
    else:
        ax.scatter([row['s_mm'] for row in rows],
                   list(range(1, len(rows) + 1)), marker='o', s=34,
                   color=C_CROSS, zorder=5)
        ax.set_ylabel('crossing ordinal')
        axc.axis('off')
        axc.text(0.5, 0.5, 'no partner height available\n'
                 '(positions mapped by projection)', ha='center',
                 va='center', fontsize=8.0, transform=axc.transAxes)

    ax.set_xlim(0.0, total_s)
    ax.set_xlabel('arc length s along route (mm)')
    ax.set_title(
        'Route R%d  plane=%s  |  %d crossings along s  (%d clusters, '
        'gap %.1f mm)\nmid-body S-curves: %d, true 3D length %.2f mm'
        % (rid, _plane(route) or '?', len(rows), len(clusters),
           cluster_gap_mm, _n_mid(route), _route_length(route)),
        fontsize=10.0)
    ax.grid(True, linewidth=0.25, color='#dddddd')
    handles = [
        Line2D([0], [0], marker='o', color='none', markerfacecolor=C_CROSS,
               markersize=6, label='crossing (colour = partner height)'),
        Line2D([0], [0], color=C_CROSS, alpha=0.25, linewidth=8,
               label='dense cluster span'),
        Line2D([0], [0], color=C_MID, alpha=0.35, linewidth=8,
               label='mid S-curve'),
    ]
    for key in height_order:
        z_value = HEIGHT_BY_KEY[key][1]
        handles.append(Line2D(
            [0], [0], marker='o', color='none',
            markerfacecolor=CMAP(NORM(z_value)), markersize=5.5,
            label='%s %+.2f mm' % (HEIGHT_BY_KEY[key][2], z_value)))
    ax.legend(handles=handles, loc='upper right', fontsize=6.8,
              framealpha=0.9)

    # bottom: route height profile + crossing heights
    if samples is not None and len(samples) >= 2:
        axz.plot(s_values, samples[:, 2], color=C_BODY, linewidth=1.4,
                 label='route z(s)')
    if rows:
        marker_z = [row['partner_z'] if row['partner_z'] is not None
                    else float('nan') for row in rows]
        axz.scatter([row['s_mm'] for row in rows], marker_z, marker='x',
                    s=22, c=C_CROSS, linewidths=0.8, zorder=6,
                    label='crossing plane z')
    axz.set_xlim(0.0, total_s)
    axz.set_ylim(Z_MIN - 0.05, Z_MAX + 0.05)
    axz.set_xlabel('arc length s along route (mm)')
    axz.set_ylabel('Z (mm)')
    axz.grid(True, linewidth=0.25, color='#dddddd')
    axz.legend(loc='upper right', fontsize=6.5, framealpha=0.9)
    axz.tick_params(labelsize=6.5)

    return _save_fig(fig, out_path)


# --------------------------------------------------------------------------- #
# (5) experiment B candidates summary
# --------------------------------------------------------------------------- #
def _normalise_candidates(candidates, strategy_key='strategy'):
    if isinstance(candidates, dict):
        for key in ('candidates', 'rows', 'items', 'records'):
            if isinstance(candidates.get(key), list):
                candidates = candidates[key]
                break
    out = []
    for entry in candidates or ():
        if not isinstance(entry, dict):
            continue
        rid = _pick(entry, ('route_id', 'id', 'route', 'rid'))
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            rid = None
        removed = _to_float(_pick(entry, (
            'removed', 'removed_crossings', 'removed_count', 'n_removed',
            'crossings_removed', 'removed_estimate')))
        added = _to_float(_pick(entry, (
            'added', 'added_crossings', 'added_count', 'n_added',
            'crossings_added', 'added_estimate')))
        net = _to_float(_pick(entry, ('net', 'net_crossings', 'net_change',
                                      'delta', 'expected_net')))
        if removed is None:
            removed = 0.0
        if added is None:
            added = 0.0
        if net is None:
            net = removed - added
        target_z = _to_float(_pick(entry, (
            'target_z', 'target_z_mm', 'to_z', 'target_height',
            'target_plane_z')))
        target_label = _pick(entry, ('target_label', 'target_plane_label',
                                     'target_layer', 'to_layer'), None)
        strategy = _pick(entry, (strategy_key, 'strategy_name', 'method',
                                 'kind'), 'unspecified')
        extra = _to_float(_pick(entry, (
            'extra_length_mm', 'extra_mm', 'extra_length', 'cost_mm',
            'added_length_mm'))) or 0.0
        out.append(dict(route_id=rid, target_z=target_z,
                        target_label=str(target_label)
                        if target_label is not None else '',
                        removed=float(removed), added=float(added),
                        net=float(net), strategy=str(strategy),
                        extra_length_mm=float(extra)))
    return out


def plot_experiment_b_summary(candidates, out_path):
    """Grouped bars removed vs added crossings per candidate + net line.

    ``candidates`` is a list of dicts with ``route_id, target_z, removed,
    added, net, strategy, extra_length_mm`` (extra keys are tolerated).
    The best candidates by net reduction are plotted; when there are more than
    30 candidates the figure notes that it shows the top 30.
    """
    path = Path(out_path)
    rows = _normalise_candidates(candidates)
    if not rows:
        _log(None, 'plot_experiment_b_summary: no candidates with numbers',
             level='warn')
        return None
    rows.sort(key=lambda row: (-row['net'], -row['removed'],
                               row['route_id'] if row['route_id']
                               is not None else 0))
    total = len(rows)
    if total > 30:
        rows = rows[:30]
    labels = []
    for row in rows:
        label = 'R%s' % (row['route_id'] if row['route_id'] is not None
                         else '?')
        if row['target_z'] is not None:
            label += '\n%s' % _height_text(row['target_z'])
        labels.append(label)
    x = np.arange(len(rows), dtype=float)
    removed = np.array([row['removed'] for row in rows], dtype=float)
    added = np.array([row['added'] for row in rows], dtype=float)
    net = np.array([row['net'] for row in rows], dtype=float)

    strategy_totals = OrderedDict()
    for row in rows:
        bucket = strategy_totals.setdefault(
            row['strategy'], dict(removed=0.0, added=0.0, count=0,
                                  net=0.0))
        bucket['removed'] += row['removed']
        bucket['added'] += row['added']
        bucket['net'] += row['net']
        bucket['count'] += 1
    strategies = sorted(strategy_totals,
                        key=lambda name: (-strategy_totals[name]['net'], name))

    fig = plt.figure(figsize=(16.0, 7.6))
    ax = fig.add_axes([0.05, 0.30, 0.55, 0.62])
    ax2 = fig.add_axes([0.68, 0.30, 0.29, 0.62])
    width = 0.38
    ax.bar(x - width / 2.0, removed, width, color=C_REMOVED,
           label='removed crossings', alpha=0.9)
    ax.bar(x + width / 2.0, added, width, color=C_ADDED,
           label='added crossings', alpha=0.9)
    ax.plot(x, net, color=C_NET, marker='o', markersize=4.5, linewidth=1.4,
            label='net = removed - added')
    for xi, net_value in zip(x, net):
        ax.text(xi, net_value + 0.15, '%+.0f' % net_value, fontsize=6.0,
                ha='center', va='bottom', color=C_NET)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.0, rotation=90)
    ax.set_ylabel('crossings')
    _set_count_ylim(ax, (removed, added, net))
    ax.axhline(0.0, color='#616161', linewidth=0.6)
    ax.grid(True, axis='y', linewidth=0.25, color='#dddddd')
    ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
    ax.set_title('Experiment B candidates: removed vs added crossings'
                 + (' (top 30 of %d by net reduction)' % total
                    if total > 30 else ''),
                 fontsize=10.0)

    sx = np.arange(len(strategies), dtype=float)
    s_removed = np.array([strategy_totals[name]['removed']
                          for name in strategies], dtype=float)
    s_added = np.array([strategy_totals[name]['added']
                        for name in strategies], dtype=float)
    s_net = np.array([strategy_totals[name]['net']
                      for name in strategies], dtype=float)
    ax2.bar(sx - width / 2.0, s_removed, width, color=C_REMOVED, alpha=0.9,
            label='removed')
    ax2.bar(sx + width / 2.0, s_added, width, color=C_ADDED, alpha=0.9,
            label='added')
    ax2.plot(sx, s_net, color=C_NET, marker='o', markersize=4.5,
             linewidth=1.4, label='net')
    for xi, net_value, name in zip(sx, s_net, strategies):
        ax2.text(xi, net_value + 0.15, '%+.0f\n(%d cand.)'
                 % (net_value, strategy_totals[name]['count']),
                 fontsize=6.0, ha='center', va='bottom', color=C_NET)
    ax2.set_xticks(sx)
    ax2.set_xticklabels([str(name) for name in strategies], fontsize=6.5,
                        rotation=30, ha='right')
    ax2.set_ylabel('crossings')
    _set_count_ylim(ax2, (s_removed, s_added, s_net))
    ax2.axhline(0.0, color='#616161', linewidth=0.6)
    ax2.grid(True, axis='y', linewidth=0.25, color='#dddddd')
    ax2.legend(loc='upper right', fontsize=7.0, framealpha=0.9)
    ax2.set_title('aggregated per strategy', fontsize=9.0)

    fig.suptitle('Experiment B: crossing changes of the evaluated '
                 'mid-body S-curve candidates', fontsize=11.0)
    return _save_fig(fig, path)


# --------------------------------------------------------------------------- #
# height panels (shared by E5 demo and experiment C)
# --------------------------------------------------------------------------- #
def plot_height_panels(routes, crossing_stats=None, out_dir=None,
                       manifest=None, only=None, prefix='height'):
    """The 21 real per-height XY figures (all flat parts grouped by real z)."""
    if not _wanted(only, 'height_panels'):
        return []
    routes = list(routes or ())
    if not routes:
        _skip(manifest, 'height_panels', 'no routes')
        return []
    out_dir = Path(out_dir or '.')
    cache = _RouteCache(routes)
    native_ids = {_route_id(route) for route in routes
                  if _n_mid(route) > 0 or route.get('native_3d')}
    events_by_key = _events_by_height(crossing_stats)
    transitions_by_key = defaultdict(list)
    for transition in cache.transitions:
        for z_value in (transition['z0'], transition['z1']):
            key = _height_key(z_value)
            if key is not None:
                transitions_by_key[key].append(transition)
    paths = []
    for order, (pid, z, label, kind) in enumerate(HEIGHT_ROWS):
        key = round(z, 6)
        entries = cache.flat_by_z.get(key, [])
        route_ids = {entry['route_id'] for entry in entries}
        events = events_by_key.get(key, [])
        native_entries = [entry for entry in entries
                          if entry['route_id'] in native_ids]
        others = [entry for entry in entries
                  if entry['route_id'] not in native_ids]
        z1_entries = [entry for entry in others
                      if entry['plane'].startswith('z1')]
        z2_entries = [entry for entry in others
                      if entry['plane'].startswith('z2')]
        other_entries = [entry for entry in others
                         if not entry['plane'].startswith('z1')
                         and not entry['plane'].startswith('z2')]
        fig, ax = plt.subplots(figsize=(8.5, 8.3))
        _draw_board(ax)
        for group_entries, colour, width, label_text in (
                (z1_entries, C_PLANE['z1'], 0.45, 'z1 routes'),
                (z2_entries, C_PLANE['z2'], 0.45, 'z2 routes'),
                (other_entries, '#7f7f7f', 0.45, 'other'),
                (native_entries, C_MID, 0.75,
                 'native 3D route flats (%d routes)' % len(
                     {entry['route_id'] for entry in native_entries}))):
            if not group_entries:
                continue
            ax.add_collection(LineCollection(
                [entry['pts'] for entry in group_entries], colors=colour,
                linewidths=width, alpha=0.9 if colour == C_MID else 0.75,
                label=label_text))
        transition_entries = transitions_by_key.get(key, [])
        if transition_entries:
            ax.add_collection(LineCollection(
                [transition['pts'][:, :2] for transition in transition_entries],
                colors='#9e9e9e', linewidths=0.35, linestyles=':',
                alpha=0.5, label='S-curve footprints on this height'))
        n_cross = _scatter_crossings(ax, events)
        _xy_limits(ax)
        crossing_text = ('crossings: %d' % n_cross if crossing_stats is not None
                         else 'crossings: n/a (no crossing_stats.json)')
        ax.set_title(
            '%s   z = %+.2f mm   [%s]\n'
            'routes on this height: %d   flat parts: %d   %s'
            % (label, z, kind, len(route_ids), len(entries), crossing_text),
            fontsize=10.5)
        handles, labels = ax.get_legend_handles_labels()
        seen = OrderedDict()
        for handle, text in zip(handles, labels):
            seen.setdefault(text, handle)
        if seen:
            ax.legend(seen.values(), seen.keys(), loc='upper right',
                      fontsize=6.5, framealpha=0.9)
        filename = '%s_%02d_%s.png' % (prefix, order + 1,
                                       _safe_token(label))
        paths.append(_save_fig(fig, out_dir / filename, manifest,
                               name='height_%02d_%s'
                                    % (order + 1, _safe_token(label))))
    return paths


def _overview_3d(routes, out_dir, manifest, only=None):
    if not _wanted(only, '3d_overview'):
        return None
    routes = list(routes or ())
    if not routes:
        _skip(manifest, '3d_overview', 'no routes')
        return None
    cache = _RouteCache(routes)
    segments, colours = [], []
    mid_points = []
    fanout_count = 0
    sampled_routes = 0
    for route in routes:
        polyline = cache.route_polyline3d(route, flat_stride=2)
        if polyline is None or len(polyline) < 2:
            continue
        sampled_routes += 1
        seg, col = _color_segments(polyline)
        if seg is not None:
            segments.append(seg)
            colours.append(col)
        for _index, part, tag in transition_records(route):
            if tag == 'mid':
                start = part.get('start') or []
                end = part.get('end') or []
                z0 = _to_float(part.get('z0'))
                z1 = _to_float(part.get('z1'))
                if len(start) >= 2 and len(end) >= 2 and z0 is not None \
                        and z1 is not None:
                    mid_points.append([(start[0] + end[0]) * 0.5,
                                       (start[1] + end[1]) * 0.5,
                                       (z0 + z1) * 0.5])
            else:
                fanout_count += 1
    if not segments:
        _skip(manifest, '3d_overview', 'no drawable route geometry')
        return None
    all_segments = np.concatenate(segments, axis=0)
    all_colours = np.concatenate(colours, axis=0)
    n_mid = len(mid_points)

    fig = plt.figure(figsize=(13.6, 11.2))
    ax = fig.add_subplot(111, projection='3d')
    collection = Line3DCollection(all_segments, colors=all_colours,
                                  linewidths=0.25, alpha=0.62)
    ax.add_collection3d(collection, autolim=False)

    # glass box + interface reference planes (real process heights)
    for z in (Z_MIN, Z_MAX):
        ax.plot([0, BOARD_MM, BOARD_MM, 0, 0], [0, 0, BOARD_MM, BOARD_MM, 0],
                [z] * 5, color='#9e9e9e', linewidth=0.5, alpha=0.6)
    for x, y in ((0, 0), (BOARD_MM, 0), (BOARD_MM, BOARD_MM), (0, BOARD_MM)):
        ax.plot([x, x], [y, y], [Z_MIN, Z_MAX], color='#9e9e9e',
                linewidth=0.4, alpha=0.5)
    for z, name in ((INTERFACE_Z[0], 'Z1 interface'), (INTERFACE_Z[1],
                                                       'Z2 interface')):
        verts = [[(0, 0, z), (BOARD_MM, 0, z), (BOARD_MM, BOARD_MM, z),
                  (0, BOARD_MM, z)]]
        ax.add_collection3d(Poly3DCollection(
            verts, facecolor='#90caf9', edgecolor='#64b5f6', alpha=0.06,
            linewidths=0.4))
        ax.text(BOARD_MM * 0.02, BOARD_MM * 1.01, z,
                '%s z=%+.2f' % (name, z), fontsize=6.5, color='#1565c0')

    if mid_points:
        points = np.asarray(mid_points, dtype=float)
        ax.scatter(points[:, 0], points[:, 1], points[:, 2], marker='D',
                   s=16, c=C_MID, edgecolors='white', linewidths=0.35,
                   depthshade=False,
                   label='mid-body S-curves (%d)' % n_mid)
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_zlim(Z_MIN - 0.05, Z_MAX + 0.05)
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.view_init(elev=23, azim=-58)
    try:
        ax.set_box_aspect((1.5, 1.5, 0.8))
    except (AttributeError, ValueError):  # pragma: no cover
        pass
    ax.set_title(
        'All %d routes in true 3D   |   colour = physical z '
        '(%d mid-body S-curves marked)\n'
        'flat parts sampled at ~4 mm, stored S-curves at 0.4 mm; '
        'glass z = %.2f .. %.2f mm'
        % (len(routes), n_mid, Z_MIN, Z_MAX), fontsize=10.5)
    sm = plt.cm.ScalarMappable(norm=NORM, cmap=CMAP)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.08, shrink=0.65,
                 label='physical z (mm)')
    handles = [Line2D([0], [0], color=C_MID, marker='D', linestyle='none',
                      markersize=6,
                      label='mid-body S-curve (%d)' % n_mid)]
    ax.legend(handles=handles, loc='upper right', fontsize=8.0,
              framealpha=0.9)
    return _save_fig(fig, Path(out_dir) / '3d_overview_1024.png', manifest,
                     name='3d_overview_1024')


# --------------------------------------------------------------------------- #
# crossing-vs-iteration curve
# --------------------------------------------------------------------------- #
def _pick_column(headers, candidates):
    lookup = {str(header).strip().lower(): header for header in headers}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


def _dashboard_crossing_curve(run_dir, out_dir, manifest, only=None):
    if not _wanted(only, 'crossing_curve'):
        return None
    path = _find_path(run_dir, 'optimization_history.csv')
    if path is None:
        _skip(manifest, 'crossing_curve',
              'optimization_history.csv missing')
        return None
    rows = _read_csv_rows(path)
    if not rows:
        _skip(manifest, 'crossing_curve', 'optimization_history.csv empty')
        return None
    headers = list(rows[0].keys())
    iteration_col = _pick_column(headers, (
        'iteration', 'iter', 'step', 'round', 'epoch', 'pass', 'sweep'))
    stage_col = _pick_column(headers, ('stage', 'phase', 'pass_name'))
    crossing_col = _pick_column(headers, (
        'total_crossings', 'crossings', 'n_crossings', 'num_crossings',
        'crossing_count', 'crossings_total', 'crossing_events'))
    pairs_col = _pick_column(headers, (
        'crossing_pairs', 'pairs', 'unique_crossing_pairs'))
    if crossing_col is None:
        _skip(manifest, 'crossing_curve',
              'optimization_history.csv has no crossings column (headers: %s)'
              % ', '.join(headers))
        return None
    xs, ys, pair_values, stage_labels = [], [], [], []
    for index, row in enumerate(rows):
        y = _to_float(row.get(crossing_col))
        if y is None:
            continue
        x = _to_float(row.get(iteration_col)) if iteration_col else None
        if x is None:
            x = float(index + 1)
        xs.append(x)
        ys.append(y)
        pair_values.append(_to_float(row.get(pairs_col))
                           if pairs_col is not None else None)
        stage = row.get(stage_col) if stage_col is not None else None
        sweep = _to_float(row.get('sweep')) if 'sweep' in headers else None
        if stage is not None and str(stage).strip():
            stage_labels.append(str(stage) + (
                ' / s%d' % int(sweep) if sweep is not None else ''))
        else:
            stage_labels.append('')
    if not xs:
        _skip(manifest, 'crossing_curve',
              'no numeric rows in column %r' % crossing_col)
        return None
    # per-stage sweep counters restart at 1 -> fall back to a running step axis
    if any(second <= first for first, second in zip(xs, xs[1:])):
        xs = [float(index + 1) for index in range(len(xs))]
        iteration_label = 'optimization step'
    else:
        iteration_label = str(iteration_col or 'step')
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.plot(xs, ys, color=C_ADDED, marker='o', markersize=4.5, linewidth=1.6,
            label=str(crossing_col))
    if any(value is not None for value in pair_values):
        valid = [(x, value) for x, value in zip(xs, pair_values)
                 if value is not None]
        if valid:
            ax.plot([item[0] for item in valid],
                    [item[1] for item in valid], color='#1565c0',
                    linestyle='--', marker='s', markersize=3.5,
                    linewidth=1.1, label=str(pairs_col))
    best_index = int(np.argmin(ys))
    ax.scatter([xs[best_index]], [ys[best_index]], s=90, facecolors='none',
               edgecolors='#2e7d32', linewidths=1.6, zorder=5,
               label='best %s at step %s' % (_fmt_count(ys[best_index]),
                                             _fmt_count(xs[best_index])))
    ax.annotate('final: %s' % _fmt_count(ys[-1]), xy=(xs[-1], ys[-1]),
                xytext=(-50, 14), textcoords='offset points', fontsize=8.0,
                color='#424242',
                arrowprops=dict(arrowstyle='->', color='#616161', lw=0.7))
    ax.set_xlabel(iteration_label)
    ax.set_ylabel('crossings')
    ax.grid(True, linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
    if any(stage_labels):
        ax.set_xticks(xs)
        ax.set_xticklabels(stage_labels, fontsize=7.0, rotation=20,
                           ha='right')
    reduction = ys[0] - ys[-1]
    ax.set_title('Crossing count per optimization step\n'
                 '%s -> %s  (reduction %s, best %s)'
                 % (_fmt_count(ys[0]), _fmt_count(ys[-1]),
                    ('%+g' % reduction), _fmt_count(min(ys))), fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'crossing_curve.png', manifest,
                     name='crossing_curve')


# --------------------------------------------------------------------------- #
# per-layer before / after bars
# --------------------------------------------------------------------------- #
def _dashboard_per_layer(baseline_stats, final_stats, out_dir, manifest,
                         only=None):
    if not _wanted(only, 'per_layer_before_after'):
        return None
    if final_stats is None:
        _skip(manifest, 'per_layer_before_after',
              'final crossing_stats.json missing')
        return None
    before_rows = _plane_rows(baseline_stats)
    after_rows = _plane_rows(final_stats)
    if not after_rows:
        _skip(manifest, 'per_layer_before_after',
              'final crossing_stats.json has no planes table')
        return None
    labels, zs, before, after = [], [], [], []
    for pid, z, label, _kind in HEIGHT_ROWS:
        labels.append(label)
        zs.append(z)
        before_row = before_rows.get(pid) or {}
        after_row = after_rows.get(pid) or {}
        before.append(_to_float(before_row.get('crossings')) or 0.0)
        after.append(_to_float(after_row.get('crossings')) or 0.0)
    fig, ax = plt.subplots(figsize=(14.0, 6.6))
    x = np.arange(len(labels), dtype=float)
    width = 0.4
    if before_rows:
        ax.bar(x - width / 2.0, before, width, color='#9e9e9e', alpha=0.9,
               label='E5 baseline (%d crossings)' % int(sum(before)))
    else:
        before = [0.0] * len(labels)
    ax.bar(x + width / 2.0, after, width, color='#1565c0', alpha=0.9,
           label='native 3D final (%d crossings)' % int(sum(after)))
    for xi, before_value, after_value in zip(x, before, after):
        if before_value or after_value:
            ax.text(xi, max(before_value, after_value) + 0.8,
                    '%d / %d' % (int(before_value), int(after_value)),
                    fontsize=5.8, ha='center', va='bottom',
                    color='#424242', rotation=90)
    ax.set_xticks(x)
    ax.set_xticklabels(['%s\n%+.2f' % (label, z)
                        for label, z in zip(labels, zs)], fontsize=6.5,
                       rotation=60, ha='right')
    ax.set_ylabel('crossing events on the height')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=8.0, framealpha=0.9)
    ax.set_title('Per-height crossings: frozen E5 baseline vs native 3D final\n'
                 '(all 21 real routing heights, sorted by physical z)',
                 fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'per_layer_before_after.png',
                     manifest, name='per_layer_before_after')


# --------------------------------------------------------------------------- #
# top-10 routes before / after
# --------------------------------------------------------------------------- #
def _dashboard_top10(baseline_stats, final_stats, out_dir, manifest,
                     only=None):
    if not _wanted(only, 'top10_routes_before_after'):
        return None
    before_counts = _per_route_counts(baseline_stats)
    after_counts = _per_route_counts(final_stats)
    if not before_counts and not after_counts:
        _skip(manifest, 'top10_routes_before_after',
              'no per-route crossing counts available')
        return None
    ranking = before_counts if before_counts else after_counts
    top = sorted(ranking, key=lambda rid: (-ranking.get(rid, 0), rid))[:10]
    if not top:
        _skip(manifest, 'top10_routes_before_after', 'no routes with crossings')
        return None
    fig = plt.figure(figsize=(15.0, 6.6))
    ax = fig.add_axes([0.05, 0.28, 0.50, 0.64])
    axs = fig.add_axes([0.65, 0.28, 0.32, 0.60])
    x = np.arange(len(top), dtype=float)
    width = 0.38
    before = [float(before_counts.get(rid, 0)) for rid in top]
    after = [float(after_counts.get(rid, 0)) for rid in top]
    ax.bar(x - width / 2.0, before, width, color='#9e9e9e',
           label='E5 baseline')
    ax.bar(x + width / 2.0, after, width, color='#1565c0',
           label='native 3D final')
    for xi, before_value, after_value in zip(x, before, after):
        ax.text(xi - width / 2.0, before_value + 0.4, '%d' % before_value,
                fontsize=6.2, ha='center', va='bottom', color='#424242')
        ax.text(xi + width / 2.0, after_value + 0.4, '%d' % after_value,
                fontsize=6.2, ha='center', va='bottom', color='#1565c0')
    ax.set_xticks(x)
    ax.set_xticklabels(['R%d' % rid for rid in top], fontsize=8.0)
    ax.set_ylabel('crossings of the route')
    _set_count_ylim(ax, (before, after))
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=8.0, framealpha=0.9)
    ax.set_title('Top-10 routes by crossing count: before vs after',
                 fontsize=10.5)

    if before_counts and after_counts:
        all_ids = sorted(set(before_counts) | set(after_counts))
        xs = [before_counts.get(rid, 0) for rid in all_ids]
        ys = [after_counts.get(rid, 0) for rid in all_ids]
        axs.scatter(xs, ys, s=10, color='#90a4ae', alpha=0.55,
                    label='all routes')
        top_before = [before_counts.get(rid, 0) for rid in top]
        top_after = [after_counts.get(rid, 0) for rid in top]
        axs.scatter(top_before, top_after, s=30, color='#c62828',
                    label='top-10', zorder=4)
        for rid, bx, by in zip(top, top_before, top_after):
            axs.annotate('R%d' % rid, (bx, by), fontsize=5.5,
                         xytext=(2, 2), textcoords='offset points')
        limit = max(max(xs, default=1), max(ys, default=1)) + 1.0
        axs.plot([0, limit], [0, limit], color='#616161', linestyle='--',
                 linewidth=0.7)
        axs.set_xlim(0, limit)
        axs.set_ylim(0, limit)
        axs.set_xlabel('baseline crossings')
        axs.set_ylabel('final crossings')
        axs.grid(True, linewidth=0.3, color='#e0e0e0')
        axs.legend(loc='upper left', fontsize=6.5, framealpha=0.9)
        axs.set_title('per-route: below the diagonal = improvement',
                      fontsize=9.0)
    else:
        axs.axis('off')
        axs.text(0.5, 0.5, 'before/after per-route counts\nnot both available',
                 ha='center', va='center', fontsize=8.0,
                 transform=axs.transAxes)
    return _save_fig(fig, Path(out_dir) / 'top10_routes_before_after.png',
                     manifest, name='top10_routes_before_after')


# --------------------------------------------------------------------------- #
# native statistics: mid transition counts + extra length
# --------------------------------------------------------------------------- #
def _dashboard_mid_transition_counts(baseline_routes, routes, out_dir,
                                     manifest, only=None):
    if not _wanted(only, 'mid_transition_counts'):
        return None
    if not routes:
        _skip(manifest, 'mid_transition_counts', 'no final routes')
        return None
    final_counts = [_n_mid(route) for route in routes]
    baseline_counts = [_n_mid(route) for route in baseline_routes or ()]
    max_count = max(final_counts + baseline_counts + [1])
    bins = list(range(0, max_count + 2))
    final_hist = Counter(final_counts)
    baseline_hist = Counter(baseline_counts)
    fig, ax = plt.subplots(figsize=(11.0, 5.8))
    width = 0.38
    xs = np.arange(len(bins), dtype=float) - 0.5
    if baseline_counts:
        ax.bar(xs - width / 2.0,
               [baseline_hist.get(count, 0) for count in bins], width,
               color='#9e9e9e', label='E5 baseline (%d routes)'
               % len(baseline_counts))
    ax.bar(xs + width / 2.0,
           [final_hist.get(count, 0) for count in bins], width,
           color=C_MID, alpha=0.85,
           label='native 3D final (%d routes)' % len(routes))
    for xi, count in zip(xs, bins):
        value = final_hist.get(count, 0)
        if value:
            ax.text(xi + width / 2.0, value + 2.0, '%d' % value,
                    fontsize=6.0, ha='center', va='bottom', color='#6a1b9a')
    ax.set_xticks(xs)
    ax.set_xticklabels([str(count) for count in bins], fontsize=8.0)
    ax.set_xlabel('mid-body S-curve transitions per route')
    ax.set_ylabel('number of routes')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=8.0, framealpha=0.9)
    n_routes_with_mid = sum(1 for count in final_counts if count > 0)
    ax.set_title(
        'Native 3D mid-body S-curves per route\n'
        '%d of %d routes use at least one mid excursion (total %d)'
        % (n_routes_with_mid, len(routes), sum(final_counts)), fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'mid_transition_counts.png',
                     manifest, name='mid_transition_counts')


def _dashboard_extra_length(baseline_routes, routes, out_dir, manifest,
                            only=None):
    if not _wanted(only, 'extra_length_distribution'):
        return None
    baseline_by_id = _routes_by_id(baseline_routes)
    if not routes or not baseline_by_id:
        _skip(manifest, 'extra_length_distribution',
              'final routes or E5 baseline routes missing')
        return None
    extras = []
    for route in routes:
        rid = _route_id(route)
        before = baseline_by_id.get(rid)
        if before is None:
            continue
        extras.append(_route_length(route) - _route_length(before))
    if not extras:
        _skip(manifest, 'extra_length_distribution',
              'no route ids shared with the baseline')
        return None
    values = np.asarray(extras, dtype=float)
    changed_mask = np.abs(values) > 1e-9
    changed = int(changed_mask.sum())
    mean_value = float(values.mean())
    median_value = float(np.median(values))

    if changed:
        fig = plt.figure(figsize=(15.0, 5.9))
        ax = fig.add_axes([0.05, 0.17, 0.46, 0.72])
        ax2 = fig.add_axes([0.60, 0.17, 0.37, 0.72])
    else:
        fig = plt.figure(figsize=(11.0, 5.8))
        ax = fig.add_axes([0.07, 0.14, 0.88, 0.76])
        ax2 = None
    ax.hist(values, bins=40, color='#1565c0', alpha=0.85,
            edgecolor='white', linewidth=0.4)
    ax.axvline(mean_value, color=C_ADDED, linestyle='--', linewidth=1.1,
               label='mean %+.4f mm' % mean_value)
    ax.axvline(median_value, color='#2e7d32', linestyle=':', linewidth=1.2,
               label='median %+.4f mm' % median_value)
    ax.axvline(0.0, color='#616161', linewidth=0.6)
    ax.text(0.02, 0.96,
            'n = %d routes\nchanged: %d\nmean %+.4f mm\nmedian %+.4f mm\n'
            'max +%.4f / min %+.4f mm'
            % (len(values), changed, mean_value, median_value,
               float(values.max()), float(values.min())),
            transform=ax.transAxes, fontsize=8.0, va='top',
            bbox=dict(boxstyle='round,pad=0.35', facecolor='white',
                      edgecolor='#bdbdbd', alpha=0.9))
    ax.set_xlabel('extra true 3D length of the final route vs frozen E5 (mm)')
    ax.set_ylabel('number of routes')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=8.0, framealpha=0.9)
    ax.set_title('All %d routes: length difference vs frozen E5'
                 % len(values), fontsize=10.0)

    if ax2 is not None:
        changed_routes = []
        route_by_id = _routes_by_id(routes)
        for route in routes:
            rid_int = _route_id(route)
            if rid_int is None:
                continue
            before = baseline_by_id.get(rid_int)
            final = route_by_id.get(rid_int)
            if before is None or final is None:
                continue
            extra = _route_length(final) - _route_length(before)
            if abs(extra) > 1e-9:
                changed_routes.append((rid_int, extra, final))
        changed_routes.sort(key=lambda item: (-item[1], item[0]))
        labels = []
        for rid, _extra, route in changed_routes:
            target_z = _mid_target_z(route)
            labels.append('R%d\n%s' % (rid, _height_text(target_z)
                                       if target_z is not None else ''))
        x = np.arange(len(changed_routes), dtype=float)
        heights = [item[1] for item in changed_routes]
        ax2.bar(x, heights, 0.55, color=C_MID, alpha=0.85)
        label_offset = max(abs(value) for value in heights) * 0.04
        for xi, extra in zip(x, heights):
            ax2.text(xi, extra + label_offset, '%+.4f' % extra,
                     fontsize=6.0, ha='center', va='bottom',
                     color='#4a148c',
                     rotation=90 if len(changed_routes) > 8 else 0)
        ax2.set_xticks(x)
        ax2.set_xticklabels(labels, fontsize=6.0,
                            rotation=90 if len(changed_routes) > 8 else 0)
        ax2.set_ylabel('extra length (mm)')
        ax2.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
        _set_count_ylim(ax2, (heights,))
        ax2.set_title('Changed routes only (%d): length cost and target height'
                      % len(changed_routes), fontsize=10.0)
    fig.suptitle('Length cost of the Native 3D mid-body excursions '
                 '(real route records)', fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'extra_length_distribution.png',
                     manifest, name='extra_length_distribution')


# --------------------------------------------------------------------------- #
# crossing hotspot
# --------------------------------------------------------------------------- #
def _smooth2d(grid):
    kernel = np.array([[1.0, 2.0, 1.0], [2.0, 4.0, 2.0], [1.0, 2.0, 1.0]])
    kernel /= kernel.sum()
    padded = np.pad(grid, 1, mode='constant')
    out = np.zeros_like(grid, dtype=float)
    rows, cols = grid.shape
    for dy in range(3):
        for dx in range(3):
            out += kernel[dy, dx] * padded[dy:dy + rows, dx:dx + cols]
    return out


def _dashboard_hotspot(final_stats, out_dir, manifest, only=None):
    if not _wanted(only, 'crossing_hotspot'):
        return None
    events = (final_stats or {}).get('crossing_events') or ()
    coords = []
    z_values = []
    for event in events:
        x = _to_float(event.get('x_mm'))
        y = _to_float(event.get('y_mm'))
        if x is None or y is None:
            continue
        coords.append((x, y))
        z_values.append(_to_float(event.get('z_mm')))
    if not coords:
        _skip(manifest, 'crossing_hotspot',
              'no crossing events with x/y coordinates')
        return None
    xs = np.array([point[0] for point in coords])
    ys = np.array([point[1] for point in coords])
    bins = 75
    grid, x_edges, y_edges = np.histogram2d(
        xs, ys, bins=bins, range=[[0.0, BOARD_MM], [0.0, BOARD_MM]])
    smooth = _smooth2d(grid)
    fig, ax = plt.subplots(figsize=(10.6, 9.0))
    image = ax.imshow(np.log1p(smooth.T), origin='lower',
                      extent=[x_edges[0], x_edges[-1], y_edges[0],
                              y_edges[-1]],
                      cmap='inferno', aspect='equal', interpolation='nearest')
    _draw_board(ax, label='')
    ax.set_xlim(-2.0, BOARD_MM + 2.0)
    ax.set_ylim(-2.0, BOARD_MM + 2.0)
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    cb = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.03)
    cb.set_label('log(1 + crossings per cell)')
    max_cell = float(smooth.max())
    hotspot_y, hotspot_x = np.unravel_index(int(np.argmax(smooth)),
                                            smooth.shape)
    hx = (x_edges[hotspot_x] + x_edges[hotspot_x + 1]) * 0.5
    hy = (y_edges[hotspot_y] + y_edges[hotspot_y + 1]) * 0.5
    ax.scatter([hx], [hy], s=180, facecolors='none', edgecolors='#00e5ff',
               linewidths=1.4, label='hottest cell (%.0f, %.0f) mm' % (hx, hy))
    heights = sorted({_height_key(z) for z in z_values if z is not None})
    ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
    ax.set_title(
        'Final crossing-event density hotspot (all %d real events, %d planes)\n'
        'grid %dx%d cells; hottest cell = %.1f events'
        % (len(coords), len(heights), bins, bins, max_cell), fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'crossing_hotspot.png', manifest,
                     name='crossing_hotspot')


# --------------------------------------------------------------------------- #
# example route height profiles
# --------------------------------------------------------------------------- #
def _pick_example_routes(routes, final_stats=None, count=4):
    routes = list(routes or ())
    if not routes:
        return []
    counts = _per_route_counts(final_stats)
    by_mid = sorted(routes, key=lambda route: (
        -_n_mid(route), -len(_parts(route)),
        _route_id(route) or 0))
    picks = []
    for route in by_mid:
        if _n_mid(route) <= 0:
            break
        if route not in picks:
            picks.append(route)
        if len(picks) >= 2:
            break
    by_cross = sorted(routes, key=lambda route: (
        -counts.get(_route_id(route), 0), -_n_mid(route),
        _route_id(route) or 0))
    for route in by_cross:
        if route not in picks:
            picks.append(route)
        if len(picks) >= count:
            break
    if len(picks) < count:
        by_length = sorted(routes, key=lambda route: (
            -_route_length(route), _route_id(route) or 0))
        for route in by_length:
            if route not in picks:
                picks.append(route)
            if len(picks) >= count:
                break
    return picks[:count]


def _dashboard_height_profiles(routes, final_stats, out_dir, manifest,
                               only=None):
    if not _wanted(only, 'route_height_profile_examples'):
        return None
    examples = _pick_example_routes(routes, final_stats, count=4)
    if not examples:
        _skip(manifest, 'route_height_profile_examples', 'no routes')
        return None
    counts = _per_route_counts(final_stats)
    fig, axes = plt.subplots(2, 2, figsize=(14.0, 8.4))
    axes = list(axes.ravel())
    for position, route in enumerate(examples):
        ax = axes[position]
        samples, s_values = route_s_z(route, step_flat=1.0,
                                      step_transition=0.2)
        if samples is None or len(samples) < 2:
            ax.axis('off')
            continue
        parts = _parts(route)
        tags = {index: tag for index, _part, tag in transition_records(route)}
        offset = 0.0
        for index, part in enumerate(parts):
            length = N.part_length(part)
            if part.get('kind') == 'transition':
                tag = tags.get(index, 'fanout')
                ax.axvspan(offset, offset + length,
                           color=C_MID if tag == 'mid' else '#90a4ae',
                           alpha=0.22 if tag == 'mid' else 0.13, zorder=0)
            else:
                z = _to_float(part.get('z_mm'))
                if z is not None:
                    ax.text(offset + length * 0.5, z, _height_text(z),
                            fontsize=5.5, ha='center', va='bottom',
                            color=CMAP(NORM(z)))
            offset += length
        mid_z = (samples[:-1, 2] + samples[1:, 2]) * 0.5
        profile_segments = np.stack([
            np.column_stack([s_values[:-1], samples[:-1, 2]]),
            np.column_stack([s_values[1:], samples[1:, 2]])], axis=1)
        ax.add_collection(LineCollection(profile_segments,
                                         colors=CMAP(NORM(mid_z)),
                                         linewidths=1.6))
        ax.set_xlim(0.0, offset)
        ax.set_ylim(Z_MIN - 0.05, Z_MAX + 0.05)
        ax.set_xlabel('arc length s (mm)', fontsize=7.0)
        ax.set_ylabel('Z (mm)', fontsize=7.0)
        ax.grid(True, linewidth=0.3, color='#e0e0e0')
        ax.tick_params(labelsize=6.5)
        n_mid = _n_mid(route)
        ax.set_title(
            'R%s  plane=%s  length %.2f mm  mid S-curves: %d  crossings: %d'
            % (_route_id(route), _plane(route) or '?', _route_length(route),
               n_mid, counts.get(_route_id(route), 0)), fontsize=8.5)
        handles = [
            Line2D([0], [0], color=C_MID, alpha=0.4, linewidth=8,
                   label='mid S-curve'),
            Line2D([0], [0], color='#90a4ae', alpha=0.4, linewidth=8,
                   label='fanout S-curve'),
        ]
        ax.legend(handles=handles, loc='upper right', fontsize=6.0,
                  framealpha=0.9)
    for ax in axes[len(examples):]:
        ax.axis('off')
    fig.suptitle('Route height profiles z(s) of example routes: stored flat '
                 'heights and real S-curve transitions (colour = z)',
                 fontsize=11.0)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save_fig(fig, Path(out_dir) / 'route_height_profile_examples.png',
                     manifest, name='route_height_profile_examples')


# --------------------------------------------------------------------------- #
# (6) experiment C dashboard
# --------------------------------------------------------------------------- #
def _guarded(manifest, name, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - a bad input must not kill the run
        traceback.print_exc()
        _skip(manifest, name, 'exception: %r' % (exc,))
        return None


def _guarded_figure(manifest, name, func, *args, **kwargs):
    """Run a standalone figure function and record the produced path(s)."""
    result = _guarded(manifest, name, func, *args, **kwargs)
    if result is None:
        return None
    paths = result if isinstance(result, (list, tuple)) else [result]
    for path in paths:
        try:
            if isinstance(path, Path) and path.exists():
                _record_figure(manifest, name, path)
        except OSError:
            continue
    return result


def plot_experiment_c_dashboard(run_dir, out_dir, baseline_dir=None,
                                only=None):
    """Produce the complete experiment-C figure set into ``out_dir``."""
    started = time.time()
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(N.E5_DIR)
    manifest = _new_manifest('experiment_C', run_dir, out_dir)
    _log(manifest, 'experiment C dashboard: run_dir=%s baseline=%s'
         % (run_dir, baseline_dir))

    routes_path = _find_path(run_dir, 'routes_l3d.json')
    routes = _load_routes_file(routes_path) if routes_path else None
    if not routes:
        _skip(manifest, 'all', 'routes_l3d.json missing or empty in %s'
              % run_dir)
        return _finish_manifest(manifest, out_dir, started)
    stats_path = _find_path(run_dir, 'crossing_stats.json')
    final_stats = _read_json(stats_path) if stats_path else None
    history_path = _find_path(run_dir, 'optimization_history.csv')
    checkpoint_path = _find_path(run_dir, 'checkpoints/best_routes_l3d.json')
    baseline_routes = load_routes(baseline_dir)
    baseline_stats = load_crossing_stats(baseline_dir)
    manifest['data'] = dict(
        routes_file=str(routes_path),
        crossing_stats_file=str(stats_path) if stats_path else None,
        optimization_history_file=str(history_path) if history_path else None,
        checkpoint_file=str(checkpoint_path) if checkpoint_path else None,
        baseline_dir=str(baseline_dir),
        baseline_routes_file=str(_find_path(baseline_dir, 'routes_l3d.json')),
        baseline_crossing_stats_file=str(
            _find_path(baseline_dir, 'crossing_stats.json')),
        route_count=len(routes),
        baseline_route_count=len(baseline_routes or ()),
        crossing_events_total=len((final_stats or {}).get(
            'crossing_events') or ()),
        baseline_crossing_events_total=len((baseline_stats or {}).get(
            'crossing_events') or ()),
    )
    _log(manifest, 'loaded %d final routes, %d baseline routes, '
         '%d final crossing events'
         % (len(routes), len(baseline_routes or ()),
            manifest['data']['crossing_events_total']))

    _guarded(manifest, 'height_panels', plot_height_panels, routes,
             final_stats, out_dir, manifest, only, 'height')
    _guarded(manifest, '3d_overview', _overview_3d, routes, out_dir,
             manifest, only)
    _guarded(manifest, 'crossing_curve', _dashboard_crossing_curve, run_dir,
             out_dir, manifest, only)
    _guarded(manifest, 'per_layer_before_after', _dashboard_per_layer,
             baseline_stats, final_stats, out_dir, manifest, only)
    _guarded(manifest, 'top10_routes_before_after', _dashboard_top10,
             baseline_stats, final_stats, out_dir, manifest, only)
    _guarded(manifest, 'mid_transition_counts',
             _dashboard_mid_transition_counts, baseline_routes, routes,
             out_dir, manifest, only)
    _guarded(manifest, 'extra_length_distribution',
             _dashboard_extra_length, baseline_routes, routes, out_dir,
             manifest, only)
    _guarded(manifest, 'crossing_hotspot', _dashboard_hotspot, final_stats,
             out_dir, manifest, only)
    _guarded(manifest, 'route_height_profile_examples',
             _dashboard_height_profiles, routes, final_stats, out_dir,
             manifest, only)
    return _finish_manifest(manifest, out_dir, started)


# --------------------------------------------------------------------------- #
# experiment A dashboard (native route changes with real parts)
# --------------------------------------------------------------------------- #
def _extract_route_records(payload):
    """Route records with real ``parts`` from tolerated experiment-A payloads."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = None
        for key in ('routes', 'accepted_routes', 'accepted', 'results',
                    'route_records', 'records', 'comparisons'):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        if items is None:
            items = [payload]
    else:
        return []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        found = None
        for key in ('route', 'after_route', 'after', 'native_route',
                    'accepted_route', 'final_route'):
            candidate = item.get(key)
            if isinstance(candidate, dict) and candidate.get('parts'):
                found = candidate
                break
        if found is None and item.get('parts'):
            found = item
        if found is not None and _route_id(found) is not None:
            records.append(found)
    return records


def _extract_candidates(payload):
    rows = _normalise_candidates(payload)
    return rows


def _route_comparison_entries(comparison_dir):
    """Tolerated parse of ``experiment_A/route_comparison/*.json``."""
    comparison_dir = Path(comparison_dir)
    if not comparison_dir.exists():
        return []
    entries = []
    for path in sorted(comparison_dir.glob('*.json')):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        merged = {}
        for key in ('comparison', 'crossings', 'metrics', 'summary'):
            if isinstance(payload.get(key), dict):
                merged.update(payload[key])
        merged.update({key: value for key, value in payload.items()
                       if not isinstance(value, dict)})
        rid = _pick(merged, ('route_id', 'id', 'rid'))
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            digits = ''.join(char for char in path.stem if char.isdigit())
            rid = int(digits) if digits else None
        before = _to_float(_pick(merged, (
            'before_crossings', 'baseline_crossings', 'crossings_before',
            'before', 'from_crossings', 'old_crossings')))
        after = _to_float(_pick(merged, (
            'after_crossings', 'final_crossings', 'crossings_after', 'after',
            'to_crossings', 'new_crossings', 'accepted_crossings')))
        if before is None and after is None:
            continue
        entries.append(dict(path=path, route_id=rid, before=before,
                            after=after))
    entries.sort(key=lambda item: (item['route_id'] if item['route_id']
                                   is not None else 10 ** 9, str(item['path'])))
    return entries


def _route_comparison_figure(entries, out_path, manifest=None,
                             source_note=None):
    if not entries:
        return None
    rows = [entry for entry in entries
            if entry['before'] is not None and entry['after'] is not None]
    if not rows:
        return None
    labels = ['R%s' % (entry['route_id'] if entry['route_id'] is not None
                       else '?') for entry in rows]
    before = [entry['before'] for entry in rows]
    after = [entry['after'] for entry in rows]
    x = np.arange(len(rows), dtype=float)
    width = 0.38
    fig, ax = plt.subplots(figsize=(max(9.0, 1.1 * len(rows) + 6.0), 5.8))
    ax.bar(x - width / 2.0, before, width, color='#9e9e9e',
           label='before')
    ax.bar(x + width / 2.0, after, width, color='#1565c0', label='after')
    for xi, before_value, after_value in zip(x, before, after):
        if before_value:
            ax.text(xi - width / 2.0, before_value, '%d' % before_value,
                    fontsize=6.0, ha='center', va='bottom')
        if after_value:
            ax.text(xi + width / 2.0, after_value, '%d' % after_value,
                    fontsize=6.0, ha='center', va='bottom')
    _set_count_ylim(ax, (before, after))
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.5, rotation=90)
    ax.set_ylabel('crossings of the route')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=8.0, framealpha=0.9)
    ax.set_title('Experiment A: per-route crossing comparison '
                 '(%d routes with before/after)%s'
                 % (len(rows),
                    ('\nsource: %s' % source_note) if source_note else ''),
                 fontsize=10.5)
    return _save_fig(fig, out_path, manifest, name=Path(out_path).stem)


def _a2_route_changes(run_dir):
    """``[(before, after)]`` from ``experiment_A/a2_single_route_result.json``."""
    path = _find_path(run_dir, 'a2_single_route_result.json')
    if path is None:
        return []
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return []
    pairs = []
    for item in payload.get('changes') or ():
        if not isinstance(item, dict):
            continue
        before = item.get('before')
        after = item.get('after')
        if isinstance(after, dict) and after.get('parts'):
            pairs.append((before if isinstance(before, dict) and
                          before.get('parts') else None, after))
    return pairs


def _experiment_a_candidates(run_dir):
    """Candidate rows from any experiment-A artifact (tolerant parser)."""
    payload = _read_json(_find_path(run_dir, 'candidates.json')) \
        if _find_path(run_dir, 'candidates.json') else None
    rows = _normalise_candidates(payload)
    if rows:
        return rows, 'candidates.json'
    scan_path = _find_path(run_dir, 'a1_scan.json')
    if scan_path is not None:
        scan = _read_json(scan_path)
        rows = []
        for record in (scan or {}).get('routes_scanned') or ():
            if not isinstance(record, dict):
                continue
            delta = _to_float(_pick(record, ('best_delta', 'delta', 'net')))
            if delta is None:
                continue
            rid = _pick(record, ('route_id', 'id'))
            try:
                rid = int(rid)
            except (TypeError, ValueError):
                continue
            rows.append(dict(
                route_id=rid,
                target_z=_to_float(_pick(record, ('best_target_z',
                                                  'target_z'))),
                removed=max(0.0, -delta), added=max(0.0, delta), net=delta,
                strategy='a1_scan', extra_length_mm=0.0))
        if rows:
            return rows, 'a1_scan.json (best_delta)'
    a2_path = _find_path(run_dir, 'a2_single_route_result.json')
    if a2_path is not None:
        payload = _read_json(a2_path)
        rows = []
        for record in (payload or {}).get('accepted') or ():
            if not isinstance(record, dict):
                continue
            delta = _to_float(record.get('delta'))
            try:
                rid = int(record.get('route_id'))
            except (TypeError, ValueError):
                continue
            if delta is None:
                continue
            rows.append(dict(
                route_id=rid, target_z=_to_float(record.get('to_z')),
                removed=max(0.0, -delta), added=max(0.0, delta), net=delta,
                strategy='a2_accepted', extra_length_mm=0.0))
        if rows:
            return rows, 'a2_single_route_result.json (accepted)'
    return [], None


def _experiment_a_changes(run_dir, baseline_routes):
    """``[(before, after)]`` real route pairs for experiment A."""
    baseline_by_id = _routes_by_id(baseline_routes)
    pairs = _a2_route_changes(run_dir)
    if pairs:
        return [(before if before is not None
                 else baseline_by_id.get(_route_id(after)), after)
                for before, after in pairs], 'a2_single_route_result.json'
    accepted_path = _find_path(run_dir, 'accepted_routes.json')
    if accepted_path is not None:
        records = _extract_route_records(_read_json(accepted_path))
        if records:
            return [(baseline_by_id.get(_route_id(record)), record)
                    for record in records], 'accepted_routes.json'
    routes_path = _find_path(run_dir, 'routes_l3d.json')
    if routes_path is not None:
        routes = _load_routes_file(routes_path) or []
        pairs = [(baseline_by_id.get(_route_id(route)), route)
                 for route in routes if _n_mid(route) > 0]
        if pairs:
            return pairs, 'routes_l3d.json (native routes)'
    return [], None


def _experiment_a_comparison_entries(run_dir):
    """Per-route before/after crossing rows for experiment A."""
    comparison_dir = _find_path(run_dir, 'route_comparison')
    if comparison_dir is not None:
        entries = _route_comparison_entries(comparison_dir)
        if entries:
            return entries, 'route_comparison/ (before/after crossings)'
    scan_path = _find_path(run_dir, 'a1_scan.json')
    if scan_path is not None:
        scan = _read_json(scan_path)
        entries = []
        for record in (scan or {}).get('routes_scanned') or ():
            if not isinstance(record, dict):
                continue
            delta = _to_float(_pick(record, ('best_delta', 'delta')))
            crossings = _to_float(record.get('crossings'))
            if delta is None or crossings is None:
                continue
            try:
                rid = int(_pick(record, ('route_id', 'id')))
            except (TypeError, ValueError):
                continue
            entries.append(dict(path=None, route_id=rid,
                                before=crossings,
                                after=crossings + delta))
        if entries:
            return entries, 'a1_scan.json (real route crossings + best delta)'
    return [], None


def plot_experiment_a_dashboard(run_dir, baseline_dir, out_dir, only=None):
    """Figures for experiment A (candidate scoring + before/after routes)."""
    started = time.time()
    run_dir = Path(run_dir)
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(N.E5_DIR)
    out_dir = Path(out_dir)
    manifest = _new_manifest('experiment_A', run_dir, out_dir)
    baseline_routes = load_routes(baseline_dir) or []
    baseline_by_id = _routes_by_id(baseline_routes)

    candidates, candidates_source = _experiment_a_candidates(run_dir)
    if candidates:
        manifest['data']['candidates_source'] = str(candidates_source)
        manifest['data']['candidate_count'] = len(candidates)
        _guarded(manifest, 'experiment_A_candidates',
                 _summary_figure, candidates,
                 out_dir / 'experiment_A_candidates.png', manifest,
                 'experiment_A_candidates',
                 'Experiment A candidate scoring (removed vs added crossings)')
    else:
        _skip(manifest, 'experiment_A_candidates',
              'no candidates.json / a1_scan.json / a2 accepted rows found')

    pairs, pairs_source = _experiment_a_changes(run_dir, baseline_routes)
    manifest['data']['route_changes_source'] = (str(pairs_source)
                                                if pairs_source else None)
    if pairs and baseline_routes:
        manifest['data']['route_change_count'] = len(pairs)
        drawn = 0
        for order, (before, after) in enumerate(pairs[:6]):
            rid = _route_id(after)
            path = out_dir / ('experiment_A_route_%04d_3d.png' % rid)
            result = _guarded_figure(
                manifest, 'experiment_A_route_%04d_3d' % rid,
                plot_route_3d, before, after, path,
                'Experiment A accepted route R%d (before grey dashed / '
                'after coloured by physical z)' % rid)
            drawn += 1 if result else 0
            mid_indices = [index for index, _part, tag
                           in transition_records(after) if tag == 'mid']
            if mid_indices and drawn <= 2:
                neighbours = _neighbour_routes(baseline_routes, after,
                                               limit=20)
                _guarded_figure(
                    manifest, 'experiment_A_route_%04d_zoom' % rid,
                    plot_transition_zoom, after, mid_indices, neighbours,
                    out_dir / ('experiment_A_route_%04d_zoom.png' % rid))
        first = pairs[0][1]
        rid = _route_id(first)
        _guarded_figure(
            manifest, 'experiment_A_route_%04d_2d' % rid,
            plot_route_2d_projections, first,
            out_dir / 'experiment_A_2d_projections',
            prefix='route%04d' % rid)
    elif pairs:
        _skip(manifest, 'experiment_A_route_3d',
              'baseline routes unavailable for the before/after comparison')
    else:
        _skip(manifest, 'experiment_A_route_3d',
              'no accepted route records with parts (a2 changes / '
              'accepted_routes.json / native routes_l3d.json)')

    entries, comparison_source = _experiment_a_comparison_entries(run_dir)
    if entries:
        manifest['data']['route_comparison_source'] = str(comparison_source)
        _guarded(manifest, 'experiment_A_route_comparison',
                 _route_comparison_figure, entries,
                 out_dir / 'experiment_A_route_comparison.png', manifest,
                 comparison_source)
    else:
        _skip(manifest, 'experiment_A_route_comparison',
              'no per-route before/after crossing data found')
    return _finish_manifest(manifest, out_dir, started)


# --------------------------------------------------------------------------- #
# experiment B dashboard
# --------------------------------------------------------------------------- #
def _experiment_b_candidates(run_dir, baseline_routes=None):
    """Candidate rows from any experiment-B artifact (tolerant parser)."""
    candidates_path = _find_path(run_dir, 'candidates.json')
    payload = _read_json(candidates_path) if candidates_path else None
    rows = _normalise_candidates(payload)
    if rows:
        return rows, str(candidates_path)
    if not isinstance(payload, dict):
        payload = None
    final_routes = load_routes(run_dir) or []
    final_by_id = _routes_by_id(final_routes)
    baseline_by_id = _routes_by_id(baseline_routes)

    def _extra_length(route_id):
        final = final_by_id.get(route_id)
        before = baseline_by_id.get(route_id)
        if final is None or before is None:
            return 0.0
        return _route_length(final) - _route_length(before)

    excursions = (payload or {}).get('excursions')
    if isinstance(excursions, list) and excursions:
        accepted = (payload or {}).get('accepted_routes') or []
        strategy = str((payload or {}).get('strategy') or 'experiment_B')
        rows = []
        for index, excursion in enumerate(excursions):
            if not isinstance(excursion, dict):
                continue
            try:
                rid = int(accepted[index])
            except (IndexError, TypeError, ValueError):
                continue
            delta = _to_float(excursion.get('delta')) or 0.0
            rows.append(dict(
                route_id=rid,
                target_z=_to_float(_pick(excursion, ('target_z',
                                                    'target_z_mm'))),
                removed=max(0.0, -delta), added=max(0.0, delta), net=delta,
                strategy=strategy,
                extra_length_mm=float(_extra_length(rid))))
        if rows:
            return rows, '%s (excursions + accepted_routes)' % (
                candidates_path or 'experiment_B/candidates.json')
    batch_path = _find_path(run_dir, 'batch_result.json')
    if batch_path is not None:
        batch = _read_json(batch_path)
        rows = []
        for record in (batch or {}).get('records') or ():
            if not isinstance(record, dict):
                continue
            details = record.get('excursion_details') or []
            if not details:
                continue
            try:
                rid = int(record.get('route_id'))
            except (TypeError, ValueError):
                continue
            deltas = [_to_float(detail.get('delta')) or 0.0
                      for detail in details if isinstance(detail, dict)]
            net = float(sum(deltas))
            removed = float(sum(max(0.0, -delta) for delta in deltas))
            added = float(sum(max(0.0, delta) for delta in deltas))
            target_z = None
            for detail in details:
                if isinstance(detail, dict) and detail.get('target_z') is not None:
                    target_z = _to_float(detail['target_z'])
                    break
            rows.append(dict(
                route_id=rid, target_z=target_z, removed=removed,
                added=added, net=net,
                strategy=str(record.get('strategy') or 'experiment_B'),
                extra_length_mm=float(_extra_length(rid))))
        if rows:
            return rows, str(batch_path)
    return [], None


def _experiment_b_strategy_figure(run_dir, out_path, manifest=None):
    """Bars of per-strategy final crossings for experiment B."""
    path = _find_path(run_dir, 'strategy_comparison.json')
    if path is None:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    strategies = [row for row in payload.get('strategies') or ()
                  if isinstance(row, dict)]
    if not strategies:
        return None
    names = [str(row.get('strategy') or '?') for row in strategies]
    finals = [_to_float(row.get('final_total')) or 0.0 for row in strategies]
    nets = [_to_float(row.get('net_crossings')) or 0.0 for row in strategies]
    applied = [_to_float(row.get('applied')) or 0.0 for row in strategies]
    excursions = [_to_float(row.get('excursions')) or 0.0
                  for row in strategies]
    baseline = _to_float(payload.get('baseline_total'))
    x = np.arange(len(names), dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    ax, ax2 = axes
    ax.bar(x, finals, 0.55, color='#1565c0', alpha=0.9,
           label='final total crossings')
    if baseline is not None:
        ax.axhline(baseline, color='#9e9e9e', linestyle='--', linewidth=1.1,
                   label='E5 baseline %s' % _fmt_count(baseline))
    for xi, value, count in zip(x, finals, applied):
        ax.text(xi, value + 0.3, '%s\n(%d applied)'
                % (_fmt_count(value), int(count)), fontsize=6.5,
                ha='center', va='bottom', color='#0d47a1')
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=7.0, rotation=20, ha='right')
    ax.set_ylabel('crossings on the board')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
    ax.set_title('Per-strategy final crossing total', fontsize=9.5)
    ax2.bar(x, nets, 0.55, color=[C_REMOVED if value < 0 else C_ADDED
                                  for value in nets], alpha=0.9)
    for xi, value, count in zip(x, nets, excursions):
        ax2.text(xi, value - 0.4 if value < 0 else value + 0.2,
                 '%s\n(%d exc.)' % ('%+.0f' % value, int(count)),
                 fontsize=6.5, ha='center',
                 va='top' if value < 0 else 'bottom', color='#212121')
    ax2.axhline(0.0, color='#616161', linewidth=0.6)
    _set_count_ylim(ax2, (nets,))
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, fontsize=7.0, rotation=20, ha='right')
    ax2.set_ylabel('net crossing change')
    ax2.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax2.set_title('Net crossing change per strategy (negative = improvement)',
                  fontsize=9.5)
    fig.suptitle('Experiment B strategy comparison (%d evaluated strategies)'
                 % len(strategies), fontsize=10.5)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _save_fig(fig, out_path, manifest,
                     name=Path(out_path).stem)


def plot_experiment_b_dashboard(run_dir, out_dir, baseline_dir=None, only=None):
    """Figures for experiment B (candidate intervals) into ``out_dir``."""
    started = time.time()
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(N.E5_DIR)
    manifest = _new_manifest('experiment_B', run_dir, out_dir)
    baseline_routes = load_routes(baseline_dir) or []
    baseline_by_id = _routes_by_id(baseline_routes)
    candidates, candidates_source = _experiment_b_candidates(run_dir,
                                                             baseline_routes)
    manifest['data'] = dict(candidates_source=str(candidates_source)
                            if candidates_source else None,
                            candidate_count=len(candidates),
                            baseline_dir=str(baseline_dir))
    if not candidates:
        _skip(manifest, 'experiment_B_summary',
              'no candidates found (candidates.json / batch_result.json)')
        return _finish_manifest(manifest, out_dir, started)
    _guarded_figure(manifest, 'experiment_B_summary',
                    plot_experiment_b_summary, candidates,
                    out_dir / 'experiment_B_summary.png')
    _guarded(manifest, 'experiment_B_strategy_comparison',
             _experiment_b_strategy_figure, run_dir,
             out_dir / 'experiment_B_strategy_comparison.png', manifest)

    final_routes = load_routes(run_dir) or []
    native_routes = [route for route in final_routes if _n_mid(route) > 0]
    manifest['data']['native_routes'] = [_route_id(route)
                                        for route in native_routes]
    if native_routes:
        for order, route in enumerate(native_routes[:3]):
            rid = _route_id(route)
            _guarded_figure(
                manifest, 'experiment_B_route_%04d_3d' % rid,
                plot_route_3d, baseline_by_id.get(rid), route,
                out_dir / ('experiment_B_route_%04d_3d.png' % rid),
                'Experiment B accepted route R%d (before grey dashed / '
                'after coloured by physical z)' % rid)
            mid_indices = [index for index, _part, tag
                           in transition_records(route) if tag == 'mid']
            if mid_indices and order < 2:
                neighbours = _neighbour_routes(baseline_routes, route,
                                               limit=20)
                _guarded_figure(
                    manifest, 'experiment_B_route_%04d_zoom' % rid,
                    plot_transition_zoom, route, mid_indices, neighbours,
                    out_dir / ('experiment_B_route_%04d_zoom.png' % rid))
        first = native_routes[0]
        rid = _route_id(first)
        _guarded_figure(
            manifest, 'experiment_B_route_%04d_2d' % rid,
            plot_route_2d_projections, first,
            out_dir / 'experiment_B_2d_projections',
            prefix='route%04d' % rid)
    return _finish_manifest(manifest, out_dir, started)


# --------------------------------------------------------------------------- #
# combined helper + baseline demo
# --------------------------------------------------------------------------- #
def _summary_figure(candidates, out_path, manifest=None, name=None,
                    title=None):
    path = Path(out_path)
    rows = _normalise_candidates(candidates)
    if not rows:
        _log(None, 'summary: no candidates with numbers', level='warn')
        return None
    fig = _build_summary_figure(rows, total=len(rows))
    if fig is None:
        return None
    fig.suptitle(title or 'Crossing changes of the evaluated candidates',
                 fontsize=11.0)
    return _save_fig(fig, path, manifest, name=name or path.stem)


def _build_summary_figure(rows, total=None):
    """Redraw the experiment-B summary from already normalised candidate rows."""
    rows = list(rows or ())
    if not rows:
        return None
    rows.sort(key=lambda row: (-row['net'], -row['removed'],
                               row['route_id'] if row['route_id'] is not None
                               else 0))
    total = total if total is not None else len(rows)
    if total > 30:
        rows = rows[:30]
    labels = []
    for row in rows:
        label = 'R%s' % (row['route_id'] if row['route_id'] is not None
                         else '?')
        if row['target_z'] is not None:
            label += '\n%s' % _height_text(row['target_z'])
        labels.append(label)
    x = np.arange(len(rows), dtype=float)
    removed = np.array([row['removed'] for row in rows], dtype=float)
    added = np.array([row['added'] for row in rows], dtype=float)
    net = np.array([row['net'] for row in rows], dtype=float)
    strategy_totals = OrderedDict()
    for row in rows:
        bucket = strategy_totals.setdefault(
            row['strategy'], dict(removed=0.0, added=0.0, count=0, net=0.0))
        bucket['removed'] += row['removed']
        bucket['added'] += row['added']
        bucket['net'] += row['net']
        bucket['count'] += 1
    strategies = sorted(strategy_totals,
                        key=lambda name: (-strategy_totals[name]['net'], name))
    fig = plt.figure(figsize=(16.0, 7.6))
    ax = fig.add_axes([0.05, 0.30, 0.55, 0.62])
    ax2 = fig.add_axes([0.68, 0.30, 0.29, 0.62])
    width = 0.38
    ax.bar(x - width / 2.0, removed, width, color=C_REMOVED,
           label='removed crossings', alpha=0.9)
    ax.bar(x + width / 2.0, added, width, color=C_ADDED,
           label='added crossings', alpha=0.9)
    ax.plot(x, net, color=C_NET, marker='o', markersize=4.5, linewidth=1.4,
            label='net = removed - added')
    for xi, net_value in zip(x, net):
        ax.text(xi, net_value + 0.15, '%+.0f' % net_value, fontsize=6.0,
                ha='center', va='bottom', color=C_NET)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.0, rotation=90)
    ax.set_ylabel('crossings')
    _set_count_ylim(ax, (removed, added, net))
    ax.axhline(0.0, color='#616161', linewidth=0.6)
    ax.grid(True, axis='y', linewidth=0.25, color='#dddddd')
    ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
    ax.set_title('Candidates: removed vs added crossings'
                 + (' (top 30 of %d by net reduction)' % total
                    if total > 30 else ''), fontsize=10.0)
    sx = np.arange(len(strategies), dtype=float)
    s_removed = np.array([strategy_totals[name]['removed']
                          for name in strategies], dtype=float)
    s_added = np.array([strategy_totals[name]['added']
                        for name in strategies], dtype=float)
    s_net = np.array([strategy_totals[name]['net']
                      for name in strategies], dtype=float)
    ax2.bar(sx - width / 2.0, s_removed, width, color=C_REMOVED, alpha=0.9,
            label='removed')
    ax2.bar(sx + width / 2.0, s_added, width, color=C_ADDED, alpha=0.9,
            label='added')
    ax2.plot(sx, s_net, color=C_NET, marker='o', markersize=4.5,
             linewidth=1.4, label='net')
    for xi, net_value, name in zip(sx, s_net, strategies):
        ax2.text(xi, net_value + 0.15, '%+.0f\n(%d cand.)'
                 % (net_value, strategy_totals[name]['count']), fontsize=6.0,
                 ha='center', va='bottom', color=C_NET)
    ax2.set_xticks(sx)
    ax2.set_xticklabels([str(name) for name in strategies], fontsize=6.5,
                        rotation=30, ha='right')
    ax2.set_ylabel('crossings')
    _set_count_ylim(ax2, (s_removed, s_added, s_net))
    ax2.axhline(0.0, color='#616161', linewidth=0.6)
    ax2.grid(True, axis='y', linewidth=0.25, color='#dddddd')
    ax2.legend(loc='upper right', fontsize=7.0, framealpha=0.9)
    ax2.set_title('aggregated per strategy', fontsize=9.0)
    fig.suptitle('Crossing changes of the evaluated candidates', fontsize=11.0)
    return fig


def plot_baseline_demo(baseline_dir=None, out_dir=None, only=None):
    """Plot the frozen E5 baseline only (21 height panels + 3D + hotspot)."""
    started = time.time()
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(N.E5_DIR)
    out_dir = Path(out_dir) if out_dir else (
        Path(N.RUN_DIR) / 'scratch' / 'native_viz' / 'baseline_demo')
    manifest = _new_manifest('baseline_E5_demo', baseline_dir, out_dir)
    routes = load_routes(baseline_dir)
    stats = load_crossing_stats(baseline_dir)
    if not routes:
        _skip(manifest, 'all', 'no routes_l3d.json in %s' % baseline_dir)
        return _finish_manifest(manifest, out_dir, started)
    manifest['data'] = dict(
        baseline_dir=str(baseline_dir),
        routes_file=str(_find_path(baseline_dir, 'routes_l3d.json')),
        crossing_stats_file=str(_find_path(baseline_dir,
                                           'crossing_stats.json')),
        route_count=len(routes),
        crossing_events_total=len((stats or {}).get('crossing_events') or ()),
    )
    _log(manifest, 'baseline demo: %d routes, %d crossing events'
         % (len(routes), manifest['data']['crossing_events_total']))
    _guarded(manifest, 'height_panels', plot_height_panels, routes, stats,
             out_dir, manifest, only, 'baseline_height')
    _guarded(manifest, '3d_overview', _overview_3d_baseline, routes, out_dir,
             manifest, only)
    _guarded(manifest, 'crossing_hotspot', _dashboard_hotspot, stats, out_dir,
             manifest, only)
    _guarded(manifest, 'per_layer_baseline', _baseline_per_layer, stats,
             out_dir, manifest, only)
    _guarded(manifest, 'route_height_profile_examples',
             _dashboard_height_profiles, routes, stats, out_dir, manifest,
             only)
    return _finish_manifest(manifest, out_dir, started)


def _overview_3d_baseline(routes, out_dir, manifest, only=None):
    """3D overview for the baseline demo (same real geometry as experiment C)."""
    return _overview_3d(routes, out_dir, manifest, only)


def _baseline_per_layer(stats, out_dir, manifest, only=None):
    if not _wanted(only, 'per_layer_baseline'):
        return None
    if stats is None:
        _skip(manifest, 'per_layer_baseline', 'crossing_stats.json missing')
        return None
    rows = _plane_rows(stats)
    labels, zs, counts = [], [], []
    for pid, z, label, _kind in HEIGHT_ROWS:
        labels.append(label)
        zs.append(z)
        row = rows.get(pid) or {}
        counts.append(_to_float(row.get('crossings')) or 0.0)
    fig, ax = plt.subplots(figsize=(13.5, 6.2))
    x = np.arange(len(labels), dtype=float)
    colours = [CMAP(NORM(z)) for z in zs]
    ax.bar(x, counts, 0.72, color=colours, alpha=0.9)
    for xi, value in zip(x, counts):
        if value:
            ax.text(xi, value + 1.0, '%d' % int(value), fontsize=6.0,
                    ha='center', va='bottom', color='#424242')
    ax.set_xticks(x)
    ax.set_xticklabels(['%s\n%+.2f' % (label, z)
                        for label, z in zip(labels, zs)], fontsize=6.5,
                       rotation=60, ha='right')
    ax.set_ylabel('crossing events on the height')
    ax.grid(True, axis='y', linewidth=0.3, color='#e0e0e0')
    ax.set_title('Frozen E5 baseline: crossing events per physical height '
                 '(total %d)' % int(sum(counts)), fontsize=10.5)
    return _save_fig(fig, Path(out_dir) / 'baseline_per_layer_crossings.png',
                     manifest, name='baseline_per_layer_crossings')


def plot_all_experiments(run_root, baseline_dir=None, out_root=None,
                         only=None):
    """Auto-detect and plot experiments A / B / C under ``run_root``."""
    run_root = Path(run_root)
    baseline_dir = Path(baseline_dir) if baseline_dir else Path(N.E5_DIR)
    out_root = Path(out_root) if out_root else run_root / 'plots'
    results = {}
    c_dir = run_root / 'experiment_C'
    if (c_dir / 'routes_l3d.json').exists() or (
            run_root / 'routes_l3d.json').exists():
        target = c_dir if (c_dir / 'routes_l3d.json').exists() else run_root
        results['C'] = plot_experiment_c_dashboard(
            target, out_root / 'experiment_C', baseline_dir, only=only)
    else:
        print('[native3d.viz] warn: experiment C routes_l3d.json missing '
              '(neither %s nor %s); skipping C figures'
              % (c_dir / 'routes_l3d.json', run_root / 'routes_l3d.json'),
              flush=True)
    a_dir = run_root / 'experiment_A'
    if a_dir.exists():
        results['A'] = plot_experiment_a_dashboard(
            a_dir, baseline_dir, out_root / 'experiment_A', only=only)
    else:
        print('[native3d.viz] warn: %s missing; skipping A figures' % a_dir,
              flush=True)
    b_dir = run_root / 'experiment_B'
    if b_dir.exists():
        results['B'] = plot_experiment_b_dashboard(
            b_dir, out_root / 'experiment_B', baseline_dir, only=only)
    else:
        print('[native3d.viz] warn: %s missing; skipping B figures' % b_dir,
              flush=True)
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser():
    parser = argparse.ArgumentParser(
        prog='python -m four_side_1024.fanout1024.native3d.visualize',
        description='Real-geometry figures for the Native 3D experiment '
                    '(21-height multi-body routes, R15 S-curves, real '
                    'crossing records).')
    parser.add_argument('--run-dir', type=Path, default=None,
                        help='native 3D run dir (or experiment root) holding '
                             'routes_l3d.json / crossing_stats.json')
    parser.add_argument('--baseline-dir', type=Path, default=None,
                        help='frozen E5 baseline dir (default: %s)'
                             % N.E5_DIR)
    parser.add_argument('--out-dir', type=Path, default=None,
                        help='figure output directory')
    parser.add_argument('--demo-baseline', action='store_true',
                        help='plot the frozen E5 baseline only '
                             '(21 height panels + 3D + hotspot)')
    parser.add_argument('--all-experiments', action='store_true',
                        help='also plot experiment A / B when their files '
                             'exist under the run root')
    parser.add_argument('--only', type=str, default=None,
                        help='comma separated figure groups to generate, e.g. '
                             'height_panels,3d_overview,crossing_hotspot')
    parser.add_argument('--quiet', action='store_true',
                        help='suppress per-figure logging')
    return parser


def main(argv=None):
    """CLI entry point.  Returns a process exit code (0 on success)."""
    global _QUIET
    args = _build_parser().parse_args(argv)
    _QUIET = bool(args.quiet)
    started = time.time()
    baseline_dir = Path(args.baseline_dir) if args.baseline_dir else Path(
        N.E5_DIR)
    only = _parse_only(args.only)

    if args.demo_baseline:
        out_dir = Path(args.out_dir) if args.out_dir else (
            Path(N.RUN_DIR) / 'scratch' / 'native_viz' / 'baseline_demo')
        manifest = plot_baseline_demo(baseline_dir, out_dir, only=only)
        print('[native3d.viz] baseline demo: %d figures in %.1fs -> %s'
              % (manifest['figure_count'], manifest['runtime_seconds'],
                 out_dir), flush=True)
        return 0

    run_dir = Path(args.run_dir) if args.run_dir else Path(N.RUN_DIR)
    if not run_dir.exists():
        print('[native3d.viz] run dir does not exist: %s' % run_dir,
              flush=True)
        return 0
    if args.out_dir is not None:
        out_dir = Path(args.out_dir)
    elif run_dir.name.startswith('experiment_'):
        out_dir = run_dir.parent / 'plots'
    else:
        out_dir = run_dir / 'plots'

    if args.all_experiments:
        results = plot_all_experiments(run_dir, baseline_dir, out_dir,
                                       only=only)
        total = sum(len(manifest['figures'])
                    for manifest in results.values())
        elapsed = time.time() - started
        print('[native3d.viz] all experiments: %d figures in %.1fs'
              % (total, elapsed), flush=True)
        return 0

    c_dir = run_dir
    if not (c_dir / 'routes_l3d.json').exists() and (
            run_dir / 'experiment_C' / 'routes_l3d.json').exists():
        c_dir = run_dir / 'experiment_C'
    if not (c_dir / 'routes_l3d.json').exists() and not (
            run_dir / 'routes_l3d.json').exists():
        print('[native3d.viz] no routes_l3d.json under %s; nothing to plot'
              % run_dir, flush=True)
        return 0
    manifest = plot_experiment_c_dashboard(c_dir, out_dir, baseline_dir,
                                           only=only)
    print('[native3d.viz] experiment C dashboard: %d figures in %.1fs -> %s'
          % (manifest['figure_count'], manifest['runtime_seconds'], out_dir),
          flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
