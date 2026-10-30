# -*- coding: utf-8 -*-
"""E1 figures. Every figure is drawn from real XYZ route data."""
from __future__ import annotations

import math
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from . import core as C

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

PLANE_COLORS = {0.0: '#1f6fd6', 0.5: '#e07b1a'}
ROUTING_COLORS = ['#2f9e44', '#7048e8', '#e03131', '#0c8599',
                  '#f08c00', '#c2255c', '#5c940d', '#1864ab']
X_RANGE = (0.0, 150.0)
Y_RANGE = (0.0, 150.0)


def color_for_z(z):
    z = round(float(z), 6)
    if z in PLANE_COLORS:
        return PLANE_COLORS[z]
    keys = sorted(set(C.LAYER_Z.values()))
    index = keys.index(z) if z in keys else 0
    return ROUTING_COLORS[index % len(ROUTING_COLORS)]


def sample_primitives(primitives, n_arc=16):
    xs, ys = [], []
    for prim in primitives:
        if prim.get('kind') == 'line':
            p0, p1 = prim['p0'], prim['p1']
            xs.extend([p0[0], p1[0]])
            ys.extend([p0[1], p1[1]])
        elif prim.get('kind') == 'arc':
            center = prim['center']
            radius = float(prim['radius'])
            theta = np.linspace(float(prim['start_angle']),
                                float(prim['start_angle']) + float(prim['sweep']),
                                n_arc)
            xs.extend((center[0] + radius * np.cos(theta)).tolist())
            ys.extend((center[1] + radius * np.sin(theta)).tolist())
    return np.asarray(xs), np.asarray(ys)


def flat_primitives_at(record, z):
    out = []
    for part in record.get('parts') or []:
        if part['kind'] == 'flat' and abs(float(part['z_mm']) - z) <= 1e-9:
            out.extend(part['primitives'])
    return out


def _style_xy(ax):
    ax.set_xlim(*X_RANGE)
    ax.set_ylim(*Y_RANGE)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.grid(alpha=0.12)


def draw_flat_xy(ax, record, z, color, lw=0.35, alpha=0.35, linestyle='-'):
    prims = flat_primitives_at(record, z)
    if not prims:
        return False
    xs, ys = sample_primitives(prims)
    if not len(xs):
        return False
    ax.plot(xs, ys, color=color, lw=lw, alpha=alpha, linestyle=linestyle)
    return True


def draw_3d(ax, records, title, only_transitions=False, highlight_ids=None,
            highlight_color='#e03131'):
    highlight_ids = set(highlight_ids or ())
    for record in records:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part['kind'] == 'flat':
                if only_transitions:
                    continue
                xs, ys = sample_primitives(part['primitives'])
                if not len(xs):
                    continue
                color = (highlight_color if rid in highlight_ids
                         else color_for_z(part['z_mm']))
                width = 1.0 if rid in highlight_ids else 0.3
                alpha = 0.9 if rid in highlight_ids else 0.35
                ax.plot(xs, ys, np.full(len(xs), float(part['z_mm'])),
                        color=color, lw=width, alpha=alpha)
            else:
                p0, p1 = part['start'], part['end']
                color = (highlight_color if rid in highlight_ids
                         else ('#e8590c' if only_transitions else '#8c8c8c'))
                ax.plot([p0[0], p1[0]], [p0[1], p1[1]], [part['z0'], part['z1']],
                        color=color,
                        lw=0.9 if only_transitions or rid in highlight_ids else 0.35,
                        alpha=0.85 if only_transitions or rid in highlight_ids else 0.3)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_zlim(-0.05, max(C.LAYER_Z.values()) + 0.1)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_zlabel('z (mm)')
    ax.view_init(elev=24, azim=-58)
    ax.set_title(title, fontsize=9.5, pad=6)


