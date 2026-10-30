# -*- coding: utf-8 -*-
"""Iterative repair of C3: revert validator-violating routes to BASE geometry."""
import sys, json
from collections import Counter
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C

C3 = C.E1 / 'E1_C3_z2_bundle'


def validate(records):
    return C.Z.validate_payload(
        dict(schema='four_side_1024_v2_l3d_routes_v1',
             experiment='E1_C3_z2_bundle',
             layer_stack=C.Z.stack_payload(7), routes=records),
        max_layer=7, log=lambda *a: None)


def main():
    ctx = C.load_ctx()
    payload = C.read_json(C3 / 'routes_1024.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    summary = C.read_json(C3 / 'summary.json')
    cleared = set(summary.get('c3_phase1_cleared_z2_ids') or [])
    reverted = set()
    for iteration in range(12):
        report = validate(records)
        counts = dict(report.get('counts') or {})
        violations = report.get('violations') or []
        print(f'iter {iteration}: violations={counts.get("violations")} '
              f'clearance={counts.get("clearance_violations")}', flush=True)
        if counts.get('violations', 1) == 0:
            break
        bad = set()
        for item in violations:
            for field in ('route_id', 'other_route'):
                value = item.get(field)
                if isinstance(value, int):
                    bad.add(int(value))
                elif isinstance(value, str) and ':' in value:
                    bad.add(int(value.split(':')[0]))
        bad -= reverted
        if not bad:
            print('no new routes to revert')
            break
        print('  reverting', sorted(bad), 'from', [ctx.cat.get(rid) for rid in sorted(bad)])
        records = [ctx.by_id[int(r['route_id'])]
                   if int(r['route_id']) in bad else r for r in records]
        reverted |= bad
    analysis = C.audit(records, ctx)
    print('final audit unique=', analysis['n_unique_pairs'],
          'z1=', analysis['z1_pairs'], 'z2=', analysis['z2_pairs'],
          'high=', analysis['high_pairs'], 'adj=', analysis['adjacent_related_events'])
    report = validate(records)
    counts = dict(report.get('counts') or {})
    print('final validation', report.get('status'), counts)
    if counts.get('violations', 1) == 0:
        C.save_experiment(
            'E1_C3_z2_bundle', records, ctx, folder=C3,
            extra=dict(c3_repaired_routes=sorted(reverted),
                       c3_repair_note=('routes whose post-refine geometry failed '
                                       'the frozen validator clearance check were '
                                       'reverted to their BASE geometry; the rest '
                                       'of the C3 layout is unchanged'),
                       c3_iterations=iteration + 1),
            note=summary.get('note'))
        from four_side_1024.e1 import plots as P
        P.standard_figures(C3, records, ctx, 'E1_C3_z2_bundle',
                           baseline_records=ctx.records_base)
        out = C.read_json(C3 / 'summary.json')
        print('SAVED C3 unique=', out['unique_crossing_pairs'],
              'z1=', out['z1_crossing_pairs'], 'z2=', out['z2_crossing_pairs'],
              'high=', out['high_layer_crossing_pairs'],
              'adj=', out['adjacent_related_events'],
              'hours=', out['fabrication_hours'],
              'viol=', (out['validation_counts'] or {}).get('violations'))
    else:
        print('STILL INVALID')


if __name__ == '__main__':
    main()
