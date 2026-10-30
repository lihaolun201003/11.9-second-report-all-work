# -*- coding: utf-8 -*-
"""E1-B1 / E1-B2: DIAGNOSTIC Z2-removal experiments.

Both experiments keep the complete published Z1 layout and ask the same
question: with (part of) the Z2 interface layer removed from the clearance
world, how many of the 29 still-flat Z1 C2 pair-directions can be lifted, with
which minimal windows, and what residual crossing load remains?

  E1-B1_remove_all_z2      : remove ALL 512 Z2 routes (same_u_z2 + adjacent_z2
                             + opposite_z2); keep the 512 Z1 routes.
  E1-B2_remove_movable_z2  : remove only the movable Z2 routes
                             (same_u_z2 192 + opposite_z2 8 = 200); keep the
                             312 z2 adjacent L-routes, which are the collinear
                             barriers identified in E1-A.

Greedy application: the 29 pair-directions are visited in the published pair
order; each pair is lifted pair-together (same window both members) with the
nearest-to-port legal window against the current world, then committed.  As a
fallback the independent-window mode is evaluated.  Because Z2 routes are
missing, the resulting 512/824-route payloads are DIAGNOSTIC ONLY and are
explicitly saved as not validated.  They are never a valid 1024-channel
solution.
"""
from __future__ import annotations

import csv
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, '.')

from four_side_1024.e1 import core as C
from four_side_1024.e1 import plots as P
from four_side_1024.e1 import search as S
from four_side_1024.e1 import run_e1a as A

OUT_ROOT = C.E1
EXPERIMENTS = {
    'E1_B1_remove_all_z2': dict(
        name='E1_B1',
        title='B1: all Z2 removed',
        keep_cats={'adjacent_z1', 'same_u_z1', 'opposite_z1_EW',
                   'opposite_z1_NS'},
        note=('DIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION. '
              'All 512 Z2 routes are removed from the world; only the 512 Z1 '
              'routes are present (58 of them lifted).')),
    'E1_B2_remove_movable_z2': dict(
        name='E1_B2',
        title='B2: movable Z2 removed (adjacent Z2 kept)',
        keep_cats={'adjacent_z1', 'same_u_z1', 'opposite_z1_EW',
                   'opposite_z1_NS', 'adjacent_z2'},
        note=('DIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION. '
              'same_u_z2 (192) + opposite_z2 (8) removed; the 312 z2 adjacent '
              'L-routes are kept. 824/1024 routes present.')),
}
BANNER = ('=' * 78 + '\nDIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION\n'
          'This directory is a Z2-removal diagnostic, not a router solution.\n'
          'The payload in routes_1024.json intentionally misses Z2 routes and\n'
          'is saved as "not_validated". Do NOT use it as a deliverable.\n'
          + '=' * 78 + '\n')


# ---------------------------------------------------------------------------
# greedy pair lifting
# ---------------------------------------------------------------------------
def independent_pair(ctx, world, entry, max_candidates=200):
    """Independent-window mode: each member with its own (layer, a_in, a_out)."""
    hits = []
    n = 0
    for rid in entry['rids']:
        hit = None
        for layer in C.LAYERS:
            for a_in, a_out in S.window_grid(ctx, rid, layer):
                n += 1
                rec, _route = S.evaluate_single(ctx, world, rid, layer, a_in,
                                                a_out, collect=False)
                if rec['legal']:
                    hit = (int(layer), round(a_in, 4), round(a_out, 4))
                    break
                if n >= max_candidates * len(entry['rids']):
                    break
            if hit:
                break
        hits.append(hit)
    legal = False
    if all(hit is not None for hit in hits):
        routes = [ctx.lift(rid, *hit) for rid, hit in zip(entry['rids'], hits)]
        legal = not C.pairwise_violations(world, routes[0], routes[1])
    return dict(legal=legal, windows=hits, n_evaluated=n)


