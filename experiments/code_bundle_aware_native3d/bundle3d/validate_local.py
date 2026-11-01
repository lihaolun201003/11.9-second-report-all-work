"""Frozen 2D + strict C4 validation helpers used by the rip-up search."""
from __future__ import annotations

import json

from ..manual_c4 import connectivity as CONN


def validate_plane_payload(payload, plane, log=lambda *a: None):
    from ..manual_c4 import audit2d
    from ..v3c4 import validate2d

    saved = json.loads(json.dumps(payload, default=str))
    report = audit2d.audit_plane(saved, plane, label=f'RIPUP_{plane}',
                                 log=log)
    all_groups = CONN.combined_topology()['groups']
    route_group = CONN.route_group_map()
    c4 = validate2d.audit_c4_groups(
        saved['routes'],
        [group for group in all_groups if group['plane'] == plane],
        route_group, log=log)
    return dict(passed=bool(report['passed'] and c4['passed']),
                plane_audit=report, c4_symmetry=c4)


def summarize_payload(payload):
    routed = sum(1 for record in payload.get('routes', [])
                 if record.get('status') == 'routed')
    total = len(payload.get('routes', []))
    return dict(routed=routed, total=total, failed=total - routed)
