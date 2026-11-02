# -*- coding: utf-8 -*-
"""Prototype phase B: rebuild 256 Z1 manual U on L2-L5."""
import json, sys, time
from collections import OrderedDict
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4_adapt import compare_15L as M
from four_side_1024.manual_c4_adapt import manual_u_geometry as UGEOM
from four_side_1024.v3c4 import lift_cross as LIFT
from four_side_1024.r15 import profile_r15
from four_side_1024.manual_c4_adapt.run_full_campaign import CAMPAIGN_V4


def log(msg):
    print(msg, flush=True)


def build_manual_us_20(lifter, connections):
    started = time.perf_counter()
    manual_ids = set(connections)
    ports = M._all_ports()
    port_ids = list(ports)
    import numpy as np
    ports_xyz = np.asarray([[ports[pid]['xy'][0], ports[pid]['xy'][1],
                             ports[pid]['z_mm']] for pid in port_ids], dtype=float)
    port_index = {pid: index for index, pid in enumerate(port_ids)}
    results = OrderedDict()
    for layer in (2, 3, 4, 5):
        layer_z = float(lifter.stack.z_for_layer(layer))
        arm_requirement = M._arm_requirement(layer, layer_z)
        lifter._refresh_plane_cache()
        for side in UGEOM.SIDE_ORDER:
            side_connections = [c for c in connections.values()
                                if c['new_layer'] == layer and c['side'] == side]
            if not side_connections:
                continue
            items = [dict(route_id=c['route_id'], source=c['source'],
                          target=c['target']) for c in side_connections]
            nesting = UGEOM.nesting_plan(items, arm_min_mm=arm_requirement,
                                         depth_step_mm=0.25)
            ordered = sorted(side_connections,
                             key=lambda c: (nesting[c['route_id']]['contains'],
                                            c['route_id']))
            for c in ordered:
                rid = c['route_id']
                row = nesting[rid]
                record = c['record']
                own_ids = {record.get('source_endpoint'),
                           record.get('target_endpoint')}
                own_mask = np.zeros(len(port_ids), dtype=bool)
                for pid in own_ids:
                    if pid in port_index:
                        own_mask[port_index[pid]] = True
                keepout = (ports_xyz, own_mask, float(UGEOM.PROFILE_CLEARANCE_MM))
                outcome = None
                last_reason = 'no_candidate_depth'
                for arm_index, arm in enumerate(M._arm_candidates(row, arm_requirement)):
                    geometry = UGEOM.build_manual_u_geometry(
                        c['source'], c['target'], c['side'], arm_mm=arm)
                    if not geometry['ok']:
                        last_reason = 'geometry:' + ','.join(geometry['errors'])
                        continue
                    committed, reason = M.force_manual_route(
                        lifter, rid, layer,
                        dict(connection=c, geometry=geometry),
                        plan_limit=80 if arm_index == 0 else 32,
                        port_keepout=keepout)
                    if committed is None:
                        last_reason = reason
                        continue
                    outcome = dict(route_id=rid, layer=int(layer), side=side,
                                   group=c['group'], order=c['order'],
                                   u_pair=c['u_pair'], arm_mm=float(committed['arm_mm']),
                                   depth_mm=float(committed['depth_mm']),
                                   nesting_contains=int(row['contains']),
                                   nesting_k=int(row['chain_k']),
                                   transition=committed['plan'],
                                   length_mm=float(committed['route'].get('length_mm') or 0),
                                   n_transitions=int(committed['route'].get('n_transitions') or 0),
                                   primitives=committed['primitives'])
                    break
                if outcome is None:
                    outcome = dict(route_id=rid, layer=int(layer), side=side,
                                   group=c['group'], order=c['order'],
                                   u_pair=c['u_pair'], failed=True, reason=last_reason)
                results[rid] = outcome
            placed = sum(1 for item in results.values()
                         if item.get('layer') == layer and item.get('side') == side
                         and 'failed' not in item)
            log(f'[phaseB] L{layer} {side}: {placed}/'
                f'{len(side_connections)} placed ({time.perf_counter()-started:.1f}s)')
    return dict(results=results,
                placed=sum(1 for item in results.values() if 'failed' not in item),
                failed=sum(1 for item in results.values() if 'failed' in item),
                elapsed=time.perf_counter() - started)


def main():
    M.install_extended_stack_builder()
    profile_r15.apply()
    heights = [round(0.65 + 0.15 * i, 2) for i in range(19)]
    out = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_LAYERS_20L_PROTO'
    lifter = LIFT.CrossingLifter(v4_root=CAMPAIGN_V4, out_dir=out,
                                 heights=heights, log=log)
    lifter.world.rebuild({})
    lifter.lifted = {}
    lifter.primitives = {}
    lifter.base_routes = {}
    connections = M.load_manual_connections()
    for c in connections.values():
        c['new_layer'] = int(c['layer']) + 1
    log(f'connections {len(connections)}; layer counts '
        f'{ {l: sum(1 for c in connections.values() if c["new_layer"]==l) for l in (2,3,4,5)} }')
    phase = build_manual_us_20(lifter, connections)
    log(f'phaseB placed={phase["placed"]} failed={phase["failed"]} ({phase["elapsed"]:.1f}s)')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'phaseB.json').write_text(json.dumps(phase, ensure_ascii=False, indent=1,
                                                default=str), encoding='utf-8')
    routes = {int(rid): lifter.lifted.get(int(rid)) for rid in connections}
    (out / 'manual_routes.json').write_text(json.dumps(
        dict(routes={str(k): v for k, v in routes.items() if v},
             primitives={str(k): [dict(p) for p in lifter.primitives[k]]
                         for k in connections if k in lifter.primitives}),
        ensure_ascii=False, indent=1), encoding='utf-8')
    # per-layer stats
    from collections import Counter
    print('per layer', Counter(int(row['layer']) for row in phase['results'].values()
                               if 'failed' not in row))
    print('failures', [(rid, row['layer'], row['side'], row['reason'])
                       for rid, row in phase['results'].items() if 'failed' in row][:30])


if __name__ == '__main__':
    main()
