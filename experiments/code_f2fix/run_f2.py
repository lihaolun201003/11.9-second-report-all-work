# -*- coding: utf-8 -*-
"""F2 reworked v2: chunked incremental legal F2 from the E1 baseline.

Z1 asymmetric (NS->L2, EW->L3 preferred, adjacent stays interface);
Z2 strict C4 orbits (128), preferentially L4..L7.

Candidate legality uses the frozen validator's own 3D clearance geometry
(exact transition/flat sampling + segment-segment distance), so the acceptance
oracle matches the final validator.  Changes are applied in small chunks and
each chunk is confirmed by a full frozen validation; rejected chunks are
dropped (previous legal state kept), so every accepted checkpoint is legal.
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, '.')

from four_side_1024.e1 import core as C
from four_side_1024.f123 import core as F
from four_side_1024.f123 import savefigs as SF
from four_side_1024.l3d import validate_l3d_multi as V
from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from four_side_1024.c4 import orbits as O
from four_side_1024.c4 import engine as E

OUT = C.Z.CAMPAIGN / 'F2_reworked_Z1_asymmetric_Z2_C4'
LOG = []
CHUNK = 20


def log(*args):
    text = ' '.join(str(a) for a in args)
    LOG.append(text)
    print(text, flush=True)


class FrozenOracle:
    def __init__(self):
        self.stack = V.parse_layer_stack(Z.stack_payload(F.MAX_LAYER),
                                         'embedded')
        self.identity = V._port_identity()
        self.geoms = {}
        self.limit = V.CLEARANCE_MM - V.CLEARANCE_TOL_MM
        self.flat_tree = self.trans_tree = None
        self.flat_route = self.trans_route = None
        self._flat = self._trans = None

    def _parse(self, record):
        return V._parse_route(record, self.stack, self.identity, V._Report())

    def build(self, records):
        self.geoms = {}
        for rid, record in records.items():
            try:
                self.geoms[int(rid)] = self._parse(record)
            except Exception:
                continue
        store = V._build_3d_segment_store(list(self.geoms.values()))
        flat_a, flat_b, self.flat_route = store['flat_a']
        trans_a, trans_b, self.trans_route = store['trans_a']
        from scipy.spatial import cKDTree
        self.flat_tree = (cKDTree(0.5 * (flat_a + flat_b))
                          if len(flat_a) else None)
        self.trans_tree = (cKDTree(0.5 * (trans_a + trans_b))
                           if len(trans_a) else None)
        self._flat = (flat_a, flat_b)
        self._trans = (trans_a, trans_b)

    @staticmethod
    def _cat(parts):
        return np.vstack(parts) if parts else np.zeros((0, 3))

    def segments(self, geom):
        fa, fb, ta, tb = [], [], [], []
        for part in geom.flat_parts:
            a, b, _m = V._segments_from_polyline(
                part.samples3d(V.FLAT_LINE_STEP_MM, V.FLAT_ARC_STEP_MM))
            if len(a):
                fa.append(a)
                fb.append(b)
        for part in geom.transitions:
            a, b, _m = V._segments_from_polyline(
                part.samples3d(V.TRANSITION_STEP_MM))
            if len(a):
                ta.append(a)
                tb.append(b)
        return self._cat(fa), self._cat(fb), self._cat(ta), self._cat(tb)

    def _check(self, query_a, query_b, tree, other, other_route, skip, acc):
        if tree is None or not len(query_a):
            return
        other_a, other_b = other
        mids = 0.5 * (query_a + query_b)
        for qi, oi in V._iter_candidate_pairs(tree, mids, V.QUERY_RADIUS_MM):
            keep = ~np.isin(other_route[oi], skip)
            if not np.any(keep):
                continue
            qi = qi[keep]
            oi = oi[keep]
            dist, _pa, _pb, _s, _t = V._segment_segment_closest(
                query_a[qi], query_b[qi], other_a[oi], other_b[oi])
            acc['minimum'] = min(acc['minimum'], float(np.min(dist)))
            acc['bad'] += int(np.sum(dist < self.limit))

    def clearance(self, record, skip_rids=()):
        geom = self._parse(record)
        fa, fb, ta, tb = self.segments(geom)
        skip = np.asarray(sorted(int(r) for r in skip_rids
                                 if int(r) in self.geoms), dtype=np.int64)
        acc = dict(bad=0, minimum=float('inf'))
        self._check(ta, tb, self.flat_tree, self._flat, self.flat_route,
                    skip, acc)
        self._check(ta, tb, self.trans_tree, self._trans, self.trans_route,
                    skip, acc)
        self._check(fa, fb, self.trans_tree, self._trans, self.trans_route,
                    skip, acc)
        return acc['bad'], acc['minimum']

    def legal(self, route, skip_rids, world=None):
        if world is not None and not planes_ok(world, route):
            return False
        bad, _minimum = self.clearance(route, skip_rids)
        return bad == 0


def planes_ok(world, route):
    rid = int(route['route_id'])
    for part in route.get('parts') or []:
        if part['kind'] != 'flat':
            continue
        evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
        if evaluation is None or getattr(evaluation, 'valid', True):
            continue
        for blocker in getattr(evaluation, 'blockers', []) or []:
            if int(blocker) // 1000 != rid:
                return False
    return True


def frozen_validate(records):
    report = F.validate(records)
    return report, dict(report.get('counts') or {})


def violation_rids(report, ctx):
    out = set()
    for item in report.get('violations') or []:
        for field in ('route_id', 'other_route', 'route_a', 'route_b'):
            value = item.get(field)
            if isinstance(value, str) and ':' in value:
                value = value.split(':')[0]
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(value, int) and value in ctx.manifest:
                out.add(int(value))
    return out


def chunked_apply(records, order, builder, oracle, label, chunk=CHUNK):
    stats = dict(candidates=0, applied=0, chunks=0, chunk_fail=0,
                 validations=0)
    world = F.make_world(records)
    oracle.build(records)
    geoms_all = F.geoms_of(records)
    pending = []
    for index, rid in enumerate(order):
        route = builder(rid, records, world, oracle, geoms_all)
        if route is not None:
            pending.append((rid, route))
            stats['candidates'] += 1
        if len(pending) >= chunk or index == len(order) - 1:
            if pending:
                trial = dict(records)
                trial.update({rid: route for rid, route in pending})
                report, counts = frozen_validate(trial)
                stats['validations'] += 1
                stats['chunks'] += 1
                if int(counts.get('violations') or 0) == 0:
                    records = trial
                    stats['applied'] += len(pending)
                    world = F.make_world(records)
                    oracle.build(records)
                    geoms_all = F.geoms_of(records)
                else:
                    stats['chunk_fail'] += 1
            pending = []
    log(f'  [{label}] candidates={stats["candidates"]} applied='
        f'{stats["applied"]} chunks={stats["chunks"]} '
        f'failed_chunks={stats["chunk_fail"]} '
        f'validations={stats["validations"]}')
    return records, stats


def z1_candidate_builder(ctx, target_of, preferred_layers, engine):
    def builder(rid, records, world, oracle, geoms_all=None):
        current = records[rid]
        cur_layer = C.Ctx.route_target_layer(current)
        target = target_of.get(rid, cur_layer)
        layers = [target] + [lay for lay in preferred_layers if lay != target]
        carried = C.Ctx.stubs(current) if cur_layer > 1 else None
        for layer in layers:
            if layer <= 1:
                continue
            windows = []
            if carried is not None:
                windows.append(carried)
            windows.extend(F.windows(ctx, rid, layer, count=6))
            seen = set()
            for a_in, a_out in windows:
                key = (round(a_in, 4), round(a_out, 4))
                if key in seen:
                    continue
                seen.add(key)
                route = ctx.lift(rid, layer, a_in, a_out)
                if route is None:
                    continue
                if not oracle.legal(route, {rid}, world):
                    continue
                return route
        return None
    return builder


def z1_window_builder(ctx, engine):
    def builder(rid, records, world, oracle, geoms_all=None):
        current = records[rid]
        layer = C.Ctx.route_target_layer(current)
        if layer <= 1:
            return None
        carried = C.Ctx.stubs(current)
        geoms = geoms_all if geoms_all is not None else F.geoms_of(records)
        best = None
        for a_in, a_out in F.windows(ctx, rid, layer, count=6):
            if abs(a_in - carried[0]) < 1e-3 and abs(a_out - carried[1]) < 1e-3:
                continue
            route = ctx.lift(rid, layer, a_in, a_out)
            if route is None:
                continue
            if not oracle.legal(route, {rid}, world):
                continue
            delta = F.unit_delta(engine, geoms, [rid],
                                 {rid: E.route_geom(route)})
            if delta < 0 and (best is None or delta < best[0]):
                best = (delta, route)
        return best[1] if best else None
    return builder


def z2_orbit_pass(ctx, records, oracle, engine, label, windows_only=False,
                  chunk=6, layer_priority=(4, 5, 6, 7)):
    orbits = F.z2_orbits(ctx)
    world = F.make_world(records)
    oracle.build(records)
    geoms_all = F.geoms_of(records)
    stats = dict(candidates=0, applied=0, chunks=0, chunk_fail=0,
                 validations=0)
    pending = 0
    changes = {}
    for index, orbit in enumerate(orbits):
        rids = [int(r) for r in orbit['ids']]
        skip = set(rids)
        cur_layer = C.Ctx.route_target_layer(records[rids[0]])
        layers = ([cur_layer] if windows_only
                  else [lay for lay in layer_priority if lay != cur_layer])
        geoms = geoms_all
        best = None
        for layer in layers:
            if layer <= 1:
                continue
            grid = O.window_grid(ctx, orbit, layer, symmetric_only=False)
            if not grid:
                continue
            picks = list(grid[:2]) + [
                grid[min(len(grid) - 1, int(f * (len(grid) - 1)))]
                for f in (0.25, 0.5, 0.75)]
            seen = set()
            for a_in, a_out in picks[:4]:
                key = (round(a_in, 4), round(a_out, 4))
                if key in seen:
                    continue
                seen.add(key)
                routes = O.build_orbit(ctx, orbit, layer, a_in, a_out)
                if routes is None:
                    continue
                if any(not oracle.legal(route, skip, world)
                       for route in routes):
                    continue
                new_geoms = E.orbit_geom(ctx, orbit, layer, a_in, a_out)
                if new_geoms is None:
                    continue
                delta = engine.orbit_delta(geoms, orbit, new_geoms)
                if best is None or delta < best[0]:
                    best = (delta, routes)
                if delta < 0:
                    break
            if best is not None and best[0] < 0:
                break
        stats['candidates'] += 1
        if best is None:
            continue
        delta, routes = best
        if not windows_only and delta >= 0:
            continue
        for route in routes:
            changes[int(route['route_id'])] = route
        pending += 1
        if pending >= chunk or index == len(orbits) - 1:
            if changes:
                trial = dict(records)
                trial.update(changes)
                report, counts = frozen_validate(trial)
                stats['validations'] += 1
                stats['chunks'] += 1
                if int(counts.get('violations') or 0) == 0:
                    records = trial
                    stats['applied'] += pending
                    world = F.make_world(records)
                    oracle.build(records)
                    geoms_all = F.geoms_of(records)
                else:
                    stats['chunk_fail'] += 1
            pending = 0
            changes = {}
    log(f'  [{label}] orbit candidates={stats["candidates"]} applied='
        f'{stats["applied"]} chunks={stats["chunks"]} failed='
        f'{stats["chunk_fail"]} validations={stats["validations"]}')
    return records, stats


def main():
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = C.load_ctx()
    engine = F.engine(ctx)
    oracle = FrozenOracle()
    target_of = {}
    for rid in ctx.z1_opposite:
        target_of[rid] = 2 if ctx.cat[rid] == 'opposite_z1_NS' else 3
    for gid in F.z1_u_groups(ctx):
        for rid in ctx.groups[gid]['route_ids']:
            target_of[int(rid)] = 3
    baseline = F.load_baseline(ctx)
    baseline_list = [baseline[rid] for rid in sorted(baseline)]
    report, counts = frozen_validate(baseline)
    log(f'[stage1] E1 unique=3594 violations={counts.get("violations")} '
        f'z2c4={F.z2_c4_validation(ctx, baseline).get("symmetry_pass")}')
    C.write_json(OUT / 'baseline_E1' / 'baseline_check.json',
                 dict(e1_unique=3594, counts=counts))
    C.ensure_dir(OUT / 'baseline_E1' / 'figures')

    log('[stage2] incremental Z1 target assignment (NS->L2, EW->L3)')
    order = [rid for rid in sorted(target_of)
             if C.Ctx.route_target_layer(baseline[rid]) != target_of[rid]]
    order.sort(key=lambda rid: (ctx.cat[rid], rid))
    builder = z1_candidate_builder(ctx, target_of, [2, 3, 4, 5, 6, 7], engine)
    records = dict(baseline)
    records, stats2 = chunked_apply(records, order, builder, oracle, 'z1-target')
    report, counts = frozen_validate(records)
    log(f'[stage2] after: unique='
        f'{C.audit(list(records.values()), ctx)["n_unique_pairs"]} '
        f'violations={counts.get("violations")}')
    layers_now = {cat: dict(Counter(C.Ctx.route_target_layer(records[rid])
                                    for rid in ctx.manifest
                                    if ctx.cat[rid] == cat))
                  for cat in sorted(set(ctx.cat.values()))}
    C.write_json(OUT / 'incremental_Z1' / 'stage2.json',
                 dict(stats=stats2, counts=counts, layers=layers_now))

    log('[stage3] repair residual violations by re-windowing')
    best_records = records
    best_counts = counts
    for round_index in range(8):
        report, counts = frozen_validate(records)
        violation_count = int(counts.get('violations') or 0)
        log(f'[stage3] round {round_index}: violations={violation_count}')
        if violation_count == 0:
            best_records, best_counts = records, counts
            break
        bad = violation_rids(report, ctx)
        z2_rids = {int(rid) for orbit in F.z2_orbits(ctx)
                   for rid in orbit['ids']}
        z1_bad = [rid for rid in sorted(bad) if rid not in z2_rids]
        oracle.build(records)
        world = F.make_world(records)
        window_builder = z1_window_builder(ctx, engine)
        target_builder = z1_candidate_builder(
            ctx, target_of, [2, 3, 4, 5, 6, 7], engine)
        changes = {}
        for rid in z1_bad:
            if C.Ctx.route_target_layer(records[rid]) <= 1:
                continue
            route = window_builder(rid, records, world, oracle)
            if route is None:
                route = target_builder(rid, records, world, oracle)
            if route is not None:
                changes[rid] = route
        if not changes:
            log('[stage3] no re-window candidate left')
            break
        trial = dict(records)
        trial.update(changes)
        report2, counts2 = frozen_validate(trial)
        count2 = int(counts2.get('violations') or 0)
        if count2 < violation_count:
            records = trial
            if count2 == 0:
                best_records, best_counts = records, counts2
        else:
            rids = sorted(changes)
            half = {rid: changes[rid] for rid in rids[:max(1, len(rids) // 2)]}
            trial = dict(records)
            trial.update(half)
            report3, counts3 = frozen_validate(trial)
            count3 = int(counts3.get('violations') or 0)
            if count3 < violation_count:
                records = trial
                if count3 == 0:
                    best_records, best_counts = records, counts3
            else:
                break
    report, counts = frozen_validate(records)
    analysis = C.audit(list(records.values()), ctx)
    log(f'[stage3] unique={analysis["n_unique_pairs"]} violations='
        f'{counts.get("violations")}')
    if int(counts.get('violations') or 0) == 0:
        best_records, best_counts = records, counts

    log('[stage4] Z2 strict C4 optimisation (L4-L7 priority)')
    records, stats4 = z2_orbit_pass(ctx, records, oracle, engine, 'z2-c4')
    report, counts = frozen_validate(records)
    analysis = C.audit(list(records.values()), ctx)
    log(f'[stage4] unique={analysis["n_unique_pairs"]} violations='
        f'{counts.get("violations")}')
    if int(counts.get('violations') or 0) == 0:
        best_records, best_counts = records, counts

    log('[stage5] Z1 window refinement')
    analysis = C.audit(list(records.values()), ctx)
    contribution = analysis['per_route']
    order = [rid for rid in sorted(records,
                                   key=lambda rid: -contribution.get(rid, 0))
             if not ctx.cat[rid].startswith(('adjacent_z2', 'same_u_z2',
                                             'opposite_z2'))
             and C.Ctx.route_target_layer(records[rid]) > 1][:120]
    builder = z1_window_builder(ctx, engine)
    records, stats5 = chunked_apply(records, order, builder, oracle,
                                    'z1-window')
    report, counts = frozen_validate(records)
    analysis = C.audit(list(records.values()), ctx)
    log(f'[stage5] unique={analysis["n_unique_pairs"]} violations='
        f'{counts.get("violations")}')
    if int(counts.get('violations') or 0) == 0:
        best_records, best_counts = records, counts
    log(f'[f2] total {time.perf_counter()-started:.0f}s')

    final_report, final_counts = frozen_validate(best_records)
    final_analysis = C.audit(list(best_records.values()), ctx)
    log(f'[f2] best_legal unique={final_analysis["n_unique_pairs"]} '
        f'violations={final_counts.get("violations")}')
    z2_c4 = F.z2_c4_validation(ctx, best_records)
    SF.save_scheme(ctx, 'F2_reworked_best_legal',
                   OUT / 'F2_best_legal', best_records,
                   plan=target_of, baseline_records=baseline_list,
                   extra=dict(stage='incremental legal F2 from E1: NS->L2, '
                                    'EW->L3, Z2 strict C4 L4-L7',
                              stats=dict(stage2=stats2, stage4=stats4,
                                         stage5=stats5),
                              log=LOG[-200:]),
                   log=log)
    C.write_json(OUT / 'comparison_candidate.json',
                 dict(unique=final_analysis['n_unique_pairs'],
                      z1=final_analysis['z1_pairs'],
                      z2=final_analysis['z2_pairs'],
                      high=final_analysis['high_pairs'],
                      counts=final_counts, z2_c4=z2_c4))
    log('[f2] saved F2_best_legal')


if __name__ == '__main__':
    main()
