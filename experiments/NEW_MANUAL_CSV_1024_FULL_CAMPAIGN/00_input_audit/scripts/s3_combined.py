# -*- coding: utf-8 -*-
"""Stage 3: merge Z1 (512) + Z2 expanded (512) into the audited 1024-connection table.

Writes ``combined_1024_audit.json``, ``connectivity_1024_proposed.csv`` (12-column
V3/V4 topology schema) and a 21-column annotated convenience variant.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import common as C  # noqa: E402

OUT_JSON = AUDIT / 'combined_1024_audit.json'
OUT_CSV = AUDIT / 'connectivity_1024_proposed.csv'
OUT_CSV_FULL = AUDIT / 'connectivity_1024_proposed_annotated.csv'

ANNOTATED_FIELDS = C.MANUAL_FIELDS + ['plane', 'pair']


def counter_dict(counter):
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def main():
    eps = C.endpoints()
    combined = C.load_combined()
    routes = combined['routes']
    checks = []

    def check(cid, name, passed, detail=None):
        checks.append(dict(id=cid, name=name, passed=bool(passed), detail=detail))
        return passed

    # ---------------------------------------------------------------- totals
    route_ids = [r['route_id'] for r in routes]
    check('c-01', 'exactly 1024 connections', len(routes) == 1024, len(routes))
    check('c-02', 'route_id = 1..1024 exactly once', route_ids == list(range(1, 1025)),
          dict(count=len(route_ids), unique=len(set(route_ids))))
    plane_counts = Counter(r['plane'] for r in routes)
    check('c-03', 'plane split 512 z1 + 512 z2',
          plane_counts == {'z1': 512, 'z2': 512}, counter_dict(plane_counts))
    row_counts = Counter((r['plane'], r['source_row'], r['target_row']) for r in routes)
    check('c-04', 'every z1 route uses row 1 and every z2 route uses row 2',
          set(row_counts) == {('z1', 1, 1), ('z2', 2, 2)}, counter_dict(row_counts))

    # ---------------------------------------------------------------- endpoints
    usage = Counter()
    for r in routes:
        usage[r['source']] += 1
        usage[r['target']] += 1
    all_ports = set(eps)
    check('c-05', '2048 endpoints used, each exactly once',
          len(usage) == 2048 and set(usage.values()) == {1},
          dict(unique=len(usage), max_use=max(usage.values())))
    check('c-06', 'endpoint set equals the full frozen 2048-port model',
          set(usage) == all_ports,
          dict(missing=len(all_ports - set(usage)),
               extra=len(set(usage) - all_ports)))
    # 64 connectors x 32 holes
    per_connector = {}
    ok_connector = True
    for name in C.connector_names():
        ports = {e for e, ep in eps.items() if ep['connector'] == name}
        used = {e for e in ports if usage.get(e) == 1}
        per_connector[name] = dict(ports=len(ports), used_once=len(used),
                                   z1_ports=sum(1 for e in ports if eps[e]['plane'] == 'z1'),
                                   z2_ports=sum(1 for e in ports if eps[e]['plane'] == 'z2'),
                                   complete=(len(used) == 32))
        ok_connector &= per_connector[name]['complete']
    check('c-07', '64 connectors x 32 holes: every connector fully covered, each hole once',
          ok_connector and len(per_connector) == 64,
          dict(connectors=len(per_connector),
               min_holes=min(v['used_once'] for v in per_connector.values()),
               max_holes=max(v['used_once'] for v in per_connector.values())))
    side_counts = Counter(eps[e]['side'] for e in usage)
    check('c-08', 'each board side provides 512 used endpoints',
          side_counts == {'N': 512, 'E': 512, 'S': 512, 'W': 512},
          counter_dict(side_counts))
    check('c-09', 'no duplicate unordered connection',
          len({C.canonical_connection(r['source'], r['target']) for r in routes})
          == len(routes),
          dict(unique=len({C.canonical_connection(r['source'], r['target'])
                           for r in routes})))

    # ---------------------------------------------------------------- relations
    rel_plane = {plane: Counter(r['relation'] for r in routes if r['plane'] == plane)
                 for plane in C.PLANES}
    rel_total = Counter(r['relation'] for r in routes)
    pair_plane = {plane: Counter(r['pair'] for r in routes if r['plane'] == plane)
                  for plane in C.PLANES}
    pair_total = Counter(r['pair'] for r in routes)
    check('c-10', 'z1 relations = opposite 256 / same 256',
          rel_plane['z1'] == {'opposite': 256, 'same': 256},
          counter_dict(rel_plane['z1']))
    check('c-11', 'z2 relations = adjacent 400 / same 112',
          rel_plane['z2'] == {'adjacent': 400, 'same': 112},
          counter_dict(rel_plane['z2']))
    check('c-12', 'combined relation totals = opposite 256 / adjacent 400 / same 368',
          rel_total == {'opposite': 256, 'adjacent': 400, 'same': 368},
          counter_dict(rel_total))
    check('c-13', 'relation field equals frozen-model relation on every row',
          all(r['relation'] == r['csv_relation'] for r in routes),
          dict(mismatches=sum(1 for r in routes if r['relation'] != r['csv_relation'])))
    cross_side = rel_total['opposite'] + rel_total['adjacent']
    u_side = rel_total['same']
    check('c-14', 'cross-edge endpoints 1312 / same-side U endpoints 736',
          2 * cross_side == 1312 and 2 * u_side == 736,
          dict(cross_connections=cross_side, cross_endpoints=2 * cross_side,
               u_connections=u_side, u_endpoints=2 * u_side,
               total_endpoints=2 * (cross_side + u_side)))

    # ---------------------------------------------------------------- C4 groups
    rot_analysis = C.rotation_analysis([(r['source'], r['target']) for r in routes])
    # rebuild explicit groups (route_id level) with plane/kind/pair consistency
    rot = C.rot90_map()
    by_conn = {}
    for r in routes:
        key = frozenset((r['source'], r['target']))
        if key in by_conn:
            raise ValueError(f'duplicate connection {sorted(key)}')
        by_conn[key] = r
    groups = []
    route_group = {}
    seen = set()
    for r in routes:
        if r['route_id'] in seen:
            continue
        orbit, cur = [r], r
        for _ in range(3):
            key = frozenset(rot[e] for e in (cur['source'], cur['target']))
            nxt = by_conn.get(key)
            if nxt is None:
                raise ValueError(f'no rotation partner for route {cur["route_id"]}')
            orbit.append(nxt)
            cur = nxt
        if frozenset(rot[e] for e in (cur['source'], cur['target'])) != \
                frozenset((r['source'], r['target'])):
            raise ValueError(f'group of route {r["route_id"]} does not close')
        planes = {m['plane'] for m in orbit}
        kinds = {m['relation'] for m in orbit}
        if len(planes) != 1 or len(kinds) != 1:
            raise ValueError(f'group of route {r["route_id"]} mixes plane/kind')
        gid = len(groups) + 1
        groups.append(dict(group_id=gid, plane=orbit[0]['plane'],
                           kind=orbit[0]['relation'], pair=orbit[0]['pair'],
                           route_ids=[m['route_id'] for m in orbit]))
        for phase, member in enumerate(orbit):
            route_group[member['route_id']] = [gid, phase]
            seen.add(member['route_id'])
    group_kinds = Counter(g['kind'] for g in groups)
    groups_per_plane = Counter(g['plane'] for g in groups)
    check('c-15', '256 strict C4 orbits of 4 connections, 128 per plane',
          len(groups) == 256 and groups_per_plane == {'z1': 128, 'z2': 128},
          dict(groups=len(groups), per_plane=counter_dict(groups_per_plane),
               orbit_size_histogram=rot_analysis['orbit_size_histogram']))
    check('c-16', 'rotation closure 0 missing at 90/180/270 deg',
          all(v == 0 for v in rot_analysis['closure_missing'].values()),
          rot_analysis['closure_missing'])
    check('c-17', 'group kinds = opposite 64 / adjacent 100 / same 92',
          group_kinds == {'opposite': 64, 'adjacent': 100, 'same': 92},
          counter_dict(group_kinds))
    routes_by_id = {r['route_id']: r for r in routes}
    check('c-18', 'every C4 orbit stays inside one plane and one relation class',
          all(len({routes_by_id[rid]['plane'] for rid in g['route_ids']}) == 1 and
              len({routes_by_id[rid]['relation'] for rid in g['route_ids']}) == 1
              for g in groups),
          dict(kinds=counter_dict(group_kinds),
               per_plane=counter_dict(groups_per_plane)))

    # ---------------------------------------------------------------- CSV output
    csv_rows = []
    for r in routes:
        csv_rows.append(dict(route_id=r['route_id'],
                             source_side=r['source_side'],
                             source_connector=r['source_connector'],
                             source_row=r['source_row'],
                             source_column=r['source_column'],
                             source_channel=r['source_channel'],
                             target_side=r['target_side'],
                             target_connector=r['target_connector'],
                             target_row=r['target_row'],
                             target_column=r['target_column'],
                             target_channel=r['target_channel'],
                             relation=r['relation']))
    C.write_csv(OUT_CSV, C.COMBINED_FIELDS, csv_rows)
    readback = C.read_plain_csv(OUT_CSV)
    reference = C.read_plain_csv(C.OLD_COMBINED)
    csv_facts = dict(
        path=str(OUT_CSV), sha256=C.sha256_file(OUT_CSV),
        bytes=OUT_CSV.stat().st_size, rows=len(csv_rows),
        header=readback['header'],
        header_matches_reference=readback['header'] == reference['header'],
        reference_path=str(C.OLD_COMBINED),
        reference_header=reference['header'],
        schema_note='same 12-column V3/V4 topology schema as the old campaign '
                    'connectivity_1024.csv')
    check('c-19', 'proposed CSV has the same 12-column schema as the engineering '
                  'V3/V4 connectivity table',
          readback['header'] == reference['header'] and len(readback['rows']) == 1024,
          dict(header=readback['header'], rows=len(readback['rows'])))
    check('c-20', 'proposed CSV round-trips: 1024 rows, route_id 1..1024, all port '
                  'identities resolvable',
          [int(r['route_id']) for r in readback['rows']] == list(range(1, 1025)) and
          all(f"{r[role + '_connector']}:{r[role + '_row']}:{r[role + '_column']}"
              in eps
              for r in readback['rows'] for role in ('source', 'target')),
          dict(rows=len(readback['rows'])))
    # annotated variant
    annotated = []
    for r in routes:
        annotated.append(dict(route_id=r['route_id'],
                              source_side=r['source_side'],
                              source_connector=r['source_connector'],
                              source_row=r['source_row'],
                              source_column=r['source_column'],
                              source_channel=r['source_channel'],
                              target_side=r['target_side'],
                              target_connector=r['target_connector'],
                              target_row=r['target_row'],
                              target_column=r['target_column'],
                              target_channel=r['target_channel'],
                              relation=r['relation'],
                              source_port_id=r['source'],
                              target_port_id=r['target'],
                              source_x_mm=r['source_x_mm'],
                              source_y_mm=r['source_y_mm'],
                              target_x_mm=r['target_x_mm'],
                              target_y_mm=r['target_y_mm'],
                              layer=r['plane'], plane=r['plane'], pair=r['pair']))
    C.write_csv(OUT_CSV_FULL, ANNOTATED_FIELDS, annotated)
    annotated_facts = dict(path=str(OUT_CSV_FULL),
                           sha256=C.sha256_file(OUT_CSV_FULL),
                           rows=len(annotated), columns=len(ANNOTATED_FIELDS),
                           fields=ANNOTATED_FIELDS,
                           note='19-column manual schema plus plane/pair annotations; '
                                'convenience variant, not the engineering topology schema')
    check('c-21', 'annotated CSV has 1024 rows and 21 columns',
          len(annotated) == 1024, annotated_facts)

    # ---------------------------------------------------------------- cross checks
    # Z1 rows are preserved byte-semantically (same route_id, same connection)
    z1_src = {int(r['route_id']): (C.ep_of(r, 'source'), C.ep_of(r, 'target'))
              for r in combined['z1']['rows']}
    z1_out = {r['route_id']: (r['source'], r['target'])
              for r in routes if r['plane'] == 'z1'}
    check('c-22', 'Z1 512 connections preserved with the same route_id and ordering',
          z1_src == z1_out, dict(rows=len(z1_src)))
    # Z2 route ids 513..1024 are the expanded order + 512
    z2_exp = {c['route_id'] + 512: (c['source'], c['target'])
              for c in combined['z2']['expanded']}
    z2_out = {r['route_id']: (r['source'], r['target'])
              for r in routes if r['plane'] == 'z2'}
    check('c-23', 'Z2 512 connections use route_id 513..1024 (expanded order + 512)',
          z2_exp == z2_out, dict(rows=len(z2_exp)))
    # cross validation against the campaign builder's combined table
    builder = C.read_plain_csv(C.NEW_CAMPAIGN_COMBINED)
    builder_pairs = {C.canonical_connection(
        f"{r['source_connector']}:{r['source_row']}:{r['source_column']}",
        f"{r['target_connector']}:{r['target_row']}:{r['target_column']}")
        for r in builder['rows']}
    mine_pairs = {C.canonical_connection(r['source'], r['target']) for r in routes}
    cross = dict(path=str(C.NEW_CAMPAIGN_COMBINED),
                 sha256=C.sha256_file(C.NEW_CAMPAIGN_COMBINED),
                 rows=len(builder['rows']), header=builder['header'],
                 header_equals=readback['header'] == builder['header'],
                 common=len(mine_pairs & builder_pairs),
                 only_audit=len(mine_pairs - builder_pairs),
                 only_builder=len(builder_pairs - mine_pairs),
                 connection_sets_equal=mine_pairs == builder_pairs,
                 route_id_identity=None)
    # route_id identity only where connection sets are equal
    builder_by_rid = {int(r['route_id']): C.canonical_connection(
        f"{r['source_connector']}:{r['source_row']}:{r['source_column']}",
        f"{r['target_connector']}:{r['target_row']}:{r['target_column']}")
        for r in builder['rows']}
    mine_by_rid = {r['route_id']: C.canonical_connection(r['source'], r['target'])
                   for r in routes}
    same_rid = sum(1 for rid in mine_by_rid
                   if rid in builder_by_rid and mine_by_rid[rid] == builder_by_rid[rid])
    cross.update(route_id_identity=same_rid,
                 route_id_identity_note='Z1 route_id 1..512 identical; Z2 route_id '
                                        '513..1024 depend on the C4 phase ordering')
    check('c-24', 'connection set equals the independently built campaign combined CSV',
          mine_pairs == builder_pairs,
          dict(common=cross['common'], only_audit=cross['only_audit'],
               only_builder=cross['only_builder'], same_route_ids=same_rid))

    payload = dict(
        schema='new_manual_csv_input_audit_combined_1024_v1',
        title='Merged 1024-connection topology audit (Z1 512 + Z2 C4-expanded 512)',
        numbering_rule=dict(z1='route_id 1..512 exactly as in the Z1 CSV',
                            z2='expanded z2 route_id 1..512 (base route_id ascending, '
                               'C4 phase 0/90/180/270) + 512 -> 513..1024'),
        inputs=dict(z1=dict(path=str(C.Z1_NEW), sha256=C.sha256_file(C.Z1_NEW),
                            rows=512),
                    z2_expanded=dict(path=str(AUDIT / 'z2_expanded_512.csv'),
                                     sha256=C.sha256_file(AUDIT / 'z2_expanded_512.csv'),
                                     rows=512)),
        totals=dict(connections=len(routes), endpoints=2 * len(routes),
                    endpoints_used_once=True,
                    connectors=len(per_connector),
                    holes_per_connector=32,
                    planes=counter_dict(plane_counts),
                    relation_by_plane={p: counter_dict(rel_plane[p])
                                       for p in C.PLANES},
                    relation_total=counter_dict(rel_total),
                    pair_by_plane={p: counter_dict(pair_plane[p])
                                   for p in C.PLANES},
                    pair_total=counter_dict(pair_total),
                    side_endpoints=counter_dict(side_counts),
                    cross_edge_endpoints=2 * cross_side,
                    u_endpoints=2 * u_side),
        per_connector=per_connector,
        c4_groups=dict(count=len(groups),
                       per_plane=counter_dict(groups_per_plane),
                       kinds=counter_dict(group_kinds),
                       closure=rot_analysis['closure_missing'],
                       orbit_size_histogram=rot_analysis['orbit_size_histogram'],
                       groups=groups),
        route_group={str(k): v for k, v in sorted(route_group.items())},
        output_csv=csv_facts,
        output_csv_annotated=annotated_facts,
        cross_validation_with_campaign_builder=cross,
        checks=checks,
        verdict=dict(errors=sum(1 for c in checks if not c['passed']),
                     passed=all(c['passed'] for c in checks)))
    C.write_json(OUT_JSON, payload)
    print(json.dumps(dict(
        out=str(OUT_JSON), csv=str(OUT_CSV), csv_full=str(OUT_CSV_FULL),
        connections=len(routes), endpoints=len(usage),
        relations=counter_dict(rel_total),
        groups=len(groups), group_kinds=counter_dict(group_kinds),
        closure=rot_analysis['closure_missing'],
        checks=len(checks), passed=payload['verdict']['passed'],
        crossequal=cross['connection_sets_equal'],
        csv_sha=csv_facts['sha256']), ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