def diagnose_failure(ctx, world, entry, collect_cap=40):
    """Remaining failure reasons for a pair that is not liftable."""
    classes = Counter()
    sources = Counter()
    collected = 0
    for layer in C.LAYERS:
        for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer):
            rec, _routes = S.evaluate_pair_together(
                ctx, world, entry, layer, a_in, a_out,
                collect=collected < collect_cap)
            if rec['legal']:
                continue
            if rec.get('built') is False:
                classes['curvature_or_space'] += 1
                sources['geometry'] += 1
                continue
            if collected < collect_cap:
                A.annotate_record(ctx, rec, entry['rids'])
                classes[rec['failure']] += 1
                sources[rec['block_class']] += 1
                collected += 1
            else:
                classes['not_diagnosed'] += 1
    return dict(classes=dict(classes), sources=dict(sources),
                n_diagnosed=collected)


def greedy_lift(ctx, base_records):
    plan = {int(record['route_id']): record for record in base_records}
    accepted = []
    failed = []
    independent = []
    started = time.perf_counter()
    for entry in ctx.unlifted_pairs:
        members = [int(rid) for rid in entry['rids']]
        world = ctx.world([record for rid, record in plan.items()
                           if rid not in members])
        t = time.perf_counter()
        scan = A.search_pair_legal(ctx, world, entry)
        seconds = time.perf_counter() - t
        ind = independent_pair(ctx, world, entry)
        independent.append(dict(pair_id=entry['pair_id'], legal=ind['legal'],
                                windows=ind['windows'],
                                n_evaluated=ind['n_evaluated']))
        if scan['first'] is not None:
            first = scan['first']
            for rid, route in zip(members, first['routes']):
                plan[rid] = route
            accepted.append(dict(
                pair_id=entry['pair_id'], key=entry['key'],
                route_ids=';'.join(str(r) for r in members),
                layer=first['layer'], a_in=first['a_in'],
                a_out=first['a_out'],
                per_layer_windows='|'.join(
                    f'L{layer}:{span[0]:.2f}/{span[1]:.2f}'
                    for layer, span in sorted(scan['per_layer'].items())),
                n_layer_windows=len(scan['per_layer']),
                n_evaluated=scan['n_evaluated'],
                scan_seconds=round(seconds, 2),
                independent_legal=ind['legal'],
                independent_windows='|'.join(
                    'L%s:%s/%s' % (hit[0], hit[1], hit[2]) if hit else 'none'
                    for hit in ind['windows']),
            ))
            print(f'  {entry["pair_id"]:8s} L{first["layer"]} '
                  f'a={first["a_in"]:.2f}/{first["a_out"]:.2f} '
                  f'({scan["n_evaluated"]} cands, {seconds:.1f}s)'
                  f' ind={ind["legal"]}', flush=True)
        else:
            reasons = diagnose_failure(ctx, world, entry)
            failed.append(dict(pair_id=entry['pair_id'], key=entry['key'],
                               route_ids=';'.join(str(r) for r in members),
                               n_evaluated=scan['n_evaluated'],
                               independent_legal=ind['legal'],
                               independent_windows=str(ind['windows']),
                               failure_classes=str(reasons['classes']),
                               failure_sources=str(reasons['sources'])))
            print(f'  {entry["pair_id"]:8s} STILL BLOCKED '
                  f'({scan["n_evaluated"]} cands) {reasons["classes"]}',
                  flush=True)
    print(f'  greedy done in {time.perf_counter()-started:.1f}s', flush=True)
    return dict(plan=plan, accepted=accepted, failed=failed,
                independent=independent)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def pair_degrees(analysis):
    degrees = Counter()
    for event in analysis['events']:
        pair = tuple(event['pair'])
        degrees[pair[0]] += 1
        degrees[pair[1]] += 1
    unique = Counter()
    for pair in analysis['unique_pairs']:
        unique[pair[0]] += 1
        unique[pair[1]] += 1
    return unique


