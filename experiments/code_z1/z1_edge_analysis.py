# -*- coding: utf-8 -*-
"""Trace every real Z1 crossing of the current 7L solution back to its source."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from four_side_1024.manual_c4 import z1_multilayer_150um as Z

import os
OUT_ROOT = Z.OUT_ROOT / 'z1_edge_optimization'
ANALYSIS = Path(os.environ.get('Z1_ANALYSIS_OUT', str(OUT_ROOT / 'analysis')))
BASE = Path(os.environ.get('Z1_ROUTE_DIR', str(Z.OUT_ROOT / 'optimized_7L')))


def load_routes(folder=BASE):
    payload = Z.read_json(Path(folder) / 'routes_1024.json')
    return [r for r in payload['routes'] if r.get('status') == 'routed']


def load_manifest():
    conn = Z.read_json(Z.CAMPAIGN / 'inputs/connectivity_1024.json')
    return {int(r['route_id']): r for r in conn['routes']}


def point_segment_distance(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    if abs(dx) + abs(dy) < 1e-12:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def point_arc_distance(px, py, prim):
    cx, cy = prim['center']
    r = float(prim['radius'])
    a0 = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    ang = math.atan2(py - cy, px - cx)
    # normalize into [a0, a0+sweep]
    lo, hi = (a0, a0 + sweep) if sweep >= 0 else (a0 + sweep, a0)
    candidates = [lo, hi]
    # angle + 2k*pi inside range
    for k in range(-2, 3):
        for c in (ang + 2 * math.pi * k,):
            if lo - 1e-9 <= c <= hi + 1e-9:
                candidates.append(c)
    best = min(abs(math.hypot(px - (cx + r * math.cos(c)),
                              py - (cy + r * math.sin(c))))
               for c in candidates)
    return best


def segment_at(route, x, y):
    """Return (part_kind, primitive_kind, distance) nearest to (x,y)."""
    best = (None, None, 1e9)
    for pi, part in enumerate(route.get('parts') or []):
        if part['kind'] != 'flat':
            continue
        for prim in part['primitives']:
            if prim.get('kind') == 'line':
                p0, p1 = prim['p0'], prim['p1']
                d = point_segment_distance(x, y, p0[0], p0[1], p1[0], p1[1])
                kind = 'line'
            elif prim.get('kind') == 'arc':
                d = point_arc_distance(x, y, prim)
                kind = 'arc'
            else:
                continue
            if d < best[2]:
                best = (part['kind'], kind, d)
    return best


def region_of(x, y, board=150.0):
    edge = min(x, y, board - x, board - y)
    corner = min(max(x, y), 0)  # placeholder
    near_x = min(abs(x), abs(board - x))
    near_y = min(abs(y), abs(board - y))
    if near_x <= 18 or near_y <= 18:
        return 'port_lead' if near_x <= 18 and near_y <= 18 else 'edge_lead'
    if (x < 52 and y < 52) or (x < 52 and y > 98) or \
       (x > 98 and y < 52) or (x > 98 and y > 98):
        return 'corner_turn'
    return 'central_trunk'


def relation_of(manifest, rid):
    rec = manifest[int(rid)]
    rel = rec.get('relation')
    if rel == 'same':
        return 'same'
    if rel == 'adjacent':
        return 'adjacent'
    if rel == 'opposite':
        return 'opposite'
    return str(rel)


def audit_plane(records, manifest, z=0.0):
    from four_side_1024.fslw import validate_fslw as V
    entries = []
    for rec in records:
        for part in rec.get('parts') or []:
            if part['kind'] == 'flat' and abs(float(part['z_mm']) - z) <= 1e-9:
                # A lifted route has two Z1 flats: before and after the S-climb.
                entries.append((int(rec['route_id']), part['primitives']))
    prepared = [V.prepare_route(prims, rid) for rid, prims in entries]
    return V.audit_route_pairs(prepared, policy='strict')


def main():
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    routes = load_routes()
    by_id = {int(r['route_id']): r for r in routes}
    manifest = load_manifest()
    result = audit_plane(routes, manifest, z=0.0)
    rows = []
    pair_seen = set()
    for item in result['crossings']:
        a, b = int(item['route_a']), int(item['route_b'])
        if a == b:
            continue
        x, y, z = float(item['x']), float(item['y']), 0.0
        ka = segment_at(by_id[a], x, y)
        kb = segment_at(by_id[b], x, y)
        ra, rb = relation_of(manifest, a), relation_of(manifest, b)
        cat = ' x '.join(sorted((ra, rb)))
        seg = ' x '.join(sorted((ka[1] or '?', kb[1] or '?')))
        rows.append(dict(
            route_a=a, route_b=b, relation_a=ra, relation_b=rb,
            category=cat, x=round(x, 4), y=round(y, 4), z=z,
            geom_a=ka[1], geom_b=kb[1], geom_pair=seg,
            region=region_of(x, y),
            dist_a=round(ka[2], 5), dist_b=round(kb[2], 5)))
        pair_seen.add(tuple(sorted((a, b))))
    with (ANALYSIS / 'z1_crossings.csv').open('w', newline='',
                                              encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    # category aggregation
    cat = Counter()
    cat_seg = Counter()
    cat_region = Counter()
    for row in rows:
        cat[row['category']] += 1
        cat_seg[(row['category'], row['geom_pair'])] += 1
        cat_region[(row['category'], row['region'])] += 1
    total_pairs = len(pair_seen)
    summary = dict(
        plane_z=0.0,
        total_unique_pairs=total_pairs,
        total_events=len(rows),
        category_events=dict(cat),
        category_pairs={},
        geometry_by_category={f'{k[0]} | {k[1]}': v for k, v in cat_seg.items()},
        region_by_category={f'{k[0]} | {k[1]}': v for k, v in cat_region.items()},
    )
    # unique pairs per category
    pair_cat = defaultdict(set)
    for row in rows:
        pair_cat[row['category']].add(tuple(sorted((row['route_a'], row['route_b']))))
    summary['category_pairs'] = {k: len(v) for k, v in pair_cat.items()}
    # adjacent-specific geometry analysis
    adj = [row for row in rows
           if 'adjacent' in (row['relation_a'], row['relation_b'])]
    summary['adjacent_events'] = len(adj)
    summary['adjacent_pairs'] = len({tuple(sorted((r['route_a'], r['route_b'])))
                                     for r in adj})
    summary['adjacent_geometry'] = dict(Counter(r['geom_pair'] for r in adj))
    summary['adjacent_regions'] = dict(Counter(r['region'] for r in adj))
    # adjacent-arc vs adjacent-lead
    arc_adj = [r for r in adj if (r['relation_a'] == 'adjacent' and r['geom_a'] == 'arc') or
               (r['relation_b'] == 'adjacent' and r['geom_b'] == 'arc')]
    summary['adjacent_arc_events'] = len(arc_adj)
    summary['adjacent_line_events'] = len(adj) - len(arc_adj)
    Z.write_json(ANALYSIS / 'z1_crossing_summary.json', summary)

    # CSV table
    with (ANALYSIS / 'z1_crossing_category_table.csv').open(
            'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.writer(fh)
        writer.writerow(['category', 'unique_pairs', 'events'])
        for key in sorted(cat):
            writer.writerow([key, len(pair_cat[key]), cat[key]])
        writer.writerow(['ALL', total_pairs, len(rows)])

    # heatmaps by category
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    colors = {
        'adjacent x adjacent': '#e03131',
        'adjacent x opposite': '#f08c00',
        'adjacent x same': '#7048e8',
        'opposite x opposite': '#1971c2',
        'same x same': '#2f9e44',
    }
    for cat_name in sorted(cat):
        pts = [(r['x'], r['y']) for r in rows if r['category'] == cat_name]
        fig, ax = plt.subplots(figsize=(7.2, 7.0))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.scatter(xs, ys, s=4, alpha=0.45,
                   color=colors.get(cat_name, '#444444'))
        ax.set_xlim(0, 150)
        ax.set_ylim(0, 150)
        ax.set_aspect('equal')
        ax.set_title(f'Z1 crossings: {cat_name}\n'
                     f'{len(pair_cat[cat_name])} pairs / {len(pts)} events',
                     fontsize=9.5)
        ax.set_xlabel('x (mm)')
        ax.set_ylabel('y (mm)')
        fig.tight_layout()
        safe = cat_name.replace(' x ', '_')
        fig.savefig(ANALYSIS / f'heatmap_{safe}.png', dpi=180,
                    bbox_inches='tight')
        plt.close(fig)
    # combined figure
    fig, ax = plt.subplots(figsize=(8.2, 7.6))
    for cat_name in sorted(cat):
        pts = [(r['x'], r['y']) for r in rows if r['category'] == cat_name]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=3,
                   alpha=0.4, label=f'{cat_name} ({len(pts)})',
                   color=colors.get(cat_name, '#444444'))
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.legend(fontsize=7, markerscale=3)
    ax.set_title('Z1 (z=0) crossing events by connection category')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    fig.tight_layout()
    fig.savefig(ANALYSIS / 'heatmap_z1_all_categories.png', dpi=220,
                bbox_inches='tight')
    plt.close(fig)

    # adjacent-only routing + its crossings
    fig, ax = plt.subplots(figsize=(7.6, 7.3))
    from four_side_1024.manual_c4.z1_multilayer_plots import sample_primitives
    for rec in routes:
        if manifest[int(rec['route_id'])]['relation'] != 'adjacent':
            continue
        for part in rec.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            xs, ys = sample_primitives(part['primitives'])
            if len(xs):
                ax.plot(xs, ys, color='#495057', lw=0.35, alpha=0.35)
    if adj:
        ax.scatter([r['x'] for r in adj], [r['y'] for r in adj],
                   s=5, color='#e03131', alpha=0.55, label='adjacent-related crossings')
        ax.legend(fontsize=8, markerscale=2)
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title(f'Z1 adjacent routes and their crossings\n'
                 f'{summary["adjacent_pairs"]} pairs / {summary["adjacent_events"]} events',
                 fontsize=9.5)
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    fig.tight_layout()
    fig.savefig(ANALYSIS / 'adjacent_routes_and_crossings.png', dpi=200,
                bbox_inches='tight')
    plt.close(fig)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print('rows', len(rows), 'unique pairs', total_pairs)


if __name__ == '__main__':
    main()
