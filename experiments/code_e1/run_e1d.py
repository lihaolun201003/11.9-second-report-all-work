# -*- coding: utf-8 -*-
"""E1-D: access-segment (base stub) analysis and asymmetric-window optimisation.

D1  analyse the lifted Z1 opposite routes: stub lengths, crossing contribution by
    counterpart category, first crossing vs rise, whether an earlier legal window
    exists on the BASE layout.
D2  greedily replace those windows with shorter legal/asymmetric ones on BASE,
    end-to-end evaluation + mandatory figures + exact deltas vs BASE.
D3  same refinement on the Lead's E1-C best solution.

Run:  .venv\\Scripts\\python.exe -m four_side_1024.e1.run_e1d verify
      .venv\\Scripts\\python.exe -m four_side_1024.e1.run_e1d probe
      .venv\\Scripts\\python.exe -m four_side_1024.e1.run_e1d d1
      .venv\\Scripts\\python.exe -m four_side_1024.e1.run_e1d d2
      .venv\\Scripts\\python.exe -m four_side_1024.e1.run_e1d d3 --source <dir>
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.e1 import search as S
from four_side_1024.fslw import validate_fslw as V

D_ROOT = C.E1 / 'E1_D_early_lift'
D1_DIR = D_ROOT / 'D1_analysis'
D2_DIR = D_ROOT / 'D2_baseline_asymmetric'
D3_DIR = D_ROOT / 'D3_e1c_best'


# ---------------------------------------------------------------------------
# geometry: height profile of a routed record along its fixed 2D chain
# ---------------------------------------------------------------------------
def route_geom(record):
    """[(s_start, s_end, kind, z)] along the fixed 2D chain; transition span is
    its XY footprint (the chain arclength it consumes)."""
    out = []
    s = 0.0
    for part in record.get('parts') or []:
        if part['kind'] == 'flat':
            span = float(part['length_mm'])
            out.append((s, s + span, 'flat', round(float(part['z_mm']), 6)))
        else:
            span = float(part.get('footprint_mm')
                         or part.get('length_mm') or 0.0)
            out.append((s, s + span, 'transition', None))
        s += span
    return out


def geom_z_at(geom, s):
    for s0, s1, kind, z in geom:
        if s0 - 1e-9 <= s <= s1 + 1e-9:
            return z if kind == 'flat' else None
    return None


def chain_kinds(ctx, rid):
    """[(s0, s1, kind)] for the fixed 2D chain (arcs vs lines)."""
    out = []
    s = 0.0
    for prim in ctx.chain(rid):
        length = C.prim_len(prim)
        out.append((s, s + length, prim['kind']))
        s += length
    return out


def chain_position(ctx, rid, x, y):
    """Exact (distance, kind, arclength from source) of (x, y) on the chain.

    ``core.locate_on_chain`` returns the *midpoint* arclength of the closest
    primitive (it is only used for line/arc classification), so it cannot be
    used for crossing arclengths.
    """
    best = None
    offset = 0.0
    for prim in ctx.chain(rid):
        cx, cy = C.prim_closest_point(prim, x, y)
        distance = math.hypot(cx - x, cy - y)
        length = C.prim_len(prim)
        if best is None or distance < best[0]:
            if prim['kind'] == 'line':
                p0, p1 = prim['p0'], prim['p1']
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                den = dx * dx + dy * dy
                t = (0.0 if den <= 1e-18 else
                     max(0.0, min(1.0, ((cx - p0[0]) * dx
                                        + (cy - p0[1]) * dy) / den)))
            else:
                center = prim['center']
                start = float(prim['start_angle'])
                sweep = float(prim['sweep'])
                angle = math.atan2(cy - center[1], cx - center[0])
                if sweep >= 0.0:
                    delta = (angle - start) % (2.0 * math.pi)
                    if delta > sweep + 1e-9:
                        delta = 0.0 if delta <= sweep + math.pi else sweep
                    t = delta / sweep if abs(sweep) > 1e-15 else 0.0
                else:
                    delta = (start - angle) % (2.0 * math.pi)
                    if delta > -sweep + 1e-9:
                        delta = 0.0 if delta <= -sweep + math.pi else -sweep
                    t = delta / (-sweep) if abs(sweep) > 1e-15 else 0.0
                t = max(0.0, min(1.0, t))
            best = (distance, prim['kind'], offset + t * length)
        offset += length
    return best


def chain_kind_at(kinds, s):
    for s0, s1, kind in kinds:
        if s0 - 1e-9 <= s <= s1 + 1e-9:
            return kind
    return 'line'


# ---------------------------------------------------------------------------
# exact-increment crossing engine
# ---------------------------------------------------------------------------
class CrossingEngine:
    """All pairwise 2D crossings of the fixed route chains plus a fast exact
    height-aware audit.

    Every flat/transition part of every lifted record is a sub-chain of the
    fixed 2D chain, so a physical crossing event exists exactly at a fixed 2D
    chain intersection whose height on *both* routes is the same flat plane.
    """

    def __init__(self, ctx, policy='strict', verbose=True):
        started = time.perf_counter()
        self.ctx = ctx
        rids = sorted(ctx.manifest)
        prepared = [V.prepare_route(ctx.chain(rid), rid) for rid in rids]
        pairs = V._candidate_pairs(prepared, C.CLEARANCE + 2.0 * V.SAGITTA)
        if verbose:
            print(f'  [engine] prepared={len(prepared)} broad_pairs={len(pairs)} '
                  f'{time.perf_counter() - started:.2f}s')
        events = []
        self.pair_valid = {}
        t_eval = time.perf_counter()
        for index_a, index_b in pairs:
            first, second = prepared[index_a], prepared[index_b]
            result = V.evaluate_pair(first, second, C.CLEARANCE, V.SAGITTA,
                                     policy)
            if result is None:
                continue
            rid_a, rid_b = int(first.route_id), int(second.route_id)
            key = (min(rid_a, rid_b), max(rid_a, rid_b))
            if not result['crossings']:
                self.pair_valid.setdefault(key, bool(result['valid']))
                continue
            valid = bool(result['valid'])
            self.pair_valid[key] = valid
            if not valid:
                continue
            for crossing in result['crossings']:
                events.append(dict(a=rid_a, b=rid_b,
                                   x=float(crossing['point'][0]),
                                   y=float(crossing['point'][1]),
                                   s_a=float(crossing['sa']),
                                   s_b=float(crossing['sb'])))
        self.events = events
        self.by_route = defaultdict(list)
        for index, event in enumerate(events):
            self.by_route[event['a']].append((index, True))
            self.by_route[event['b']].append((index, False))
        self.kinds = {rid: chain_kinds(ctx, rid) for rid in rids}
        self.build_seconds = time.perf_counter() - started
        self.eval_seconds = time.perf_counter() - t_eval
        if verbose:
            print(f'  [engine] valid_crossing_events={len(events)} '
                  f'build={self.build_seconds:.2f}s '
                  f'(pair_eval={self.eval_seconds:.2f}s)')

    # -- flat-geometry helpers -------------------------------------------
    def signature(self, records):
        """rid -> {partner: [n_events, Counter(z)]} for the given layout."""
        geoms = {int(r['route_id']): route_geom(r) for r in records}
        sig = defaultdict(lambda: defaultdict(lambda: [0, Counter()]))
        for event in self.events:
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            sig[event['a']][event['b']][0] += 1
            sig[event['a']][event['b']][1][za] += 1
            sig[event['b']][event['a']][0] += 1
            sig[event['b']][event['a']][1][za] += 1
        return sig

    def audit(self, records, signature=None):
        """Same counters as core.audit (crossings only, no violations)."""
        ctx = self.ctx
        geoms = {int(r['route_id']): route_geom(r) for r in records}
        sig = signature if signature is not None else self.signature(records)
        by_z = defaultdict(list)
        for rid, partners in sig.items():
            for other, (count, zcounts) in partners.items():
                for z, n in zcounts.items():
                    by_z[z].append((rid, other, n))
        per_height = {}
        unique_pairs = set()
        per_route = Counter()
        events = []
        route_ids = defaultdict(set)
        segments = Counter()
        for record in records:
            for part in record.get('parts') or []:
                if part['kind'] != 'flat':
                    continue
                z = round(float(part['z_mm']), 6)
                segments[z] += 1
                route_ids[z].add(int(record['route_id']))
        for z, rows in sorted(by_z.items()):
            seen = []
            for rid, other, n in rows:
                if rid < other:
                    seen.append((rid, other, n))
            pairs = {(a, b) for a, b, _ in seen}
            unique_pairs.update(pairs)
            for a, b, n in seen:
                per_route[a] += n
                per_route[b] += n
            breakdown = Counter()
            for a, b in pairs:
                breakdown[tuple(sorted((ctx.cat.get(a, '?'),
                                        ctx.cat.get(b, '?'))))] += 1
            per_height[z] = dict(routes=len(route_ids[z]),
                                 segments=segments[z],
                                 pairs=len(pairs),
                                 events=sum(n for _, _, n in seen),
                                 violations=0,
                                 breakdown={f'{k[0]} x {k[1]}': v
                                            for k, v in breakdown.items()})
        # event-level rows for adjacent classification
        for event in self.events:
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            events.append(dict(z=za, route_a=event['a'], route_b=event['b'],
                               x=event['x'], y=event['y'],
                               s_a=event['s_a'], s_b=event['s_b']))
        adjacent_related = 0
        adjacent_line = 0
        adjacent_arc = 0
        hv_pairs = 0
        for z, info in per_height.items():
            hv_pairs += int(info['breakdown'].get(
                'opposite_z1_EW x opposite_z1_NS', 0))
        adjacent_pairs = set()
        for event in events:
            cats = (ctx.cat.get(event['route_a'], '?'),
                    ctx.cat.get(event['route_b'], '?'))
            if 'adjacent_z1' in cats:
                adjacent_pairs.add((min(event['route_a'], event['route_b']),
                                    max(event['route_a'], event['route_b'])))
            if event['z'] == C.Z1 and 'adjacent_z1' in cats and (
                    cats[0].startswith('opposite_z1')
                    or cats[1].startswith('opposite_z1')):
                adjacent_related += 1
                adj = (event['route_a'] if cats[0] == 'adjacent_z1'
                       else event['route_b'])
                side = 'a' if cats[0] == 'adjacent_z1' else 'b'
                s = event['s_a'] if side == 'a' else event['s_b']
                if chain_kind_at(self.kinds[adj], s) == 'arc':
                    adjacent_arc += 1
                else:
                    adjacent_line += 1
        opposite_opposite = sum(
            1 for event in events
            if event['z'] == C.Z1
            and ctx.cat.get(event['route_a'], '').startswith('opposite')
            and ctx.cat.get(event['route_b'], '').startswith('opposite'))
        opposite_opposite_all = sum(
            1 for event in events
            if ctx.cat.get(event['route_a'], '').startswith('opposite')
            and ctx.cat.get(event['route_b'], '').startswith('opposite'))
        return dict(
            per_height=per_height, events=events,
            unique_pairs=unique_pairs, n_unique_pairs=len(unique_pairs),
            per_route=per_route,
            z1_pairs=per_height.get(C.Z1, {}).get('pairs', 0),
            z2_pairs=per_height.get(C.Z2, {}).get('pairs', 0),
            high_pairs=sum(info['pairs'] for z, info in per_height.items()
                           if z not in (C.Z1, C.Z2)),
            adjacent_related_events=adjacent_related,
            adjacent_arc_events=adjacent_arc,
            adjacent_line_events=adjacent_line,
            adjacent_pairs=len(adjacent_pairs),
            z1_hv_pairs=hv_pairs,
            opposite_opposite_events=opposite_opposite,
            opposite_opposite_all=opposite_opposite_all,
            planes={str(z): dict(routes=info['routes'], segments=info['segments'],
                                 pairs=info['pairs'], events=info['events'])
                    for z, info in per_height.items()})

    # -- incremental signature for one candidate route --------------------
    def route_signature(self, geoms, rid):
        rid = int(rid)
        out = defaultdict(lambda: [0, Counter()])
        for index, is_a in self.by_route[rid]:
            event = self.events[index]
            s_self = event['s_a'] if is_a else event['s_b']
            z_self = geom_z_at(geoms[rid], s_self)
            if z_self is None:
                continue
            other = event['b'] if is_a else event['a']
            s_other = event['s_b'] if is_a else event['s_a']
            z_other = geom_z_at(geoms[other], s_other)
            if z_other is None or z_other != z_self:
                continue
            out[other][0] += 1
            out[other][1][z_self] += 1
        return {other: (val[0], dict(val[1])) for other, val in out.items()}

    @staticmethod
    def signature_stats(sig):
        events = sum(val[0] for val in sig.values())
        pairs = len(sig)
        zcounts = Counter()
        for val in sig.values():
            zcounts.update(val[1])
        return dict(events=events, pairs=pairs, per_height=dict(zcounts))


# ---------------------------------------------------------------------------
# D2/D3: greedy asymmetric-window refinement on a complete layout
# ---------------------------------------------------------------------------
def _load_legal_map(path):
    payload = C.read_json(path)
    out = {}
    for key, info in payload.items():
        out[int(info['route_id'])] = dict(
            target_layer=int(info['target_layer']),
            legal=[(float(a), float(b)) for a, b in info['legal']],
            current=(float(info['current_a_in']), float(info['current_a_out'])))
    return out


def refine(ctx, records, movable, legal_map, folder, name, note='', extra=None,
           max_passes=2, base_analysis=None, baseline_records=None,
           comparison_tag='D2', d1_rows=None, dry_run=False):
    """Greedy replacement of the movable routes' S-bend windows."""
    started = time.perf_counter()
    folder = C.ensure_dir(folder)
    C.ensure_dir(folder / 'figures')
    records = list(records)
    by_id = {int(record['route_id']): record for record in records}
    movable = [int(rid) for rid in movable]
    print(f'[{name}] movable={len(movable)} records={len(records)}')
    engine = LiftingEngine(ctx, movable, records)
    geoms = {rid: route_geom(by_id[rid]) for rid in movable}
    world = ctx.world(records)

    order_score = {}
    if d1_rows is not None:
        for row in d1_rows:
            rid = int(row['route_id'])
            if rid in engine.movable:
                order_score[rid] = int(row.get('predicted_z0_removed') or 0)
    order = sorted(movable, key=lambda rid: (-order_score.get(rid, 0),
                                             -sum(C.Ctx.stubs(by_id[rid]))))
    changes = []
    pass_log = []
    for pass_index in range(1, max_passes + 1):
        accepted = 0
        t_pass = time.perf_counter()
        for position, rid in enumerate(order):
            if rid not in by_id:
                continue
            info = legal_map.get(rid)
            if not info or not info['legal']:
                continue
            layer = info['target_layer']
            current = C.Ctx.stubs(by_id[rid])
            candidates = [window for window in info['legal']
                          if window[0] < current[0] - 1e-6
                          or window[1] < current[1] - 1e-6]
            if not candidates:
                continue
            total = ctx.total(rid)
            world.remove_route(rid)
            old_geom = geoms[rid]
            old_stats = engine.route_stats(rid, old_geom, geoms)
            best = None
            for a_in, a_out in candidates:
                record = S.build_single(ctx, rid, layer, a_in, a_out)
                if record is None or S.structure_errors(record):
                    continue
                if world.check_route(record):
                    continue
                new_geom = route_geom(record)
                new_stats = engine.route_stats(rid, new_geom, geoms)
                delta_pairs = new_stats['pairs'] - old_stats['pairs']
                delta_events = new_stats['events'] - old_stats['events']
                delta_adj = (new_stats['adjacent_related']
                             - old_stats['adjacent_related'])
                delta_line = (new_stats['adjacent_line']
                              - old_stats['adjacent_line'])
                delta_arc = (new_stats['adjacent_arc']
                             - old_stats['adjacent_arc'])
                if delta_pairs > 0 or delta_adj > 0 or delta_events > 0:
                    continue
                if delta_pairs == 0 and delta_adj == 0 and delta_events == 0:
                    continue
                score = (delta_pairs, delta_adj, delta_events,
                         a_in + a_out, a_in)
                if best is None or score < best[0]:
                    best = (score, record, new_geom, dict(
                        delta_pairs=delta_pairs, delta_events=delta_events,
                        delta_adjacent=delta_adj, delta_line=delta_line,
                        delta_arc=delta_arc,
                        old_pairs=old_stats['pairs'],
                        new_pairs=new_stats['pairs']))
            if best is None:
                world.add_route(by_id[rid])
                continue
            _, record, new_geom, delta = best
            world.add_route(record)
            by_id[rid] = record
            geoms[rid] = new_geom
            changes.append(dict(
                route_id=rid,
                pair_id=(ctx.pairs_by_rid[rid]['pair_id']
                         if rid in ctx.pairs_by_rid else ''),
                target_layer=layer,
                base_a_in=round(current[0], 6),
                base_a_out=round(current[1], 6),
                new_a_in=round(float(C.Ctx.stubs(record)[0]), 6),
                new_a_out=round(float(C.Ctx.stubs(record)[1]), 6),
                base_stub_total=round(current[0] + current[1], 6),
                new_stub_total=round(sum(C.Ctx.stubs(record)), 6),
                **delta))
            accepted += 1
            if accepted % 20 == 0:
                print(f'[{name}] pass{pass_index} {position + 1}/{len(order)} '
                      f'accepted={accepted} {time.perf_counter() - t_pass:.1f}s')
        pass_log.append(dict(pass_index=pass_index, accepted=accepted,
                             seconds=round(time.perf_counter() - t_pass, 2)))
        print(f'[{name}] pass{pass_index}: accepted {accepted} changes '
              f'in {time.perf_counter() - t_pass:.1f}s')
        if accepted == 0:
            break

    records = [by_id[int(rid)] for rid in sorted(by_id)]
    print(f'[{name}] refinement done: {len(changes)} windows changed '
          f'in {time.perf_counter() - started:.1f}s')
    if dry_run:
        for change in changes:
            print('   ', {key: change[key] for key in
                          ('route_id', 'base_a_in', 'base_a_out',
                           'new_a_in', 'new_a_out', 'delta_pairs',
                           'delta_events', 'delta_adjacent')})
        return None, None, None, changes

    # exact end-to-end evaluation
    analysis = C.audit(records, ctx)
    engine_check = engine.full_audit(records)
    movable_events_core = [event for event in analysis['events']
                           if int(event['route_a']) in engine.movable
                           or int(event['route_b']) in engine.movable]
    core_stats = dict(
        events=len(movable_events_core),
        unique_pairs=len({(min(int(e['route_a']), int(e['route_b'])),
                           max(int(e['route_a']), int(e['route_b'])))
                          for e in movable_events_core}),
        adjacent=sum(1 for e in analysis['events']
                     if 'adjacent_z1' in (ctx.cat.get(int(e['route_a']), '?'),
                                          ctx.cat.get(int(e['route_b']), '?'))
                     and e['z'] == C.Z1),
    )
    print(f'[{name}] engine check: engine events={engine_check["events"]} '
          f'core_movable events={core_stats["events"]} '
          f'engine_pairs={engine_check["unique_pairs"]} '
          f'core_pairs={core_stats["unique_pairs"]} '
          f'engine_adj={engine_check["adjacent_related"]} '
          f'core_adj={core_stats["adjacent"]}')
    if base_analysis is None:
        base_analysis = C.audit(baseline_records or ctx.records_base, ctx)
    usage = C.layer_usage(records, ctx)
    extra_payload = dict(
        refinement=dict(
            movable_routes=len(movable),
            routes_changed=len(changes),
            changed_route_ids=sorted(int(change['route_id']) for change in changes),
            passes=pass_log,
            symmetric_before=sum(1 for rid in movable
                                 if abs(C.Ctx.stubs(by_id[rid])[0]
                                        - C.Ctx.stubs(by_id[rid])[1]) < 1e-9),
            stub_total_movable_before=round(sum(
                sum(C.Ctx.stubs(ctx.by_id[rid])) for rid in movable), 3),
            stub_total_movable_after=round(sum(
                sum(C.Ctx.stubs(by_id[rid])) for rid in movable), 3),
            engine_check=dict(engine_events=engine_check['events'],
                              core_movable_events=core_stats['events'],
                              engine_pairs=engine_check['unique_pairs'],
                              core_pairs=core_stats['unique_pairs'],
                              engine_adjacent=engine_check['adjacent_related'],
                              core_adjacent=core_stats['adjacent']),
            seconds=round(time.perf_counter() - started, 2)),
        l6_route_count=usage[6]['routes'], l7_route_count=usage[7]['routes'],
        layer_usage={str(k): dict(z=info['z'], routes=info['routes'],
                                  segments=info['segments'])
                     for k, info in usage.items()},
    )
    if extra:
        extra_payload.update(extra)
    summary, report, analysis = C.save_experiment(
        name, records, ctx, folder=folder, extra=extra_payload,
        validate=True, note=note)
    C.write_csv(folder / 'window_changes.csv', changes)
    _write_comparison(ctx, folder, comparison_tag, records, summary,
                      base_analysis, baseline_records or ctx.records_base,
                      analysis, changes, movable)
    from four_side_1024.e1 import plots as P
    P.standard_figures(folder, records, ctx, name,
                       baseline_records=baseline_records or ctx.records_base,
                       analysis=analysis, baseline_analysis=base_analysis)
    P.four_side_zoom(folder, records, name, ctx=ctx,
                     highlight_ids=sorted(int(c['route_id']) for c in changes),
                     tag='four_side_zoom')
    _d_access_figures(folder, ctx, baseline_records or ctx.records_base, records,
                      sorted(int(c['route_id']) for c in changes), name)
    print(f'[{name}] artefacts -> {folder}')
    return summary, report, analysis, changes


