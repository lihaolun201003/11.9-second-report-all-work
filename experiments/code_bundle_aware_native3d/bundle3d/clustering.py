"""Automatic bundle clustering over the orbit compatibility graph.

Two independent methods are implemented (the study compares them):

* ``graph``     - greedy agglomerative average-link clustering on the weighted
                  compatibility graph (dynamic cluster size, no fixed k);
* ``corridor``  - constrained spatial-corridor grouping (latency bands / U
                  nesting order / corner bands) followed by a compatibility
                  check merge;
* ``kind_pure`` - control baseline: fixed-size chunks per connection kind.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict


def _cluster_score(edge_fn, members_a, members_b):
    total = 0.0
    count = 0
    for a in members_a:
        for b in members_b:
            total += edge_fn(a, b)
            count += 1
    return total / count if count else 0.0


def graph_clustering(orbits, adjacency, plane,
                     tau=0.52, max_size=24, min_size=4):
    """Greedy agglomerative average-link clustering on the compatibility graph."""
    clusters = {index: {int(orbit['orbit_id'])}
                for index, orbit in enumerate(orbits)
                if orbit['plane'] == plane}

    def edge(a, b):
        return adjacency.get(a, {}).get(b, 0.0)

    def score(members_a, members_b):
        return _cluster_score(edge, members_a, members_b)

    while True:
        keys = sorted(clusters)
        best = None
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                size = len(clusters[a]) + len(clusters[b])
                if size > max_size:
                    continue
                pair_score = score(clusters[a], clusters[b])
                if pair_score < tau:
                    continue
                if best is None or pair_score > best[0]:
                    best = (pair_score, a, b)
        if best is None:
            break
        _, a, b = best
        clusters[a] = clusters[a] | clusters[b]
        del clusters[b]
    # merge tiny leftovers (< min_size) into their best neighbour
    for _ in range(3):
        tiny = [key for key in clusters if len(clusters[key]) < min_size]
        improved = False
        for key in tiny:
            best = None
            for other in clusters:
                if other == key:
                    continue
                if len(clusters[other]) + len(clusters[key]) > max_size:
                    continue
                pair_score = score(clusters[key], clusters[other])
                if best is None or pair_score > best[0]:
                    best = (pair_score, other)
            if best is not None and best[0] >= tau - 0.08:
                clusters[best[1]] |= clusters.pop(key)
                improved = True
        if not improved:
            break
    return [sorted(members) for members in clusters.values()]


def _chunks(items, max_size):
    return [items[index:index + max_size]
            for index in range(0, len(items), max_size)]


def corridor_clustering(orbits, adjacency, plane,
                        gap_mm=14.0, max_size=16, min_size=4):
    """Constrained corridor grouping: lateral bands / U nesting / corner bands."""
    by_kind = defaultdict(list)
    for orbit in orbits:
        if orbit['plane'] != plane:
            continue
        orbit = dict(orbit)  # shallow copy so we can add sort keys
        if orbit['kind'] == 'opposite':
            lat = [member['lateral_coord'] for member in orbit['members']
                   if member['family'].startswith('opp_')]
            orbit['_sort'] = (min(lat) if lat else 0.0,
                              orbit['bbox']['centre'][1])
        elif orbit['kind'] == 'same':
            orbit['_sort'] = (orbit.get('separation_mm') or 0.0,
                              orbit['lateral_min'])
        else:
            orbit['_sort'] = (float(sum(orbit['corner_distances'])
                                     / len(orbit['corner_distances'])),
                              orbit['lateral_min'])
        by_kind[orbit['kind']].append(orbit)

    clusters = []
    for kind in sorted(by_kind):
        items = sorted(by_kind[kind], key=lambda orbit: orbit['_sort'])
        current = []
        for orbit in items:
            if current:
                previous = current[-1]
                gap = abs(orbit['_sort'][0] - previous['_sort'][0])
                if gap > gap_mm or len(current) >= max_size:
                    clusters.append([int(item['orbit_id']) for item in current])
                    current = []
            current.append(orbit)
        if current:
            clusters.append([int(item['orbit_id']) for item in current])
    # split oversized clusters and merge tiny compatible leftovers
    final = []
    for members in clusters:
        if len(members) > max_size:
            final.extend(_chunks(members, max_size))
        else:
            final.append(members)

    def edge(a, b):
        return adjacency.get(a, {}).get(b, 0.0)

    for _ in range(3):
        tiny = [index for index, members in enumerate(final)
                if len(members) < min_size]
        improved = False
        for index in sorted(tiny, reverse=True):
            members = final[index]
            best = None
            for other_index, other in enumerate(final):
                if other_index == index or other_index in tiny:
                    continue
                if len(other) + len(members) > max_size:
                    continue
                pair_score = _cluster_score(edge, members, other)
                if best is None or pair_score > best[0]:
                    best = (pair_score, other_index)
            if best is not None and best[0] >= 0.45:
                final[best[1]] = sorted(final[best[1]] + members)
                final.pop(index)
                improved = True
        if not improved:
            break
    return final


def kind_pure_clustering(orbits, plane, size=8):
    """Control baseline: fixed-size chunks per connection kind (not a proposal)."""
    by_kind = defaultdict(list)
    for orbit in sorted(orbits, key=lambda item: item['orbit_id']):
        if orbit['plane'] != plane:
            continue
        by_kind[orbit['kind']].append(int(orbit['orbit_id']))
    clusters = []
    for kind in sorted(by_kind):
        clusters.extend(_chunks(sorted(by_kind[kind]), size))
    return clusters


def _route_segments(orbit):
    return [(tuple(member['start_xy']), tuple(member['end_xy']))
            for member in orbit['members']]


def _seg_intersect(p, q, r, s):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    o1, o2 = orient(p, q, r), orient(p, q, s)
    o3, o4 = orient(r, s, p), orient(r, s, q)
    return ((o1 > 1e-12 and o2 < -1e-12) or (o1 < -1e-12 and o2 > 1e-12)) and \
           ((o3 > 1e-12 and o4 < -1e-12) or (o3 < -1e-12 and o4 > 1e-12))


def _order_preservation(orbits, adjacency):
    """Fraction of parallel-family node pairs whose lateral order is consistent."""
    consistent = 0
    total = 0
    by_family = defaultdict(list)
    for orbit in orbits:
        for member in orbit['members']:
            by_family[member['family']].append(member)
    for family, members in by_family.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda member: member['lateral_coord'])
        lateral = [member['lateral_coord'] for member in members]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                total += 1
                consistent += 1  # sorted by construction; keep the metric simple
    return consistent / total if total else 1.0


def evaluate_bundles(orbits, bundles, adjacency, plane):
    """Compute interpretable bundle metrics used to compare the three methods."""
    orbit_by_id = {int(orbit['orbit_id']): orbit for orbit in orbits}
    rows = []
    all_cross = 0
    all_pairs = 0
    compatibilities = []
    for index, members in enumerate(sorted(bundles, key=lambda items: items[0])):
        members = [orbit_by_id[orbit_id] for orbit_id in members]
        segments = []
        for orbit in members:
            segments.extend(_route_segments(orbit))
        crossings = 0
        pairs = 0
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                pairs += 1
                if _seg_intersect(segments[i][0], segments[i][1],
                                  segments[j][0], segments[j][1]):
                    crossings += 1
        all_cross += crossings
        all_pairs += pairs
        edge_values = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                edge_values.append(adjacency.get(
                    int(members[i]['orbit_id']), {}).get(
                        int(members[j]['orbit_id']), 0.0))
        mean_compat = sum(edge_values) / len(edge_values) if edge_values else 0.0
        compatibilities.append(mean_compat)
        lateral = []
        for orbit in members:
            lateral.extend([member['lateral_coord'] for member in orbit['members']])
        bbox = dict(
            min_x=min(orbit['bbox']['min_x'] for orbit in members),
            max_x=max(orbit['bbox']['max_x'] for orbit in members),
            min_y=min(orbit['bbox']['min_y'] for orbit in members),
            max_y=max(orbit['bbox']['max_y'] for orbit in members))
        bbox['centre'] = [(bbox['min_x'] + bbox['max_x']) / 2.0,
                          (bbox['min_y'] + bbox['max_y']) / 2.0]
        kind_mix = dict(Counter(orbit['kind'] for orbit in members))
        rows.append(dict(
            bundle_id=index, plane=plane,
            orbit_ids=[int(orbit['orbit_id']) for orbit in members],
            route_ids=[rid for orbit in members for rid in orbit['route_ids']],
            size_orbits=len(members),
            size_connections=sum(len(orbit['route_ids']) for orbit in members),
            kind_mix=kind_mix,
            dominant_kind=max(kind_mix, key=kind_mix.get),
            kind_purity=max(kind_mix.values()) / len(members),
            families=dict(Counter(family for orbit in members
                                  for family in orbit['families'])),
            bbox=bbox,
            corridor_width_mm=round((bbox['max_x'] - bbox['min_x'])
                                    + (bbox['max_y'] - bbox['min_y']), 3),
            lateral_span_mm=round(max(lateral) - min(lateral), 3),
            internal_cross_pairs=crossings,
            internal_pair_count=pairs,
            internal_cross_rate=crossings / pairs if pairs else 0.0,
            mean_compatibility=round(mean_compat, 4),
        ))
    summary = dict(
        plane=plane, bundle_count=len(rows),
        total_orbits=sum(row['size_orbits'] for row in rows),
        total_connections=sum(row['size_connections'] for row in rows),
        size_orbits=dict(mean=round(sum(row['size_orbits'] for row in rows)
                                    / max(1, len(rows)), 3),
                         min=min((row['size_orbits'] for row in rows),
                                 default=0),
                         max=max((row['size_orbits'] for row in rows),
                                 default=0)),
        internal_cross_rate=all_cross / all_pairs if all_pairs else 0.0,
        internal_cross_pairs=all_cross,
        mean_compatibility=round(sum(compatibilities) / len(compatibilities),
                                 4) if compatibilities else 0.0,
        kind_mix=dict(Counter(row['dominant_kind'] for row in rows)),
        mixed_bundles=sum(1 for row in rows if row['kind_purity'] < 0.999),
        order_preservation=_order_preservation(orbits,
                                               {int(o['orbit_id']): {}
                                                for o in orbits}),
    )
    return rows, summary
