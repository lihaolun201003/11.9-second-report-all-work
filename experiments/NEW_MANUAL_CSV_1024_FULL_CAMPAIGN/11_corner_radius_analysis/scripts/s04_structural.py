# -*- coding: utf-8 -*-
"""Step 4: rigorous family-capacity / rigid-template conflict analysis.

Three structural results that single-connection geometry cannot see:

A. same-side U family capacity (frozen r15.u_geometry ladder)
   The frozen U family only offers bulge values {0, R/2, R, 2R}; therefore the
   horizontal middle straight of a U lies on one of only four depth tracks
   {R, 1.5R, 2R, 3R} = {15, 22.5, 30, 45} mm.  Two U-turns of the same plane and
   side whose middle-straight x-intervals overlap and which sit on the same depth
   track are exactly coincident (distance 0 < 0.08 mm clearance).  Sweeping the
   intervals gives the maximum number of U-turns whose middle straights contain a
   common x: if that number exceeds 4, at least two of them must share a depth
   track (pigeonhole) and their centrelines are provably coincident
   -> the family alone cannot route that side; ordering / layer changes are needed.

B. adjacent rigid single-L conflicts
   The frozen single-arc L of an adjacent pair is uniquely determined by the two
   ports (one arc, both legs fixed).  Sampling the 400 unique L centrelines of the
   z2 plane and measuring pairwise distance shows pairs that coincide / come
   closer than the 0.08 mm clearance.  Those pairs cannot both use the canonical
   2D L template in the same layer (alternative compound templates or a layer
   change are required).

C. opposite transfer flexibility
   For an opposite pair the two-arc short-S / quarter-arc transfer can slide along
   the 150 mm corridor (free s1), so no pair is rigidly forced to overlap unless a
   delta = 0 full straight shares the x/y slot of another route's port lead; that
   case is counted explicitly (expected 0).

Rewrites ``corner_r15_analysis.json`` and ``corner_connectors.json`` with the
structural evidence attached.
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

CLEARANCE = L.CLEARANCE
SAMPLE_STEP = 0.05          # mm for the rigid-conflict distance check
QUERY_RADIUS = CLEARANCE + SAMPLE_STEP   # conservative detection radius
MIN_CROSS_ANGLE_DEG = 5.0   # frozen project policy: crossings below this are rejected
U_DEPTH_TRACKS = (L.R, 1.5 * L.R, 2.0 * L.R, 3.0 * L.R)


# ---------------------------------------------------------------------------
# A. same-side U family capacity
# ---------------------------------------------------------------------------
def same_u_capacity(records):
    """Middle-straight interval sweep per plane/side + per-connection blockers."""
    per_side = defaultdict(list)
    for rec in records:
        if rec['relation'] != 'same':
            continue
        xy_s, xy_t = rec['source_xy'], rec['target_xy']
        if rec['source_side'] in 'NS':
            a, b = xy_s[0], xy_t[0]
        else:
            a, b = xy_s[1], xy_t[1]
        lo, hi = min(a, b), max(a, b)
        key = (rec['plane'], rec['source_side'])
        per_side[key].append(dict(route_id=rec['route_id'],
                                  interval_lo=round(lo + L.R, 6),
                                  interval_hi=round(hi - L.R, 6),
                                  separation=round(hi - lo, 6)))
    summary = {}
    blockers = {}
    for key, items in sorted(per_side.items()):
        events = []
        for item in items:
            events.append((item['interval_lo'], 1, item['route_id']))
            events.append((item['interval_hi'], -1, item['route_id']))
        # half-open intervals; tolerance to keep touching intervals separate
        events.sort(key=lambda e: (e[0], -e[1]))
        active = 0
        max_active = 0
        max_at = None
        cover = []                     # (x, coverage) breakpoints
        for x, delta, _rid in events:
            active += delta
            if active > max_active:
                max_active = active
                max_at = x
            cover.append((round(x, 6), active))
        # per connection: # other U's with overlapping middle interval
        blockers_local = Counter()
        for i, a in enumerate(items):
            count = 0
            for j, b in enumerate(items):
                if i == j:
                    continue
                if (a['interval_lo'] < b['interval_hi'] - 1e-9 and
                        b['interval_lo'] < a['interval_hi'] - 1e-9):
                    count += 1
            blockers[a['route_id']] = count
            blockers_local[count] += 1
        summary[f'{key[0]}_{key[1]}'] = dict(
            plane=key[0], side=key[1], u_count=len(items),
            depth_tracks=list(U_DEPTH_TRACKS),
            max_middle_interval_coverage=max_active,
            max_coverage_at_x=max_at,
            pigeonhole_conflict_provable=max_active > len(U_DEPTH_TRACKS),
            coverage_breakpoints=cover,
            blocker_histogram=dict(sorted(blockers_local.items())),
        )
    return summary, blockers


# ---------------------------------------------------------------------------
# B. adjacent rigid single-L pair distances
# ---------------------------------------------------------------------------
def sample_template_pts(template, step=SAMPLE_STEP):
    """(points, unit tangents) samples; arcs at 0.05 mm arc length."""
    pts, tans = [], []
    for prim in template['primitives']:
        if prim['kind'] == 'line':
            p0 = np.asarray(prim['p0'], dtype=float)
            p1 = np.asarray(prim['p1'], dtype=float)
            delta = p1 - p0
            length = float(np.hypot(*delta))
            direction = delta / length if length > 0 else np.array([1.0, 0.0])
            n = max(2, int(math.ceil(length / step)) + 1)
            t = np.linspace(0, 1, n)[:, None]
            pts.append(p0 + t * delta)
            tans.append(np.repeat(direction[None, :], n, axis=0))
        else:
            radius = float(prim['radius'])
            sweep = float(prim['sweep'])
            center = np.asarray(prim['center'], dtype=float)
            start = float(prim['start_angle'])
            n = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
            angles = start + np.linspace(0.0, sweep, n)
            pts.append(center + radius * np.stack(
                [np.cos(angles), np.sin(angles)], axis=1))
            sign = 1.0 if sweep > 0 else -1.0
            tans.append(sign * np.stack([-np.sin(angles),
                                         np.cos(angles)], axis=1))
    if not pts:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.vstack(pts), np.vstack(tans)


def adjacent_rigid_conflicts(templates, connections, step=SAMPLE_STEP):
    """Parallel (spacing) conflicts between the 400 unique single-arc L routes."""
    adj = [c for c in connections if c['relation'] == 'adjacent']
    ids = [c['route_id'] for c in adj]
    pts_all, tan_all, owners = [], [], []
    for rid in ids:
        p, t = sample_template_pts(templates[str(rid)], step)
        pts_all.append(p)
        tan_all.append(t)
        owners.append(np.full(len(p), rid, dtype=np.int32))
    pts = np.vstack(pts_all)
    tans = np.vstack(tan_all)
    owners = np.concatenate(owners)
    tree = cKDTree(pts)
    query_radius = CLEARANCE + step
    pair_hits = {}          # (a,b) -> #query samples of a that are parallel-close to b
    pair_min = {}
    chunk = 200000
    for start in range(0, len(pts), chunk):
        q = pts[start:start + chunk]
        qt = tans[start:start + chunk]
        hits = tree.query_ball_point(q, r=query_radius, workers=-1)
        for local, hit_idx in enumerate(hits):
            if not hit_idx:
                continue
            rid = int(owners[start + local])
            d0 = q[local]
            t0 = qt[local]
            best = {}
            for index in hit_idx:
                other = int(owners[index])
                if other == rid:
                    continue
                d = float(np.hypot(*(d0 - pts[index])))
                if d >= CLEARANCE:
                    continue
                t1 = tans[index]
                cross = t0[0] * t1[1] - t0[1] * t1[0]
                dot = float(t0[0] * t1[0] + t0[1] * t1[1])
                angle = abs(math.degrees(math.atan2(cross, dot)))
                angle = min(angle, 180.0 - angle)
                if angle >= MIN_CROSS_ANGLE_DEG:
                    continue                     # permitted designed crossing
                if d < best.get(other, 1e9):
                    best[other] = d
            for other, d in best.items():
                if rid > other:
                    continue
                key = (rid, other)
                pair_hits[key] = pair_hits.get(key, 0) + 1
                if d < pair_min.get(key, 1e9):
                    pair_min[key] = d
    SUBSTANTIAL = int(round(1.0 / step))     # >= 1 mm of parallel coincidence
    substantial = {k: v for k, v in pair_hits.items() if v >= SUBSTANTIAL}
    per_route = defaultdict(list)
    for (a, b), hits in sorted(substantial.items(), key=lambda kv: -kv[1]):
        entry = dict(other=b, overlap_samples=int(hits),
                     overlap_length_mm=round(hits * step, 3),
                     min_distance_mm=round(pair_min[(a, b)], 6))
        per_route[a].append(entry)
        entry2 = dict(entry)
        entry2['other'] = a
        per_route[b].append(entry2)
    info = {rid: dict(
        rigid_conflict_partner_count=len(per_route.get(rid, [])),
        severe_rigid_partner_count=sum(
            1 for e in per_route.get(rid, []) if e['overlap_length_mm'] >= 10.0),
        max_rigid_overlap_mm=max(
            (e['overlap_length_mm'] for e in per_route.get(rid, [])), default=0.0),
        worst_rigid_partners=sorted(
            per_route.get(rid, []),
            key=lambda e: -e['overlap_length_mm'])[:8])
        for rid in ids}
    summary = dict(
        method=('all 400 unique single-arc L centrelines sampled at %.2f mm; '
                'point pairs closer than %.2f mm whose tangent angle is '
                '< %.1f deg (parallel) are counted; a pair with >= 1 mm of such '
                'parallel coincidence is reported as a substantial rigid-template '
                'conflict (crossings are permitted and not counted)'
                % (step, CLEARANCE, MIN_CROSS_ANGLE_DEG)),
        adjacent_routes=len(ids),
        substantial_conflict_pairs=len(substantial),
        routes_with_rigid_conflict=len(per_route),
        routes_with_severe_conflict=sum(
            1 for rid in ids if info[rid]['severe_rigid_partner_count'] > 0),
        min_pair_distance_mm=round(min(pair_min.values()), 6) if pair_min else None,
        max_overlap_mm=max((e['overlap_length_mm']
                            for entries in per_route.values()
                            for e in entries), default=0.0),
        sample_pairs=[dict(a=int(a), b=int(b),
                           overlap_mm=round(hits * step, 3),
                           min_distance_mm=round(pair_min[(a, b)], 6))
                      for (a, b), hits in sorted(
                          substantial.items(), key=lambda kv: -kv[1])[:12]],
    )
    return info, summary


# ---------------------------------------------------------------------------
# C. opposite transfer flexibility
# ---------------------------------------------------------------------------
def opposite_forced_conflicts(records):
    """Opposite routes whose *mandatory* straight segment forces a coincidence."""
    opp = [r for r in records if r['relation'] == 'opposite']
    straights = []
    for rec in opp:
        if rec['opposite']['delta_mm'] <= 1e-9:
            # full straight along the travel axis, no free parameter
            if rec['source_side'] in 'NS':
                straights.append(dict(route_id=rec['route_id'], axis='x',
                                      coordinate=round(rec['source_xy'][0], 6),
                                      lo=0.0, hi=150.0))
            else:
                straights.append(dict(route_id=rec['route_id'], axis='y',
                                      coordinate=round(rec['source_xy'][1], 6),
                                      lo=0.0, hi=150.0))
        else:
            # port leads are mandatory at the two port coordinates (length >= 0
            # can be chosen freely, so only a port-slot coincidence is rigid)
            if rec['source_side'] in 'NS':
                straights.append(dict(route_id=rec['route_id'], axis='x',
                                      coordinate=round(rec['source_xy'][0], 6),
                                      lo=None, hi=None))
                straights.append(dict(route_id=rec['route_id'], axis='x',
                                      coordinate=round(rec['target_xy'][0], 6),
                                      lo=None, hi=None))
            else:
                straights.append(dict(route_id=rec['route_id'], axis='y',
                                      coordinate=round(rec['source_xy'][1], 6),
                                      lo=None, hi=None))
                straights.append(dict(route_id=rec['route_id'], axis='y',
                                      coordinate=round(rec['target_xy'][1], 6),
                                      lo=None, hi=None))
    forced = []
    for i, a in enumerate(straights):
        for b in straights[i + 1:]:
            if a['axis'] != b['axis'] or a['route_id'] == b['route_id']:
                continue
            if abs(a['coordinate'] - b['coordinate']) > 1e-9:
                continue
            # same x/y slot: only rigid if at least one side is a full straight
            if (a['lo'] is not None and b['lo'] is not None):
                forced.append(dict(a=a['route_id'], b=b['route_id'],
                                   axis=a['axis'], slot=a['coordinate']))
            elif a['lo'] is not None or b['lo'] is not None:
                forced.append(dict(a=a['route_id'], b=b['route_id'],
                                   axis=a['axis'], slot=a['coordinate'],
                                   reason='full_straight_blocks_port_lead'))
    return forced


def main():
    L.EPS = L.load_endpoints()
    analysis = json.loads((OUT / 'corner_r15_analysis.json').read_text(encoding='utf-8'))
    corner = json.loads((OUT / 'corner_connectors.json').read_text(encoding='utf-8'))
    templates = json.loads((DATA / 'geometry_1024.json').read_text(
        encoding='utf-8'))['templates']
    records = analysis['connections']
    rec_by_id = {r['route_id']: r for r in records}
    connections = L.load_connections()['connections']

    print('A. same-side U family capacity ...', flush=True)
    u_summary, u_blockers = same_u_capacity(records)
    for key, value in u_summary.items():
        print(f'  {key}: {value["u_count"]} U, max interval coverage '
              f'{value["max_middle_interval_coverage"]}, pigeonhole '
              f'{value["pigeonhole_conflict_provable"]}')
    analysis['same_u_family_capacity'] = dict(
        depth_tracks_mm=list(U_DEPTH_TRACKS),
        argument=('frozen r15.u_geometry U candidates only use bulge in '
                  '{0, R/2, R, 2R}, so middle straights lie on 4 depth tracks; '
                  'more than 4 overlapping middle-straight intervals at one x '
                  '=> pigeonhole => two centrelines coincide => family alone '
                  'cannot route that side'),
        per_plane_side=u_summary,
    )
    for rec in records:
        if rec['relation'] != 'same':
            continue
        side = rec['source_side']
        key = f'{rec["plane"]}_{side}'
        value = u_summary[key]
        rec['same']['family_blockers_same_side'] = int(u_blockers[rec['route_id']])
        rec['same']['family_depth_tracks'] = list(U_DEPTH_TRACKS)
        rec['same']['side_max_interval_coverage'] = value['max_middle_interval_coverage']
        rec['same']['family_capacity_conflict_provable'] = (
            value['pigeonhole_conflict_provable'])

    print('B. adjacent rigid single-L conflicts ...', flush=True)
    adj_info, adj_summary = adjacent_rigid_conflicts(templates, connections)
    print(json.dumps(adj_summary, ensure_ascii=False, indent=1)[:1500], flush=True)
    analysis['adjacent_rigid_template'] = adj_summary
    for rec in records:
        if rec['relation'] != 'adjacent':
            continue
        info = adj_info[rec['route_id']]
        rec['adjacent']['rigid_conflict_partner_count'] = \
            info['rigid_conflict_partner_count']
        rec['adjacent']['worst_rigid_partners'] = info['worst_rigid_partners']
        rec['adjacent']['rigid_template_unique'] = True

    print('C. opposite forced conflicts ...', flush=True)
    forced = opposite_forced_conflicts(records)
    analysis['opposite_forced_conflicts'] = dict(
        forced_pairs=len(forced), examples=forced[:10],
        note=('delta=0 straight routes are rigid; a route whose port sits on the '
              'same slot is blocked. Non-zero delta transfers slide freely along '
              'the 150 mm corridor (free s1), so no rigid pair conflict is '
              'forced by single-connection geometry.'),
    )
    print('   forced pairs:', len(forced))

    # ------------------------------------------------------------------
    # re-classify every connection with the structural evidence
    # ------------------------------------------------------------------
    classes = Counter()
    by_relation = defaultdict(Counter)
    for rec in records:
        rid = rec['route_id']
        cls = None
        if not rec['template']['feasible']:
            cls = 'radius_limited_2d'
        elif rec['relation'] == 'opposite' and not rec['opposite']['strict_90_feasible']:
            cls = 'pure90_template_limited'
        elif rec['relation'] == 'adjacent' and \
                rec['adjacent']['rigid_conflict_partner_count'] > 0:
            cls = 'rigid_template_conflict'
        elif rec['relation'] == 'same' and \
                rec['same']['family_capacity_conflict_provable']:
            cls = 'same_u_family_capacity_limited'
        elif rec['relation'] == 'same' and \
                rec.get('judgement', {}).get('spacing_conflict_partner_count', 0) > 0:
            cls = 'conflict_needs_joint_search'
        elif rec['s_lift']['unreachable_layers']:
            cls = 'lift_limited'
        elif rec.get('judgement', {}).get('spacing_conflict_partner_count', 0) > 0:
            cls = 'conflict_needs_joint_search'
        else:
            cls = 'not_limited'
        rec['judgement']['class_'] = cls
        classes[cls] += 1
        by_relation[rec['relation']][cls] += 1
    analysis['summary']['judgement_class_all'] = dict(classes)
    analysis['summary']['judgement_class_by_relation'] = {
        rel: dict(c) for rel, c in by_relation.items()}
    analysis['summary']['judgement_definitions'] = dict(
        radius_limited_2d='no template of the frozen family reaches R=15 (proven '
                          'by the per-connection inequality)',
        pure90_template_limited='pure two-90deg-turn template cannot generate the '
                                'connection; the frozen two-arc short-S pair can',
        rigid_template_conflict='the unique single-arc L of this adjacent pair '
                                'comes closer than 0.08 mm to another unique '
                                'single-arc L; both cannot share one layer -> '
                                'alternative template or 3D layer needed',
        same_u_family_capacity_limited=('the frozen U family has only 4 middle-'
                                        'straight depth tracks and this side has '
                                        'more overlapping U intervals than tracks '
                                        '-> pigeonhole proves unavoidable '
                                        'coincidence; ordering/layer change needed'),
        conflict_needs_joint_search='template exists with free parameters but the '
                                    'representative geometry conflicts; joint '
                                    'routing search needed (not single-connection '
                                    'geometry)',
        lift_limited='2D template exists but no straight is long enough for the '
                     'vertical S-lift to some routing layer',
        not_limited='template exists and representative geometry is clean',
    )
    analysis['summary']['structural_categories'] = dict(
        radius_limited_2d=classes.get('radius_limited_2d', 0),
        template_family_limited=classes.get('pure90_template_limited', 0),
        rigid_template_conflict=classes.get('rigid_template_conflict', 0),
        same_u_family_capacity_limited=classes.get(
            'same_u_family_capacity_limited', 0),
        conflict_needs_joint_search=classes.get('conflict_needs_joint_search', 0),
        lift_limited=classes.get('lift_limited', 0),
        not_limited=classes.get('not_limited', 0),
    )
    (OUT / 'corner_r15_analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding='utf-8')

    # ------------------------------------------------- corner re-classification
    corner.setdefault('structural_analysis', {})
    corner['structural_analysis'] = dict(
        same_u_family_capacity=dict(
            depth_tracks_mm=list(U_DEPTH_TRACKS),
            per_plane_side=u_summary,
        ),
        adjacent_rigid_template=adj_summary,
        opposite_forced_conflicts=dict(forced_pairs=len(forced)),
        template_definitions=analysis['summary'].get('judgement_definitions'),
    )
    total_classes = Counter()
    total_by_relation = defaultdict(Counter)
    corner_ids = set(corner['corner_connection_route_ids'])
    for rid in corner_ids:
        rec = rec_by_id[rid]
        total_classes[rec['judgement']['class_']] += 1
        total_by_relation[rec['relation']][rec['judgement']['class_']] += 1
    for corner_name, corner_entry in corner['corners'].items():
        for entry in corner_entry['connections']:
            rec = rec_by_id[entry['route_id']]
            cls = rec['judgement']['class_']
            entry['judgement_class'] = cls
            entry['same_side_family_blockers'] = (
                rec['same']['family_blockers_same_side']
                if rec['relation'] == 'same' else None)
            entry['side_max_interval_coverage'] = (
                rec['same']['side_max_interval_coverage']
                if rec['relation'] == 'same' else None)
            entry['rigid_conflict_partner_count'] = (
                rec['adjacent']['rigid_conflict_partner_count']
                if rec['relation'] == 'adjacent' else None)
            entry['judgement'] = rec['judgement']
        counts = Counter(e['judgement_class']
                         for e in corner_entry['connections'])
        corner_entry['judgement_counts'] = dict(counts)
        corner_entry['judgement_by_relation'] = {
            rel: dict(Counter(e['judgement_class']
                              for e in corner_entry['connections']
                              if e['relation'] == rel))
            for rel in ('same', 'adjacent', 'opposite')}
        corner_entry['same_family_capacity'] = dict(
            max_side_interval_coverage=max(
                (e['side_max_interval_coverage'] or 0
                 for e in corner_entry['connections']), default=0))
    corner['global_summary']['judgement_class'] = dict(total_classes)
    corner['global_summary']['judgement_by_relation'] = {
        rel: dict(c) for rel, c in total_by_relation.items()}
    unique_ids = sorted(corner_ids)
    rel_unique = Counter(rec_by_id[rid]['relation'] for rid in unique_ids)
    plane_unique = Counter(rec_by_id[rid]['plane'] for rid in unique_ids)
    strict_unique = Counter(
        'ok' if (rec_by_id[rid]['relation'] != 'opposite' or
                 rec_by_id[rid]['opposite']['strict_90_feasible'])
        else 'short_s_required' for rid in unique_ids)
    corner['global_summary'].update(
        corner_connections=len(unique_ids),
        connections_by_relation=dict(rel_unique),
        connections_by_plane=dict(plane_unique),
        strict90=dict(strict_unique),
        s_lift_limited=sum(1 for rid in unique_ids
                           if rec_by_id[rid]['s_lift']['unreachable_layers']),
        radius_limited=total_classes.get('radius_limited_2d', 0),
        spacing_conflict_flagged=sum(
            1 for rid in unique_ids
            if rec_by_id[rid].get('judgement', {}).get(
                'spacing_conflict_partner_count', 0) > 0),
        max_spacing_conflict_partners=max(
            (rec_by_id[rid].get('judgement', {}).get(
                'spacing_conflict_partner_count', 0) for rid in unique_ids),
            default=0),
        incidence_counts=dict(
            corner_connection_incidences=sum(
                v['connection_count'] for v in corner['corners'].values()),
            connections_by_relation=dict(Counter(
                e['relation'] for v in corner['corners'].values()
                for e in v['connections'])),
            note='a connection between two corner connectors of different '
                 'corners is listed once per corner; unique counts are above'),
    )
    corner['global_summary']['structural_evidence'] = dict(
        radius_limited=0,
        pure90_template_limited=total_classes.get('pure90_template_limited', 0),
        rigid_template_conflict=total_classes.get('rigid_template_conflict', 0),
        same_u_family_capacity_limited=total_classes.get(
            'same_u_family_capacity_limited', 0),
        conflict_needs_joint_search=total_classes.get(
            'conflict_needs_joint_search', 0),
        lift_limited=total_classes.get('lift_limited', 0),
        not_limited=total_classes.get('not_limited', 0),
    )
    (OUT / 'corner_connectors.json').write_text(
        json.dumps(corner, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(
        judgement_class_all=dict(classes),
        by_relation={rel: dict(c) for rel, c in by_relation.items()},
        corner_judgement=dict(total_classes),
        adjacent_summary=adj_summary,
    ), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
