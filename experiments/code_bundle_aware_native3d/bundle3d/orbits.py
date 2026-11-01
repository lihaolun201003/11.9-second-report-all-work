"""Orbit-level views of the 1024 connections.

Because the new manual design is 4-fold rotationally symmetric and Z2 must keep
strict C4, the atomic planning object is a C4 rotation orbit (4 connections).
Bundles are sets of *orbits*; this way every bundle decision is automatically
C4-closed and a bundle's spatial corridor is rotationally replicated.
"""
from __future__ import annotations

import math
from collections import Counter

from .features import PLANE_Z, CORNERS


def _bbox(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return dict(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys),
                width=max(xs) - min(xs), height=max(ys) - min(ys),
                centre=[(min(xs) + max(xs)) / 2.0,
                        (min(ys) + max(ys)) / 2.0])


def build_orbits(features, group_of_route, c4_groups):
    """Build one feature record per C4 rotation orbit."""
    by_group = {}
    for feature in features:
        by_group.setdefault(feature['group_id'], []).append(feature)
    orbits = []
    for group_id in sorted(by_group):
        members = sorted(by_group[group_id], key=lambda item: item['route_id'])
        group = c4_groups[group_id]
        kind = group['kind']
        plane = group['plane']
        starts = [tuple(member['start_xy']) for member in members]
        ends = [tuple(member['end_xy']) for member in members]
        points = starts + ends
        orbit = dict(
            orbit_id=int(group_id), plane=plane, kind=kind,
            n_connections=len(members),
            route_ids=[int(member['route_id']) for member in members],
            families=[member['family'] for member in members],
            pair=group.get('pair'),
            z_mm=PLANE_Z[plane],
            bbox=_bbox(points),
            endpoint_union=[[round(x, 4), round(y, 4)] for x, y in points],
            members=members,
            rotation_phases=[member.get('source_row') for member in members],
        )
        lateral = [member['lateral_coord'] for member in members]
        orbit['lateral_min'] = min(lateral)
        orbit['lateral_max'] = max(lateral)
        orbit['lateral_span'] = max(lateral) - min(lateral)
        separations = [member['separation_mm'] for member in members
                       if member.get('separation_mm') is not None]
        if separations:
            orbit['separation_mm'] = float(sum(separations) / len(separations))
            orbit['separation_min_mm'] = float(min(separations))
            orbit['separation_max_mm'] = float(max(separations))
        orbit['corner_distances'] = [member['corner_distance_mm']
                                     for member in members]
        orbit['los_len_mm'] = float(sum(member['los_len_mm']
                                        for member in members) / len(members))
        orbit['family_mix'] = dict(Counter(member['family']
                                           for member in members))
        orbit['kind_mix'] = dict(Counter(member['kind'] for member in members))
        orbit['corner_mix'] = dict(Counter(member['corner']
                                           for member in members))
        orbit['source_sides'] = [member['source_side'] for member in members]
        orbits.append(orbit)
    return orbits


def orbit_route_ids(orbits):
    return [rid for orbit in orbits for rid in orbit['route_ids']]


def nearest_corner(x, y):
    best = None
    for name, (cx, cy) in CORNERS.items():
        distance = math.hypot(x - cx, y - cy)
        if best is None or distance < best[1]:
            best = (name, distance)
    return best
