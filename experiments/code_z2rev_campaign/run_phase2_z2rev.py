# -*- coding: utf-8 -*-
"""Phase-2 (2D strict C4) + extended-ladder repair for the revised Z2 CSV."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile
apply_profile()

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import run2d  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402
from four_side_1024.v3c4 import validate2d  # noqa: E402

CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
PHASE2 = CAMPAIGN / 'phase2_2d'
REPAIRED = CAMPAIGN / 'phase2_2d_repaired'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def repair_plane(plane):
    from four_side_1024.d56.index import prepare
    from four_side_1024.d56.search import RouteResult
    from four_side_1024.manual_c4 import audit2d

    groups = CONN.groups_for_plane(plane)
    by_gid = {int(group['group_id']): group for group in groups}
    payload = json.loads((PHASE2 / plane / 'routes.json').read_text(
        encoding='utf-8'))
    records = {int(record['route_id']): dict(record)
               for record in payload['routes']}
    state = state_for(plane, log=lambda *a: None)
    for record in records.values():
        if record.get('status') != 'routed':
            continue
        rid = int(record['route_id'])
        prims = [dict(primitive) for primitive in record['primitives']]
        prepared = prepare(prims)
        state.index.add(rid, prepared)
        state.accepted[rid] = RouteResult(
            rid, record.get('family') or 'HISTORY',
            dict(record.get('params') or {}), prims, prepared,
            float(record.get('length_mm') or 0.0), 0, 0,
            int(record.get('bend_count') or 0))
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    old_ladder = ROUTER.BULGE_LADDER
    ROUTER.BULGE_LADDER = ([round(0.1 * index, 3) for index in range(0, 1301)]
                           + [130.0, 135.0, 140.0])
    recovered = []
    started = time.perf_counter()
    try:
        for pass_index in range(4):
            pending = [by_gid[gid] for gid in sorted(by_gid)
                       if not all(int(rid) in state.accepted
                                  for rid in by_gid[gid]['route_ids'])]
            if not pending:
                break
            pass_recovered = 0
            for group in pending:
                results, failure, stats = router.attempt_group(group, 30000)
                if results is not None:
                    router.commit_group(group, results)
                    pass_recovered += 1
                    recovered.append(dict(pass_index=pass_index,
                                          group_id=int(group['group_id']),
                                          kind=group['kind'],
                                          evaluated=stats.get('evaluated')))
            print(f'[repair-z2rev] {plane} pass {pass_index}: pending='
                  f'{len(pending)} recovered={pass_recovered} routed='
                  f'{len(state.accepted)}', flush=True)
            if not pass_recovered:
                break
        payload_out = state.payload('C4_2D_REPAIRED_Z2REV', dict(
            name='C4_2D_REPAIRED_Z2REV', algorithm='C4_2D_REPAIRED_Z2REV',
            process_profile='R15_min_radius_15mm', radius_mm=15.0,
            geometry_mode='d56', crossing_policy='exact',
            strategy='easy order + extended U bulge repair'),
            'C4_2D_REPAIRED_Z2REV')
        payload_out['rotation_groups'] = [
            dict(group_id=int(group['group_id']), plane=group['plane'],
                 kind=group['kind'],
                 route_ids=[int(rid) for rid in group['route_ids']],
                 status='routed' if int(group['group_id'])
                 in router.group_results else 'failed')
            for group in groups]
        payload_out['failed_groups'] = [
            dict(group_id=gid, kind=by_gid[gid]['kind'],
                 reason='no_legal_quad_after_extended_ladder')
            for gid in sorted(by_gid)
            if int(gid) not in router.group_results]
        router.augment_route_records(payload_out)
        for record in payload_out['routes']:
            if record.get('status') != 'routed':
                record['status'] = 'failed'
                record['reason'] = 'no_legal_quad_after_extended_ladder'
        saved = json.loads(json.dumps(payload_out, default=str))
        report = audit2d.audit_plane(saved, plane,
                                     label=f'Z2REV_{plane}',
                                     log=lambda *a: None)
        all_groups = CONN.combined_topology()['groups']
        route_group = CONN.route_group_map()
        c4 = validate2d.audit_c4_groups(
            saved['routes'], [group for group in all_groups
                              if group['plane'] == plane],
            route_group, log=lambda *a: None)
        validation = dict(schema='manual_c4_2d_plane_validation_v1',
                          experiment='C4_2D_REPAIRED_Z2REV', plane=plane,
                          passed=bool(report['passed'] and c4['passed']),
                          plane_audit=report, c4_symmetry=c4)
        out_dir = REPAIRED / plane
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'routes.json').write_text(
            json.dumps(payload_out, ensure_ascii=False, default=str),
            encoding='utf-8')
        (out_dir / 'validation.json').write_text(
            json.dumps(validation, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        return dict(plane=plane, routed=len(state.accepted),
                    failed=len(state.routes) - len(state.accepted),
                    recovered=recovered,
                    validation_passed=validation['passed'],
                    seconds=round(time.perf_counter() - started, 1))
    finally:
        ROUTER.BULGE_LADDER = old_ladder


def reuse_z1():
    """Z1 input is unchanged -> reuse the previously validated 512/512 layout."""
    src = OLD / 'phase2_2d_repaired/z1'
    dst = REPAIRED / 'z1'
    dst.mkdir(parents=True, exist_ok=True)
    for name in ('routes.json', 'validation.json'):
        with open(src / name, 'rb') as handle:
            data = handle.read()
        with open(dst / name, 'wb') as handle:
            handle.write(data)
    payload = json.loads((dst / 'routes.json').read_text(encoding='utf-8'))
    routed = sum(1 for record in payload['routes']
                 if record.get('status') == 'routed')
    return dict(plane='z1', routed=routed, reused=True)


def main():
    patch_conn()
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    summary = {}
    # ---- Z2 phase 2 (same settings as the previous campaign) ----------
    z2_dir = PHASE2 / 'z2'
    started = time.perf_counter()
    run2d.run_plane('z2', 'easy', 1600, z2_dir,
                    rr_rounds=2, retry_passes=3, time_limit=1800)
    routes = json.loads((z2_dir / 'routes.json').read_text(encoding='utf-8'))
    routed = sum(1 for record in routes['routes']
                 if record.get('status') == 'routed')
    summary['z2_phase2'] = dict(routed=routed,
                                seconds=round(time.perf_counter() - started, 1))
    print(f'[z2rev] phase2 z2 routed={routed}/512', flush=True)
    # ---- repair -------------------------------------------------------
    summary['z2_repair'] = repair_plane('z2')
    print(f'[z2rev] repaired z2 routed={summary["z2_repair"]["routed"]}/512',
          flush=True)
    # ---- z1 reuse -----------------------------------------------------
    summary['z1'] = reuse_z1()
    # ---- combine ------------------------------------------------------
    combined = run2d.combine(phase2_dir=REPAIRED, log=print)
    summary['combined'] = dict(routed=combined.get('routed'),
                               groups=combined.get('routed_groups'),
                               plane_crossings=combined.get('plane_crossings'),
                               validation_passed=combined.get(
                                   'validation_passed'))
    (CAMPAIGN / 'phase2_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