def _summary_metrics(analysis, stats, summary):
    rows = dict(
        routed=summary.get('routed', len(analysis['per_route']) and None),
        unique_crossing_pairs=analysis['n_unique_pairs'],
        z1_crossing_pairs=analysis['z1_pairs'],
        z2_crossing_pairs=analysis['z2_pairs'],
        high_layer_crossing_pairs=analysis['high_pairs'],
        adjacent_related_events=analysis['adjacent_related_events'],
        adjacent_related_pairs=analysis['adjacent_pairs'],
        adjacent_line_events=analysis['adjacent_line_events'],
        adjacent_arc_events=analysis['adjacent_arc_events'],
        opposite_opposite_events=analysis['opposite_opposite_events'],
        z1_hv_same_height_pairs=analysis['z1_hv_pairs'],
        transitions=stats['transitions'],
        total_length_mm=stats['total_length_mm'],
        fabrication_hours=stats['fabrication_hours'],
        l6_routes=stats['layer_counts'].get('6', 0),
        l7_routes=stats['layer_counts'].get('7', 0),
        violations=(summary.get('validation_counts') or {}).get(
            'violations', summary.get('n_violations')),
        validation_status=summary.get('validation_status'),
    )
    return rows


def _reference_summary(ctx):
    path = C.E1 / 'baseline' / 'summary.json'
    if path.exists():
        return C.read_json(path)
    return dict()


