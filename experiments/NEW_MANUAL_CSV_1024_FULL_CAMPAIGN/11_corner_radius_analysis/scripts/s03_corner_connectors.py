# -*- coding: utf-8 -*-
"""Step 3: four-corner connector audit + template-level conflict evidence.

* identifies the 16 physical connectors closest to the four board corners
  (2 per corner side, all their 32 holes within 18.375 mm of the corner);
* lists every connection that touches those connectors (each physical connector
  has 32 holes -> 16 z1-row + 16 z2-row connections), with the required minimum
  geometry, the R15 margin, the template class and the vertical S-lift capacity;
* gives the "radius limited" judgement per connection distinguishing
    (1) proven 2D template infeasible at R=15 for the frozen family;
    (2) template-family limited: frozen family works only with non-90-deg
        short-S arcs, so a pure "two 90 deg turn" template cannot generate it;
    (3) template route exists but conflicts with other canonical templates
        (spacing closer than 0.08 mm between representative centrelines), i.e.
        not decidable by single-connection geometry -> routing/joint search;
    (4) not limited: template exists and the representative geometry keeps the
        0.08 mm clearance against all other representative templates.
  For adjacent connections the single-arc L has no free parameter, so a spacing
  conflict there cannot be repaired inside the same template family -> it needs
  a compound template or a 3D layer change ("needs 3D search").

The conflict evidence samples every canonical 2D template centreline at 0.10 mm
and classifies nearby point pairs by the angle between the local tangents
(< 5 deg => parallel spacing conflict; >= 5 deg => permitted designed crossing,
matching the project's MIN_CROSS_ANGLE_DEG = 5 policy).

Writes the required deliverable ``corner_connectors.json`` and the internal
``data/collision_1024.json``.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corner_lib as L  # noqa: E402

OUT = L.OUT
DATA = L.DATA

CORNER_DEFS = {
    'NE': dict(corner_xy=[150.0, 150.0], sides=('N', 'E')),
    'SE': dict(corner_xy=[150.0, 0.0], sides=('E', 'S')),
    'SW': dict(corner_xy=[0.0, 0.0], sides=('S', 'W')),
    'NW': dict(corner_xy=[0.0, 150.0], sides=('W', 'N')),
}

SAMPLE_STEP = 0.10     # mm along the template centreline
QUERY_RADIUS = 0.11    # mm (clearance 0.08 + sampling margin)
MIN_CROSS_ANGLE_DEG = 5.0


def sample_primitive(prim):
    """(points, unit tangents) of one line/arc primitive at 0.1 mm spacing."""
    if prim['kind'] == 'line':
        p0 = np.array(prim['p0'], dtype=np.float64)
        p1 = np.array(prim['p1'], dtype=np.float64)
        delta = p1 - p0
        length = float(np.hypot(*delta))
        direction = delta / length if length > 0 else np.array([1.0, 0.0])
        n = max(2, int(math.ceil(length / SAMPLE_STEP)) + 1)
        t = np.linspace(0.0, 1.0, n)[:, None]
        return p0 + t * delta, np.repeat(direction[None, :], n, axis=0)
    radius = float(prim['radius'])
    sweep = float(prim['sweep'])
    center = np.array(prim['center'], dtype=np.float64)
    start = float(prim['start_angle'])
    n = max(2, int(math.ceil(abs(sweep) * radius / SAMPLE_STEP)) + 1)
    angles = start + np.linspace(0.0, sweep, n)
    pts = center + radius * np.stack([np.cos(angles), np.sin(angles)], axis=1)
    sign = 1.0 if sweep > 0 else -1.0
    tangents = sign * np.stack([-np.sin(angles), np.cos(angles)], axis=1)
    return pts, tangents


def sample_template(template):
    pts, dirs = [], []
    for prim in template['primitives']:
        p, d = sample_primitive(prim)
        pts.append(p)
        dirs.append(d)
    if not pts:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.vstack(pts), np.vstack(dirs)


def collision_analysis(templates, connections):
    """Angle-aware canonical-template proximity analysis per plane."""
    result = {}
    summary = {}
    for plane in ('z1', 'z2'):
        ids = [c['route_id'] for c in connections if c['plane'] == plane]
        points, dirs, owners = [], [], []
        for rid in ids:
            pts, tan = sample_template(templates[str(rid)])
            points.append(pts)
            dirs.append(tan)
            owners.append(np.full(len(pts), rid, dtype=np.int32))
        points = np.vstack(points)
        dirs = np.vstack(dirs)
        owners = np.concatenate(owners)
        tree = cKDTree(points)
        spacing = {rid: Counter() for rid in ids}
        crossing = {rid: Counter() for rid in ids}
        chunk = 200000
        for start in range(0, len(points), chunk):
            q = points[start:start + chunk]
            qd = dirs[start:start + chunk]
            hits = tree.query_ball_point(q, r=QUERY_RADIUS, workers=-1)
            for local, hit_idx in enumerate(hits):
                if not hit_idx:
                    continue
                rid = int(owners[start + local])
                d1 = qd[local]
                for index in hit_idx:
                    other = int(owners[index])
                    if other == rid:
                        continue
                    d2 = dirs[index]
                    cross = d1[0] * d2[1] - d1[1] * d2[0]
                    dot = float(d1[0] * d2[0] + d1[1] * d2[1])
                    angle = abs(math.degrees(math.atan2(cross, dot)))
                    angle = min(angle, 180.0 - angle)
                    if angle < MIN_CROSS_ANGLE_DEG:
                        spacing[rid][other] += 1
                    else:
                        crossing[rid][other] += 1
        for rid in ids:
            sp = sorted(spacing[rid].items(), key=lambda kv: -kv[1])
            cr = sorted(crossing[rid].items(), key=lambda kv: -kv[1])
            result[rid] = dict(
                spacing_conflict_partner_count=len(sp),
                crossing_partner_count=len(cr),
                worst_spacing_partners=[dict(route_id=int(o), hits=int(n))
                                        for o, n in sp[:8]],
                same_plane_routes=len(ids) - 1,
            )
        sp_counts = [result[rid]['spacing_conflict_partner_count'] for rid in ids]
        cr_counts = [result[rid]['crossing_partner_count'] for rid in ids]
        summary[plane] = dict(
            routes=len(ids),
            spacing_conflict_partner_min=min(sp_counts),
            spacing_conflict_partner_max=max(sp_counts),
            spacing_conflict_partner_median=sorted(sp_counts)[len(sp_counts) // 2],
            spacing_conflict_partner_mean=round(sum(sp_counts) / len(sp_counts), 3),
            spacing_conflict_routes=sum(1 for v in sp_counts if v > 0),
            crossing_partner_median=sorted(cr_counts)[len(cr_counts) // 2],
        )
    return result, summary


def corner_connector_sets(eps):
    """Two connectors per adjacent side, i.e. the 16 physical corner connectors."""
    conn_ports = defaultdict(list)
    for eid, ep in eps.items():
        if ep['plane'] != 'z1':
            continue
        conn_ports[ep['connector']].append(ep)
    out = {}
    for corner, spec in CORNER_DEFS.items():
        cx, cy = spec['corner_xy']
        chosen = []
        for side in spec['sides']:
            ranked = []
            for connector, ports in conn_ports.items():
                if ports[0]['side'] != side:
                    continue
                min_d = min(math.hypot(float(p['routing_xy'][0]) - cx,
                                       float(p['routing_xy'][1]) - cy)
                            for p in ports)
                ranked.append((min_d, connector))
            ranked.sort()
            chosen.extend(ranked[:2])
        out[corner] = dict(
            corner_xy=spec['corner_xy'], sides=list(spec['sides']),
            connectors=[c for _d, c in chosen],
            connector_corner_distance={c: round(d, 6) for d, c in chosen},
        )
    return out


def connection_judgement(rec, collision):
    """Requested failure-cause class of one connection (single-template level)."""
    strict90_ok = (True if rec['relation'] != 'opposite'
                   else rec['opposite']['strict_90_feasible'])
    spacing = collision['spacing_conflict_partner_count']
    if not rec['template']['feasible']:
        cls = 'radius_limited_2d'
    elif not strict90_ok:
        cls = 'pure90_template_limited'      # only shortest pair (non-90 deg) works
    elif rec['relation'] == 'adjacent' and spacing > 0:
        cls = 'rigid_template_conflict_needs_3d'
    elif spacing > 0:
        cls = 'conflict_needs_joint_search'
    else:
        cls = 'not_limited'
    flags = []
    if cls == 'radius_limited_2d':
        flags.append('2D template infeasible at R=15 for the frozen family')
    if cls == 'pure90_template_limited':
        flags.append('needs non-90deg two-arc short-S (theta = acos(1-delta/2R))')
    if rec['s_lift']['unreachable_layers']:
        flags.append('vertical S-lift cannot reach layers %s'
                     % rec['s_lift']['unreachable_layers'])
    if spacing > 0:
        flags.append('%d same-plane canonical templates within 0.08 mm '
                     '(parallel spacing conflict of the representative template)'
                     % spacing)
    if rec['relation'] == 'adjacent' and (rec['template']['length_mm'] or 0) > 200.0:
        flags.append('rigid single-L template longer than 200 mm')
    if rec['relation'] == 'same' and rec.get('same', {}).get(
            'intermediate_port_count', 0) > 8:
        flags.append('%d same-side ports between the two U endpoints'
                     % rec['same']['intermediate_port_count'])
    return cls, flags


def main():
    L.EPS = L.load_endpoints()
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    templates = json.loads((DATA / 'geometry_1024.json').read_text(
        encoding='utf-8'))['templates']
    records = {r['route_id']: r for r in analysis['connections']}
    connections = L.load_connections()['connections']

    print('template collision analysis ...', flush=True)
    collision, collision_summary = collision_analysis(templates, connections)
    (DATA / 'collision_1024.json').write_text(
        json.dumps(dict(
            method=dict(sample_step_mm=SAMPLE_STEP, query_radius_mm=QUERY_RADIUS,
                        min_cross_angle_deg=MIN_CROSS_ANGLE_DEG),
            summary=collision_summary, routes=collision),
            ensure_ascii=False), encoding='utf-8')

    # global per-connection classes
    global_class = Counter()
    global_flags = Counter()
    per_relation_class = defaultdict(Counter)
    for rid, rec in records.items():
        cls, flags = connection_judgement(rec, collision[rid])
        rec['judgement'] = dict(
            class_=cls,
            strict90_ok=(True if rec['relation'] != 'opposite'
                         else rec['opposite']['strict_90_feasible']),
            spacing_conflict_partner_count=collision[rid]['spacing_conflict_partner_count'],
            crossing_partner_count=collision[rid]['crossing_partner_count'],
            flags=flags,
        )
        global_class[cls] += 1
        per_relation_class[rec['relation']][cls] += 1
        for flag in flags:
            global_flags[flag.split(' ')[0]] += 1
    # write the enriched per-connection analysis back
    for rid, rec in records.items():
        collision[rid] = dict(collision[rid])
    analysis['summary']['judgement_class_all'] = dict(global_class)
    analysis['summary']['judgement_class_by_relation'] = {
        rel: dict(counter) for rel, counter in per_relation_class.items()}
    analysis['summary']['collision_summary'] = collision_summary
    analysis['summary']['collision_method'] = collision['method'] if False else dict(
        sample_step_mm=SAMPLE_STEP, query_radius_mm=QUERY_RADIUS,
        min_cross_angle_deg=MIN_CROSS_ANGLE_DEG,
        note='canonical representative templates only; proxy for route conflicts')
    (OUT / 'corner_r15_analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding='utf-8')

    # ------------------------------------------------ corner connectors
    corner_sets = corner_connector_sets(L.EPS)
    all_corner = []
    for spec in corner_sets.values():
        spec['connector_set'] = set(spec['connectors'])
        all_corner.extend(spec['connectors'])
    corner_connector_set = set(all_corner)
    port_connector = {eid: ep['connector'] for eid, ep in L.EPS.items()}

    overall = dict(classes=Counter(), relations=Counter(), planes=Counter(),
                   strict90=Counter(), s_lift_limited=0, radius_limited=0,
                   spacing_conflict=0, max_spacing_partner=0,
                   by_relation_class=defaultdict(Counter))
    corners_out = {}
    all_ids = set()
    for corner, spec in corner_sets.items():
        conn_ids = set()
        for conn in connections:
            if (port_connector[conn['source_endpoint']] in spec['connector_set'] or
                    port_connector[conn['target_endpoint']] in spec['connector_set']):
                conn_ids.add(conn['route_id'])
        all_ids |= conn_ids
        entries = []
        for rid in sorted(conn_ids):
            rec = records[rid]
            cls, flags = connection_judgement(rec, collision[rid])
            entries.append(dict(
                route_id=rid, plane=rec['plane'], relation=rec['relation'],
                source_port_id=rec['source_port_id'],
                target_port_id=rec['target_port_id'],
                source_xy=rec['source_xy'], target_xy=rec['target_xy'],
                corner=corner,
                corner_connectors=sorted(
                    ({port_connector[rec['source_port_id']],
                      port_connector[rec['target_port_id']]} & spec['connector_set'])),
                template_family=rec['template']['family'],
                template_feasible=rec['template']['feasible'],
                template_length_mm=rec['template']['length_mm'],
                required_geometry=(rec.get('same') or rec.get('adjacent')
                                   or rec.get('opposite')),
                margin_mm=rec.get('margin_mm'),
                radius_status=('ok' if rec['template']['feasible'] else 'infeasible'),
                strict90_ok=(True if rec['relation'] != 'opposite'
                             else rec['opposite']['strict_90_feasible']),
                s_lift=dict(
                    max_single_dz_mm=rec['max_single_lift_dz_mm'],
                    reachable_layers=rec['s_lift']['reachable_layers'],
                    unreachable_layers=rec['s_lift']['unreachable_layers']),
                spacing_conflict_partner_count=collision[rid]['spacing_conflict_partner_count'],
                crossing_partner_count=collision[rid]['crossing_partner_count'],
                worst_spacing_partners=collision[rid]['worst_spacing_partners'],
                judgement_class=cls, flags=flags,
            ))
            overall['classes'][cls] += 1
            overall['relations'][rec['relation']] += 1
            overall['planes'][rec['plane']] += 1
            overall['by_relation_class'][rec['relation']][cls] += 1
            overall['strict90']['ok' if entries[-1]['strict90_ok']
                               else 'short_s_required'] += 1
            if rec['s_lift']['unreachable_layers']:
                overall['s_lift_limited'] += 1
            if cls == 'radius_limited_2d':
                overall['radius_limited'] += 1
            if collision[rid]['spacing_conflict_partner_count'] > 0:
                overall['spacing_conflict'] += 1
            overall['max_spacing_partner'] = max(
                overall['max_spacing_partner'],
                collision[rid]['spacing_conflict_partner_count'])

        def min_margin(rel):
            vals = [e['margin_mm'] for e in entries
                    if e['relation'] == rel and e['margin_mm'] is not None]
            return round(min(vals), 6) if vals else None

        class_lists = defaultdict(list)
        for e in entries:
            class_lists[e['judgement_class']].append(e['route_id'])
        corners_out[corner] = dict(
            corner_xy=spec['corner_xy'], sides=list(spec['sides']),
            connectors=[dict(connector=c, min_distance_to_corner_mm=d,
                             ports_physical=32, ports_row1=16, ports_row2=16)
                        for c, d in spec['connector_corner_distance'].items()],
            corner_connector_set=sorted(spec['connector_set']),
            connections=entries, connection_count=len(entries),
            relation_counts=dict(Counter(e['relation'] for e in entries)),
            plane_counts=dict(Counter(e['plane'] for e in entries)),
            judgement_counts=dict(Counter(e['judgement_class'] for e in entries)),
            judgement_by_relation={rel: dict(Counter(
                e['judgement_class'] for e in entries if e['relation'] == rel))
                for rel in sorted({e['relation'] for e in entries})},
            min_margins_mm=dict(same=min_margin('same'),
                                adjacent=min_margin('adjacent'),
                                opposite=min_margin('opposite')),
            radius_limited_connections=class_lists['radius_limited_2d'],
            pure90_limited_connections=class_lists['pure90_template_limited'],
            rigid_conflict_connections=class_lists['rigid_template_conflict_needs_3d'],
            conflict_connections=class_lists['conflict_needs_joint_search'],
            not_limited_connections=class_lists['not_limited'],
            max_spacing_conflict_partners=max(
                (e['spacing_conflict_partner_count'] for e in entries), default=0),
        )

    # per physical connector
    per_connector = {}
    for connector in sorted(corner_connector_set):
        entries = []
        for conn in connections:
            this_end = other = None
            if port_connector[conn['source_endpoint']] == connector:
                this_end, other = conn['source_endpoint'], conn['target_endpoint']
            elif port_connector[conn['target_endpoint']] == connector:
                this_end, other = conn['target_endpoint'], conn['source_endpoint']
            if this_end is None:
                continue
            rid = conn['route_id']
            rec = records[rid]
            cls, _flags = connection_judgement(rec, collision[rid])
            entries.append(dict(
                route_id=rid, plane=conn['plane'], relation=conn['relation'],
                this_port_id=this_end, other_port_id=other,
                other_connector=port_connector[other],
                margin_mm=rec.get('margin_mm'),
                judgement_class=cls,
                strict90_ok=(True if conn['relation'] != 'opposite'
                             else rec['opposite']['strict_90_feasible']),
                s_lift_unreachable_layers=rec['s_lift']['unreachable_layers'],
                spacing_conflict_partner_count=collision[rid]['spacing_conflict_partner_count'],
            ))
        per_connector[connector] = dict(
            connector=connector, physical_ports=32, connection_count=len(entries),
            relation_counts=dict(Counter(e['relation'] for e in entries)),
            judgement_counts=dict(Counter(e['judgement_class'] for e in entries)),
            entries=entries)

    payload = dict(
        schema='corner_connectors_v1',
        description=('Four board corners: the 2 nearest connectors per adjacent '
                     'side (16 physical 2x16 MPO connectors, every hole within '
                     '18.375 mm of its corner) and every connection touching '
                     'them, with R=15 mm template margins and the '
                     'radius / template-family / conflict / 3D judgement.'),
        radius_mm=L.R, board_mm=L.BOARD, clearance_mm=L.CLEARANCE,
        corner_definition='2 connectors per corner side with the smallest minimum '
                          'port-to-corner distance',
        template_definitions=dict(
            same='quarter_pair U: D = 2R + m, m >= 0',
            adjacent='single-arc L: legs = b-R / a-R, both >= 0',
            opposite=('delta=0 straight | 0<delta<2R short-S pair '
                      '(theta=acos(1-delta/2R) per arc) | delta>=2R two 90deg '
                      'arcs + middle straight delta-2R'),
        ),
        judgement_definitions=dict(
            radius_limited_2d='no 2D template in the frozen family satisfies R=15 '
                              '(proven by the listed inequality)',
            pure90_template_limited='pure two-90deg-turn template cannot generate it; '
                                    'the frozen short-S pair (arcs of theta<90deg) can',
            rigid_template_conflict_needs_3d=(
                'the single possible 2D template (adjacent L, no free parameter) '
                'has parallel spacing conflicts with other canonical templates; '
                'needs compound template or 3D layer change -> 3D search'),
            conflict_needs_joint_search=(
                'a 2D template exists but its representative geometry conflicts '
                'with other canonical templates; solvable only by joint routing '
                'search, not by single-connection geometry'),
            not_limited='template exists and representative geometry is 0.08 mm '
                        'clear of all other canonical templates',
        ),
        corners=corners_out, connectors=per_connector,
        corner_connector_ids=sorted(corner_connector_set),
        corner_connection_route_ids=sorted(all_ids),
        global_summary=dict(
            corner_connectors=len(corner_connector_set),
            corner_connections=len(all_ids),
            connections_by_relation=dict(overall['relations']),
            connections_by_plane=dict(overall['planes']),
            judgement_class=dict(overall['classes']),
            judgement_by_relation={rel: dict(c)
                                   for rel, c in overall['by_relation_class'].items()},
            strict90=dict(overall['strict90']),
            s_lift_limited=overall['s_lift_limited'],
            radius_limited=overall['radius_limited'],
            spacing_conflict_flagged=overall['spacing_conflict'],
            max_spacing_conflict_partners=overall['max_spacing_partner'],
            connections_per_corner={c: v['connection_count']
                                    for c, v in corners_out.items()},
        ),
        collision_analysis=dict(
            method=('canonical representative template centrelines sampled at '
                    '%.2f mm; KD-tree radius %.2f mm; nearby point pairs with '
                    'tangent angle < %.1f deg counted as parallel spacing '
                    'conflicts (>= %.1f deg would be permitted designed crossings)'
                    % (SAMPLE_STEP, QUERY_RADIUS, MIN_CROSS_ANGLE_DEG,
                       MIN_CROSS_ANGLE_DEG)),
            sample_step_mm=SAMPLE_STEP, query_radius_mm=QUERY_RADIUS,
            min_cross_angle_deg=MIN_CROSS_ANGLE_DEG,
            all_routes_summary=collision_summary,
        ),
    )
    (OUT / 'corner_connectors.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(
        corner_connector_ids=sorted(corner_connector_set),
        global_summary=payload['global_summary'],
        per_corner={c: dict(connectors=sorted(v['corner_connector_set']),
                            connections=v['connection_count'],
                            relations=v['relation_counts'],
                            judgement=v['judgement_counts'],
                            min_margins=v['min_margins_mm'])
                    for c, v in corners_out.items()},
        collision_summary=collision_summary,
    ), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
