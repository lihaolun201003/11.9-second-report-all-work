# -*- coding: utf-8 -*-
"""Step 4 - analysis plots (matplotlib, Agg backend, no GUI needed).

(a) one 2D figure per physical height with the real flat geometry and the
    crossing points marked               -> plots/plane_<label>_z<png>
(b) global crossing hotspot density map  -> plots/crossing_hotspot_density.png
(c) top-10 crossing routes vs the rest    -> plots/top10_crossing_routes.png
(d) per-route crossing histogram         -> plots/per_route_crossing_histogram.png
(e) per-plane crossing bar chart          -> plots/per_plane_crossings.png
(f) family-pair crossing matrix heatmap   -> plots/family_pair_matrix.png
(g) L9 vs L15 real geometry comparison    -> plots/anomaly_L9_vs_L15.png
plus two diagnostic figures (topology vs actual, crossing-angle histogram).
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_common as AC

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

SCHEMA_VERSION = '1.0.0'
DPI = 120

FAMILY_COLORS = {}
_PALETTE = plt.get_cmap('tab20').colors


def family_color_map():
    if FAMILY_COLORS:
        return FAMILY_COLORS
    order = [family for family in AC.FAMILY_ORDER]
    for index, family in enumerate(order):
        FAMILY_COLORS[family] = _PALETTE[index % len(_PALETTE)]
    return FAMILY_COLORS


def load_all():
    planes = AC.load_planes()
    meta = {plane['plane_id']: plane for plane in planes.values()}
    table = AC.build_route_table(planes)
    raw = AC.read_json(AC.WORK_DIR / 'crossings.json')
    analysis = AC.read_json(AC.OUT_DIR / 'crossing_analysis.json')
    routes = AC.load_routes_payload()['routes']
    groups = AC.group_flats_by_height(routes)
    return planes, meta, table, raw, analysis, groups


def short_draw(groups, z_key, table, ax, colors, linewidth=0.8, alpha=0.9,
               route_filter=None, highlight=None):
    """Draw every flat part at one physical height."""
    drawn = 0
    for rid, prims in sorted(groups[z_key].items()):
        if route_filter is not None and not route_filter(rid):
            continue
        rec = table[rid]
        color = colors.get(rec['family'], (0.6, 0.6, 0.6, 1.0))
        points = AC.polyline_of(prims)
        if len(points) < 2:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        if highlight is not None and rid == highlight:
            ax.plot(xs, ys, color='#d62728', linewidth=2.2, alpha=1.0, zorder=6)
        else:
            ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha,
                    zorder=2)
        drawn += 1
    return drawn


def plane_figures(planes, meta, table, raw, groups, colors):
    crossings_by_z = defaultdict(list)
    for event in raw['crossings']:
        crossings_by_z[round(event['z_mm'], 9)].append(event)
    made = []
    for plane in sorted(planes.values(), key=lambda p: p['z_mm']):
        pid = plane['plane_id']
        z = round(plane['z_mm'], 9)
        prim_groups = groups.get(z)
        if not prim_groups:
            continue
        fig, ax = plt.subplots(figsize=(8.2, 8.2))
        n_routes = short_draw(groups, z, table, ax, colors)
        events = crossings_by_z.get(z, [])
        if events:
            ax.scatter([event['x_mm'] for event in events],
                       [event['y_mm'] for event in events],
                       marker='x', s=34, linewidths=1.1, color='red',
                       zorder=9, label='%d crossings' % len(events))
        ax.set_xlim(-2, 152)
        ax.set_ylim(-2, 152)
        ax.set_aspect('equal')
        ax.set_xlabel('x (mm)')
        ax.set_ylabel('y (mm)')
        title = ('%s  z=%+.3f mm  kind=%s   flat routes=%d  crossings=%d'
                 % (plane['label'], plane['z_mm'], plane['kind'], n_routes,
                    len(events)))
        ax.set_title(title, fontsize=10)
        ax.grid(True, linewidth=0.25, alpha=0.4)
        # family legend (only families present at this height)
        present = sorted({table[rid]['family'] for rid in prim_groups})
        handles = [Line2D([0], [0], color=colors[f], linewidth=2, label=f)
                   for f in present]
        if handles:
            ax.legend(handles=handles, fontsize=6.2, loc='upper right',
                      framealpha=0.85, ncol=2)
        if events:
            ax.legend(fontsize=7, loc='lower right')
        safe = plane['label'].replace('/', '_')
        path = AC.PLOTS_DIR / ('plane_%02d_%s_z%+.3f.png'
                               % (pid, safe, plane['z_mm']))
        fig.tight_layout()
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        made.append(path)
    print('[step4] plane figures:', len(made))
    return made


def hotspot_figure(raw):
    xs = np.array([event['x_mm'] for event in raw['crossings']])
    ys = np.array([event['y_mm'] for event in raw['crossings']])
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 6.6))
    ax = axes[0]
    bins = np.linspace(0, 150, 61)
    hist, xedges, yedges = np.histogram2d(xs, ys, bins=[bins, bins])
    image = ax.imshow(hist.T, origin='lower', extent=[0, 150, 0, 150],
                      cmap='inferno', aspect='equal')
    fig.colorbar(image, ax=ax, label='crossing events per 2.5 mm cell')
    ax.set_title('Global crossing hotspot density, all 21 heights merged\n'
                 '(%d events / %d pairs)' % (len(xs),
                                          AC.REFERENCE_TOTALS['crossing_pairs']))
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    # per-height hotspot strip: fraction of events per height, cumulative
    ax2 = axes[1]
    by_z = Counter(round(event['z_mm'], 3) for event in raw['crossings'])
    zs = sorted(by_z)
    ax2.barh(['%+.2f' % z for z in zs], [by_z[z] for z in zs], color='#1f77b4')
    for index, z in enumerate(zs):
        ax2.text(by_z[z] + 10, index, '%d' % by_z[z], va='center', fontsize=7)
    ax2.set_xlabel('crossing events')
    ax2.set_ylabel('physical height z (mm)')
    ax2.set_title('Crossing events per physical height')
    ax2.grid(True, axis='x', linewidth=0.25, alpha=0.4)
    fig.tight_layout()
    path = AC.PLOTS_DIR / 'crossing_hotspot_density.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def top_routes_figure(analysis, meta, table, groups, colors):
    per_route = {row['route_id']: row for row in analysis['per_route']}
    top = sorted(analysis['per_route'],
                 key=lambda row: -row['crossings_total'])[:10]
    fig, axes = plt.subplots(2, 5, figsize=(20.0, 8.6))
    axes = axes.ravel()
    for index, row in enumerate(top):
        ax = axes[index]
        rid = row['route_id']
        rec = table[rid]
        pid = rec['target_plane']
        z = round(meta[pid]['z_mm'], 9)
        prim_groups = groups[z]
        # faint context: all other routes on this height
        for other in prim_groups:
            if other == rid:
                continue
            points = AC.polyline_of(prim_groups[other])
            if len(points) < 2:
                continue
            ax.plot([p[0] for p in points], [p[1] for p in points],
                    color='0.75', linewidth=0.35, alpha=0.6, zorder=1)
        short_draw(groups, z, table, ax, colors, route_filter=lambda r: r == rid,
                   highlight=rid)
        events = [event for event in analysis_crossings_cache['all']
                  if rid in (event['route_a'], event['route_b'])]
        if events:
            ax.scatter([event['x_mm'] for event in events],
                       [event['y_mm'] for event in events],
                       marker='x', s=22, linewidths=0.9, color='red', zorder=9)
        ax.set_xlim(-2, 152)
        ax.set_ylim(-2, 152)
        ax.set_aspect('equal')
        ax.set_title('route %d  %s\n%s  crossings=%d'
                     % (rid, rec['family'], rec['target_plane_label'],
                        row['crossings_total']), fontsize=8.5)
        ax.tick_params(labelsize=6)
    fig.suptitle('Top-10 highest-crossing routes (red) vs all other routes on the '
                 'same height (grey) with their crossing points', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path = AC.PLOTS_DIR / 'top10_crossing_routes.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


analysis_crossings_cache = {'all': []}


def histogram_figure(analysis):
    totals = [row['crossings_total'] for row in analysis['per_route']]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    ax = axes[0]
    ax.hist([value for value in totals if value > 0], bins=41,
            color='#1f77b4', edgecolor='black', linewidth=0.4)
    ax.set_xlabel('crossings per route (events)')
    ax.set_ylabel('# routes')
    ax.set_title('Per-route crossing histogram (632 routes with crossings)')
    ax.grid(True, linewidth=0.25, alpha=0.4)
    ax2 = axes[1]
    buckets = Counter()
    for value in totals:
        if value == 0:
            buckets['0'] += 1
        elif value <= 10:
            buckets['1-10'] += 1
        elif value <= 25:
            buckets['11-25'] += 1
        elif value <= 40:
            buckets['26-40'] += 1
        elif value <= 55:
            buckets['41-55'] += 1
        elif value <= 70:
            buckets['56-70'] += 1
        else:
            buckets['>70'] += 1
    order = ['0', '1-10', '11-25', '26-40', '41-55', '56-70', '>70']
    ax2.bar(order, [buckets[key] for key in order], color='#ff7f0e')
    for index, key in enumerate(order):
        ax2.text(index, buckets[key] + 3, str(buckets[key]), ha='center',
                 fontsize=8)
    ax2.set_xlabel('crossing bucket')
    ax2.set_ylabel('# routes')
    ax2.set_title('Per-route crossing distribution over all 1024 routes')
    ax2.grid(True, axis='y', linewidth=0.25, alpha=0.4)
    fig.tight_layout()
    path = AC.PLOTS_DIR / 'per_route_crossing_histogram.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def per_plane_bar_figure(analysis):
    rows = sorted(analysis['planes'], key=lambda row: row['z_mm'])
    labels = ['%s\n%+.2f' % (row['label'], row['z_mm']) for row in rows]
    values = [row['crossings'] for row in rows]
    colors = []
    for row in rows:
        if row['kind'] == 'interface_body':
            colors.append('#9467bd')
        elif row['crossings'] == 0:
            colors.append('#7f7f7f')
        elif row['crossings'] < 200:
            colors.append('#2ca02c')
        else:
            colors.append('#d62728')
    fig, ax = plt.subplots(figsize=(15.5, 5.8))
    bars = ax.bar(range(len(rows)), values, color=colors)
    for index, value in enumerate(values):
        if value:
            ax.text(index, value + 15, str(value), ha='center', fontsize=7.5,
                    rotation=90)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel('same-height crossings (events)')
    ax.set_title('Baseline 21-height per-plane crossing counts '
                 '(total %d events / %d pairs)'
                 % (analysis['totals']['crossings'],
                    analysis['totals']['crossing_pairs']))
    ax.grid(True, axis='y', linewidth=0.25, alpha=0.4)
    handles = [Line2D([0], [0], color='#7f7f7f', linewidth=6, label='crossing-free'),
               Line2D([0], [0], color='#2ca02c', linewidth=6, label='0 < events < 200'),
               Line2D([0], [0], color='#d62728', linewidth=6, label='events >= 200'),
               Line2D([0], [0], color='#9467bd', linewidth=6, label='interface height')]
    ax.legend(handles=handles, fontsize=8)
    fig.tight_layout()
    path = AC.PLOTS_DIR / 'per_plane_crossings.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def family_matrix_figure(analysis):
    matrix = analysis['family_pair_matrix']
    families = matrix['families']
    values = np.array(matrix['total'], dtype=float)
    fig, ax = plt.subplots(figsize=(11.5, 9.4))
    image = ax.imshow(values, cmap='YlOrRd')
    ax.set_xticks(range(len(families)))
    ax.set_xticklabels(families, rotation=60, ha='right', fontsize=8)
    ax.set_yticks(range(len(families)))
    ax.set_yticklabels(families, fontsize=8)
    for i in range(len(families)):
        for j in range(len(families)):
            if values[i, j] > 0:
                ax.text(j, i, '%d' % values[i, j], ha='center', va='center',
                        fontsize=6.4,
                        color='white' if values[i, j] > values.max() * 0.55 else 'black')
    ax.set_title('Family-pair crossing matrix (all heights, %d events)'
                 % analysis['totals']['crossings'])
    fig.colorbar(image, ax=ax, label='crossing events')
    fig.tight_layout()
    path = AC.PLOTS_DIR / 'family_pair_matrix.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def anomaly_figure(analysis, meta, table, groups, colors):
    raw = AC.read_json(AC.WORK_DIR / 'crossings.json')
    by_plane = defaultdict(list)
    for event in raw['crossings']:
        by_plane[event['plane_id']].append(event)
    fig, axes = plt.subplots(1, 2, figsize=(16.2, 8.0))
    for ax, pid in zip(axes, (9, 15)):
        z = round(meta[pid]['z_mm'], 9)
        prim_groups = groups[z]
        for rid, prims in sorted(prim_groups.items()):
            points = AC.polyline_of(prims)
            if len(points) < 2:
                continue
            ax.plot([point[0] for point in points],
                    [point[1] for point in points],
                    color=colors.get(table[rid]['family'], '0.5'),
                    linewidth=1.6, alpha=0.95)
        events = by_plane.get(pid, [])
        if events:
            ax.scatter([event['x_mm'] for event in events],
                       [event['y_mm'] for event in events],
                       marker='x', s=44, linewidths=1.3, color='red', zorder=9)
        families = sorted({table[rid]['family'] for rid in prim_groups})
        handles = [Line2D([0], [0], color=colors[f], linewidth=2.4, label=f)
                   for f in families]
        ax.legend(handles=handles, fontsize=7.5, loc='upper right',
                  framealpha=0.9)
        ax.set_xlim(-2, 152)
        ax.set_ylim(-2, 152)
        ax.set_aspect('equal')
        ax.set_xlabel('x (mm)')
        ax.set_ylabel('y (mm)')
        ax.set_title('%s (z=%+.2f): %d routes = 12 C4 orbits x 4 families, '
                     '%d crossings' % (meta[pid]['label'], meta[pid]['z_mm'],
                                       len(prim_groups), len(events)),
                     fontsize=10)
        ax.grid(True, linewidth=0.25, alpha=0.4)
    fig.suptitle('Anomaly: same composition, 60 vs 1246 crossings - corner-bundle '
                 'orbits (L9) vs grid orbits (L15)', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = AC.PLOTS_DIR / 'anomaly_L9_vs_L15.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def diagnostic_figure(analysis):
    rows = [row for row in analysis['planes'] if row['assigned_route_count'] > 1]
    labels = ['%s' % row['label'] for row in rows]
    actual = [row['crossing_pairs'] for row in rows]
    alt = [row['chord_alternating_pairs'] for row in rows]
    x = np.arange(len(rows))
    width = 0.38
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 5.4))
    ax = axes[0]
    ax.bar(x - width / 2, actual, width, label='baseline crossing pairs',
           color='#d62728')
    ax.bar(x + width / 2, alt, width,
           label='port-chord alternating pairs (topology risk)', color='#1f77b4')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=60, ha='right', fontsize=7.5)
    ax.set_ylabel('# route pairs')
    ax.set_title('Port-chord topology risk vs actual crossings, per height')
    ax.legend(fontsize=8)
    ax.grid(True, axis='y', linewidth=0.25, alpha=0.4)
    ax2 = axes[1]
    classes = Counter(event['forced_class'] for event in analysis['crossings'])
    order = ['forced', 'uncertain', 'avoidable']
    ax2.bar(order, [classes[key] for key in order],
            color=['#8c564b', '#ff7f0e', '#2ca02c'])
    for index, key in enumerate(order):
        ax2.text(index, classes[key] + 60, str(classes[key]), ha='center',
                 fontsize=9)
    ax2.set_ylabel('# crossing events')
    ax2.set_title('Forced / uncertain / avoidable crossing classification')
    ax2.grid(True, axis='y', linewidth=0.25, alpha=0.4)
    fig.tight_layout()
    path = AC.PLOTS_DIR / 'topology_vs_actual.png'
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print('[step4] wrote', path)
    return path


def main(force=False):
    planes, meta, table, raw, analysis, groups = load_all()
    analysis_crossings_cache['all'] = analysis['crossings']
    colors = family_color_map()
    made = []
    made.extend(plane_figures(planes, meta, table, raw, groups, colors))
    made.append(hotspot_figure(raw))
    made.append(top_routes_figure(analysis, meta, table, groups, colors))
    made.append(histogram_figure(analysis))
    made.append(per_plane_bar_figure(analysis))
    made.append(family_matrix_figure(analysis))
    made.append(anomaly_figure(analysis, meta, table, groups, colors))
    made.append(diagnostic_figure(analysis))
    print('[step4] total plots:', len(made))
    return made


if __name__ == '__main__':
    main(force='--force' in sys.argv)
