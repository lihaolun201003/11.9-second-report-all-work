# -*- coding: utf-8 -*-
"""Full 3D route assembly and world-level acceptance for the Fanout-First system.

A finished route is

    P_s --lead(z0)--> Q_s --S-transition(z0->zt)--> A
    A --2D body(z=zt, target layer)--> B
    B --S-transition(zt->z0)--> Q_t --lead(z0)--> P_t

where ``P`` are the true physical ports, ``Q = P + lead*d`` and the transition
footprint makes ``A = Q + footprint*d``.  This module only assembles and checks;
it never invents geometry that the fanout / layer2d modules did not produce.
"""
from __future__ import annotations

import math
from collections import Counter

from ..fslw import geom
from ..fsd25d import path3d as P3
from ..l3d.world import World
from . import common as C

TOL = 1e-6


class AssemblyError(RuntimeError):
    def __init__(self, route_id, reason, detail=None):
        super().__init__(f'route {route_id}: {reason}')
        self.route_id = int(route_id)
        self.reason = reason
        self.detail = detail or {}


def _line_prim(p0, p1):
    return geom.line((float(p0[0]), float(p0[1])),
                     (float(p1[0]), float(p1[1])))


def _flat_part(layer_id, z_mm, primitives):
    primitives = [dict(prim) for prim in primitives]
    return dict(kind='flat', layer_id=int(layer_id), z_mm=float(z_mm),
                length_mm=float(P3.path_length(primitives)),
                primitives=primitives)


def _transition_part(record):
    part = dict(record)
    part['kind'] = 'transition'
    return part


def _close(a, b, tol=TOL):
    return math.hypot(float(a[0]) - float(b[0]),
                      float(a[1]) - float(b[1])) <= tol


def _check_lead(route_id, port_xy, start_xy, inward_dir, role):
    """Verify ``start_xy`` lies on the inward ray of the port and return lead."""
    dx = float(start_xy[0]) - float(port_xy[0])
    dy = float(start_xy[1]) - float(port_xy[1])
    ux, uy = float(inward_dir[0]), float(inward_dir[1])
    along = dx * ux + dy * uy
    across = -dx * uy + dy * ux
    if along < -TOL or abs(across) > TOL:
        raise AssemblyError(route_id, f'{role}_transition_off_inward_ray',
                            dict(port=port_xy, start=start_xy,
                                 along=along, across=across))
    if along <= TOL:
        raise AssemblyError(route_id, f'{role}_zero_lead')
    return along


def _check_pose(route_id, prims, start, end, start_tangent, end_tangent,
                what='body'):
    if not prims:
        raise AssemblyError(route_id, f'{what}_empty')
    first, last = prims[0], prims[-1]
    if 'p0' not in first or 'p1' not in last:
        raise AssemblyError(route_id, f'{what}_missing_endpoints')
    if not _close(first['p0'], start):
        raise AssemblyError(route_id, f'{what}_start_mismatch',
                            dict(expected=start, actual=first['p0']))
    if not _close(last['p1'], end):
        raise AssemblyError(route_id, f'{what}_end_mismatch',
                            dict(expected=end, actual=last['p1']))
    # tangents (only line/arc supported)
    tangent0 = _start_tangent(first)
    tangent1 = _end_tangent(last)
    if _angle_diff(tangent0, start_tangent) > 1e-4:
        raise AssemblyError(route_id, f'{what}_start_tangent_mismatch',
                            dict(expected=start_tangent, actual=tangent0))
    if _angle_diff(tangent1, end_tangent) > 1e-4:
        raise AssemblyError(route_id, f'{what}_end_tangent_mismatch',
                            dict(expected=end_tangent, actual=tangent1))


def _start_tangent(prim):
    if prim['kind'] == 'line':
        dx = float(prim['p1'][0]) - float(prim['p0'][0])
        dy = float(prim['p1'][1]) - float(prim['p0'][1])
        norm = math.hypot(dx, dy)
        return (dx / norm, dy / norm) if norm > 0 else (0.0, 0.0)
    angle = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    sign = 1.0 if sweep >= 0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def _end_tangent(prim):
    if prim['kind'] == 'line':
        return _start_tangent(prim)
    angle = float(prim['start_angle']) + float(prim['sweep'])
    sweep = float(prim['sweep'])
    sign = 1.0 if sweep >= 0 else -1.0
    return (-sign * math.sin(angle), sign * math.cos(angle))


def _angle_diff(a, b):
    na = math.hypot(a[0], a[1])
    nb = math.hypot(b[0], b[1])
    if na <= 1e-12 or nb <= 1e-12:
        return math.pi
    cosine = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
    return math.acos(max(-1.0, min(1.0, cosine)))


