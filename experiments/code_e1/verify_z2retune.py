# -*- coding: utf-8 -*-
"""Lead independent verification of the D3 Z2-retune extension."""
import sys
from collections import Counter
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C

EXT = (C.E1 / 'E1_D_early_lift' / 'D3_e1c_best' / 'z2_retune_extension')


def main():
    ctx = C.load_ctx()
    payload = C.read_json(EXT / 'routes_1024.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    print('routed records:', len(records))
    ids = {int(r['route_id']) for r in records}
    print('route-id set == base:', ids == set(ctx.manifest),
          'missing:', len(set(ctx.manifest) - ids),
          'extra:', len(ids - set(ctx.manifest)))
    # connection identity preserved
    bad = 0
    for record in records:
        rid = int(record['route_id'])
        m = ctx.manifest[rid]
        for field in ('source_endpoint', 'target_endpoint', 'plane'):
            if str(record.get(field)) != str(m[field]):
                bad += 1
    print('endpoint/plane identity mismatches:', bad)

    analysis = C.audit(records, ctx)
    stats = C.bar(records)
    usage = C.layer_usage(records, ctx)
    print(f"unique={analysis['n_unique_pairs']} z1={analysis['z1_pairs']} "
          f"z2={analysis['z2_pairs']} high={analysis['high_pairs']} "
          f"adj={analysis['adjacent_related_events']} "
          f"line={analysis['adjacent_line_events']} "
          f"arc={analysis['adjacent_arc_events']} "
          f"hv={analysis['z1_hv_pairs']} "
          f"opp_opp={analysis['opposite_opposite_events']}")
    print('by height:', {z: info['pairs'] for z, info in
                         sorted(analysis['per_height'].items())})
    print(f"transitions={stats['transitions']} "
          f"length={stats['total_length_mm']} "
          f"hours={stats['fabrication_hours']} "
          f"L6={usage[6]['routes']} L7={usage[7]['routes']}")

    report = C.Z.validate_payload(
        dict(schema='four_side_1024_v2_l3d_routes_v1',
             experiment='D3_z2retune_extension',
             layer_stack=C.Z.stack_payload(7), routes=records),
        max_layer=7, log=lambda *a: None)
    print('validation:', report.get('status'),
          dict(report.get('counts') or {}))
    # compare with C3 for the changed routes
    c3 = C.read_json(C.E1 / 'E1_C3_z2_bundle' / 'routes_1024.json')
    c3_by = {int(r['route_id']): r for r in c3['routes']
             if r.get('status') == 'routed'}
    changed = []
    for record in records:
        rid = int(record['route_id'])
        a = C.Ctx.stubs(c3_by[rid])
        b = C.Ctx.stubs(record)
        la = C.Ctx.route_target_layer(c3_by[rid])
        lb = C.Ctx.route_target_layer(record)
        if (round(a[0], 2), round(a[1], 2), la) != (round(b[0], 2),
                                                    round(b[1], 2), lb):
            changed.append((rid, ctx.cat[rid], la, lb,
                            (round(a[0], 2), round(a[1], 2)),
                            (round(b[0], 2), round(b[1], 2))))
    print('changed vs C3:', len(changed))
    for item in changed:
        print('   ', item)


if __name__ == '__main__':
    main()
