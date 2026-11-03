# -*- coding: utf-8 -*-
"""Plot generation for the fanout-first Z2-manual-verified 1024 run.

Writes into ``RUN_DIR/plots/``:

* ``01_3d_all_routes.png``       all routed routes in 3D, coloured by plane
* ``02_3d_manual_groups.png``    the 8 manual groups, one 3D subplot each
* ``03_layer_stack_section.png`` the 18 routing layers + interfaces + assignments
* ``04_per_layer_2d.png``        per-layer 2D routing views (colour = manual group)
* ``05_manual_2d_layers.png``    the 8 manual layers in 2D detail
* ``06_validation_summary.png``  success/failure bars by plane / group / layer
* ``plots_manifest.json``        which figures were produced and which skipped

Every figure is produced independently and robustly: missing input files or
missing route parts are logged as ``skipped`` instead of crashing the run.

CLI::

    python -m four_side_1024.fanout1024.plots [--run-dir DIR] [--only NAME]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from collections import Counter, OrderedDict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection  # noqa: E402

from . import common  # noqa: E402
from ..fsd25d import path3d as P  # noqa: E402

RUN_DIR = common.RUN_DIR
PLOTS_DIR = RUN_DIR / 'plots'
BOARD_MM = 150.0

PLANE_COLORS = {'z1': '#1f77b4', 'z2': '#ff7f0e'}
GROUP_COLORS = OrderedDict([
    ('Z1-U1', '#e6194b'), ('Z1-U2', '#f58231'),
    ('Z1-U3', '#3cb44b'), ('Z1-U4', '#4363d8'),
    ('Z2-U1', '#911eb4'), ('Z2-U2', '#f032e6'),
    ('Z2-U3', '#008080'), ('Z2-U4', '#9a6324'),
])
OTHER_COLOR = '#8c8c8c'
INTERFACE_COLOR = '#222222'

#: manual group -> fixed layer (new naming)
MANUAL_GROUP_LAYER = OrderedDict([
    ('Z1-U1', 2), ('Z1-U2', 3), ('Z1-U3', 4), ('Z1-U4', 5),
    ('Z2-U1', 10), ('Z2-U2', 11), ('Z2-U3', 12), ('Z2-U4', 13),
])
MANUAL_GROUP_ALIASES = {'NS-1': 'Z1-U1', 'NS-2': 'Z1-U2',
                        'EW-1': 'Z1-U3', 'EW-2': 'Z1-U4'}
LAYER_GROUP = {layer: group for group, layer in MANUAL_GROUP_LAYER.items()}


def _log(entries, message, level='info'):
    print(f'[plots] {level}: {message}', flush=True)
    entries.append(dict(level=level, message=message))


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def load_routes(run_dir):
    """Load routed/failed route records from RUN_DIR/routes_l3d.json."""
    run_dir = Path(run_dir)
    payload = _read_json(run_dir / 'routes_l3d.json')
    if not isinstance(payload, dict):
        return None, None, None
    records = payload.get('routes') or []
    routed, failed = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        status = str(record.get('status') or 'routed').strip().lower()
        if status in ('routed', 'ok', 'success', 'valid', 'accepted', 'done'):
            routed.append(record)
        else:
            failed.append(record)
    routed.sort(key=lambda item: int(item.get('route_id', 0)))
    failed.sort(key=lambda item: int(item.get('route_id', 0)))
    return routed, failed, payload


def load_assignment(run_dir):
    """assignment_1024.csv -> {route_id: row} (best effort, no crash)."""
    import csv
    path = Path(run_dir) / 'assignment_1024.csv'
    if not path.exists():
        return {}
    rows = {}
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    route_id = int(str(row.get('route_id')).strip())
                except (TypeError, ValueError):
                    continue
                rows[route_id] = row
    except OSError:
        return {}
    return rows


def _normalise_group(name):
    text = str(name or '').strip()
    if not text:
        return ''
    return MANUAL_GROUP_ALIASES.get(text, text)


def route_group(record, assignment_rows):
    """Manual group of a route (new names normalised, old names aliased)."""
    route_id = record.get('route_id')
    try:
        route_id = int(route_id)
    except (TypeError, ValueError):
        route_id = None
    row = assignment_rows.get(route_id) if route_id is not None else None
    if isinstance(row, dict):
        group = _normalise_group(row.get('manual_group'))
        if group:
            return group
        layer = row.get('physical_layer') or row.get('logical_layer')
        try:
            layer = int(str(layer).strip())
        except (TypeError, ValueError):
            layer = None
        if layer in LAYER_GROUP:
            return LAYER_GROUP[layer]
    # fallback: body flat layer
    for part in record.get('parts') or []:
        if part.get('kind') != 'flat':
            continue
        try:
            layer_id = int(part.get('layer_id'))
        except (TypeError, ValueError):
            continue
        if layer_id in LAYER_GROUP:
            return LAYER_GROUP[layer_id]
    return ''


def layer_of(record):
    """Assigned/body routing layer of a route (or None)."""
    for part in record.get('parts') or []:
        if part.get('kind') != 'flat':
            continue
        try:
            layer_id = int(part.get('layer_id'))
        except (TypeError, ValueError):
            continue
        if layer_id != 1:
            return layer_id
    return None


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def route_polyline(record, step_flat=1.0, step_transition=0.1):
    parts = record.get('parts') or []
    if not parts:
        return None
    try:
        points, _lengths = P.sample_parts(parts, step_flat=step_flat,
                                          step_transition=step_transition)
    except (KeyError, TypeError, ValueError):
        return None
    if len(points) < 2:
        return None
    return np.asarray(points, dtype=float)


def flat_prim_polyline(prim, step=0.5):
    """2D polyline of one fslw primitive (line or arc)."""
    kind = prim.get('kind')
    p0 = prim.get('p0')
    p1 = prim.get('p1')
    if kind == 'line' and p0 is not None and p1 is not None:
        return [(float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1]))]
    if kind == 'arc':
        try:
            center = prim['center']
            radius = float(prim['radius'])
            start = float(prim['start_angle'])
            sweep = float(prim['sweep'])
        except (KeyError, TypeError, ValueError):
            return None
        count = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
        angles = np.linspace(start, start + sweep, count)
        return [(float(center[0] + radius * math.cos(angle)),
                 float(center[1] + radius * math.sin(angle)))
                for angle in angles.tolist()]
    return None


def flat_part_polylines(part):
    """List of 2D polylines for one flat part."""
    out = []
    for prim in part.get('primitives') or []:
        polyline = flat_prim_polyline(prim)
        if polyline and len(polyline) >= 2:
            out.append(polyline)
    return out


def _save(fig, path, manifest, name):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    manifest['figures'].append(dict(name=name, path=str(path),
                                    bytes=path.stat().st_size if path.exists() else 0))
    _log(manifest['log'], f'wrote {path.name}')
    return path


def _skip(manifest, name, reason):
    manifest['skipped'].append(dict(name=name, reason=reason))
    _log(manifest['log'], f'skip {name}: {reason}', level='warn')


# ---------------------------------------------------------------------------
# (a) 3D all routes, coloured by plane
# ---------------------------------------------------------------------------
def plot_3d_all_routes(run_dir, out_dir, manifest):
    routed, _failed, _payload = load_routes(run_dir)
    name = '01_3d_all_routes'
    if not routed:
        _skip(manifest, name, 'no routed routes / routes_l3d.json missing')
        return None
    fig = plt.figure(figsize=(15, 12))
    ax = fig.add_subplot(111, projection='3d')
    totals = Counter()
    for plane in ('z1', 'z2'):
        segments = []
        for record in routed:
            if str(record.get('plane')) != plane:
                continue
            polyline = route_polyline(record, step_flat=1.0, step_transition=0.1)
            if polyline is None:
                continue
            segments.append(polyline)
            totals[plane] += 1
        if segments:
            collection = Line3DCollection(segments, colors=PLANE_COLORS[plane],
                                          linewidths=0.25, alpha=0.45)
            ax.add_collection3d(collection, autolim=False)
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_zlim(-0.40, 0.70)
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.view_init(elev=26, azim=-58)
    handles = [Line2D([0], [0], color=PLANE_COLORS[plane], lw=1.4,
                      label=f'{plane}  ({totals.get(plane, 0)} routed)')
               for plane in ('z1', 'z2')]
    ax.legend(handles=handles, loc='upper right', fontsize=9)
    ax.set_title(f'All routed routes in true 3D — {len(routed)} of 1024 '
                 f'(Z1 interface z=0, Z2 interface z=0.5, 18 body layers '
                 f'-0.35..0.65 mm)')
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# (b) the 8 manual groups, one 3D subplot each
# ---------------------------------------------------------------------------
def plot_3d_manual_groups(run_dir, out_dir, manifest):
    routed, failed, _payload = load_routes(run_dir)
    assignment_rows = load_assignment(run_dir)
    name = '02_3d_manual_groups'
    if not routed and not failed:
        _skip(manifest, name, 'no route records')
        return None
    by_group = OrderedDict((group, []) for group in MANUAL_GROUP_LAYER)
    by_group_failed = Counter()
    for record in routed:
        group = route_group(record, assignment_rows)
        if group in by_group:
            polyline = route_polyline(record, step_flat=1.0, step_transition=0.1)
            if polyline is not None:
                by_group[group].append(polyline)
    for record in failed:
        group = route_group(record, assignment_rows)
        if group in by_group:
            by_group_failed[group] += 1
    fig = plt.figure(figsize=(18, 10))
    for index, (group, segments) in enumerate(by_group.items()):
        layer = MANUAL_GROUP_LAYER[group]
        z = float(common.PHYSICAL_LAYERS[layer])
        ax = fig.add_subplot(2, 4, index + 1, projection='3d')
        if segments:
            collection = Line3DCollection(segments, colors=GROUP_COLORS[group],
                                          linewidths=0.35, alpha=0.65)
            ax.add_collection3d(collection, autolim=False)
        ax.set_xlim(0.0, BOARD_MM)
        ax.set_ylim(0.0, BOARD_MM)
        ax.set_zlim(-0.40, 0.70)
        ax.view_init(elev=24, azim=-58)
        ax.set_title(f'{group}  L{layer} z={z:+.2f} mm\n'
                     f'routed {len(segments)} / failed {by_group_failed.get(group, 0)}',
                     fontsize=9)
        ax.tick_params(labelsize=6)
        ax.set_xlabel('X', fontsize=7)
        ax.set_ylabel('Y', fontsize=7)
        ax.set_zlabel('Z', fontsize=7)
    fig.suptitle('Manual groups (Z1-U1..U4 -> L2..L5, Z2-U1..U4 -> L10..L13): '
                 'routed routes only', fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# (c) layer stack section
# ---------------------------------------------------------------------------
def plot_layer_stack_section(run_dir, out_dir, manifest):
    name = '03_layer_stack_section'
    payload = _read_json(Path(run_dir) / 'physical_layer_stack.json')
    layers = common.PHYSICAL_LAYERS
    interface = {'z1': common.Z1_INTERFACE_MM, 'z2': common.Z2_INTERFACE_MM}
    fig, ax = plt.subplots(figsize=(11, 9))
    ax.axhspan(common.GLASS_Z_MIN_MM, common.GLASS_Z_MAX_MM, color='#dceefb',
               alpha=0.55, label='glass (z -0.35 .. +0.65 mm)')
    rows = []
    for layer_id, z in layers.items():
        group = LAYER_GROUP.get(layer_id)
        role = group if group else ('Z1 opposite' if layer_id in (6, 7)
                                    else 'Z2 adjacent / spare')
        color = GROUP_COLORS.get(group, '#7f7f7f')
        rows.append((float(z), f'L{layer_id}', f'{z:+.2f} mm', role, color))
    for z, label, ztext, role, color in sorted(rows):
        ax.axhline(z, color=color, lw=2.4)
        ax.text(0.02, z, f'{label}  {ztext}', va='center', ha='left',
                fontsize=9, color=color, weight='bold')
        ax.text(0.42, z, role, va='center', ha='left', fontsize=8, color='#333333')
    for plane, z in interface.items():
        ax.axhline(z, color=INTERFACE_COLOR, lw=3.0, linestyle='--')
        ax.text(0.02, z, f'{plane} interface  z={z:+.2f} mm', va='center',
                ha='left', fontsize=10, weight='bold', color=INTERFACE_COLOR)
    for name_group, layer_id in MANUAL_GROUP_LAYER.items():
        z = float(layers[layer_id])
        ax.plot([0.90], [z], marker='s', color=GROUP_COLORS[name_group], ms=8)
        ax.text(0.92, z, name_group, va='center', fontsize=8,
                color=GROUP_COLORS[name_group])
    ax.set_xlim(0.0, 1.05)
    ax.set_ylim(common.GLASS_Z_MIN_MM - 0.05, common.GLASS_Z_MAX_MM + 0.18)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_ylabel('z (mm)')
    title = 'Layer stack: 1 mm glass, 18 routing layers, 50 um minimum pitch'
    if isinstance(payload, dict):
        provenance = payload.get('provenance')
        if provenance:
            title += f'\nprovenance: {provenance} (simulation input, not confirmed process)'
    ax.set_title(title, fontsize=11)
    ax.legend(loc='lower right', fontsize=8)
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# layerwise 2D data loading (layerwise_routes/routes.json or routes_l3d fallback)
# ---------------------------------------------------------------------------
def _as_records(routes):
    """Layerwise ``routes`` may be a list or a {route_id: payload} dict."""
    if isinstance(routes, list):
        return routes
    if isinstance(routes, dict):
        records = []
        for key, value in routes.items():
            if not isinstance(value, dict):
                continue
            record = dict(value)
            if record.get('route_id') is None:
                try:
                    record['route_id'] = int(key)
                except (TypeError, ValueError):
                    record['route_id'] = key
            records.append(record)
        return records
    return []


def _iter_layerwise_entries(payload):
    """Yield (layer_id, records) from a layerwise routes payload (best effort)."""
    if not isinstance(payload, dict):
        return
    for key in ('layers', 'layer_routes'):
        block = payload.get(key)
        if isinstance(block, dict):
            for layer_key, value in block.items():
                if not isinstance(value, dict):
                    continue
                try:
                    layer_id = int(value.get('layer_id', layer_key))
                except (TypeError, ValueError):
                    continue
                yield layer_id, _as_records(value.get('routes'))
        elif isinstance(block, list):
            for value in block:
                if not isinstance(value, dict):
                    continue
                try:
                    layer_id = int(value.get('layer_id', value.get('layer')))
                except (TypeError, ValueError):
                    continue
                yield layer_id, _as_records(value.get('routes'))
    records = payload.get('routes')
    if isinstance(records, list):
        grouped = OrderedDict()
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                layer_id = int(record.get('layer_id', record.get('layer')))
            except (TypeError, ValueError):
                continue
            grouped.setdefault(layer_id, []).append(record)
        for layer_id, items in grouped.items():
            yield layer_id, items


def build_layerwise_2d(run_dir, routed, assignment_rows):
    """{layer_id: [dict(route_id, group, primitives)]} for 2D layer views."""
    run_dir = Path(run_dir)
    layerwise = OrderedDict()
    payload = _read_json(run_dir / 'layerwise_routes' / 'routes.json')
    if isinstance(payload, dict):
        for layer_id, records in _iter_layerwise_entries(payload):
            entries = layerwise.setdefault(layer_id, [])
            for record in records:
                if not isinstance(record, dict):
                    continue
                status = str(record.get('status') or 'routed').strip().lower()
                if status not in ('routed', 'ok', 'success', 'valid', 'accepted', 'done'):
                    continue
                primitives = record.get('primitives')
                if primitives is None:
                    primitives = []
                    for part in record.get('parts') or []:
                        if part.get('kind') == 'flat':
                            primitives.extend(part.get('primitives') or [])
                if not primitives:
                    continue
                route_id = record.get('route_id')
                entries.append(dict(route_id=route_id,
                                    group=route_group(record, assignment_rows),
                                    primitives=primitives))
    if layerwise:
        return layerwise, 'layerwise_routes/routes.json'
    # fallback: rebuild the per-layer 2D view from the final 3D route bodies
    for record in routed:
        layer_id = layer_of(record)
        if layer_id is None:
            continue
        primitives = []
        for part in record.get('parts') or []:
            if part.get('kind') == 'flat':
                try:
                    part_layer = int(part.get('layer_id'))
                except (TypeError, ValueError):
                    continue
                if part_layer == layer_id:
                    primitives.extend(part.get('primitives') or [])
        if not primitives:
            continue
        layerwise.setdefault(layer_id, []).append(
            dict(route_id=record.get('route_id'),
                 group=route_group(record, assignment_rows),
                 primitives=primitives))
    return layerwise, 'routes_l3d.json body flats (fallback)'


def _draw_layer(ax, entries, title, show_group_legend=False):
    used_groups = set()
    drawn = 0
    segments = []
    colors = []
    for entry in entries:
        group = entry.get('group') or ''
        color = GROUP_COLORS.get(group, OTHER_COLOR)
        used_groups.add(group)
        for prim in entry.get('primitives') or []:
            polyline = flat_prim_polyline(prim)
            if polyline and len(polyline) >= 2:
                segments.append(np.asarray(polyline, dtype=float))
                colors.append(color)
                drawn += 1
    if segments:
        collection = LineCollection(segments, colors=colors, linewidths=0.45,
                                    alpha=0.85)
        ax.add_collection(collection)
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=9)
    for spine in ax.spines.values():
        spine.set_linewidth(0.4)
    if show_group_legend:
        handles = [Line2D([0], [0], color=GROUP_COLORS[group], lw=1.2, label=group)
                   for group in MANUAL_GROUP_LAYER if group in used_groups]
        if handles:
            ax.legend(handles=handles, fontsize=6, loc='lower right')
    return drawn


# ---------------------------------------------------------------------------
# (d) per-layer 2D routing views
# ---------------------------------------------------------------------------
def plot_per_layer_2d(run_dir, out_dir, manifest):
    routed, _failed, _payload = load_routes(run_dir)
    assignment_rows = load_assignment(run_dir)
    name = '04_per_layer_2d'
    if not routed:
        _skip(manifest, name, 'no routed routes / routes_l3d.json missing')
        return None
    layerwise, source = build_layerwise_2d(run_dir, routed, assignment_rows)
    if not layerwise:
        _skip(manifest, name, 'no per-layer 2D geometry available')
        return None
    layer_ids = sorted(common.PHYSICAL_LAYERS)
    columns = 5
    rows = int(math.ceil(len(layer_ids) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 4.2 * rows))
    axes = np.atleast_1d(axes).ravel()
    for position, layer_id in enumerate(layer_ids):
        ax = axes[position]
        entries = layerwise.get(layer_id) or []
        z = float(common.PHYSICAL_LAYERS[layer_id])
        group = LAYER_GROUP.get(layer_id)
        title = f'L{layer_id}  z={z:+.2f} mm'
        if group:
            title += f'  ({group})'
        title += f'\n{len(entries)} routes'
        _draw_layer(ax, entries, title)
    for position in range(len(layer_ids), len(axes)):
        axes[position].axis('off')
    handles = [Line2D([0], [0], color=GROUP_COLORS[group], lw=1.4, label=group)
               for group in MANUAL_GROUP_LAYER]
    handles.append(Line2D([0], [0], color=OTHER_COLOR, lw=1.4, label='other routes'))
    fig.legend(handles=handles, loc='lower center', ncol=9, fontsize=8)
    fig.suptitle(f'Per-layer 2D routing views (source: {source}); colour = manual '
                 f'group, legal same-layer crossings allowed', fontsize=12)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# (e) the 8 manual layers in 2D detail
# ---------------------------------------------------------------------------
def plot_manual_2d_layers(run_dir, out_dir, manifest):
    routed, _failed, _payload = load_routes(run_dir)
    assignment_rows = load_assignment(run_dir)
    name = '05_manual_2d_layers'
    if not routed:
        _skip(manifest, name, 'no routed routes / routes_l3d.json missing')
        return None
    layerwise, source = build_layerwise_2d(run_dir, routed, assignment_rows)
    if not layerwise:
        _skip(manifest, name, 'no per-layer 2D geometry available')
        return None
    fig, axes = plt.subplots(2, 4, figsize=(22, 11))
    axes = np.atleast_1d(axes).ravel()
    for position, (group, layer_id) in enumerate(MANUAL_GROUP_LAYER.items()):
        ax = axes[position]
        entries = layerwise.get(layer_id) or []
        z = float(common.PHYSICAL_LAYERS[layer_id])
        _draw_layer(ax, entries, f'{group}  L{layer_id} z={z:+.2f} mm  '
                                 f'({len(entries)} routes)', show_group_legend=False)
        entry_file = Path(run_dir) / 'layerwise_routes' / f'layer_{layer_id}.json'
        if entry_file.exists():
            pass
    fig.suptitle(f'Manual layers 2D detail (source: {source}); each manual group '
                 f'is fixed to one layer', fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# (f) validation summary bars
# ---------------------------------------------------------------------------
def _bar(ax, labels, series, title, ylabel='routes'):
    x = np.arange(len(labels))
    width = 0.8 / max(1, len(series))
    for index, (label, values, color) in enumerate(series):
        ax.bar(x + index * width - 0.4 + width / 2, values, width,
               label=label, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.25)


def plot_validation_summary(run_dir, out_dir, manifest):
    name = '06_validation_summary'
    routed, failed, _payload = load_routes(run_dir)
    assignment_rows = load_assignment(run_dir)
    validation = _read_json(Path(run_dir) / 'validation.json')
    if not routed and not failed and not isinstance(validation, dict):
        _skip(manifest, name, 'no routes and no validation.json')
        return None
    planes = ['z1', 'z2']
    routed_by_plane = Counter()
    failed_by_plane = Counter()
    for record in routed:
        routed_by_plane[str(record.get('plane'))] += 1
    for record in failed:
        failed_by_plane[str(record.get('plane'))] += 1
    routed_by_group = Counter()
    failed_by_group = Counter()
    for record in routed:
        group = route_group(record, assignment_rows)
        if group:
            routed_by_group[group] += 1
    for record in failed:
        group = route_group(record, assignment_rows)
        if group:
            failed_by_group[group] += 1
    routed_by_layer = Counter()
    failed_by_layer = Counter()
    assigned_by_layer = Counter()
    for record in routed:
        layer_id = layer_of(record)
        if layer_id is not None:
            routed_by_layer[layer_id] += 1
    for record in failed:
        try:
            layer_id = int(record.get('target_layer'))
        except (TypeError, ValueError):
            layer_id = None
        if layer_id is not None:
            failed_by_layer[layer_id] += 1
    for row in assignment_rows.values():
        try:
            layer_id = int(str(row.get('physical_layer')).strip())
        except (TypeError, ValueError):
            continue
        assigned_by_layer[layer_id] += 1
    fig, axes = plt.subplots(1, 3, figsize=(22, 7))
    _bar(axes[0], planes,
         [('routed', [routed_by_plane.get(plane, 0) for plane in planes], '#2ca02c'),
          ('failed', [failed_by_plane.get(plane, 0) for plane in planes], '#d62728')],
         'Routes by plane')
    groups = list(MANUAL_GROUP_LAYER)
    _bar(axes[1], groups,
         [('routed', [routed_by_group.get(group, 0) for group in groups], '#2ca02c'),
          ('failed', [failed_by_group.get(group, 0) for group in groups], '#d62728')],
         'Manual groups (fixed layers)')
    layer_ids = sorted(common.PHYSICAL_LAYERS)
    _bar(axes[2], [f'L{layer}' for layer in layer_ids],
         [('assigned', [assigned_by_layer.get(layer, 0) for layer in layer_ids], '#1f77b4'),
          ('routed', [routed_by_layer.get(layer, 0) for layer in layer_ids], '#2ca02c'),
          ('failed', [failed_by_layer.get(layer, 0) for layer in layer_ids], '#d62728')],
         'Routes by body layer')
    caption = f'routed {len(routed)} / records {len(routed) + len(failed)}'
    if isinstance(validation, dict):
        caption += (f"   validator: geometry_pass={validation.get('geometry_pass')}, "
                    f"violations={validation.get('violation_count')}, "
                    f"min_3d_clearance={validation.get('min_3d_clearance_mm')} mm")
    fig.suptitle('Validation summary — ' + caption, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, out_dir / f'{name}.png', manifest, name)


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
FIGURES = OrderedDict([
    ('01_3d_all_routes', plot_3d_all_routes),
    ('02_3d_manual_groups', plot_3d_manual_groups),
    ('03_layer_stack_section', plot_layer_stack_section),
    ('04_per_layer_2d', plot_per_layer_2d),
    ('05_manual_2d_layers', plot_manual_2d_layers),
    ('06_validation_summary', plot_validation_summary),
])


def generate_plots(run_dir=None, out_dir=None, only=None):
    run_dir = Path(run_dir) if run_dir is not None else RUN_DIR
    out_dir = Path(out_dir) if out_dir is not None else run_dir / 'plots'
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(run_dir=str(run_dir), out_dir=str(out_dir),
                    generated_at=__import__('datetime').datetime.now()
                    .isoformat(timespec='seconds'),
                    figures=[], skipped=[], log=[])
    names = [name for name in FIGURES
             if only is None or name in set(only)]
    for name in names:
        try:
            FIGURES[name](run_dir, out_dir, manifest)
        except Exception as error:  # noqa: BLE001 - one figure must not kill the rest
            _skip(manifest, name, f'{type(error).__name__}: {error}')
            traceback.print_exc()
    manifest_path = out_dir / 'plots_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False,
                                        default=str) + '\n', encoding='utf-8')
    print(f'[plots] {len(manifest["figures"])} figures written, '
          f'{len(manifest["skipped"])} skipped -> {out_dir}', flush=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate the report plots.')
    parser.add_argument('--run-dir', default=str(RUN_DIR))
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--only', nargs='*', default=None,
                        help='only these figure names (default: all)')
    args = parser.parse_args(argv)
    manifest = generate_plots(args.run_dir, args.out_dir, args.only)
    return 0 if len(manifest['figures']) > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