def plot_layer(ax, records, z, title, highlight_ids=None,
               event_points=None):
    highlight_ids = set(highlight_ids or ())
    drawn = 0
    for record in records:
        rid = int(record['route_id'])
        if rid in highlight_ids:
            if draw_flat_xy(ax, record, z, '#e03131', lw=1.0, alpha=0.9):
                drawn += 1
        else:
            if draw_flat_xy(ax, record, z, color_for_z(z), lw=0.35, alpha=0.3):
                drawn += 1
    if event_points:
        ax.plot([p[0] for p in event_points], [p[1] for p in event_points],
                'x', color='#c92a2a', ms=3.2, mew=0.8)
    _style_xy(ax)
    ax.set_title(title, fontsize=8.6)


def make_contact_sheet(figdir, names, out_name='all_layers_contact_sheet.png',
                       thumb=(760, 640), cols=3):
    from PIL import Image, ImageDraw, ImageFont
    figdir = C.ensure_dir(figdir)
    images = [Image.open(figdir / name).convert('RGB') for name in names]
    w, h = thumb
    rows = (len(images) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * w + 40, rows * (h + 32) + 20), 'white')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 20)
    except Exception:
        font = ImageFont.load_default()
    for index, (image, name) in enumerate(zip(images, names)):
        image.thumbnail((w - 8, h - 8), Image.LANCZOS)
        row, col = divmod(index, cols)
        x = 10 + col * w
        y = 10 + row * (h + 32)
        canvas.paste(image, (x, y))
        draw.text((x + 8, y + h - 18), name, font=font, fill='#333333')
    path = figdir / out_name
    canvas.save(path, optimize=True)
    return path


def _save(fig, path, dpi=170):
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def layer_figure_names():
    names = [('03_L1_Z1.png', 'L1-Z1'), ('04_L1_Z2.png', 'L1-Z2')]
    for layer in C.LAYERS:
        names.append((f'{5 + layer - 2:02d}_L{layer}.png', f'L{layer}'))
    return names


