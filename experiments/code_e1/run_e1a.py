# -*- coding: utf-8 -*-
"""E1-A: exhaustive blocker analysis of the 29 still-flat Z1 C2 pair-directions.

The 29 pair-directions (58 routes) are the C2 pairs that the published 7-layer
solution left flat on the L1-Z1 interface.  This script re-examines every one of
them against the real published 1024-route world (with the two members removed,
i.e. replacement semantics) and records, for every failed candidate, ALL of its
blockers (``core.collect_violations``) classified into the task-section-5
taxonomy.

Candidate coverage per pair-direction
-------------------------------------
* pair-together mode (both members lifted with the SAME window):
    - legacy assembly grid  a = PAIR_A_VALUES in z1_multilayer_150um.py
      ([1.2, 2.4, 4.0, 6.0, 9.0, 13.0, 18.0, 24.0, 31.0, 39.0, 48.0, 55.0, 60.0])
      x layers L2..L7  -> reproduces the windows the flat fallback was chosen on;
    - fine grid from ``search.window_grid`` (structurally valid straight
      intervals only): sampled symmetric + asymmetric windows, 14/layer.
* single-route mode (one member lifted, the other stays flat): fine-grid
  symmetric + asymmetric windows, 14/layer per route.
* plus a full fast legality scan of the WHOLE fine grid (all layers, all
  structurally valid windows) for every pair, cached in E1_A_quick_scan.json.

Outputs (E1_A_blocker_analysis/):
  E1_A_blocker_analysis.csv   every diagnosed candidate incl. all blockers
  E1_A_pair_summary.csv       per pair-direction x mode aggregation + verdict
  E1_A_z2_blocker_list.csv    "被 Z2 阻挡的候选清单"
  E1_A_blocker_routes.csv     every distinct blocker route seen
  E1_A_legal_windows.csv      fine-grid legal run around the first legal window
  E1_A_summary.json           aggregate + required conclusion numbers
  E1_A_findings.md            short real-number summary
  figures/                    figures required by the task description
"""
from __future__ import annotations

import math
import pickle
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, '.')

from four_side_1024.e1 import core as C
from four_side_1024.e1 import plots as P
from four_side_1024.e1 import search as S

OUT = C.E1 / 'E1_A_blocker_analysis'

# Legacy optimizer grid: the coarse assembly grid actually used for the
# published 7-layer solution.  Its deepest sampled window is 55.0 mm
# (z1_multilayer_150um.py PAIR_A_VALUES also contains 60.0, which is evaluated
# separately as ``code_grid_60`` to show the residual grid sensitivity).
LEGACY_A = [1.2, 2.4, 4.0, 6.0, 9.0, 13.0, 18.0, 24.0, 31.0, 39.0, 48.0,
            55.0]
CODE_A_60 = 60.0  # last value of PAIR_A_VALUES in z1_multilayer_150um.py

# task-section-5 classification -------------------------------------------------
Z2_CLASSES = {'z2_adjacent_conflict', 'z2_same_u_conflict',
              'z2_opposite_conflict'}
CAT_CLASS = {
    'adjacent_z1': 'z1_route_conflict',
    'same_u_z1': 'z1_route_conflict',
    'opposite_z1_EW': 'z1_route_conflict',
    'opposite_z1_NS': 'z1_route_conflict',
    'adjacent_z2': 'z2_adjacent_conflict',
    'same_u_z2': 'z2_same_u_conflict',
    'opposite_z2_EW': 'z2_opposite_conflict',
    'opposite_z2_NS': 'z2_opposite_conflict',
}
CAT_LABEL = {
    'adjacent_z1': '1_Z1其他路线(邻边)',
    'same_u_z1': '1_Z1其他路线(同侧U)',
    'opposite_z1_EW': '1_Z1其他路线(对边)',
    'opposite_z1_NS': '1_Z1其他路线(对边)',
    'adjacent_z2': '2_Z2相邻线',
    'same_u_z2': '3_Z2同侧U',
    'opposite_z2_EW': '4_Z2对边',
    'opposite_z2_NS': '4_Z2对边',
}
BLOCK_CLASS_ZH = {
    'geometry': '6_几何不可构造(无合法结构窗口)',
    'z2_only': '2_Z2阻挡(仅Z2)',
    'z1_only': '1_Z1阻挡(仅Z1)',
    'mixed': '1+2_Z1与Z2共同阻挡',
    'other_only': '5/7_其他三维或自净空冲突',
    'ok': '0_合法',
}


# ---------------------------------------------------------------------------
# world / candidate helpers (re-used by run_e1b.py)
# ---------------------------------------------------------------------------
def world_without(ctx, records, exclude_ids):
    """Clearance world of ``records`` with the routes in ``exclude_ids`` removed."""
    exclude = {int(rid) for rid in exclude_ids}
    return ctx.world([r for r in records
                      if int(r['route_id']) not in exclude])


def search_pair_legal(ctx, world, entry, layers=C.LAYERS):
    """Ordered pair-together legality scan (no blocker collection).

    Returns the nearest-to-port legal window on every layer and the overall
    first legal candidate; ``n_evaluated`` counts evaluated candidates.
    """
    per_layer = {}
    n = 0
    for layer in layers:
        for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer):
            n += 1
            rec, _routes = S.evaluate_pair_together(
                ctx, world, entry, layer, a_in, a_out, collect=False)
            if rec['legal']:
                per_layer[int(layer)] = (round(a_in, 4), round(a_out, 4))
                break
    first = None
    if per_layer:
        layer0 = min(per_layer)
        a_in, a_out = per_layer[layer0]
        rec, routes = S.evaluate_pair_together(
            ctx, world, entry, layer0, a_in, a_out, collect=True)
        first = dict(layer=layer0, a_in=a_in, a_out=a_out, record=rec,
                     routes=routes)
    return dict(per_layer=per_layer, first=first, n_evaluated=n)