def _write_comparison(ctx, folder, tag, records, summary, base_analysis,
                      base_records, analysis, changes, movable,
                      ref_summary=None, ref_label='reference'):
    ref_summary = ref_summary if ref_summary is not None else _reference_summary(ctx)
    base_rows = _summary_metrics(base_analysis, C.bar(base_records),
                                 ref_summary)
    after_rows = _summary_metrics(analysis, C.bar(records), summary)
    rows = []
    for key, before in base_rows.items():
        after = after_rows.get(key)
        try:
            delta = round(float(after) - float(before), 6)
            pct = (round(100.0 * delta / float(before), 3)
                   if isinstance(before, (int, float)) and float(before) else None)
        except (TypeError, ValueError):
            delta, pct = None, None
        rows.append(dict(metric=key, before=before, after=after,
                         delta=delta, delta_pct=pct))
    C.write_csv(folder / f'{tag}_comparison.csv', rows)
    payload = dict(tag=tag, metrics=rows,
                   routes_changed=len(changes),
                   changed_route_ids=sorted(int(c['route_id']) for c in changes),
                   changes=changes)
    C.write_json(folder / f'{tag}_comparison.json', payload)
    lines = [f'# {tag} refinement: exact deltas vs reference layout', '',
             '| metric | reference | this experiment | delta | delta % |',
             '|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["metric"]} | {row["before"]} | {row["after"]} | '
                     f'{row["delta"]} | {row["delta_pct"]} |')
    lines += ['', f'Refined `a_in`/`a_out` windows of {len(changes)} of '
                  f'{len(movable)} movable Z1-opposite routes '
                  f'(independent per pair member, world-legal only).', '']
    (folder / f'{tag}_comparison.md').write_text(
        '\n'.join(lines), encoding='utf-8')
    print(f'[{tag}] comparison: base{base_rows["unique_crossing_pairs"]} -> '
          f'{after_rows["unique_crossing_pairs"]} ('
          f'{after_rows["unique_crossing_pairs"] - base_rows["unique_crossing_pairs"]:+d}) '
          f'unique pairs; adjacent {base_rows["adjacent_related_events"]} -> '
          f'{after_rows["adjacent_related_events"]} ('
          f'{after_rows["adjacent_related_events"] - base_rows["adjacent_related_events"]:+d})')
    return rows


def _d_access_figures(folder, ctx, before_records, after_records, changed_rids,
                      name):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from four_side_1024.e1 import plots as P

    figdir = C.ensure_dir(C.ensure_dir(folder) / 'figures')
    before_by = {int(r['route_id']): r for r in before_records}
    after_by = {int(r['route_id']): r for r in after_records}
    changed = [rid for rid in changed_rids if rid in before_by and rid in after_by]
    before_stub = [sum(C.Ctx.stubs(before_by[rid])) for rid in changed]
    after_stub = [sum(C.Ctx.stubs(after_by[rid])) for rid in changed]
    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.0))
    axes[0].hist(before_stub, bins=np.arange(0, 115, 5), alpha=0.6,
                 color='#868e96', label='BASE')
    axes[0].hist(after_stub, bins=np.arange(0, 115, 5), alpha=0.6,
                 color='#2f9e44', label='refined')
    axes[0].set_xlabel('base stub total a_in+a_out (mm)')
    axes[0].set_ylabel('changed routes')
    axes[0].legend(fontsize=8)
    axes[0].set_title(f'access stubs of the {len(changed)} re-windowed routes',
                      fontsize=9)
    if changed:
        axes[1].scatter(before_stub, after_stub, s=16, alpha=0.75,
                        color='#2f9e44')
        limit = max(before_stub + after_stub + [10])
        axes[1].plot([0, limit], [0, limit], 'k--', lw=0.8)
    axes[1].set_xlabel('reference stub total (mm)')
    axes[1].set_ylabel('refined stub total (mm)')
    axes[1].set_title('stub shortening per route', fontsize=9)
    axes[1].grid(alpha=0.2)

    def stub_paths(record):
        segments = []
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or abs(part['z_mm']) > 1e-9:
                continue
            xs, ys = P.sample_primitives(part['primitives'])
            if len(xs):
                segments.append((xs, ys))
        return segments

    for rid in changed[:80]:
        for xs, ys in stub_paths(before_by[rid]):
            axes[2].plot(xs, ys, color='#e03131', lw=0.5, alpha=0.45)
        for xs, ys in stub_paths(after_by[rid]):
            axes[2].plot(xs, ys, color='#2f9e44', lw=0.6, alpha=0.75)
    axes[2].set_xlim(0, 150)
    axes[2].set_ylim(0, 150)
    axes[2].set_aspect('equal')
    axes[2].grid(alpha=0.15)
    axes[2].set_title(f'Z1 stubs XY: reference red / refined green '
                      f'({min(len(changed), 80)} routes)', fontsize=9)
    fig.tight_layout()
    fig.savefig(figdir / 'z1_access_before_after.png', dpi=170,
                bbox_inches='tight')
    plt.close(fig)

    before_analysis = C.audit(before_records, ctx)
    after_analysis = C.audit(after_records, ctx)
    events_before = [e for e in before_analysis['events']
                     if int(e['route_a']) in set(changed)
                     or int(e['route_b']) in set(changed)]
    events_after = [e for e in after_analysis['events']
                    if int(e['route_a']) in set(changed)
                    or int(e['route_b']) in set(changed)]
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2))
    for events, label, color in ((events_before, 'reference', '#e03131'),
                                 (events_after, name, '#2f9e44')):
        z0 = [e for e in events if e['z'] == C.Z1]
        axes[0].scatter([e['x'] for e in z0], [e['y'] for e in z0],
                        s=4, alpha=0.35, color=color, label=label)
    axes[0].set_xlim(*P.X_RANGE)
    axes[0].set_ylim(*P.Y_RANGE)
    axes[0].set_aspect('equal')
    axes[0].legend(fontsize=7)
    axes[0].set_title('Z1 crossing events involving the re-windowed routes',
                      fontsize=9)
    heights = sorted({round(float(e['z']), 6) for e in events_before}
                     | {round(float(e['z']), 6) for e in events_after})
    count_before = Counter(round(float(e['z']), 6) for e in events_before)
    count_after = Counter(round(float(e['z']), 6) for e in events_after)
    positions = np.arange(len(heights))
    axes[1].bar(positions - 0.2, [count_before.get(h, 0) for h in heights],
                0.4, color='#e03131', label='reference')
    axes[1].bar(positions + 0.2, [count_after.get(h, 0) for h in heights],
                0.4, color='#2f9e44', label=name)
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels([f'{h:.2f}' for h in heights], fontsize=7)
    axes[1].set_xlabel('physical z (mm)')
    axes[1].set_ylabel('crossing events')
    axes[1].legend(fontsize=8)
    axes[1].set_title('crossing events by height (re-windowed routes only)',
                      fontsize=9)
    fig.tight_layout()
    fig.savefig(figdir / 'first_crossing_vs_rise.png', dpi=170,
                bbox_inches='tight')
    plt.close(fig)
    print(f'  D-specific figures -> {figdir}')


def _lifted_z1_routes(ctx):
    return [rid for rid in ctx.z1_opposite
            if C.Ctx.route_target_layer(ctx.by_id[rid]) > 1]


def verify():
    ctx = C.load_ctx()
    print(f'ctx: records={len(ctx.records_base)} z1_opposite={len(ctx.z1_opposite)} '
          f'lifted_z1={len(_lifted_z1_routes(ctx))}')
    base = C.audit(ctx.records_base, ctx)
    print('core.audit:', dict(unique=base['n_unique_pairs'], z1=base['z1_pairs'],
                              z2=base['z2_pairs'], high=base['high_pairs'],
                              adj=base['adjacent_related_events'],
                              line=base['adjacent_line_events'],
                              arc=base['adjacent_arc_events'],
                              hv=base['z1_hv_pairs']))
    for policy in ('strict', 'legacy'):
        engine = CrossingEngine(ctx, policy=policy)
        mine = engine.audit(ctx.records_base)
        print(f'engine[{policy}]:', dict(unique=mine['n_unique_pairs'],
                                         z1=mine['z1_pairs'], z2=mine['z2_pairs'],
                                         high=mine['high_pairs'],
                                         adj=mine['adjacent_related_events'],
                                         line=mine['adjacent_line_events'],
                                         arc=mine['adjacent_arc_events'],
                                         hv=mine['z1_hv_pairs']))
        diffs = []
        for key in ('n_unique_pairs', 'z1_pairs', 'z2_pairs', 'high_pairs',
                    'adjacent_related_events', 'adjacent_line_events',
                    'adjacent_arc_events', 'z1_hv_pairs',
                    'opposite_opposite_events'):
            if base[key] != mine[key]:
                diffs.append((key, base[key], mine[key]))
        for z in sorted(set(base['per_height']) | set(mine['per_height'])):
            b = base['per_height'].get(z, {})
            m = mine['per_height'].get(z, {})
            if b.get('pairs') != m.get('pairs') or b.get('events') != m.get('events'):
                diffs.append((f'z={z}', b.get('pairs'), m.get('pairs')))
        bad_route = [rid for rid in ctx.manifest
                     if base['per_route'].get(rid, 0) != mine['per_route'].get(rid, 0)]
        print(f'  mismatched counters: {len(diffs)}; routes with different event '
              f'count: {len(bad_route)}')
        for diff in diffs[:10]:
            print('   ', diff)
        if bad_route[:5]:
            print('   example route ids:', bad_route[:5])
            for rid in bad_route[:3]:
                print('    rid', rid, 'base', base['per_route'].get(rid),
                      'engine', mine['per_route'].get(rid))
    return ctx


