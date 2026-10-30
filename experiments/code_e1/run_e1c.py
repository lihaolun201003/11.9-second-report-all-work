# -*- coding: utf-8 -*-
"""E1-C: Z1 priority + Z2 local rerouting, complete 1024-route experiments.

C1 : only Z1 is re-layered (Z2 restored exactly as BASE).
C2 : Z1 priority + single-line Z2 local layer swaps.
C3 : Z1 priority + bundle-level joint Z2 rerouting (whole conflicting classes),
     re-lifting every Z1 C2 pair with the shortest legal window.

All geometry is rebuilt through the existing S-bend builder and validated by the
frozen validator on the 7-layer 150 um stack.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter

from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.e1 import layering as L
from four_side_1024.e1 import plots as P

OUT = C.E1
C1_DIR = OUT / 'E1_C1_z1_only'
C2_DIR = OUT / 'E1_C2_z2_local'
C3_DIR = OUT / 'E1_C3_z2_bundle'


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------
def audit(records, ctx):
    return C.audit(records, ctx)


def save_group(name, folder, records, ctx, extra=None, note=None,
               baseline_records=None, log=print):
    summary, report, analysis = C.save_experiment(
        name, records, ctx, folder=folder, extra=extra, note=note, log=log)
    try:
        P.standard_figures(folder, records, ctx, name,
                           baseline_records=baseline_records or ctx.records_base,
                           analysis=analysis,
                           baseline_analysis=audit(baseline_records or
                                                   ctx.records_base, ctx))
    except Exception as exc:  # figures must not invalidate the experiment
        log(f'[figures] {name} failed: {exc}')
    return summary


def preferred_layers(entry):
    if entry['key'] == 'EW':
        return [2, 4, 5, 6, 7, 3]
    return [3, 4, 5, 6, 7, 2]


def legal_pair_candidates(ctx, world, entry, layer, limit=3,
                          symmetric_only=True):
    """Legal windows for one C2 pair at one layer, shortest stubs first."""
    out = []
    for a_in, a_out in S.window_grid(ctx, entry['rids'][0], layer,
                                     symmetric_only=symmetric_only):
        routes = ctx.lift_pair(entry, layer, a_in, a_out)
        if routes is None:
            continue
        if any(S.structure_errors(route) for route in routes):
            continue
        if any(world.check_route(route) for route in routes):
            continue
        if C.pairwise_violations(world, routes[0], routes[1]):
            continue
        out.append(dict(layer=int(layer), a_in=float(a_in),
                        a_out=float(a_out), routes=routes))
        if len(out) >= limit:
            break
    return out


def best_delta_candidate(ctx, records, analysis, candidates):
    """Pick the candidate whose full-layout crossing count is smallest."""
    best = None
    for candidate in candidates:
        trial = L.replace(records, candidate['routes'])
        trial_analysis = audit(trial, ctx)
        delta = trial_analysis['n_unique_pairs'] - analysis['n_unique_pairs']
        key = (delta, candidate['a_in'] + candidate['a_out'])
        if best is None or key < best[0]:
            best = (key, candidate, trial_analysis)
    return best


def flat_pairs(ctx, records):
    by_id = L.records_by_id(records)
    out = []
    for entry in ctx.pair_dirs:
        try:
            layers = [ctx.route_target_layer(by_id[rid]) for rid in entry['rids']]
        except KeyError:
            continue
        if max(layers) <= 1:
            out.append(entry)
    return out


def stub_report(ctx, records):
    by_id = L.records_by_id(records)
    stubs = []
    for rid in ctx.z1_opposite:
        if rid not in by_id:
            continue
        head, tail = C.Ctx.stubs(by_id[rid])
        if max(head, tail) > 1.5:
            stubs.append((rid, round(head, 2), round(tail, 2)))
    return dict(n_routes_with_stub=len(stubs),
                max_stub=round(max((max(h, t) for _, h, t in stubs),
                                   default=0.0), 3),
                stub_hist=dict(Counter(int(min(max(h, t), 90) // 10 * 10)
                                       for _, h, t in stubs)))


# ---------------------------------------------------------------------------
# C1 -- Z1 only
# ---------------------------------------------------------------------------
def c1_z1_only(ctx, log=print):
    log('=== E1-C1: Z1-only re-layering (Z2 exactly as BASE) ===')
    records = list(ctx.records_base)
    analysis = audit(records, ctx)
    accepted = []
    failed = []
    for entry in ctx.unlifted_pairs:
        world = ctx.world([record for record in records
                           if int(record['route_id']) not in entry['rids']])
        picked = None
        for layer in preferred_layers(entry):
            candidates = legal_pair_candidates(ctx, world, entry, layer,
                                               limit=2)
            if not candidates:
                continue
            best = best_delta_candidate(ctx, records, analysis, candidates)
            if best[0][0] < 0:
                delta, candidate, trial_analysis = best
                records = L.replace(records, candidate['routes'])
                analysis = trial_analysis
                picked = dict(pair_id=entry['pair_id'], layer=candidate['layer'],
                              a_in=candidate['a_in'], a_out=candidate['a_out'],
                              delta=delta, route_ids=list(entry['rids']))
            break
        if picked:
            accepted.append(picked)
            log(f'  [C1] {entry["pair_id"]} -> L{picked["layer"]} '
                f'a={picked["a_in"]:.2f} delta={picked["delta"]}')
        else:
            failed.append(entry['pair_id'])
    log(f'  [C1] lifted {len(accepted)}/{len(ctx.unlifted_pairs)} pairs, '
        f'still flat {len(failed)}')
    stats = C.bar(records)
    summary = save_group(
        'E1_C1_z1_only', C1_DIR, records, ctx,
        extra=dict(c1_lifted_pairs=accepted, c1_failed_pairs=failed,
                   c1_flat_pair_count=len(flat_pairs(ctx, records)),
                   z1_stubs=stub_report(ctx, records)),
        note='C1: Z1-only refinement; Z2 geometry identical to BASE',
        log=log)
    return records, analysis, summary


# ---------------------------------------------------------------------------
# C2 -- single-line Z2 local swap
# ---------------------------------------------------------------------------
def pair_blockers(ctx, records, entry, layer=2, a=1.2):
    """Z2/Z1 routes that block the pair at the requested early window."""
    world = ctx.world([record for record in records
                       if int(record['route_id']) not in entry['rids']])
    routes = ctx.lift_pair(entry, layer, a, a)
    if routes is None:
        routes = [ctx.lift(rid, layer, a, a) for rid in entry['rids']]
    violations = []
    for route in routes:
        if route is None:
            continue
        violations.extend(C.collect_violations(world, route))
    rows = C.blocker_rows(ctx, entry['rids'][0], violations)
    return rows


def move_z2_route(ctx, records, rid, dest=(6, 7, 5), small_grid=None):
    """Find a legal lift for one Z2 route, keeping every other route fixed."""
    world = ctx.world([record for record in records
                       if int(record['route_id']) != int(rid)])
    cat = ctx.cat[int(rid)]
    layers = L.Z2_DEST.get(cat, dest)
    for layer in layers:
        for a_in, a_out in S.window_grid(ctx, int(rid), int(layer),
                                         symmetric_only=True):
            route = ctx.lift(int(rid), int(layer), a_in, a_out)
            if route is None or S.structure_errors(route):
                continue
            if world.check_route(route):
                continue
            return dict(layer=int(layer), a_in=float(a_in), a_out=float(a_out),
                        route=route)
    return None


def c2_z2_single(ctx, start_records, log=print, max_rounds=2,
                 max_blockers_per_pair=3):
    log('=== E1-C2: Z1 priority + single-line Z2 local layer swaps ===')
    records = list(start_records)
    analysis = audit(records, ctx)
    moves = []
    for round_index in range(max_rounds):
        changed = 0
        for entry in flat_pairs(ctx, records):
            blockers = pair_blockers(ctx, records, entry)
            z2_blockers = [row for row in blockers
                           if row['plane'] == 'z2'][:max_blockers_per_pair]
            if not z2_blockers:
                continue
            for row in z2_blockers:
                rid = int(row['route_id'])
                option = move_z2_route(ctx, records, rid)
                if option is None:
                    continue
                trial = L.replace(records, [option['route']])
                # retry the pair in the modified world
                world = ctx.world([record for record in trial
                                   if int(record['route_id'])
                                   not in entry['rids']])
                for layer in preferred_layers(entry):
                    candidates = legal_pair_candidates(ctx, world, entry,
                                                       layer, limit=1)
                    if not candidates:
                        continue
                    candidate = candidates[0]
                    trial2 = L.replace(trial, candidate['routes'])
                    trial_analysis = audit(trial2, ctx)
                    delta = (trial_analysis['n_unique_pairs']
                             - analysis['n_unique_pairs'])
                    if delta < 0:
                        records = trial2
                        analysis = trial_analysis
                        moves.append(dict(pair_id=entry['pair_id'],
                                          z2_route=rid,
                                          z2_layer=option['layer'],
                                          z1_layer=candidate['layer'],
                                          z1_a_in=candidate['a_in'],
                                          delta=delta))
                        changed += 1
                        log(f'  [C2] {entry["pair_id"]} freed by Z2 {rid}->'
                            f'L{option["layer"]}; lift L{candidate["layer"]} '
                            f'a={candidate["a_in"]:.2f} delta={delta}')
                        break
                if changed and moves and moves[-1]['pair_id'] == entry['pair_id']:
                    break
        log(f'  [C2] round {round_index}: {changed} pair(s) resolved')
        if not changed:
            break
    stats = C.bar(records)
    summary = save_group(
        'E1_C2_z2_local', C2_DIR, records, ctx,
        extra=dict(c2_moves=moves,
                   c2_flat_pair_count=len(flat_pairs(ctx, records)),
                   z1_stubs=stub_report(ctx, records)),
        note='C2: Z1 priority + single-line Z2 local layer swaps',
        log=log)
    return records, analysis, summary


# ---------------------------------------------------------------------------
# C3 -- bundle-level joint rerouting
# ---------------------------------------------------------------------------
def c3_bundle(ctx, log=print, variants=None):
    log('=== E1-C3: Z1 priority + bundle-level Z2 joint rerouting ===')
    movers = L.collinear_z2_movers(ctx)
    log(f'  collinear Z2 movers: {len(movers)} '
        f'{dict(Counter(ctx.cat[r] for r in movers))}')
    variants = variants or [
        dict(label='bundle_adj6_u7', ew_layer=2, ns_layer=3,
             dest={'adjacent_z2': (6, 7), 'same_u_z2': (7, 6),
                   'opposite_z2_EW': (5, 6), 'opposite_z2_NS': (5, 6)}),
        dict(label='bundle_adj6_u6', ew_layer=2, ns_layer=3,
             dest={'adjacent_z2': (6, 7), 'same_u_z2': (6, 7),
                   'opposite_z2_EW': (5, 6), 'opposite_z2_NS': (5, 6)}),
        dict(label='bundle_adj6_u5', ew_layer=2, ns_layer=3,
             dest={'adjacent_z2': (6, 7), 'same_u_z2': (5, 6, 4),
                   'opposite_z2_EW': (5, 6), 'opposite_z2_NS': (5, 6)}),
        dict(label='bundle_adj6_ns4', ew_layer=2, ns_layer=4,
             dest={'adjacent_z2': (6, 7), 'same_u_z2': (7, 6),
                   'opposite_z2_EW': (5, 6), 'opposite_z2_NS': (5, 6)}),
    ]
    best = None
    variant_rows = []
    for variant in variants:
        started = time.perf_counter()
        log(f'  --- variant {variant["label"]} EW->L{variant["ew_layer"]} '
            f'NS->L{variant["ns_layer"]} ---')
        moved_records, moved, failed = L.relocate_z2(
            ctx, ctx.records_base, movers, dest=variant['dest'], log=log)
        lifted_records, lift_stats = L.lift_z1_pairs(
            ctx, moved_records, ew_layer=variant['ew_layer'],
            ns_layer=variant['ns_layer'], fallback=True, log=log)
        analysis, stats, usage = L.summarise(
            ctx, lifted_records, f'C3-{variant["label"]}')
        row = dict(label=variant['label'],
                   ew_layer=variant['ew_layer'], ns_layer=variant['ns_layer'],
                   moved_z2=len(moved), moved_z2_failed=len(failed),
                   lifted_z1_pairs=len(lift_stats['lifted']),
                   flat_pairs=len(lift_stats['flat']),
                   unique=analysis['n_unique_pairs'],
                   z1=analysis['z1_pairs'], z2=analysis['z2_pairs'],
                   high=analysis['high_pairs'],
                   adj=analysis['adjacent_related_events'],
                   line=analysis['adjacent_line_events'],
                   arc=analysis['adjacent_arc_events'],
                   transitions=stats['transitions'],
                   hours=stats['fabrication_hours'],
                   L5=usage[5]['routes'], L6=usage[6]['routes'],
                   L7=usage[7]['routes'],
                   seconds=round(time.perf_counter() - started, 1))
        variant_rows.append(row)
        log('  ' + json.dumps(row, ensure_ascii=False))
        if best is None or row['unique'] < best[0]['unique']:
            best = (row, lifted_records, moved, failed, lift_stats, analysis,
                    stats, usage)
    row, records, moved, failed, lift_stats, analysis, stats, usage = best
    log(f'  [C3] best variant {row["label"]}: unique={row["unique"]}')
    summary = save_group(
        f'E1_C3_z2_bundle', C3_DIR, records, ctx,
        extra=dict(c3_best_variant=row, c3_variants=variant_rows,
                   c3_moved_z2=len(moved), c3_moved_z2_ids=sorted(moved),
                   c3_moved_z2_failed=sorted(failed),
                   c3_lifted_z1_pairs=len(lift_stats['lifted']),
                   c3_flat_pairs=lift_stats['flat'],
                   c3_windows=lift_stats['windows'],
                   z1_stubs=stub_report(ctx, records)),
        note='C3: Z1 priority + bundle-level Z2 rerouting to the free upper layers',
        log=log)
    return records, analysis, summary, variant_rows


def main(argv):
    what = argv[1] if len(argv) > 1 else 'all'
    ctx = C.load_ctx()
    C.ensure_dir(OUT)
    outputs = {}
    c1_records = None
    if what in ('c1', 'all'):
        c1_records, c1_analysis, c1_summary = c1_z1_only(ctx)
        outputs['C1'] = c1_summary
    if what in ('c2', 'all'):
        if c1_records is None:
            _, c1_records = C.load_experiment(C1_DIR)
        c2_records, c2_analysis, c2_summary = c2_z2_single(ctx, c1_records)
        outputs['C2'] = c2_summary
    if what in ('c3', 'all'):
        c3_records, c3_analysis, c3_summary, rows = c3_bundle(ctx)
        outputs['C3'] = c3_summary
    C.write_json(OUT / '_run_e1c_state.json',
                 {key: C.summary_row(key, value)
                  for key, value in outputs.items()})
    print(json.dumps({key: C.summary_row(key, value)
                      for key, value in outputs.items()},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv)
