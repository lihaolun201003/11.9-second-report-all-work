# -*- coding: utf-8 -*-
"""Build the new-manual-CSV campaign inputs (connectivity 1024) for section-2 CSVs.

Z1: section-2 CSV (512 rows, z1/row-1 convention) is used directly.
Z2: section-2 CSV (128 quad-base rows, legacy z1 port ids) is first converted to the
    z2 row-2 ports, then expanded by the real C4 rotation (90/180/270 about (75,75))
    into 512 connections with unique endpoints.
The resulting combined topology is validated with the frozen manual_c4 connectivity
validator (256 C4 groups, 2048 ports used once, relation consistency, C4 closure).
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

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
INPUTS = CAMPAIGN / 'inputs'
SRC_Z1 = ROOT / 'manual_z1_router/data/exports/manual_z1_c4_full_section2.csv'
SRC_Z2 = ROOT / 'manual_z1_router/data/exports/manual_z2_c4_full_section2.csv'
MANUAL_FIELDS = CONN.MANUAL_FIELDS


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    raw = Path(path).read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    return raw, rows


def endpoint_xy(eid):
    eps = CONN.endpoints()
    return tuple(eps[eid]['routing_xy'])


def row1_to_row2(eid):
    """Map a legacy row-1 (z1) port id to the same hole of the z2 row-2 plane."""
    eps = CONN.endpoints()
    ep = eps[eid]
    conn = ep['connector']
    column = int(ep['column'])
    z2 = eps.get(f'{conn}:2:{column}')
    if z2 is None:
        raise KeyError(f'no row-2 endpoint for {eid}')
    return z2['plane'], z2, f'{conn}:2:{column}'


def z2_row_from_expanded(route_id, source_eid, target_eid):
    eps = CONN.endpoints()
    se, te = eps[source_eid], eps[target_eid]
    relation = CONN._relation_of_sides(se['side'], te['side'])
    return dict(route_id=route_id,
                source_side=se['side'], source_connector=se['connector'],
                source_row=int(se['row']), source_column=int(se['column']),
                source_channel=int(se['channel']),
                target_side=te['side'], target_connector=te['connector'],
                target_row=int(te['row']), target_column=int(te['column']),
                target_channel=int(te['channel']),
                relation=relation,
                source_port_id=source_eid, target_port_id=target_eid,
                source_x_mm=float(se['routing_xy'][0]),
                source_y_mm=float(se['routing_xy'][1]),
                target_x_mm=float(te['routing_xy'][0]),
                target_y_mm=float(te['routing_xy'][1]),
                layer='z2')


def main():
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    INPUTS.mkdir(parents=True, exist_ok=True)
    (INPUTS / 'source').mkdir(exist_ok=True)
    report = dict(schema='new_manual_csv_campaign_inputs_v1',
                  source_z1=dict(path=str(SRC_Z1), sha256=sha256(SRC_Z1)),
                  source_z2=dict(path=str(SRC_Z2), sha256=sha256(SRC_Z2)),
                  steps=[], checks=[])
    report['local_versions'] = dict(
        note='local section-2 exports are the authoritative source for this campaign')

    # copy original sources (byte-exact)
    shutil.copyfile(SRC_Z1, INPUTS / 'source' / SRC_Z1.name)
    shutil.copyfile(SRC_Z2, INPUTS / 'source' / SRC_Z2.name)

    eps = CONN.endpoints()
    # ------------------------------------------------------------------ Z1
    raw1, rows1 = read_rows(SRC_Z1)
    z1_info = dict(path=str(SRC_Z1), sha256=sha256(SRC_Z1), bytes=len(raw1),
                   rows=len(rows1), bom=raw1[:3] == b'\xef\xbb\xbf',
                   header=list(rows1[0].keys()) if rows1 else [])
    report['steps'].append(dict(step='z1_read', rows=len(rows1)))
    z1_ids = [int(r['route_id']) for r in rows1]
    report['checks'].append(dict(name='z1 route_id 1..512 unique',
                                 passed=sorted(z1_ids) == list(range(1, 513)),
                                 detail=len(z1_ids)))
    usage1 = Counter()
    bad = []
    for r in rows1:
        rid = int(r['route_id'])
        if int(r['source_row']) != 1 or int(r['target_row']) != 1:
            bad.append((rid, 'row', r['source_row'], r['target_row']))
            continue
        for role in ('source', 'target'):
            eid = r[f'{role}_port_id']
            ep = eps.get(eid)
            if ep is None or ep['plane'] != 'z1':
                bad.append((rid, role, 'bad port', eid))
                continue
            usage1[eid] += 1
            if ep['connector'] != r[f'{role}_connector'] or \
                    int(ep['column']) != int(r[f'{role}_column']) or \
                    int(ep['channel']) != int(r[f'{role}_channel']) or \
                    ep['side'] != r[f'{role}_side']:
                bad.append((rid, role, 'metadata mismatch', eid))
            x, y = float(r[f'{role}_x_mm']), float(r[f'{role}_y_mm'])
            ex, ey = ep['routing_xy']
            if abs(x - ex) > 1e-9 or abs(y - ey) > 1e-9:
                bad.append((rid, role, 'xy mismatch', eid))
        rel = CONN._relation_of_sides(r['source_side'], r['target_side'])
        if rel != r['relation']:
            bad.append((rid, 'relation', r['relation'], rel))
    report['checks'].append(dict(name='z1 row/port/metadata/xy/relation consistent',
                                 passed=not bad, detail=str(bad[:5])))
    z1_ports = {eid for eid, ep in eps.items() if ep['plane'] == 'z1'}
    report['checks'].append(dict(
        name='z1 uses all 1024 z1 ports exactly once',
        passed=(len(usage1) == 1024 and set(usage1.values()) == {1}
                and set(usage1) == z1_ports),
        detail=dict(unique=len(usage1), dup=sum(1 for v in usage1.values() if v > 1),
                    missing=len(z1_ports - set(usage1)))))
    z1_relations = Counter(r['relation'] for r in rows1)
    report['steps'].append(dict(step='z1_stats', rows=len(rows1),
                                relations=dict(z1_relations)))
    report['z1'] = dict(info=z1_info, relations=dict(z1_relations),
                        endpoints_unique=len({e for r in rows1
                                              for e in (r['source_port_id'],
                                                        r['target_port_id'])}))
    # write z1 manual table for the strict validator (same bytes)
    shutil.copyfile(SRC_Z1, INPUTS / 'manual_z1_c4_full_section2.csv')

    # ------------------------------------------------------------------ Z2
    raw2, rows2 = read_rows(SRC_Z2)
    z2_info = dict(path=str(SRC_Z2), sha256=sha256(SRC_Z2), bytes=len(raw2),
                   rows=len(rows2), bom=raw2[:3] == b'\xef\xbb\xbf',
                   header=list(rows2[0].keys()) if rows2 else [])
    report['steps'].append(dict(step='z2_read', rows=len(rows2)))
    base_relations = Counter(r['relation'] for r in rows2)
    report['z2'] = dict(info=z2_info, base_rows=len(rows2),
                        base_relations=dict(base_relations))
    # convert each base row to row-2 z2 ports
    base_pairs = []
    convert_problems = []
    for r in rows2:
        try:
            plane_s, ep_s, eid_s = row1_to_row2(r['source_port_id'])
            plane_t, ep_t, eid_t = row1_to_row2(r['target_port_id'])
        except KeyError as exc:
            convert_problems.append((r['route_id'], repr(exc)))
            continue
        base_pairs.append((int(r['route_id']), ep_s, ep_t, eid_s, eid_t))
    report['checks'].append(dict(name='z2 base rows convert to row-2 ports',
                                 passed=not convert_problems,
                                 detail=str(convert_problems[:5])))
    # C4 expansion with the real rotation on z2 endpoints
    rot = {eid: CONN.rot90_port(eid) for eid, ep in eps.items()
           if ep['plane'] == 'z2'}
    expanded = {}
    duplicates_within = []
    for base_id, se, te, sid, tid in base_pairs:
        cur = (sid, tid)
        orbit = set()
        for k in range(4):
            key = frozenset(cur)
            if key in orbit:
                duplicates_within.append((base_id, k))
            orbit.add(key)
            cur = (rot[cur[0]], rot[cur[1]])
        for key in orbit:
            if key in expanded:
                raise ValueError(f'duplicate expanded connection {sorted(key)}')
            expanded[key] = dict(base_id=base_id, source=sorted(key)[0],
                                 target=sorted(key)[1])
    report['steps'].append(dict(step='z2_c4_expansion',
                                base=len(base_pairs), expanded=len(expanded)))
    z2_ports_used = Counter()
    for cell in expanded.values():
        z2_ports_used[cell['source']] += 1
        z2_ports_used[cell['target']] += 1
    z2_ports = {eid for eid, ep in eps.items() if ep['plane'] == 'z2'}
    report['checks'].append(dict(
        name='z2 expanded = 512 connections, all 1024 z2 ports once',
        passed=(len(expanded) == 512 and len(z2_ports_used) == 1024
                and set(z2_ports_used.values()) == {1}
                and set(z2_ports_used) == z2_ports),
        detail=dict(expanded=len(expanded), ports=len(z2_ports_used),
                    missing=len(z2_ports - set(z2_ports_used)))))
    # rotation closure of the expanded set (should be exact)
    closure = dict()
    pairs = {tuple(sorted((c['source'], c['target']))) for c in expanded.values()}
    for step in (1, 2, 3):
        power = {}
        for eid in z2_ports:
            cur = eid
            for _ in range(step):
                cur = rot[cur]
            power[eid] = cur
        missing = [p for p in pairs
                   if tuple(sorted((power[p[0]], power[p[1]]))) not in pairs]
        closure[f'{step * 90}deg'] = len(missing)
    report['checks'].append(dict(name='z2 expanded C4 closure (0 missing at 90/180/270)',
                                 passed=all(v == 0 for v in closure.values()),
                                 detail=closure))
    report['z2'].update(expanded=len(expanded), closure=closure,
                        relations=dict(Counter(
                            CONN._relation_of_sides(eps[c['source']]['side'],
                                                    eps[c['target']]['side'])
                            for c in expanded.values())))
    # write the expanded 512-row z2 manual table (row-2 convention, 19 columns)
    expanded_rows = []
    ordered = sorted(expanded.values(), key=lambda c: (c['base_id'],
                                                       c['source'], c['target']))
    for index, cell in enumerate(ordered, start=1):
        expanded_rows.append(z2_row_from_expanded(index, cell['source'],
                                                  cell['target']))
    expanded_csv = INPUTS / 'manual_z2_c4_full_section2_expanded_row2.csv'
    with expanded_csv.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_FIELDS,
                                lineterminator='\r\n')
        writer.writeheader()
        for row in expanded_rows:
            writer.writerow(row)
    report['z2']['expanded_csv'] = dict(path=str(expanded_csv),
                                        sha256=sha256(expanded_csv),
                                        rows=len(expanded_rows))

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
                                failed=[c for c in validation['checks']
                                        if not c['passed']])
    report['topology'] = dict(connections=topology['connections'],
                              groups=topology['group_count'],
                              relation_counts=topology['relation_counts'],
                              group_kinds=topology['group_kinds'],
                              rotation_closure=topology['rotation_closure'],
                              combined_csv=topology['combined_csv'])
    # keep the original section-2 z2 file name for the archive
    shutil.copyfile(SRC_Z2, INPUTS / 'manual_z2_c4_full_section2.csv')
    (CAMPAIGN / 'build_inputs_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report['validation'], ensure_ascii=False))
    print(json.dumps(report['topology'], ensure_ascii=False))
    return report


if __name__ == '__main__':
    main()
