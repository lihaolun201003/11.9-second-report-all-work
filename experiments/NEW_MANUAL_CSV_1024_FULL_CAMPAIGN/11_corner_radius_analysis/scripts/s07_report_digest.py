# -*- coding: utf-8 -*-
"""Step 7: print a number digest used to write the Chinese report (no files written
except data/report_digest.json)."""
from __future__ import annotations

import csv
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
CAMPAIGN = L.CAMPAIGN
ROOT = L.ROOT

analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
load_report = json.loads((DATA / 'load_report.json').read_text(encoding='utf-8'))
recs = analysis['connections']

digest = dict(
    load_checks=dict(passed=load_report['passed'],
                     total=len(load_report['checks']),
                     failed=[c['check'] for c in load_report['checks']
                             if not c['passed']]),
    stats=load_report['stats'],
    summary=analysis['summary'],
    same_u_family_capacity={
        k: dict(u_count=v['u_count'],
                max_coverage=v['max_middle_interval_coverage'],
                at_x=v['max_coverage_at_x'],
                pigeonhole=v['pigeonhole_conflict_provable'],
                tracks=len(v['depth_tracks']))
        for k, v in analysis['same_u_family_capacity']['per_plane_side'].items()},
    adjacent_rigid=analysis['adjacent_rigid_template'],
    opposite_forced=analysis['opposite_forced_conflicts'],
    phase2=analysis['two_d_routing_evidence']['summary'],
    phase2_planes={p: {k: v.get(k) for k in (
        'routed', 'failed', 'total', 'routed_groups', 'failed_groups',
        'failed_group_kinds', 'failures_by_relation', 'failures_by_class')}
        for p, v in analysis['two_d_routing_evidence']['planes'].items()},
    corner_global=corner['global_summary'],
    corner_per_corner={name: dict(
        connectors=v['corner_connector_set'],
        connector_min_dist=[c['min_distance_to_corner_mm'] for c in v['connectors']],
        connections=v['connection_count'],
        relation_counts=v['relation_counts'],
        judgement_counts=v['judgement_counts'],
        min_margins=v['min_margins_mm'],
        phase2_failed=v.get('phase2_failed_connections'),
        max_spacing=max((e['spacing_conflict_partner_count']
                         for e in v['connections']), default=0),
    ) for name, v in corner['corners'].items()},
)
# example rows for the report
same_sorted = sorted((r for r in recs if r['relation'] == 'same'),
                     key=lambda r: r['same']['margin_mm'])
digest['examples'] = dict(
    same_tightest=[dict(route_id=r['route_id'], plane=r['plane'],
                        src=r['source_port_id'], dst=r['target_port_id'],
                        D=r['same']['separation_D_mm'],
                        m=r['same']['middle_straight_mm'],
                        blockers=r['same'].get('family_blockers_same_side'))
                   for r in same_sorted[:6]],
    same_loosest=[dict(route_id=r['route_id'], plane=r['plane'],
                       D=r['same']['separation_D_mm'])
                  for r in same_sorted[-3:]],
    adjacent_tightest=sorted(
        (r for r in recs if r['relation'] == 'adjacent'),
        key=lambda r: r['adjacent']['min_leg_mm'])[:6],
    opposite_short_s=sorted(
        (r for r in recs if r['relation'] == 'opposite'
         and not r['opposite']['strict_90_feasible']),
        key=lambda r: r['opposite']['delta_mm']),
)
digest['examples']['adjacent_tightest'] = [
    dict(route_id=r['route_id'], plane=r['plane'],
         src=r['source_port_id'], dst=r['target_port_id'],
         a=r['adjacent']['a_source_to_corner_mm'],
         b=r['adjacent']['b_target_to_corner_mm'],
         leg_min=r['adjacent']['min_leg_mm'])
    for r in digest['examples']['adjacent_tightest']]
digest['examples']['opposite_short_s'] = [
    dict(route_id=r['route_id'], delta=r['opposite']['delta_mm'],
         theta=r['opposite']['theta_deg'], advance=r['opposite']['advance_mm'],
         margin=r['opposite']['margin_mm'])
    for r in digest['examples']['opposite_short_s'][:12]]
# opposite regime counts / margins
digest['opposite_regimes'] = dict(Counter(
    r['opposite']['regime'] for r in recs if r['relation'] == 'opposite'))
digest['opposite_short_s_margins'] = sorted(
    {round(r['opposite']['margin_mm'], 3)
     for r in recs if r['relation'] == 'opposite'
     and not r['opposite']['strict_90_feasible']})
digest['s_lift'] = analysis['summary']['s_lift']
digest['s_lift_footprints'] = [
    dict(dz=dz, footprint=round(L.s_lift_footprint(dz), 4))
    for dz in (0.15, 0.30, 0.50, 0.65, 0.80, 1.00, 1.35, 1.50, 2.00)]
# historical comparison (read-only): old campaign CSVs
OLD = ROOT / 'manual_z1_router/data/exports'
old = {}
eps = L.load_endpoints()
for name, plane in (('manual_z1_c4_full.csv', 'z1'),
                    ('manual_z2_c4_full.csv', 'z2')):
    rows = list(csv.DictReader((OLD / name).read_bytes()
                               .decode('utf-8-sig').splitlines()))
    rel = Counter(r['relation'] for r in rows)
    legs = []
    same_seps = []
    for r in rows:
        a, b = eps[r['source_port_id']], eps[r['target_port_id']]
        xa, ya = (float(v) for v in a['routing_xy'])
        xb, yb = (float(v) for v in b['routing_xy'])
        if r['relation'] == 'adjacent':
            legs.append(min(abs(xa - xb), abs(ya - yb)) - L.R)
        elif r['relation'] == 'same':
            same_seps.append(abs(xa - xb) if a['side'] in 'NS' else abs(ya - yb))
    old[plane] = dict(
        rows=len(rows), relations=dict(rel),
        adjacent_leg_min=round(min(legs), 6) if legs else None,
        adjacent_legs_below_1mm=sum(1 for v in legs if v < 1.0),
        adjacent_legs_below_R=sum(1 for v in legs if v < L.R),
        same_min_sep=round(min(same_seps), 6) if same_seps else None,
        same_below_2R=sum(1 for v in same_seps if v < 2 * L.R - 1e-9),
    )
digest['historical_old_campaign'] = old

(DATA / 'report_digest.json').write_text(
    json.dumps(digest, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(digest, ensure_ascii=False, indent=1))
