# -*- coding: utf-8 -*-
"""P2 failure map: existing Z2 layout + candidate paths + blocker orbits."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from four_side_1024.v3c4.profile import apply as apply_profile
apply_profile()

from four_side_1024.bundle3d.reroute import (  # noqa: E402
    RipUpRerouter, load_plane_payload)
from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import router as ROUTER  # noqa: E402
from four_side_1024.manual_c4.router import ManualGroupRouter  # noqa: E402
from four_side_1024.manual_c4.state import state_for  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/BUNDLE_AWARE_NATIVE_3D'
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
FAILED = [154, 156, 158, 214, 246, 249, 250, 254]
FIGS = CAMPAIGN / 'figures'


def route_points(primitives):
    points = []
    for primitive in primitives:
        if primitive.get('kind') == 'line':
            points.append(tuple(primitive['p0']))
            points.append(tuple(primitive['p1']))
        else:
            for key in ('p0', 'p1'):
                points.append(tuple(primitive[key]))
    return points


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


def main():
    patch_conn()
    groups = CONN.groups_for_plane('z2')
    by_gid = {int(group['group_id']): group for group in groups}
    combined = json.loads((OLD / 'phase2_2d_selected/routes_1024.json')
                          .read_text(encoding='utf-8'))
    payload = dict(schema='x', plane='z2',
                   routes=[copy.deepcopy(record) for record in
                           combined['routes'] if record.get('plane') == 'z2'])
    state = state_for('z2', log=lambda *a: None)
    load_plane_payload(state, payload)
    router = ManualGroupRouter(state, groups, log=lambda *a: None)
    ROUTER.BULGE_LADDER = ([round(0.1 * i, 3) for i in range(0, 1301)]
                           + [130.0, 135.0, 140.0])
    rr = RipUpRerouter(router, state, groups, log=lambda *a: None)
    rr.plane = 'z2'
    fig, ax = plt.subplots(figsize=(9.2, 8.6))
    # routed 2D layout (light)
    for record in payload['routes']:
        if record.get('status') != 'routed':
            continue
        points = route_points(record.get('primitives') or [])
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        ax.plot(xs, ys, color='#dee2e6', lw=0.35, zorder=1)
    info_rows = []
    colors = plt.cm.tab10(np.linspace(0, 1, len(FAILED)))
    for color, group_id in zip(colors, FAILED):
        target = by_gid[group_id]
        candidates = rr.candidate_quads(target, budget=300)
        blocker_ids = []
        drawn = 0
        for candidate in candidates:
            if candidate['self_conflict']:
                continue
            if drawn >= 3:
                break
            for primitive in candidate['oriented'][0]:
                points = route_points([primitive])
                ax.plot([p[0] for p in points], [p[1] for p in points],
                        color=color, lw=1.0, alpha=0.9, zorder=3)
            drawn += 1
            blocker_ids.extend(candidate['blocker_groups'])
        blocker_ids = sorted(set(blocker_ids))
        for blocker in blocker_ids:
            for rid in by_gid[blocker]['route_ids']:
                record = next((row for row in payload['routes']
                               if int(row['route_id']) == int(rid)), None)
                if record is None or record.get('status') != 'routed':
                    continue
                points = route_points(record.get('primitives') or [])
                if points:
                    ax.plot([p[0] for p in points], [p[1] for p in points],
                            color=color, lw=0.9, alpha=0.35,
                            linestyle='--', zorder=2)
        record = next((row for row in payload['routes']
                       if int(row['route_id']) == int(target['route_ids'][0])),
                      None)
        info_rows.append(dict(group_id=group_id, kind=target['kind'],
                              blocker_orbits=blocker_ids))
    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], color='#dee2e6', lw=1.0, label='routed 480 routes'),
        Line2D([0], [0], color='#e03131', lw=1.0,
               label='candidate paths of the 8 unrouted orbits'),
        Line2D([0], [0], color='#e03131', lw=0.9, linestyle='--',
               label='blocking orbits (must be moved)'),
    ]
    ax.legend(handles=legend, fontsize=7, loc='upper right')
    ax.set_xlim(0, 150)
    ax.set_ylim(0, 150)
    ax.set_aspect('equal')
    ax.set_title('P2: the 8 unrouted Z2 C4 orbits, their candidate paths and '
                 'blocking orbits (colors = orbit, dashes = blockers)',
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGS / 'fig11_ripup_failure_map.png', dpi=175)
    plt.close(fig)
    (CAMPAIGN / '02_ripup/failure_map_summary.json').write_text(
        json.dumps(dict(failed=FAILED, details=info_rows), ensure_ascii=False,
                   indent=1), encoding='utf-8')
    print(json.dumps(info_rows, ensure_ascii=False, indent=1)[:1200])


if __name__ == '__main__':
    main()
