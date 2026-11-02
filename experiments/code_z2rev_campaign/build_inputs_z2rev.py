# -*- coding: utf-8 -*-
"""Build campaign inputs for the REVISED Z2 CSV (user updated the Z2 export).

Z1: unchanged section-2 CSV (512 rows, row-1 convention) - used directly.
Z2: the new section-2 CSV is already C4-expanded (512 rows) but keeps the legacy
    row-1 port ids; we map every port to the same hole on row-2 (z=0.5 plane),
    verify the expanded set is the same 1024-port design (unique ports, relation
    counts, C4 closure), and write the row-2 table preserving the *new explicit
    source->target directions*.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402

OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
INPUTS = CAMPAIGN / 'inputs'
SRC_Z1 = ROOT / 'manual_z1_router/data/exports/manual_z1_c4_full_section2.csv'
SRC_Z2 = ROOT / 'manual_z1_router/data/exports/manual_z2_c4_full_section2.csv'
MANUAL_FIELDS = CONN.MANUAL_FIELDS


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    raw = Path(path).read_bytes()
    return raw, list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))


def row1_to_row2(eid):
    eps = CONN.endpoints()
    ep = eps[eid]
    conn = ep['connector']
    column = int(ep['column'])
    z2 = eps.get(f'{conn}:2:{column}')
    if z2 is None:
        raise KeyError(f'no row-2 endpoint for {eid}')
    return z2, f'{conn}:2:{column}'


def z2_row(route_id, se, te, sid, tid):
    relation = CONN._relation_of_sides(se['side'], te['side'])
    return dict(route_id=route_id,
                source_side=se['side'], source_connector=se['connector'],
                source_row=int(se['row']), source_column=int(se['column']),
                source_channel=int(se['channel']),
                target_side=te['side'], target_connector=te['connector'],
                target_row=int(te['row']), target_column=int(te['column']),
                target_channel=int(te['channel']),
                relation=relation,
                source_port_id=sid, target_port_id=tid,
                source_x_mm=float(se['routing_xy'][0]),
                source_y_mm=float(se['routing_xy'][1]),
                target_x_mm=float(te['routing_xy'][0]),
                target_y_mm=float(te['routing_xy'][1]),
                layer='z2')


def main():
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    INPUTS.mkdir(parents=True, exist_ok=True)
    (INPUTS / 'source').mkdir(exist_ok=True)
    report = dict(schema='new_manual_csv_campaign_inputs_z2rev_v1',
                  source_z1=dict(path=str(SRC_Z1), sha256=sha256(SRC_Z1)),
                  source_z2=dict(path=str(SRC_Z2), sha256=sha256(SRC_Z2)),
                  reference_old_campaign=str(OLD),
                  checks=[], steps=[])
    shutil.copyfile(SRC_Z1, INPUTS / 'source' / SRC_Z1.name)
    shutil.copyfile(SRC_Z2, INPUTS / 'source' / SRC_Z2.name)
    eps = CONN.endpoints()

    # ------------------------------------------------------------------ Z1
    raw1, rows1 = read_rows(SRC_Z1)
    z1_ids = [int(row['route_id']) for row in rows1]
    report['checks'].append(dict(name='z1 route_id 1..512 unique',
                                 passed=sorted(z1_ids) == list(range(1, 513)),
                                 detail=len(z1_ids)))
    usage1 = Counter()
    for row in rows1:
        for role in ('source', 'target'):
            usage1[row[f'{role}_port_id']] += 1
    z1_ports = {eid for eid, ep in eps.items() if ep['plane'] == 'z1'}
    report['checks'].append(dict(
        name='z1 uses all 1024 z1 ports exactly once',
        passed=(len(usage1) == 1024 and set(usage1.values()) == {1}
                and set(usage1) == z1_ports),
        detail=dict(unique=len(usage1),
                    missing=len(z1_ports - set(usage1)))))
    shutil.copyfile(SRC_Z1, INPUTS / 'manual_z1_c4_full_section2.csv')
    report['z1'] = dict(sha256=sha256(SRC_Z1), rows=len(rows1),
                        relations=dict(Counter(row['relation']
                                               for row in rows1)))

    # ------------------------------------------------------------------ Z2
    raw2, rows2 = read_rows(SRC_Z2)
    report['steps'].append(dict(step='z2_read', rows=len(rows2),
                                sha256=sha256(SRC_Z2)))
    report['checks'].append(dict(
        name='z2 revised CSV is already C4-expanded (512 rows)',
        passed=len(rows2) == 512, detail=len(rows2)))
    z2_rows = []
    problems = []
    usage2 = Counter()
    for row in rows2:
        try:
            se, sid = row1_to_row2(row['source_port_id'])
            te, tid = row1_to_row2(row['target_port_id'])
        except KeyError as exc:
            problems.append((row.get('route_id'), repr(exc)))
            continue
        if se['plane'] != 'z2' or te['plane'] != 'z2':
            problems.append((row['route_id'], 'not z2 plane'))
            continue
        usage2[sid] += 1
        usage2[tid] += 1
        # keep the user's explicit direction; validate metadata/xy consistency
        for role, ep, eid in (('source', se, sid), ('target', te, tid)):
            if ep['connector'] != row[f'{role}_connector'] or \
                    int(ep['column']) != int(row[f'{role}_column']):
                problems.append((row['route_id'], role, 'metadata', eid))
        z2_rows.append(z2_row(int(row['route_id']), se, te, sid, tid))
    report['checks'].append(dict(name='z2 rows convert to row-2 ports',
                                 passed=not problems,
                                 detail=str(problems[:5])))
    z2_ports = {eid for eid, ep in eps.items() if ep['plane'] == 'z2'}
    report['checks'].append(dict(
        name='z2 uses all 1024 z2 ports exactly once',
        passed=(len(usage2) == 1024 and set(usage2.values()) == {1}
                and set(usage2) == z2_ports),
        detail=dict(unique=len(usage2),
                    missing=len(z2_ports - set(usage2)))))
    relations = Counter(row['relation'] for row in z2_rows)
    report['checks'].append(dict(
        name='z2 relation composition (adjacent 400 + same 112)',
        passed=(relations.get('adjacent') == 400
                and relations.get('same') == 112),
        detail=dict(relations)))
    # C4 closure on the undirected connection set
    rot = {eid: CONN.rot90_port(eid) for eid, ep in eps.items()
           if ep['plane'] == 'z2'}
    pairs = {tuple(sorted((row['source_port_id'], row['target_port_id'])))
             for row in z2_rows}
    closure = {}
    for step in (1, 2, 3):
        power = {}
        for eid in z2_ports:
            cur = eid
            for _ in range(step):
                cur = rot[cur]
            power[eid] = cur
        missing = [pair for pair in pairs
                   if tuple(sorted((power[pair[0]], power[pair[1]]))) not in pairs]
        closure[f'{step * 90}deg'] = len(missing)
    report['checks'].append(dict(
        name='z2 revised C4 closure (0 missing at 90/180/270)',
        passed=all(value == 0 for value in closure.values()),
        detail=closure))
    report['z2'] = dict(sha256=sha256(SRC_Z2), rows=len(z2_rows),
                        relations=dict(relations), closure=closure,
                        directions='explicit user source->target preserved')
    # write the row-2 z2 table preserving the new directions
    expanded_csv = INPUTS / 'manual_z2_c4_full_section2_expanded_row2.csv'
    with expanded_csv.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_FIELDS,
                                lineterminator='\r\n')
        writer.writeheader()
        for row in sorted(z2_rows, key=lambda item: item['route_id']):
            writer.writerow(row)
    report['z2']['expanded_csv'] = dict(path=str(expanded_csv),
                                        sha256=sha256(expanded_csv),
                                        rows=len(z2_rows))

    # ------------------------------------------------- strict combined build
    CONN.SRC_Z1 = SRC_Z1
    CONN.SRC_Z2 = expanded_csv
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = INPUTS
    CONN.COMBINED_CSV = INPUTS / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = INPUTS / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None
    topology = CONN.build_topology()
    validation = json.loads((INPUTS / 'input_validation.json').read_text(
        encoding='utf-8'))
    report['validation'] = dict(passed=validation['passed'],
                                checks=len(validation['checks']),
                                failed=[check for check in validation['checks']
                                        if not check['passed']])
    report['topology'] = dict(connections=topology['connections'],
                              groups=topology['group_count'],
                              relation_counts=topology['relation_counts'],
                              group_kinds=topology['group_kinds'],
                              rotation_closure=topology['rotation_closure'],
                              combined_csv=topology['combined_csv'])
    shutil.copyfile(SRC_Z2, INPUTS / 'manual_z2_c4_full_section2.csv')
    (CAMPAIGN / 'build_inputs_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report['validation'], ensure_ascii=False, indent=1))
    print(json.dumps(report['topology'], ensure_ascii=False, indent=1))
    print('z2 closure', closure, 'relations', dict(relations))


if __name__ == '__main__':
    main()