def probe():
    t0 = time.perf_counter()
    ctx = C.load_ctx()
    print(f'ctx loaded {time.perf_counter() - t0:.2f}s records={len(ctx.records_base)}')
    lifted = _lifted_z1_routes(ctx)
    print(f'z1_opposite={len(ctx.z1_opposite)} lifted={len(lifted)} '
          f'unlifted_pairs={len(ctx.unlifted_pairs)}')
    cats = Counter(ctx.cat.values())
    print('categories:', dict(sorted(cats.items())))
    stub_pairs = Counter()
    for rid in lifted:
        head, tail = C.Ctx.stubs(ctx.by_id[rid])
        stub_pairs[(round(head, 3), round(tail, 3))] += 1
    print('stub (head,tail) top:', stub_pairs.most_common(10))
    print('both 55:', len([rid for rid in lifted
                           if all(abs(v - 55.0) < 1e-6
                                  for v in C.Ctx.stubs(ctx.by_id[rid]))]))
    print('layer counts:', dict(sorted(Counter(
        C.Ctx.route_target_layer(ctx.by_id[rid]) for rid in lifted).items())))
    print('totals:', dict(sorted(Counter(
        round(ctx.total(rid), 1) for rid in lifted).items())))
    rid = lifted[0]
    print(f'route {rid}: cat={ctx.cat[rid]} pair={ctx.rid_pair[rid]["pair_id"]} '
          f'layer={C.Ctx.route_target_layer(ctx.by_id[rid])} '
          f'stubs={C.Ctx.stubs(ctx.by_id[rid])} total={ctx.total(rid):.3f}')
    for layer in C.LAYERS:
        print(f'  L{layer} footprint={S.footprint(ctx, rid, layer):.3f} '
              f'windows={S.rise_windows(ctx, rid, layer)}')
    grid = S.window_grid(ctx, rid, C.Ctx.route_target_layer(ctx.by_id[rid]))
    print(f'  window_grid n={len(grid)} head={grid[:8]}')
    t = time.perf_counter()
    world = ctx.world(ctx.records_base)
    print(f'world build {time.perf_counter() - t:.3f}s')
    t = time.perf_counter()
    old = world.remove_route(rid)
    print(f'remove_route {time.perf_counter() - t:.3f}s plan={len(world.plan)}')
    t = time.perf_counter()
    world.add_route(old)
    print(f'add_route {time.perf_counter() - t:.3f}s')
    layer = C.Ctx.route_target_layer(ctx.by_id[rid])
    t = time.perf_counter()
    world.remove_route(rid)
    built = legal = 0
    for a_in, a_out in grid:
        rec, route = S.evaluate_single(ctx, world, rid, layer, a_in, a_out,
                                       collect=False)
        built += int(rec['built'])
        legal += int(rec['legal'])
    print(f'{len(grid)} checks {time.perf_counter() - t:.3f}s built={built} legal={legal}')
    world.add_route(old)


def diag(rids=(3, 5, 7, 9)):
    ctx = C.load_ctx()
    world = ctx.world(ctx.records_base)
    for rid in rids:
        layer = C.Ctx.route_target_layer(ctx.by_id[rid])
        head, tail = C.Ctx.stubs(ctx.by_id[rid])
        print(f'\n=== rid {rid} cat={ctx.cat[rid]} pair={ctx.rid_pair[rid]["pair_id"]} '
              f'layer={layer} stubs=({head},{tail}) total={ctx.total(rid):.2f}')
        grid = S.window_grid(ctx, rid, layer)
        print(f'  grid n={len(grid)}')
        for layer2 in C.LAYERS:
            pass
        world.remove_route(rid)
        t_build = t_plane = t_clear = 0.0
        legal = []
        for a_in, a_out in grid:
            t = time.perf_counter()
            route = S.build_single(ctx, rid, layer, a_in, a_out)
            t_build += time.perf_counter() - t
            if route is None:
                continue
            t = time.perf_counter()
            plane_bad = []
            for part in route['parts']:
                if part['kind'] != 'flat':
                    continue
                evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
                if evaluation is not None and not evaluation.valid:
                    plane_bad.append(part['z_mm'])
            t_plane += time.perf_counter() - t
            t = time.perf_counter()
            clear = world.clearance_world.check_route(route, check_self=True)
            t_clear += time.perf_counter() - t
            if not plane_bad and not clear:
                legal.append((a_in, a_out))
        world.add_route(ctx.by_id[rid])
        print(f'  build={t_build:.2f}s plane={t_plane:.2f}s clear={t_clear:.2f}s '
              f'legal={len(legal)}')
        print('  legal windows:', legal[:20])
        print('  plane-window of L2 z2 arms: ')
        # which z2 routes are near this z1 chain at 0.5? report blockers for
        # the smallest a_in candidates with collect
        for a_in, a_out in grid[:3]:
            world.remove_route(rid)
            rec, route = S.evaluate_single(ctx, world, rid, layer, a_in, a_out,
                                           collect=True)
            world.add_route(ctx.by_id[rid])
            blockers = rec.get('blockers') or []
            print(f'  cand ({a_in},{a_out}) legal={rec["legal"]} '
                  f'blockers={[(b["route_id"], b["category"]) for b in blockers[:5]]}')


# ---------------------------------------------------------------------------
# D1: access-segment analysis of the lifted Z1 opposite routes
# ---------------------------------------------------------------------------
def _event_rows_for_lifted(ctx, base_analysis, lifted_set):
    """Per lifted route: its BASE crossing events with arclength on its chain."""
    rows = defaultdict(list)
    for event in base_analysis['events']:
        a, b = int(event['route_a']), int(event['route_b'])
        in_a, in_b = a in lifted_set, b in lifted_set
        if not (in_a or in_b):
            continue
        loc_a = chain_position(ctx, a, event['x'], event['y'])
        loc_b = chain_position(ctx, b, event['x'], event['y'])
        if in_a:
            rows[a].append(dict(partner=b, z=round(float(event['z']), 6),
                                s=float(loc_a[2]),
                                kind_other=loc_b[1],
                                cat_other=ctx.cat.get(b, '?')))
        if in_b:
            rows[b].append(dict(partner=a, z=round(float(event['z']), 6),
                                s=float(loc_b[2]),
                                kind_other=loc_a[1],
                                cat_other=ctx.cat.get(a, '?')))
    return rows


def _route_event_stats(ctx, rid, record, events):
    """Aggregate one lifted route's BASE crossing events."""
    total = ctx.total(rid)
    a_in, a_out = C.Ctx.stubs(record)
    z0 = [e for e in events if e['z'] == C.Z1]
    high = [e for e in events if e['z'] != C.Z1]
    for event in events:
        s = event['s']
        event['side'] = ('head' if s <= a_in + 1e-9
                         else ('tail' if s >= total - a_out - 1e-9
                               else 'travel'))
        event['dist_port'] = min(s, total - s)
    stats = dict(
        crossing_events=len(events),
        crossing_pairs=len({e['partner'] for e in events}),
        z0_events=len(z0), high_events=len(high),
        z0_adjacent_line=sum(1 for e in z0 if e['cat_other'] == 'adjacent_z1'
                             and e['kind_other'] != 'arc'),
        z0_adjacent_arc=sum(1 for e in z0 if e['cat_other'] == 'adjacent_z1'
                            and e['kind_other'] == 'arc'),
        z0_opposite=sum(1 for e in z0 if e['cat_other'].startswith('opposite')),
        z0_same_u=sum(1 for e in z0 if e['cat_other'] == 'same_u_z1'),
        z0_other=sum(1 for e in z0 if not (
            e['cat_other'] == 'adjacent_z1'
            or e['cat_other'].startswith('opposite')
            or e['cat_other'] == 'same_u_z1')),
        high_opposite=sum(1 for e in high if e['cat_other'].startswith('opposite')),
        high_same_u=sum(1 for e in high if e['cat_other'] == 'same_u_z1'),
        high_other=sum(1 for e in high if not (
            e['cat_other'].startswith('opposite')
            or e['cat_other'] == 'same_u_z1')),
        high_by_z=dict(Counter(str(e['z']) for e in high)),
        z0_head=sum(1 for e in z0 if e['side'] == 'head'),
        z0_tail=sum(1 for e in z0 if e['side'] == 'tail'),
    )
    head_z0 = sorted(e['s'] for e in z0 if e['side'] == 'head')
    tail_z0 = sorted(total - e['s'] for e in z0 if e['side'] == 'tail')
    stats['nearest_head_crossing_arclen'] = round(head_z0[0], 4) if head_z0 else None
    stats['nearest_tail_crossing_arclen'] = round(tail_z0[0], 4) if tail_z0 else None
    stats['max_head_crossing_arclen'] = round(head_z0[-1], 4) if head_z0 else None
    stats['max_tail_crossing_arclen'] = round(tail_z0[-1], 4) if tail_z0 else None
    if events:
        first = min(events, key=lambda e: e['s'])
        near = min(events, key=lambda e: e['dist_port'])
        stats['first_crossing_arclen'] = round(first['s'], 4)
        stats['first_crossing_dist_port'] = round(near['dist_port'], 4)
        stats['first_crossing_side'] = near['side']
        stats['first_crossing_cat'] = near['cat_other']
    else:
        stats.update(first_crossing_arclen=None, first_crossing_dist_port=None,
                     first_crossing_side='', first_crossing_cat='')
    return stats


def _removed_z0(stats, z0_events, total, new_a_in, new_a_out):
    removed = 0
    for event in z0_events:
        if event['side'] == 'head' and event['s'] > new_a_in + 1e-9:
            removed += 1
        elif event['side'] == 'tail' and (total - event['s']) > new_a_out + 1e-9:
            removed += 1
    return removed