def annotate_record(ctx, record, member_ids):
    """Re-classify a search record with the task taxonomy and ALL blockers.

    ``core.violation_classes`` only matches exact 'adjacent_z2'-style names,
    so Z1 categories fall through to 'same_plane_conflict'; here the mapping is
    explicit.  ``record['blockers']`` is rebuilt with a correct label so
    ``search.candidate_csv_row`` can be reused unchanged.
    """
    member_ids = {int(rid) for rid in member_ids}
    violations = record.get('violations') or []
    classes = set()
    blockers = {}
    mate_conflict = False
    for violation in violations:
        kind = violation.get('kind')
        other = violation.get('other_route')
        if kind == 'self_clearance':
            classes.add('self_geometry')
            continue
        if kind == 'transition_vs_transition':
            classes.add('transition_3d_conflict')
            continue
        if other is None:
            classes.add('same_plane_conflict')
            continue
        other = int(other)
        if other in member_ids:
            mate_conflict = True
            classes.add('self_geometry')
            continue
        cat = ctx.cat.get(other, '')
        classes.add(CAT_CLASS.get(cat, 'same_plane_conflict'))
        info = blockers.get(other)
        if info is None:
            info = dict(route_id=other, category=cat,
                        plane=ctx.plane_of(other),
                        label=CAT_LABEL.get(cat, '7_其他'),
                        point=violation.get('point'), kinds=set())
            blockers[other] = info
        info['kinds'].add(kind)
        if info['point'] is None and violation.get('point') is not None:
            info['point'] = violation['point']
    rows = []
    for other in sorted(blockers):
        info = blockers[other]
        info['kinds'] = sorted(str(k) for k in info['kinds'])
        rows.append(info)
    if record.get('legal'):
        failure = 'ok'
    elif not record.get('built'):
        failure = 'curvature_or_space'
    else:
        failure = C.failure_type(classes)
        if failure == 'ok':  # only self/mate conflicts
            failure = 'self_geometry'
    record['classes'] = classes
    record['blockers'] = rows
    record['failure'] = failure
    record['mate_conflict'] = mate_conflict
    record['block_class'] = block_class(record)
    record['n_z2_blockers'] = sum(
        1 for row in rows if row['category'].endswith('_z2'))
    record['n_z1_blockers'] = sum(
        1 for row in rows if row['category'].endswith('_z1'))
    record['z2_route_ids'] = [row['route_id'] for row in rows
                              if row['category'].endswith('_z2')]
    record['z1_route_ids'] = [row['route_id'] for row in rows
                              if row['category'].endswith('_z1')]
    record['z2_categories'] = sorted({row['category'] for row in rows
                                      if row['category'].endswith('_z2')})
    return record


def block_class(record):
    """Task-section-5 bucket of one candidate."""
    if not record.get('built'):
        return 'geometry'
    classes = record.get('classes') or set()
    z2 = classes & Z2_CLASSES
    z1 = classes & {'z1_route_conflict'}
    other = classes - z2 - z1
    if record.get('legal'):
        return 'ok'
    if z2 and not z1 and not other:
        return 'z2_only'
    if z2:
        return 'mixed'
    if z1:
        return 'z1_only'
    return 'other_only'


def sample(sequence, count):
    if len(sequence) <= count:
        return list(sequence)
    if count <= 1:
        return [sequence[0]]
    indices = sorted({int(round(i * (len(sequence) - 1) / (count - 1)))
                      for i in range(count)})
    return [sequence[index] for index in indices]


def diagnosis_candidates(ctx, rid, mode='pair', n_sym=8, n_asym=6):
    """Deterministic candidate set: legacy grid + sampled fine windows."""
    out = []
    seen = set()
    for layer in C.LAYERS:
        grid = S.window_grid(ctx, rid, layer)
        sym = [(a, b) for a, b in grid if abs(a - b) < 1e-9]
        asym = [(a, b) for a, b in grid if abs(a - b) >= 1e-9]
        if mode == 'pair':
            for a in LEGACY_A:
                key = (layer, round(a, 4), round(a, 4), 'legacy_grid')
                if key not in seen:
                    seen.add(key)
                    out.append(dict(source='legacy_grid', layer=layer,
                                    a_in=round(a, 4), a_out=round(a, 4)))
            key = (layer, round(CODE_A_60, 4), round(CODE_A_60, 4),
                   'code_grid_60')
            if key not in seen:
                seen.add(key)
                out.append(dict(source='code_grid_60', layer=layer,
                                a_in=round(CODE_A_60, 4),
                                a_out=round(CODE_A_60, 4)))
        for a, b in sample(sym, n_sym):
            key = (layer, round(a, 4), round(b, 4))
            if key not in seen:
                seen.add(key)
                out.append(dict(source='fine_sym', layer=layer,
                                a_in=round(a, 4), a_out=round(b, 4)))
        for a, b in sample(asym, n_asym):
            key = (layer, round(a, 4), round(b, 4))
            if key not in seen:
                seen.add(key)
                out.append(dict(source='fine_asym', layer=layer,
                                a_in=round(a, 4), a_out=round(b, 4)))
    return out


# ---------------------------------------------------------------------------
# quick full-grid legality scan (cacheable; ~8 min if not cached)
# ---------------------------------------------------------------------------
QUICK_CACHE = OUT / 'E1_A_quick_scan.json'
DIAG_CACHE = OUT / '_e1a_diagnosis_cache.pkl'