def assemble_route(row, source_trans, target_trans, body_primitives):
    """Assemble one full 3D route from selected transitions and one body."""
    rid = int(row['route_id'])
    plane = str(row['plane'])
    target_layer = int(row['target_layer'])
    target_z = float(row['target_z_mm'])
    interface_z = C.interface_z(plane)
    eps = C.endpoints()
    src_id = str(row['source_endpoint'])
    tgt_id = str(row['target_endpoint'])
    p_s = tuple(float(v) for v in eps[src_id]['routing_xy'])
    d_s = tuple(float(v) for v in eps[src_id]['inward'])
    p_t = tuple(float(v) for v in eps[tgt_id]['routing_xy'])
    d_t = tuple(float(v) for v in eps[tgt_id]['inward'])

    if source_trans is None or target_trans is None:
        raise AssemblyError(rid, 'missing_transition')
    src = source_trans
    tgt = target_trans
    Q_s = (float(src['start_xy'][0]), float(src['start_xy'][1]))
    A = (float(src['end_xy'][0]), float(src['end_xy'][1]))
    Q_t = (float(tgt['start_xy'][0]), float(tgt['start_xy'][1]))
    B = (float(tgt['end_xy'][0]), float(tgt['end_xy'][1]))

    # ---------------- structural consistency with the assignment
    if int(src['target_layer']) != target_layer or int(tgt['target_layer']) != target_layer:
        raise AssemblyError(rid, 'transition_target_layer_mismatch')
    if abs(float(src['target_z_mm']) - target_z) > TOL:
        raise AssemblyError(rid, 'transition_target_z_mismatch')
    if abs(float(src['z0']) - interface_z) > TOL or abs(float(tgt['z0']) - interface_z) > TOL:
        raise AssemblyError(rid, 'transition_interface_z_mismatch')
    lead_s = _check_lead(rid, p_s, Q_s, d_s, 'source')
    lead_t = _check_lead(rid, p_t, Q_t, d_t, 'target')

    # ---------------- body pose checks (starts at A heading d_s, ends at B heading -d_t)
    _check_pose(rid, body_primitives, A, B, d_s, (-d_t[0], -d_t[1]), 'body')

    parts = []
    if lead_s > TOL:
        parts.append(_flat_part(1, interface_z, [_line_prim(p_s, Q_s)]))
    parts.append(_transition_part(src['transition']))
    parts.append(_flat_part(target_layer, target_z, body_primitives))
    parts.append(_transition_part(tgt['reverse_transition']))
    if lead_t > TOL:
        parts.append(_flat_part(1, interface_z, [_line_prim(Q_t, p_t)]))
    if not parts or parts[0]['kind'] != 'flat' or parts[-1]['kind'] != 'flat':
        raise AssemblyError(rid, 'route_needs_interface_leads',
                            dict(lead_source=lead_s, lead_target=lead_t))

    xyz_length = float(sum(part.get('length_mm') or 0.0 for part in parts))
    body_xy = float(P3.path_length([dict(p) for p in body_primitives]))
    xy_length = body_xy + lead_s + lead_t + 2.0 * float(src['footprint_mm'])
    route = dict(
        route_id=rid, plane=plane,
        source_endpoint=src_id, target_endpoint=tgt_id,
        source_side=row.get('source_side'), target_side=row.get('target_side'),
        relation=row.get('relation'), manual_group=row.get('manual_group'),
        layer_role=row.get('layer_role'),
        start_z_mm=interface_z, end_z_mm=interface_z,
        source_row=eps[src_id]['row'], target_row=eps[tgt_id]['row'],
        target_layer=target_layer, target_z_mm=target_z,
        layer_sequence=[1, target_layer, 1],
        layer_z_sequence=[interface_z, target_z, interface_z],
        n_transitions=2, lifted=True, layers_used=[1, target_layer],
        length_mm=round(xyz_length, 9), xy_length_mm=round(xy_length, 9),
        z_span_mm=abs(target_z - interface_z),
        lead_source_mm=lead_s, lead_target_mm=lead_t,
        parts=parts,
    )
    return route


def check_route_structure(route):
    errors = World.check_structure(route)
    return errors


def validate_routes_independent(routes, clearance=C.MIN_3D_CLEARANCE_MM,
                                log=print):
    """Rebuild a fresh world and check every route in route-id order.

    Returns ``{'valid': {rid: route}, 'violations': [...], 'counts': {...}}``.
    Routes that violate are not added to the world and are reported.
    """
    world = World(C.layer_stack(), clearance=clearance)
    valid = {}
    violations = []
    ordered = sorted(routes, key=lambda item: int(item['route_id']))
    for route in ordered:
        rid = int(route['route_id'])
        structural = World.check_structure(route)
        if structural:
            violations.append(dict(route_id=rid, kind='structure',
                                   detail=structural))
            continue
        found = world.check_route(route)
        if found:
            for record in found:
                violations.append(dict(record, route_id=rid))
            continue
        world.add_route(route)
        valid[rid] = route
    counts = Counter(record.get('kind') for record in violations)
    return dict(valid=valid, violations=violations, counts=dict(counts),
                world=world)


def routes_payload(routes, failed, stack_payload, process_payload,
                   assignment_rows=None):
    """routes_l3d.json payload required by the final validator."""
    assignment = {}
    if assignment_rows:
        assignment = {int(row['route_id']): row for row in assignment_rows}
    records = []
    for route in sorted(routes, key=lambda item: int(item['route_id'])):
        record = dict(route)
        row = assignment.get(int(route['route_id']))
        if row is not None:
            record.setdefault('target_layer', int(row['target_layer']))
            record['manual_group'] = row.get('manual_group') or ''
        records.append(record)
    for failure in sorted(failed, key=lambda item: int(item['route_id'])):
        record = dict(failure)
        record['status'] = 'failed'
        maps = assignment.get(int(failure['route_id']))
        if maps is not None:
            record['plane'] = maps.get('plane')
            record['source_endpoint'] = maps.get('source_endpoint')
            record['target_endpoint'] = maps.get('target_endpoint')
            record['target_layer'] = maps.get('target_layer')
            record['manual_group'] = maps.get('manual_group') or ''
        records.append(record)
    routed = sum(1 for route in routes)
    return dict(
        schema='fanout_first_routes_l3d_v1',
        topology='MANUAL_C4',
        algorithm='FANOUT_FIRST_THEN_LAYERWISE_2D',
        process_mode='corrected_50um',
        route_count=1024,
        routed=routed,
        failed=len(failed),
        layer_stack=stack_payload,
        process=process_payload,
        routes=records,
    )
