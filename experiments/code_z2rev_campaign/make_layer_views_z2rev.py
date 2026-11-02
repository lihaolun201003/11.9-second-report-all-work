# -*- coding: utf-8 -*-
"""Improved per-layer routing views (cleaner geometry, correct counts)."""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV'
BEST = CAMPAIGN / 'best_solution'
OUT = BEST / 'figures' / 'per_layer_view'
BOARD = 150.0
KIND_COLORS = {'opposite': '#1f6fd6', 'same': '#e07b1a', 'adjacent': '#2f9e44'}
KIND_LABEL = {'opposite': 'opposite connections', 'same': 'same-side U',
              'adjacent': 'adjacent connections'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def primitive_polyline(primitive):
    from four_side_1024.v3c4 import lift_cross_run as LCR
    if primitive.get('kind') == 'line':
        return [tuple(primitive['p0'])[:2], tuple(primitive['p1'])[:2]]
    sampled = LCR._sample_primitive(dict(primitive), step_deg=2.0)
    if sampled is None:
        return []
    return [(float(x), float(y)) for x, y in sampled]


def transition_endpoints(part):
    """Both physical endpoints (start/end) of an S transition."""
    start = tuple(part['start'])[:2]
    direction = part['direction']
    norm = math.hypot(direction[0], direction[1]) or 1.0
    dz = abs(float(part['z1']) - float(part['z0']))
    footprint, _theta = 0.0, 0.0
    ratio = 1.0 - dz / 30.0
    theta = math.acos(max(-1.0, min(1.0, ratio)))
    footprint = 30.0 * math.sin(theta)
    end = (start[0] + direction[0] / norm * footprint,
           start[1] + direction[1] / norm * footprint)
    return start, end, footprint


def build_layer_data(payload):
    flat = defaultdict(list)          # z -> list of dict(polyline, route, kind)
    routes_by_layer = defaultdict(set)
    endpoint_markers = defaultdict(list)  # z -> [(x, y, kind_of_transition)]
    transitions = []
    routed = [record for record in payload['routes']
              if record.get('status') == 'routed']
    records = {int(record['route_id']): record for record in routed}
    for record in routed:
        rid = int(record['route_id'])
        kind = record.get('relation', 'opposite')
        for part in record.get('parts') or []:
            if part.get('kind') == 'flat':
                z = round(float(part['z_mm']), 6)
                for primitive in part.get('primitives') or []:
                    polyline = primitive_polyline(primitive)
                    if len(polyline) >= 2:
                        flat[z].append(dict(polyline=polyline, route=rid,
                                            kind=kind))
                        routes_by_layer[z].add(rid)
            elif part.get('kind') == 'transition':
                transitions.append(part)
                start, end, _foot = transition_endpoints(part)
                z0 = round(float(part['z0']), 6)
                z1 = round(float(part['z1']), 6)
                endpoint_markers[z0].append((start[0], start[1],
                                             'up' if z1 > z0 else 'down'))
                endpoint_markers[z1].append((end[0], end[1],
                                             'down' if z1 > z0 else 'up'))
    return dict(flat=flat, routes_by_layer=routes_by_layer,
                endpoint_markers=endpoint_markers,
                transitions=transitions, records=records, routed=routed)


def draw_context(ax, flat):
    for z in (0.0, 0.5):
        polylines = [item['polyline'] for item in flat.get(z) or []]
        if not polylines:
            continue
        ax.add_collection(LineCollection(polylines, colors='#adb5bd',
                                         linewidths=0.10, alpha=0.10,
                                         zorder=1))


def draw_layer(ax, z, data, dense_context=True, annotate=False):
    flat = data['flat']
    if dense_context:
        draw_context(ax, flat)
    items = flat.get(z) or []
    by_kind = defaultdict(list)
    for item in items:
        by_kind[item['kind']].append(item['polyline'])
    for kind in ('adjacent', 'same', 'opposite'):
        if by_kind.get(kind):
            ax.add_collection(LineCollection(
                by_kind[kind], colors=KIND_COLORS[kind], linewidths=0.85,
                alpha=0.9, zorder=3, label=KIND_LABEL[kind]))
    markers = data['endpoint_markers'].get(round(z, 6)) or []
    if markers:
        points = np.asarray([(x, y) for x, y, _kind in markers])
        ax.scatter(points[:, 0], points[:, 1], s=5, c='#e03131',
                   alpha=0.75, zorder=4, label='transition on this layer')
    if annotate:
        seen = set()
        for item in items:
            if item['route'] in seen:
                continue
            seen.add(item['route'])
            if len(seen) > 40:
                break
            polyline = item['polyline']
            ax.text(polyline[0][0], polyline[0][1], str(item['route']),
                    fontsize=2.8, color='#212529', zorder=5)
    ax.add_patch(Rectangle((0, 0), BOARD, BOARD, fill=False, lw=1.0,
                           color='#343a40'))
    ax.set_xlim(-2, BOARD + 2)
    ax.set_ylim(-2, BOARD + 2)
    ax.set_aspect('equal')
    ax.grid(alpha=0.10)
    routes = len(data['routes_by_layer'].get(round(z, 6)) or set())
    transitions_here = len(markers)
    layer_id = int(round((z - 0.65) / 0.15)) + 2 if z >= 0.65 else None
    label = f'L{layer_id}  z={z:.2f} mm' if layer_id else f'z={z:.2f} mm'
    ax.set_title(f'{label} | {routes} routes | {len(items)} primitives | '
                 f'{transitions_here} transition endpoints', fontsize=8.5)
    return dict(z_mm=z, layer_id=layer_id, routes=routes,
                flat_primitives=len(items),
                transition_endpoints=transitions_here)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    payload = read_json(BEST / 'routes_l3d.json')
    data = build_layer_data(payload)
    z_levels = sorted(data['routes_by_layer'])
    print('[layer-views] layers:', z_levels, flush=True)
    table = []
    for z in z_levels:
        fig, ax = plt.subplots(figsize=(7.0, 6.8))
        info = draw_layer(ax, z, data,
                          dense_context=z not in (0.0, 0.5),
                          annotate=z >= 0.65)
        if z in (0.0, 0.5):
            handles, labels = ax.get_legend_handles_labels()
            ax.legend(handles, labels, fontsize=6.5, loc='lower right')
        fig.tight_layout()
        fig.savefig(OUT / f'layer_z{z:.2f}.png', dpi=185)
        plt.close(fig)
        table.append(info)
    # --- high-layer contact sheet -------------------------------------
    high = [z for z in z_levels if z >= 0.65]
    cols = 4
    rows = int(math.ceil(len(high) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 4.15 * rows))
    axes = np.atleast_2d(axes)
    for index, ax in enumerate(axes.ravel()):
        if index >= len(high):
            ax.axis('off')
            continue
        draw_layer(ax, high[index], data, dense_context=True, annotate=False)
        ax.tick_params(labelsize=5)
        ax.set_xlabel('x (mm)', fontsize=5.5)
        ax.set_ylabel('y (mm)', fontsize=5.5)
    fig.suptitle('Best legal 15L solution, high routing layers '
                 '(L2 z=0.65 mm … L15 z=2.60 mm)\n'
                 'grey = interface context (Z1 z=0 / Z2 z=0.5); '
                 'red dots = transitions that start/end on this layer',
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    contact_high = BEST / 'figures' / 'layer_contact_sheet_high.png'
    fig.savefig(contact_high, dpi=185)
    plt.close(fig)
    # --- interface contact sheet --------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 7.2))
    for ax, z in zip(axes, (0.0, 0.5)):
        draw_layer(ax, z, data, dense_context=False)
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles, labels, fontsize=7, loc='lower right')
    fig.suptitle('Best legal 15L solution, dense interface planes '
                 '(Z1 ports z=0 / Z2 ports z=0.5)', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    contact_interface = BEST / 'figures' / 'layer_contact_sheet_interface.png'
    fig.savefig(contact_interface, dpi=185)
    plt.close(fig)
    (BEST / 'per_layer_view_summary.json').write_text(
        json.dumps(dict(schema='per_layer_views_v2', layers=table,
                        contact_sheets=dict(
                            interface=str(contact_interface),
                            high=str(contact_high))),
                   ensure_ascii=False, indent=1), encoding='utf-8')
    print('[layer-views] done')
    for row in table:
        print(row)


if __name__ == '__main__':
    main()