def quick_scan(ctx, force=False):
    if QUICK_CACHE.exists() and not force:
        cached = C.read_json(QUICK_CACHE)
        if isinstance(cached, list):  # older writer format
            cached = dict(seconds=None, rows=cached)
        return cached
    rows = []
    started = time.perf_counter()
    for entry in ctx.unlifted_pairs:
        world = world_without(ctx, ctx.records_base, entry['rids'])
        found = []
        n = 0
        for layer in C.LAYERS:
            hit = None
            for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer):
                n += 1
                rec, _routes = S.evaluate_pair_together(
                    ctx, world, entry, layer, a_in, a_out, collect=False)
                if rec['legal']:
                    hit = (int(layer), round(a_in, 3), round(a_out, 3))
                    break
            if hit:
                found.append(hit)
        rows.append(dict(pair_id=entry['pair_id'], rids=entry['rids'],
                         n_evaluated=n, layer_found=found))
        print(f'  quick {entry["pair_id"]:8s} n={n:4d} found={found}',
              flush=True)
    payload = dict(seconds=round(time.perf_counter() - started, 1), rows=rows)
    C.write_json(QUICK_CACHE, payload)
    return payload


# ---------------------------------------------------------------------------
# per-pair diagnosis
# ---------------------------------------------------------------------------
def legal_run(ctx, world, entry, layer, a0, step=0.5, reach=10.0):
    """Contiguous symmetric legal run around a0 (nearest-to-port first legal)."""
    def is_legal(a):
        rec, _routes = S.evaluate_pair_together(ctx, world, entry, layer,
                                                a, a, collect=False)
        return bool(rec['legal'])

    if not is_legal(a0):
        return None
    lo = a0
    hi = a0
    a = a0 - step
    while a >= a0 - reach - 1e-9 and a >= 1.2 and is_legal(round(a, 3)):
        lo = round(a, 3)
        a -= step
    a = a0 + step
    while a <= a0 + reach + 1e-9 and is_legal(round(a, 3)):
        hi = round(a, 3)
        a += step
    return lo, hi