def metrics(ctx, records, base_records, analysis, base_analysis):
    z1_cats = {'adjacent_z1', 'same_u_z1', 'opposite_z1_EW', 'opposite_z1_NS'}
    z1_records = [record for record in records
                  if ctx.cat[int(record['route_id'])] in z1_cats]
    z1_base = [record for record in base_records
               if ctx.cat[int(record['route_id'])] in z1_cats]
    analysis_z1 = C.audit(z1_records, ctx)
    base_z1 = C.audit(z1_base, ctx) if len(z1_records) != len(base_records) \
        else base_analysis
    new_degree = pair_degrees(analysis)
    base_degree = pair_degrees(base_analysis)
    changes = []
    for rid, record in ((int(r['route_id']), r) for r in records):
        delta = base_degree.get(rid, 0) - new_degree.get(rid, 0)
        if delta == 0:
            continue
        changes.append(dict(route_id=rid, category=ctx.cat.get(rid, ''),
                            plane=ctx.plane_of(rid),
                            base_crossing_partners=base_degree.get(rid, 0),
                            new_crossing_partners=new_degree.get(rid, 0),
                            delta=delta))
    changes.sort(key=lambda row: row['delta'])
    return dict(
        analysis=analysis, analysis_z1=analysis_z1, base_z1=base_z1,
        changes=changes,
        numbers=dict(
            routed=len(records),
            z1_routes=len(z1_records),
            unique_crossing_pairs=analysis['n_unique_pairs'],
            base_unique_crossing_pairs=base_analysis['n_unique_pairs'],
            delta_unique_crossing_pairs=(analysis['n_unique_pairs']
                                         - base_analysis['n_unique_pairs']),
            z1_crossing_pairs=analysis['z1_pairs'],
            base_z1_crossing_pairs=base_analysis['z1_pairs'],
            delta_z1_crossing_pairs=(analysis['z1_pairs']
                                     - base_analysis['z1_pairs']),
            z2_crossing_pairs=analysis['z2_pairs'],
            high_layer_crossing_pairs=analysis['high_pairs'],
            base_high_layer_crossing_pairs=base_analysis['high_pairs'],
            z1_subset_z1_crossing_pairs=analysis_z1['z1_pairs'],
            z1_subset_high_crossing_pairs=analysis_z1['high_pairs'],
            base_z1_subset_z1_crossing_pairs=base_z1['z1_pairs'],
            base_z1_subset_high_crossing_pairs=base_z1['high_pairs'],
            transitions=C.bar(records)['transitions'],
            base_transitions=C.bar(base_records)['transitions'],
            total_length_mm=C.bar(records)['total_length_mm'],
            base_total_length_mm=C.bar(base_records)['total_length_mm'],
        ))