def standard_figures(folder, records, ctx, name, baseline_records=None,
                     highlight_ids=None, diagnostic=False, note='',
                     analysis=None, baseline_analysis=None):
    """The mandatory figure set for a complete 1024-route solution."""
    folder = C.ensure_dir(folder)
    figdir = C.ensure_dir(folder / 'figures')
    analysis = analysis or C.audit(records, ctx)
    if baseline_records is not None and baseline_analysis is None:
        baseline_analysis = C.audit(baseline_records, ctx)
    summary_stats = C.bar(records)
    n = len(records)
    banner = 'DIAGNOSTIC ONLY (Z2 occupancy removed) ' if diagnostic else ''
    title_prefix = f'{banner}{name}'

    # 01 overall 3D
    fig = plt.figure(figsize=(10, 8.5))
    ax = fig.add_subplot(111, projection='3d')
    draw_3d(ax, records,
            f'{title_prefix}: {n}/1024 routes, unique crossings '
            f'{analysis["n_unique_pairs"]}, length {summary_stats["total_length_mm"]:.0f} mm')
    fig.tight_layout()
    fig.savefig(figdir / '01_overall_3d.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    # 02 overall XY
    fig, ax = plt.subplots(figsize=(8, 8))
    for record in records:
        for part in record.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            xs, ys = sample_primitives(part['primitives'])
            if len(xs):
                ax.plot(xs, ys, color=color_for_z(part['z_mm']), lw=0.3,
                        alpha=0.22)
    _style_xy(ax)
    ax.set_title(f'{title_prefix} XY projection (all physical layers)')
    _save(fig, figdir / '02_overall_xy.png', dpi=200)

    # 03..10 per physical layer
    layer_names = layer_figure_names()
    for fname, label in layer_names:
        z = 0.0 if label == 'L1-Z1' else (0.5 if label == 'L1-Z2' else
                                          C.LAYER_Z[int(label[1:])])
        info = analysis['per_height'].get(round(z, 6),
                                          dict(routes=0, segments=0, pairs=0,
                                               events=0))
        points = [(event['x'], event['y']) for event in analysis['events']
                  if abs(event['z'] - z) < 1e-9]
        fig, ax = plt.subplots(figsize=(7.4, 7.2))
        plot_layer(ax, records, z,
                   f'{label}  z={z:.2f} mm | unique routes={info["routes"]} '
                   f'segments={info["segments"]} crossing_pairs={info["pairs"]} '
                   f'events={info["events"]}', highlight_ids=highlight_ids,
                   event_points=points)
        _save(fig, figdir / fname)
    make_contact_sheet(figdir, [fname for fname, _ in layer_names])

    # transitions 3D
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    draw_3d(ax, records, f'{title_prefix}: 3D S transitions ({summary_stats["transitions"]} transitions)',
            only_transitions=True)
    fig.tight_layout()
    fig.savefig(figdir / 'transition_windows_3d.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    fig.savefig(figdir / 'transitions_3d.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    # z1 hotspots
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    z1_events = [event for event in analysis['events'] if event['z'] == 0.0]
    if z1_events:
        hexbin = ax.hexbin([event['x'] for event in z1_events],
                           [event['y'] for event in z1_events],
                           gridsize=38, cmap='Reds', mincnt=1)
        fig.colorbar(hexbin, ax=ax, label='crossing events')
        ax.set_title(f'{title_prefix}: Z1 (z=0) crossing hotspots, '
                     f'{len(z1_events)} events / {analysis["z1_pairs"]} pairs',
                     fontsize=9.5)
    else:
        ax.text(75, 75, 'no Z1 crossings', ha='center', va='center')
        ax.set_title(f'{title_prefix}: Z1 hotspots')
    _style_xy(ax)
    _save(fig, figdir / 'edge_crossing_hotspots.png', dpi=200)

    # z1 before/after + z2 before/after
    if baseline_records is not None:
        before_events = baseline_analysis['events']
        after_events = analysis['events']
        fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.4))
        labels = ['global unique', 'Z1 pairs', 'Z2 pairs', 'high-layer']
        before = [baseline_analysis['n_unique_pairs'],
                  baseline_analysis['z1_pairs'], baseline_analysis['z2_pairs'],
                  baseline_analysis['high_pairs']]
        after = [analysis['n_unique_pairs'], analysis['z1_pairs'],
                 analysis['z2_pairs'], analysis['high_pairs']]
        positions = np.arange(len(labels))
        axes[0].bar(positions - 0.2, before, 0.4, label='BASE', color='#868e96')
        axes[0].bar(positions + 0.2, after, 0.4, label=name, color='#2f9e44')
        axes[0].set_xticks(positions)
        axes[0].set_xticklabels(labels, fontsize=8)
        axes[0].legend(fontsize=8)
        axes[0].set_title('crossing comparison')
        for events, title, color in (
                (before_events, 'BASE z=0', '#868e96'),
                (after_events, f'{name} z=0', '#e03131')):
            z1 = [event for event in events if event['z'] == 0.0]
            axes[1].scatter([event['x'] for event in z1],
                            [event['y'] for event in z1], s=3, alpha=0.3,
                            color=color, label=title)
        axes[1].set_xlim(*X_RANGE)
        axes[1].set_ylim(*Y_RANGE)
        axes[1].set_aspect('equal')
        axes[1].legend(fontsize=7)
        axes[1].set_title('Z1 crossing positions')
        _save(fig, figdir / 'z1_before_after.png', dpi=200)

        fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.4))
        for events, title, color in (
                (before_events, 'BASE z=0.5', '#868e96'),
                (after_events, f'{name} z=0.5', '#e07b1a')):
            z2 = [event for event in events if event['z'] == 0.5]
            axes[0].scatter([event['x'] for event in z2],
                            [event['y'] for event in z2], s=3, alpha=0.35,
                            color=color, label=title)
        axes[0].set_xlim(*X_RANGE)
        axes[0].set_ylim(*Y_RANGE)
        axes[0].set_aspect('equal')
        axes[0].legend(fontsize=7)
        axes[0].set_title('Z2 interface crossing positions')
        before_cat = _category_counts(baseline_analysis)
        after_cat = _category_counts(analysis)
        keys = ['adjacent x opposite(z2)', 'opposite x opposite(z2)']
        axes[1].bar(np.arange(2) - 0.2, [before_cat.get(k, 0) for k in keys],
                    0.4, color='#868e96', label='BASE')
        axes[1].bar(np.arange(2) + 0.2, [after_cat.get(k, 0) for k in keys],
                    0.4, color='#e07b1a', label=name)
        axes[1].set_xticks(np.arange(2))
        axes[1].set_xticklabels(['adjacent-opposite', 'opposite-opposite'],
                                fontsize=8)
        axes[1].legend(fontsize=8)
        axes[1].set_title('Z2 crossing category')
        _save(fig, figdir / 'z2_before_after.png', dpi=200)

    # z1 unlifted routes highlight (current solution's flat z1 opposite routes)
    by_id = {int(record['route_id']): record for record in records}
    flat_pairs = []
    for entry in ctx.pair_dirs:
        try:
            layers = [ctx.route_target_layer(by_id[rid]) for rid in entry['rids']]
        except KeyError:
            continue
        if max(layers) <= 1:
            flat_pairs.append(entry)
    flat_ids = [rid for entry in flat_pairs for rid in entry['rids']]
    fig, ax = plt.subplots(figsize=(7.6, 7.2))
    for record in records:
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or part['z_mm'] != 0.0:
                continue
            rid = int(record['route_id'])
            xs, ys = sample_primitives(part['primitives'])
            if not len(xs):
                continue
            if rid in flat_ids:
                ax.plot(xs, ys, color='#e03131', lw=0.9, alpha=0.75)
            else:
                ax.plot(xs, ys, color='#adb5bd', lw=0.25, alpha=0.25)
    _style_xy(ax)
    ax.set_title(f'{title_prefix}: Z1 opposite routes still flat on L1-Z1 '
                 f'({len(flat_ids)} routes / {len(flat_pairs)} C2 pairs)',
                 fontsize=9.5)
    _save(fig, figdir / 'z1_unlifted_routes.png', dpi=200)

    # z1/z2 transition near-miss map
    _transition_conflict_figure(figdir, records, ctx, title_prefix)

    if note:
        (figdir / 'FIGURE_NOTE.txt').write_text(note, encoding='utf-8')
    return figdir