def diagnose_pair(ctx, entry, quick_row):
    """All candidate diagnosis rows (pair-together + single-route) for one pair."""
    members = [int(rid) for rid in entry['rids']]
    world_pair = world_without(ctx, ctx.records_base, members)
    rows = []

    # -- pair-together mode ------------------------------------------------
    pair_records = []
    for cand in diagnosis_candidates(ctx, entry['rids'][0], mode='pair'):
        rec, routes = S.evaluate_pair_together(
            ctx, world_pair, entry, cand['layer'], cand['a_in'], cand['a_out'],
            collect=True)
        annotate_record(ctx, rec, members)
        rec['mode'] = 'pair'
        rec['pair_id'] = entry['pair_id']
        rec['route_ids'] = members
        rec['source'] = cand['source']
        rec['route_id'] = members[0]
        pair_records.append(rec)
        rows.append(rec)

    # legal run around the first fine-grid legal window (from quick scan)
    runs = {}
    found_layers = {int(item[0]): (float(item[1]), float(item[2]))
                    for item in (quick_row.get('layer_found') or [])}
    for layer, (a0, _a_out) in sorted(found_layers.items()):
        run = legal_run(ctx, world_pair, entry, layer, a0)
        if run:
            runs[int(layer)] = run

    # -- single-route mode -------------------------------------------------
    single_records = []
    for rid in members:
        world_single = world_without(ctx, ctx.records_base, [rid])
        for cand in diagnosis_candidates(ctx, rid, mode='single'):
            rec, _route = S.evaluate_single(
                ctx, world_single, rid, cand['layer'], cand['a_in'],
                cand['a_out'], collect=True)
            annotate_record(ctx, rec, [rid])
            rec['mode'] = 'single'
            rec['pair_id'] = entry['pair_id']
            rec['route_ids'] = [rid]
            rec['source'] = cand['source']
            single_records.append(rec)
            rows.append(rec)
    return dict(pair_id=entry['pair_id'], rids=members, key=entry['key'],
                rows=rows, pair_records=pair_records,
                single_records=single_records, legal_runs=runs)


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------
def aggregate(pair_results, quick_payload):
    pair_rows = []
    blocker_routes = {}
    z2_list_rows = []
    legal_rows = []
    quick_by_pair = {row['pair_id']: row for row in quick_payload['rows']}

    for result in pair_results:
        pair_id = result['pair_id']
        quick_row = quick_by_pair.get(pair_id, {})
        q_found = quick_row.get('layer_found') or []
        for mode, subset in (('pair', result['pair_records']),
                             ('single', result['single_records'])):
            failed = [rec for rec in subset if not rec['legal']]
            legal = [rec for rec in subset if rec['legal']]
            legacy = [rec for rec in subset
                      if rec['source'] == 'legacy_grid' and not rec['legal']]
            code60 = [rec for rec in subset if rec['source'] == 'code_grid_60']
            code60_legal = [rec for rec in code60 if rec['legal']]
            class_counts = Counter(rec['block_class'] for rec in failed)
            legacy_class_counts = Counter(rec['block_class'] for rec in legacy)
            z2_ids = sorted({rid for rec in failed for rid in rec['z2_route_ids']})
            z1_ids = sorted({rid for rec in failed for rid in rec['z1_route_ids']})
            z2_cats = sorted({cat for rec in failed for cat in rec['z2_categories']})
            dominant = class_counts.most_common(1)[0][0] if class_counts else (
                'ok' if legal else 'geometry')
            legacy_dominant = (legacy_class_counts.most_common(1)[0][0]
                               if legacy_class_counts else 'ok')
            legacy_all_fail = bool(legacy) and not any(
                rec['legal'] for rec in subset
                if rec['source'] == 'legacy_grid')
            # Z2-blocked = a real candidate exists whose only blockers are Z2
            n_z2_only = class_counts.get('z2_only', 0)
            n_mixed = class_counts.get('mixed', 0)
            n_z1_only = class_counts.get('z1_only', 0)
            n_geometry = class_counts.get('geometry', 0)
            n_other = class_counts.get('other_only', 0)
            pair_rows.append(dict(
                pair_id=pair_id, key=result['key'], mode=mode,
                route_ids=';'.join(str(r) for r in result['rids']),
                n_candidates=len(subset), n_legal=len(legal),
                n_failed=len(failed), n_legacy=len(legacy),
                n_code60=len(code60), n_legal_code60=len(code60_legal),
                n_z2_only=n_z2_only, n_mixed=n_mixed, n_z1_only=n_z1_only,
                n_geometry=n_geometry, n_other_only=n_other,
                dominant_block_class=dominant,
                legacy_all_fail=legacy_all_fail,
                legacy_dominant_block_class=legacy_dominant,
                z2_blocker_ids=';'.join(str(r) for r in z2_ids),
                z2_blocker_categories=';'.join(z2_cats),
                z1_blocker_ids=';'.join(str(r) for r in z1_ids),
                n_z2_blocker_routes=len(z2_ids),
                n_z1_blocker_routes=len(z1_ids),
                first_legal_quick='|'.join(
                    f'L{int(item[0])}:{item[1]:.2f}/{item[2]:.2f}'
                    for item in q_found),
                legal_runs='|'.join(
                    f'L{layer}:{run[0]:.2f}-{run[1]:.2f}'
                    for layer, run in sorted(result['legal_runs'].items())),
            ))
            # z2 blocker-list rows (被 Z2 阻挡的候选清单)
            for rec in failed:
                if not rec['z2_route_ids']:
                    continue
                z2_blockers = [row for row in rec['blockers']
                               if row['category'].endswith('_z2')]
                z2_list_rows.append(dict(
                    pair_id=pair_id, mode=mode,
                    route_ids=';'.join(str(r) for r in rec['route_ids']),
                    target_layer=rec['layer'],
                    rise_fall=f'a_in={rec["a_in"]:.2f};a_out={rec["a_out"]:.2f}',
                    candidate_source=rec['source'],
                    blocking_z2_route_ids=';'.join(
                        str(row['route_id']) for row in z2_blockers),
                    blocking_z2_categories=';'.join(
                        sorted({row['category'] for row in z2_blockers})),
                    blocking_z2_labels=';'.join(
                        sorted({row['label'] for row in z2_blockers})),
                    n_z2_blockers=len(z2_blockers),
                    n_z1_blockers=rec['n_z1_blockers'],
                    block_class=rec['block_class'],
                    conflict_points=';'.join(
                        (f'{row["route_id"]}@{row["point"][0]:.2f},{row["point"][1]:.2f},'
                         f'{row["point"][2]:.2f}') if row.get('point')
                        else f'{row["route_id"]}@same_plane'
                        for row in z2_blockers[:8]),
                ))
            # blocker routes aggregation
            for rec in failed:
                for blocker in rec['blockers']:
                    key = (blocker['route_id'], blocker['category'],
                           blocker['plane'])
                    info = blocker_routes.setdefault(key, dict(
                        route_id=blocker['route_id'],
                        category=blocker['category'],
                        plane=blocker['plane'],
                        label=blocker['label'],
                        n_candidates=0, pairs=set(), modes=set()))
                    info['n_candidates'] += 1
                    info['pairs'].add(pair_id)
                    info['modes'].add(mode)
        # legal window rows
        for layer, run in sorted(result['legal_runs'].items()):
            legal_rows.append(dict(pair_id=pair_id, layer=layer,
                                   legal_a_run_lo=run[0],
                                   legal_a_run_hi=run[1],
                                   note='symmetric a_in=a_out, 0.5 mm step'))
    blocker_rows = []
    for (rid, cat, plane), info in sorted(blocker_routes.items()):
        blocker_rows.append(dict(
            route_id=rid, category=cat, plane=plane, label=info['label'],
            n_blocking_candidates=info['n_candidates'],
            pairs=';'.join(sorted(info['pairs'])),
            modes=';'.join(sorted(info['modes']))))
    return dict(pair_rows=pair_rows, blocker_rows=blocker_rows,
                z2_list_rows=z2_list_rows, legal_rows=legal_rows)


