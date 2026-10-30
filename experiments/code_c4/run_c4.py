# -*- coding: utf-8 -*-
"""C4-SYMMETRIC experiment driver.

Runs the strict-C4 orbit-level optimisation for 7 / 9 / 11 / 13 layers, saves
every complete scheme with routes_1024.json / summary.json / validation.json /
c4_validation.json / per_route.csv / per_layer.csv / search_log.json / figures,
and produces comparison.csv / comparison.json / comparison.png.

Usage (project root):
    python -m four_side_1024.c4.run_c4                 # full experiment
    python -m four_side_1024.c4.run_c4 --quick         # small smoke run
    python -m four_side_1024.c4.run_c4 --layers 7      # only one layer count
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.c4 import layers as LY
from four_side_1024.c4 import orbits as O
from four_side_1024.c4 import engine as E
from four_side_1024.c4 import optimize as OPT

OUT = C.Z.CAMPAIGN / 'c4_symmetric_multilayer'
WORK = OUT / '_work'
LOG_LINES = []


def log(*args):
    text = ' '.join(str(a) for a in args)
    LOG_LINES.append(text)
    print(text, flush=True)


# ---------------------------------------------------------------------------
# frozen-validator driven repair: revert orbits involved in violations to flat
# ---------------------------------------------------------------------------
def _violation_route_ids(report):
    ids = set()
    for item in report.get('violations') or []:
        for field in ('route_id', 'other_route', 'route_a', 'route_b',
                      'other'):
            value = item.get(field)
            if isinstance(value, int):
                ids.add(int(value))
            elif isinstance(value, str) and value.split(':')[0].isdigit():
                ids.add(int(value.split(':')[0]))
        for key in ('blockers', 'routes'):
            for value in item.get(key) or []:
                if isinstance(value, int):
                    ids.add(int(value) // 1000 if value > 10000 else int(value))
                elif isinstance(value, str) and value.split(':')[0].isdigit():
                    ids.add(int(value.split(':')[0]))
    return ids


def repair_frozen(ctx, records, params, orbits, max_layer, log=log,
                  max_rounds=12):
    """Validate with the frozen validator and revert offending orbits to flat."""
    orbit_by_rid = O.orbit_of_route(orbits)
    reverted_all = []
    report = None
    for round_index in range(max_rounds):
        payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                       experiment='repair',
                       layer_stack=LY.stack_payload(max_layer),
                       routes=records)
        report = LY.validate_payload(payload, max_layer, log=lambda *a: None)
        counts = dict(report.get('counts') or {})
        violations = int(counts.get('violations') or 0)
        log(f'  [repair] round {round_index}: violations={violations} '
            f'(clearance={counts.get("clearance_violations")}, '
            f'same_plane={counts.get("same_plane_violations")})')
        if violations == 0:
            return records, params, report, reverted_all
        bad_rids = _violation_route_ids(report)
        gids = sorted({orbit_by_rid[rid]['group_id'] for rid in bad_rids
                       if rid in orbit_by_rid})
        revert = [gid for gid in gids if params.get(gid) is not None]
        if not revert:
            log('  [repair] violations not attributable to lifted orbits')
            break
        log(f'  [repair] reverting {len(revert)} orbits: {revert[:12]}')
        for gid in revert:
            params.pop(gid, None)
        reverted_all.extend(revert)
        records = O.assemble(ctx, params, orbits)
    return records, params, report, reverted_all


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def save_scheme(ctx, name, folder, records, max_layer, extra=None,
                save_figures=True, log=log):
    folder = Path(folder)
    (folder / 'figures').mkdir(parents=True, exist_ok=True)
    payload = dict(schema='four_side_1024_v2_l3d_routes_v1', experiment=name,
                   layer_stack=LY.stack_payload(max_layer), routes=records)
    started = time.perf_counter()
    report = LY.validate_payload(payload, max_layer, log=lambda *a: None)
    log(f'[{name}] frozen validation {time.perf_counter()-started:.1f}s '
        f'status={report.get("status")} counts={dict(report.get("counts") or {})}')
    stats = OPT.summarise(ctx, records, name)
    stats.update(dict(max_layer=int(max_layer),
                      layer_stack_max=LY.HEIGHTS[max_layer],
                      validation_status=report.get('status'),
                      validation_counts=dict(report.get('counts') or {}),
                      n_violations=len(report.get('violations') or []),
                      provenance='unconfirmed_simulation'))
    if extra:
        stats.update(extra)
    C.write_json(folder / 'routes_1024.json', payload, indent=None)
    C.write_json(folder / 'validation.json', report)
    C.write_json(folder / 'search_log.json',
                 dict(experiment=name, log=LOG_LINES[-600:],
                      extra=extra or {}))
    analysis = C.audit(records, ctx)
    orbit_by_rid = O.orbit_of_route(O.load_orbits(ctx))
    rows = []
    for record in records:
        rid = int(record['route_id'])
        head = float(record['parts'][0]['length_mm'])
        tail = float(record['parts'][-1]['length_mm'])
        orbit = orbit_by_rid.get(rid)
        rows.append(dict(route_id=rid, plane=record.get('plane'),
                         relation=ctx.manifest[rid]['relation'],
                         orbit_id=orbit['group_id'] if orbit else '',
                         source_endpoint=record.get('source_endpoint'),
                         target_endpoint=record.get('target_endpoint'),
                         target_layer=C.Ctx.route_target_layer(record),
                         max_z_mm=round(C.Ctx.route_max_z(record), 6),
                         n_transitions=int(record.get('n_transitions') or 0),
                         base_stub_in_mm=round(head, 6),
                         base_stub_out_mm=round(tail, 6),
                         length_mm=round(float(record.get('length_mm') or 0), 6),
                         crossing_pairs=int(analysis['per_route'].get(rid, 0))))
    C.write_csv(folder / 'per_route.csv', rows)
    layer_rows = []
    for z, info in sorted(analysis['per_height'].items()):
        layer_rows.append(dict(z_mm=z, routes=info['routes'],
                               segments=info['segments'],
                               unique_crossing_pairs=info['pairs'],
                               crossing_events=info['events']))
    C.write_csv(folder / 'per_layer.csv', layer_rows)
    c4_report = None
    try:
        from four_side_1024.c4 import validate as V4
        c4_report = V4.validate_layout(payload, max_layer=max_layer)
        C.write_json(folder / 'c4_validation.json', c4_report)
        log(f'[{name}] c4 symmetry_pass={c4_report.get("symmetry_pass")} '
            f'max_dev={c4_report.get("maximum_xyz_deviation_mm")}')
    except Exception as exc:
        log(f'[{name}] c4 validator unavailable: {exc!r}')
    stats['c4_symmetry'] = dict(
        pass_=None if c4_report is None else c4_report.get('symmetry_pass'),
        max_xyz_deviation_mm=None if c4_report is None else
        c4_report.get('maximum_xyz_deviation_mm'))
    C.write_json(folder / 'summary.json', stats)
    if save_figures:
        try:
            from four_side_1024.c4 import plots as P4
            P4.geometry_figures(folder, records, ctx, name=name,
                                c4_report=c4_report)
            log(f'[{name}] figures done')
        except Exception as exc:
            log(f'[{name}] figures unavailable: {exc!r}')
    return stats, report, c4_report


# ---------------------------------------------------------------------------
# main experiment
# ---------------------------------------------------------------------------
def corridor_blocker_orbits(ctx):
    """Z2 orbits owning a long straight arm collinear with a Z1 line.

    These arms sit at z = 0.5 across the Z1 ports and block every Z1 S-bend
    window along that line, so they must be cleared first (utility move).
    """
    gids = set()
    for orbit in O.load_orbits(ctx):
        if orbit['plane'] != 'z2':
            continue
        longest = 0.0
        for prim in ctx.chain(orbit['rep']):
            if prim['kind'] == 'line':
                longest = max(longest, C.prim_len(prim))
        if longest >= 28.0:
            gids.add(orbit['group_id'])
    return gids


def run(layer_counts=(7, 9, 11, 13), quick=False, only=None, save=True):
    started = time.perf_counter()
    ctx = C.load_ctx()
    orbits = O.load_orbits(ctx)
    engine = E.C4Engine(ctx, cache_dir=WORK, log=log)
    log(f'orbits={len(orbits)} kinds={O.classify(ctx, orbits)}')

    flat = O.flat_records(ctx, orbits)
    flat_analysis = C.audit(flat, ctx)
    log(f'[C4-BASE flat] unique={flat_analysis["n_unique_pairs"]} '
        f'z1={flat_analysis["z1_pairs"]} z2={flat_analysis["z2_pairs"]}')
    rows = []
    if save:
        stats, report, c4r = save_scheme(
            ctx, 'C4-BASE', OUT / 'baseline', flat, 7,
            extra=dict(note='strict C4 interface-only baseline (ablation A: '
                            'symmetry only, no 3D lifting optimisation)'))
        rows.append(dict(experiment='C4-BASE', layers=7,
                         unique_crossing_pairs=stats['unique_crossing_pairs'],
                         z1_crossing_pairs=stats['z1_crossing_pairs'],
                         z2_crossing_pairs=stats['z2_crossing_pairs'],
                         high_layer_crossing_pairs=stats['high_layer_crossing_pairs'],
                         transitions=stats['transitions'],
                         total_length_mm=stats['total_length_mm'],
                         fabrication_hours=stats['fabrication_hours'],
                         max_z_mm=stats['max_z_mm'],
                         c4_symmetry_pass=None if c4r is None else
                         c4r.get('symmetry_pass'),
                         violations=stats['n_violations'],
                         note='symmetry only, all routes flat'))
    else:
        rows.append(dict(experiment='C4-BASE', layers=7,
                         unique_crossing_pairs=flat_analysis['n_unique_pairs']))

    params = {}
    ablation = []
    for layer_total in sorted(layer_counts):
        max_layer = int(layer_total)
        log(f'===== C4-{layer_total}L (layers L2..L{max_layer}) =====')
        if quick:
            plan = [dict(mode='layer', order='priority'),
                    dict(mode='window', order='configuration')]
            plan = [dict(mode='layer', order='priority')]
        elif layer_total == min(layer_counts):
            plan = [dict(mode='layer', order='priority'),
                    dict(mode='mixed', order='contribution')]
        else:
            plan = [dict(mode='layer', order='priority'),
                    dict(mode='mixed', order='contribution')]
        focus = orbits[:40] if quick else orbits
        utility = corridor_blocker_orbits(ctx)
        log(f'[C4-{layer_total}L] corridor-blocking Z2 orbits: {len(utility)}')
        best_current = None
        first = dict(mode='layer', order='priority', utility_gids=utility)
        if quick:
            trials = [first]
        elif layer_total == min(layer_counts):
            trials = [first, dict(mode='mixed', order='contribution')]
        else:
            trials = [first]
        for step in trials:
            trial_params = {}
            result = OPT.run_pass(
                ctx, focus, trial_params, max_layer, engine, log=log, **step)
            records, trial_params, repair_report, reverted = repair_frozen(
                ctx, result['records'], trial_params, orbits, max_layer)
            analysis = C.audit(records, ctx)
            trial = dict(records=records, params=trial_params,
                         unique=analysis['n_unique_pairs'],
                         per_height={z: info['pairs'] for z, info in
                                     sorted(analysis['per_height'].items())},
                         step=step, reverted=reverted)
            ablation.append(dict(layer_total=layer_total, mode=step['mode'],
                                 order=step['order'],
                                 unique=trial['unique'],
                                 accepted=result['accepted'],
                                 kept=result['kept'],
                                 reverted_orbits=len(reverted),
                                 seconds=result['seconds']))
            log(f'[C4-{layer_total}L after {step["mode"]}/{step["order"]}] '
                f'unique={trial["unique"]} reverted={len(reverted)}')
            if best_current is None or trial['unique'] < best_current['unique']:
                best_current = trial
            WORK.mkdir(parents=True, exist_ok=True)
            C.write_json(WORK / f'checkpoint_{layer_total}L.json',
                         dict(params={str(k): list(v) for k, v in
                                      trial_params.items()},
                              step=step, unique=trial['unique']))
        current = best_current
        params = current['params']
        # frozen-validator repair: revert offending orbits until violations = 0
        records, params, repair_report, reverted = repair_frozen(
            ctx, current['records'], params, orbits, max_layer)
        analysis = C.audit(records, ctx)
        current['records'] = records
        current['unique'] = analysis['n_unique_pairs']
        current['per_height'] = {z: info['pairs'] for z, info in
                                 sorted(analysis['per_height'].items())}
        if save:
            folder = OUT / f'optimized_{layer_total}L'
            stats, report, c4r = save_scheme(
                ctx, f'C4-{layer_total}L', folder, current['records'], max_layer,
                extra=dict(params={str(k): list(v) for k, v in params.items()},
                           ablation=ablation,
                           repair_reverted_orbit_ids=reverted,
                           note='strict C4 orbit-level joint optimisation'))
            rows.append(dict(experiment=f'C4-{layer_total}L',
                             layers=layer_total,
                             unique_crossing_pairs=stats['unique_crossing_pairs'],
                             z1_crossing_pairs=stats['z1_crossing_pairs'],
                             z2_crossing_pairs=stats['z2_crossing_pairs'],
                             high_layer_crossing_pairs=stats['high_layer_crossing_pairs'],
                             transitions=stats['transitions'],
                             total_length_mm=stats['total_length_mm'],
                             fabrication_hours=stats['fabrication_hours'],
                             max_z_mm=stats['max_z_mm'],
                             c4_symmetry_pass=None if c4r is None else
                             c4r.get('symmetry_pass'),
                             violations=stats['n_violations']))
        else:
            rows.append(dict(experiment=f'C4-{layer_total}L',
                             layers=layer_total,
                             unique_crossing_pairs=current['unique']))
    if save:
        C.write_csv(OUT / 'comparison.csv', rows)
        C.write_json(OUT / 'comparison.json',
                     dict(rows=rows, ablation=ablation,
                          runtime_seconds=round(time.perf_counter() - started, 1)))
        valid = [row for row in rows
                 if row.get('experiment', '').startswith('C4-')
                 and row.get('violations') == 0
                 and row.get('layers', 7) != 7 or False]
        valid = [row for row in rows
                 if row.get('experiment', '').startswith('C4-')
                 and row.get('violations') == 0
                 and row.get('c4_symmetry_pass') in (True, None)]
        if valid:
            best = min(valid, key=lambda row: row['unique_crossing_pairs'])
            src = OUT / f"optimized_{best['layers']}L"
            dst = OUT / 'best_solution'
            dst.mkdir(parents=True, exist_ok=True)
            import shutil
            for name in ('routes_1024.json', 'summary.json', 'validation.json',
                         'c4_validation.json', 'per_route.csv', 'per_layer.csv',
                         'search_log.json'):
                source = src / name
                if source.exists():
                    shutil.copy2(source, dst / name)
            if (src / 'figures').exists():
                target = dst / 'figures'
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(src / 'figures', target)
            C.write_json(dst / 'BEST_SOURCE.json', dict(
                source_experiment=best['experiment'],
                layer_total=best['layers'],
                unique_crossing_pairs=best['unique_crossing_pairs'],
                summary=best))
            log(f'[best] {best["experiment"]} unique='
                f'{best["unique_crossing_pairs"]}')
        try:
            from four_side_1024.c4 import plots as P4
            P4.summary_figures(OUT, rows, e1_row=dict(
                experiment='E1-BASE', layers=7, unique_crossing_pairs=3594))
            log('[summary] figures done')
        except Exception as exc:
            log(f'[summary] figures unavailable: {exc!r}')
    log(f'[c4] total {time.perf_counter()-started:.0f}s')
    return rows


def main(argv):
    quick = '--quick' in argv
    only = None
    if '--layers' in argv:
        index = argv.index('--layers')
        only = [int(value) for value in argv[index + 1].split(',')]
    rows = run(layer_counts=only or (7, 9, 11, 13), quick=quick)
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv)
