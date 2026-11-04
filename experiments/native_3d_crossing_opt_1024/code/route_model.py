# -*- coding: utf-8 -*-
"""Native 3D route model: multi-height route construction and structure checks."""
from __future__ import annotations

import copy
import math

from ...fsd25d import path3d as P
from ...l3d.world import World
from . import common as N
from . import transition as T


# ------------------------------------------------------------------ tagging
def tag_parts(route):
    """Return a copy with ``tag`` on every part: lead/fanout vs body/mid."""
    route = copy.deepcopy(route)
    parts = route['parts']
    flats = [index for index, part in enumerate(parts) if part['kind'] == 'flat']
    transitions = [index for index, part in enumerate(parts)
                   if part['kind'] == 'transition']
    if not parts:
        return route
    if int(route.get('n_transitions') or 0) == 0 or len(transitions) == 0:
        for index in flats:
            parts[index]['tag'] = 'body'
        return route
    lead_indices = set()
    if parts[0]['kind'] == 'flat':
        lead_indices.add(0)
    if parts[-1]['kind'] == 'flat':
        lead_indices.add(len(parts) - 1)
    for index in flats:
        parts[index].setdefault('tag', 'lead' if index in lead_indices else 'body')
    if transitions:
        parts[min(transitions)]['setdefault_tag'] = None
        del parts[min(transitions)]['setdefault_tag']
        parts[min(transitions)]['tag'] = parts[min(transitions)].get('tag') or 'fanout'
        parts[max(transitions)]['tag'] = parts[max(transitions)].get('tag') or 'fanout'
        for index in transitions[1:-1]:
            parts[index]['tag'] = parts[index].get('tag') or 'mid'
    return route


def make_flat(z_mm, primitives, tag='body', layer_id=None):
    primitives = [dict(prim) for prim in primitives]
    z_mm = float(z_mm)
    plane_id = int(layer_id) if layer_id is not None else N.plane_of_z(z_mm)
    if plane_id is None:
        raise ValueError('flat height %.9f is not one of the 21 heights' % z_mm)
    return dict(kind='flat', layer_id=int(plane_id), z_mm=z_mm,
                length_mm=N.chain_length(primitives),
                primitives=primitives, tag=str(tag))


# ------------------------------------------------------------------ duck-out
def duck_out(route, body_part_index, s0, s1, z_to, radius=float(N.R15),
             max_middle=None, interface_z=None):
    """Insert one mid-body excursion into ``route``.

    The route keeps its original port poses, fanout transitions and all parts
    outside ``body_part_index``; the body flat is split into
    ``prefix | up | middle(new z) | down | suffix``.

    Returns ``dict(route=new_route, excursion=record, footprint_mm, middle_mm)``.
    """
    parts = route['parts']
    if body_part_index < 0 or body_part_index >= len(parts):
        raise ValueError('body part index out of range')
    body = parts[body_part_index]
    if body['kind'] != 'flat':
        raise ValueError('mid-body excursion must start from a flat body part')
    z_from = float(body['z_mm'])
    prims = [dict(prim) for prim in body['primitives']]
    excursion = T.build_excursion(prims, s0, s1, z_from, float(z_to),
                                  radius=radius, max_middle=max_middle)
    new_route = copy.deepcopy(route)
    new_parts = [copy.deepcopy(part) for part in parts[:body_part_index]]
    base = len(new_parts)
    new_parts.append(make_flat(z_from, excursion['prefix'], tag='body'))
    up = excursion['up']
    up['tag'] = 'mid'
    new_parts.append(up)
    new_parts.append(make_flat(float(z_to), [excursion['middle']], tag='body'))
    down = excursion['down']
    down['tag'] = 'mid'
    new_parts.append(down)
    new_parts.append(make_flat(z_from, excursion['suffix'], tag='body'))
    new_parts.extend(copy.deepcopy(part) for part in parts[body_part_index + 1:])
    new_route['parts'] = new_parts
    previous = new_route.get('excursions') or []
    record = dict(s_start_mm=round(float(s0), 6),
                  s_end_mm=round(float(s1), 6),
                  from_z=float(z_from), to_z=float(z_to),
                  from_plane=N.plane_of_z(z_from), to_plane=N.plane_of_z(float(z_to)),
                  up_part_index=base + 1, down_part_index=base + 3,
                  middle_part_index=base + 2, prefix_part_index=base,
                  suffix_part_index=base + 4,
                  footprint_mm=round(float(excursion['footprint_mm']), 6),
                  middle_mm=round(float(excursion['middle_mm']), 6),
                  direction=list(excursion['direction']),
                  body_part_index=int(body_part_index))
    new_route = N.rebuild_route_metadata(new_route, interface_z=interface_z)
    new_route = tag_parts(new_route)
    new_route['native_3d'] = True
    new_route['excursions'] = list(previous) + [record]
    return dict(route=new_route, excursion=record,
                footprint_mm=float(excursion['footprint_mm']),
                middle_mm=float(excursion['middle_mm']))


