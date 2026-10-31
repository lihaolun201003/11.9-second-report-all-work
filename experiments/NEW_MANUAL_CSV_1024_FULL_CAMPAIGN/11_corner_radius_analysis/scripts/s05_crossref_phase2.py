# -*- coding: utf-8 -*-
"""Step 5: cross-reference with the campaign's own phase-2 2D routing results.

The campaign's 2D router (``phase2_2d/<plane>/checkpoint.json``, produced by the
Lead's pipeline, read-only here) already tried the frozen family on exactly these
planes.  This step attaches the observed outcome (routed / failed) to every
connection and to the corner connector tables, and adds the cross-tabulation
"geometric judgement class x 2D routing outcome".  It does not modify the
phase-2 artefacts.
"""
from __future__ import annotations

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

TOPOLOGY_JSON = CAMPAIGN / 'inputs/connectivity_1024.json'
PHASE2 = {plane: CAMPAIGN / f'phase2_2d/{plane}' for plane in ('z1', 'z2')}


def load_phase2(plane):
    ck_path = PHASE2[plane] / 'checkpoint.json'
    if not ck_path.exists():
        return None
    ck = json.loads(ck_path.read_text(encoding='utf-8'))
    topology = json.loads(TOPOLOGY_JSON.read_text(encoding='utf-8'))
    groups = {g['group_id']: g for g in topology['groups']}
    failed_groups = [int(k) for k in ck.get('failed_groups', {})]
    failed_routes = set()
    for gid in failed_groups:
        failed_routes.update(groups[gid]['route_ids'])
    routed_routes = {int(r['route_id']) for r in ck.get('routed', [])}
    summary_path = PHASE2[plane] / 'run_summary.json'
    summary = (json.loads(summary_path.read_text(encoding='utf-8'))
               if summary_path.exists() else None)
    return dict(failed_groups=failed_groups, failed_routes=sorted(failed_routes),
                routed_routes=sorted(routed_routes), summary=summary,
                failed_group_kinds=dict(Counter(groups[g]['kind']
                                                for g in failed_groups)))


def main():
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
    records = {r['route_id']: r for r in analysis['connections']}
    phase2 = {plane: load_phase2(plane) for plane in ('z1', 'z2')}

    outcome = {}
    evidence = dict(
        source='read-only cross-reference with the campaign phase-2 2D routing '
               'outputs (phase2_2d/<plane>/checkpoint.json, run_summary.json)',
        planes={},
    )
    for plane, payload in phase2.items():
        if payload is None:
            evidence['planes'][plane] = dict(available=False)
            continue
        failed = set(payload['failed_routes'])
        routed = set(payload['routed_routes'])
        lo, hi = (1, 513) if plane == 'z1' else (513, 1025)
        for rid in range(lo, hi):
            outcome[rid] = 'failed' if rid in failed else (
                'routed' if rid in routed else 'not_attempted')
        summary = payload['summary'] or {}
        tab = Counter()
        for rid in range(lo, hi):
            rec = records[rid]
            tab[(rec['relation'], rec['judgement']['class_'],
                 outcome[rid])] += 1
        evidence['planes'][plane] = dict(
            available=True,
            routed=summary.get('routed'), failed=summary.get('failed'),
            total=summary.get('total'),
            routed_groups=summary.get('routed_groups'),
            failed_groups=summary.get('failed_groups'),
            failed_group_kinds=payload['failed_group_kinds'],
            failed_route_ids=payload['failed_routes'],
            cross_tab={f'{rel}|{cls}|{out}': n for
                       (rel, cls, out), n in sorted(tab.items())},
            failures_by_relation=dict(Counter(
                records[rid]['relation'] for rid in payload['failed_routes'])),
            failures_by_class=dict(Counter(
                records[rid]['judgement']['class_']
                for rid in payload['failed_routes'])),
        )
    total_failed = {}
    for plane, payload in phase2.items():
        if payload is not None:
            for rid in payload['failed_routes']:
                total_failed[rid] = records[rid]['relation']
    evidence['summary'] = dict(
        total_routed=sum((p['summary'] or {}).get('routed', 0)
                         for p in phase2.values() if p),
        total_failed=len(total_failed),
        failed_by_relation=dict(Counter(total_failed.values())),
        failed_by_class=dict(Counter(
            records[rid]['judgement']['class_'] for rid in total_failed)),
        note='phase-2 routing is the Lead pipeline output; it is quoted here only '
             'as an independent confirmation, never modified',
    )
    analysis['two_d_routing_evidence'] = evidence
    for rec in analysis['connections']:
        rec['phase2_2d_status'] = outcome.get(rec['route_id'], 'unknown')
    (OUT / 'corner_r15_analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding='utf-8')

    # attach to corner tables
    for corner_entry in corner['corners'].values():
        failed = 0
        for entry in corner_entry['connections']:
            entry['phase2_2d_status'] = outcome.get(entry['route_id'], 'unknown')
            if entry['phase2_2d_status'] == 'failed':
                failed += 1
        corner_entry['phase2_failed_connections'] = failed
    for connector_entry in corner['connectors'].values():
        failed = 0
        for entry in connector_entry['entries']:
            entry['phase2_2d_status'] = outcome.get(entry['route_id'], 'unknown')
            if entry['phase2_2d_status'] == 'failed':
                failed += 1
        connector_entry['phase2_failed_connections'] = failed
    corner['two_d_routing_evidence'] = evidence
    (OUT / 'corner_connectors.json').write_text(
        json.dumps(corner, ensure_ascii=False, indent=1), encoding='utf-8')

    print(json.dumps(evidence['summary'], ensure_ascii=False, indent=1))
    for plane, payload in evidence['planes'].items():
        if payload.get('available'):
            print(plane, 'routed', payload['routed'], 'failed', payload['failed'],
                  'failed kinds', payload['failed_group_kinds'],
                  'failed classes', payload['failures_by_class'])


if __name__ == '__main__':
    main()
