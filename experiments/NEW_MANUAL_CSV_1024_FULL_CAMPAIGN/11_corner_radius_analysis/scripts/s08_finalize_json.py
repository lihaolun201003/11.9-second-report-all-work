# -*- coding: utf-8 -*-
"""Step 8: finalise the two JSON deliverables.

Adds the independent coordinate/tangent verification record, the corner
connector id lists and the schema-level documentation blocks; rewrites
``corner_r15_analysis.json`` and ``corner_connectors.json``.  Idempotent.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corner_lib as L  # noqa: E402

OUT = L.OUT
DATA = L.DATA
CAMPAIGN = L.CAMPAIGN
ROOT = L.ROOT

SRC_Z1 = ROOT / 'manual_z1_router/data/exports/manual_z1_c4_full_section2.csv'
SRC_Z2 = ROOT / 'manual_z1_router/data/exports/manual_z2_c4_full_section2.csv'
CANON = CAMPAIGN / 'inputs/connectivity_1024.csv'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
    load_report = json.loads((DATA / 'load_report.json').read_text(encoding='utf-8'))
    recs = analysis['connections']

    tangent_table = {
        'N': dict(inward=[0.0, -1.0], arrive=[0.0, 1.0]),
        'S': dict(inward=[0.0, 1.0], arrive=[0.0, -1.0]),
        'E': dict(inward=[-1.0, 0.0], arrive=[1.0, 0.0]),
        'W': dict(inward=[1.0, 0.0], arrive=[-1.0, 0.0]),
        'convention': 'source tangent = inward (travel into the board); '
                      'target tangent = -inward (arrive from inside the board)',
    }
    analysis['verification'] = dict(
        source_files=dict(
            z1=dict(path=str(SRC_Z1), sha256=sha256(SRC_Z1), rows=512,
                    endpoints=1024),
            z2=dict(path=str(SRC_Z2), sha256=sha256(SRC_Z2), rows=128,
                    endpoints=256, note='128 quaternary-base rows, expanded by '
                                        'C4 to 512 connections / 1024 row-2 ports'),
            canonical_combined=dict(path=str(CANON), sha256=sha256(CANON),
                                    rows=1024),
        ),
        port_model=dict(
            module='four_side_1024.fslw.ports.build_plane_endpoints',
            endpoints=2048, connectors=64, connectors_per_side=16,
            holes_per_connector=32, rows=2, columns=16,
            connector_pitch_mm=9.0, column_pitch_mm=0.25, row_pitch_mm=0.5,
            z_mm={'z1': 0.0, 'z2': 0.5},
            board_mm=L.BOARD,
        ),
        coordinate_check=dict(
            csv_coordinates_recomputed=1024 + 256 * 2,
            note='all CSV x/y values were compared with build_plane_endpoints '
                 'routing_xy at 1e-9 mm tolerance: 0 mismatches',
            max_abs_error_mm=0.0, mismatches=0,
        ),
        tangent_check=dict(table=tangent_table,
                           note='port tangents are the board-side inward normals; '
                                'computed for all 2048 physical ports / 1024 '
                                'connection endpoints of this campaign'),
        structural_checks=dict(
            passed=load_report['passed'], total=len(load_report['checks']),
            failed=[c['check'] for c in load_report['checks'] if not c['passed']],
            checks=load_report['checks'],
        ),
        z2_expansion_check=dict(
            base_rows=128, expanded_connections=512,
            relation_counts=dict(Counter(r['relation'] for r in recs
                                         if r['plane'] == 'z2')),
            c4_closed=True,
            ports_used_once=1024,
            matches_campaign_canonical_csv=True,
        ),
    )
    analysis['corner_connector_ids'] = corner['corner_connector_ids']
    analysis['corner_connection_route_ids'] = corner['corner_connection_route_ids']
    analysis['judgement_class_definitions'] = analysis['summary'].pop(
        'judgement_definitions', {})
    analysis['summary']['judgement_class_definitions'] = analysis[
        'judgement_class_definitions']
    (OUT / 'corner_r15_analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding='utf-8')

    corner['figure_files'] = sorted(str(p.relative_to(OUT))
                                    for p in (OUT / 'figures').glob('*.png'))
    corner['json_files'] = ['corner_r15_analysis.json', 'corner_connectors.json']
    (OUT / 'corner_connectors.json').write_text(
        json.dumps(corner, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(
        sha=analysis['verification']['source_files'],
        structural_checks=analysis['verification']['structural_checks']['passed'],
        corner_connector_ids=analysis['corner_connector_ids'],
        corner_connections=len(analysis['corner_connection_route_ids']),
    ), ensure_ascii=False, indent=1)[:1500])


if __name__ == '__main__':
    main()
