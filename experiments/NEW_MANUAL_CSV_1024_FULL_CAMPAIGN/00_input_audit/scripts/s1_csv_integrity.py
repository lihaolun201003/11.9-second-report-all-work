# -*- coding: utf-8 -*-
"""Stage 1: integrity audit of the two new section-2 manual CSVs.

Produces ``csv_integrity.json`` under 00_input_audit/.
All facts are computed against the frozen port model of four_side_1024.fslw.ports.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import common as C  # noqa: E402

OUT = AUDIT / 'csv_integrity.json'


def counter_dict(counter):
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def audit_endpoint_columns(file_info, expected_plane):
    """Validate port ids / coordinates / metadata of one manual table."""
    eps = C.endpoints()
    rows = file_info['rows']
    report = dict(rows=len(rows), port_ids=dict(), coordinates=dict(),
                  metadata=dict(), port_id_column=dict(), relation=dict(),
                  duplicate_connections=0, usage=dict(), ranges=dict(),
                  row_distribution=dict(), layer=dict(), channel_convention=dict(),
                  side_distribution=dict(), pair_distribution=dict(),
                  field_parse_errors=[])
    usage = Counter()
    conns = Counter()
    missing, wrong_plane, port_id_errors = [], [], []
    metadata_errors, coord_errors = [], []
    max_err_x = max_err_y = 0.0
    relation_mismatch = 0
    xs, ys = [], []
    idset = set()
    rows_rel = Counter()
    sides = Counter()
    pairs = Counter()
    for row in rows:
        try:
            rid = int(row['route_id'])
        except (TypeError, ValueError) as exc:
            report['field_parse_errors'].append(dict(route_id=row.get('route_id'),
                                                     error=repr(exc)))
            continue
        rows_rel[row['relation']] += 1
        sides[row['source_side']] += 1
        pairs[C.side_pair(row['source_side'], row['target_side'])] += 1
        src = tgt = None
        for role in ('source', 'target'):
            eid = row[f'{role}_port_id']
            idset.add(eid)
            ep = eps.get(eid)
            if ep is None:
                missing.append(dict(route_id=rid, role=role, port_id=eid))
                continue
            if ep['plane'] != expected_plane:
                wrong_plane.append(dict(route_id=rid, role=role, port_id=eid,
                                        plane=ep['plane']))
            usage[eid] += 1
            built = C.ep_of(row, role)
            if built != eid:
                port_id_errors.append(dict(route_id=rid, role=role,
                                           port_id_column=eid, built=built))
            model = dict(side=ep['side'], connector=ep['connector'],
                         row=int(ep['row']), column=int(ep['column']),
                         channel=int(ep['channel']))
            for field in ('side', 'connector'):
                if str(model[field]) != row[f'{role}_{field}']:
                    metadata_errors.append(dict(route_id=rid, role=role,
                                                field=field,
                                                csv=row[f'{role}_{field}'],
                                                model=model[field]))
            for field in ('row', 'column', 'channel'):
                try:
                    value = int(row[f'{role}_{field}'])
                except (TypeError, ValueError) as exc:
                    report['field_parse_errors'].append(
                        dict(route_id=rid, role=role, field=field,
                             error=repr(exc)))
                    continue
                if value != model[field]:
                    metadata_errors.append(dict(route_id=rid, role=role,
                                                field=field, csv=value,
                                                model=model[field]))
            ex = float(ep['routing_xy'][0])
            ey = float(ep['routing_xy'][1])
            x = float(row[f'{role}_x_mm'])
            y = float(row[f'{role}_y_mm'])
            xs.append(x)
            ys.append(y)
            max_err_x = max(max_err_x, abs(x - ex))
            max_err_y = max(max_err_y, abs(y - ey))
            if abs(x - ex) > C.TOL or abs(y - ey) > C.TOL:
                coord_errors.append(dict(route_id=rid, role=role, port_id=eid,
                                         csv=[x, y], model=[ex, ey],
                                         error=max(abs(x - ex), abs(y - ey))))
            if role == 'source':
                src = eid
            else:
                tgt = eid
        if src is not None and tgt is not None:
            if C.canonical_connection(src, tgt) in conns:
                conns[C.canonical_connection(src, tgt)] += 1
            else:
                conns[C.canonical_connection(src, tgt)] = 1
            rel = C.relation_of_sides(row['source_side'], row['target_side'])
            if rel != row['relation']:
                relation_mismatch += 1
    report['port_ids'] = dict(
        count=len(idset), rows_checked=2 * len(rows),
        missing_from_model=len(missing), missing_sample=missing[:5],
        wrong_plane=len(wrong_plane), wrong_plane_sample=wrong_plane[:5])
    report['coordinates'] = dict(
        compared=2 * len(rows), tolerance_mm=C.TOL,
        max_abs_error_x_mm=max_err_x, max_abs_error_y_mm=max_err_y,
        max_abs_error_mm=max(max_err_x, max_err_y),
        over_tolerance=len(coord_errors),
        over_tolerance_sample=coord_errors[:5])
    report['metadata'] = dict(errors=len(metadata_errors),
                              sample=metadata_errors[:5])
    report['port_id_column'] = dict(mismatches=len(port_id_errors),
                                    sample=port_id_errors[:5])
    report['relation'] = dict(field_counts=counter_dict(rows_rel),
                              consistent_with_sides_mismatches=relation_mismatch)
    report['duplicate_connections'] = sum(1 for v in conns.values() if v > 1)
    report['usage'] = dict(unique=len(usage),
                           max_use=max(usage.values()) if usage else 0,
                           used_once=bool(usage) and set(usage.values()) == {1},
                           duplicated=sum(1 for v in usage.values() if v > 1),
                           side_distribution=counter_dict(
                               Counter(eps[e]['side'] for e in usage)))
    report['ranges'] = dict(
        x_min=min(xs) if xs else None, x_max=max(xs) if xs else None,
        y_min=min(ys) if ys else None, y_max=max(ys) if ys else None,
        inside_board=bool(xs) and all(0.0 <= v <= C.BOARD_MM for v in xs + ys),
        unique_xy=len({(round(x, 6), round(y, 6)) for x, y in zip(xs, ys)}))
    report['layer'] = counter_dict(Counter(row['layer'] for row in rows))
    report['row_distribution'] = dict(
        source_rows=counter_dict(Counter(row['source_row'] for row in rows)),
        target_rows=counter_dict(Counter(row['target_row'] for row in rows)))
    report['channel_convention'] = dict(
        channel_equals_column=all(int(row[f'{role}_channel']) ==
                                  int(row[f'{role}_column'])
                                  for row in rows for role in ('source', 'target')),
        channel_equals_16_plus_column=all(int(row[f'{role}_channel']) ==
                                          16 + int(row[f'{role}_column'])
                                          for row in rows for role in ('source', 'target')))
    report['side_distribution'] = dict(source=counter_dict(sides),
                                       target=counter_dict(
                                           Counter(row['target_side'] for row in rows)))
    report['pair_distribution'] = counter_dict(pairs)
    report['endpoint_ids'] = dict(
        unique=len(idset), sample=sorted(idset)[:3],
        min=sorted(idset)[0] if idset else None,
        max=sorted(idset)[-1] if idset else None)
    return report


def file_facts(path):
    info = C.read_manual_csv(path)
    facts = dict(path=info['path'], sha256=info['sha256'], bytes=info['bytes'],
                 rows=len(info['rows']), bom=info['bom'],
                 crlf_only=info['crlf_only'], line_count=info['line_count'],
                 data_lines=info['data_lines'], header=info['header'],
                 header_ok=info['header'] == C.MANUAL_FIELDS,
                 columns=len(info['header']))
    return facts, info


def main():
    eps = C.endpoints()
    payload = dict(
        schema='new_manual_csv_input_audit_csv_integrity_v1',
        title='Integrity audit of the two new section-2 manual connectivity CSVs',
        board_mm=C.BOARD_MM,
        tolerance_mm=C.TOL,
        port_model=dict(
            name='real_2x16_dual_height (IEC 61754-7-3:2019 2x16 MPO)',
            source_module='four_side_1024.fslw.ports.build_plane_endpoints',
            endpoints=len(eps), connectors=64, rows=2, columns=16,
            holes_per_connector=32, ports_per_plane=1024,
            connector_pitch_mm=9.0, column_pitch_mm=0.25, row_pitch_mm=0.5,
            z_mm={'z1': 0.0, 'z2': 0.5}),
        inputs=dict(
            z1_new=dict(path=str(C.Z1_NEW), sha256=C.sha256_file(C.Z1_NEW)),
            z2_new=dict(path=str(C.Z2_NEW), sha256=C.sha256_file(C.Z2_NEW)),
            old=dict(z1=dict(path=str(C.Z1_OLD), sha256=C.sha256_file(C.Z1_OLD)),
                     z2=dict(path=str(C.Z2_OLD), sha256=C.sha256_file(C.Z2_OLD)),
                     z1_campaign=dict(path=str(C.Z1_OLD_CAMPAIGN),
                                      sha256=C.sha256_file(C.Z1_OLD_CAMPAIGN)),
                     z2_campaign=dict(path=str(C.Z2_OLD_CAMPAIGN),
                                      sha256=C.sha256_file(C.Z2_OLD_CAMPAIGN)),
                     combined_campaign=dict(path=str(C.OLD_COMBINED),
                                            sha256=C.sha256_file(C.OLD_COMBINED)))),
        checks=[],
    )

    def check(cid, section, name, passed, detail=None, severity='error'):
        entry = dict(id=cid, section=section, name=name, passed=bool(passed),
                     severity=severity)
        if detail is not None:
            entry['detail'] = detail
        payload['checks'].append(entry)
        return entry

    # ---------------------------------------------------------------- Z1
    z1_facts, z1_info = file_facts(C.Z1_NEW)
    payload['files'] = dict(z1=z1_facts)
    payload['z1'] = audit_endpoint_columns(z1_info, 'z1')
    z1 = payload['z1']
    z1_rows = z1_info['rows']
    route_ids = sorted(int(row['route_id']) for row in z1_rows)
    check('z1-01', 'z1', 'file exists and is readable', True, z1_facts['path'])
    check('z1-02', 'z1', 'header = 19-column manual schema',
          z1_facts['header_ok'], z1_facts['header'])
    check('z1-03', 'z1', 'UTF-8 BOM present', z1_facts['bom'])
    check('z1-04', 'z1', 'CRLF-only line endings', z1_facts['crlf_only'],
          dict(line_count=z1_facts['line_count']))
    check('z1-05', 'z1', '512 data rows', z1_facts['rows'] == 512, z1_facts['rows'])
    check('z1-06', 'z1', 'route_id = 1..512 exactly once',
          route_ids == list(range(1, 513)),
          dict(count=len(route_ids), min=min(route_ids), max=max(route_ids),
               unique=len(set(route_ids))))
    check('z1-07', 'z1', "layer tag = 'z1' on every row",
          set(z1['layer']) == {'z1'}, z1['layer'])
    check('z1-08', 'z1', 'all source_row and target_row = 1',
          set(z1['row_distribution']['source_rows']) == {'1'} and
          set(z1['row_distribution']['target_rows']) == {'1'},
          z1['row_distribution'])
    check('z1-09', 'z1', 'channel = column (row-1 IEC convention)',
          z1['channel_convention']['channel_equals_column'], z1['channel_convention'])
    check('z1-10', 'z1', 'all port ids exist in the frozen 2048-port model',
          z1['port_ids']['missing_from_model'] == 0, z1['port_ids'])
    check('z1-11', 'z1', 'every port id belongs to plane z1',
          z1['port_ids']['wrong_plane'] == 0,
          dict(wrong_plane=z1['port_ids']['wrong_plane']))
    check('z1-12', 'z1', 'port_id column equals connector:row:column columns',
          z1['port_id_column']['mismatches'] == 0, z1['port_id_column'])
    check('z1-13', 'z1', 'side/connector/row/column/channel match the port model',
          z1['metadata']['errors'] == 0, z1['metadata'])
    check('z1-14', 'z1', 'x/y coordinates match the port model within 1e-9 mm',
          z1['coordinates']['over_tolerance'] == 0, z1['coordinates'])
    check('z1-15', 'z1', 'relation field consistent with the two sides',
          z1['relation']['consistent_with_sides_mismatches'] == 0, z1['relation'])
    check('z1-16', 'z1', 'no duplicate unordered connection',
          z1['duplicate_connections'] == 0,
          dict(duplicate_connections=z1['duplicate_connections']))
    z1_used = {C.ep_of(row, role) for row in z1_rows for role in ('source', 'target')}
    z1_plane_ports = C.plane_ports('z1')
    check('z1-17', 'z1', '1024 endpoints used exactly once = full z1 port set',
          z1['usage']['unique'] == 1024 and z1['usage']['used_once'] and
          z1_used == z1_plane_ports,
          dict(unique=z1['usage']['unique'],
               missing=len(z1_plane_ports - z1_used),
               extra=len(z1_used - z1_plane_ports)))
    check('z1-18', 'z1', 'all coordinates inside the 150x150 mm board',
          z1['ranges']['inside_board'], z1['ranges'])
    payload['z1']['rotation_analysis'] = C.rotation_analysis(
        [(C.ep_of(row, 'source'), C.ep_of(row, 'target')) for row in z1_rows])
    rot1 = payload['z1']['rotation_analysis']
    check('z1-19', 'z1', '512 connections form 128 strict C4 orbits of size 4',
          rot1['closure_missing']['90deg'] == 0 and
          rot1['closure_missing']['180deg'] == 0 and
          rot1['closure_missing']['270deg'] == 0 and
          rot1['orbit_size_histogram'] == {'4': 128},
          dict(closure_missing=rot1['closure_missing'],
               orbit_size_histogram=rot1['orbit_size_histogram'],
               orbit_relations=rot1['orbit_relations']))
    check('z1-20', 'z1', 'relation counts = opposite 256 / same 256',
          z1['relation']['field_counts'] == {'opposite': 256, 'same': 256},
          z1['relation']['field_counts'])
    check('z1-21', 'z1', 'used endpoints are balanced 256 per board side',
          z1['usage']['side_distribution'] == {'N': 256, 'E': 256, 'S': 256,
                                              'W': 256},
          z1['usage']['side_distribution'])

    # ---------------------------------------------------------------- Z2 base
    z2_facts, z2_info = file_facts(C.Z2_NEW)
    payload['files']['z2'] = z2_facts
    payload['z2_base'] = audit_endpoint_columns(z2_info, 'z1')
    z2 = payload['z2_base']
    z2_rows = z2_info['rows']
    z2_ids = sorted(int(row['route_id']) for row in z2_rows)
    check('z2-01', 'z2_base', 'file exists and is readable', True, z2_facts['path'])
    check('z2-02', 'z2_base', 'header = 19-column manual schema',
          z2_facts['header_ok'], z2_facts['header'])
    check('z2-03', 'z2_base', 'UTF-8 BOM present', z2_facts['bom'])
    check('z2-04', 'z2_base', 'CRLF-only line endings', z2_facts['crlf_only'])
    check('z2-05', 'z2_base', '128 data rows (= 512 / 4 C4 base connections)',
          z2_facts['rows'] == 128, z2_facts['rows'])
    check('z2-06', 'z2_base', 'route_id unique (legacy, non-contiguous ids)',
          len(set(z2_ids)) == 128,
          dict(count=len(z2_ids), min=min(z2_ids), max=max(z2_ids),
               contiguous_minus_1=z2_ids == list(range(1, 129))))
    check('z2-07', 'z2_base', 'raw port ids exist in the 2048-port model',
          z2['port_ids']['missing_from_model'] == 0, z2['port_ids'])
    check('z2-08', 'z2_base',
          'raw ids/labels are internally consistent with the legacy row-1/z1 convention',
          z2['port_ids']['wrong_plane'] == 0 and set(z2['layer']) == {'z1'} and
          set(z2['row_distribution']['source_rows']) == {'1'} and
          set(z2['row_distribution']['target_rows']) == {'1'} and
          z2['channel_convention']['channel_equals_column'] and
          z2['port_id_column']['mismatches'] == 0,
          dict(plane_of_ids='z1', layer=z2['layer'],
               rows=z2['row_distribution'],
               channel_equals_column=z2['channel_convention']['channel_equals_column']))
    check('z2-09', 'z2_base', 'metadata match the port model',
          z2['metadata']['errors'] == 0, z2['metadata'])
    check('z2-10', 'z2_base', 'x/y coordinates match the port model within 1e-9 mm',
          z2['coordinates']['over_tolerance'] == 0, z2['coordinates'])
    check('z2-11', 'z2_base', 'relation field consistent with the two sides',
          z2['relation']['consistent_with_sides_mismatches'] == 0, z2['relation'])
    check('z2-12', 'z2_base', 'no duplicate unordered connection',
          z2['duplicate_connections'] == 0,
          dict(duplicate_connections=z2['duplicate_connections']))
    check('z2-13', 'z2_base', '256 endpoints used exactly once (1/4 base set)',
          z2['usage']['unique'] == 256 and z2['usage']['used_once'], z2['usage'])
    check('z2-14', 'z2_base', 'all coordinates inside the 150x150 mm board',
          z2['ranges']['inside_board'], z2['ranges'])
    check('z2-15', 'z2_base', 'relation counts = adjacent 100 / same 28 as stated',
          z2['relation']['field_counts'] == {'adjacent': 100, 'same': 28},
          z2['relation']['field_counts'])
    z2_used = {C.ep_of(row, role) for row in z2_rows for role in ('source', 'target')}
    check('z2-16', 'z2_base',
          "legacy label: layer='z1'/row=1/channel=1..16 are row-1 ids while the "
          "campaign plane is z2 (row 2), so a documented remap is required",
          True,
          dict(legacy_layer=z2['layer'], legacy_rows=z2['row_distribution'],
               note='not an error: the ids are consistent among themselves; '
                    'the remap is validated in z2_c4_expansion.json'),
          severity='warning')
    check('z2-17', 'z2_base',
          'raw row-1 ids of Z1 and Z2 share the same identity space (would collide '
          'if used without the row-1 -> row-2 remap)', True,
          dict(overlap=len(z1_used & z2_used)), severity='warning')

    # ---------------------------------------------------------------- inventory
    payload['old_files_inventory'] = {}
    for key, path in (('z1_old_export', C.Z1_OLD), ('z2_old_export', C.Z2_OLD),
                      ('z1_old_campaign', C.Z1_OLD_CAMPAIGN),
                      ('z2_old_campaign', C.Z2_OLD_CAMPAIGN)):
        info = C.read_manual_csv(path)
        payload['old_files_inventory'][key] = dict(
            path=str(path), sha256=info['sha256'], bytes=info['bytes'],
            rows=len(info['rows']),
            relations=counter_dict(Counter(r['relation'] for r in info['rows'])),
            layers=counter_dict(Counter(r['layer'] for r in info['rows'])),
            source_rows=counter_dict(Counter(r['source_row'] for r in info['rows'])))
    payload['old_combined_inventory'] = dict(
        path=str(C.OLD_COMBINED), sha256=C.sha256_file(C.OLD_COMBINED),
        header=C.read_plain_csv(C.OLD_COMBINED)['header'])

    # ---------------------------------------------------------------- verdict
    errors = [c for c in payload['checks'] if c['severity'] == 'error'
              and not c['passed']]
    warnings = [c for c in payload['checks'] if c['severity'] == 'warning']
    payload['verdict'] = dict(
        errors=len(errors), error_ids=[c['id'] for c in errors],
        warnings=[dict(id=c['id'], note=c.get('detail')) for c in warnings],
        passed=len(errors) == 0)
    C.write_json(OUT, payload)
    print(json.dumps(dict(
        out=str(OUT), checks=len(payload['checks']), errors=len(errors),
        warnings=len(warnings),
        z1_relations=z1['relation']['field_counts'],
        z1_rotation=z1['rotation_analysis']['orbit_size_histogram'],
        z2_relations=z2['relation']['field_counts'],
        z1_max_xy_error=z1['coordinates']['max_abs_error_mm'],
        z2_max_xy_error=z2['coordinates']['max_abs_error_mm']),
        ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
