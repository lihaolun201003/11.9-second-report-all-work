# -*- coding: utf-8 -*-
"""Experiment driver: Z1-specialised multilayer routing on the 150 um stack.

A : 5-layer baseline (rebuilt Hybrid-H style on L1-L5, Z1 lifts kept historical)
B : 5-layer Z1 optimisation
C : 7-layer Z1 optimisation
D : 9-layer Z1 optimisation
E : 11-layer Z1 optimisation

All geometry is rebuilt as real XYZ.  Outputs go to
``outputs/manual_c4_new_connectivity/z1_multilayer_150um/<experiment>/``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from four_side_1024.manual_c4 import structured_layer_routing as S
from four_side_1024.manual_c4.spatial_u_bundle import group_separation

OUT = Z.OUT_ROOT
FEAS = Z.CAMPAIGN / 'hybrid_c2_c4_directional/_work/H_feasibility.json'
BUNDLE = set(range(160, 176))


def load_entries():
    base = Z.read_json(Z.CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json')
    payload, failed = Z.rez_payload(base, max_layer=11, log=lambda *a: None)
    data, z1 = Z.z1_opposite_sets()
    conn = Z.read_json(Z.CAMPAIGN / 'inputs/connectivity_1024.json')
    groups = {int(g['group_id']): [int(r) for r in g['route_ids']]
              for g in conn['groups']}
    feasible = Z.read_json(FEAS)
    return data, z1, payload, groups, feasible


def rebuilt_u_bundle(data, payload, groups, z1):
    """Rebuild the old L4 corner-U bundle at the compressed L4=0.95 mm."""
    from four_side_1024.v3c4.lift_cross import transition_geometry
    b_rids = {rid for gid in BUNDLE for rid in groups[gid]}
    fixed = [r for r in Z.fixed_routes_from_hybrid(payload, z1)
             if int(r['route_id']) not in b_rids]
    world = Z.make_world(fixed, 11)
    campaign = data.campaign
    previous_d = None
    rebuilt = []
    for gid in sorted(BUNDLE, key=lambda g: group_separation(campaign, g)):
        fp = float(transition_geometry(0.95 - campaign.base_z(groups[gid][0]))
                   ['footprint_mm'])
        chosen = None
        d = (previous_d + 0.5) if previous_d is not None else 10.0
        while d < 60.0 and chosen is None:
            a = 1.2
            while a <= min(12.0, d - fp) + 1e-9:
                routes = S.build_u_group(campaign, gid, 4, 0.95, d, a, a)
                if routes is not None and not any(world.check_route(r)
                                                  for r in routes):
                    chosen = (d, routes)
                    break
                a += 0.8
            if chosen is None:
                d += 0.5
        if chosen is None:
            raise RuntimeError(f'cannot rebuild U bundle group {gid}')
        previous_d = chosen[0]
        for route in chosen[1]:
            world.add_route(route)
            rebuilt.append(route)
    return fixed + rebuilt


def pair_distance(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def pair_cost(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def baseline_pair(data, pair, key, feasible):
    if key == 'ns':
        return Z.flat_pair(data.campaign, pair, 'ns')
    for a_in, a_out, _fall in feasible.get(str(pair['group_id']), []):
        routes = [Z.build_pair_route(data.campaign, rid, 2, Z.layer_z(2),
                                     a_in, a_out) for rid in pair['ew']]
        if all(route is not None for route in routes):
            return routes
    return Z.flat_pair(data.campaign, pair, 'ew')


def baseline_payload(data, fixed, feasible, max_layer):
    world = Z.make_world(fixed, max_layer)
    records = []
    for pair in data.pairs:
        for route in baseline_pair(data, pair, 'ns', feasible):
            world.add_route(route)
            records.append(route)
    for pair in data.pairs:
        chosen = None
        for a_in, a_out, _fall in feasible.get(str(pair['group_id']), []):
            routes = [Z.build_pair_route(data.campaign, rid, 2, Z.layer_z(2),
                                         a_in, a_out) for rid in pair['ew']]
            if any(route is None for route in routes):
                continue
            if any(world.check_route(route) for route in routes):
                continue
            chosen = routes
            break
        if chosen is None:
            chosen = Z.flat_pair(data.campaign, pair, 'ew')
        for route in chosen:
            world.add_route(route)
            records.append(route)
    return fixed + records


A_VALUES = [1.2, 4.0, 9.0, 16.0, 24.0]


def build_options(data, fixed, max_layer):
    fixed_world = Z.make_world(fixed, max_layer)
    opts = {}
    for pair in data.pairs:
        for key in ('ew', 'ns'):
            for layer in range(2, max_layer + 1):
                found = None
                for a in A_VALUES:
                    routes = Z.build_pair(data.campaign, pair, key, layer,
                                          Z.layer_z(layer), a)
                    if routes is None:
                        continue
                    if any(fixed_world.check_route(route) for route in routes):
                        continue
                    found = (a, routes)
                    break
                opts[(pair['group_id'], key, layer)] = found
    return opts


def early_records(data, fixed, opts, max_layer, ew_layer, ns_layer, base_by):
    """Start from baseline, replace pairs by early-rise options where available."""
    records = {}
    owner = {}
    for pair in data.pairs:
        for key in ('ew', 'ns'):
            for route in base_by[(pair['group_id'], key)]:
                records[int(route['route_id'])] = route
                owner[int(route['route_id'])] = (pair['group_id'], key)
    for pair in data.pairs:
        for key, preferred in (('ew', ew_layer), ('ns', ns_layer)):
            chosen = None
            for layer in [preferred] + [x for x in range(2, max_layer + 1)
                                        if x != preferred]:
                option = opts.get((pair['group_id'], key, layer))
                if option:
                    chosen = option[1]
                    break
            if chosen:
                for rid in [int(r) for r in pair[key]]:
                    records.pop(rid, None)
                for route in chosen:
                    records[int(route['route_id'])] = route
    return list(records.values()), owner


def _rid(value):
    text = str(value.get('route_id', ''))
    return int(text.split(':')[0]) if text else None


def validate_records(records, max_layer):
    payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                   layer_stack=Z.stack_payload(max_layer), routes=records)
    return Z.validate_payload(payload, max_layer=max_layer, log=lambda *a: None)


def repair_to_valid(data, fixed, base_by, records, owner, max_layer,
                    log=print):
    """Revert whole Z1 pairs that appear in validator violations."""
    reverted = set()
    for iteration in range(30):
        report = validate_records(fixed + records, max_layer)
        violations = report.get('violations') or []
        log(f'[repair {max_layer}L] iter {iteration}: violations={len(violations)}')
        if not violations:
            return records, report, reverted
        revert = set()
        for item in violations:
            for field in ('route_id', 'other_route'):
                rid = _rid({field: item.get(field, '')})
                if rid in owner:
                    revert.add(owner[rid])
        # also revert the paired direction of the same group
        for gid, _key in list(revert):
            revert.add((gid, 'ew'))
            revert.add((gid, 'ns'))
        if not revert:
            log('[repair] violations not attributable to Z1 pairs')
            return records, report, reverted
        new_reverts = revert - reverted
        if not new_reverts:
            log('[repair] no new pairs to revert')
            return records, report, reverted
        for gid, key in new_reverts:
            pair = next(p for p in data.pairs if p['group_id'] == gid)
            for rid in [int(r) for r in pair[key]]:
                records = [r for r in records if int(r['route_id']) != rid]
            for route in base_by[(gid, key)]:
                records.append(route)
        reverted |= new_reverts
    return records, validate_records(fixed + records, max_layer), reverted


def save_experiment(name, records, max_layer, extra=None, log=print):
    out = OUT / name
    (out / 'figures').mkdir(parents=True, exist_ok=True)
    report = validate_records(records, max_layer)
    metrics = Z.crossing_metrics(records, max_layer)
    metrics['validation_status'] = report.get('status')
    metrics['validation_counts'] = dict(report.get('counts') or {})
    metrics['validation_exploratory_pass'] = report.get('exploratory_pass')
    metrics['max_layer'] = int(max_layer)
    if extra:
        metrics.update(extra)
    Z.write_json(out / 'routes_1024.json',
                 dict(schema='four_side_1024_v2_l3d_routes_v1',
                      experiment=name,
                      layer_stack=Z.stack_payload(max_layer),
                      routes=records), indent=None)
    Z.write_json(out / 'summary.json', metrics)
    Z.write_json(out / 'validation.json', report)
    log(f'[{name}] routed={metrics["routed"]} unique={metrics["unique_crossing_pairs"]} '
        f'z1hv={metrics["z1_hv_same_height_pairs"]} '
        f'trans={metrics["transitions"]} len={metrics["total_length_mm"]} '
        f'valid={report.get("status")} counts={report.get("counts")}')
    return metrics, report


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    data, z1, payload, groups, feasible = load_entries()
    fixed = rebuilt_u_bundle(data, payload, groups, z1)
    assert not Z.check_fixed_world(fixed), 'fixed 150um world has conflicts'
    rows = []

    baseline = baseline_payload(data, fixed, feasible, max_layer=5)
    metrics, _ = save_experiment('baseline_5L', baseline, 5)
    rows.append(('5L 基线', metrics))
    base_by = {}
    for pair in data.pairs:
        for key in ('ew', 'ns'):
            ids = set(int(r) for r in pair[key])
            base_by[(pair['group_id'], key)] = [r for r in baseline
                                                if int(r['route_id']) in ids]

    for name, max_layer, candidates in (
            ('optimized_5L', 5, [(3, 4), (4, 5)]),
            ('optimized_7L', 7, [(6, 7), (5, 6)]),
            ('optimized_9L', 9, [(8, 9), (7, 8)]),
            ('optimized_11L', 11, [(10, 11), (9, 10)])):
        opts = build_options(data, fixed, max_layer)
        best = None
        for ew_layer, ns_layer in candidates:
            records, owner = early_records(data, fixed, opts, max_layer,
                                           ew_layer, ns_layer, base_by)
            records, report, reverted = repair_to_valid(
                data, fixed, base_by, records, owner, max_layer)
            metrics = Z.crossing_metrics(fixed + records, max_layer)
            key = (metrics['unique_crossing_pairs'],
                   metrics['transitions'], metrics['total_length_mm'])
            print(f'[{name}] EW{ew_layer}/NS{ns_layer}: '
                  f'cross={metrics["unique_crossing_pairs"]} '
                  f'z1hv={metrics["z1_hv_same_height_pairs"]} '
                  f'valid={report.get("status")} reverted={len(reverted)}')
            if report.get('counts', {}).get('violations', 1) == 0:
                if best is None or key < best[0]:
                    best = (key, records, (ew_layer, ns_layer), report,
                            len(reverted))
        if best is None:
            # fall back to the valid baseline geometry for this layer budget
            records = baseline
            best = ((Z.crossing_metrics(records, max_layer)['unique_crossing_pairs'],
                     0, 0), records, (None, None), None, 0)
        _, records, layers, report, reverted = best
        records = fixed + records
        metrics, report = save_experiment(
            name, records, max_layer,
            extra=dict(ew_layer=layers[0], ns_layer=layers[1],
                       reverted_pairs=reverted))
        rows.append((name, metrics))

    # comparison table
    comp = {}
    for label, metrics in rows:
        comp[label] = dict(
            unique_crossing_pairs=metrics['unique_crossing_pairs'],
            z1_hv=metrics['z1_hv_same_height_pairs'],
            transitions=metrics['transitions'],
            length_mm=metrics['total_length_mm'],
            fabrication_hours=round(metrics['total_length_mm'] / 3600.0, 4),
            max_layer=metrics['max_layer'],
            validation=metrics['validation_status'],
            counts=metrics['validation_counts'])
    Z.write_json(OUT / 'comparison.json', comp)
    print('comparison', json.dumps(comp, ensure_ascii=False, indent=1))
    print('total seconds', round(time.perf_counter() - started, 1))


if __name__ == '__main__':
    run()