def _category_counts(analysis):
    counts = Counter()
    for event in analysis['events']:
        if event['z'] != 0.5:
            continue
        cats = tuple(sorted((event['cat_a'], event['cat_b'])))
        if 'adjacent_z2' in cats:
            counts['adjacent x opposite(z2)'] += 1
        elif all(cat.startswith('opposite_z2') for cat in cats):
            counts['opposite x opposite(z2)'] += 1
    return counts


def transition_near_misses(records, ctx, threshold=0.2):
    """3D near misses (< threshold) between transitions and other routes' flats."""
    world = ctx.world(records)
    clearance_world = world.clearance_world
    hits = []
    for record in records:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part['kind'] != 'transition':
                continue
            from four_side_1024.fsd25d import path3d as P3
            samples = P3.transition_samples(part, step=0.25)
            for sample in samples:
                for entry in clearance_world._query_flats(sample[0], sample[1]):
                    if int(entry['route_id']) == rid:
                        continue
                    from four_side_1024.fsd25d.world25d import (
                        point_primitive_distance_2d)
                    distance2 = point_primitive_distance_2d(sample, entry['prim'])
                    if distance2 >= threshold:
                        continue
                    distance3 = math.hypot(distance2, sample[2] - entry['z'])
                    if distance3 < threshold:
                        hits.append(dict(route_id=rid, other_route=int(entry['route_id']),
                                         x=float(sample[0]), y=float(sample[1]),
                                         z=float(sample[2]), distance_mm=distance3))
    return hits