def d1():
    t_start = time.perf_counter()
    C.ensure_dir(D1_DIR)
    ctx = C.load_ctx()
    lifted = _lifted_z1_routes(ctx)
    lifted_set = set(lifted)
    print(f'[D1] lifted z1 routes={len(lifted)}')
    t = time.perf_counter()
    base_analysis = C.audit(ctx.records_base, ctx)
    print(f'[D1] base audit {time.perf_counter() - t:.2f}s unique='
          f'{base_analysis["n_unique_pairs"]} adj={base_analysis["adjacent_related_events"]}')
    t = time.perf_counter()
    event_rows = _event_rows_for_lifted(ctx, base_analysis, lifted_set)
    print(f'[D1] per-route events for {len(event_rows)} routes '
          f'{time.perf_counter() - t:.2f}s')

    world = ctx.world(ctx.records_base)
    rows = []
    legal_payload = {}
    candidate_rows = []
    t_search = time.perf_counter()
    for index, rid in enumerate(lifted):
        record = ctx.by_id[rid]
        layer = C.Ctx.route_target_layer(record)
        total = ctx.total(rid)
        f = S.footprint(ctx, rid, layer)
        a_in, a_out = C.Ctx.stubs(record)
        events = event_rows.get(rid, [])
        stats = _route_event_stats(ctx, rid, record, events)
        grid = S.window_grid(ctx, rid, layer)
        world.remove_route(rid)
        legal = []
        for a_rise, a_fall in grid:
            rec, route = S.evaluate_single(ctx, world, rid, layer, a_rise, a_fall,
                                           collect=False)
            is_legal = bool(rec['legal'])
            if is_legal:
                legal.append((float(a_rise), float(a_fall)))
            candidate_rows.append(dict(route_id=rid, target_layer=layer,
                                       a_in=a_rise, a_out=a_fall,
                                       built=bool(rec['built']),
                                       legal=is_legal))
        world.add_route(record)
        earlier = [(i, o) for i, o in legal
                   if i < a_in - 0.05 or o < a_out - 0.05]
        best_earlier = min(earlier, key=lambda w: (w[0] + w[1], w[0])) if earlier else None
        min_ain = min(legal, key=lambda w: (w[0], w[1])) if legal else None
        min_total = min(legal, key=lambda w: (w[0] + w[1], w[0])) if legal else None
        removed = 0
        if best_earlier:
            removed = _removed_z0(stats, [e for e in events if e['z'] == C.Z1],
                                  total, best_earlier[0], best_earlier[1])
        entry = ctx.pairs_by_rid.get(rid)
        row = dict(
            route_id=rid,
            pair_id=entry['pair_id'] if entry else '',
            direction=ctx.manifest[rid].get('pair', ''),
            target_layer=layer,
            total_mm=round(total, 4),
            footprint_mm=round(f, 4),
            current_a_in=round(a_in, 4),
            current_a_out=round(a_out, 4),
            current_rise_start_mm=round(a_in, 4),
            current_fall_start_mm=round(total - a_out - f, 4),
            current_stub_total_mm=round(a_in + a_out, 4),
            n_candidates=len(grid),
            n_legal=len(legal),
            n_legal_earlier=len(earlier),
            min_legal_a_in=min_ain[0] if min_ain else None,
            min_legal_a_in_a_out=min_ain[1] if min_ain else None,
            min_legal_stub=(round(min_total[0] + min_total[1], 4)
                            if min_total else None),
            min_legal_stub_a_in=min_total[0] if min_total else None,
            min_legal_stub_a_out=min_total[1] if min_total else None,
            best_earlier_a_in=best_earlier[0] if best_earlier else None,
            best_earlier_a_out=best_earlier[1] if best_earlier else None,
            predicted_z0_removed=removed,
            **stats,
        )
        row['z0_events'] = stats['z0_events']
        rows.append(row)
        legal_payload[str(rid)] = dict(
            route_id=rid, target_layer=layer, total_mm=round(total, 6),
            footprint_mm=round(f, 6),
            current_a_in=round(a_in, 6), current_a_out=round(a_out, 6),
            n_candidates=len(grid), n_legal=len(legal),
            legal=[[round(i, 6), round(o, 6)] for i, o in legal])
        if (index + 1) % 20 == 0 or index + 1 == len(lifted):
            elapsed = time.perf_counter() - t_search
            print(f'[D1] searched {index + 1}/{len(lifted)} ({elapsed:.1f}s, '
                  f'eta {elapsed / (index + 1) * (len(lifted) - index - 1):.0f}s)')
    search_seconds = time.perf_counter() - t_search
    print(f'[D1] window search done in {search_seconds:.1f}s')

    C.write_csv(D1_DIR / 'D1_access_analysis.csv', rows)
    C.write_csv(D1_DIR / 'D1_access_candidates.csv', candidate_rows)
    C.write_json(D1_DIR / 'D1_legal_windows.json', legal_payload)
    summary = _d1_summary(ctx, rows, base_analysis, lifted, search_seconds)
    C.write_json(D1_DIR / 'D1_summary.json', summary)
    print('[D1] summary:')
    for key in ('n_lifted_routes', 'n_both55', 'adjacent_events_involving_lifted',
                'adjacent_line_involving_lifted', 'adjacent_arc_involving_lifted',
                'n_with_earlier_legal', 'n_shorter_min_a_in',
                'predicted_z0_removed_total', 'n_min_legal_stub_lt_current'):
        print(f'   {key} = {summary.get(key)}')
    _d1_figures(ctx, rows, lifted, legal_payload)
    print(f'[D1] done in {time.perf_counter() - t_start:.1f}s -> {D1_DIR}')
    return summary


def _d1_summary(ctx, rows, base_analysis, lifted, search_seconds):
    lifted_set = set(lifted)
    adj_total = adj_lifted = adj_flat = 0
    adj_line_lifted = adj_arc_lifted = 0
    adj_line_flat = adj_arc_flat = 0
    opp_opp_lifted = opp_opp_total = 0
    same_u_lifted = same_u_total = 0
    for event in base_analysis['events']:
        a, b = int(event['route_a']), int(event['route_b'])
        cats = (ctx.cat.get(a, '?'), ctx.cat.get(b, '?'))
        is_adj = 'adjacent_z1' in cats
        adj_route = a if cats[0] == 'adjacent_z1' else b
        other = b if adj_route == a else a
        if is_adj:
            loc = C.locate_on_chain(ctx.chain(adj_route), event['x'], event['y'])
            kind = 'arc' if (loc is not None and loc[1] == 'arc') else 'line'
            if event['z'] == C.Z1 and (
                    ctx.cat.get(other, '').startswith('opposite_z1')):
                adj_total += 1
                if other in lifted_set:
                    adj_lifted += 1
                    if kind == 'arc':
                        adj_arc_lifted += 1
                    else:
                        adj_line_lifted += 1
                else:
                    adj_flat += 1
                    if kind == 'arc':
                        adj_arc_flat += 1
                    else:
                        adj_line_flat += 1
        if event['z'] == C.Z1 and cats[0].startswith('opposite') and \
                cats[1].startswith('opposite'):
            opp_opp_total += 1
            if a in lifted_set or b in lifted_set:
                opp_opp_lifted += 1
        if event['z'] == C.Z1 and {cats[0], cats[1]} & {'opposite_z1_EW',
                                                        'opposite_z1_NS'} and \
                ('same_u_z1' in cats):
            same_u_total += 1
            if a in lifted_set or b in lifted_set:
                same_u_lifted += 1
    stub_counts = Counter()
    for row in rows:
        stub_counts[(round(row['current_a_in'], 3),
                     round(row['current_a_out'], 3))] += 1
    n_earlier = sum(1 for row in rows if row['n_legal_earlier'] > 0)
    n_shorter_min_ain = sum(1 for row in rows
                            if row['min_legal_a_in'] is not None
                            and row['min_legal_a_in'] < row['current_a_in'] - 0.5)
    n_shorter_stub = sum(1 for row in rows
                         if row['min_legal_stub'] is not None
                         and row['min_legal_stub'] < row['current_stub_total_mm'] - 1.0)
    removed_total = sum(int(row.get('predicted_z0_removed') or 0) for row in rows)
    min_ain_values = [row['min_legal_a_in'] for row in rows
                      if row['min_legal_a_in'] is not None]

    def _quant(values, frac):
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(frac * len(ordered)))], 4)

    return dict(
        experiment='E1-D D1 access analysis (BASE layout)',
        n_lifted_routes=len(rows),
        layer_counts=dict(sorted(Counter(
            row['target_layer'] for row in rows).items())),
        direction_counts=dict(sorted(Counter(
            row['direction'] for row in rows).items())),
        stub_distribution={f'{k[0]:.2f}/{k[1]:.2f}': v
                           for k, v in sorted(stub_counts.items())},
        n_both55=sum(1 for row in rows if abs(row['current_a_in'] - 55.0) < 1e-6
                     and abs(row['current_a_out'] - 55.0) < 1e-6),
        n_one_side55=sum(1 for row in rows
                         if any(abs(v - 55.0) < 1e-6 for v in
                                (row['current_a_in'], row['current_a_out']))),
        current_stub_total_sum=round(sum(row['current_stub_total_mm']
                                         for row in rows), 3),
        adjacent_related_events=adj_total,
        adjacent_events_involving_lifted=adj_lifted,
        adjacent_events_involving_flat_opposite=adj_flat,
        adjacent_line_involving_lifted=adj_line_lifted,
        adjacent_arc_involving_lifted=adj_arc_lifted,
        adjacent_line_involving_flat=adj_line_flat,
        adjacent_arc_involving_flat=adj_arc_flat,
        opposite_opposite_events_total=opp_opp_total,
        opposite_opposite_events_involving_lifted=opp_opp_lifted,
        same_u_events_total=same_u_total,
        same_u_events_involving_lifted=same_u_lifted,
        lifted_route_event_total=sum(row['crossing_events'] for row in rows),
        lifted_route_z0_event_total=sum(row['z0_events'] for row in rows),
        lifted_route_high_event_total=sum(row['high_events'] for row in rows),
        n_legal_zero=sum(1 for row in rows if row['n_legal'] == 0),
        n_legal_positive=sum(1 for row in rows if row['n_legal'] > 0),
        n_legal_distribution=dict(sorted(Counter(
            row['n_legal'] for row in rows).items())),
        n_with_earlier_legal=n_earlier,
        n_shorter_min_a_in=n_shorter_min_ain,
        n_min_legal_stub_lt_current=n_shorter_stub,
        predicted_z0_removed_total=removed_total,
        predicted_z0_removed_both55=sum(
            int(row.get('predicted_z0_removed') or 0) for row in rows
            if abs(row['current_a_in'] - 55.0) < 1e-6
            and abs(row['current_a_out'] - 55.0) < 1e-6),
        min_legal_a_in_quantiles=dict(
            p10=_quant(min_ain_values, 0.10), p25=_quant(min_ain_values, 0.25),
            p50=_quant(min_ain_values, 0.50), p75=_quant(min_ain_values, 0.75),
            p90=_quant(min_ain_values, 0.90)),
        search_seconds=round(search_seconds, 2),
        note=('Earlier legal windows found on the BASE layout with all other '
              'routes fixed. predicted_z0_removed is the number of z=0 '
              'crossing events of these routes that would disappear if each '
              'route took its best earlier legal window (upper bound, high-layer '
              'effects measured exactly in D2).'),
    )


