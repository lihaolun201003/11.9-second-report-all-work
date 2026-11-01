"""Per-connection geometric features for the bundle-aware routing study.

Everything here is derived from the frozen connectivity table and the frozen port
model (``four_side_1024.manual_c4.connectivity``); no connection is modified.
"""
from __future__ import annotations

import math
from collections import defaultdict

PLANE_Z = {'z1': 0.0, 'z2': 0.5}
CORNERS = {'NE': (150.0, 150.0), 'SE': (150.0, 0.0),
           'SW': (0.0, 0.0), 'NW': (0.0, 150.0)}
SIDES = ('N', 'E', 'S', 'W')
SIDE_ORDER = {'N': 0, 'E': 1, 'S': 2, 'W': 3}


def _unit(dx, dy):
    norm = math.hypot(dx, dy)
    return (dx / norm, dy / norm) if norm > 1e-12 else (0.0, 0.0)


def route_features(conn, endpoints, route, group_of_route, c4_groups):
    """Build the feature dict of one connection (one route id)."""
    plane = route['plane']
    dep = endpoints[route['source_endpoint']]
    arr = endpoints[route['target_endpoint']]
    start = tuple(float(v) for v in dep['routing_xy'])
    end = tuple(float(v) for v in arr['routing_xy'])
    inward_start = tuple(float(v) for v in dep['inward'])
    inward_end = tuple(float(v) for v in arr['inward'])
    dx, dy = end[0] - start[0], end[1] - start[1]
    los = _unit(dx, dy)
    los_len = math.hypot(dx, dy)
    kind = route['relation']
    pair = route['pair']
    source_side, target_side = route['source_side'], route['target_side']
    feature = dict(
        route_id=int(route['route_id']), plane=plane,
        z_mm=PLANE_Z[plane], kind=kind, pair=pair,
        source_side=source_side, target_side=target_side,
        source_endpoint=route['source_endpoint'],
        target_endpoint=route['target_endpoint'],
        source_connector=dep['connector'], target_connector=arr['connector'],
        source_row=int(route['source_row']), target_row=int(route['target_row']),
        source_column=int(route['source_column']),
        target_column=int(route['target_column']),
        source_channel=int(route['source_channel']),
        target_channel=int(route['target_channel']),
        start_xy=[start[0], start[1]], end_xy=[end[0], end[1]],
        inward_start=[inward_start[0], inward_start[1]],
        inward_end=[inward_end[0], inward_end[1]],
        los_dir=[los[0], los[1]], los_len_mm=round(los_len, 6),
        group_id=int(group_of_route[route['route_id']]),
        rotation_group_kind=c4_groups[int(group_of_route[route['route_id']])]['kind'],
    )
    # --- family / corridor coordinate ------------------------------------
    if kind == 'opposite':
        if pair == 'NS':
            family = 'opp_NS'
            lateral = start[0]
            span_start, span_end = start[1], end[1]
        else:
            family = 'opp_EW'
            lateral = start[1]
            span_start, span_end = start[0], end[0]
        feature.update(
            family=family, corridor_axis='vertical' if pair == 'NS' else 'horizontal',
            lateral_coord=float(lateral),
            span_start=float(span_start), span_end=float(span_end),
            lateral_shift_mm=0.0, min_leg_mm=min(abs(dx), abs(dy)),
            separation_mm=None,
            corner='centre', corner_distance_mm=min(
                math.hypot(start[0] - cx, start[1] - cy)
                for cx, cy in CORNERS.values()))
    elif kind == 'same':
        side = source_side
        if side in 'NS':
            lateral = start[0]
            separation = abs(end[0] - start[0])
            span_lo, span_hi = sorted((start[1], end[1]))
        else:
            lateral = start[1]
            separation = abs(end[1] - start[1])
            span_lo, span_hi = sorted((start[0], end[0]))
        feature.update(
            family=f'u_{side}', corridor_axis=f'edge_{side}',
            lateral_coord=float(lateral),
            span_start=float(span_lo), span_end=float(span_hi),
            lateral_shift_mm=float(separation), min_leg_mm=0.0,
            separation_mm=float(separation),
            corner='centre', corner_distance_mm=min(
                math.hypot(start[0] - cx, start[1] - cy)
                for cx, cy in CORNERS.values()))
    else:  # adjacent: two perpendicular legs, one port on each of two sides
        sides = {source_side, target_side}
        corner = None
        for name, sides_of_corner in (
                ('NE', {'N', 'E'}), ('SE', {'S', 'E'}),
                ('SW', {'S', 'W'}), ('NW', {'N', 'W'})):
            if sides == sides_of_corner:
                corner = name
                break
        if corner is None:
            corner = 'centre'
        cx, cy = CORNERS.get(corner, (75.0, 75.0))
        corner_distance = min(math.hypot(start[0] - cx, start[1] - cy),
                              math.hypot(end[0] - cx, end[1] - cy))
        # lateral coordinate: position along the corner's diagonal projection
        lateral = start[0] + start[1] if corner in ('NE', 'SW') else start[0] - start[1]
        leg_a = abs((end[0] - start[0]) if source_side in 'NS'
                    else (end[1] - start[1]))
        leg_b = abs((end[1] - start[1]) if source_side in 'NS'
                    else (end[0] - start[0]))
        feature.update(
            family=f'adj_{corner}', corridor_axis='corner',
            lateral_coord=float(lateral),
            span_start=float(min(start[0], end[0])),
            span_end=float(max(start[0], end[0])),
            lateral_shift_mm=float(abs(leg_a - leg_b)),
            min_leg_mm=float(min(leg_a, leg_b)),
            separation_mm=None, corner=corner,
            corner_distance_mm=float(corner_distance),
            adjacent_legs_mm=[float(leg_a), float(leg_b)])
    # --- nesting order among same-side U's ------------------------------
    feature['u_nesting_lo'] = (feature['span_start']
                               if kind == 'same' else None)
    feature['u_nesting_hi'] = (feature['span_end']
                               if kind == 'same' else None)
    # --- roughness / difficulty proxies ---------------------------------
    feature['straight_mm'] = round(los_len, 4)
    feature['manhattan_mm'] = round(abs(dx) + abs(dy), 4)
    feature['radius_mm'] = 15.0
    feature['min_turn_space_mm'] = 30.0
    feature['layer_options'] = None  # filled by the campaign (5/7/11/15)
    return feature


def build_features(conn, endpoints, routes, groups):
    """Feature list for all routes plus the route<->C4-group maps."""
    c4_groups = {int(group['group_id']): group for group in groups}
    group_of_route = {}
    for group in groups:
        for rid in group['route_ids']:
            group_of_route[int(rid)] = int(group['group_id'])
    features = [route_features(conn, endpoints, route, group_of_route, c4_groups)
                for route in routes]
    features.sort(key=lambda item: item['route_id'])
    return features, group_of_route, c4_groups


def family_groups(features):
    """Group features by routing family (used by the constrained grouping)."""
    buckets = defaultdict(list)
    for feature in features:
        buckets[feature['family']].append(feature)
    for name in buckets:
        buckets[name].sort(key=lambda item: (item['lateral_coord'],
                                             item['route_id']))
    return buckets