# ------------------------------------------------------------------ multi excursion
def build_multi_excursion(route, body_part_index, intervals, radius=float(N.R15),
                          interface_z=None):
    """Insert several non-overlapping mid-body excursions in one pass.

    ``intervals`` is ``[(s0, s1, z_to), ...]`` on the original body path of
    ``route['parts'][body_part_index]`` (sorted, non-overlapping, with >= 1 mm
    of straight run between them).  Returns ``dict(route, excursions)``.
    """
    parts = route['parts']
    body = parts[body_part_index]
    if body['kind'] != 'flat':
        raise ValueError('mid-body excursions must start from a flat body part')
    z_from = float(body['z_mm'])
    prims = [dict(prim) for prim in body['primitives']]
    total = T.path_total(prims)
    ordered = sorted(intervals, key=lambda item: float(item[0]))
    # validate ordering / separation
    previous_end = 0.0
    for s0, s1, z_to in ordered:
        s0 = float(s0)
        s1 = float(s1)
        if s0 <= previous_end + 0.5:
            raise ValueError('excursions overlap or are too close')
        if s1 > total - 0.5:
            raise ValueError('excursion outside the body flat')
        previous_end = s1
    new_route = copy.deepcopy(route)
    new_parts = [copy.deepcopy(part) for part in parts[:body_part_index]]
    cursor = 0.0
    records = []
    for s0, s1, z_to in ordered:
        s0 = float(s0)
        s1 = float(s1)
        if s0 - cursor > 1e-6:
            lead_chain, _rest = T.split_chain(prims, s0)
            inserted, _tail = T.split_chain(lead_chain, cursor) \
                if cursor > 1e-9 else (lead_chain, [])
            new_parts.append(make_flat(z_from, inserted, tag='body'))
        excursion = T.build_excursion(prims, s0, s1, z_from, float(z_to),
                                      radius=radius)
        base = len(new_parts)
        up = excursion['up']
        up['tag'] = 'mid'
        down = excursion['down']
        down['tag'] = 'mid'
        new_parts.append(up)
        new_parts.append(make_flat(float(z_to), [excursion['middle']],
                                   tag='body'))
        new_parts.append(down)
        records.append(dict(s_start_mm=round(s0, 6), s_end_mm=round(s1, 6),
                            from_z=z_from, to_z=float(z_to),
                            from_plane=N.plane_of_z(z_from),
                            to_plane=N.plane_of_z(float(z_to)),
                            up_part_index=base, down_part_index=base + 2,
                            middle_part_index=base + 1,
                            footprint_mm=round(float(excursion['footprint_mm']), 6),
                            middle_mm=round(float(excursion['middle_mm']), 6),
                            direction=list(excursion['direction'])))
        cursor = s1
    if total - cursor > 1e-6:
        _head, tail = T.split_chain(prims, cursor)
        new_parts.append(make_flat(z_from, tail, tag='body'))
    new_parts.extend(copy.deepcopy(part) for part in parts[body_part_index + 1:])
    new_route['parts'] = new_parts
    new_route = N.rebuild_route_metadata(new_route, interface_z=interface_z)
    new_route = tag_parts(new_route)
    new_route['native_3d'] = True
    new_route['excursions'] = list(new_route.get('excursions') or []) + records
    return dict(route=new_route, excursions=records)


# ------------------------------------------------------------------ checks
def _flat_start_tangent(primitives):
    if not primitives:
        return None
    return P.prim_tangent_at(primitives[0], 0.0)


def _flat_end_tangent(primitives):
    if not primitives:
        return None
    return P.prim_tangent_at(primitives[-1], 1.0)


def _direction_error(first, second):
    if first is None or second is None:
        return 0.0
    dot = float(first[0]) * float(second[0]) + float(first[1]) * float(second[1])
    return abs(1.0 - max(-1.0, min(1.0, dot)))