def _d1_figures(ctx, rows, lifted, legal_payload):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from four_side_1024.e1 import plots as P

    figdir = C.ensure_dir(D1_DIR / 'figures')
    before_head = [row['current_a_in'] for row in rows]
    before_tail = [row['current_a_out'] for row in rows]
    after_head = [row['best_earlier_a_in'] for row in rows]
    after_tail = [row['best_earlier_a_out'] for row in rows]
    earlier = [row for row in rows if row['best_earlier_a_in'] is not None]

    fig, axes = plt.subplots(1, 3, figsize=(17.0, 5.0))
    axes[0].hist(before_head, bins=list(range(0, 60, 5)), alpha=0.55,
                 color='#e03131', label='BASE head stub')
    axes[0].hist(before_tail, bins=list(range(0, 60, 5)), alpha=0.45,
                 color='#e07b1a', label='BASE tail stub')
    if earlier:
        axes[0].hist([row['best_earlier_a_in'] for row in earlier],
                     bins=list(range(0, 60, 5)), alpha=0.55, color='#2f9e44',
                     label='best earlier head')
        axes[0].hist([row['best_earlier_a_out'] for row in earlier],
                     bins=list(range(0, 60, 5)), alpha=0.45, color='#1f6fd6',
                     label='best earlier tail')
    axes[0].set_xlabel('base stub length (mm)')
    axes[0].set_ylabel('routes')
    axes[0].legend(fontsize=7)
    axes[0].set_title('Z1 opposite base stubs: BASE vs best earlier legal window',
                      fontsize=9)
    if earlier:
        axes[1].scatter([row['current_stub_total_mm'] for row in earlier],
                        [row['best_earlier_a_in'] + row['best_earlier_a_out']
                         for row in earlier], s=14, color='#2f9e44', alpha=0.7)
        limit = max([row['current_stub_total_mm'] for row in earlier] + [10])
        axes[1].plot([0, limit], [0, limit], 'k--', lw=0.8)
    axes[1].set_xlabel('BASE stub total a_in+a_out (mm)')
    axes[1].set_ylabel('best earlier legal stub total (mm)')
    axes[1].set_title('stub shortening potential', fontsize=9)
    axes[1].grid(alpha=0.2)

    def z0_paths(record):
        segments = []
        for part in record.get('parts') or []:
            if part['kind'] != 'flat' or abs(part['z_mm']) > 1e-9:
                continue
            xs, ys = P.sample_primitives(part['primitives'])
            if len(xs):
                segments.append((xs, ys))
        return segments

    highlight = earlier[:60]
    for row in highlight:
        rid = row['route_id']
        for xs, ys in z0_paths(ctx.by_id[rid]):
            axes[2].plot(xs, ys, color='#e03131', lw=0.5, alpha=0.5)
        new_record = S.build_single(ctx, rid, row['target_layer'],
                                    row['best_earlier_a_in'],
                                    row['best_earlier_a_out'])
        if new_record is not None:
            for xs, ys in z0_paths(new_record):
                axes[2].plot(xs, ys, color='#2f9e44', lw=0.6, alpha=0.7)
    axes[2].set_xlim(0, 150)
    axes[2].set_ylim(0, 150)
    axes[2].set_aspect('equal')
    axes[2].set_title(f'Z1 stubs XY: BASE red / shorter green '
                      f'({len(highlight)} routes shown)', fontsize=9)
    axes[2].grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(figdir / 'z1_access_before_after.png', dpi=170,
                bbox_inches='tight')
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.2))
    for row in rows:
        color = '#e03131'
        cat = row['first_crossing_cat']
        if cat == 'adjacent_z1':
            color = '#e07b1a'
        elif cat.startswith('opposite'):
            color = '#1f6fd6'
        elif cat == 'same_u_z1':
            color = '#2f9e44'
        axes[0].scatter(row['first_crossing_dist_port'] or 0,
                        row['current_a_in'], s=12, color=color, alpha=0.75)
    axes[0].set_xlabel('first crossing distance to nearest port (mm)')
    axes[0].set_ylabel('current rise start a_in (mm)')
    axes[0].set_title('first crossing vs rise start (BASE)', fontsize=9)
    axes[0].grid(alpha=0.2)
    axes[0].legend(handles=[
        plt.Line2D([], [], marker='o', color='#e07b1a', lw=0, label='adjacent z1'),
        plt.Line2D([], [], marker='o', color='#1f6fd6', lw=0, label='opposite z1'),
        plt.Line2D([], [], marker='o', color='#2f9e44', lw=0, label='same_u z1')],
        fontsize=7)
    diag = [row for row in rows if row['max_head_crossing_arclen'] is not None
            and row['min_legal_a_in'] is not None]
    if diag:
        axes[1].scatter([row['max_head_crossing_arclen'] for row in diag],
                        [row['min_legal_a_in'] for row in diag],
                        s=14, color='#2f9e44', alpha=0.75)
        limit = max(max(row['max_head_crossing_arclen'] for row in diag),
                    max(row['min_legal_a_in'] for row in diag), 10.0)
        axes[1].plot([0, limit], [0, limit], 'k--', lw=0.8)
    axes[1].set_xlabel('outermost head-side crossing arclength (mm)')
    axes[1].set_ylabel('minimal legal a_in (mm)')
    axes[1].set_title('min legal rise vs outermost head crossing\n(points below '
                      'the line can remove head crossings)', fontsize=9)
    axes[1].grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figdir / 'first_crossing_vs_rise.png', dpi=170,
                bbox_inches='tight')
    plt.close(fig)

    P.four_side_zoom(D1_DIR, ctx.records_base, 'D1 BASE', ctx=ctx,
                     highlight_ids=lifted, tag='four_side_zoom')
    print(f'[D1] figures written to {figdir}')


def _cmd_d1():
    d1()


# ---------------------------------------------------------------------------
# exact-increment crossing engine (movable routes only)
# ---------------------------------------------------------------------------
class LiftingEngine:
    """Exact crossing bookkeeping for routes whose S-bend windows may change.

    A movable route is modelled by its fixed 2D chain: its height at arclength
    ``s`` is read from its current record (base stub -> base row z, target-layer
    travel -> layer z, transition -> None).  Every fixed route contributes its
    real flat parts with their real z.  Crossing events are the fixed 2D
    intersections; a crossing exists when both sides are flat at the same z.

    Because only movable routes change, all deltas of a candidate replacement
    are exactly computable from the precomputed events.
    """

    def __init__(self, ctx, movable, fixed_records, policy='strict',
                 verbose=True):
        started = time.perf_counter()
        self.ctx = ctx
        self.movable = {int(rid) for rid in movable}
        entries = []
        for rid in sorted(self.movable):
            entries.append(dict(kind='movable', rid=rid,
                                prep=V.prepare_route(ctx.chain(rid), rid)))
        for record in fixed_records:
            rid = int(record['route_id'])
            if rid in self.movable:
                continue
            for index, part in enumerate(record.get('parts') or []):
                if part['kind'] != 'flat':
                    continue
                entries.append(dict(kind='fixed', rid=rid, index=index,
                                    z=round(float(part['z_mm']), 6),
                                    prep=V.prepare_route(part['primitives'],
                                                         rid)))
        pairs = V._candidate_pairs([entry['prep'] for entry in entries],
                                   C.CLEARANCE + 2.0 * V.SAGITTA)
        if verbose:
            print(f'  [lift-engine] entries={len(entries)} broad_pairs={len(pairs)} '
                  f'{time.perf_counter() - started:.2f}s')
        self.mm_events = []
        self.mf_events = []
        self.by_m = defaultdict(list)
        for index_a, index_b in pairs:
            first, second = entries[index_a], entries[index_b]
            if first['kind'] == 'fixed' and second['kind'] == 'fixed':
                continue
            result = V.evaluate_pair(first['prep'], second['prep'],
                                     C.CLEARANCE, V.SAGITTA, policy)
            if result is None or not result['crossings'] or not result['valid']:
                continue
            if first['kind'] == 'movable' and second['kind'] == 'movable':
                for crossing in result['crossings']:
                    index = len(self.mm_events)
                    self.mm_events.append(dict(
                        a=first['rid'], b=second['rid'],
                        s_a=float(crossing['sa']), s_b=float(crossing['sb']),
                        x=float(crossing['point'][0]),
                        y=float(crossing['point'][1])))
                    self.by_m[first['rid']].append(('mm', index, True))
                    self.by_m[second['rid']].append(('mm', index, False))
            else:
                if first['kind'] == 'movable':
                    mover, fixed, s_m, s_f = first, second, 'sa', 'sb'
                else:
                    mover, fixed, s_m, s_f = second, first, 'sb', 'sa'
                cat = ctx.cat.get(fixed['rid'], '?')
                for crossing in result['crossings']:
                    point = crossing['point']
                    adj_kind = ''
                    if cat == 'adjacent_z1' and fixed['z'] == C.Z1:
                        located = C.locate_on_chain(ctx.chain(fixed['rid']),
                                                    point[0], point[1])
                        adj_kind = 'arc' if (located is not None
                                             and located[1] == 'arc') else 'line'
                    index = len(self.mf_events)
                    self.mf_events.append(dict(
                        m=mover['rid'], s_m=float(crossing[s_m]),
                        f=fixed['rid'], z=fixed['z'],
                        s_f=float(crossing[s_f]),
                        x=float(point[0]), y=float(point[1]),
                        cat=cat, adj_kind=adj_kind))
                    self.by_m[mover['rid']].append(('mf', index, True))
        self.build_seconds = time.perf_counter() - started
        if verbose:
            print(f'  [lift-engine] mm_events={len(self.mm_events)} '
                  f'mf_events={len(self.mf_events)} '
                  f'build={self.build_seconds:.2f}s')

    # -- per-route crossing statistics ------------------------------------
    def route_stats(self, rid, geom, geoms):
        """(pairs, events, per_height, adjacent_line, adjacent_arc) of one route."""
        rid = int(rid)
        partners = {}
        events = 0
        per_height = Counter()
        adjacent_line = adjacent_arc = adjacent_related = 0
        for kind, index, is_m in self.by_m.get(rid, ()):
            if kind == 'mm':
                event = self.mm_events[index]
                s_self = event['s_a'] if is_m else event['s_b']
                z_self = geom_z_at(geom, s_self)
                if z_self is None:
                    continue
                other = event['b'] if is_m else event['a']
                other_geom = geoms.get(other)
                if other_geom is None:
                    continue
                s_other = event['s_b'] if is_m else event['s_a']
                if geom_z_at(other_geom, s_other) != z_self:
                    continue
            else:
                event = self.mf_events[index]
                z_self = geom_z_at(geom, event['s_m'])
                if z_self is None or z_self != event['z']:
                    continue
                other = event['f']
                if z_self == C.Z1 and event['cat'] == 'adjacent_z1':
                    adjacent_related += 1
                    if event['adj_kind'] == 'arc':
                        adjacent_arc += 1
                    else:
                        adjacent_line += 1
            events += 1
            per_height[z_self] += 1
            if other in partners:
                partners[other] += 1
            else:
                partners[other] = 1
        return dict(pairs=len(partners), events=events,
                    per_height=dict(per_height), adjacent_related=adjacent_related,
                    adjacent_line=adjacent_line, adjacent_arc=adjacent_arc)

    def full_audit(self, records, verbose=False):
        """Crossing audit of one complete layout (movable-involved events)."""
        geoms = {int(record['route_id']): route_geom(record) for record in records
                 if int(record['route_id']) in self.movable}
        per_route = Counter()
        unique_pairs = set()
        events = 0
        adjacent_related = adjacent_line = adjacent_arc = 0
        for rid, geom in geoms.items():
            stats = self.route_stats(rid, geom, geoms)
            per_route[rid] = stats['events']
            adjacent_related += stats['adjacent_related']
            adjacent_line += stats['adjacent_line']
            adjacent_arc += stats['adjacent_arc']
        for event in self.mm_events:
            za = geom_z_at(geoms[event['a']], event['s_a'])
            if za is None:
                continue
            zb = geom_z_at(geoms[event['b']], event['s_b'])
            if zb is None or za != zb:
                continue
            events += 1
            unique_pairs.add((min(event['a'], event['b']),
                              max(event['a'], event['b'])))
        for event in self.mf_events:
            z_self = geom_z_at(geoms[event['m']], event['s_m'])
            if z_self is None or z_self != event['z']:
                continue
            events += 1
            unique_pairs.add((min(event['m'], event['f']),
                              max(event['m'], event['f'])))
        return dict(events=events, unique_pairs=len(unique_pairs),
                    per_route=per_route, adjacent_related=adjacent_related,
                    adjacent_line=adjacent_line, adjacent_arc=adjacent_arc)


