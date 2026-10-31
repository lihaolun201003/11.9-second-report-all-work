# -*- coding: utf-8 -*-
"""Step 9: final self-check of the delivered JSON/figures.

Recomputes the essential quantities from the port model and the raw CSVs and
asserts they agree with the two delivered JSONs + report-critical numbers.
Writes data/verification_final.json.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corner_lib as L  # noqa: E402

OUT = L.OUT
DATA = L.DATA
FIG = OUT / 'figures'

failures = []
checks = []


def check(name, ok, detail=''):
    checks.append(dict(check=name, passed=bool(ok), detail=detail))
    if not ok:
        failures.append(name)


def main():
    eps = L.load_endpoints()
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
    recs = analysis['connections']
    by_id = {r['route_id']: r for r in recs}

    check('analysis has 1024 connections', len(recs) == 1024, len(recs))
    check('route ids are 1..1024', sorted(by_id) == list(range(1, 1025)))
    check('all 1024 templates feasible at R=15',
          all(r['template']['feasible'] for r in recs),
          sum(1 for r in recs if not r['template']['feasible']))
    # per-relation formulas re-checked from the port model
    bad = 0
    for r in recs:
        sp, tp = eps[r['source_port_id']], eps[r['target_port_id']]
        sx, sy = (float(v) for v in sp['routing_xy'])
        tx, ty = (float(v) for v in tp['routing_xy'])
        if r['relation'] == 'same':
            d = abs(sx - tx) if sp['side'] in 'NS' else abs(sy - ty)
            if abs(r['same']['separation_D_mm'] - d) > 1e-9:
                bad += 1
            if abs(r['same']['middle_straight_mm'] - (d - 30.0)) > 1e-9:
                bad += 1
        elif r['relation'] == 'adjacent':
            corners = {frozenset('NE'): (150., 150.), frozenset('ES'): (150., 0.),
                       frozenset('SW'): (0., 0.), frozenset('WN'): (0., 150.)}
            cx, cy = corners[frozenset((sp['side'], tp['side']))]
            da = abs(sx - cx) if sp['side'] in 'NS' else abs(sy - cy)
            db = abs(tx - cx) if tp['side'] in 'NS' else abs(ty - cy)
            if abs(r['adjacent']['a_source_to_corner_mm'] - da) > 1e-9:
                bad += 1
            if abs(r['adjacent']['b_target_to_corner_mm'] - db) > 1e-9:
                bad += 1
            if abs(r['adjacent']['min_leg_mm'] - (min(da, db) - 15.0)) > 1e-9:
                bad += 1
        else:
            delta = abs(sx - tx) if sp['side'] in 'NS' else abs(sy - ty)
            if abs(r['opposite']['delta_mm'] - delta) > 1e-9:
                bad += 1
            regime = r['opposite']['regime']
            if delta < 1e-9 and regime != 'straight':
                bad += 1
            if 1e-9 < delta < 30 - 1e-9 and regime != 'short_s_pair':
                bad += 1
            if delta >= 30 - 1e-9 and regime != 'quarter_arc_pair':
                bad += 1
    check('per-connection geometric quantities re-derived formula-consistent',
          bad == 0, bad)

    classes = Counter(r['judgement']['class_'] for r in recs)
    expected = {'radius_limited_2d': 0, 'pure90_template_limited': 144,
                'same_u_family_capacity_limited': 368,
                'rigid_template_conflict': 240,
                'conflict_needs_joint_search': 224, 'lift_limited': 4,
                'not_limited': 44}
    check('global judgement class counts match the report',
          {k: classes.get(k, 0) for k in expected} == expected,
          dict(classes))
    check('no radius-limited connection', classes.get('radius_limited_2d', 0) == 0)
    check('relations 368/400/256',
          dict(Counter(r['relation'] for r in recs)) ==
          {'same': 368, 'adjacent': 400, 'opposite': 256},
          dict(Counter(r['relation'] for r in recs)))

    # port usage exactly once
    used = Counter()
    for r in recs:
        used[r['source_port_id']] += 1
        used[r['target_port_id']] += 1
    check('2048 physical ports used exactly once',
          len(used) == 2048 and set(used.values()) == {1}, len(used))

    # corner tables
    ids = set(corner['corner_connector_ids'])
    check('16 corner connectors', len(ids) == 16, len(ids))
    check('4 corners x 2 connectors per side',
          all(len(v['corner_connector_set']) == 4
              for v in corner['corners'].values()))
    unique = set(corner['corner_connection_route_ids'])
    check('396 unique corner connections', len(unique) == 396, len(unique))
    rel_u = Counter(by_id[r]['relation'] for r in unique)
    check('corner unique relations 112/172/112',
          dict(rel_u) == {'opposite': 112, 'same': 172, 'adjacent': 112},
          dict(rel_u))
    cls_u = Counter(by_id[r]['judgement']['class_'] for r in unique)
    check('corner unique class counts match report',
          dict(cls_u) == {'not_limited': 4, 'pure90_template_limited': 48,
                          'conflict_needs_joint_search': 60,
                          'rigid_template_conflict': 112,
                          'same_u_family_capacity_limited': 172},
          dict(cls_u))
    for cname, cdata in corner['corners'].items():
        check(f'{cname}: 128 connection-corner entries',
              cdata['connection_count'] == 128, cdata['connection_count'])
        check(f'{cname}: judgement counts sum to 128',
              sum(cdata['judgement_counts'].values()) == 128)
        check(f'{cname}: phase-2 failed list length matches count',
              len([e for e in cdata['connections']
                   if e['phase2_2d_status'] == 'failed']) ==
              cdata['phase2_failed_connections'])
    for cname, cdata in corner['connectors'].items():
        check(f'connector {cname}: 32 holes -> 32 connections',
              cdata['connection_count'] == 32, cdata['connection_count'])

    # phase-2 cross evidence
    ev = analysis['two_d_routing_evidence']['summary']
    check('phase-2 routed+failed == 1024',
          ev['total_routed'] + ev['total_failed'] == 1024,
          (ev['total_routed'], ev['total_failed']))
    check('phase-2 failures by relation same 64 / adjacent 16',
          ev['failed_by_relation'] == {'same': 64, 'adjacent': 16},
          ev['failed_by_relation'])

    # structural claims
    cap = analysis['same_u_family_capacity']['per_plane_side']
    check('U family capacity: 4 depth tracks',
          len(analysis['same_u_family_capacity']['depth_tracks_mm']) == 4)
    check('U family capacity: all sides exceed 4 coverage',
          all(v['max_middle_interval_coverage'] > 4 for v in cap.values()),
          {k: v['max_middle_interval_coverage'] for k, v in cap.items()})
    check('adjacent rigid conflicts: 240 routes / 212 pairs',
          analysis['adjacent_rigid_template']['routes_with_rigid_conflict'] == 240 and
          analysis['adjacent_rigid_template']['substantial_conflict_pairs'] == 212,
          analysis['adjacent_rigid_template']['substantial_conflict_pairs'])
    check('opposite forced conflicts == 0',
          analysis['opposite_forced_conflicts']['forced_pairs'] == 0)

    # verification block
    ver = analysis.get('verification', {})
    check('verification block present', bool(ver))
    check('22 structural checks passed',
          ver['structural_checks']['passed'] and
          ver['structural_checks']['total'] == 22,
          ver['structural_checks']['total'])
    check('no coordinate mismatch', ver['coordinate_check']['mismatches'] == 0)

    # figures
    figures = sorted(FIG.glob('*.png'))
    check('6 PNG figures present', len(figures) == 6, [f.name for f in figures])
    check('all figures > 50 kB', all(f.stat().st_size > 50000 for f in figures),
          {f.name: f.stat().st_size for f in figures})

    # report exists and references the numbers
    report = OUT / 'corner_r15_report.md'
    text = report.read_text(encoding='utf-8') if report.exists() else ''
    check('report exists with substantial content', len(text) > 8000, len(text))
    for token in ('34.25', '10.625', '3.75', '144', '368', '240', '0.125',
                  '944/1024'):
        check(f'report contains {token}', token in text)

    payload = dict(schema='corner_r15_final_verification_v1',
                   passed=not failures, check_count=len(checks),
                   failed=failures, checks=checks)
    (DATA / 'verification_final.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(passed=payload['passed'],
                          checks=len(checks), failed=failures),
                     ensure_ascii=False, indent=1))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