# ---------------------------------------------------------------------------
# one experiment
# ---------------------------------------------------------------------------
def run_experiment(key):
    config = EXPERIMENTS[key]
    name = config['name']
    out_dir = C.ensure_dir(OUT_ROOT / key)
    C.ensure_dir(out_dir / 'figures')
    (out_dir / 'DIAGNOSTIC_ONLY_NOTE.txt').write_text(BANNER, encoding='utf-8')
    started = time.perf_counter()
    ctx = C.load_ctx()

    base_records = [record for record in ctx.records_base
                    if ctx.cat[int(record['route_id'])] in config['keep_cats']]
    kept = Counter(ctx.cat[int(record['route_id'])] for record in base_records)
    print(f'[{name}] kept routes={len(base_records)} {dict(kept)}', flush=True)
    print(f'[{name}] removed routes={1024-len(base_records)}', flush=True)

    greedy = greedy_lift(ctx, base_records)
    records = list(greedy['plan'].values())
    lifted_ids = [rid for item in greedy['accepted']
                  for rid in (int(x) for x in item['route_ids'].split(';'))]
    print(f'[{name}] lifted pairs={len(greedy["accepted"])}/29 '
          f'routes={len(lifted_ids)} failed={len(greedy["failed"])}', flush=True)

    analysis = C.audit(records, ctx)
    base_analysis = C.audit(base_records, ctx)
    stats = metrics(ctx, records, base_records, analysis, base_analysis)
    numbers = stats['numbers']
    print(f'[{name}] unique={numbers["unique_crossing_pairs"]} '
          f'(base {numbers["base_unique_crossing_pairs"]}) '
          f'z1={numbers["z1_crossing_pairs"]} '
          f'(base {numbers["base_z1_crossing_pairs"]}) '
          f'high={numbers["high_layer_crossing_pairs"]} '
          f'(base {numbers["base_high_layer_crossing_pairs"]})', flush=True)

    # --- csv -----------------------------------------------------------------
    C.write_csv(out_dir / f'{name}_minimal_windows.csv', greedy['accepted'])
    C.write_csv(out_dir / f'{name}_remaining_failures.csv', greedy['failed'])
    C.write_csv(out_dir / f'{name}_independent_mode.csv', greedy['independent'])
    C.write_csv(out_dir / f'{name}_routes_biggest_change.csv', stats['changes'])

    # --- persistence ---------------------------------------------------------
    extra = dict(
        diagnostic_only=True,
        warning=('DIAGNOSTIC ONLY - NOT A VALID 1024-CHANNEL SOLUTION'),
        experiment_kind='Z2 removal diagnostic',
        z2_removed=1024 - len(base_records),
        routes_present=len(records),
        routes_missing=1024 - len(records),
        kept_route_categories={key_: value for key_, value in kept.items()},
        removed_route_categories={
            key_: value for key_, value in Counter(ctx.cat.values()).items()
            if key_ not in config['keep_cats']},
        lifted_pairs=len(greedy['accepted']),
        lifted_pair_ids=[item['pair_id'] for item in greedy['accepted']],
        lifted_route_ids=lifted_ids,
        lifted_route_count=len(lifted_ids),
        failed_pairs=len(greedy['failed']),
        failed_pair_ids=[item['pair_id'] for item in greedy['failed']],
        independent_mode_legal_pairs=sum(
            1 for item in greedy['independent'] if item['legal']),
        z1_only_audit=dict(
            z1_crossing_pairs=numbers['z1_subset_z1_crossing_pairs'],
            high_layer_crossing_pairs=numbers['z1_subset_high_crossing_pairs'],
            base_z1_crossing_pairs=numbers['base_z1_subset_z1_crossing_pairs'],
            base_high_layer_crossing_pairs=numbers[
                'base_z1_subset_high_crossing_pairs']),
        residual=numbers,
        greedy_seconds=round(time.perf_counter() - started, 1),
        validation='not_validated (diagnostic Z2-removal payload, '
                   '512/824 of 1024 routes present)',
    )
    summary, report, analysis2 = C.save_experiment(
        name, records, ctx, folder=out_dir, extra=extra, validate=False,
        note=config['note'])
    C.write_json(out_dir / 'summary.json', dict(summary))
    C.write_json(out_dir / f'{name}_metrics.json', dict(
        numbers=numbers,
        lifted_pairs=[dict(pair_id=item['pair_id'],
                           layer=item['layer'],
                           a_in=item['a_in'], a_out=item['a_out'],
                           per_layer_windows=item['per_layer_windows'])
                      for item in greedy['accepted']],
        failed_pairs=greedy['failed'],
        independent_mode=greedy['independent'],
        removed_routes=1024 - len(base_records),
        present_routes=len(records),
        diagnostic_only=True,
    ))

    # --- figures -------------------------------------------------------------
    t = time.perf_counter()
    P.standard_figures(out_dir, records, ctx, f'{name} ({config["title"]})',
                       baseline_records=base_records, diagnostic=True,
                       highlight_ids=lifted_ids, analysis=analysis2,
                       baseline_analysis=base_analysis,
                       note=BANNER)
    P.four_side_zoom(out_dir, records, f'{name} DIAGNOSTIC', ctx=ctx,
                     highlight_ids=lifted_ids, tag='four_side_zoom')
    print(f'[{name}] figures {time.perf_counter()-t:.1f}s', flush=True)

    # --- markdown findings ---------------------------------------------------
    write_findings(name, config, out_dir, greedy, numbers, stats)
    print(f'[{name}] done in {time.perf_counter()-started:.1f}s', flush=True)
    return dict(name=name, dir=str(out_dir), lifted_pairs=len(greedy['accepted']),
                failed_pairs=len(greedy['failed']),
                lifted_routes=len(lifted_ids), numbers=numbers,
                accepted=[dict(pair_id=item['pair_id'], layer=item['layer'],
                               a_in=item['a_in'], a_out=item['a_out'],
                               n_layer_windows=item['n_layer_windows'])
                          for item in greedy['accepted']],
                independent_legal=sum(1 for item in greedy['independent']
                                      if item['legal']))