def verify_engine():
    ctx = C.load_ctx()
    lifted = _lifted_z1_routes(ctx)
    base_analysis = C.audit(ctx.records_base, ctx)
    engine = LiftingEngine(ctx, lifted, ctx.records_base)
    geoms = {rid: route_geom(ctx.by_id[rid]) for rid in lifted}
    bad = []
    totals = Counter()
    for rid in lifted:
        stats = engine.route_stats(rid, geoms[rid], geoms)
        base_events = base_analysis['per_route'].get(rid, 0)
        if stats['events'] != base_events:
            bad.append((rid, base_events, stats['events']))
        totals['event_base'] += base_events
        totals['event_engine'] += stats['events']
        totals['adj_base'] += sum(
            1 for event in base_analysis['events']
            if event['z'] == C.Z1 and rid in (event['route_a'], event['route_b'])
            and 'adjacent_z1' in (ctx.cat.get(event['route_a']),
                                  ctx.cat.get(event['route_b'])))
        totals['adj_engine'] += stats['adjacent_related']
    print(f'verify_engine: routes={len(lifted)} event mismatches={len(bad)} '
          f'totals={dict(totals)}')
    for item in bad[:12]:
        print('   rid', item)
    # fixed-fixed / movable involvement sanity: compare full audit
    full = engine.full_audit(ctx.records_base)
    print(f'engine movable events={full["events"]} unique_pairs={full["unique_pairs"]} '
          f'adj={full["adjacent_related"]} line={full["adjacent_line"]} arc={full["adjacent_arc"]}')
    # core audit restricted to movable-involved events
    base_events_m = [event for event in base_analysis['events']
                     if int(event['route_a']) in engine.movable
                     or int(event['route_b']) in engine.movable]
    base_pairs = {(min(int(e['route_a']), int(e['route_b'])),
                   max(int(e['route_a']), int(e['route_b'])))
                  for e in base_events_m}
    adj_base = 0
    line_base = 0
    arc_base = 0
    for event in base_events_m:
        cats = (ctx.cat.get(int(event['route_a'])), ctx.cat.get(int(event['route_b'])))
        if 'adjacent_z1' in cats and event['z'] == C.Z1:
            other = int(event['route_a']) if cats[0] != 'adjacent_z1' else int(event['route_b'])
            if ctx.cat[other].startswith('opposite_z1'):
                adj_base += 1
                adj = int(event['route_a']) if cats[0] == 'adjacent_z1' else int(event['route_b'])
                located = C.locate_on_chain(ctx.chain(adj), event['x'], event['y'])
                if located is not None and located[1] == 'arc':
                    arc_base += 1
                else:
                    line_base += 1
    print(f'core movable events={len(base_events_m)} unique_pairs={len(base_pairs)} '
          f'adj={adj_base} line={line_base} arc={arc_base}')