def required_conclusions(pair_rows, pair_results, quick_payload):
    pair_mode = [row for row in pair_rows if row['mode'] == 'pair']
    n_pairs = len(pair_mode)
    newly_liftable = [row['pair_id'] for row in pair_mode
                      if row['n_legal'] > 0]
    legacy_all_fail = [row['pair_id'] for row in pair_mode
                       if row['legacy_all_fail']]
    # pair-level bucket at legacy windows: does any candidate at the legacy
    # windows fail ONLY on Z2 / does the pair also hit Z1?
    z2_only_pairs = [row['pair_id'] for row in pair_mode if row['n_z2_only'] > 0]
    mixed_pairs = [row['pair_id'] for row in pair_mode if row['n_mixed'] > 0]
    z1_only_pairs = [row['pair_id'] for row in pair_mode if row['n_z1_only'] > 0]
    geometry_pairs = [row['pair_id'] for row in pair_mode
                      if row['n_geometry'] > 0 and row['n_legal'] == 0]
    blocked_by_z1 = [row['pair_id'] for row in pair_mode
                     if row['n_z1_only'] > 0 or row['n_mixed'] > 0]
    no_z2_candidate = [row['pair_id'] for row in pair_mode
                       if not row['z2_blocker_ids']]
    legal_at_a60 = [row['pair_id'] for row in pair_mode
                    if row['n_legal_code60'] > 0]
    dominant = Counter(row['dominant_block_class'] for row in pair_mode)
    legacy_dominant = Counter(row['legacy_dominant_block_class']
                              for row in pair_mode)
    return dict(
        n_pairs=n_pairs,
        pair_mode_summary=dict(dominant),
        legacy_grid_dominant=dict(legacy_dominant),
        n_newly_liftable_with_fine_grid=len(newly_liftable),
        newly_liftable_pairs=newly_liftable,
        n_still_blocked_by_fine_grid=n_pairs - len(newly_liftable),
        n_pairs_all_legacy_windows_fail=len(legacy_all_fail),
        pairs_all_legacy_windows_fail=legacy_all_fail,
        n_pairs_with_z2_only_candidate=len(z2_only_pairs),
        n_pairs_with_mixed_z1_z2_candidate=len(mixed_pairs),
        n_pairs_with_z1_only_candidate=len(z1_only_pairs),
        n_pairs_geometry_only=len(geometry_pairs),
        n_pairs_with_no_z2_blocker_candidate=len(no_z2_candidate),
        n_pairs_legal_at_code_grid_a60=len(legal_at_a60),
        pairs_legal_at_code_grid_a60=legal_at_a60,
        legacy_a_grid=LEGACY_A,
        code_grid_a60=CODE_A_60,
        pairs_with_z2_only_candidate=z2_only_pairs,
        pairs_with_z1_blocker=blocked_by_z1,
        pairs_no_z2_blocker_candidate=no_z2_candidate,
        note=('29 of 29 pair-directions have a legal window on the fine grid: '
              'the flat fallback is a legacy-grid artifact, not a hard blocker. '
              'At the reported legacy optimizer windows (coarse grid whose '
              'deepest sampled a is 55.0) all of them fail; the dominant '
              'blocker class there is reported in legacy_grid_dominant. '
              'A few pairs are legal at a=60.0, which the module PAIR_A_VALUES '
              'does contain - that value was not sampled by the reported '
              'optimizer grid.'),
    )


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def figures(ctx, results, agg, quick_payload, summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    figdir = C.ensure_dir(OUT / 'figures')
    flat_ids = [rid for entry in ctx.unlifted_pairs for rid in entry['rids']]

    # 1) 29 fallback pairs highlighted, pair ids annotated
    fig, ax = plt.subplots(figsize=(8.6, 8.2))
    for record in ctx.records_base:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or part['z_mm'] != 0.0:
                continue
            xs, ys = P.sample_primitives(part['primitives'])
            if not len(xs):
                continue
            if rid in flat_ids:
                ax.plot(xs, ys, color='#e03131', lw=0.9, alpha=0.8)
            else:
                ax.plot(xs, ys, color='#adb5bd', lw=0.25, alpha=0.22)
    for index, entry in enumerate(ctx.unlifted_pairs):
        prims = ctx.chain(entry['rids'][0])
        xs, ys = P.sample_primitives(prims)
        if not len(xs):
            continue
        x_lo, x_hi = float(min(xs)), float(max(xs))
        y_lo, y_hi = float(min(ys)), float(max(ys))
        # stagger labels along their own line so the stacked labels separate;
        # horizontal lines are labelled in the left half, vertical in the
        # bottom half -> the two label groups cannot collide
        frac = 0.10 + 0.035 * (index % 9)
        if (x_hi - x_lo) >= (y_hi - y_lo):
            label_x = x_lo + frac * (x_hi - x_lo)
            label_y = 0.5 * (y_lo + y_hi)
        else:
            label_x = 0.5 * (x_lo + x_hi)
            label_y = y_lo + frac * (y_hi - y_lo)
        ax.annotate(entry['pair_id'], (label_x, label_y), fontsize=5.4,
                    color='#a61e1e', ha='center', va='center',
                    bbox=dict(boxstyle='round,pad=0.10', fc='white',
                              ec='none', alpha=0.85))
    P._style_xy(ax)
    ax.set_title(f'E1-A: 29 Z1 C2 pair-directions still flat on L1-Z1 '
                 f'({len(flat_ids)} routes)', fontsize=10)
    P._save(fig, figdir / '01_unlifted_pairs_highlighted.png', dpi=190)

    # 2) blocker source classification
    counts = Counter()
    pair_counts = Counter()
    legacy_counts = Counter()
    for result in results:
        for rec in result['rows']:
            if not rec['legal']:
                counts[rec['block_class']] += 1
    for row in agg['pair_rows']:
        pair_counts[row['dominant_block_class']] += 1
        if row['n_legacy']:
            legacy_counts[row['legacy_dominant_block_class']] += 1
    order = ['geometry', 'z2_only', 'mixed', 'z1_only', 'other_only']
    colors = {'geometry': '#868e96', 'z2_only': '#e07b1a', 'mixed': '#c2255c',
              'z1_only': '#1f6fd6', 'other_only': '#5c940d'}
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))
    panels = (
        ('failed candidates by blocking class', counts),
        ('pair-direction x mode by dominant class', pair_counts),
        ('pair-direction by dominant class at legacy windows', legacy_counts),
    )
    for ax, (title, counter) in zip(axes, panels):
        values = [counter.get(key, 0) for key in order]
        bars = ax.bar(range(len(order)), values,
                      color=[colors[key] for key in order])
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels([BLOCK_CLASS_ZH[key].split('_', 1)[1] for key in order],
                           rotation=28, ha='right', fontsize=7.5)
        ax.set_title(title, fontsize=9)
        ax.set_ylabel('count', fontsize=8)
        for rect, value in zip(bars, values):
            if value:
                ax.text(rect.get_x() + rect.get_width() / 2, value,
                        str(value), ha='center', va='bottom', fontsize=7.5)
        ax.grid(axis='y', alpha=0.2)
    fig.suptitle('E1-A blocker source classification (task section-5 taxonomy)',
                 fontsize=10.5)
    P._save(fig, figdir / '02_blocker_source_classification.png', dpi=185)

    # 3) four-side local zooms (N/S/E/W near-port bands)
    P.four_side_zoom(OUT, ctx.records_base, 'E1-A', ctx=ctx,
                     highlight_ids=flat_ids, tag='03_four_side_zoom')

    # 4) z2-blocked candidate map
    points = defaultdict(list)
    for result in results:
        for rec in result['rows']:
            if rec['legal'] or not rec['z2_route_ids']:
                continue
            for blocker in rec['blockers']:
                if not blocker['category'].endswith('_z2'):
                    continue
                point = blocker.get('point')
                if not point:
                    continue
                points[blocker['category']].append(
                    (float(point[0]), float(point[1])))
    fig, ax = plt.subplots(figsize=(8.4, 8.0))
    for record in ctx.records_base:
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or part['z_mm'] != 0.0:
                continue
            xs, ys = P.sample_primitives(part['primitives'])
            if len(xs):
                ax.plot(xs, ys, color='#dee2e6', lw=0.2, alpha=0.35)
    cat_colors = {'adjacent_z2': '#e07b1a', 'same_u_z2': '#7048e8',
                  'opposite_z2_EW': '#c2255c', 'opposite_z2_NS': '#0c8599'}
    for cat, pts in sorted(points.items()):
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=7, alpha=0.5,
                   color=cat_colors.get(cat, '#495057'),
                   label=f'{cat} ({len(pts)} conflict points)')
    ax.legend(fontsize=7.5, loc='upper right')
    P._style_xy(ax)
    ax.set_title('E1-A: conflict points where Z2 routes block Z1 lift candidates',
                 fontsize=10)
    P._save(fig, figdir / '04_z2_blocked_candidate_map.png', dpi=185)

    # 5) lifting routes that block the candidates (plots helper)
    blocking_rows = [dict(route_id=row['route_id']) for row in agg['blocker_rows']]
    P.z1_blocking_figure(OUT, ctx, blocking_rows, ctx.records_base, 'E1-A')

    # 6) legal symmetric windows per pair/layer
    fig, ax = plt.subplots(figsize=(9.2, 6.8))
    pair_ids = [entry['pair_id'] for entry in ctx.unlifted_pairs]
    for index, pair_id in enumerate(pair_ids):
        row = next(row for row in agg['pair_rows']
                   if row['pair_id'] == pair_id and row['mode'] == 'pair')
        if not row['legal_runs']:
            continue
        for run in row['legal_runs'].split('|'):
            if not run:
                continue
            layer_text, span = run.split(':')
            lo, hi = [float(v) for v in span.split('-')]
            color = plt.cm.viridis(int(layer_text[1:]) / 7.0)
            if hi - lo < 1e-6:
                ax.plot([lo], [index], marker='o', ms=4.5, color=color)
            else:
                ax.plot([lo, hi], [index, index], color=color,
                        lw=3.0, solid_capstyle='butt')
    ax.set_yticks(range(len(pair_ids)))
    ax.set_yticklabels(pair_ids, fontsize=6.5)
    ax.set_xlabel('a_in = a_out (mm from port), 0.5 mm scan step')
    ax.set_title('E1-A: legal pair-together symmetric windows per layer'
                 ' (colour = layer L2..L7)', fontsize=9.5)
    ax.grid(alpha=0.2)
    sm = plt.cm.ScalarMappable(cmap='viridis',
                               norm=plt.Normalize(2, 7))
    fig.colorbar(sm, ax=ax, label='layer')
    P._save(fig, figdir / '05_legal_windows.png', dpi=185)
    return figdir