def _transition_conflict_figure(figdir, records, ctx, title_prefix,
                                threshold=0.2):
    hits = transition_near_misses(records, ctx, threshold)
    fig, ax = plt.subplots(figsize=(7.6, 7.2))
    categories = Counter()
    for hit in hits:
        pair = {ctx.plane_of(hit['route_id']), ctx.plane_of(hit['other_route'])}
        categories['Z1 transition vs Z2 route' if pair == {'z1', 'z2'}
                   else ('Z1 self-plane' if pair == {'z1'} else 'Z2 self-plane')] += 1
    colors = {'Z1 transition vs Z2 route': '#e03131',
              'Z1 self-plane': '#1f6fd6', 'Z2 self-plane': '#e07b1a'}
    for key, value in categories.items():
        group = [hit for hit in hits
                 if ('Z1 transition vs Z2 route' if {ctx.plane_of(hit['route_id']),
                                                     ctx.plane_of(hit['other_route'])} == {'z1', 'z2'}
                      else ('Z1 self-plane' if {ctx.plane_of(hit['route_id']),
                                                ctx.plane_of(hit['other_route'])} == {'z1'}
                            else 'Z2 self-plane')) == key]
        ax.scatter([hit['x'] for hit in group], [hit['y'] for hit in group],
                   s=6, alpha=0.5, color=colors.get(key, '#495057'),
                   label=f'{key} ({value})')
    _style_xy(ax)
    ax.legend(fontsize=7)
    ax.set_title(f'{title_prefix}: Z1/Z2 transition near misses '
                 f'(<{threshold} mm 3D), {len(hits)} samples', fontsize=9.5)
    _save(fig, figdir / 'z1_z2_transition_conflicts.png', dpi=200)
    return hits


def z1_blocking_figure(folder, ctx, blocking_rows, records, name,
                       highlight_pairs=None):
    """Highlight the blocking routes found by E1-A/B on top of a solution."""
    figdir = C.ensure_dir(C.ensure_dir(folder) / 'figures')
    blocking_ids = sorted({int(row['route_id']) for row in blocking_rows})
    fig, ax = plt.subplots(figsize=(7.8, 7.4))
    for record in records:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            xs, ys = sample_primitives(part['primitives'])
            if not len(xs):
                continue
            if rid in blocking_ids:
                ax.plot(xs, ys, color='#e03131', lw=0.8, alpha=0.6)
            else:
                ax.plot(xs, ys, color='#ced4da', lw=0.2, alpha=0.22)
    _style_xy(ax)
    ax.set_title(f'{name}: routes that block Z1 early lift '
                 f'({len(blocking_ids)} blocking routes)', fontsize=9.5)
    _save(fig, figdir / 'z1_blocking_routes.png', dpi=200)
    return figdir / 'z1_blocking_routes.png'


def four_side_zoom(folder, records, name, ctx=None, highlight_ids=None,
                   tag='four_side_zoom'):
    """Four local zooms (N / S / E / W near-port bands)."""
    figdir = C.ensure_dir(C.ensure_dir(folder) / 'figures')
    highlight_ids = set(highlight_ids or ())
    windows = {'N band (y>=128)': (0, 150, 128, 150),
               'S band (y<=22)': (0, 150, 0, 22),
               'E band (x>=128)': (128, 150, 0, 150),
               'W band (x<=22)': (0, 22, 0, 150)}
    fig, axes = plt.subplots(2, 2, figsize=(12.6, 12.2))
    for ax, (label, (x0, x1, y0, y1)) in zip(axes.ravel(), windows.items()):
        for record in records:
            rid = int(record['route_id'])
            for part in record.get('parts') or []:
                if part['kind'] != 'flat':
                    continue
                xs, ys = sample_primitives(part['primitives'])
                if not len(xs):
                    continue
                color = '#e03131' if rid in highlight_ids else color_for_z(part['z_mm'])
                alpha = 0.85 if rid in highlight_ids else 0.3
                width = 0.8 if rid in highlight_ids else 0.3
                ax.plot(xs, ys, color=color, lw=width, alpha=alpha)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect('equal')
        ax.set_title(label, fontsize=9)
        ax.grid(alpha=0.12)
    fig.suptitle(f'{name}: four-side near-port detail', fontsize=11)
    _save(fig, figdir / f'{tag}.png', dpi=180)
    return figdir / f'{tag}.png'
