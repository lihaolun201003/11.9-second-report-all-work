# -*- coding: utf-8 -*-
"""Step 1 (v2): authoritative 1024-connection table + independent verification.

Independently re-derives the canonical campaign topology from the two *source*
CSVs (manual_z1_c4_full_section2.csv / manual_z2_c4_full_section2.csv) and checks
it against the campaign's own canonical inputs (inputs/connectivity_1024.csv):

* Z1: 512 rows used directly (row-1 / z1 ports), opposite 256 + same 256.
* Z2: 128 quaternary-base rows -> row-2 / z2 ports -> C4 expansion (90/180/270
  about (75,75)) -> 512 connections, adjacent 400 + same 112.

Port coordinates / inward tangents come from the frozen model
``four_side_1024.fslw.ports.build_plane_endpoints`` (the 2048 real 2x16 MPO
endpoints).  Every CSV coordinate is re-computed and compared.

Writes ``data/connections_1024.json`` and ``data/load_report.json`` only.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from four_side_1024.fslw.ports import build_plane_endpoints  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
DATA = OUT / 'data'
DATA.mkdir(parents=True, exist_ok=True)
CAMPAIGN = OUT.parent
CANON_CSV = CAMPAIGN / 'inputs/connectivity_1024.csv'
SRC_Z1 = ROOT / 'manual_z1_router/data/exports/manual_z1_c4_full_section2.csv'
SRC_Z2 = ROOT / 'manual_z1_router/data/exports/manual_z2_c4_full_section2.csv'

BOARD = 150.0
TOL = 1e-9
R = 15.0
Z = {'z1': 0.0, 'z2': 0.5}

EPS = build_plane_endpoints()
COORD_INDEX = {}
for _eid, _ep in EPS.items():
    key = (round(float(_ep['routing_xy'][0]), 6),
           round(float(_ep['routing_xy'][1]), 6), float(_ep['z_mm']))
    if key in COORD_INDEX:
        raise ValueError(f'duplicate endpoint coordinate {key}')
    COORD_INDEX[key] = _eid
# rot90 about the board centre (75,75): (x,y) -> (150-y, x); z plane preserved
ROT90 = {}
for _eid, _ep in EPS.items():
    _x, _y = (float(v) for v in _ep['routing_xy'])
    ROT90[_eid] = COORD_INDEX[(round(BOARD - _y, 6), round(_x, 6),
                               float(_ep['z_mm']))]
ROT90_INV = {v: k for k, v in ROT90.items()}
PLANE_PORTS = {p: {eid for eid, ep in EPS.items() if ep['plane'] == p}
               for p in ('z1', 'z2')}


def read_csv_rows(path):
    raw = Path(path).read_bytes()
    return raw, list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))


def relation_of_sides(a, b):
    if a == b:
        return 'same'
    return 'opposite' if {a, b} in ({'N', 'S'}, {'E', 'W'}) else 'adjacent'


def row_to_row2(eid):
    """Map a row-1 port id to the same hole of the z2 row-2 plane."""
    conn, _row, col = eid.split(':')
    out = f'{conn}:2:{col}'
    if out not in EPS or EPS[out]['plane'] != 'z2':
        raise KeyError(out)
    return out


def check_row(row, issues, tag, expected_row):
    rid = int(row['route_id'])
    for role in ('source', 'target'):
        eid = row[f'{role}_port_id']
        ep = EPS.get(eid)
        if ep is None:
            issues.append([tag, rid, role, 'unknown port id', eid])
            continue
        if ep['plane'] != 'z1':
            issues.append([tag, rid, role, 'not a z1 port id', eid])
        for field, key in (('side', 'side'), ('connector', 'connector')):
            if ep[key] != row[f'{role}_{field}']:
                issues.append([tag, rid, role, f'{field} mismatch', eid])
        if int(ep['row']) != int(row[f'{role}_row']):
            issues.append([tag, rid, role, 'row mismatch', eid])
        if int(ep['column']) != int(row[f'{role}_column']):
            issues.append([tag, rid, role, 'column mismatch', eid])
        if int(ep['channel']) != int(row[f'{role}_channel']):
            issues.append([tag, rid, role, 'channel mismatch', eid])
        x, y = float(row[f'{role}_x_mm']), float(row[f'{role}_y_mm'])
        ex, ey = (float(ep['routing_xy'][0]), float(ep['routing_xy'][1]))
        if abs(x - ex) > 1e-9 or abs(y - ey) > 1e-9:
            issues.append([tag, rid, role, 'xy mismatch', eid, [x, y], [ex, ey]])
    rel = relation_of_sides(row['source_side'], row['target_side'])
    if rel != row['relation']:
        issues.append([tag, rid, 'relation mismatch', row['relation'], rel])


def connection_record(route_id, source_eid, target_eid, plane, origin):
    sp, tp = EPS[source_eid], EPS[target_eid]
    sx, sy = (float(v) for v in sp['routing_xy'])
    tx, ty = (float(v) for v in tp['routing_xy'])
    s_side, t_side = sp['side'], tp['side']
    return dict(
        route_id=int(route_id), plane=plane, origin=origin,
        source_endpoint=source_eid, target_endpoint=target_eid,
        source_endpoint_row1=(source_eid if plane == 'z1' else row_to_row2(source_eid)),
        target_endpoint_row1=(target_eid if plane == 'z1' else row_to_row2(target_eid)),
        source_side=s_side, target_side=t_side,
        source_connector=sp['connector'], target_connector=tp['connector'],
        source_row=int(sp['row']), target_row=int(tp['row']),
        source_column=int(sp['column']), target_column=int(tp['column']),
        source_channel=int(sp['channel']), target_channel=int(tp['channel']),
        source_xy=[sx, sy], target_xy=[tx, ty],
        source_z=float(sp['z_mm']), target_z=float(tp['z_mm']),
        source_inward=[float(v) for v in sp['inward']],
        target_inward=[float(v) for v in tp['inward']],
        relation=relation_of_sides(s_side, t_side),
    )


def main():
    report = dict(schema='corner_r15_connections_1024_v1',
                  board_mm=BOARD, radius_mm=R,
                  width_mm=0.05, clearance_mm=0.08,
                  z_mm=Z, checks=[], issues=[])
    issues = report['issues']

    def check(name, ok, detail=''):
        report['checks'].append(dict(check=name, passed=bool(ok), detail=detail))
        return ok

    # ------------------------------------------------------------- Z1 source
    raw1, rows1 = read_csv_rows(SRC_Z1)
    check('source z1 csv rows == 512', len(rows1) == 512, len(rows1))
    check('source z1 csv header == 19 manual columns',
          list(rows1[0].keys()) == [
              'route_id', 'source_side', 'source_connector', 'source_row',
              'source_column', 'source_channel', 'target_side', 'target_connector',
              'target_row', 'target_column', 'target_channel', 'relation',
              'source_port_id', 'target_port_id', 'source_x_mm', 'source_y_mm',
              'target_x_mm', 'target_y_mm', 'layer'], list(rows1[0].keys()))
    for row in rows1:
        check_row(row, issues, 'z1', 1)
    check('source z1: every port id/metadata/xy/relation re-computed OK',
          not [i for i in issues if i[0] == 'z1'], len(issues))
    check('source z1: all rows are row=1 / layer=z1',
          all(int(r['source_row']) == 1 and int(r['target_row']) == 1 and
              r['layer'] == 'z1' for r in rows1))
    z1_conns = [connection_record(int(r['route_id']), r['source_port_id'],
                                  r['target_port_id'], 'z1', 'z1_section2')
                for r in rows1]
    z1_usage = Counter()
    for c in z1_conns:
        z1_usage[c['source_endpoint']] += 1
        z1_usage[c['target_endpoint']] += 1
    check('source z1: all 1024 z1 ports used exactly once',
          set(z1_usage) == PLANE_PORTS['z1'] and set(z1_usage.values()) == {1},
          dict(unique=len(z1_usage)))
    check('source z1 relations 256 opposite + 256 same',
          dict(Counter(c['relation'] for c in z1_conns)) ==
          {'opposite': 256, 'same': 256},
          dict(Counter(c['relation'] for c in z1_conns)))
    z1_pairs = {tuple(sorted((c['source_endpoint'], c['target_endpoint'])))
                for c in z1_conns}
    check('source z1 connection set is C4 closed (90/180/270)',
          all(tuple(sorted((p[0], p[1]))) in z1_pairs
              for p in [(ROT90[a], ROT90[b]) for a, b in z1_pairs]))

    # --------------------------------------------------------- Z2 base source
    raw2, rows2 = read_csv_rows(SRC_Z2)
    check('source z2 csv rows == 128 quaternary base', len(rows2) == 128, len(rows2))
    for row in rows2:
        check_row(row, issues, 'z2_base', 1)
    check('source z2 base: every port id/metadata/xy/relation re-computed OK',
          not [i for i in issues if i[0] == 'z2_base'],
          len([i for i in issues if i[0] == 'z2_base']))
    z2_base = [(int(r['route_id']), r['source_port_id'], r['target_port_id'],
                r['relation']) for r in rows2]
    check('source z2 base relations 100 adjacent + 28 same',
          dict(Counter(x[3] for x in z2_base)) == {'adjacent': 100, 'same': 28},
          dict(Counter(x[3] for x in z2_base)))
    # convert to row-2 ports then expand by C4 (on the physical z2 ports)
    expanded = {}
    for base_id, s1, t1, _rel in z2_base:
        s2, t2 = row_to_row2(s1), row_to_row2(t1)
        cur = (s2, t2)
        for step in range(4):
            key = tuple(sorted(cur))
            if key not in expanded:
                expanded[key] = dict(base_route_id=base_id, c4_step=step,
                                     source=cur[0], target=cur[1])
            cur = (ROT90[cur[0]], ROT90[cur[1]])
    check('z2 C4 expansion -> 512 unique connections', len(expanded) == 512,
          len(expanded))
    z2_usage = Counter()
    for cell in expanded.values():
        z2_usage[cell['source']] += 1
        z2_usage[cell['target']] += 1
    check('z2 expansion uses all 1024 z2 ports exactly once',
          set(z2_usage) == PLANE_PORTS['z2'] and set(z2_usage.values()) == {1},
          dict(unique=len(z2_usage)))
    z2_conns = []
    for key, cell in expanded.items():
        conn = connection_record(0, cell['source'], cell['target'], 'z2',
                                 'c4_of_base_%d' % cell['base_route_id'])
        conn['base_route_id'] = int(cell['base_route_id'])
        conn['c4_step'] = int(cell['c4_step'])
        z2_conns.append(conn)
    # order z2 by base route then lexicographic to match the campaign ordering
    z2_conns.sort(key=lambda c: (c['base_route_id'], c['c4_step'],
                                 c['source_endpoint'], c['target_endpoint']))
    rel2 = Counter(c['relation'] for c in z2_conns)
    check('z2 expansion relations adjacent 400 + same 112',
          dict(rel2) == {'adjacent': 400, 'same': 112}, dict(rel2))

    # ------------------------------------- campaign canonical combined input
    if not CANON_CSV.exists():
        raise FileNotFoundError(CANON_CSV)
    _rawc, canon_rows = read_csv_rows(CANON_CSV)
    check('campaign canonical combined csv has 1024 rows', len(canon_rows) == 1024,
          len(canon_rows))
    canon = {}
    bad_canon = []
    for row in canon_rows:
        rid = int(row['route_id'])
        s = f"{row['source_connector']}:{row['source_row']}:{row['source_column']}"
        t = f"{row['target_connector']}:{row['target_row']}:{row['target_column']}"
        if s not in EPS or t not in EPS:
            bad_canon.append((rid, 'unknown port'))
            continue
        canon[rid] = (s, t)
    check('campaign canonical combined csv port ids all exist in model',
          not bad_canon, bad_canon[:5])
    check('campaign canonical route ids are 1..1024',
          sorted(canon) == list(range(1, 1025)))
    # z1 must match row for row
    z1_order_ok = all(
        canon[rid] == (c['source_endpoint'], c['target_endpoint'])
        for rid, c in zip(range(1, 513), rows1)
        for c in [z1_conns[rid - 1]])
    check('campaign route_id 1..512 == source z1 csv rows (ordered)', z1_order_ok)
    # z2 set equality (unordered)
    canon_z2 = {rid: canon[rid] for rid in range(513, 1025)}
    mine_z2 = {tuple(sorted((c['source_endpoint'], c['target_endpoint'])))
               for c in z2_conns}
    theirs_z2 = {tuple(sorted(p)) for p in canon_z2.values()}
    check('campaign route_id 513..1024 set == my independent z2 expansion',
          mine_z2 == theirs_z2,
          dict(mine=len(mine_z2), theirs=len(theirs_z2),
               missing=len(theirs_z2 - mine_z2),
               extra=len(mine_z2 - theirs_z2)))

    # ---------------------------- build the canonical 1024 table (campaign ids)
    all_conns = []
    for rid in range(1, 1025):
        s, t = canon[rid]
        plane = 'z1' if rid <= 512 else 'z2'
        origin = 'manual_z1_section2' if plane == 'z1' else 'c4_expanded_z2_section2'
        conn = connection_record(rid, s, t, plane, origin)
        if plane == 'z2':
            # attach base route from my independent expansion (if available)
            key = tuple(sorted((s, t)))
            conn['base_route_id'] = int(expanded[key]['base_route_id'])
            conn['c4_step'] = int(expanded[key]['c4_step'])
        all_conns.append(conn)

    # independent structural re-checks on the final 1024 table
    used = Counter()
    for c in all_conns:
        used[c['source_endpoint']] += 1
        used[c['target_endpoint']] += 1
    check('final table: 2048 physical ports each used exactly once',
          len(used) == 2048 and set(used.values()) == {1}, len(used))
    check('final table relations: opposite 256 / adjacent 400 / same 368',
          dict(Counter(c['relation'] for c in all_conns)) ==
          {'opposite': 256, 'adjacent': 400, 'same': 368},
          dict(Counter(c['relation'] for c in all_conns)))
    # per-plane C4 closure on the physical port ids
    for plane, lo, hi in (('z1', 1, 513), ('z2', 513, 1025)):
        pairs = {tuple(sorted((c['source_endpoint'], c['target_endpoint'])))
                 for c in all_conns if c['plane'] == plane}
        closure = {}
        for step in (1, 2, 3):
            power = {}
            for eid in PLANE_PORTS[plane]:
                cur = eid
                for _ in range(step):
                    cur = ROT90[cur]
                power[eid] = cur
            closure[f'{step * 90}deg'] = sum(
                1 for p in pairs
                if tuple(sorted((power[p[0]], power[p[1]]))) not in pairs)
        check(f'{plane} physical connection set C4 closure = 0 missing',
              all(v == 0 for v in closure.values()), closure)

    # ------------------------------------------------------------ statistics
    same = [c for c in all_conns if c['relation'] == 'same']
    adj = [c for c in all_conns if c['relation'] == 'adjacent']
    opp = [c for c in all_conns if c['relation'] == 'opposite']

    def same_sep(c):
        if c['source_side'] in 'NS':
            return abs(c['source_xy'][0] - c['target_xy'][0])
        return abs(c['source_xy'][1] - c['target_xy'][1])

    same_seps = sorted(round(same_sep(c), 6) for c in same)
    stats = dict(
        total=len(all_conns),
        relations=dict(Counter(c['relation'] for c in all_conns)),
        relations_by_plane={p: dict(Counter(c['relation'] for c in all_conns
                                            if c['plane'] == p))
                            for p in ('z1', 'z2')},
        same=dict(
            count=len(same), min_sep=min(same_seps), max_sep=max(same_seps),
            below_2R=sum(1 for v in same_seps if v < 2 * R - 1e-9),
            below_R=sum(1 for v in same_seps if v < R - 1e-9),
            below_clearance=sum(1 for v in same_seps if v < 0.08),
            distinct=dict(Counter(same_seps)),
            side_pairs={f'{a}{b}': n for (a, b), n in Counter(
                (c['source_side'], c['target_side']) for c in same).items()},
            same_connector=sum(1 for c in same
                               if c['source_connector'] == c['target_connector']),
        ),
        adjacent=dict(count=len(adj), side_pairs={
            f'{a}{b}': n for (a, b), n in Counter(
                (c['source_side'], c['target_side']) for c in adj).items()}),
        opposite=dict(count=len(opp), shifts=None),
    )
    # adjacent: distances of both ports to the shared corner
    CORNERS = {frozenset('NE'): (150.0, 150.0), frozenset('ES'): (150.0, 0.0),
               frozenset('SW'): (0.0, 0.0), frozenset('WN'): (0.0, 150.0)}

    def corner_distance(c, role):
        side = c[f'{role}_side']
        x, y = c[f'{role}_xy']
        cx, cy = CORNERS[frozenset((c['source_side'], c['target_side']))]
        return abs(x - cx) if side in 'NS' else abs(y - cy)

    adj_pairs = [(round(corner_distance(c, 'source'), 6),
                  round(corner_distance(c, 'target'), 6)) for c in adj]
    stats['adjacent'].update(
        min_corner_distance=min(min(p) for p in adj_pairs),
        max_corner_distance=max(max(p) for p in adj_pairs),
        min_leg=min(min(p) - R for p in adj_pairs),
        max_leg=max(max(p) - R for p in adj_pairs),
        neg_leg_count=sum(1 for p in adj_pairs if min(p) < R - 1e-9),
        distance_pairs=dict(Counter(f'{a:.6f}|{b:.6f}' for a, b in adj_pairs)),
    )
    # opposite: lateral offset along the axis perpendicular to travel
    shifts = []
    for c in opp:
        if c['source_side'] in 'NS':
            shifts.append(round(abs(c['source_xy'][0] - c['target_xy'][0]), 6))
        else:
            shifts.append(round(abs(c['source_xy'][1] - c['target_xy'][1]), 6))
    stats['opposite'].update(
        min_shift=min(shifts), max_shift=max(shifts),
        distinct_shifts=dict(Counter(shifts)),
        strict90_feasible=sum(1 for v in shifts if v < 1e-9 or v >= 2 * R - 1e-9),
        short_s_required=sum(1 for v in shifts if 1e-9 < v < 2 * R - 1e-9),
    )
    report['stats'] = stats
    report['passed'] = all(c['passed'] for c in report['checks'])

    payload = dict(schema='corner_r15_connections_1024_v1',
                   board_mm=BOARD, radius_mm=R, width_mm=0.05,
                   clearance_mm=0.08, z_mm=Z,
                   sources=dict(z1=str(SRC_Z1), z2=str(SRC_Z2),
                                canonical_combined=str(CANON_CSV)),
                   connections=all_conns)
    (DATA / 'connections_1024.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    (DATA / 'load_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],
                          failed=[c for c in report['checks'] if not c['passed']],
                          stats=stats), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
