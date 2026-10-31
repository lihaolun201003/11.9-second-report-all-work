# -*- coding: utf-8 -*-
"""Stage 2: C4 expansion of the 128 Z2 base connections into the 512-row z2 plane.

Writes ``z2_expanded_512.csv`` (19-column manual schema, physical row-2 ids) and
``z2_c4_expansion.json``.  Everything is recomputed from the frozen port model.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import common as C  # noqa: E402

OUT_JSON = AUDIT / 'z2_c4_expansion.json'
OUT_CSV = AUDIT / 'z2_expanded_512.csv'


def counter_dict(counter):
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def main():
    eps = C.endpoints()
    rot = C.rot90_map()
    exp = C.load_z2_expansion()
    checks = []

    def check(cid, name, passed, detail=None):
        checks.append(dict(id=cid, name=name, passed=bool(passed), detail=detail))
        return passed

    base_rows = exp['base']['rows']
    base_info = dict(
        path=str(C.Z2_NEW), sha256=exp['base']['sha256'],
        bytes=exp['base']['bytes'], rows=len(base_rows),
        relations=counter_dict(Counter(r['relation'] for r in base_rows)),
        route_ids=dict(count=len(base_rows),
                       min=min(int(r['route_id']) for r in base_rows),
                       max=max(int(r['route_id']) for r in base_rows),
                       contiguous=sorted(int(r['route_id']) for r in base_rows)
                       == list(range(1, 129))),
        raw_row_convention={'layer': counter_dict(Counter(r['layer'] for r in base_rows)),
                            'source_row': counter_dict(Counter(r['source_row']
                                                               for r in base_rows))},
        note='128 base rows carry legacy row-1 port ids; the campaign plane is z2')
    base_conns = exp['base_conns']

    # ------------------------------------------------------------------ remap
    remap = dict(
        rule='same connector and column, row 1 -> row 2, z 0.0 mm -> 0.5 mm',
        example={'N03:1:3': 'N03:2:3'},
        endpoints_remapped=256,
        base_source_ids_are_row1=all(e.split(':')[1] == '1'
                                     for c in base_conns
                                     for e in (c['source'], c['target'])),
        rotation_commutes_with_remap=len(exp['equivalence_mismatch']) == 0,
        equivalence_mismatches=len(exp['equivalence_mismatch']),
        check_detail='rot90(row1_to_row2(e)) == row1_to_row2(rot90(e)) for all 1024 '
                     'row-1 endpoints')
    check('z2x-01', 'all 256 base port ids are row-1 ids', 
          remap['base_source_ids_are_row1'])
    check('z2x-02', 'row-1 -> row-2 remap commutes with the 90 deg rotation',
          remap['rotation_commutes_with_remap'], remap['equivalence_mismatches'])
    base_relation_mismatch = [dict(base_route_id=c['base_route_id'],
                                   csv=c['csv_relation'], model=c['relation'])
                              for c in base_conns if c['relation'] != c['csv_relation']]
    check('z2x-03', 'base csv relation equals relation recomputed from physical z2 sides',
          not base_relation_mismatch, base_relation_mismatch[:5])

    # ------------------------------------------------------------------ orbits
    per_base = exp['per_base']
    orbit_sizes = Counter(len(v) for v in per_base.values())
    per_base_report = []
    for conn in base_conns:
        orbit = per_base[conn['base_route_id']]
        per_base_report.append(dict(
            base_route_id=conn['base_route_id'],
            base_source=conn['source'], base_target=conn['target'],
            plane2_source=conn['plane2_source'],
            plane2_target=conn['plane2_target'],
            relation=conn['relation'],
            orbit_size=len(set(orbit)),
            distinct_orbits=len(set(orbit)),
            orbit=[list(p) for p in orbit]))
    check('z2x-04', 'each of the 128 base connections generates exactly 4 distinct '
                    'rotated ring connections',
          orbit_sizes == {4: 128},
          dict(orbit_size_histogram=counter_dict(orbit_sizes)))
    duplicated_base_orbits = [dict(base_route_id=r['base_route_id'])
                              for r in per_base_report if r['orbit_size'] < 4]
    check('z2x-05', 'no base connection degenerates under rotation '
                    '(no 90/180/270 self-symmetric connection)',
          not duplicated_base_orbits, duplicated_base_orbits[:5])

    expanded = exp['expanded']
    check('z2x-06', 'expanded set holds exactly 512 distinct unordered connections',
          len(expanded) == 512 and len({C.canonical_connection(c['source'],
                                                               c['target'])
                                        for c in expanded}) == 512,
          dict(rows=len(expanded)))
    check('z2x-07', 'no cross-base orbit collision (all 128 orbits disjoint)',
          not exp['conflicts'], exp['conflicts'][:5])

    # ------------------------------------------------------------------ endpoints
    usage = Counter()
    for cell in expanded:
        usage[cell['source']] += 1
        usage[cell['target']] += 1
    z2_ports = C.plane_ports('z2')
    check('z2x-08', '1024 endpoints, each used exactly once',
          len(usage) == 1024 and set(usage.values()) == {1},
          dict(unique=len(usage), max_use=max(usage.values())))
    check('z2x-09', 'expanded endpoint set equals the full 1024-port z2 plane',
          set(usage) == z2_ports,
          dict(missing=len(z2_ports - set(usage)),
               extra=len(set(usage) - z2_ports)))
    all_z2 = all(eps[e]['plane'] == 'z2' and eps[e]['row'] == 2 for e in usage)
    check('z2x-10', 'every expanded endpoint is a physical row-2 / z2 port', all_z2)

    # ------------------------------------------------------------------ closure
    closure = {}
    pairs = {C.canonical_connection(c['source'], c['target']) for c in expanded}
    for step in (1, 2, 3):
        power = C.rot_power(step)
        missing = [p for p in pairs
                   if C.canonical_connection(power[p[0]], power[p[1]])
                   not in pairs]
        closure[f'{step * 90}deg'] = len(missing)
    check('z2x-11', 'C4 closure: rotating the expanded 512-set by 90/180/270 deg '
                    'returns the same set',
          all(v == 0 for v in closure.values()), closure)

    relations = Counter(c['relation'] for c in expanded)
    pairs_cnt = Counter(C.side_pair(eps[c['source']]['side'],
                                    eps[c['target']]['side']) for c in expanded)
    check('z2x-12', 'expanded relation counts = adjacent 400 / same 112',
          relations == {'adjacent': 400, 'same': 112}, counter_dict(relations))
    plane2_ports_in_opposite = sum(1 for c in expanded if c['relation'] == 'opposite')
    check('z2x-13', 'expanded z2 plane contains no opposite relation',
          plane2_ports_in_opposite == 0, dict(opposite=plane2_ports_in_opposite))

    # ---------------------------------------------------------------- per connector
    per_conn = {}
    for side in C.SIDES:
        for i in range(1, 17):
            name = f'{side}{i:02d}'
            ports = [e for e in z2_ports if eps[e]['connector'] == name]
            adj = sum(1 for e in ports
                      for c in expanded
                      if e in (c['source'], c['target']) and c['relation'] == 'adjacent')
            same = sum(1 for e in ports
                       for c in expanded
                       if e in (c['source'], c['target']) and c['relation'] == 'same')
            per_conn[name] = dict(adjacent_endpoints=adj, same_endpoints=same,
                                  total=adj + same)
    uniform = (len({(v['adjacent_endpoints'], v['same_endpoints'])
                    for v in per_conn.values()}) == 2)
    check('z2x-14', 'per-connector z2 split is uniform: end connectors 8 adjacent/8 U, '
                    'middle connectors 14 adjacent/2 U',
          all(per_conn[f'{s}{i:02d}'] == dict(adjacent_endpoints=(8 if i in (1, 2, 15, 16)
                                                                  else 14),
                                              same_endpoints=(8 if i in (1, 2, 15, 16)
                                                              else 2),
                                              total=16)
              for s in C.SIDES for i in range(1, 17)), dict(uniform=uniform))

    # ------------------------------------------------------------------ CSV
    csv_rows = [C.expanded_row(cell) for cell in expanded]
    C.write_csv(OUT_CSV, C.MANUAL_FIELDS, csv_rows)
    readback = C.read_manual_csv(OUT_CSV)
    readback_ok = (
        readback['header'] == C.MANUAL_FIELDS and len(readback['rows']) == 512 and
        readback['bom'] and readback['crlf_only'] and
        [int(r['route_id']) for r in readback['rows']] == list(range(1, 513)) and
        all(r['layer'] == 'z2' and r['source_row'] == '2' and r['target_row'] == '2'
            for r in readback['rows']) and
        all(int(r[f'{role}_channel']) == 16 + int(r[f'{role}_column'])
            for r in readback['rows'] for role in ('source', 'target')))
    csv_facts = dict(path=str(OUT_CSV), sha256=C.sha256_file(OUT_CSV),
                     bytes=OUT_CSV.stat().st_size, rows=len(csv_rows),
                     header=readback['header'], readback_ok=readback_ok,
                     route_id_range=[1, 512], layer='z2', source_row=2,
                     channel_convention='channel = 16 + column',
                     route_id_assignment='base route_id ascending, then C4 phase '
                                         '0/90/180/270 -> route_id 1..512')
    check('z2x-15', 'z2_expanded_512.csv round-trips: schema, 512 rows, z2 row-2 ids, '
                    'channel = 16 + column', readback_ok, csv_facts)

    # ---------------------------------------------------- cross validation
    builder_path = C.NEW_CAMPAIGN_Z2_EXPANDED
    cross = dict(path=str(builder_path), available=builder_path.exists())
    if builder_path.exists():
        builder = C.read_manual_csv(builder_path)
        builder_pairs = {C.canonical_connection(C.ep_of(r, 'source'),
                                                C.ep_of(r, 'target'))
                         for r in builder['rows']}
        mine = {C.canonical_connection(c['source'], c['target']) for c in expanded}
        cross.update(sha256=builder['sha256'], rows=len(builder['rows']),
                     header=builder['header'],
                     common=len(mine & builder_pairs),
                     only_audit=len(mine - builder_pairs),
                     only_builder=len(builder_pairs - mine),
                     connection_sets_equal=mine == builder_pairs)
        check('z2x-16', 'connection set equals the independently built campaign '
                        'expanded z2 CSV (only route_id ordering may differ)',
              mine == builder_pairs,
              dict(common=cross['common'], only_audit=cross['only_audit'],
                   only_builder=cross['only_builder']))

    # ---------------------------------------------------------------- report
    payload = dict(
        schema='new_manual_csv_input_audit_z2_c4_expansion_v1',
        title='C4 expansion of the 128 Z2 base connections into 512 z2-plane connections',
        operation='two base rows -> four lines per C4 orbit: rotate both endpoints by '
                  '0/90/180/270 deg about the board centre (75, 75) mm; an undirected '
                  'connection {A,B} is identified with {B,A}',
        board_mm=C.BOARD_MM,
        rotation_formula=dict(matrix=[[0.0, -1.0], [1.0, 0.0]], offset=[150.0, 0.0],
                              text='(x, y) -> (150 - y, x), z unchanged'),
        base=base_info,
        remap=remap,
        expansion=dict(
            base_connections=len(base_conns), expanded_connections=len(expanded),
            multiplier=4, orbits=len(set(per_base)),
            orbit_size_histogram=counter_dict(orbit_sizes),
            conflicts=exp['conflicts'],
            endpoint_count=len(usage),
            endpoints_used_once=bool(usage) and set(usage.values()) == {1},
            endpoint_set_equals_plane_z2=set(usage) == z2_ports,
            closure=closure,
            relation_counts=counter_dict(relations),
            pair_counts=counter_dict(pairs_cnt),
            per_connector=per_conn,
            expected_relation_counts={'adjacent': 400, 'same': 112},
            relation_counts_match_expected=(relations == {'adjacent': 400,
                                                          'same': 112})),
        per_base_orbits=per_base_report,
        route_id_map={str(r['base_route_id']): [cell['route_id']
                                               for cell in expanded
                                               if cell['ex_base_route_id']
                                               == r['base_route_id']]
                      for r in per_base_report},
        output_csv=csv_facts,
        cross_validation=cross,
        checks=checks,
        verdict=dict(errors=sum(1 for c in checks if not c['passed']),
                     passed=all(c['passed'] for c in checks)))
    C.write_json(OUT_JSON, payload)
    print(json.dumps(dict(
        out=str(OUT_JSON), csv=str(OUT_CSV),
        base=len(base_conns), expanded=len(expanded),
        relations=payload['expansion']['relation_counts'],
        endpoints=len(usage), closure=closure,
        orbits=len(set(per_base)), checks=len(checks),
        crossequal=cross.get('connection_sets_equal'),
        passed=payload['verdict']['passed']), ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