def structure_errors(route):
    """Structural / continuity / radius errors of a (native) route record."""
    errors = []
    try:
        errors.extend(World.check_structure(route))
    except Exception as error:  # noqa: BLE001
        errors.append('structure_exception:%s' % error)
        return errors
    parts = route.get('parts') or []
    heights = {round(float(z), 9) for z in N.all_heights()}
    for index, part in enumerate(parts):
        if part['kind'] == 'flat':
            z = round(float(part['z_mm']), 9)
            if z not in heights:
                errors.append('flat_z_not_routing_height:%d:%s' % (index, z))
            tag = part.get('tag') or ''
            layer_id = int(part.get('layer_id', -1))
            interface_heights = (0.0, 0.5)
            is_lead = (tag == 'lead'
                       or (layer_id == 1
                           and any(abs(z - item) < 1e-9
                                   for item in interface_heights)))
            expected_plane = N.plane_of_z(float(part['z_mm']))
            # baseline convention: interface LEAD flats live on the interface
            # layer (layer_id == 1); body flats use the plane id of their z.
            if is_lead:
                if layer_id != 1:
                    errors.append('lead_layer_id_not_interface:%d' % index)
            elif expected_plane is not None and layer_id != int(expected_plane):
                errors.append('flat_layer_id_mismatch:%d' % index)
            for prim in part.get('primitives') or ():
                if prim.get('kind') == 'arc':
                    if abs(float(prim.get('radius', 0.0)) - float(N.R15)) > 1e-6:
                        errors.append('flat_arc_radius_not_15:%d' % index)
                elif prim.get('kind') != 'line':
                    errors.append('unknown_primitive:%d' % index)
        elif part['kind'] == 'transition':
            radius = float(part.get('radius_mm') or 0.0)
            if abs(radius - float(N.R15)) > 1e-6:
                errors.append('transition_radius_not_15:%d' % index)
            dz = float(part['z1']) - float(part['z0'])
            footprint = float(part.get('footprint_mm') or 0.0)
            expected = T.transition_footprint(dz, radius)
            if abs(footprint - expected) > 1e-6:
                errors.append('transition_footprint_mismatch:%d' % index)
            try:
                start = (float(part['start'][0]), float(part['start'][1]),
                         float(part['direction'][0]), float(part['direction'][1]))
                end = (float(part['end'][0]), float(part['end'][1]))
            except (KeyError, TypeError, ValueError):
                errors.append('transition_geometry_missing:%d' % index)
                continue
            predicted = (start[0] + start[2] * footprint,
                         start[1] + start[3] * footprint)
            if math.dist(predicted, end) > 1e-6:
                errors.append('transition_end_mismatch:%d' % index)
        else:
            errors.append('unknown_part_kind:%d' % index)
    # tangent continuity at every junction
    for index in range(len(parts) - 1):
        first, second = parts[index], parts[index + 1]
        if first['kind'] == 'flat' and second['kind'] == 'transition':
            flat_end = first['primitives'][-1]['p1'] if first['primitives'] else None
            tangent = _flat_end_tangent(first['primitives'])
            error = _direction_error(tangent, second.get('direction'))
            if error > 1e-6:
                errors.append('tangent_flat_to_transition:%d' % index)
            if flat_end is not None:
                distance = math.hypot(flat_end[0] - float(second['start'][0]),
                                      flat_end[1] - float(second['start'][1]))
                if distance > 1e-6:
                    errors.append('position_flat_to_transition:%d' % index)
        elif first['kind'] == 'transition' and second['kind'] == 'flat':
            prims = second['primitives']
            if prims:
                start = prims[0]['p0']
                distance = math.hypot(start[0] - float(first['end'][0]),
                                      start[1] - float(first['end'][1]))
                if distance > 1e-6:
                    errors.append('position_transition_to_flat:%d' % index)
            error = _direction_error(first.get('direction'),
                                     _flat_start_tangent(prims))
            if error > 1e-6:
                errors.append('tangent_transition_to_flat:%d' % index)
    return errors


def world_parts_consistent(route):
    """True when ``l3d.world.World.check_structure`` accepts the part chain."""
    return not World.check_structure(route)


def route_metadata_errors(route):
    """Compare the stored native metadata with what the parts actually say."""
    errors = []
    parts = route.get('parts') or []
    body_indices = N.body_flat_indices(route)
    body_heights = [round(float(route['parts'][index]['z_mm']), 9)
                    for index in body_indices]
    stored = [round(float(z), 9) for z in (route.get('body_heights') or [])]
    if stored != body_heights:
        errors.append('body_heights_mismatch')
    mid_parts = [index for index, part in enumerate(parts)
                 if part['kind'] == 'transition' and part.get('tag') == 'mid']
    stored_mid = sorted(int(item['part_index'])
                        for item in (route.get('mid_transitions') or []))
    if sorted(mid_parts) != stored_mid:
        errors.append('mid_transitions_mismatch')
    n_transitions = sum(1 for part in parts if part['kind'] == 'transition')
    if int(route.get('n_transitions') or 0) != n_transitions:
        errors.append('n_transitions_mismatch')
    if int(route.get('n_mid_transitions') or 0) != len(mid_parts):
        errors.append('n_mid_transitions_mismatch')
    length = sum(N.part_length(part) for part in parts)
    if abs(float(route.get('length_mm') or 0.0) - length) > 1e-5:
        errors.append('length_mm_mismatch')
    return errors