def _read_csv_rows(path):
    import csv
    with open(path, 'r', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def d2():
    ctx = C.load_ctx()
    lifted = _lifted_z1_routes(ctx)
    legal_path = D1_DIR / 'D1_legal_windows.json'
    if not legal_path.exists():
        raise SystemExit(f'missing {legal_path}; run D1 first')
    legal_map = _load_legal_map(legal_path)
    d1_rows = _read_csv_rows(D1_DIR / 'D1_access_analysis.csv')
    print(f'[D2] movable={len(lifted)} legal-window entries={len(legal_map)}')
    base_analysis = C.audit(ctx.records_base, ctx)
    summary, report, analysis, changes = refine(
        ctx, ctx.records_base, lifted, legal_map, D2_DIR,
        'E1-D D2 baseline asymmetric',
        note=('BASE layout with independent a_in/a_out S-bend windows for the '
              'already-lifted Z1 opposite routes (world-legal greedy, exact '
              'incremental crossing accounting).'),
        base_analysis=base_analysis, baseline_records=ctx.records_base,
        comparison_tag='D2_vs_BASE', d1_rows=d1_rows)
    print(f'[D2] done: {len(changes)} routes re-windowed')
    return summary, analysis, changes


def selftest():
    """Tiny dry run of the refinement loop on two routes (no artefacts)."""
    ctx = C.load_ctx()
    rid = _lifted_z1_routes(ctx)[0]
    layer = C.Ctx.route_target_layer(ctx.by_id[rid])
    world = ctx.world(ctx.records_base)
    world.remove_route(rid)
    legal = []
    for a_in, a_out in S.window_grid(ctx, rid, layer):
        record = S.build_single(ctx, rid, layer, a_in, a_out)
        if record is None or S.structure_errors(record):
            continue
        if not world.check_route(record):
            legal.append((a_in, a_out))
    world.add_route(ctx.by_id[rid])
    print(f'selftest route {rid} layer {layer} legal={legal}')
    legal_map = {rid: dict(target_layer=layer, legal=legal,
                           current=C.Ctx.stubs(ctx.by_id[rid]))}
    refine(ctx, ctx.records_base, [rid], legal_map, D_ROOT / '_selftest',
           'selftest', dry_run=True, max_passes=1)


# ---------------------------------------------------------------------------
# D3: window search + refinement on the Lead's E1-C best solution
# ---------------------------------------------------------------------------
def _search_windows(ctx, records, movable, tag='search', window_log=None):
    """Search the current layer's structurally valid windows on a fixed layout."""
    by_id = {int(record['route_id']): record for record in records}
    world = ctx.world(records)
    legal_map = {}
    candidate_rows = []
    started = time.perf_counter()
    for index, rid in enumerate(movable):
        record = by_id[rid]
        layer = C.Ctx.route_target_layer(record)
        a_in, a_out = C.Ctx.stubs(record)
        grid = S.window_grid(ctx, rid, layer)
        world.remove_route(rid)
        legal = []
        for a_rise, a_fall in grid:
            candidate, route = S.evaluate_single(ctx, world, rid, layer,
                                                 a_rise, a_fall, collect=False)
            is_legal = bool(candidate['legal'])
            if is_legal:
                legal.append((float(a_rise), float(a_fall)))
            candidate_rows.append(dict(route_id=rid, target_layer=layer,
                                       a_in=a_rise, a_out=a_fall,
                                       built=bool(candidate['built']),
                                       legal=is_legal))
        world.add_route(record)
        legal_map[rid] = dict(target_layer=layer, legal=legal,
                              current=(float(a_in), float(a_out)))
        if (index + 1) % 20 == 0 or index + 1 == len(movable):
            elapsed = time.perf_counter() - started
            print(f'[{tag}] searched {index + 1}/{len(movable)} ({elapsed:.1f}s, '
                  f'eta {elapsed / (index + 1) * (len(movable) - index - 1):.0f}s)',
                  flush=True)
    payload = {str(rid): dict(route_id=rid, target_layer=info['target_layer'],
                              total_mm=round(ctx.total(rid), 6),
                              footprint_mm=round(S.footprint(
                                  ctx, rid, info['target_layer']), 6),
                              current_a_in=info['current'][0],
                              current_a_out=info['current'][1],
                              n_candidates=len(
                                  [row for row in candidate_rows
                                   if row['route_id'] == rid]),
                              n_legal=len(info['legal']),
                              legal=[[round(a, 6), round(b, 6)]
                                     for a, b in info['legal']])
               for rid, info in legal_map.items()}
    return legal_map, candidate_rows, payload, time.perf_counter() - started


def d3(source_dir, include_z2=False, folder=None, comparison_tag=None,
       experiment_name=None):
    """D3: refine the Lead's E1-C best layout with the validated refiner.

    ``include_z2=True`` additionally allows the refiner to retune every Z2
    route that the E1-C layout lifted (the task allows local Z2 retuning).
    """
    from four_side_1024.e1 import refine as R
    from four_side_1024.e1 import plots as P
    source_dir = Path(source_dir)
    ctx = C.load_ctx()
    payload = C.read_json(source_dir / 'routes_1024.json')
    records = [record for record in payload['routes']
               if record.get('status') == 'routed']
    by_id = {int(record['route_id']): record for record in records}
    missing = [rid for rid in ctx.manifest if rid not in by_id]
    if missing:
        raise SystemExit(f'D3 source is missing {len(missing)} routes')
    movable = [rid for rid in ctx.z1_opposite
               if C.Ctx.route_target_layer(by_id[rid]) > 1]
    if include_z2:
        movable += [rid for rid in sorted(by_id)
                    if ctx.manifest[rid]['plane'] == 'z2'
                    and C.Ctx.route_target_layer(by_id[rid]) > 1]
    folder = C.ensure_dir(folder or D3_DIR)
    comparison_tag = comparison_tag or 'D3_vs_E1C_best'
    experiment_name = experiment_name or 'E1-D D3 e1c_best'
    print(f'[D3] source={source_dir} records={len(records)} '
          f'movable lifted z1 opposite={len([rid for rid in movable if ctx.manifest[rid]["plane"] == "z1"])} '
          f'z2 lifted={len([rid for rid in movable if ctx.manifest[rid]["plane"] == "z2"])}')
    ref_analysis = C.audit(records, ctx)
    print(f'[D3] reference: unique={ref_analysis["n_unique_pairs"]} '
          f'z1={ref_analysis["z1_pairs"]} '
          f'adj={ref_analysis["adjacent_related_events"]} '
          f'high={ref_analysis["high_pairs"]}')
    result = R.refine(ctx, records, movable_rids=movable)
    final = result['records']
    raw_changes = result['changed']

    # -- repair against the frozen validator --------------------------------
    # ClearanceWorld3D used by refine is slightly less strict than the frozen
    # validator; any route that becomes a validator violation is reverted to
    # the E1-C input geometry (which is violation-free) until the layout is
    # clean.
    c3_by_id = {int(record['route_id']): record for record in records}
    final_by_id = {int(record['route_id']): record for record in final}

    def _validate(records_to_check):
        payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                       experiment=experiment_name,
                       layer_stack=C.Z.stack_payload(C.MAX_LAYER),
                       routes=records_to_check)
        report = C.Z.validate_payload(payload, max_layer=C.MAX_LAYER,
                                      log=lambda *args: None)
        return report

    t_repair = time.perf_counter()
    report = _validate(final)
    raw_violations = len(report.get('violations') or [])
    raw_counts = dict(report.get('counts') or {})
    revert_ids = set()
    repair_log = []
    guard = 0
    while (report.get('violations') or []) and guard < 15:
        guard += 1
        ids = set()
        for violation in report['violations']:
            rid = violation.get('route_id')
            if rid is None:
                for key in ('route_a', 'route_b', 'route', 'id'):
                    if violation.get(key) is not None:
                        rid = violation[key]
                        break
            if rid is not None:
                ids.add(int(rid))
        if not ids:
            print('[D3] cannot map validator violations to routes:',
                  report['violations'][:3], flush=True)
            break
        revert_ids |= ids
        for rid in ids:
            if rid in c3_by_id:
                final_by_id[rid] = c3_by_id[rid]
        final = [final_by_id[int(record['route_id'])] for record in records]
        report = _validate(final)
        repair_log.append(dict(iteration=guard, reverted=sorted(ids),
                               violations=len(report.get('violations') or [])))
        print(f'[D3] repair {guard}: reverted {sorted(ids)} -> violations '
              f'{len(report.get("violations") or [])}', flush=True)
    repaired_counts = dict(report.get('counts') or {})
    repair_seconds = time.perf_counter() - t_repair
    print(f'[D3] validation repair: raw changes={len(raw_changes)} '
          f'raw violations={raw_violations}; reverted routes='
          f'{len(revert_ids)}; final violations='
          f'{repaired_counts.get("violations")} in {repair_seconds:.1f}s',
          flush=True)
    changes = [change for change in raw_changes
               if int(change['route_id']) not in revert_ids]
    reverted_changes = [change for change in raw_changes
                        if int(change['route_id']) in revert_ids]
    folder = C.ensure_dir(folder or D3_DIR)
    extra = dict(source_solution=str(source_dir),
                 refiner='four_side_1024.e1.refine.refine',
                 include_z2_movable=bool(include_z2),
                 source_unique_crossing_pairs=ref_analysis['n_unique_pairs'],
                 source_adjacent_related_events=ref_analysis[
                     'adjacent_related_events'],
                 refine_stats=result['stats'],
                 pass_stats=result['pass_stats'],
                 raw_changes=len(raw_changes),
                 applied_changes=len(changes),
                 reverted_route_ids=sorted(int(rid) for rid in revert_ids),
                 reverted_changes=reverted_changes,
                 raw_validation=dict(counts=raw_counts,
                                     n_violations=raw_violations),
                 repair_log=repair_log,
                 repair_seconds=round(repair_seconds, 2),
                 changed_route_ids=[int(change['route_id'])
                                    for change in changes])
    summary, report, analysis = C.save_experiment(
        experiment_name, final, ctx, folder=folder, extra=extra,
        validate=True,
        note=('E1-C best solution refined with independent a_in/a_out S-bend '
              'windows for its lifted Z1 opposite routes'
              + (' and the Z2 routes E1-C moved' if include_z2 else '')
              + ' (validated greedy refiner, exact incremental crossing '
                'accounting).'))
    if repaired_counts.get('violations'):
        raise SystemExit('D3 repair failed: validator violations remain after '
                         'reverting flagged routes')
    C.write_csv(folder / 'window_changes.csv', changes)
    if reverted_changes:
        C.write_csv(folder / 'window_changes_reverted.csv', reverted_changes)
    C.write_json(folder / 'D3_refine_result.json',
                 dict(stats=result['stats'], pass_stats=result['pass_stats'],
                      raw_changes=raw_changes, applied_changes=changes,
                      reverted_changes=reverted_changes,
                      raw_violations=raw_violations,
                      repaired_counts=repaired_counts,
                      repair_log=repair_log))
    ref_summary = {}
    for name in ('summary.json', 'validation.json'):
        path = source_dir / name
        if path.exists():
            loaded = C.read_json(path)
            if name == 'summary.json':
                ref_summary.update(loaded)
            else:
                ref_summary['validation_counts'] = loaded.get('counts')
                ref_summary['validation_status'] = loaded.get('status')
    _write_comparison(ctx, folder, comparison_tag, final, summary,
                      ref_analysis, records, analysis, changes, movable,
                      ref_summary=ref_summary, ref_label='E1-C best')
    P.standard_figures(folder, final, ctx, experiment_name,
                       baseline_records=records, analysis=analysis,
                       baseline_analysis=ref_analysis)
    changed_ids = [int(change['route_id']) for change in changes]
    P.four_side_zoom(folder, final, experiment_name, ctx=ctx,
                     highlight_ids=changed_ids, tag='four_side_zoom')
    _d_access_figures(folder, ctx, records, final, changed_ids,
                      experiment_name)
    print(f'[D3] done: {len(changes)} routes re-windowed -> {folder}')
    return summary, analysis, changes


def d3check(source_dir):
    """Fast pre-flight report on a candidate D3 source layout."""
    from collections import Counter
    source_dir = Path(source_dir)
    ctx = C.load_ctx()
    payload = C.read_json(source_dir / 'routes_1024.json')
    records = [record for record in payload['routes']
               if record.get('status') == 'routed']
    by_id = {int(record['route_id']): record for record in records}
    missing = [rid for rid in ctx.manifest if rid not in by_id]
    print(f'[D3check] source={source_dir}')
    print(f'[D3check] routed={len(records)} missing={len(missing)} '
          f'duplicates={len(records) - len(by_id)}')
    analysis = C.audit(records, ctx)
    stats = C.bar(records)
    usage = C.layer_usage(records, ctx)
    print(f'[D3check] unique={analysis["n_unique_pairs"]} z1={analysis["z1_pairs"]} '
          f'z2={analysis["z2_pairs"]} high={analysis["high_pairs"]} '
          f'adj={analysis["adjacent_related_events"]} '
          f'line={analysis["adjacent_line_events"]} '
          f'arc={analysis["adjacent_arc_events"]} '
          f'opp_opp={analysis["opposite_opposite_events"]} '
          f'trans={stats["transitions"]} h={stats["fabrication_hours"]:.4f}')
    print(f'[D3check] layer route counts={stats["layer_counts"]} '
          f'L6/L7={usage[6]["routes"]}/{usage[7]["routes"]}')
    movable = [rid for rid in ctx.z1_opposite
               if C.Ctx.route_target_layer(by_id[rid]) > 1]
    print(f'[D3check] movable z1-opposite lifted={len(movable)} '
          f'unlifted pairs={len(ctx.unlifted_pairs)}')
    stubs = Counter()
    searchable = []
    chain_bad = []
    for rid in movable:
        record = by_id[rid]
        a_in, a_out = C.Ctx.stubs(record)
        stubs[(round(a_in, 2), round(a_out, 2))] += 1
        geom = route_geom(record)
        if abs(geom[-1][1] - ctx.total(rid)) > 1e-6:
            chain_bad.append(rid)
        if (analysis['per_route'].get(rid, 0) > 0
                and (a_in > 1.2 + 1e-6 or a_out > 1.2 + 1e-6)):
            searchable.append(rid)
    print(f'[D3check] stub distribution={dict(sorted(stubs.items()))}')
    print(f'[D3check] chain-based mismatches={len(chain_bad)} {chain_bad[:5]}')
    print(f'[D3check] routes with events and stubs>1.2 (search set)={len(searchable)}')
    z1_events = [event for event in analysis['events']
                 if 'adjacent_z1' in (ctx.cat.get(int(event['route_a']), '?'),
                                      ctx.cat.get(int(event['route_b']), '?'))]
    print(f'[D3check] adjacent-involved events={len(z1_events)} '
          f'by z={dict(Counter(str(event["z"]) for event in z1_events))}')
    return analysis


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    if cmd == 'probe':
        probe()
    elif cmd == 'verify':
        verify()
    elif cmd == 'diag':
        diag(tuple(int(x) for x in sys.argv[2:]) or (3, 5, 7, 9))
    elif cmd == 'd1':
        d1()
    elif cmd == 'verify_engine':
        verify_engine()
    elif cmd == 'd2':
        d2()
    elif cmd == 'd3check':
        args = sys.argv[2:]
        source = args[args.index('--source') + 1] if '--source' in args else (args[0] if args else None)
        if not source:
            raise SystemExit('d3check needs --source <dir>')
        d3check(source)
    elif cmd == 'd3':
        args = sys.argv[2:]
        source = None
        if '--source' in args:
            source = args[args.index('--source') + 1]
        elif args:
            source = args[0]
        if not source:
            raise SystemExit('d3 needs --source <E1-C best solution dir>')
        include_z2 = '--z2' in args
        folder = None
        tag = None
        if '--folder' in args:
            folder = args[args.index('--folder') + 1]
        if '--tag' in args:
            tag = args[args.index('--tag') + 1]
        d3(source, include_z2=include_z2, folder=folder,
           comparison_tag=tag,
           experiment_name=('E1-D D3 e1c_best z2 retune'
                            if include_z2 else None))
    elif cmd == 'selftest':
        selftest()
    else:
        raise SystemExit(f'unknown command {cmd}')
