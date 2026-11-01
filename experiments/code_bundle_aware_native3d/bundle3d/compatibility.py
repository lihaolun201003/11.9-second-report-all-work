"""Bundle compatibility graph over C4 orbits.

Edge weights combine geometric proximity, shared-corridor potential, endpoint
ordering compatibility, template compatibility and same-layer conflict risk.
Crossing of 2D straight chords is *not* treated as illegal; it is a cost that
lowers bundling compatibility because a bundle should avoid internal crossings
unless it plans them onto different heights.
"""
from __future__ import annotations

import math

import numpy as np


def _seg_intersect(p, q, r, s):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    o1, o2 = orient(p, q, r), orient(p, q, s)
    o3, o4 = orient(r, s, p), orient(r, s, q)
    return ((o1 > 1e-12 and o2 < -1e-12) or (o1 < -1e-12 and o2 > 1e-12)) and \
           ((o3 > 1e-12 and o4 < -1e-12) or (o3 < -1e-12 and o4 > 1e-12))


def _span_overlap(a_lo, a_hi, b_lo, b_hi):
    overlap = min(a_hi, b_hi) - max(a_lo, b_lo)
    if overlap <= 0:
        return 0.0
    union = max(a_hi, b_hi) - min(a_lo, b_lo)
    return overlap / union if union > 0 else 0.0


def _orbit_segments(orbit):
    segments = []
    for member in orbit['members']:
        segments.append((tuple(member['start_xy']), tuple(member['end_xy'])))
    return segments


def _corridor_score(a, b):
    """Kind-specific shared-band score in [0, 1]."""
    kind = a['kind']
    if kind == 'opposite':
        scores = []
        for family in ('opp_NS', 'opp_EW'):
            a_lat = [member['lateral_coord'] for member in a['members']
                     if member['family'] == family]
            b_lat = [member['lateral_coord'] for member in b['members']
                     if member['family'] == family]
            a_span = [(member['span_start'], member['span_end'])
                      for member in a['members'] if member['family'] == family]
            b_span = [(member['span_start'], member['span_end'])
                      for member in b['members'] if member['family'] == family]
            if not a_lat or not b_lat:
                continue
            lateral_gap = min(abs(x - y) for x in a_lat for y in b_lat)
            lateral_score = math.exp(-lateral_gap / 10.0)
            if a_span and b_span:
                span = _span_overlap(min(s[0] for s in a_span),
                                     max(s[1] for s in a_span),
                                     min(s[0] for s in b_span),
                                     max(s[1] for s in b_span))
            else:
                span = 0.0
            scores.append(0.6 * lateral_score + 0.4 * span)
        return max(scores) if scores else 0.0
    if kind == 'same':
        scores = []
        for family in ('u_N', 'u_E', 'u_S', 'u_W'):
            a_members = [member for member in a['members']
                         if member['family'] == family]
            b_members = [member for member in b['members']
                         if member['family'] == family]
            if not a_members or not b_members:
                continue
            a_lo = min(member['span_start'] for member in a_members)
            a_hi = max(member['span_end'] for member in a_members)
            b_lo = min(member['span_start'] for member in b_members)
            b_hi = max(member['span_end'] for member in b_members)
            overlap = _span_overlap(a_lo, a_hi, b_lo, b_hi)
            # nested or disjoint intervals are both order-compatible
            nested = (a_lo >= b_lo - 1e-9 and a_hi <= b_hi + 1e-9) or \
                     (b_lo >= a_lo - 1e-9 and b_hi <= a_hi + 1e-9)
            separation_gap = abs(a.get('separation_mm', 0.0)
                                 - b.get('separation_mm', 0.0))
            scores.append(0.45 * overlap + 0.35 * (1.0 if nested else 0.0)
                          + 0.2 * math.exp(-separation_gap / 15.0))
        return max(scores) if scores else 0.0
    # adjacent: corner occupancy + leg similarity
    leg_a = [member['adjacent_legs_mm'] for member in a['members']
             if member.get('adjacent_legs_mm')]
    leg_b = [member['adjacent_legs_mm'] for member in b['members']
             if member.get('adjacent_legs_mm')]
    corner_a = float(np.mean(a['corner_distances']))
    corner_b = float(np.mean(b['corner_distances']))
    corner_score = math.exp(-abs(corner_a - corner_b) / 20.0)
    leg_score = 0.0
    if leg_a and leg_b:
        a_mean = float(np.mean([min(pair) for pair in leg_a]))
        b_mean = float(np.mean([min(pair) for pair in leg_b]))
        leg_score = math.exp(-abs(a_mean - b_mean) / 20.0)
    bbox = _span_overlap(a['bbox']['min_x'], a['bbox']['max_x'],
                         b['bbox']['min_x'], b['bbox']['max_x']) * \
        _span_overlap(a['bbox']['min_y'], a['bbox']['max_y'],
                      b['bbox']['min_y'], b['bbox']['max_y'])
    return 0.4 * corner_score + 0.25 * leg_score + 0.35 * bbox


