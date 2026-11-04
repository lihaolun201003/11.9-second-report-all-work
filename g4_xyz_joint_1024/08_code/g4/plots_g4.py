# -*- coding: utf-8 -*-
"""G4-5 visualisation: per-physical-height XY plots + comparison / migration /
modification / budget figures.

Every figure is drawn from the **accepted** ``routes_l3d.json`` of one layout:

* flat parts -> their real stored primitives (``line`` / exact R15 ``arc``),
  sampled with :func:`four_side_1024.fsd25d.path3d.path_polyline`;
* transition parts -> the exact stored R15 S-curve, sampled with
  :func:`...path3d.transition_samples` and projected on XY (footprint);
* crossing markers -> ``crossing_stats.json`` ``crossing_events`` whose
  ``z_mm`` matches the physical height **exactly** (rounded to 1e-6 mm).

Nothing is interpolated or invented.  A route/part that cannot be sampled is
counted as a sampling failure and simply does not appear.

Public API
----------
``plot_layer_suite(run_dir, out_dir, prefix, title)``
    21 independent per-height XY figures + 21-panel overview montage +
    per-height statistics (JSON/CSV/Markdown) + manifest.
``plot_compare_suite(before_dir, after_dir, out_dir, prefix)``
    per-height before/after comparison figures, per-height crossing bars,
    comparison tables.
``plot_migration(before_dir, after_dir, out_dir, changes_json=None)``
    original manual-U group -> new geometric family migration matrix.
``plot_modifications(before_dir, after_dir, out_dir)``
    XY / Z modification statistics of all routes.
``plot_budget_curves(arms, out_dir)``
    crossings vs route_3d_checks / wall time from ``optimization_history.csv``
    and budget bars from ``budget_ledger.json``.

CLI
---
::

    python -m four_side_1024.fanout1024.xyzrouter.g4.plots_g4 layer-suite \
        --run-dir <layout dir> --out-dir experiments/.../09_plots/G3_baseline \
        --prefix G3_baseline --title "G3 baseline"
    python -m ...g4.plots_g4 compare-suite --before <g3> --after <g4> --out-dir ...
    python -m ...g4.plots_g4 migration --before <g3> --after <g4> --out-dir ...
    python -m ...g4.plots_g4 modifications --before <g3> --after <g4> --out-dir ...
    python -m ...g4.plots_g4 budget --out-dir ...
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.reheight21 import model as M  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import visualize as V  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402
from four_side_1024.fsd25d import path3d as P3  # noqa: E402

SCHEMA = 'g4_plots_v1'
BOARD_MM = 150.0
GRID_N = 10
GRID_MM = BOARD_MM / GRID_N
DEFAULT_DPI = 140
MONTAGE_DPI = 105

HEIGHT_ROWS = V.HEIGHT_ROWS
HEIGHT_KEYS = list(V.HEIGHT_KEYS)
HEIGHT_BY_Z = V.HEIGHT_BY_Z

COLORS = dict(
    manual_line='#d32f2f',
    manual_arc='#ff6f00',
    plain_line='#1565c0',
    plain_arc='#00838f',
    transition='#6a1b9a',
    cross='#e53935',
    board='#37474f',
    grid='#eceff1',
    congested='#ffcdd2',
    before='#9e9e9e',
    after='#00897b',
    accent='#c62828',
)

plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'savefig.facecolor': 'white',
    'font.size': 8.5,
    'axes.titlesize': 9.5,
    'axes.labelsize': 7.6,
    'xtick.labelsize': 6.6,
    'ytick.labelsize': 6.6,
    'legend.fontsize': 7.0,
    'axes.grid': False,
    'axes.linewidth': 0.5,
    'axes.unicode_minus': False,
})


# --------------------------------------------------------------------------- #
# tiny IO helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


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


def _rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _save_figure(fig, path, dpi=DEFAULT_DPI):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor='white')
    plt.close(fig)
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError('figure was not written: %s' % path)
    return dict(path=_rel(path), bytes=path.stat().st_size)


def _file_meta(path):
    path = Path(path)
    if not path.exists():
        return None
    return dict(path=_rel(path), bytes=path.stat().st_size,
                sha256=GP.sha256_file(path))


# --------------------------------------------------------------------------- #
# geometry helpers (reuse the real samplers of visualize / path3d)
# --------------------------------------------------------------------------- #
def _prim_xy(prim):
    """Exact 2-D polyline of one stored primitive (line or R15 arc)."""
    kind = str(prim.get('kind') or '')
    step = 0.8 if kind == 'arc' else 2.0
    try:
        points = P3.path_polyline([prim], step=step)
    except Exception:  # noqa: BLE001 - undrawable primitive
        return None
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] != 2:
        return None
    if not np.isfinite(array).all():
        return None
    return array


def _cell_of(x_mm, y_mm):
    col = int(math.floor(max(0.0, min(BOARD_MM - 1e-9, float(x_mm))) / GRID_MM))
    row = int(math.floor(max(0.0, min(BOARD_MM - 1e-9, float(y_mm))) / GRID_MM))
    return (min(col, GRID_N - 1), min(row, GRID_N - 1))


def _polyline_cells(xy):
    """Grid blocks (col, row) covered by a sampled 2-D polyline."""
    cells = set()
    if xy is None or len(xy) == 0:
        return cells
    for x, y in xy:
        cells.add(_cell_of(x, y))
    return cells


def _xy_signature(route):
    """Fingerprint of the *XY* geometry only (physical z ignored)."""
    out = []
    for part in V._parts(route):
        kind = part.get('kind')
        if kind == 'flat':
            for prim in part.get('primitives') or ():
                pk = prim.get('kind')
                if pk == 'line':
                    out.append(('line',
                                tuple(round(float(v), 6) for v in prim.get('p0') or ()),
                                tuple(round(float(v), 6) for v in prim.get('p1') or ())))
                elif pk == 'arc':
                    out.append(('arc',
                                tuple(round(float(v), 6) for v in prim.get('p0') or ()),
                                tuple(round(float(v), 6) for v in prim.get('p1') or ()),
                                tuple(round(float(v), 6) for v in prim.get('center') or ()),
                                round(float(prim.get('radius')), 6),
                                round(float(prim.get('start_angle')), 9),
                                round(float(prim.get('sweep')), 9)))
        elif kind == 'transition':
            out.append(('transition',
                        tuple(round(float(v), 6) for v in part.get('start') or ()),
                        tuple(round(float(v), 6) for v in part.get('direction') or ())))
    return tuple(out)


# --------------------------------------------------------------------------- #
# one layout (accepted route set) + per-height geometry buckets
# --------------------------------------------------------------------------- #
class Layout:
    """Accepted layout of one run directory with per-height real geometry."""

    def __init__(self, run_dir, name=None, step_flat=2.0, step_transition=0.35):
        self.dir = Path(run_dir)
        self.name = name or self.dir.name
        self.routes = V.load_routes(self.dir) or []
        if not self.routes:
            raise FileNotFoundError(
                'no drawable routes_l3d.json under %s' % self.dir)
        self.stats = V.load_crossing_stats(self.dir) or {}
        self.assignment = V.load_assignment(self.dir)
        self.geometry = V.RouteGeometry(self.routes, step_flat=step_flat,
                                        step_transition=step_transition)
        self.by_id = self.geometry.by_id
        self.manual_group = dict(self.geometry.manual_group)
        self.primary_z = dict(self.geometry.primary_z)
        self.manual = dict(self.geometry.manual)

        self.events = [event for event in
                       (self.stats.get('crossing_events') or ())
                       if isinstance(event, dict)]
        self.events_by_key = defaultdict(list)
        for event in self.events:
            z = V._to_float(event.get('z_mm'))
            if z is None:
                continue
            self.events_by_key[round(z, 6)].append(event)
        self.per_route = V._per_route_counts(self.stats)
        self.stats_planes = OrderedDict()
        for row in self.stats.get('planes') or ():
            if not isinstance(row, dict):
                continue
            z = V._to_float(row.get('z_mm'))
            if z is not None:
                self.stats_planes[round(z, 6)] = row

        self.layer_prims = defaultdict(list)
        self.layer_trans = defaultdict(list)
        self.route_flat_keys = defaultdict(set)
        self.route_trans = defaultdict(list)
        self.sampling_failures = 0
        self._build_details()

    # -- real geometry per height ------------------------------------------
    def _build_details(self):
        for rid, route in self.by_id.items():
            group = self.manual_group.get(rid) or ''
            manual = bool(group)
            parts = V._parts(route)
            trans_positions = [index for index, part in enumerate(parts)
                               if part.get('kind') == 'transition']
            n_trans = len(trans_positions)
            for order, index in enumerate(trans_positions):
                part = parts[index]
                z0 = V._to_float(part.get('z0'))
                z1 = V._to_float(part.get('z1'))
                is_mid = 0 < order < n_trans - 1
                self.route_trans[rid].append(dict(
                    z0=z0, z1=z1, mid=bool(is_mid), index=index))
                xyz = V.sample_transition_xyz(part, 0.35)
                if xyz is None:
                    self.sampling_failures += 1
                    continue
                xy = xyz[:, :2]
                for z in (z0, z1):
                    if z is None:
                        continue
                    self.layer_trans[round(z, 6)].append(dict(
                        route_id=rid, xy=xy, manual=manual, group=group,
                        mid=bool(is_mid), other_z=(z1 if z == z0 else z0)))
            for part in parts:
                if part.get('kind') != 'flat':
                    continue
                z = V._to_float(part.get('z_mm'))
                prims = part.get('primitives') or ()
                if z is None:
                    self.sampling_failures += 1
                    continue
                key = round(z, 6)
                self.route_flat_keys[rid].add(key)
                for prim in prims:
                    kind = str(prim.get('kind') or '')
                    if kind not in ('line', 'arc'):
                        self.sampling_failures += 1
                        continue
                    xy = _prim_xy(prim)
                    if xy is None:
                        self.sampling_failures += 1
                        continue
                    self.layer_prims[key].append(dict(
                        route_id=rid, kind=kind, xy=xy, manual=manual,
                        group=group))

    # -- derived ------------------------------------------------------------
    def route_ids(self):
        return sorted(self.by_id)

    def manual_route_ids(self):
        return sorted(rid for rid in self.by_id if self.manual.get(rid))

    def height_label(self, z_mm):
        return V._height_info(z_mm)['label']

    def crossing_total(self):
        return V.crossing_total(self.stats)


# --------------------------------------------------------------------------- #
# per-height statistics (all from the accepted real geometry)
# --------------------------------------------------------------------------- #
def layer_stats(layout, key):
    """Statistics of one physical height, from the accepted layout."""
    info = HEIGHT_BY_Z[key]
    prims = layout.layer_prims.get(key, ())
    body_ids = sorted({entry['route_id'] for entry in prims})
    manual_ids = [rid for rid in body_ids if layout.manual.get(rid)]
    groups = sorted({layout.manual_group.get(rid) or '' for rid in body_ids
                     if layout.manual_group.get(rid)})
    events = layout.events_by_key.get(key, ())
    pairs = set()
    layer_counts = Counter()
    for event in events:
        try:
            route_a = int(event.get('route_a'))
            route_b = int(event.get('route_b'))
        except (TypeError, ValueError):
            continue
        pairs.add((min(route_a, route_b), max(route_a, route_b)))
        layer_counts[route_a] += 1
        layer_counts[route_b] += 1
    per_route = [layer_counts.get(rid, 0) for rid in body_ids]
    average = (sum(per_route) / float(len(per_route))) if per_route else 0.0
    maximum = max(per_route) if per_route else 0

    mid_route_ids = set()
    mid_events = 0
    for entry in layout.layer_trans.get(key, ()):
        if entry.get('mid'):
            mid_events += 1
            mid_route_ids.add(entry['route_id'])
    mid_route_ids &= set(body_ids)

    covered = set()
    for entry in prims:
        covered |= _polyline_cells(entry['xy'])
    covered_flat = len(covered)
    for entry in layout.layer_trans.get(key, ()):
        covered |= _polyline_cells(entry['xy'])
    covered_all = len(covered)
    idle_blocks = GRID_N * GRID_N - covered_all

    congested = Counter()
    for event in events:
        x = V._to_float(event.get('x_mm'))
        y = V._to_float(event.get('y_mm'))
        if x is None or y is None:
            continue
        congested[_cell_of(x, y)] += 1
    congested_blocks = sum(1 for count in congested.values() if count >= 2)
    max_block = max(congested.values()) if congested else 0
    hotspots = []
    for (col, row), count in sorted(congested.items(),
                                    key=lambda item: (-item[1], item[0]))[:3]:
        in_cell = [(V._to_float(event.get('x_mm')),
                    V._to_float(event.get('y_mm')))
                   for event in events
                   if _cell_of(V._to_float(event.get('x_mm')) or 0.0,
                               V._to_float(event.get('y_mm')) or 0.0)
                   == (col, row)]
        in_cell = [(x, y) for x, y in in_cell if x is not None and y is not None]
        hotspots.append(dict(
            cell=[col, row], count=count,
            x_mm=round(sum(point[0] for point in in_cell) / max(1, len(in_cell)), 3),
            y_mm=round(sum(point[1] for point in in_cell) / max(1, len(in_cell)), 3),
            x_range_mm=[col * GRID_MM, (col + 1) * GRID_MM],
            y_range_mm=[row * GRID_MM, (row + 1) * GRID_MM]))

    stats_plane = layout.stats_planes.get(key) or {}
    stats_plane_crossings = stats_plane.get('crossings')
    stats_plane_routes = stats_plane.get('routes')
    crossings_match = (stats_plane_crossings is not None
                       and int(stats_plane_crossings) == len(events))

    n_line = sum(1 for entry in prims if entry['kind'] == 'line')
    n_arc = sum(1 for entry in prims if entry['kind'] == 'arc')
    flat_parts = set()
    for entry in prims:
        flat_parts.add((entry['route_id'], entry['kind']))
    return dict(
        layer_index=HEIGHT_KEYS.index(key) + 1,
        plane_id=info['plane_id'], label=info['label'],
        z_mm=round(float(info['z_mm']), 6),
        kind=info['kind'], role=info['role'],
        manual_group_fixed=info['manual_group'],
        body_routes=len(body_ids),
        manual_routes=len(manual_ids),
        manual_groups=groups,
        group_count=len(groups),
        crossings=len(events),
        crossing_pairs=len(pairs),
        crossings_avg_per_route=round(average, 3),
        crossings_max_per_route=maximum,
        routes_with_crossings=sum(1 for value in per_route if value > 0),
        mid_transition_routes=len(mid_route_ids),
        mid_transition_events=mid_events,
        covered_blocks_flat=covered_flat,
        covered_blocks_all=covered_all,
        idle_blocks=idle_blocks,
        congested_blocks=congested_blocks,
        max_block_crossings=max_block,
        hotspots=hotspots,
        line_prims=n_line,
        arc_prims=n_arc,
        transition_prims_touching=len(layout.layer_trans.get(key, ())),
        stats_plane_routes=(int(stats_plane_routes)
                            if stats_plane_routes is not None else None),
        stats_plane_crossings=(int(stats_plane_crossings)
                               if stats_plane_crossings is not None else None),
        crossings_match_planes=bool(crossings_match),
    )


def all_layer_stats(layout):
    return [layer_stats(layout, key) for key in HEIGHT_KEYS]


def layout_statistics(layout):
    """Global statistics + per-height rows of one accepted layout."""
    rows = all_layer_stats(layout)
    manual_ids = layout.manual_route_ids()
    tot = dict(
        name=layout.name,
        dir=_rel(layout.dir),
        routes=len(layout.by_id),
        manual_routes=len(manual_ids),
        manual_groups=len({layout.manual_group.get(rid)
                           for rid in manual_ids
                           if layout.manual_group.get(rid)}),
        crossing_total=sum(row['crossings'] for row in rows),
        crossing_total_stats_file=(layout.crossing_total()
                                   if layout.crossing_total() is not None
                                   else None),
        crossing_pairs=sum(row['crossing_pairs'] for row in rows),
        routes_with_crossings=len(set(layout.per_route)),
        sampling_failures=layout.sampling_failures,
        heights=len(rows),
        layers_with_crossings=sum(1 for row in rows if row['crossings']),
        body_routes_max=max(row['body_routes'] for row in rows),
        body_routes_min=min(row['body_routes'] for row in rows),
        total_flat_line_prims=sum(row['line_prims'] for row in rows),
        total_arc_prims=sum(row['arc_prims'] for row in rows),
        total_mid_transition_events=sum(row['mid_transition_events']
                                        for row in rows),
        per_height=rows,
        routes_sha256=(GP.sha256_file(layout.dir / 'routes_l3d.json')
                       if (layout.dir / 'routes_l3d.json').exists() else None),
        crossing_stats_sha256=(
            GP.sha256_file(layout.dir / 'crossing_stats.json')
            if (layout.dir / 'crossing_stats.json').exists() else None),
        generated_at=_now(),
    )
    return tot


# --------------------------------------------------------------------------- #
# drawing: one physical height
# --------------------------------------------------------------------------- #
def _layer_legend_handles(layout, key):
    prims = layout.layer_prims.get(key, ())
    events = layout.events_by_key.get(key, ())
    trans = layout.layer_trans.get(key, ())
    n = lambda pred: sum(1 for entry in prims if pred(entry))
    handles = [
        Line2D([0], [0], color=COLORS['plain_line'], lw=1.1,
               label='non-manual flat line (%d)' % n(
                   lambda e: e['kind'] == 'line' and not e['manual'])),
        Line2D([0], [0], color=COLORS['manual_line'], lw=1.1,
               label='manual-U flat line (%d)' % n(
                   lambda e: e['kind'] == 'line' and e['manual'])),
        Line2D([0], [0], color=COLORS['plain_arc'], lw=2.0,
               label='non-manual R15 arc (%d)' % n(
                   lambda e: e['kind'] == 'arc' and not e['manual'])),
        Line2D([0], [0], color=COLORS['manual_arc'], lw=2.0,
               label='manual-U R15 arc (%d)' % n(
                   lambda e: e['kind'] == 'arc' and e['manual'])),
        Line2D([0], [0], color=COLORS['transition'], lw=1.0,
               linestyle=(0, (3, 2.5)),
               label='3-D transition footprint, projected (%d)' % len(trans)),
        Line2D([0], [0], marker='x', color=COLORS['cross'], ls='none',
               markersize=6.0, markeredgewidth=1.0,
               label='real crossing point, z exact (%d)' % len(events)),
        Patch(facecolor=COLORS['congested'], edgecolor='#c62828',
              alpha=0.55, label='congested block (>=2 crossings / %d mm)'
                               % GRID_MM),
    ]
    return handles


def _draw_layer_board(ax, layout, key, crossing_size=26.0, line_lw=0.5,
                      arc_lw=1.2, transition_alpha=0.45,
                      show_transitions=True, show_grid=True,
                      show_crossings=True, show_congestion=True,
                      show_hotspots=False, title=None, fontsize_title=10.0):
    """Draw the real XY geometry of one physical height on ``ax``."""
    ax.add_patch(Rectangle((0.0, 0.0), BOARD_MM, BOARD_MM, fill=False,
                           edgecolor=COLORS['board'], linewidth=0.85,
                           zorder=0))
    if show_grid:
        for index in range(1, GRID_N):
            value = index * GRID_MM
            ax.plot([value, value], [0.0, BOARD_MM], color=COLORS['grid'],
                    linewidth=0.4, zorder=0)
            ax.plot([0.0, BOARD_MM], [value, value], color=COLORS['grid'],
                    linewidth=0.4, zorder=0)
    prims = layout.layer_prims.get(key, ())
    buckets = OrderedDict([
        ('plain_line', [entry['xy'] for entry in prims
                        if entry['kind'] == 'line' and not entry['manual']]),
        ('manual_line', [entry['xy'] for entry in prims
                         if entry['kind'] == 'line' and entry['manual']]),
        ('plain_arc', [entry['xy'] for entry in prims
                       if entry['kind'] == 'arc' and not entry['manual']]),
        ('manual_arc', [entry['xy'] for entry in prims
                        if entry['kind'] == 'arc' and entry['manual']]),
    ])
    style = OrderedDict([
        ('plain_line', dict(colors=COLORS['plain_line'], linewidths=line_lw,
                            alpha=0.80, zorder=3)),
        ('manual_line', dict(colors=COLORS['manual_line'], linewidths=line_lw,
                             alpha=0.90, zorder=4)),
        ('plain_arc', dict(colors=COLORS['plain_arc'], linewidths=arc_lw,
                           alpha=0.95, zorder=3)),
        ('manual_arc', dict(colors=COLORS['manual_arc'], linewidths=arc_lw,
                            alpha=0.98, zorder=5)),
    ])
    for name, arrays in buckets.items():
        if not arrays:
            continue
        ax.add_collection(LineCollection(arrays, **style[name]))
    if show_transitions:
        trans = layout.layer_trans.get(key, ())
        if trans:
            ax.add_collection(LineCollection(
                [entry['xy'] for entry in trans],
                colors=COLORS['transition'], linewidths=0.55,
                alpha=transition_alpha, linestyles=(0, (2.5, 2.0)), zorder=1))
    if show_congestion:
        congested = Counter()
        for event in layout.events_by_key.get(key, ()):
            x = V._to_float(event.get('x_mm'))
            y = V._to_float(event.get('y_mm'))
            if x is None or y is None:
                continue
            congested[_cell_of(x, y)] += 1
        for (col, row), count in congested.items():
            if count < 2:
                continue
            ax.add_patch(Rectangle(
                (col * GRID_MM, row * GRID_MM), GRID_MM, GRID_MM,
                facecolor=COLORS['congested'],
                alpha=min(0.55, 0.18 + 0.07 * count), edgecolor='#c62828',
                linewidth=0.35, linestyle=(0, (2, 2)), zorder=1))
    if show_crossings:
        events = layout.events_by_key.get(key, ())
        points = []
        for event in events:
            x = V._to_float(event.get('x_mm'))
            y = V._to_float(event.get('y_mm'))
            if x is not None and y is not None:
                points.append((x, y))
        if points:
            array = np.asarray(points, dtype=float)
            ax.scatter(array[:, 0], array[:, 1], marker='x',
                       s=crossing_size, c=COLORS['cross'], linewidths=0.9,
                       alpha=0.95, zorder=10)
    if show_hotspots:
        for event in layout.events_by_key.get(key, ())[:0]:
            pass
    ax.set_xlim(-1.5, BOARD_MM + 1.5)
    ax.set_ylim(-1.5, BOARD_MM + 1.5)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.tick_params(labelsize=6.4)
    if title:
        ax.set_title(title, fontsize=fontsize_title, pad=6.0)
    return ax


def _info_text_block(layout, key, stats):
    info = HEIGHT_BY_Z[key]
    events = layout.events_by_key.get(key, ())
    lines = []
    lines.append('%s   z = %+.2f mm' % (info['label'], info['z_mm']))
    lines.append('layer %d / %d   |   plane_id %s   |   %s'
                 % (stats['layer_index'], len(HEIGHT_KEYS),
                    info['plane_id'], info['kind']))
    role = str(info['role'] or '')
    lines.append('role: %s' % (role if role else '-'))
    if info['manual_group']:
        lines.append('fixed manual group: %s' % info['manual_group'])
    lines.append('')
    lines.append('body routes            %d' % stats['body_routes'])
    lines.append('  manual-U routes      %d' % stats['manual_routes'])
    lines.append('  current group count  %d%s'
                 % (stats['group_count'],
                    ' (%s)' % ', '.join(stats['manual_groups'])
                    if stats['manual_groups'] else ''))
    lines.append('')
    lines.append('same-height crossings  %d' % stats['crossings'])
    lines.append('  unique route pairs   %d' % stats['crossing_pairs'])
    lines.append('  avg per body route   %.2f'
                 % stats['crossings_avg_per_route'])
    lines.append('  max per route        %d'
                 % stats['crossings_max_per_route'])
    lines.append('  stats plane check    %s'
                 % ('match' if stats['crossings_match_planes']
                    else 'n/a' if stats['stats_plane_crossings'] is None
                    else 'MISMATCH'))
    lines.append('')
    lines.append('mid layer changes      %d routes / %d transition ends'
                 % (stats['mid_transition_routes'],
                    stats['mid_transition_events']))
    lines.append('')
    lines.append('covered blocks (flat)  %d / %d'
                 % (stats['covered_blocks_flat'], GRID_N * GRID_N))
    lines.append('idle corridor blocks   %d / %d'
                 % (stats['idle_blocks'], GRID_N * GRID_N))
    lines.append('congested blocks       %d (>=2 X / %.0f mm)'
                 % (stats['congested_blocks'], GRID_MM))
    lines.append('max crossings / block  %d' % stats['max_block_crossings'])
    for rank, hot in enumerate(stats['hotspots'], 1):
        lines.append('  hotspot %d  (%6.1f, %6.1f)  %d X'
                     % (rank, hot['x_mm'], hot['y_mm'], hot['count']))
    lines.append('')
    lines.append('flat lines / R15 arcs  %d / %d'
                 % (stats['line_prims'], stats['arc_prims']))
    lines.append('transition ends here   %d'
                 % stats['transition_prims_touching'])
    return '\n'.join(lines)


def fig_layer(layout, key, out_path, title=None, dpi=DEFAULT_DPI):
    """One independent XY figure of one physical height."""
    stats = layer_stats(layout, key)
    info = HEIGHT_BY_Z[key]
    title = title or ('%s — %s, z = %+.2f mm (layer %d/%d)'
                      % (layout.name, info['label'], info['z_mm'],
                         stats['layer_index'], len(HEIGHT_KEYS)))
    fig = plt.figure(figsize=(11.6, 9.9))
    main_ax = fig.add_axes([0.045, 0.075, 0.665, 0.855])
    info_ax = fig.add_axes([0.735, 0.385, 0.255, 0.545])
    legend_ax = fig.add_axes([0.735, 0.055, 0.255, 0.305])
    info_ax.axis('off')
    legend_ax.axis('off')
    _draw_layer_board(main_ax, layout, key, title=title)
    info_ax.text(0.0, 1.0, _info_text_block(layout, key, stats),
                 transform=info_ax.transAxes, va='top', ha='left',
                 fontsize=7.9, family='DejaVu Sans', linespacing=1.42)
    legend_ax.legend(handles=_layer_legend_handles(layout, key),
                     loc='center', framealpha=0.95, fontsize=7.2,
                     handlelength=1.9, borderaxespad=0.2)
    n_cross = stats['crossings']
    fig.text(0.5, 0.012,
             '%s  |  real stored line / exact R15 arc primitives, exact '
             'S-curve footprint projection, crossing markers from '
             'crossing_stats.json with exact z match (%d on this height)'
             % (layout.name, n_cross), ha='center', fontsize=6.6,
             color='#546e7a')
    fig.text(0.5, 0.028,
             'source: %s/routes_l3d.json + crossing_stats.json'
             % _rel(layout.dir), ha='center', fontsize=6.2, color='#78909c')
    return _save_figure(fig, out_path, dpi=dpi)


# --------------------------------------------------------------------------- #
# drawing: 21-panel overview montage
# --------------------------------------------------------------------------- #
def fig_montage(layout, out_path, title=None, ncols=5, dpi=MONTAGE_DPI):
    rows = all_layer_stats(layout)
    nrows = int(math.ceil(len(HEIGHT_KEYS) / float(ncols)))
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(3.55 * ncols + 0.8, 3.7 * nrows + 0.9))
    axes_flat = np.asarray(axes).ravel()
    for order, key in enumerate(HEIGHT_KEYS):
        ax = axes_flat[order]
        row = rows[order]
        _draw_layer_board(ax, layout, key, crossing_size=7.5,
                          line_lw=0.28, arc_lw=0.6, transition_alpha=0.30,
                          show_transitions=False, show_grid=False,
                          show_congestion=False, title=None)
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.tick_params(labelsize=4.2, length=1.5)
        ax.set_title('%s  z=%+.2f\nroutes %d | crossings %d'
                     % (row['label'], row['z_mm'], row['body_routes'],
                        row['crossings']), fontsize=6.6, pad=2.5)
    for index in range(len(HEIGHT_KEYS), len(axes_flat)):
        axes_flat[index].set_visible(False)
    total = sum(row['crossings'] for row in rows)
    fig.suptitle(title or ('%s — all %d physical heights (XY)'
                           % (layout.name, len(HEIGHT_KEYS))),
                 fontsize=13.0, y=0.995)
    handles = [
        Line2D([0], [0], color=COLORS['plain_line'], lw=1.2,
               label='non-manual flat line'),
        Line2D([0], [0], color=COLORS['manual_line'], lw=1.2,
               label='manual-U flat line'),
        Line2D([0], [0], color=COLORS['plain_arc'], lw=2.0,
               label='non-manual R15 arc'),
        Line2D([0], [0], color=COLORS['manual_arc'], lw=2.0,
               label='manual-U R15 arc'),
        Line2D([0], [0], marker='x', color=COLORS['cross'], ls='none',
               markersize=5.0, markeredgewidth=0.8,
               label='real crossing (%d total, exact z per panel)' % total),
    ]
    fig.legend(handles=handles, loc='lower center', ncol=5, fontsize=8.0,
               framealpha=0.95, bbox_to_anchor=(0.5, 0.001))
    fig.text(0.5, 0.022,
             'panels in physical z order; each panel from the accepted '
             'routes_l3d.json only; transition footprints omitted here '
             '(shown dashed in the per-height figures) — source: %s'
             % _rel(layout.dir), ha='center', fontsize=6.8, color='#546e7a')
    fig.subplots_adjust(left=0.015, right=0.995, top=0.945, bottom=0.055,
                        hspace=0.42, wspace=0.10)
    return _save_figure(fig, out_path, dpi=dpi)


# --------------------------------------------------------------------------- #
# markdown / csv tables of the per-height statistics
# --------------------------------------------------------------------------- #
def _stats_markdown(layout, rows, title):
    lines = ['# %s' % title, '',
             'Source (accepted layout): `%s`' % _rel(layout.dir), '',
             '- routes: **%d** (manual-U %d, groups %d)'
             % (len(layout.by_id), len(layout.manual_route_ids()),
                len({layout.manual_group.get(rid)
                     for rid in layout.manual_route_ids()
                     if layout.manual_group.get(rid)})),
             '- crossings (sum of exact-z events): **%d**'
             % sum(row['crossings'] for row in rows),
             '- routes SHA256: `%s`'
             % (GP.sha256_file(layout.dir / 'routes_l3d.json')
                if (layout.dir / 'routes_l3d.json').exists() else 'n/a'),
             '- generated: %s' % _now(), '',
             '| # | height | z (mm) | body routes | manual-U | groups | '
             'crossings | unique pairs | avg/route | max/route | '
             'mid-layer routes | covered blocks | idle blocks | '
             'congested blocks | max X/block |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for row in rows:
        lines.append('| %d | %s | %+.2f | %d | %d | %d | **%d** | %d | %.2f '
                     '| %d | %d | %d | %d | %d | %d |'
                     % (row['layer_index'], row['label'], row['z_mm'],
                        row['body_routes'], row['manual_routes'],
                        row['group_count'], row['crossings'],
                        row['crossing_pairs'],
                        row['crossings_avg_per_route'],
                        row['crossings_max_per_route'],
                        row['mid_transition_routes'],
                        row['covered_blocks_all'], row['idle_blocks'],
                        row['congested_blocks'], row['max_block_crossings']))
    lines.append('')
    lines.append('Notes:')
    lines.append('- Every number is computed from the accepted '
                 '`routes_l3d.json` real primitives and the '
                 '`crossing_stats.json` events with an **exact** physical-z '
                 'match (rounded to 1e-6 mm).')
    lines.append('- *body routes* = routes with at least one flat part on '
                 'that physical height; *groups* = distinct original '
                 '`manual_group` labels among those body routes.')
    lines.append('- *covered blocks* = %d x %d grid of %.0f mm blocks touched '
                 'by flat routes or transition footprints; *idle blocks* = '
                 'no route geometry at all on that height.'
                 % (GRID_N, GRID_N, GRID_MM))
    lines.append('- *congested block* = block with >=2 real crossing events '
                 'on that height.')
    return '\n'.join(lines) + '\n'


def _stats_rows_csv(rows):
    fields = [
        'layer_index', 'plane_id', 'label', 'z_mm', 'kind', 'role',
        'manual_group_fixed', 'body_routes', 'manual_routes', 'group_count',
        'manual_groups', 'crossings', 'crossing_pairs',
        'crossings_avg_per_route', 'crossings_max_per_route',
        'routes_with_crossings', 'mid_transition_routes',
        'mid_transition_events', 'covered_blocks_flat', 'covered_blocks_all',
        'idle_blocks', 'congested_blocks', 'max_block_crossings',
        'line_prims', 'arc_prims', 'transition_prims_touching',
        'stats_plane_routes', 'stats_plane_crossings',
        'crossings_match_planes',
    ]
    out = []
    for row in rows:
        item = {key: row.get(key) for key in fields}
        item['manual_groups'] = '|'.join(row.get('manual_groups') or [])
        item['hotspots'] = json.dumps(row.get('hotspots') or [],
                                      ensure_ascii=False)
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# suite: 21 independent figures + montage + stats
# --------------------------------------------------------------------------- #
def plot_layer_suite(run_dir, out_dir, prefix='layout', title=None,
                     layers=None, dpi=DEFAULT_DPI, write_montage=True):
    """21 per-height figures + montage + per-height statistics + manifest."""
    started = _now()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = dict(schema=SCHEMA, kind='layer_suite', prefix=prefix,
                  run_dir=_rel(run_dir), out_dir=_rel(out_dir),
                  started_at=started, written=[], errors=[])
    layout = Layout(run_dir, name=title or Path(run_dir).parent.name)
    keys = HEIGHT_KEYS
    if layers:
        wanted = {int(value) for value in layers}
        keys = [key for index, key in enumerate(HEIGHT_KEYS)
                if (index + 1) in wanted]
    figures = []
    for key in keys:
        row = layer_stats(layout, key)
        name = 'layer_%02d_%s_z%+.2fmm.png' % (
            row['layer_index'], row['label'], row['z_mm'])
        try:
            info = fig_layer(layout, key, out_dir / name, title=None)
            figures.append(info)
            result['written'].append(name)
        except Exception as exc:  # noqa: BLE001 - keep other layers going
            result['errors'].append(dict(layer=row['label'], error=repr(exc)))
    if write_montage:
        try:
            info = fig_montage(layout, out_dir / ('%s_21_layers_montage.png'
                                                 % prefix))
            figures.append(info)
            result['written'].append(Path(info['path']).name)
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(dict(figure='montage', error=repr(exc)))
    rows = all_layer_stats(layout)
    totals = layout_statistics(layout)
    _write_json(out_dir / ('%s_layer_stats.json' % prefix),
                dict(layout=totals, per_height=rows,
                     cross_check=dict(
                         crossings_events_sum=sum(row['crossings']
                                                  for row in rows),
                         crossings_stats_file=totals['crossing_total_stats_file'],
                     )))
    _write_csv(out_dir / ('%s_layer_stats.csv' % prefix),
               _stats_rows_csv(rows))
    (out_dir / ('%s_LAYERS.md' % prefix)).write_text(
        _stats_markdown(layout, rows, title or ('%s per-height statistics'
                                                % prefix)),
        encoding='utf-8')
    manifest = dict(
        schema=SCHEMA, kind='layer_suite', prefix=prefix,
        run_dir=_rel(run_dir), generated_at=_now(),
        figures=figures,
        source_files=[meta for meta in (
            _file_meta(Path(run_dir) / 'routes_l3d.json'),
            _file_meta(Path(run_dir) / 'crossing_stats.json'),
            _file_meta(Path(run_dir) / 'assignment_1024.csv'),
        ) if meta],
        stats=dict(routes=totals['routes'],
                   manual_routes=totals['manual_routes'],
                   crossing_total=totals['crossing_total'],
                   crossing_total_stats_file=totals['crossing_total_stats_file'],
                   heights=len(rows)),
        written=result['written'], errors=result['errors'])
    _write_json(out_dir / 'manifest.json', manifest)
    result.update(manifest)
    result['stats_json'] = _rel(out_dir / ('%s_layer_stats.json' % prefix))
    result['layers_md'] = _rel(out_dir / ('%s_LAYERS.md' % prefix))
    _write_json(out_dir / ('%s_run.json' % prefix), result)
    return result


# --------------------------------------------------------------------------- #
# suite: before/after per-height comparison
# --------------------------------------------------------------------------- #
def fig_layer_compare(before, after, key, out_path, info_lines=None,
                      dpi=DEFAULT_DPI):
    left = layer_stats(before, key)
    right = layer_stats(after, key)
    info = HEIGHT_BY_Z[key]
    fig = plt.figure(figsize=(16.2, 8.9))
    ax_before = fig.add_axes([0.030, 0.095, 0.395, 0.815])
    ax_after = fig.add_axes([0.455, 0.095, 0.395, 0.815])
    text_ax = fig.add_axes([0.875, 0.095, 0.118, 0.815])
    text_ax.axis('off')
    _draw_layer_board(ax_before, before, key, crossing_size=17.0,
                      line_lw=0.35, arc_lw=0.8,
                      title='BEFORE  %s  (%d routes, %d crossings)'
                            % (before.name, left['body_routes'],
                               left['crossings']), fontsize_title=9.5)
    _draw_layer_board(ax_after, after, key, crossing_size=17.0,
                      line_lw=0.35, arc_lw=0.8,
                      title='AFTER  %s  (%d routes, %d crossings)'
                            % (after.name, right['body_routes'],
                               right['crossings']), fontsize_title=9.5)
    fig.suptitle('%s  z = %+.2f mm  —  before vs after  (crossings %d -> %d, '
                 '%+d)' % (info['label'], info['z_mm'], left['crossings'],
                           right['crossings'],
                           right['crossings'] - left['crossings']),
                 fontsize=12.5, y=0.985)
    lines = info_lines or []
    lines = list(lines) + [
        '',
        'body routes  %d -> %d' % (left['body_routes'], right['body_routes']),
        'manual-U     %d -> %d' % (left['manual_routes'], right['manual_routes']),
        'groups       %d -> %d' % (left['group_count'], right['group_count']),
        'crossings    %d -> %d' % (left['crossings'], right['crossings']),
        'pairs        %d -> %d' % (left['crossing_pairs'],
                                   right['crossing_pairs']),
        'avg/route    %.2f -> %.2f' % (left['crossings_avg_per_route'],
                                       right['crossings_avg_per_route']),
        'max/route    %d -> %d' % (left['crossings_max_per_route'],
                                   right['crossings_max_per_route']),
        'idle blocks  %d -> %d' % (left['idle_blocks'], right['idle_blocks']),
        'congested    %d -> %d' % (left['congested_blocks'],
                                   right['congested_blocks']),
        'mid-layer    %d -> %d' % (left['mid_transition_routes'],
                                   right['mid_transition_routes']),
    ]
    text_ax.text(0.0, 1.0, '\n'.join(lines), transform=text_ax.transAxes,
                 va='top', ha='left', fontsize=7.6, linespacing=1.45)
    handles = [Line2D([0], [0], color=COLORS['plain_line'], lw=1.1,
                      label='non-manual line'),
               Line2D([0], [0], color=COLORS['manual_line'], lw=1.1,
                      label='manual-U line'),
               Line2D([0], [0], color=COLORS['plain_arc'], lw=2.0,
                      label='non-manual R15 arc'),
               Line2D([0], [0], color=COLORS['manual_arc'], lw=2.0,
                      label='manual-U R15 arc'),
               Line2D([0], [0], color=COLORS['transition'], lw=1.0,
                      linestyle=(0, (3, 2.5)),
                      label='3-D transition footprint (projected)'),
               Line2D([0], [0], marker='x', color=COLORS['cross'], ls='none',
                      markersize=5.0, label='real crossing (exact z)')]
    fig.legend(handles=handles, loc='lower center', ncol=6, fontsize=7.4,
               framealpha=0.95, bbox_to_anchor=(0.5, 0.005))
    fig.text(0.5, 0.036,
             'accepted geometry only: before = %s, after = %s'
             % (_rel(before.dir), _rel(after.dir)), ha='center',
             fontsize=6.8, color='#546e7a')
    return _save_figure(fig, out_path, dpi=dpi)


def plot_compare_suite(before_dir, after_dir, out_dir, prefix='compare',
                       before_name='BEFORE', after_name='AFTER',
                       dpi=DEFAULT_DPI):
    started = _now()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = dict(schema=SCHEMA, kind='compare_suite', prefix=prefix,
                  started_at=started, written=[], errors=[])
    before = Layout(before_dir, name=before_name)
    after = Layout(after_dir, name=after_name)
    figures = []
    rows = []
    for key in HEIGHT_KEYS:
        left = layer_stats(before, key)
        right = layer_stats(after, key)
        row = dict(
            layer_index=left['layer_index'], label=left['label'],
            z_mm=left['z_mm'],
            before_routes=left['body_routes'], after_routes=right['body_routes'],
            before_manual=left['manual_routes'],
            after_manual=right['manual_routes'],
            before_groups=left['group_count'],
            after_groups=right['group_count'],
            before_crossings=left['crossings'],
            after_crossings=right['crossings'],
            delta_crossings=right['crossings'] - left['crossings'],
            before_pairs=left['crossing_pairs'],
            after_pairs=right['crossing_pairs'],
            before_avg=left['crossings_avg_per_route'],
            after_avg=right['crossings_avg_per_route'],
            before_max=left['crossings_max_per_route'],
            after_max=right['crossings_max_per_route'],
            before_idle=left['idle_blocks'], after_idle=right['idle_blocks'],
            before_congested=left['congested_blocks'],
            after_congested=right['congested_blocks'],
            before_mid=left['mid_transition_routes'],
            after_mid=right['mid_transition_routes'],
        )
        rows.append(row)
        name = 'compare_layer_%02d_%s_z%+.2fmm.png' % (
            left['layer_index'], left['label'], left['z_mm'])
        try:
            info = fig_layer_compare(before, after, key, out_dir / name)
            figures.append(info)
            result['written'].append(name)
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(dict(layer=left['label'],
                                         error=repr(exc)))
    _write_csv(out_dir / ('%s_per_height.csv' % prefix), rows)
    totals = dict(
        before=dict(routes=len(before.by_id),
                    crossings=sum(row['before_crossings'] for row in rows)),
        after=dict(routes=len(after.by_id),
                   crossings=sum(row['after_crossings'] for row in rows)),
    )
    totals['delta_crossings'] = (totals['after']['crossings']
                                 - totals['before']['crossings'])
    _write_json(out_dir / ('%s_per_height.json' % prefix),
                dict(totals=totals, per_height=rows, generated_at=_now()))
    _write_json(out_dir / ('%s_manifest.json' % prefix),
                dict(schema=SCHEMA, kind='compare_suite',
                     before=_rel(before_dir), after=_rel(after_dir),
                     generated_at=_now(), figures=figures, totals=totals,
                     errors=result['errors']))
    result.update(totals=totals, rows=rows, figures=figures)
    _write_json(out_dir / ('%s_run.json' % prefix), result)
    return result


# --------------------------------------------------------------------------- #
# manual-U migration: original 8 groups -> new geometric families
# --------------------------------------------------------------------------- #
def _load_changes(path):
    if not path:
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    return payload


def plot_migration(before_dir, after_dir, out_dir, changes_json=None,
                   prefix='manual_u_migration', dpi=DEFAULT_DPI):
    """Original manual-U group -> new geometric family migration matrix."""
    started = _now()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = Layout(before_dir, name='G3')
    after = Layout(after_dir, name='G4')
    manual_ids = before.manual_route_ids()
    changes = _load_changes(changes_json)
    result = dict(schema=SCHEMA, kind='manual_u_migration',
                  before=_rel(before_dir), after=_rel(after_dir),
                  manual_routes=len(manual_ids), started_at=started,
                  written=[], errors=[])
    old_groups = []
    for group in M.MANUAL_GROUPS.keys():
        if any(before.manual_group.get(rid) == group for rid in manual_ids):
            old_groups.append(group)
    for rid in manual_ids:
        group = before.manual_group.get(rid)
        if group and group not in old_groups:
            old_groups.append(group)
    new_families = {}
    for rid in manual_ids:
        z = after.primary_z.get(rid)
        if z is None:
            new_families[rid] = 'unknown'
            continue
        new_families[rid] = '%s %+.2f' % (V._height_info(z)['label'],
                                          float(z))
    family_order = sorted({value for value in new_families.values()},
                          key=lambda text: (text == 'unknown', text))
    matrix = OrderedDict()
    for group in old_groups:
        row = OrderedDict((family, 0) for family in family_order)
        for rid in manual_ids:
            if before.manual_group.get(rid) != group:
                continue
            row[new_families[rid]] = row.get(new_families[rid], 0) + 1
        matrix[group] = row
    table_rows = []
    for group in old_groups:
        row = matrix[group]
        table_rows.append(dict(
            original_group=group,
            n=int(sum(row.values())),
            **{('new_' + family.replace(' ', '_')): count
               for family, count in row.items()},
            n_new_families=sum(1 for count in row.values() if count),
        ))
    _write_json(out_dir / ('%s.json' % prefix),
                dict(manual_routes=len(manual_ids), old_groups=old_groups,
                     new_families=family_order,
                     matrix={group: dict(row) for group, row in matrix.items()},
                     changes_source=(_rel(changes_json) if changes_json else None),
                     changes_payload=changes if changes else None,
                     generated_at=_now()))
    if before.by_id and after.by_id:
        fig = plt.figure(figsize=(14.6, 9.4))
        matrix_ax = fig.add_axes([0.10, 0.12, 0.52, 0.76])
        group_ax = fig.add_axes([0.66, 0.12, 0.31, 0.76])
        data = np.zeros((len(old_groups), len(family_order)), dtype=float)
        for r_index, group in enumerate(old_groups):
            for c_index, family in enumerate(family_order):
                data[r_index, c_index] = matrix[group].get(family, 0)
        image = matrix_ax.imshow(data, aspect='auto', cmap='YlOrRd',
                                 interpolation='nearest')
        matrix_ax.set_xticks(range(len(family_order)))
        matrix_ax.set_xticklabels(family_order, rotation=90, fontsize=6.6)
        matrix_ax.set_yticks(range(len(old_groups)))
        matrix_ax.set_yticklabels(['%s (%d)'
                                   % (group, int(sum(matrix[group].values())))
                                   for group in old_groups], fontsize=8.0)
        matrix_ax.set_xlabel('new geometric family (primary body height, '
                             'from accepted G4 geometry)')
        matrix_ax.set_ylabel('original manual-U group (G3)')
        matrix_ax.set_title('manual-U routes: original group -> new family '
                            '(%d routes)' % len(manual_ids), fontsize=10.0)
        for r_index in range(len(old_groups)):
            for c_index in range(len(family_order)):
                value = int(data[r_index, c_index])
                if value:
                    matrix_ax.text(c_index, r_index, str(value), ha='center',
                                   va='center', fontsize=6.2,
                                   color='white' if value > data.max() * 0.5
                                   else '#212121')
        colorbar = fig.colorbar(image, ax=matrix_ax, fraction=0.035, pad=0.02)
        colorbar.set_label('manual-U routes')
        group_ax.axis('off')
        lines = ['original group -> spread over new heights', '']
        for row in table_rows:
            lines.append('%s  n=%d  families=%d'
                         % (row['original_group'], row['n'],
                            row['n_new_families']))
        lines.append('')
        lines.append('routes staying on their original group height:')
        group_sizes = {row['original_group']: row['n'] for row in table_rows}
        for group in old_groups:
            heights = Counter(before.primary_z.get(rid) for rid in manual_ids
                              if before.manual_group.get(rid) == group)
            if not heights:
                continue
            old_z = heights.most_common(1)[0][0]
            keep = sum(1 for rid in manual_ids
                       if before.manual_group.get(rid) == group
                       and abs((after.primary_z.get(rid) or 1e9) - old_z) < 1e-6)
            n_group = group_sizes.get(group) or 0
            lines.append('  %s: %d / %d (%.0f%%)'
                         % (group, keep, n_group,
                            100.0 if not n_group else 100.0 * keep / n_group))
        group_ax.text(0.0, 1.0, '\n'.join(lines), transform=group_ax.transAxes,
                      va='top', ha='left', fontsize=7.8, linespacing=1.5)
        fig.suptitle('G4 manual-U dynamic regrouping — real geometry evidence '
                     '(G3 groups vs accepted G4 body heights)', fontsize=12.0,
                     y=0.975)
        fig.text(0.5, 0.02,
                 'families are derived from the accepted G4 routes_l3d.json '
                 'primary body z (not from labels); source: %s -> %s'
                 % (_rel(before_dir), _rel(after_dir)), ha='center',
                 fontsize=6.8, color='#546e7a')
        try:
            info = _save_figure(fig, out_dir / ('%s_matrix.png' % prefix), dpi=dpi)
            result['written'].append('%s_matrix.png' % prefix)
            result['figure'] = info
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(dict(figure='migration', error=repr(exc)))
    result.update(rows=table_rows, matrix={group: dict(row)
                                           for group, row in matrix.items()})
    _write_csv(out_dir / ('%s_table.csv' % prefix), table_rows)
    _write_json(out_dir / ('%s_run.json' % prefix), result)
    return result


# --------------------------------------------------------------------------- #
# XY / Z modification statistics
# --------------------------------------------------------------------------- #
def plot_modifications(before_dir, after_dir, out_dir, prefix='modifications',
                       dpi=DEFAULT_DPI):
    started = _now()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    before = Layout(before_dir, name='G3')
    after = Layout(after_dir, name='G4')
    result = dict(schema=SCHEMA, kind='modifications',
                  before=_rel(before_dir), after=_rel(after_dir),
                  started_at=started, written=[], errors=[])
    changed = set(V.changed_route_ids(before.routes, after.routes))
    rows = []
    classes = Counter()
    class_manual = Counter()
    length_deltas = []
    dz_values = []
    for rid in sorted(set(before.by_id) & set(after.by_id)):
        old_route = before.by_id[rid]
        new_route = after.by_id[rid]
        old_z = before.primary_z.get(rid)
        new_z = after.primary_z.get(rid)
        z_changed = (old_z is not None and new_z is not None
                     and abs(float(old_z) - float(new_z)) > 1e-9)
        xy_changed = _xy_signature(old_route) != _xy_signature(new_route)
        if z_changed and xy_changed:
            label = 'xy+z'
        elif z_changed:
            label = 'z_only'
        elif xy_changed:
            label = 'xy_only'
        else:
            label = 'unchanged'
        classes[label] += 1
        if before.manual.get(rid):
            class_manual[label] += 1
        old_len = V._route_length(old_route)
        new_len = V._route_length(new_route)
        length_deltas.append((label, float(new_len or 0.0)
                              - float(old_len or 0.0)))
        if old_z is not None and new_z is not None:
            dz_values.append(float(new_z) - float(old_z))
        rows.append(dict(route_id=rid, manual=bool(before.manual.get(rid)),
                         manual_group=before.manual_group.get(rid) or '',
                         old_primary_z=old_z, new_primary_z=new_z,
                         dz_mm=(round(float(new_z) - float(old_z), 6)
                                if old_z is not None and new_z is not None
                                else None),
                         xy_changed=bool(xy_changed), z_changed=bool(z_changed),
                         class_label=label,
                         old_length_mm=round(float(old_len or 0.0), 4),
                         new_length_mm=round(float(new_len or 0.0), 4),
                         length_delta_mm=round(float(new_len or 0.0)
                                               - float(old_len or 0.0), 4)))
    _write_csv(out_dir / ('%s_per_route.csv' % prefix), rows)
    summary = dict(
        routes=len(rows),
        changed_routes=len(changed),
        changed_manual=sum(1 for rid in changed if before.manual.get(rid)),
        changed_non_manual=sum(1 for rid in changed
                               if not before.manual.get(rid)),
        classes=dict(classes),
        classes_manual=dict(class_manual),
        abs_length_delta_mean=round(
            float(np.mean([abs(delta) for _, delta in length_deltas]))
            if length_deltas else 0.0, 4),
        abs_length_delta_max=round(
            float(np.max([abs(delta) for _, delta in length_deltas]))
            if length_deltas else 0.0, 4),
        dz_values=len([value for value in dz_values if abs(value) > 1e-9]),
        dz_min=(min(dz_values) if dz_values else None),
        dz_max=(max(dz_values) if dz_values else None),
        generated_at=_now(),
    )
    _write_json(out_dir / ('%s_summary.json' % prefix), summary)
    try:
        fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.2))
        order = ['unchanged', 'xy_only', 'z_only', 'xy+z']
        labels = [label for label in order if classes.get(label)]
        manual_counts = [class_manual.get(label, 0) for label in labels]
        other_counts = [classes.get(label, 0) - class_manual.get(label, 0)
                        for label in labels]
        x = np.arange(len(labels))
        ax = axes[0][0]
        ax.bar(x, other_counts, color=COLORS['plain_line'], label='non-manual')
        ax.bar(x, manual_counts, bottom=other_counts, color=COLORS['manual_line'],
               label='manual-U')
        for index, (below, above) in enumerate(zip(other_counts,
                                                   manual_counts)):
            ax.text(index, below + above, str(below + above), ha='center',
                    va='bottom', fontsize=8.0)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8.0)
        ax.set_ylabel('routes')
        ax.set_title('route geometry change classes (accepted layouts)')
        ax.legend(fontsize=7.5)
        ax.grid(axis='y', linewidth=0.3, color='#e0e0e0')

        ax = axes[0][1]
        keep_values = [dz for dz in dz_values if abs(dz) <= 1e-9]
        change_values = [dz for dz in dz_values if abs(dz) > 1e-9]
        ax.hist([keep_values, change_values], bins=22, stacked=True,
                color=[COLORS['before'], COLORS['after']],
                label=['unchanged height', 'height changed'])
        ax.set_xlabel('primary height change dz (mm)')
        ax.set_ylabel('routes')
        ax.set_title('Z modification (primary body height)')
        ax.legend(fontsize=7.5)

        ax = axes[1][0]
        for label, color in (('unchanged', COLORS['before']),
                             ('xy_only', COLORS['plain_line']),
                             ('z_only', COLORS['manual_arc']),
                             ('xy+z', COLORS['manual_line'])):
            values = [delta for item, delta in length_deltas if item == label]
            if values:
                ax.hist(values, bins=40, alpha=0.55, label=label, color=color)
        ax.set_xlabel('route length change (mm)')
        ax.set_ylabel('routes')
        ax.set_title('XY geometry: route length change')
        ax.legend(fontsize=7.0)

        ax = axes[1][1]
        for group in sorted({row['manual_group'] for row in rows
                             if row['manual_group']}):
            values = [row['dz_mm'] for row in rows
                      if row['manual_group'] == group
                      and row['dz_mm'] is not None]
            if not values:
                continue
            ax.scatter([group] * len(values), values, s=14.0, alpha=0.7,
                       label=group)
        ax.axhline(0.0, color='#616161', linewidth=0.6)
        ax.set_ylabel('primary height change dz (mm)')
        ax.set_title('manual-U height modification per original group')
        ax.tick_params(axis='x', rotation=35, labelsize=7.0)
        fig.suptitle('G4 XY / Z modification statistics (accepted geometry '
                     'differs from G3)', fontsize=12.0, y=0.99)
        fig.text(0.5, 0.005,
                 'source: %s vs %s — changed = any stored primitive differs; '
                 'xy signature excludes physical z'
                 % (_rel(before_dir), _rel(after_dir)), ha='center',
                 fontsize=6.8, color='#546e7a')
        fig.subplots_adjust(left=0.06, right=0.985, top=0.93, bottom=0.08,
                            hspace=0.34, wspace=0.22)
        info = _save_figure(fig, out_dir / ('%s_xy_z_stats.png' % prefix),
                            dpi=dpi)
        result['written'].append('%s_xy_z_stats.png' % prefix)
        result['figure'] = info
    except Exception as exc:  # noqa: BLE001
        result['errors'].append(dict(figure='modifications', error=repr(exc)))
    result['summary'] = summary
    _write_json(out_dir / ('%s_run.json' % prefix), result)
    return result


# --------------------------------------------------------------------------- #
# crossings vs evaluation budget curve + budget ledger bars
# --------------------------------------------------------------------------- #
_X_CANDIDATES = ('route_3d_checks', 'checks', 'candidate_checks',
                 '3d_checks', 'contract_checks', 'evals', 'evaluations',
                 'route_checks')
_Y_CANDIDATES = ('crossings', 'total', 'best_total', 'best_crossings',
                 'best', 'crossing_total')
_T_CANDIDATES = ('wall_seconds', 'elapsed_s', 'elapsed_seconds', 'seconds',
                 'time_s', 'wall_s', 'elapsed')


def _first_key(row, candidates):
    for key in candidates:
        if key in row and row[key] not in (None, ''):
            try:
                float(row[key])
            except (TypeError, ValueError):
                continue
            return key
    return None


def _read_history(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                rows.append(dict(row))
    except (OSError, ValueError, csv.Error):
        return []
    return rows


def _history_from_rounds(arm_dir):
    """Fallback curve points from ``strategy_stats.json`` / ``progress.json``.

    Used when an arm does not write a per-accept ``optimization_history.csv``
    (e.g. C0 which reuses the old G3 optimizer).  Times are accumulated
    per-round seconds unless the node carries an absolute wall value.  The
    returned points are labelled ``fallback`` and are only drawn on the
    wall-time axis (they carry no per-step ``route_3d_checks`` counter).
    """
    points = []
    for filename in ('strategy_stats.json', 'progress.json',
                     'search_result.json'):
        payload = _read_json(Path(arm_dir) / filename)
        if not isinstance(payload, dict):
            continue
        nodes = []

        def walk(node, depth=0):
            if depth > 9:
                return
            if isinstance(node, dict):
                has_total = any(key in node for key in
                                ('total_after', 'final_total', 'total'))
                has_time = any(key in node for key in
                               ('seconds', 'seconds_used', 'wall',
                                'wall_seconds', 'elapsed', 'elapsed_seconds'))
                if has_total and has_time:
                    nodes.append(node)
                for value in node.values():
                    walk(value, depth + 1)
            elif isinstance(node, list):
                for item in node:
                    walk(item, depth + 1)

        walk(payload)
        accumulator = 0.0
        for node in nodes:
            crossing = node.get('total_after', node.get('final_total',
                                                       node.get('total')))
            try:
                crossing = float(crossing)
            except (TypeError, ValueError):
                continue
            wall = node.get('wall', node.get('wall_seconds'))
            elapsed = None
            if wall is not None:
                try:
                    elapsed = float(wall)
                except (TypeError, ValueError):
                    elapsed = None
            if elapsed is None:
                for key in ('seconds', 'seconds_used', 'elapsed',
                            'elapsed_seconds'):
                    value = node.get(key)
                    if value is None:
                        continue
                    try:
                        accumulator += float(value)
                        elapsed = accumulator
                        break
                    except (TypeError, ValueError):
                        continue
            if elapsed is None:
                continue
            points.append(dict(wall_seconds=elapsed, crossings=crossing,
                               source=filename, step=len(points) + 1))
        if points:
            break
    return points


def plot_budget_curves(arms, out_dir, prefix='budget', baseline_crossings=None,
                       dpi=DEFAULT_DPI):
    """Crossings vs route_3d_checks and vs wall time, one line per arm."""
    started = _now()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = dict(schema=SCHEMA, kind='budget_curves', started_at=started,
                  arms=[], written=[], errors=[], missing=[])
    series = []
    ledger_rows = []
    for name, arm_dir in arms.items():
        arm_dir = Path(arm_dir)
        history = _read_history(arm_dir / 'optimization_history.csv')
        fallback = None
        if not history:
            fallback = _history_from_rounds(arm_dir)
            if not fallback:
                result['missing'].append(dict(
                    arm=name, file='optimization_history.csv '
                                   '(+ strategy_stats/progress fallback)'))
                continue
        x_key = _first_key(history[0], _X_CANDIDATES) if history else None
        y_key = _first_key(history[0], _Y_CANDIDATES) if history else None
        t_key = _first_key(history[0], _T_CANDIDATES) if history else None
        points = []
        if history:
            if y_key is None:
                result['missing'].append(dict(arm=name,
                                              file='crossing column in history'))
                continue
            for index, row in enumerate(history):
                try:
                    y = float(row[y_key])
                except (TypeError, ValueError):
                    continue
                x = float(row[x_key]) if x_key else float(index + 1)
                t = float(row[t_key]) if t_key else None
                points.append(dict(x=x, y=y, t=t, index=index + 1))
        else:
            for point in fallback:
                points.append(dict(x=float(point['step']), y=point['crossings'],
                                   t=point['wall_seconds'],
                                   index=point['step']))
            x_key = 'search step (fallback: no per-step check counter)'
        if not points:
            result['missing'].append(dict(arm=name, file='history points'))
            continue
        series.append(dict(name=name, points=points,
                           x_key=x_key or 'row', y_key=y_key or 'crossings',
                           t_key=t_key or 'wall_seconds',
                           fallback=fallback is not None))
        ledger = _read_json(arm_dir / 'budget_ledger.json', {}) or {}
        result['arms'].append(dict(
            name=name, dir=_rel(arm_dir), history_rows=len(history),
            fallback=fallback is not None,
            fallback_source=(fallback[0].get('source') if fallback else None),
            x_key=x_key, y_key=y_key, t_key=t_key,
            first_y=points[0]['y'] if points else None,
            last_y=points[-1]['y'] if points else None,
            ledger=ledger))
        ledger_rows.append(dict(arm=name, **{key: value for key, value in
                                             (ledger or {}).items()
                                             if isinstance(value, (int, float,
                                                                   str))}))
    if ledger_rows:
        _write_csv(out_dir / ('%s_ledger.csv' % prefix), ledger_rows)
    _write_json(out_dir / ('%s_curves.json' % prefix),
                dict(series=series, arms=result['arms'],
                     baseline_crossings=baseline_crossings,
                     generated_at=_now()))
    if not series:
        _write_json(out_dir / ('%s_run.json' % prefix), result)
        return result
    fig, axes = plt.subplots(1, 3, figsize=(17.6, 5.9))
    ax = axes[0]
    plotted_checks = 0
    for item in series:
        if item.get('fallback'):
            continue
        points = item['points']
        ax.plot([point['x'] for point in points],
                [point['y'] for point in points], marker='o', markersize=2.8,
                linewidth=1.3, label=item['name'])
        plotted_checks += 1
    if baseline_crossings:
        ax.axhline(float(baseline_crossings), color='#9e9e9e', linestyle='--',
                   linewidth=1.0,
                   label='G3 start = %d' % int(baseline_crossings))
    if not plotted_checks:
        ax.text(0.5, 0.5,
                'no per-step route_3d_checks history:\nsee the wall-time panel '
                '(fallback curves from strategy/progress counters)',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=8.0, color='#b71c1c')
    ax.set_xlabel('route_3d_checks (real 3-D checks in the shared engine)')
    ax.set_ylabel('same-height crossings')
    ax.set_title('crossings vs evaluation budget')
    ax.legend(fontsize=7.4)
    ax.grid(linewidth=0.3, color='#e0e0e0')

    ax = axes[1]
    for item in series:
        points = [point for point in item['points']
                  if point.get('t') is not None]
        if not points:
            continue
        ax.plot([point['t'] for point in points],
                [point['y'] for point in points], marker='o', markersize=2.8,
                linewidth=1.3, label=item['name'])
    if baseline_crossings:
        ax.axhline(float(baseline_crossings), color='#9e9e9e', linestyle='--',
                   linewidth=1.0)
    ax.set_xlabel('wall time (s)')
    ax.set_ylabel('same-height crossings')
    ax.set_title('crossings vs wall time')
    ax.legend(fontsize=7.4)
    ax.grid(linewidth=0.3, color='#e0e0e0')

    ax = axes[2]
    names = [item['name'] for item in series]
    best = [min(point['y'] for point in item['points']) for item in series]
    colors = plt.get_cmap('tab10').colors
    bars = ax.bar(range(len(names)), best,
                  color=[colors[index % 10] for index in range(len(names))],
                  edgecolor='#37474f', linewidth=0.5)
    for bar, value in zip(bars, best):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value, '%d' % int(value),
                ha='center', va='bottom', fontsize=7.2)
    if baseline_crossings:
        ax.axhline(float(baseline_crossings), color='#9e9e9e',
                   linestyle='--', linewidth=1.0)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=20, fontsize=7.4)
    ax.set_ylabel('best crossings reached')
    ax.set_title('best crossing count per arm')
    ax.grid(axis='y', linewidth=0.3, color='#e0e0e0')
    fig.suptitle('G4 crossings vs evaluation budget (real accepted changes; '
                 'fallback curves from strategy/progress counters when an arm '
                 'writes no per-step history)', fontsize=11.0, y=0.99)
    fig.text(0.5, 0.005,
             'budget counters are the shared-engine real counters; missing '
             'arms are listed in the JSON output', ha='center', fontsize=6.8,
             color='#546e7a')
    fig.subplots_adjust(left=0.055, right=0.99, top=0.92, bottom=0.11,
                        wspace=0.24)
    try:
        info = _save_figure(fig, out_dir / ('%s_curves.png' % prefix), dpi=dpi)
        result['written'].append('%s_curves.png' % prefix)
        result['figure'] = info
    except Exception as exc:  # noqa: BLE001
        result['errors'].append(dict(figure='budget', error=repr(exc)))
    _write_json(out_dir / ('%s_run.json' % prefix), result)
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_layers(text):
    if not text:
        return None
    return [int(part) for part in str(text).replace(';', ',').split(',')
            if part.strip()]


def _build_parser():
    parser = argparse.ArgumentParser(
        description='G4-5 visualisation (real accepted geometry only)')
    sub = parser.add_subparsers(dest='mode', required=True)

    p = sub.add_parser('layer-suite', help='21 per-height figures + montage')
    p.add_argument('--run-dir', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--prefix', default='layout')
    p.add_argument('--title', default=None)
    p.add_argument('--layers', default=None)
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)
    p.add_argument('--no-montage', action='store_true')

    p = sub.add_parser('compare-suite', help='before/after per-height compare')
    p.add_argument('--before', required=True)
    p.add_argument('--after', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--prefix', default='compare')
    p.add_argument('--before-name', default='BEFORE')
    p.add_argument('--after-name', default='AFTER')
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)

    p = sub.add_parser('migration', help='manual-U group -> new family')
    p.add_argument('--before', required=True)
    p.add_argument('--after', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--changes-json', default=None)
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)

    p = sub.add_parser('modifications', help='XY / Z modification statistics')
    p.add_argument('--before', required=True)
    p.add_argument('--after', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)

    p = sub.add_parser('budget', help='crossings vs budget curves')
    p.add_argument('--out-dir', required=True)
    p.add_argument('--baseline-crossings', type=int, default=1322)
    p.add_argument('--arm', action='append', default=[],
                   help='NAME=directory (repeatable)')
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.mode == 'layer-suite':
        result = plot_layer_suite(args.run_dir, args.out_dir,
                                  prefix=args.prefix, title=args.title,
                                  layers=_parse_layers(args.layers),
                                  dpi=args.dpi,
                                  write_montage=not args.no_montage)
    elif args.mode == 'compare-suite':
        result = plot_compare_suite(args.before, args.after, args.out_dir,
                                    prefix=args.prefix,
                                    before_name=args.before_name,
                                    after_name=args.after_name, dpi=args.dpi)
    elif args.mode == 'migration':
        result = plot_migration(args.before, args.after, args.out_dir,
                                changes_json=args.changes_json, dpi=args.dpi)
    elif args.mode == 'modifications':
        result = plot_modifications(args.before, args.after, args.out_dir,
                                    dpi=args.dpi)
    elif args.mode == 'budget':
        arms = OrderedDict()
        for item in args.arm:
            name, _, directory = item.partition('=')
            if name and directory:
                arms[name] = directory
        if not arms:
            for name, directory in GP.ARM_DIRS.items():
                if name in ('best_valid', 'chain', 'plots', 'reports',
                            'audit', 'checkpoints', 'code'):
                    continue
                arms[name] = directory
        result = plot_budget_curves(arms, args.out_dir,
                                    baseline_crossings=args.baseline_crossings,
                                    dpi=args.dpi)
    else:  # pragma: no cover
        raise SystemExit('unknown mode %r' % args.mode)
    print(json.dumps({key: value for key, value in result.items()
                      if key in ('written', 'errors', 'missing', 'stats',
                                 'totals', 'layers_md', 'stats_json')},
                     ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