def write_findings(name, config, out_dir, greedy, numbers, stats):
    lines = ['# %s 诊断结果 (DIAGNOSTIC ONLY)\n\n' % name, BANNER, '\n']
    lines.append(f"- 保留路线: {numbers['routed']}/1024; 移除 Z2 路线 "
                 f"{1024-numbers['routed']} 条 (这不是合法的 1024 通道方案)\n")
    lines.append(f"- 29 个 C2 pair-direction 中贪心抬升成功: "
                 f"**{len(greedy['accepted'])}/29** "
                 f"({numbers['routed'] and len(greedy['accepted'])*2} 条 Z1 路线); "
                 f"失败: {len(greedy['failed'])}\n")
    lines.append(f"- 独立窗口模式(pair 两成员各自窗口)合法: "
                 f"**{sum(1 for i in greedy['independent'] if i['legal'])}/29**\n")
    lines.append('\n## 关键数字 (诊断世界 vs 同保留集合未抬升基线)\n\n')
    rows = [
        ('unique crossing pairs', 'unique_crossing_pairs',
         'base_unique_crossing_pairs'),
        ('Z1 (z=0) crossing pairs', 'z1_crossing_pairs',
         'base_z1_crossing_pairs'),
        ('high-layer crossing pairs', 'high_layer_crossing_pairs',
         'base_high_layer_crossing_pairs'),
        ('Z1-only subset: Z1 pairs', 'z1_subset_z1_crossing_pairs',
         'base_z1_subset_z1_crossing_pairs'),
        ('Z1-only subset: high pairs', 'z1_subset_high_crossing_pairs',
         'base_z1_subset_high_crossing_pairs'),
        ('transitions', 'transitions', 'base_transitions'),
        ('total length mm', 'total_length_mm', 'base_total_length_mm'),
    ]
    lines.append('| metric | base (same kept set, unlifted) | %s | delta |\n'
                 '|---|---|---|---|\n' % name)
    for label, new_key, base_key in rows:
        new = numbers[new_key]
        base = numbers[base_key]
        delta = round(new - base, 4)
        lines.append(f'| {label} | {base} | {new} | {delta} |\n')
    lines.append('\n## 抬升窗口 (pair-together, 最近端口合法窗口)\n\n')
    lines.append('| pair | layer | a_in | a_out | 合法层数 | 候选数 |\n'
                 '|---|---|---|---|---|---|\n')
    for item in greedy['accepted']:
        per_layer = item.get('per_layer_windows') or ''
        n_layers = item.get('n_layer_windows') or (
            len(per_layer.split('|')) if per_layer else '')
        n_eval = item.get('n_evaluated', '-')
        lines.append(f"| {item['pair_id']} | L{item['layer']} | "
                     f"{item['a_in']:.2f} | {item['a_out']:.2f} | "
                     f"{n_layers} | {n_eval} |\n")
    if greedy['failed']:
        lines.append('\n## 剩余失败原因\n\n')
        for item in greedy['failed']:
            lines.append(f"- {item['pair_id']}: {item['failure_classes']} "
                         f"(来源 {item['failure_sources']})\n")
    else:
        lines.append('\n## 剩余失败原因\n\n- 无: 在去掉相应 Z2 路线后，'
                     '29/29 pair 均可在当前世界中抬升。\n')
    change_path = out_dir / f'{name}_routes_biggest_change.csv'
    if change_path.exists():
        with change_path.open(encoding='utf-8-sig') as handle:
            changes = list(csv.DictReader(handle))
        lines.append('\n## 交叉伙伴数变化最大的路线\n\n'
                     'delta = base - new（负 = 新世界交叉伙伴变多，正 = 减少）。\n\n'
                     '| route | category | base partners | new partners | delta |\n'
                     '|---|---|---|---|---|\n')
        for row in changes[:8]:
            lines.append(f"| {row['route_id']} | {row['category']} | "
                         f"{row['base_crossing_partners']} | "
                         f"{row['new_crossing_partners']} | {row['delta']} |\n")
        reductions = [row for row in changes if int(row['delta']) > 0]
        if reductions:
            lines.append('\n交叉伙伴减少最多的路线:\n\n'
                         '| route | category | base partners | new partners | delta |\n'
                         '|---|---|---|---|---|\n')
            for row in reductions[-5:]:
                lines.append(f"| {row['route_id']} | {row['category']} | "
                             f"{row['base_crossing_partners']} | "
                             f"{row['new_crossing_partners']} | {row['delta']} |\n")
    lines.append('\n## 说明\n\n'
                 '- 世界 = baseline 去掉被移除的 Z2 类别；评测 pair 时把该 pair '
                 '旧平坦路线从世界中移除（替换语义）。\n'
                 '- 抬升顺序 = 已发布 pair 顺序，贪心接受后立即提交；'
                 '后续 pair 的合法性检查包含前面已抬升的路线。\n'
                 '- 抬升窗口 = `search.window_grid` 顺序中的第一个合法窗口'
                 '（按基段长度最短排序，即最近端口窗口），不是按新产生交叉数'
                 '优化的窗口；高层的残余交叉数因此只反映该选取策略。\n'
                 '- 独立窗口模式为快速检查（每个成员最多 200 个候选、取首个合法'
                 '窗口，再做两成员 pairwise 检查），不是独立的穷举搜索。\n'
                 '- 本目录为诊断输出，routes_1024.json 未通过 1024 通道校验 '
                 '(validation.json status=not_validated)。\n')
    (out_dir / f'{name}_findings.md').write_text(''.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# side-by-side comparison (B1 vs B2)
# ---------------------------------------------------------------------------
def write_compare(result_b1, result_b2):
    payload = dict(
        diagnostic_only=True,
        note=('B1 vs B2: does removing movable Z2 unlock the flat Z1 pairs, '
              'or do the fixed adjacent Z2 L-routes form the barrier?'),
        B1=dict(lifted_pairs=result_b1['lifted_pairs'],
                lifted_routes=result_b1['lifted_routes'],
                present_routes=result_b1['numbers']['routed'],
                numbers=result_b1['numbers'],
                windows=result_b1['accepted']),
        B2=dict(lifted_pairs=result_b2['lifted_pairs'],
                lifted_routes=result_b2['lifted_routes'],
                present_routes=result_b2['numbers']['routed'],
                numbers=result_b2['numbers'],
                windows=result_b2['accepted']),
    )
    for result in (result_b1, result_b2):
        path = C.ensure_dir(result['dir']) / 'E1_B_side_by_side.json'
        C.write_json(path, payload)


def load_result(key):
    """Reconstruct the run_experiment() result dict from saved metrics."""
    config = EXPERIMENTS[key]
    name = config['name']
    out_dir = OUT_ROOT / key
    metrics = C.read_json(out_dir / f'{name}_metrics.json')
    lifted = metrics['lifted_pairs']
    return dict(
        name=name, dir=str(out_dir),
        lifted_pairs=len(lifted),
        lifted_routes=2 * len(lifted),
        failed_pairs=len(metrics['failed_pairs']),
        numbers=metrics['numbers'],
        accepted=lifted,
        independent_legal=sum(1 for item in metrics['independent_mode']
                              if item['legal']),
        metrics=metrics,
    )


def compare_from_files():
    b1 = load_result('E1_B1_remove_all_z2')
    b2 = load_result('E1_B2_remove_movable_z2')
    write_compare(b1, b2)
    print('[E1-B] side-by-side written from saved metrics', flush=True)


def refind():
    """Rewrite the findings markdown from saved metrics (no re-run)."""
    for key, config in EXPERIMENTS.items():
        result = load_result(key)
        metrics = result['metrics']
        greedy = dict(accepted=metrics['lifted_pairs'],
                      failed=metrics['failed_pairs'],
                      independent=metrics['independent_mode'])
        write_findings(result['name'], config, OUT_ROOT / key, greedy,
                       result['numbers'], {})
        print(f'[{result["name"]}] findings rewritten', flush=True)


def main(argv):
    if len(argv) > 1 and argv[1] == 'compare':
        compare_from_files()
        return
    if len(argv) > 1 and argv[1] == 'refind':
        refind()
        return
    keys = [key for key in EXPERIMENTS
            if len(argv) == 1 or argv[1] in key]
    results = {}
    for key in keys:
        results[key] = run_experiment(key)
    if len(results) == 2:
        write_compare(results['E1_B1_remove_all_z2'],
                      results['E1_B2_remove_movable_z2'])
        print('[E1-B] side-by-side written', flush=True)


if __name__ == '__main__':
    main(sys.argv)
