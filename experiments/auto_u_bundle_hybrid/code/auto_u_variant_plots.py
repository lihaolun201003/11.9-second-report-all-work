# -*- coding: utf-8 -*-
"""Generate routing figures for all automatic-U layer assignments.

Variants:
* best          : automatic layer-search optimum (12,960)
* greedy        : first feasible greedy assignment (14,104)
* alt_L2_* ...  : the six distinct-layer assignments found by the search (13,080)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import auto_u_bundle_plots as A
from . import run_auto_u_bundle_hybrid as R

OUT = R.OUT
VARDIR = OUT / 'variants'
FONT = r'C:\Windows\Fonts\msyh.ttc'
TITLE_FONT = ImageFont.truetype(FONT, 42)
SUB_FONT = ImageFont.truetype(FONT, 24)
LABEL_FONT = ImageFont.truetype(FONT, 26)
TILE_W, TILE_H = 880, 748
PAD = 16
LABEL_H = 40


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def contact_sheet(name, folder, title, subtitle):
    images = []
    for fname, label in (('03_L1_z1.png', 'L1-z1  z=0.0 mm'),
                         ('04_L1_z2.png', 'L1-z2  z=0.5 mm'),
                         ('05_L2.png', 'L2  z=1.0 mm'),
                         ('06_L3.png', 'L3  z=1.5 mm'),
                         ('07_L4.png', 'L4  z=2.0 mm'),
                         ('08_L5.png', 'L5  z=2.5 mm')):
        images.append((folder / fname, label))
    header_h = 100
    canvas_w = 3 * TILE_W + 4 * PAD
    canvas_h = header_h + 2 * (TILE_H + LABEL_H + PAD) + PAD
    canvas = Image.new('RGB', (canvas_w, canvas_h), 'white')
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD + 6, 10), title, font=TITLE_FONT, fill='#111111')
    draw.text((PAD + 8, 60), subtitle, font=SUB_FONT, fill='#555555')
    for index, (path, label) in enumerate(images):
        row, col = divmod(index, 3)
        x = PAD + col * (TILE_W + PAD)
        y = header_h + row * (TILE_H + LABEL_H + PAD)
        img = Image.open(path).convert('RGB')
        img.thumbnail((TILE_W, TILE_H), Image.LANCZOS)
        canvas.paste(img, (x + (TILE_W - img.width) // 2, y))
        draw.text((x + TILE_W // 2, y + TILE_H + 4), label,
                  font=LABEL_FONT, fill='#222222', anchor='ma')
    out = folder.parent / f'{name}_contact_2x3.png'
    canvas.save(out, optimize=True)
    print('contact', out)


def plot_variant(campaign, hybrid_payload, clusters, feasible, rid_cluster,
                 name, assignment, title, subtitle, log=print):
    result = R.evaluate(campaign, hybrid_payload, assignment, clusters,
                        feasible, [c['cluster_id'] for c in clusters])
    if result is None:
        log(f'{name}: INVALID assessment')
        return None
    payload = result['payload']
    metrics = result['metrics']
    vdir = VARDIR / name
    figdir = vdir / 'figures'
    figdir.mkdir(parents=True, exist_ok=True)
    R.write_json(vdir / 'routes_1024.json', payload, indent=None)
    R.write_json(vdir / 'summary.json',
                 dict(name=name, title=title, assignment=assignment,
                      metrics=metrics))
    records = [r for r in payload['routes'] if r.get('status') == 'routed']

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    specs = [('02_after_3d', None, title)]
    for fname, z, label in (('03_L1_z1', 0.0, 'L1-z1（row1 接口层）'),
                            ('04_L1_z2', 0.5, 'L1-z2（row2 接口层）'),
                            ('05_L2', 1.0, 'L2'),
                            ('06_L3', 1.5, 'L3'),
                            ('07_L4', 2.0, 'L4'),
                            ('08_L5', 2.5, 'L5')):
        specs.append((fname, z, label))
    for fname, z, label in specs:
        fig = plt.figure(figsize=A.SP.FIGSIZE)
        ax = fig.add_subplot(111, projection='3d')
        fig.subplots_adjust(left=0.01, right=0.99, bottom=0.045, top=0.885)
        if z is None:
            A.whole(ax, records, rid_cluster, assignment, title)
        else:
            A.layer(ax, records, rid_cluster, assignment, z, label)
        A.SP._save(fig, figdir / fname)
        plt.close(fig)
    # only U bundles
    fig = plt.figure(figsize=A.SP.FIGSIZE)
    ax = fig.add_subplot(111, projection='3d')
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.045, top=0.885)
    A.bundles(ax, records, rid_cluster, assignment,
              f'{title}：4 个自动 U 线束')
    A.SP._save(fig, figdir / '09_u_bundles_3d')
    plt.close(fig)
    contact_sheet(name, figdir, title, subtitle)
    log(f'{name}: {metrics["unique_crossing_pairs"]} crossings, '
        f'{metrics.get("transitions")} transitions, '
        f'{metrics.get("total_length_mm"):.2f} mm -> {vdir}')
    return dict(name=name, assignment=assignment,
                unique_crossing_pairs=metrics['unique_crossing_pairs'],
                transitions=metrics.get('transitions'),
                length=metrics.get('total_length_mm'),
                min3d=metrics.get('min_3d_clearance_mm'), path=str(vdir))


def main():
    VARDIR.mkdir(parents=True, exist_ok=True)
    campaign, hybrid_payload = R.load_hybrid_campaign()
    feasible = R.load_scan()
    clusters, k = R.auto_clusters(campaign, R.quartet_features(campaign))
    order = [c['cluster_id'] for c in clusters]
    # load the best payload to reuse the route -> cluster mapping
    auto, before, clusters2, best_assign, rid_cluster = A.load()
    best_assign = {int(k): int(v) for k, v in best_assign.items()}

    candidates = json.loads((OUT / 'search_candidates.json').read_text(encoding='utf-8-sig'))
    variants = [('best', best_assign,
                 'Auto U：层搜索最优（与 Hybrid 持平）',
                 '全局唯一交叉 12,960；784 升降；总长 98,736.09 mm；PASS')]
    variants.append(('greedy', {0: 2, 1: 3, 2: 3, 3: 3},
                     'Auto U：贪心初解（未做层搜索）',
                     '全局唯一交叉 14,104（比 Hybrid 多 1,144）'))
    for item in candidates:
        assignment = {int(k): int(v) for k, v in item['assignment'].items()}
        if assignment == best_assign:
            continue
        name = 'alt_' + '_'.join(f'c{c}L{assignment[c]}' for c in (0, 1, 2, 3))
        variants.append((name, assignment,
                         f'Auto U：其他层排列（簇层 {assignment}）',
                         f'全局唯一交叉 {item["unique_crossing_pairs"]:,}；'
                         f'总长 {item["length"]:,.2f} mm'))
    rows = []
    started = time.perf_counter()
    for name, assignment, title, subtitle in variants:
        row = plot_variant(campaign, hybrid_payload, clusters, feasible,
                           rid_cluster, name, assignment, title, subtitle)
        if row:
            rows.append(row)
    R.write_json(OUT / 'variants/index.json', dict(variants=rows,
                                                   seconds=round(time.perf_counter() - started, 1)))
    print('done', len(rows), 'variants')


if __name__ == '__main__':
    main()