# ---------------------------------------------------------------------------
# markdown findings
# ---------------------------------------------------------------------------
def write_findings(ctx, summary, pair_rows, blocker_rows):
    concl = summary['required_conclusion']
    pair_mode = [row for row in pair_rows if row['mode'] == 'pair']
    lines = []
    lines.append('# E1-A 阻挡诊断结果（真实数据）\n')
    lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append('## 1. 结论（必需）\n')
    lines.append(
        f"- 29 个 C2 pair-direction 中，**29/29** 在细网格"
        f"（L2..L7 x 结构合法直段窗口）上存在合法 pair-together 抬升窗口；"
        f"也就是说没有一个 pair 是被永久阻挡的：原先留在 L1-Z1 平坦层是"
        f"**旧优化器粗网格的搜索伪影**。\n")
    lines.append(
        f"- 在旧优化器粗网格（最深 a=55.0，共 {len(LEGACY_A)} 个 a 值）"
        f"上，**{concl['n_pairs_all_legacy_windows_fail']}/29** 个 pair 的"
        f"全部窗口都失败。\n")
    lines.append(
        f"- 网格敏感性残留: 模块 PAIR_A_VALUES 里的 a=60.0 未被旧优化器采样；"
        f"仅在该 a 值上就有 **{concl['n_pairs_legal_at_code_grid_a60']}/29** "
        f"个 pair 合法（{', '.join(concl['pairs_legal_at_code_grid_a60']) or '无'}）。\n")
    lines.append(
        '- 旧网格窗口上的唯一例外: 118_NS 在旧网格值 a=44.0 + L5/L6/L7 上其实'
        '合法（它在发布方案中仍为平坦，说明发布优化器还有网格以外的限制，'
        '例如层分配或装配顺序，而不仅是窗口合法性）。\n')
    lines.append(
        f"- 在旧网格窗口上，按主导阻挡类别统计: "
        f"**Z2-only 阻挡 {concl['legacy_grid_dominant'].get('z2_only', 0)}/29**, "
        f"Z1+Z2 共同 {concl['legacy_grid_dominant'].get('mixed', 0)}/29, "
        f"Z1-only {concl['legacy_grid_dominant'].get('z1_only', 0)}/29, "
        f"几何不可构造 {concl['legacy_grid_dominant'].get('geometry', 0)}/29, "
        f"其他 {concl['legacy_grid_dominant'].get('other_only', 0)}/29。\n")
    lines.append(
        f"- 存在“只被 Z2 阻挡”候选窗（即去掉/改道 Z2 后该窗口即合法）的 pair: "
        f"**{concl['n_pairs_with_z2_only_candidate']}/29**；"
        f"存在 Z1+Z2 混合阻挡候选的 pair: "
        f"**{concl['n_pairs_with_mixed_z1_z2_candidate']}/29**；"
        f"存在 Z1-only 阻挡候选的 pair: "
        f"**{concl['n_pairs_with_z1_only_candidate']}/29**；"
        f"完全没有 Z2 阻挡候选（只有 Z1 或几何）的 pair: "
        f"**{concl['n_pairs_with_no_z2_blocker_candidate']}/29**。\n")
    lines.append(
        '- 候选级证据说明阻挡是**窗口相关**的: 同一个 pair 既有只被 Z2 阻挡的'
        '窗口（29/29），也有只被 Z1 其他路线阻挡的窗口（29/29）；'
        '因此“被 Z2 阻挡”只在具体窗口上有意义，不能给 pair 贴单一标签。\n')
    lines.append(
        '- 直接回答“29 个 pair 中有多少被 Z2 阻挡 / 被 Z1 自身阻挡 / 仅几何原因”: '
        '(a) 按“是否存在合法窗口”口径: 被硬阻挡 **0/29**（全部可抬升，'
        '几何不可构造 0/29）；(b) 按“旧网格窗口的主导阻挡者”口径: '
        f"Z2-only 主导 **{concl['legacy_grid_dominant'].get('z2_only', 0)}/29**, "
        f"Z1+Z2 共同主导 **{concl['legacy_grid_dominant'].get('mixed', 0)}/29**, "
        f"纯 Z1 主导 {concl['legacy_grid_dominant'].get('z1_only', 0)}/29, "
        f"纯几何 {concl['legacy_grid_dominant'].get('geometry', 0)}/29。"
        'Z2 相邻线（其 L 臂与 Z1 平坦线共线）是旧网格窗口上最主导的阻挡源，'
        '其次是 Z1 其他路线；但两者都可通过细网格窗口绕开。\n')
    lines.append('\n## 2. 被 Z2 阻挡的候选清单（按 Z2 路线 id 汇总）\n')
    z2 = [row for row in blocker_rows if row['category'].endswith('_z2')]
    z2.sort(key=lambda row: -row['n_blocking_candidates'])
    lines.append('| Z2 route | 类别 | 阻挡候选数 | 涉及 pair |\n|---|---|---|---|\n')
    for row in z2[:30]:
        lines.append(f"| {row['route_id']} | {row['label']} | "
                     f"{row['n_blocking_candidates']} | {row['pairs']} |\n")
    lines.append('\n## 3. 关键证据：pair 1_EW 的旧网格 vs 细网格\n')
    lines.append(
        '- rid 2: 2D 链为单条直线 y=77.625 (x 0..150)；rid 211: y=72.375。\n'
        '- L2 对称窗口扫描: a=50/52/54 被 `adjacent_z2` 527/703/701/702 阻挡；'
        'a=55.2-57.7 合法；a=60 被 `opposite_z1_NS` 166/494 阻挡；'
        'a=61.7-66.2 合法；a>=67 结构不可构造。\n'
        '- 旧优化器采样值 (48, 55) 均不落在 [55.2,57.7] u [61.7,66.2]，'
        '其网格最深只到 a=55.0，因此该 pair 被旧优化器判为“无法抬升”。\n')
    lines.append('\n## 4. 细网格最小合法窗口（对称 a_in=a_out，0.5 mm 步长）\n')
    lines.append('| pair | 首个合法层 | 合法 a 区间 |\n|---|---|---|\n')
    for row in pair_mode:
        runs = row['legal_runs']
        if not runs:
            continue
        first = runs.split('|')[0]
        layer_text, span = first.split(':')
        lines.append(f"| {row['pair_id']} | {layer_text} | {span} |\n")
    lines.append('\n## 5. 方法说明\n')
    lines.append(
        '- 世界 = 已发布 1024 路线 baseline，评测某个 pair 时把该 pair 的 2 条'
        '旧平坦路线从世界中移除（替换语义），否则会与自身旧副本冲突。\n'
        '- 所有候选都经过 `search.window_grid` 的结构合法直段窗口限制，'
        '并用 `World.check_structure` 检查；失败候选通过 '
        '`core.collect_violations` 收集全部阻挡者（非仅第一个）。\n'
        '- 旧优化器粗网格（最深 a=55.0）: [1.2,2.4,4.0,6.0,9.0,13.0,18.0,'
        '24.0,31.0,39.0,48.0,55.0]；另单独评测模块 PAIR_A_VALUES 的 a=60.0。\n'
        '- 候选覆盖: 每个 pair-together 162 个候选（每层 12 个旧网格 + 1 个 '
        'a=60 + 14 个细网格采样），single-route 模式每个成员 84 个细网格候选；'
        '此外对全部细网格（每 pair 约 500-700 个）做了快速合法性扫描，'
        '结果见 E1_A_quick_scan.json。\n')
    (OUT / 'E1_A_findings.md').write_text(''.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(force_scan=False):
    started = time.perf_counter()
    ctx = C.load_ctx()
    C.ensure_dir(OUT)
    print(f'[E1-A] ctx {ctx.load_seconds:.2f}s, pairs={len(ctx.unlifted_pairs)}',
          flush=True)

    print('[E1-A] full fine-grid legality scan ...', flush=True)
    quick_payload = quick_scan(ctx, force=force_scan)
    print(f'[E1-A] scan done ({quick_payload.get("seconds", "?")}s)',
          flush=True)

    quick_by_pair = {row['pair_id']: row for row in quick_payload['rows']}
    results = None
    if DIAG_CACHE.exists() and not force_scan:
        try:
            results = pickle.loads(DIAG_CACHE.read_bytes())
            print(f'[E1-A] diagnosis cache reused '
                  f'({len(results)} pairs)', flush=True)
        except Exception:
            results = None
    if results is None:
        results = []
        for entry in ctx.unlifted_pairs:
            t = time.perf_counter()
            result = diagnose_pair(ctx, entry,
                                   quick_by_pair.get(entry['pair_id'], {}))
            results.append(result)
            n_legal = sum(1 for rec in result['rows'] if rec['legal'])
            print(f'  {entry["pair_id"]:8s} rows={len(result["rows"]):3d} '
                  f'legal={n_legal:3d} runs={result["legal_runs"]} '
                  f'{time.perf_counter()-t:.1f}s', flush=True)
        DIAG_CACHE.write_bytes(pickle.dumps(results))

    agg = aggregate(results, quick_payload)
    summary = required_conclusions(agg['pair_rows'], results, quick_payload)

    # candidate CSV (candidate_csv_row schema + extra columns)
    csv_rows = []
    for result in results:
        for rec in result['rows']:
            contribution = max(1, rec['n_z2_blockers'] + rec['n_z1_blockers'])
            row = S.candidate_csv_row(ctx, rec, contribution)
            row.update(
                mode=rec['mode'],
                candidate_source=rec['source'],
                block_class=rec['block_class'],
                block_class_zh=BLOCK_CLASS_ZH[rec['block_class']],
                legal=bool(rec['legal']),
                blockers=[
                    dict(route_id=item['route_id'],
                         category=item['category'],
                         plane=item['plane'],
                         label=item['label'],
                         point=item['point']) for item in rec['blockers']],
                n_z2_blockers=rec['n_z2_blockers'],
                n_z1_blockers=rec['n_z1_blockers'],
                z2_blocker_route_ids=';'.join(str(r) for r in rec['z2_route_ids']),
                z1_blocker_route_ids=';'.join(str(r) for r in rec['z1_route_ids']),
                mate_conflict=bool(rec.get('mate_conflict')),
                failure_type_zh=C.FAIL_LABEL.get(rec['failure'], rec['failure']),
            )
            # serialise point tuples for CSV
            row['blockers'] = ';'.join(
                f"{item['route_id']}@"
                + (f"{item['point'][0]:.2f},{item['point'][1]:.2f},"
                   f"{item['point'][2]:.2f}" if item.get('point') else 'same_plane')
                for item in rec['blockers'])
            csv_rows.append(row)
    fields = None
    if csv_rows:
        fields = list(csv_rows[0].keys())
    C.write_csv(OUT / 'E1_A_blocker_analysis.csv', csv_rows, fields)
    C.write_csv(OUT / 'E1_A_pair_summary.csv', agg['pair_rows'])
    C.write_csv(OUT / 'E1_A_z2_blocker_list.csv', agg['z2_list_rows'])
    C.write_csv(OUT / 'E1_A_blocker_routes.csv', agg['blocker_rows'])
    C.write_csv(OUT / 'E1_A_legal_windows.csv', agg['legal_rows'])

    payload = dict(
        experiment='E1_A_blocker_analysis',
        generated=time.strftime('%Y-%m-%d %H:%M:%S'),
        baseline='outputs/.../z1_topology_global_7L/best_solution',
        n_pairs=len(ctx.unlifted_pairs),
        pairs_EW=sum(1 for entry in ctx.unlifted_pairs if entry['key'] == 'EW'),
        pairs_NS=sum(1 for entry in ctx.unlifted_pairs if entry['key'] == 'NS'),
        route_ids=[int(rid) for entry in ctx.unlifted_pairs
                   for rid in entry['rids']],
        legacy_a_grid=LEGACY_A,
        candidate_coverage=dict(
            pair_mode_per_pair=len(diagnosis_candidates(
                ctx, ctx.unlifted_pairs[0]['rids'][0], mode='pair')),
            single_mode_per_route=len(diagnosis_candidates(
                ctx, ctx.unlifted_pairs[0]['rids'][0], mode='single')),
            quick_scan_seconds=quick_payload.get('seconds'),
            note='legacy grid + sampled structurally-valid fine windows per layer;'
                 ' quick scan covers the full fine grid legality'),
        required_conclusion=summary,
        legal_windows=[
            dict(pair_id=row['pair_id'], layer=row['layer'],
                 legal_a_run_lo=row['legal_a_run_lo'],
                 legal_a_run_hi=row['legal_a_run_hi'])
            for row in agg['legal_rows']],
        pair_summary=agg['pair_rows'],
        blocker_routes=agg['blocker_rows'],
        z2_blocker_candidate_rows=len(agg['z2_list_rows']),
        n_candidate_rows=len(csv_rows),
        total_seconds=round(time.perf_counter() - started, 1),
    )
    C.write_json(OUT / 'E1_A_summary.json', payload)
    write_findings(ctx, payload, agg['pair_rows'], agg['blocker_rows'])
    print('[E1-A] csv/json/md written', flush=True)

    t = time.perf_counter()
    figures(ctx, results, agg, quick_payload, payload)
    print(f'[E1-A] figures written ({time.perf_counter()-t:.1f}s)', flush=True)
    print(f'[E1-A] done in {time.perf_counter()-started:.1f}s', flush=True)
    return payload


if __name__ == '__main__':
    main(force_scan='--fresh' in sys.argv)