def orbit_pair(orbit_a, orbit_b):
    """Return the bundle-compatibility components and final weight."""
    points_a = [tuple(point) for point in orbit_a['endpoint_union']]
    points_b = [tuple(point) for point in orbit_b['endpoint_union']]
    min_port_distance = min(math.hypot(ax - bx, ay - by)
                            for ax, ay in points_a for bx, by in points_b)
    proximity = math.exp(-min_port_distance / 12.0)
    port_adjacency = 1.0 if min_port_distance < 4.0 else (
        math.exp(-(min_port_distance - 4.0) / 8.0))
    kind_same = 1.0 if orbit_a['kind'] == orbit_b['kind'] else 0.35
    corridor = _corridor_score(orbit_a, orbit_b)
    span = _span_overlap(orbit_a['bbox']['min_x'], orbit_a['bbox']['max_x'],
                         orbit_b['bbox']['min_x'], orbit_b['bbox']['max_x']) + \
        _span_overlap(orbit_a['bbox']['min_y'], orbit_a['bbox']['max_y'],
                      orbit_b['bbox']['min_y'], orbit_b['bbox']['max_y'])
    span = min(1.0, span / 2.0)
    segments_a = _orbit_segments(orbit_a)
    segments_b = _orbit_segments(orbit_b)
    crossings = 0
    for seg_a in segments_a:
        for seg_b in segments_b:
            if _seg_intersect(seg_a[0], seg_a[1], seg_b[0], seg_b[1]):
                crossings += 1
    crossing_rate = crossings / (len(segments_a) * len(segments_b))
    # expected same-layer overlap risk: parallel y-overlap of opposite orbits
    overlap_risk = 0.0
    if orbit_a['kind'] == orbit_b['kind'] == 'opposite':
        overlap_risk = min(1.0, abs(orbit_a['lateral_span']
                                    - orbit_b['lateral_span']) / 20.0)
    weight = (0.28 * kind_same + 0.24 * corridor + 0.14 * span
              + 0.12 * proximity + 0.10 * port_adjacency
              - 0.55 * crossing_rate - 0.10 * overlap_risk)
    weight = max(0.0, min(1.0, weight))
    return dict(weight=weight, kind_same=kind_same, corridor=corridor,
                span=span, proximity=proximity,
                port_adjacency=port_adjacency, crossing_rate=crossing_rate,
                overlap_risk=overlap_risk,
                min_port_distance_mm=min_port_distance)


def build_graph(orbits, max_neighbors=12, threshold=0.35):
    """Sparse weighted compatibility graph (dict of dicts)."""
    adjacency = {int(orbit['orbit_id']): {} for orbit in orbits}
    edges = []
    for index, orbit_a in enumerate(orbits):
        for orbit_b in orbits[index + 1:]:
            if orbit_a['plane'] != orbit_b['plane']:
                continue
            pair = orbit_pair(orbit_a, orbit_b)
            if pair['weight'] < threshold:
                continue
            key_a, key_b = int(orbit_a['orbit_id']), int(orbit_b['orbit_id'])
            adjacency[key_a][key_b] = pair['weight']
            adjacency[key_b][key_a] = pair['weight']
            edges.append(dict(a=key_a, b=key_b, plane=orbit_a['plane'],
                              **{k: (round(v, 6) if isinstance(v, float) else v)
                                 for k, v in pair.items()}))
    # prune to max_neighbors strongest neighbours (symmetric cores kept)
    for orbit_id, neighbours in adjacency.items():
        if len(neighbours) <= max_neighbors:
            continue
        keep = set(sorted(neighbours, key=lambda key: -neighbours[key])[:max_neighbors])
        for other in list(neighbours):
            if other not in keep:
                neighbours.pop(other)
    edges.sort(key=lambda edge: -edge['weight'])
    return adjacency, edges
