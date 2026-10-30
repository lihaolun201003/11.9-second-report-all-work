# -*- coding: utf-8 -*-
"""Figures / CSV for the 150 um Z1 multilayer experiments (real XYZ only)."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from four_side_1024.manual_c4 import z1_multilayer_150um as Z

OUT = Z.OUT_ROOT
FIG = OUT / 'figures'
PLANE_COLORS = {0.0: '#1f6fd6', 0.5: '#e07b1a'}
ROUTING_COLORS = ['#2f9e44', '#7048e8', '#e03131', '#0c8599',
                  '#f08c00', '#c2255c', '#5c940d', '#1864ab']


def color_for_z(z):
    z = round(float(z), 6)
    if z in PLANE_COLORS:
        return PLANE_COLORS[z]
    keys = sorted({h for h in Z.HEIGHTS.values()})
    try:
        idx = keys.index(z)
    except ValueError:
        idx = 0
    return ROUTING_COLORS[idx % len(ROUTING_COLORS)]


def sample_primitives(primitives, n_arc=16):
    xs, ys = [], []
    for prim in primitives:
        if prim.get('kind') == 'line':
            p0, p1 = prim['p0'], prim['p1']
            xs.extend([p0[0], p1[0]])
            ys.extend([p0[1], p1[1]])
        elif prim.get('kind') == 'arc':
            c = prim['center']
            r = float(prim['radius'])
            theta = np.linspace(float(prim['start_angle']),
                                float(prim['start_angle']) + float(prim['sweep']),
                                n_arc)
            xs.extend((c[0] + r * np.cos(theta)).tolist())
            ys.extend((c[1] + r * np.sin(theta)).tolist())
    return np.asarray(xs), np.asarray(ys)


def flat_primitives_at(record, z):
    out = []
    for part in record.get('parts') or []:
        if part['kind'] == 'flat' and abs(float(part['z_mm']) - z) <= 1e-9:
            out.extend(part['primitives'])
    return out


def audit(records):
    from four_side_1024.fslw import validate_fslw as V
    entries = defaultdict(list)
    for rec in records:
        for part in rec.get('parts') or []:
            if part['kind'] == 'flat':
                entries[round(float(part['z_mm']), 6)].append(
                    (int(rec['route_id']), part['primitives']))
    data = {}
    unique = set()
    per_route = Counter()
    for z, rows in entries.items():
        if len(rows) < 2:
            data[z] = dict(routes=len(rows), pairs=set(), events=[],
                           breakdown=Counter())
            continue
        prepared = [V.prepare_route(prims, rid) for rid, prims in rows]
        result = V.audit_route_pairs(prepared, policy='strict')
        pairs = set()
        events = []
        breakdown = Counter()
        for item in result['crossings']:
            a, b = int(item['route_a']), int(item['route_b'])
            pair = tuple(sorted((a, b)))
            pairs.add(pair)
            per_route[a] += 1
            per_route[b] += 1
            events.append(dict(x=float(item['x']), y=float(item['y']),
                               route_a=a, route_b=b))
            breakdown[pair] += 1
        unique |= pairs
        data[z] = dict(routes=len(rows), pairs=pairs, events=events,
                       breakdown=breakdown)
    return data, unique, per_route


def load_experiment(name):
    folder = OUT / name
    payload = Z.read_json(folder / 'routes_1024.json')
    summary = Z.read_json(folder / 'summary.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    return folder, payload, summary, records


def per_route_rows(records, per_route, manifest):
    rows = []
    for rec in records:
        flats = [p for p in (rec.get('parts') or []) if p['kind'] == 'flat']
        target = max((int(p.get('layer_id', 1)) for p in flats), default=1)
        z = max((float(p.get('z_mm', 0.0)) for p in flats), default=0.0)
        rows.append(dict(
            route_id=int(rec['route_id']), plane=rec.get('plane'),
            relation=manifest.get(int(rec['route_id']), {}).get('relation', ''),
            source_endpoint=rec.get('source_endpoint'),
            target_endpoint=rec.get('target_endpoint'),
            target_layer=target, max_z_mm=round(z, 6),
            n_transitions=int(rec.get('n_transitions') or 0),
            length_mm=round(float(rec.get('length_mm') or 0.0), 6),
            fabrication_s=round(float(rec.get('length_mm') or 0.0) / 1.0, 6),
            crossing_pairs=int(per_route.get(int(rec['route_id']), 0))))
    return rows


def write_csvs(folder, records, audit_data, per_route, manifest, summary):
    csv_dir = folder
    with (csv_dir / 'per_route.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(per_route_rows(
            records[:1], per_route, manifest)[0].keys()))
        writer.writeheader()
        for row in per_route_rows(records, per_route, manifest):
            writer.writerow(row)
    with (csv_dir / 'per_layer.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['z_mm', 'routes', 'unique_crossing_pairs',
                         'crossing_events', 'layer_id'])
        for z in sorted(audit_data):
            info = audit_data[z]
            writer.writerow([z, info['routes'], len(info['pairs']),
                             len(info['events']),
                             int(flat_layer_at(records, z))])
    return True


def flat_layer_at(records, z):
    for rec in records:
        for part in rec.get('parts') or []:
            if part['kind'] == 'flat' and abs(float(part['z_mm']) - z) <= 1e-9:
                return part.get('layer_id', 1)
    return 1


def plot_2d_layer(ax, records, z, title):
    drawn = 0
    for rec in records:
        prims = flat_primitives_at(rec, z)
        if not prims:
            continue
        xs, ys = sample_primitives(prims)
        if len(xs):
            ax.plot(xs, ys, color=color_for_z(z), lw=0.35, alpha=0.35)
            drawn += 1
    ax.set_xlim(-2, 152)
    ax.set_ylim(-2, 152)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.grid(alpha=0.15)
    ax.set_title(title, fontsize=9.5)


def draw_3d(ax, records, title, only_transitions=False):
    for rec in records:
        for part in rec.get('parts') or []:
            if part['kind'] == 'flat':
                if only_transitions:
                    continue
                xs, ys = sample_primitives(part['primitives'])
                if len(xs):
                    ax.plot(xs, ys, np.full(len(xs), float(part['z_mm'])),
                            color=color_for_z(part['z_mm']), lw=0.3,
                            alpha=0.35)
            else:
                p0 = part['start']
                p1 = part['end']
                ax.plot([p0[0], p1[0]], [p0[1], p1[1]],
                        [part['z0'], part['z1']],
                        color='#e8590c' if only_transitions else '#8c8c8c',
                        lw=0.8 if only_transitions else 0.35,
                        alpha=0.7 if only_transitions else 0.35)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_zlim(-0.05, max(Z.HEIGHTS.values()) + 0.1)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_zlabel('z (mm)')
    ax.view_init(elev=24, azim=-58)
    ax.set_title(title, fontsize=9.5, pad=6)


def make_contact_sheet(folder, names):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 22)
    imgs = [Image.open(folder / 'figures' / n).convert('RGB') for n in names]
    w, h = 760, 640
    cols = 3
    rows = (len(imgs) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * w + 40, rows * (h + 32) + 20), 'white')
    draw = ImageDraw.Draw(canvas)
    for idx, (img, name) in enumerate(zip(imgs, names)):
        img.thumbnail((w - 8, h - 8), Image.LANCZOS)
        r, c = divmod(idx, cols)
        x = 10 + c * w
        y = 10 + r * (h + 32)
        canvas.paste(img, (x, y))
        draw.text((x + 8, y + h - 16), name, font=font, fill='#333333')
    path = folder / 'figures' / 'all_layers_contact_sheet.png'
    canvas.save(path, optimize=True)
    return path


def plot_experiment(name, baseline=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image, ImageDraw, ImageFont
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    folder, payload, summary, records = load_experiment(name)
    figdir = folder / 'figures'
    figdir.mkdir(parents=True, exist_ok=True)
    manifest = {int(r['route_id']): r for r in
                Z.read_json(Z.CAMPAIGN / 'inputs/connectivity_1024.json')['routes']}
    audit_data, unique, per_route = audit(records)
    write_csvs(folder, records, audit_data, per_route, manifest, summary)
    max_layer = int(summary.get('max_layer') or 5)
    n = len(records)
    total_length = sum(float(r.get('length_mm') or 0.0) for r in records)

    # 01 / 02 overall
    fig = plt.figure(figsize=(10, 8.5))
    ax = fig.add_subplot(111, projection='3d')
    draw_3d(ax, records, f'{name}: {n}/1024 routes, unique crossings '
                        f'{len(unique)}, length {total_length:.1f} mm')
    fig.tight_layout()
    fig.savefig(figdir / '01_overall_3d.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 8))
    for rec in records:
        for part in rec.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            xs, ys = sample_primitives(part['primitives'])
            if len(xs):
                ax.plot(xs, ys, color=color_for_z(part['z_mm']), lw=0.3,
                        alpha=0.25)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title(f'{name} XY projection (all layers)')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    fig.tight_layout()
    fig.savefig(figdir / '02_overall_xy.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    # per physical layer
    layer_files = [('03_L1_Z1', 0.0, 'L1-Z1'), ('04_L1_Z2', 0.5, 'L1-Z2')]
    for layer_id in range(2, max_layer + 1):
        layer_files.append((f'{5 + layer_id - 2:02d}_L{layer_id}', Z.layer_z(layer_id),
                            f'L{layer_id}'))
    per_names = []
    for idx, (fname, z, label) in enumerate(layer_files):
        fig, ax = plt.subplots(figsize=(7.2, 7.0))
        plot_2d_layer(ax, records, z, f'{label}  z={z:.2f} mm')
        info = audit_data.get(round(z, 6), dict(routes=0, pairs=set(), events=[]))
        for ev in info['events']:
            ax.plot(ev['x'], ev['y'], 'x', color='#e03131', ms=3, mew=0.8)
        ax.set_title(f'{label}  z={z:.2f} mm   routes={info["routes"]}  '
                     f'crossing_pairs={len(info["pairs"])}  '
                     f'events={len(info["events"])}', fontsize=9)
        fig.tight_layout()
        fig.savefig(figdir / f'{fname}.png', dpi=170, bbox_inches='tight')
        plt.close(fig)
        per_names.append(f'{fname}.png')

    make_contact_sheet(folder, per_names)

    # transitions 3D
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    draw_3d(ax, records, f'{name}: 3D S transitions (orange)', only_transitions=True)
    fig.tight_layout()
    fig.savefig(figdir / 'transitions_3d.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    # hotspots (z1 interface layer)
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    z1_events = audit_data.get(0.0, {}).get('events', [])
    if z1_events:
        xs = [e['x'] for e in z1_events]
        ys = [e['y'] for e in z1_events]
        hb = ax.hexbin(xs, ys, gridsize=38, cmap='Reds', mincnt=1)
        fig.colorbar(hb, ax=ax, label='crossing events')
        ax.set_title(f'{name}: Z1 (z=0) crossing hotspots, '
                     f'{len(z1_events)} events', fontsize=10)
    else:
        ax.text(75, 75, 'no Z1 crossings', ha='center', va='center')
        ax.set_title(f'{name}: Z1 hotspots')
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    fig.tight_layout()
    fig.savefig(figdir / 'z1_crossing_hotspots.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    # before/after vs baseline
    if baseline is not None:
        _, _, bsum, brecs = load_experiment(baseline)
        baudit, bunique, _ = audit(brecs)
        fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
        labels = ['global unique', 'Z1 H-V pairs', 'Z1 z=0 pairs']
        before = [bsum.get('unique_crossing_pairs', 0),
                  bsum.get('z1_hv_same_height_pairs', 0),
                  len(baudit.get(0.0, {}).get('pairs', set()))]
        after = [len(unique), sum(1 for e in audit_data.get(0.0, {}).get('events', [])
                                  if e['route_a'] != e['route_b']) if False else
                 summary.get('z1_hv_same_height_pairs', 0),
                 len(audit_data.get(0.0, {}).get('pairs', set()))]
        x = np.arange(len(labels))
        axes[0].bar(x - 0.18, before, 0.36, label='5L baseline', color='#868e96')
        axes[0].bar(x + 0.18, after, 0.36, label=name, color='#2f9e44')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(labels, fontsize=8)
        axes[0].legend(fontsize=8)
        axes[0].set_title('crossing comparison')
        # z1 before/after scatter
        for ax, evs, title, color in (
                (axes[1], baudit.get(0.0, {}).get('events', []), 'baseline z=0', '#868e96'),
                (axes[1], audit_data.get(0.0, {}).get('events', []), name + ' z=0', '#e03131')):
            if evs:
                ax.scatter([e['x'] for e in evs], [e['y'] for e in evs],
                           s=3, alpha=0.35, color=color, label=title)
        axes[1].set_xlim(0, 150)
        axes[1].set_ylim(0, 150)
        axes[1].set_aspect('equal')
        axes[1].legend(fontsize=7)
        axes[1].set_title('Z1 crossing positions')
        fig.tight_layout()
        fig.savefig(figdir / 'z1_before_after.png', dpi=200, bbox_inches='tight')
        plt.close(fig)


def comparison_plots():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    comp = Z.read_json(OUT / 'comparison.json')
    order = ['5L 基线', 'optimized_5L', 'optimized_7L', 'optimized_9L',
             'optimized_11L']
    labels = ['5L base', '5L opt', '7L opt', '9L opt', '11L opt']
    vals = {key: [] for key in ('unique_crossing_pairs', 'z1_hv',
                               'transitions', 'fabrication_hours')}
    for name in order:
        for key in vals:
            vals[key].append(comp[name][key])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
    for ax, key, title in ((axes[0, 0], 'unique_crossing_pairs', 'global unique crossing pairs'),
                           (axes[0, 1], 'z1_hv', 'Z1 horizontal/vertical pairs'),
                           (axes[1, 0], 'transitions', 'transition count'),
                           (axes[1, 1], 'fabrication_hours', 'fabrication time (h, 1 mm/s)')):
        ax.plot(labels, vals[key], 'o-', color='#1971c2', lw=2)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        if key == 'fabrication_hours':
            ax.set_ylim(min(vals[key]) - 0.01, max(vals[key]) + 0.01)
    fig.suptitle('150 um stack: 5/7/9/11-layer Z1 optimisation', fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / 'comparison.png', dpi=200, bbox_inches='tight')
    plt.close(fig)

    with (OUT / 'comparison.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['experiment', 'global_unique_pairs', 'z1_hv_pairs',
                         'transitions', 'length_mm', 'fabrication_s',
                         'fabrication_h', 'max_layer', 'validation',
                         'violations'])
        for name in order:
            row = comp[name]
            writer.writerow([name, row['unique_crossing_pairs'], row['z1_hv'],
                             row['transitions'], row['length_mm'],
                             round(row['length_mm'] / 1.0, 4),
                             row['fabrication_hours'], row['max_layer'],
                             row['validation'], row['counts']['violations']])


def main():
    comparison_plots()
    baseline = 'baseline_5L'
    for name in ('baseline_5L', 'optimized_5L', 'optimized_7L',
                 'optimized_9L', 'optimized_11L'):
        print('plot', name)
        plot_experiment(name, baseline=None if name == baseline else baseline)


if __name__ == '__main__':
    main()
