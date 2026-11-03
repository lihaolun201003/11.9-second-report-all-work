# -*- coding: utf-8 -*-
"""R15 3D port fanout (transition) planner for the Fanout-First 1024 system.

Owner: fanout-planner.  Contract: ``DESIGN.md`` section 3.3.

This module coordinates *one endpoint transition per route end* in a single
true-3D world before any layer-wise 2D body is routed:

* every endpoint transition is a two-arc R=15 mm S-curve in the vertical plane
  of the local inward direction, built by
  :func:`four_side_1024.fsd25d.path3d.make_transition`;
* candidates differ only in the interface-flat lead length (0.25, 1, 2, 4, 8,
  16 mm; 0.25 mm is the process minimum and is preferred);
* a candidate endpoint pair is accepted only when the combined partial route
  ``[lead_s, transition_s, reverse_transition_t, lead_t]`` passes the true-3D
  world of :class:`four_side_1024.l3d.world.World` with clearance 0.05 mm
  (no clearance is ever lowered, R=15 mm is never reduced);
* the deterministic planning order is difficulty-first (same-side U pairs, then
  adjacent-side pairs, then opposite-side pairs; larger z-span first inside a
  class), candidate leads are tried in increasing order and a bounded rip-up of
  at most two blocking routes is attempted before an endpoint pair is recorded
  as a real failure.

The public API is intentionally small and exactly the one used by
``assemble.py`` / ``run_all.py``::

    candidate_transitions(route, role, target_layer, leads=LEAD_CANDIDATES)
    plan_fanout(rows, stack=None, fixed=None, repair_ids=None,
                clearance=0.05, log=print)
    plan_manual_groups(rows, **kwargs)
    landings(selected)
    layer_obstacles(selected, layer_id)
    write_artifacts(result, out_dir, experiment_name='experiment_B',
                    landings_out=True)

Everything here is deterministic: no wall-clock or random state influences the
selected fanout set (the only randomness in the module is a fixed-seed shuffle
used by the *independent* validation pass to change the insertion order).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from . import common
from ..d56.index import D56Index, prepare
from ..fsd25d.path3d import (make_transition, path_length, sample_parts,
                             transition_samples)
from ..fslw import config as FS
from ..fslw.geom import line
from ..l3d.layers import INTERFACE_LAYER_ID
from ..l3d.world import World, part_id

__all__ = [
    'LEAD_CANDIDATES', 'MIN_LEAD_MM', 'CLEARANCE_MM', 'RADIUS_MM',
    'MANUAL_LAYER_IDS', 'MANUAL_GROUP_PREFIXES',
    'candidate_transitions', 'direct_endpoint_record', 'partial_route',
    'combined_route',
    'plan_fanout', 'plan_manual_groups', 'landings', 'layer_obstacles',
    'validate_selected', 'write_artifacts', 'normalize_rows', 'clear_caches',
]

# ---------------------------------------------------------------- constants
RADIUS_MM = 15.0
CLEARANCE_MM = 0.05
MIN_LEAD_MM = 0.25
LEAD_CANDIDATES = (0.25, 1.0, 2.0, 4.0, 8.0, 16.0)

MANUAL_LAYER_IDS = (2, 3, 4, 5, 10, 11, 12, 13)
MANUAL_GROUP_PREFIXES = ('Z1-U', 'Z2-U')

#: z band around a body layer in which transition samples are true-3D
#: obstacles for the layer-wise 2D router (0.05 clearance + 0.02 safety).
OBSTACLE_Z_BAND_MM = 0.07
OBSTACLE_BUCKET_MM = 0.02
OBSTACLE_SAMPLE_STEP_MM = 0.02

#: dense sampling step of the independent R15/G1 audit
VALIDATION_STEP_MM = 0.01
#: coarse sampling step of the independent pair-distance audit (1-Lipschitz
#: certificate: true distance >= sampled minimum - step)
PAIR_AUDIT_STEP_MM = 0.1
PAIR_AUDIT_REFINE_STEP_MM = 0.002
R15_TOL_MM = 1e-6

GRID_CELL_MM = 0.5
_RIPUP_MAX_BLOCKERS = 2
_RIPUP_MAX_ATTEMPTS = 3
_FRESH_WORLD_SEED = 0xF0A


# ============================================================ small helpers
def _dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(vector):
    length = math.hypot(float(vector[0]), float(vector[1]))
    if length <= 0.0:
        raise ValueError('zero direction vector')
    return (float(vector[0]) / length, float(vector[1]) / length)


def _xy_tuple(value):
    return (float(value[0]), float(value[1]))


def _cell_key(point, cell=GRID_CELL_MM):
    return (int(math.floor(point[0] / cell)),
            int(math.floor(point[1] / cell)),
            int(math.floor(point[2] / cell)))


def _neighbour_keys(point, cell=GRID_CELL_MM):
    key = _cell_key(point, cell)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (key[0] + dx, key[1] + dy, key[2] + dz)


def _side_from_inward(direction):
    for side, inward in common.SIDE_INWARD.items():
        if abs(direction[0] - inward[0]) < 1e-9 and abs(direction[1] - inward[1]) < 1e-9:
            return side
    return None


def _relation_from_sides(source_side, target_side):
    if not source_side or not target_side:
        return None
    if source_side == target_side:
        return 'same'
    if {source_side, target_side} in ({'N', 'S'}, {'E', 'W'}):
        return 'opposite'
    return 'adjacent'


def _normalise_relation(value):
    text = str(value or '').lower()
    for name in ('same', 'opposite', 'adjacent'):
        if name in text:
            return name
    return None


def _target_z_for(target_layer, route=None, stack=None):
    """Resolve the physical z of one target plane id/row.

    Precedence (the 21-height experiment relies on it):

    1. the row's explicit ``target_z_mm`` — authoritative for assignment rows
       (the new model has re-pitched planes and a non-monotone plane id 20, so
       the frozen 18-layer table must never win over the assignment value);
    2. the supplied model stack (``stack.z_for_layer``);
    3. the frozen 18-layer ``common.layer_z`` (baseline compatibility only).

    Returns ``None`` when nothing can resolve the value; callers decide whether
    that is an error.
    """
    if route is not None:
        raw_z = route.get('target_z_mm')
        if raw_z not in (None, ''):
            try:
                return float(raw_z)
            except (TypeError, ValueError):
                pass
    layer_id = int(target_layer)
    if stack is not None:
        try:
            return float(stack.z_for_layer(layer_id))
        except Exception:
            pass
    try:
        return common.layer_z(layer_id)
    except Exception:
        pass
    return None


# ============================================================ port poses
def _pose_from_row(row, role, endpoints=None):
    """``((x, y), (dx, dy))`` of one endpoint of an assignment/route record."""
    endpoints = endpoints if endpoints is not None else common.endpoints()
    key = 'source' if role == 'source' else 'target'
    endpoint_id = row.get(f'{key}_endpoint')
    if endpoint_id is not None and endpoint_id in endpoints:
        point, direction, _z = common.endpoint_pose(endpoint_id)
        return point, direction, endpoint_id
    xy = row.get(f'{key}_xy')
    if xy is None:
        x = row.get(f'{key}_x_mm')
        y = row.get(f'{key}_y_mm')
        if x is not None and y is not None:
            xy = (float(x), float(y))
    if xy is None:
        raise ValueError(f'row route {row.get("route_id")!r}: missing {key} port pose')
    direction = row.get(f'{key}_inward')
    if direction is None:
        side = row.get(f'{key}_side')
        direction = common.SIDE_INWARD.get(str(side))
    if direction is None:
        raise ValueError(f'row route {row.get("route_id")!r}: missing {key} inward direction')
    return _xy_tuple(xy), _unit(direction), endpoint_id


def _lead_part(port_xy, start_xy, z0, role):
    """Interface flat lead part, oriented in route traversal order."""
    if role == 'source':
        primitive = line(port_xy, start_xy)
    else:
        primitive = line(start_xy, port_xy)
    return dict(kind='flat', layer_id=INTERFACE_LAYER_ID, z_mm=float(z0),
                length_mm=float(_dist2(port_xy, start_xy)),
                primitives=[primitive])


# ============================================================ candidates
def candidate_transitions(route, role, target_layer, leads=LEAD_CANDIDATES,
                          target_z=None):
    """All R15 interface-lead candidates of one route endpoint.

    Parameters
    ----------
    route : dict
        Either an original true-connection record from
        :func:`four_side_1024.fanout1024.common.routes` or a (normalised)
        assignment row.  It must expose the port pose of ``role`` (endpoint id
        or explicit xy/inward) and ``route_id``.
    role : 'source' | 'target'
    target_layer : int
        Physical body layer/plane of the route (``common.PHYSICAL_LAYERS`` key
        for the 18-layer baseline; any plane id of the supplied model stack,
        e.g. 20 for the 21-height experiment, when ``target_z`` is given).
    leads : sequence of float
        Interface lead lengths in mm, all ``>= MIN_LEAD_MM``.
    target_z : float, optional
        Explicit physical z of ``target_layer``.  The planner always passes the
        model-stack-resolved value so that non-monotone/new plane ids (L20) and
        re-pitched planes never fall back to the frozen 18-layer table.

    Returns
    -------
    list[dict]
        Candidate records sorted by increasing lead.  Every record contains
        everything needed by the assembler and by the planner; see the module
        docstring and ``DESIGN.md`` 3.3.
    """
    role = str(role)
    if role not in ('source', 'target'):
        raise ValueError(f'unknown endpoint role {role!r}')
    port_xy, direction, endpoint_id = _pose_from_row(route, role)
    plane = route.get('plane')
    z0 = float(route.get('interface_z_mm')) if route.get('interface_z_mm') is not None \
        else common.interface_z(plane)
    if target_z is not None:
        z1 = float(target_z)
    else:
        raw_z = route.get('target_z_mm')
        if raw_z not in (None, ''):
            z1 = float(raw_z)
        else:
            z1 = _target_z_for(target_layer, route=route)
            if z1 is None:
                raise ValueError(
                    f'route {route.get("route_id")!r}: cannot resolve target z '
                    f'for layer {target_layer!r}')
    route_id = int(route['route_id'])
    out = []
    for lead in leads:
        lead = float(lead)
        if lead < MIN_LEAD_MM - 1e-12:
            raise ValueError(f'lead {lead!r} below the {MIN_LEAD_MM} mm minimum')
        start_xy = (port_xy[0] + direction[0] * lead,
                    port_xy[1] + direction[1] * lead)
        transition = make_transition(start_xy, direction, z0, z1,
                                     radius=RADIUS_MM)
        transition['kind'] = 'transition'
        end_xy = (float(transition['end'][0]), float(transition['end'][1]))
        reverse = make_transition(end_xy, (-direction[0], -direction[1]),
                                  z1, z0, radius=RADIUS_MM)
        reverse['kind'] = 'transition'
        record = dict(
            route_id=route_id,
            endpoint_role=role,
            endpoint_id=endpoint_id,
            candidate_id=f'{route_id}-{role}-L{lead:g}',
            lead_mm=lead,
            start_xy=start_xy,
            start_xyz=(start_xy[0], start_xy[1], z0),
            direction=direction,
            z0=z0,
            z1=z1,
            target_layer=int(target_layer),
            target_z_mm=z1,
            target_z=z1,
            end_xy=end_xy,
            end_xyz=(end_xy[0], end_xy[1], z1),
            footprint_mm=float(transition['footprint_mm']),
            length_mm=float(transition['length_mm']),
            theta_rad=float(transition['theta_rad']),
            radius_mm=float(RADIUS_MM),
            geometry='two_arc_S',
            needs_transition=abs(z1 - z0) > 1e-12,
            transition=transition,
            reverse_transition=reverse,
            lead_part=_lead_part(port_xy, start_xy, z0, role),
        )
        out.append(record)
    return out


def direct_endpoint_record(route, role, target_layer=None, target_z_mm=None):
    """Interface-direct endpoint record (no lead, no S-curve, no occupancy).

    Interface-direct routes (type B of the 21-routing-height experiment) stay on
    their port interface height; the fanout contributes no geometry at all, only
    the true port landing pose for the layer-wise 2D body router.  The record
    keeps the same keys as a transition record so ``landings`` and the assembler
    can consume both kinds uniformly (``transition``/``reverse_transition`` are
    ``None`` and ``n_transitions`` is 0).
    """
    port_xy, direction, endpoint_id = _pose_from_row(route, role)
    plane = route.get('plane')
    z0 = (float(route['interface_z_mm'])
          if route.get('interface_z_mm') is not None
          else common.interface_z(plane))
    if target_layer is None:
        target_layer = route.get('target_layer', INTERFACE_LAYER_ID)
    target_layer = int(target_layer)
    z1 = float(z0 if target_z_mm is None else target_z_mm)
    return dict(
        route_id=int(route['route_id']),
        endpoint_role=role,
        endpoint_id=endpoint_id,
        candidate_id=f'{int(route["route_id"])}-{role}-direct',
        direct=True,
        lead_mm=0.0,
        port_xy=port_xy,
        start_xy=port_xy,
        start_xyz=(port_xy[0], port_xy[1], float(z0)),
        direction=direction,
        z0=float(z0),
        z1=float(z0),
        target_layer=target_layer,
        target_z_mm=z1,
        target_z=z1,
        end_xy=port_xy,
        end_xyz=(port_xy[0], port_xy[1], float(z0)),
        footprint_mm=0.0,
        length_mm=0.0,
        theta_rad=0.0,
        radius_mm=float(RADIUS_MM),
        geometry='direct_2d',
        n_transitions=0,
        needs_transition=False,
        transition=None,
        reverse_transition=None,
        lead_part=None,
    )


def _ensure_record(row, role, record):
    """Complete a transition record that came from outside (``fixed``/JSON).

    Interface-direct records (``direct=True`` or ``transition=None``) are
    normalised into a *direct* endpoint record and never receive an S-curve.
    """
    if not isinstance(record, dict):
        raise TypeError(f'route {row.get("route_id")!r}: invalid transition record')
    record = dict(record)
    if record.get('direct') or record.get('transition') is None:
        target_layer = record.get('target_layer', row.get('target_layer'))
        target_z = record.get('target_z_mm', record.get('z0',
                                                       row.get('target_z_mm')))
        return direct_endpoint_record(row, role, target_layer=target_layer,
                                      target_z_mm=target_z)
    port_xy, direction, endpoint_id = _pose_from_row(row, role)
    z0 = float(record.get('z0', common.interface_z(row.get('plane'))))
    z1 = float(record.get('z1'))
    lead = float(record.get('lead_mm', MIN_LEAD_MM))
    start_xy = record.get('start_xy')
    if start_xy is None:
        start_xy = (port_xy[0] + direction[0] * lead,
                    port_xy[1] + direction[1] * lead)
    start_xy = _xy_tuple(start_xy)
    transition = dict(record.get('transition') or {})
    if not transition or 'start' not in transition:
        transition = make_transition(start_xy, direction, z0, z1, radius=RADIUS_MM)
    transition['kind'] = 'transition'
    end_xy = record.get('end_xy')
    if end_xy is None:
        end_xy = transition.get('end')
    end_xy = _xy_tuple(end_xy)
    reverse = dict(record.get('reverse_transition') or {})
    if not reverse or 'start' not in reverse:
        reverse = make_transition(end_xy, (-direction[0], -direction[1]),
                                  z1, z0, radius=RADIUS_MM)
    reverse['kind'] = 'transition'
    lead_part = record.get('lead_part')
    if not lead_part:
        lead_part = _lead_part(port_xy, start_xy, z0, role)
    else:
        lead_part = dict(lead_part)
        lead_part['kind'] = 'flat'
        lead_part['layer_id'] = INTERFACE_LAYER_ID
        lead_part['z_mm'] = z0
        lead_part['length_mm'] = _dist2(port_xy, start_xy)
    record.update(dict(
        route_id=int(row['route_id']), endpoint_role=role,
        endpoint_id=record.get('endpoint_id', endpoint_id),
        candidate_id=record.get('candidate_id',
                                f'{int(row["route_id"])}-{role}-L{lead:g}'),
        lead_mm=lead, start_xy=start_xy, start_xyz=(start_xy[0], start_xy[1], z0),
        direction=direction, z0=z0, z1=z1,
        target_layer=int(record.get('target_layer',
                                    row.get('target_layer', 1))),
        target_z_mm=z1, target_z=z1, end_xy=end_xy,
        end_xyz=(end_xy[0], end_xy[1], z1),
        footprint_mm=float(transition['footprint_mm']),
        length_mm=float(transition['length_mm']),
        theta_rad=float(transition['theta_rad']),
        radius_mm=float(transition.get('radius_mm', RADIUS_MM)),
        geometry='two_arc_S',
        needs_transition=abs(z1 - z0) > 1e-12,
        transition=transition, reverse_transition=reverse,
        lead_part=lead_part,
    ))
    return record


# ============================================================ route snippets
def partial_route(route, role, record, world_id=None):
    """One-endpoint partial route in the true-3D route schema.

    ``source``: ``[flat lead, transition]``;
    ``target``: ``[reverse transition, flat lead]``.

    Interface-direct records return ``None``: they occupy no fanout geometry in
    the true-3D world (the interface flat body is routed later by the 2D router
    and checked in the assembled world instead).

    The world only consumes ``route_id`` and ``parts``; the remaining fields
    are filled so the record is also a valid (partial) route description.
    """
    if record.get('direct') or record.get('transition') is None:
        return None
    route_id = int(record['route_id'] if world_id is None else world_id)
    if role == 'source':
        parts = [dict(record['lead_part']), dict(record['transition'])]
    else:
        parts = [dict(record['reverse_transition']), dict(record['lead_part'])]
    flat_length = float(record['lead_part']['length_mm'])
    transition_length = float(record['length_mm'])
    xy_length = flat_length + float(record['footprint_mm'])
    length = flat_length + transition_length
    return dict(
        route_id=route_id,
        plane=route.get('plane'),
        source_endpoint=route.get('source_endpoint'),
        target_endpoint=route.get('target_endpoint'),
        start_z_mm=float(record['z0']),
        end_z_mm=float(record['z0']),
        layer_sequence=[INTERFACE_LAYER_ID, int(record['target_layer']),
                        INTERFACE_LAYER_ID],
        layer_z_sequence=[float(record['z0']), float(record['z1']),
                          float(record['z0'])],
        n_transitions=1,
        lifted=True,
        layers_used=[INTERFACE_LAYER_ID, int(record['target_layer'])],
        xy_length_mm=xy_length,
        length_mm=length,
        z_span_mm=abs(float(record['z1']) - float(record['z0'])),
        parts=parts,
    )


def combined_route(route, source_record, target_record, world_id=None):
    """Both endpoint partials of one route as a single candidate route.

    The true-3D world checks the candidate *against the world*, therefore the
    two endpoint partials of the same route are placed in one candidate route
    so that they are also checked against each other (via the world's
    self-clearance pass) without touching the committed world.
    """
    route_id = int(route['route_id'] if world_id is None else world_id)
    if (source_record.get('direct') or target_record.get('direct')
            or source_record.get('transition') is None
            or target_record.get('transition') is None):
        return None
    parts = [dict(source_record['lead_part']), dict(source_record['transition']),
             dict(target_record['reverse_transition']),
             dict(target_record['lead_part'])]
    return dict(
        route_id=route_id,
        plane=route.get('plane'),
        start_z_mm=float(source_record['z0']),
        end_z_mm=float(target_record['z0']),
        n_transitions=2,
        parts=parts,
    )


# ============================================================ row handling
def normalize_rows(rows, stack=None):
    """Normalise assignment rows / true-route records into planner rows."""
    endpoints = common.endpoints()
    out = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise TypeError('plan_fanout rows must be dicts')
        route_id = int(raw['route_id'])
        if route_id in seen:
            raise ValueError(f'duplicate route_id {route_id} in rows')
        seen.add(route_id)
        plane = raw.get('plane')
        if plane not in ('z1', 'z2'):
            interface_z = raw.get('interface_z_mm')
            if interface_z is not None:
                plane = 'z1' if abs(float(interface_z)) < 0.25 else 'z2'
            else:
                plane = 'z1'
        z0 = common.interface_z(plane)
        source_xy, source_inward, source_ep = _pose_from_row(raw, 'source', endpoints)
        target_xy, target_inward, target_ep = _pose_from_row(raw, 'target', endpoints)
        target_layer = raw.get('target_layer')
        target_z = raw.get('target_z_mm')
        if target_layer in (None, ''):
            if target_z in (None, ''):
                raise ValueError(f'route {route_id}: no target_layer / target_z_mm')
            target_z = float(target_z)
            target_layer = _layer_from_z(target_z)
        else:
            target_layer = int(target_layer)
            resolved = None
            if target_z in (None, ''):
                resolved = _target_z_for(target_layer, route=raw, stack=stack)
                if resolved is None:
                    raise ValueError(
                        f'route {route_id}: cannot resolve target z for layer '
                        f'{target_layer!r}')
                target_z = resolved
            else:
                target_z = float(target_z)
        explicit_needs = raw.get('needs_transition')
        if isinstance(explicit_needs, str):
            needs_transition = explicit_needs.strip().lower() in (
                '1', 'true', 'yes', 'y')
        elif explicit_needs is None:
            needs_transition = abs(float(target_z) - z0) > 1e-12
        else:
            needs_transition = bool(explicit_needs)
        if not needs_transition:
            # interface-direct endpoints live exactly at the interface height
            target_z = z0
        source_side = raw.get('source_side') or _side_from_inward(source_inward)
        target_side = raw.get('target_side') or _side_from_inward(target_inward)
        relation = _normalise_relation(raw.get('relation'))
        if relation is None:
            relation = _relation_from_sides(source_side, target_side)
        if relation is None:
            relation = _normalise_relation(raw.get('logical_kind')) or 'other'
        manual_group = str(raw.get('manual_group') or '').strip()
        layer_role = str(raw.get('layer_role') or raw.get('logical_kind') or '').strip()
        baseline_old_layer = raw.get('baseline_old_layer')
        if baseline_old_layer in (None, ''):
            baseline_old_layer = None
        else:
            baseline_old_layer = int(float(baseline_old_layer))
        out.append(dict(
            route_id=route_id,
            plane=plane,
            interface_z_mm=z0,
            source_endpoint=source_ep if source_ep is not None
            else raw.get('source_endpoint'),
            target_endpoint=target_ep if target_ep is not None
            else raw.get('target_endpoint'),
            source_side=source_side,
            target_side=target_side,
            source_xy=source_xy,
            target_xy=target_xy,
            source_inward=source_inward,
            target_inward=target_inward,
            relation=str(raw.get('relation') or relation),
            relation_geom=relation,
            manual_group=manual_group,
            layer_role=layer_role,
            target_layer=int(target_layer),
            target_z_mm=float(target_z),
            target_plane_label=str(raw.get('target_plane_label') or ''),
            direction=str(raw.get('direction') or ''),
            baseline_old_layer=baseline_old_layer,
            z_span_mm=abs(float(target_z) - z0),
            needs_transition=bool(needs_transition),
        ))
    return out


def _layer_from_z(target_z, tol=1e-6):
    best = None
    for layer_id, z in common.PHYSICAL_LAYERS.items():
        distance = abs(float(z) - float(target_z))
        if best is None or distance < best[1]:
            best = (int(layer_id), distance)
    if best is None or best[1] > tol:
        raise ValueError(f'cannot infer a physical layer for target z={target_z!r}')
    return best[0]


def _difficulty_key(row):
    """Deterministic difficulty order: hard endpoint pairs first.

    Same-side U pairs (category 0) are the hardest because both landings must
    be coordinated; adjacent-side pairs follow; opposite-side pairs last.
    Inside a category the larger z-span (longer footprint) is planned first so
    the long transitions pick their interface leads before short ones.
    """
    relation = row.get('relation_geom') or 'other'
    category = {'same': 0, 'adjacent': 1, 'opposite': 2}.get(relation, 3)
    return (category, -float(row.get('z_span_mm') or 0.0), int(row['route_id']))


# ============================================================ D56 lead pair
def _lead_pair_conflict(source_record, target_record):
    """Strict same-plane 2D check between the two interface leads of a route."""
    first = source_record.get('lead_part')
    second = target_record.get('lead_part')
    if not first or not second:
        return None
    if abs(float(first['z_mm']) - float(second['z_mm'])) > 1e-9:
        return None
    index = D56Index(width=FS.WIDTH_MM, gap=FS.EDGE_GAP_MM,
                     sagitta=FS.SAGITTA_MM,
                     min_cross_angle_deg=FS.MIN_CROSS_ANGLE_DEG,
                     crossing_policy='strict')
    index.add(1, prepare(first['primitives']))
    evaluation = index.evaluate(prepare(second['primitives']))
    if evaluation is None or evaluation.valid:
        return None
    return dict(kind='lead_pair_2d_conflict',
                reason=str(evaluation.reason),
                blockers=list(evaluation.blockers or [])[:5],
                min_spacing_mm=evaluation.min_spacing_mm)


# ============================================================ world plumbing
def _make_world(stack, clearance):
    return World(stack, clearance=clearance)


def _violation_route_ids(violation, meta):
    """Map world-entry ids of a violation back to real route ids."""
    route_ids = []
    other = violation.get('other_route')
    if other is not None:
        world_id = int(other)
        info = meta.get(world_id)
        route_ids.append(int(info['route_id']) if info else world_id // 2)
    for blocker in violation.get('blockers') or ():
        blocker = int(blocker)
        if blocker < 1000:
            # a raw D56 part index of a synthetic same-route check, not a
            # world-entry id
            continue
        world_id = blocker // 1000
        info = meta.get(world_id)
        route_ids.append(int(info['route_id']) if info else world_id // 2)
    return route_ids


def _summarise_violations(violations, meta, limit=5):
    out = []
    for violation in violations[:limit]:
        summary = dict(kind=violation.get('kind'),
                       route_id=violation.get('route_id'),
                       detail=violation.get('detail'))
        if violation.get('other_route') is not None:
            world_id = int(violation['other_route'])
            info = meta.get(world_id)
            summary['other_route_id'] = int(info['route_id']) if info else world_id // 2
            summary['other_role'] = info['role'] if info else None
            summary['other_world_id'] = world_id
        if violation.get('distance_mm') is not None:
            summary['distance_mm'] = round(float(violation['distance_mm']), 6)
        if violation.get('point') is not None:
            summary['point'] = [round(float(v), 6) for v in violation['point']]
        if violation.get('blockers'):
            summary['blocker_world_ids'] = [int(v) for v in violation['blockers']][:10]
        if violation.get('min_spacing_mm') is not None:
            summary['min_spacing_mm'] = round(float(violation['min_spacing_mm']), 6)
        out.append(summary)
    return out


def _add_selected(world, meta, row, source_record, target_record):
    route_id = int(row['route_id'])
    for role, record in (('source', source_record), ('target', target_record)):
        world_id = 2 * route_id + (0 if role == 'source' else 1)
        route = partial_route(row, role, record, world_id)
        world.add_route(route)
        meta[world_id] = dict(route_id=route_id, role=role, route=route,
                              record=record)


def _remove_partials_bulk(world, meta, route_ids):
    """Remove all endpoint partials of ``route_ids`` with a single world rebuild."""
    removed = []
    for route_id in route_ids:
        for offset in (0, 1):
            world_id = 2 * int(route_id) + offset
            if world_id in meta:
                world.plan.pop(world_id, None)
                meta.pop(world_id)
                removed.append(world_id)
    if removed:
        world.rebuild()
    return removed


# ============================================================ candidate pairs
def _candidate_pairs(row, source_candidates, target_candidates, leads):
    """Ordered ``(source, target, stage)`` candidate pairs for one route."""
    by_source = {record['lead_mm']: record for record in source_candidates}
    by_target = {record['lead_mm']: record for record in target_candidates}
    pairs = []
    same_side = row.get('relation_geom') == 'same'
    if same_side:
        # Joint variant first: equal leads put the two landings at the same
        # depth, which the layer-wise U-turn body router needs.
        for lead in leads:
            lead = float(lead)
            source = by_source.get(lead)
            target = by_target.get(lead)
            if source is not None and target is not None:
                pairs.append((source, target, 'joint_equal_lead'))
        for lead in leads:
            source = by_source.get(float(lead))
            if source is None:
                continue
            for target_lead in leads:
                if float(target_lead) == float(lead):
                    continue
                target = by_target.get(float(target_lead))
                if target is not None:
                    pairs.append((source, target, 'independent_leads'))
    else:
        for lead in leads:
            source = by_source.get(float(lead))
            if source is None:
                continue
            for target_lead in leads:
                target = by_target.get(float(target_lead))
                if target is not None:
                    pairs.append((source, target, 'independent_leads'))
    return pairs


# ============================================================ place one route
def _place_route(world, row, meta, selected, attempts, leads):
    """Try to place both endpoint partials of one route.  Returns (ok, blockers)."""
    route_id = int(row['route_id'])
    target_layer = int(row['target_layer'])
    if not row.get('needs_transition', True):
        # Interface-direct route (21-height experiment type B): no lead and no
        # S-curve at all, and no occupancy in the fanout world.  The interface
        # flat body is routed later by the 2D router.
        target_z = float(row.get('target_z_mm', row.get('interface_z_mm', 0.0)))
        source_record = direct_endpoint_record(row, 'source', target_layer,
                                               target_z)
        target_record = direct_endpoint_record(row, 'target', target_layer,
                                               target_z)
        selected[route_id] = dict(source=source_record, target=target_record)
        attempts.append(dict(
            route_id=route_id, stage='direct_2d', accepted=True,
            reason='interface_direct',
            source_candidate_id=source_record['candidate_id'],
            target_candidate_id=target_record['candidate_id'],
            source_lead_mm=0.0, target_lead_mm=0.0, blockers=[],
            n_transitions=0))
        return True, []
    source_candidates = candidate_transitions(
        row, 'source', target_layer, leads,
        target_z=float(row['target_z_mm']))
    target_candidates = candidate_transitions(
        row, 'target', target_layer, leads,
        target_z=float(row['target_z_mm']))
    blockers = []
    for source_record, target_record, stage in _candidate_pairs(
            row, source_candidates, target_candidates, leads):
        candidate = combined_route(row, source_record, target_record, 2 * route_id)
        violations = world.check_route(candidate, check_self=True)
        if not violations:
            conflict = _lead_pair_conflict(source_record, target_record)
            if conflict is not None:
                violations = [conflict]
        if violations:
            violation_route_ids = []
            for violation in violations:
                for blocker in _violation_route_ids(violation, meta):
                    if blocker != route_id and blocker not in violation_route_ids:
                        violation_route_ids.append(blocker)
            for blocker in violation_route_ids:
                if blocker not in blockers:
                    blockers.append(blocker)
            attempts.append(dict(
                route_id=route_id, stage=stage, accepted=False,
                reason='conflict',
                source_candidate_id=source_record['candidate_id'],
                target_candidate_id=target_record['candidate_id'],
                source_lead_mm=source_record['lead_mm'],
                target_lead_mm=target_record['lead_mm'],
                blockers=violation_route_ids,
                violation_kinds=[str(v.get('kind')) for v in violations][:5],
                violations=_summarise_violations(violations, meta),
            ))
            continue
        _add_selected(world, meta, row, source_record, target_record)
        selected[route_id] = dict(source=source_record, target=target_record)
        attempts.append(dict(
            route_id=route_id, stage=stage, accepted=True, reason='ok',
            source_candidate_id=source_record['candidate_id'],
            target_candidate_id=target_record['candidate_id'],
            source_lead_mm=source_record['lead_mm'],
            target_lead_mm=target_record['lead_mm'],
            blockers=[],
        ))
        return True, []
    return False, blockers


def _restore_saved(world, meta, selected, saved):
    for route_id, info in saved.items():
        selected[route_id] = dict(info['records'])
        for world_id, route in info['partials'].items():
            world.add_route(route)
            role = 'source' if int(world_id) % 2 == 0 else 'target'
            meta[int(world_id)] = dict(route_id=int(route_id), role=role,
                                       route=route,
                                       record=info['records'][role])


def _attempt_ripup(world, meta, selected, attempts, rows_by_id, row, leads,
                   blockers, protected_ids, stats):
    """Bounded rip-up: remove <=2 blocking routes, retry, restore/rollback."""
    route_id = int(row['route_id'])
    candidates = []
    for blocker in blockers:
        blocker = int(blocker)
        if (blocker == route_id or blocker in candidates
                or blocker not in selected or blocker in protected_ids):
            continue
        candidates.append(blocker)
        if len(candidates) >= _RIPUP_MAX_BLOCKERS:
            break
    if not candidates:
        return False
    stats['ripup_attempts'] = int(stats.get('ripup_attempts', 0)) + 1
    saved = {}
    for blocker in candidates:
        saved[blocker] = dict(
            records=dict(selected[blocker]),
            partials={world_id: meta[world_id]['route']
                      for world_id in (2 * blocker, 2 * blocker + 1)
                      if world_id in meta})
    for blocker in candidates:
        selected.pop(blocker, None)
    _remove_partials_bulk(world, meta, candidates)
    ok, _ = _place_route(world, row, meta, selected, attempts, leads)
    if not ok:
        _restore_saved(world, meta, selected, saved)
        return False
    for blocker in candidates:
        blocker_row = rows_by_id.get(blocker)
        if blocker_row is None:
            ok_blocker = False
        else:
            ok_blocker, _ = _place_route(world, blocker_row, meta, selected,
                                         attempts, leads)
        if not ok_blocker:
            # Full transaction rollback.
            remove_ids = [route_id] + [candidate for candidate in candidates]
            selected.pop(route_id, None)
            for candidate in candidates:
                selected.pop(candidate, None)
            _remove_partials_bulk(world, meta, remove_ids)
            _restore_saved(world, meta, selected, saved)
            return False
    stats['ripups'] = int(stats.get('ripups', 0)) + 1
    attempts.append(dict(route_id=route_id, stage='ripup', accepted=True,
                         reason='ripup_replaced_blockers',
                         blockers=list(candidates),
                         source_lead_mm=selected[route_id]['source']['lead_mm'],
                         target_lead_mm=selected[route_id]['target']['lead_mm']))
    return True


# ============================================================ main planner
def plan_fanout(rows, stack=None, fixed=None, repair_ids=None,
                clearance=CLEARANCE_MM, log=print, seed=None,
                leads=LEAD_CANDIDATES, max_ripup_attempts=_RIPUP_MAX_ATTEMPTS,
                **kwargs):
    """Globally coordinate all endpoint R15 transitions in one 3D world.

    Parameters
    ----------
    rows : list[dict]
        Assignment rows (see ``DESIGN.md`` 3.2) or true route records.
        Required per row: ``route_id``, plane/endpoint pose, ``target_layer``
        (or ``target_z_mm``).
    stack : LayerStack, optional
        Defaults to ``common.layer_stack()`` (18 layers, 1 mm glass, 50 um).
    fixed : dict[int, {'source': record, 'target': record}], optional
        Already fixed endpoint transitions that must not be moved (manual
        groups have priority in experiments C/D/E).  They are inserted into
        the world before planning and never modified.
    repair_ids : iterable[int], optional
        When given, only these route ids are (re)planned; every other row is
        left alone (the caller is expected to pass the frozen routes in
        ``fixed``).
    clearance : float
        True-3D centre-line clearance; the process value is 0.05 mm and must
        never be lowered.
    log : callable
        Progress sink; called once per 128 planned endpoints.

    Returns
    -------
    dict with ``selected`` (``{route_id: {'source': record, 'target':
    record}}``), ``failures`` (real route ids + role/reason/blockers),
    ``stats`` (counts, timing, lead histogram, ...) and the additional
    bookkeeping keys consumed by :func:`write_artifacts`
    (``rows``, ``attempts``, ``fixed``, ``stack``, ``ship_world``).
    """
    started = time.perf_counter()
    stack = stack if stack is not None else common.layer_stack()
    clearance = float(clearance)
    if clearance < CLEARANCE_MM - 1e-12:
        raise ValueError('the 3D clearance must not be lowered below 0.05 mm')
    if RADIUS_MM < 15.0 - 1e-12:  # pragma: no cover - constant guard
        raise ValueError('R15 must never be reduced')
    if seed is not None:
        # Determinism guard: a seed is accepted for API compatibility but the
        # planner is a deterministic greedy algorithm and never uses it.
        _ = int(seed)

    normalised = normalize_rows(rows, stack=stack)
    rows_by_id = {row['route_id']: row for row in normalised}
    fixed = {int(key): value for key, value in (fixed or {}).items()}
    repair_set = None if repair_ids is None else {int(v) for v in repair_ids}
    if repair_set is None:
        scope_rows = list(normalised)
    else:
        scope_rows = [row for row in normalised
                      if row['route_id'] in repair_set or row['route_id'] in fixed]

    world = _make_world(stack, clearance)
    meta = {}
    selected = {}
    attempts = []
    failures = []
    fixed_conflicts = []
    stats = dict(schema='fanout_plan_stats_v1', clearance_mm=clearance,
                 radius_mm=RADIUS_MM, lead_candidates=list(leads),
                 total_rows=len(normalised), scope_rows=len(scope_rows),
                 fixed_routes=len(fixed), candidate_checks=0, ripups=0,
                 fixed_conflicts=0)

    # ---- fixed endpoint transitions first (manual-group priority) ----------
    for route_id in sorted(fixed):
        row = rows_by_id.get(route_id)
        pair = fixed[route_id]
        if row is None or not isinstance(pair, dict):
            continue
        if not row.get('needs_transition', True):
            # interface-direct fixed row: canonical direct records, no world
            # occupancy (the 2D router owns the interface body).
            target_z = float(row.get('target_z_mm',
                                     row.get('interface_z_mm', 0.0)))
            records = {}
            for role in ('source', 'target'):
                record = pair.get(role)
                records[role] = (_ensure_record(row, role, record) if record
                                 else direct_endpoint_record(
                                     row, role, row['target_layer'], target_z))
            selected[route_id] = records
            attempts.append(dict(route_id=route_id, stage='fixed',
                                 accepted=True, reason='fixed_direct',
                                 source_lead_mm=0.0, target_lead_mm=0.0,
                                 n_transitions=0))
            continue
        records = {}
        for role in ('source', 'target'):
            record = pair.get(role)
            if record is None:
                records = {}
                break
            records[role] = _ensure_record(row, role, record)
        if not records:
            continue
        for role in ('source', 'target'):
            world_id = 2 * route_id + (0 if role == 'source' else 1)
            route = partial_route(row, role, records[role], world_id)
            violations = world.check_route(route)
            if violations:
                fixed_conflicts.append(dict(
                    route_id=route_id, role=role,
                    violations=_summarise_violations(violations, meta)))
            world.add_route(route)
            meta[world_id] = dict(route_id=route_id, role=role, route=route,
                                  record=records[role])
        selected[route_id] = records
        attempts.append(dict(route_id=route_id, stage='fixed', accepted=True,
                             reason='fixed', source_lead_mm=records['source']['lead_mm'],
                             target_lead_mm=records['target']['lead_mm']))
    stats['fixed_conflicts'] = len(fixed_conflicts)

    # ---- planned routes in deterministic difficulty order ------------------
    targets = [row for row in sorted(scope_rows, key=_difficulty_key)
               if row['route_id'] not in fixed]
    endpoint_total = 2 * len(targets)
    endpoints_done = 0
    manual_group_counts = Counter(row['manual_group'] for row in normalised
                                  if row['manual_group'])
    for index, row in enumerate(targets, 1):
        route_id = int(row['route_id'])
        attempts_before = len(attempts)
        ok, blockers = _place_route(world, row, meta, selected, attempts, leads)
        if not ok and blockers:
            last_attempts = attempts[attempts_before:]
            ripup_blockers = []
            for attempt in last_attempts:
                for blocker in attempt.get('blockers') or ():
                    if blocker not in ripup_blockers:
                        ripup_blockers.append(int(blocker))
            for _ in range(max(0, int(max_ripup_attempts))):
                if _attempt_ripup(world, meta, selected, attempts, rows_by_id,
                                  row, leads, ripup_blockers, fixed,
                                  stats):
                    ok = True
                    break
                break
        endpoints_done += 2
        if not ok:
            blocked_ids = []
            for attempt in attempts[attempts_before:]:
                for blocker in attempt.get('blockers') or ():
                    blocker = int(blocker)
                    if blocker not in blocked_ids:
                        blocked_ids.append(blocker)
            failures.append(dict(
                route_id=route_id,
                role='source+target',
                plane=row['plane'],
                target_layer=row['target_layer'],
                target_z_mm=row['target_z_mm'],
                reason='no_transition_candidate',
                blockers=blocked_ids,
                attempts=len(attempts) - attempts_before,
                detail='every lead pair was rejected by the true 3D world'))
            attempts.append(dict(route_id=route_id, stage='fail', accepted=False,
                                 reason='no_transition_candidate',
                                 blockers=blocked_ids))
        if endpoints_done % 128 == 0 or index == len(targets):
            elapsed = time.perf_counter() - started
            if log is not None:
                log(f'[fanout] endpoints={endpoints_done}/{endpoint_total} '
                    f'routes={index}/{len(targets)} ok={len(selected)} '
                    f'failed={len(failures)} checks={len(attempts)} '
                    f'elapsed={elapsed:.1f}s')

    seconds = time.perf_counter() - started
    direct_route_count = sum(1 for pair in selected.values()
                             if pair['source'].get('direct'))
    non_direct_route_count = len(selected) - direct_route_count
    lead_histogram = Counter()
    selected_leads = {}
    for route_id, pair in selected.items():
        if route_id in fixed:
            continue
        if pair['source'].get('direct'):
            continue
        source_lead = round(float(pair['source']['lead_mm']), 6)
        target_lead = round(float(pair['target']['lead_mm']), 6)
        lead_histogram[(source_lead, target_lead)] += 1
        selected_leads[str(route_id)] = [source_lead, target_lead]
    stats.update(dict(
        planned_routes=len(targets),
        success_routes=len(selected),
        success_endpoints=2 * len(selected),
        success_transition_endpoints=2 * non_direct_route_count,
        endpoints_needing_transition=2 * non_direct_route_count,
        direct_routes=direct_route_count,
        non_direct_routes=non_direct_route_count,
        failures=len(failures),
        candidate_checks=len(attempts),
        seconds=round(seconds, 3),
        lead_histogram={f'{key[0]:g}/{key[1]:g}': value
                        for key, value in sorted(lead_histogram.items())},
        manual_group_counts=dict(manual_group_counts),
        world_partial_routes=len(world.plan),
        selected_leads=selected_leads,
    ))
    result = dict(
        selected=selected,
        failures=failures,
        fixed_conflicts=fixed_conflicts,
        stats=stats,
        rows=scope_rows,
        attempts=attempts,
        fixed=dict(fixed),
        stack=stack,
        clearance=clearance,
        plan_world=world,
    )
    return result


def plan_manual_groups(rows, **kwargs):
    """Plan only the 368 manual-U endpoints (8 fixed manual groups).

    Filters rows whose ``manual_group`` starts with ``Z1-U``/``Z2-U`` and whose
    ``target_layer`` is one of the eight fixed manual layers, then calls
    :func:`plan_fanout`.  This is experiment B.
    """
    manual_rows = []
    for raw in rows:
        group = str(raw.get('manual_group') or '').strip()
        if not group.startswith(MANUAL_GROUP_PREFIXES):
            continue
        layer = raw.get('target_layer')
        try:
            layer = int(layer)
        except (TypeError, ValueError):
            continue
        if layer in MANUAL_LAYER_IDS:
            manual_rows.append(raw)
    kwargs.setdefault('log', print)
    result = plan_fanout(manual_rows, **kwargs)
    result['experiment_name'] = 'experiment_B'
    return result


# ============================================================ landings
def landings(selected):
    """Landing table of the selected fanout.

    ``{route_id: {'A': (x, y), 'dA': (dx, dy), 'B': (x, y), 'dB': (dx, dy)}}``
    where ``A``/``B`` are the source/target transition end points (the body
    landings) and ``dA``/``dB`` are the inward port directions.  The body starts
    at ``A`` heading ``dA`` and must arrive at ``B`` heading ``-dB``.

    Interface-direct routes (``record['direct']``) have no transition: their
    landings are exactly the true port poses, ``A = port(source)``,
    ``B = port(target)`` with the inward directions.  Those records carry
    ``port_xy``/``direction`` so this function works without the route table.
    """
    out = {}
    for route_id, pair in selected.items():
        source = pair['source']
        target = pair['target']
        if source.get('direct') or target.get('direct'):
            source_xy = source.get('port_xy') or source['start_xy']
            target_xy = target.get('port_xy') or target['start_xy']
        else:
            source_xy = source['end_xy']
            target_xy = target['end_xy']
        out[int(route_id)] = dict(
            A=(float(source_xy[0]), float(source_xy[1])),
            dA=(float(source['direction'][0]), float(source['direction'][1])),
            B=(float(target_xy[0]), float(target_xy[1])),
            dB=(float(target['direction'][0]), float(target['direction'][1])),
        )
    return out


# ============================================================ layer obstacles
_OBSTACLE_CACHE = OrderedDict()
_OBSTACLE_CACHE_MAX = 3


def clear_caches():
    """Drop the layer-obstacle cache (used by tests)."""
    _OBSTACLE_CACHE.clear()


def _selected_signature(selected):
    parts = []
    for route_id in sorted(int(key) for key in selected):
        pair = selected[route_id]
        for role in ('source', 'target'):
            record = pair[role]
            parts.append((route_id, role, bool(record.get('direct')),
                          record.get('candidate_id'),
                          round(float(record['lead_mm']), 9),
                          round(float(record['z0']), 9),
                          round(float(record['z1']), 9),
                          tuple(round(float(v), 9) for v in record['start_xy']),
                          tuple(round(float(v), 9) for v in record['end_xy'])))
    digest = hashlib.sha1(repr(parts).encode('utf-8')).hexdigest()
    return digest


def _obstacle_buckets(selected):
    """z-bucket index of all selected transition samples (cached).

    Interface-direct records (no transition) contribute no obstacles: their
    interface flat figure is the 2D router's own ``initial_routes``.
    """
    signature = _selected_signature(selected)
    cached = _OBSTACLE_CACHE.get(signature)
    if cached is not None:
        _OBSTACLE_CACHE.move_to_end(signature)
        return cached
    buckets = defaultdict(list)
    bucket = OBSTACLE_BUCKET_MM
    for route_id in sorted(int(key) for key in selected):
        pair = selected[route_id]
        for role in ('source', 'target'):
            record = pair[role]
            if record.get('direct') or record.get('transition') is None:
                continue
            samples = transition_samples(record['transition'],
                                         step=OBSTACLE_SAMPLE_STEP_MM)
            for sample in samples:
                z = float(sample[2])
                key = int(math.floor(z / bucket))
                buckets[key].append((float(sample[0]), float(sample[1]), z,
                                     route_id, role))
    _OBSTACLE_CACHE[signature] = buckets
    while len(_OBSTACLE_CACHE) > _OBSTACLE_CACHE_MAX:
        _OBSTACLE_CACHE.popitem(last=False)
    return buckets


def layer_obstacles(selected, layer_id, layer_z=None):
    """Transition sample obstacles of one routing height for the 2D router.

    Returns ``[{'x', 'y', 'z', 'route_id', 'role'}]`` for every selected
    transition sample with ``|z - layer_z| <= 0.07 mm`` (0.05 mm true 3D
    clearance plus 0.02 mm router safety).  The samples are indexed by z-bucket,
    so all heights can be queried quickly.

    ``layer_z`` may be given explicitly (the 21-height experiment body plane id
    20 = -0.05 mm and the routable interface heights 1001/1002 = 0.0/0.5 mm are
    not in the frozen 18-layer table).  When ``None`` the frozen 18-layer
    ``common.layer_z`` mapping is used, so baseline callers are unchanged.
    Interface-direct records and records without a transition are skipped.
    """
    if layer_z is None:
        layer_z = common.layer_z(int(layer_id))
    else:
        layer_z = float(layer_z)
    low = layer_z - OBSTACLE_Z_BAND_MM - 1e-12
    high = layer_z + OBSTACLE_Z_BAND_MM + 1e-12
    buckets = _obstacle_buckets(selected)
    bucket = OBSTACLE_BUCKET_MM
    first = int(math.floor(low / bucket))
    last = int(math.floor(high / bucket))
    out = []
    for key in range(first, last + 1):
        for x, y, z, route_id, role in buckets.get(key, ()):
            if low <= z <= high:
                out.append(dict(x=x, y=y, z=z, route_id=int(route_id),
                                role=role))
    return out


# ============================================================ validation
def _chord_angle(first, second):
    norm_first = math.sqrt(sum(value * value for value in first))
    norm_second = math.sqrt(sum(value * value for value in second))
    if norm_first <= 0.0 or norm_second <= 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(first, second)) / (norm_first * norm_second)
    dot = max(-1.0, min(1.0, dot))
    return math.acos(dot)


def _samples_curvature_radius(samples):
    """Minimum radius of curvature from consecutive 3D sample triples."""
    minimum = float('inf')
    worst = None
    count = len(samples)
    for index in range(1, count - 1):
        a = samples[index - 1]
        b = samples[index]
        c = samples[index + 1]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        cross = math.sqrt(cx * cx + cy * cy + cz * cz)
        if cross <= 1e-15:
            continue
        area = 0.5 * cross
        ab = _dist3(a, b)
        bc = _dist3(b, c)
        ca = _dist3(c, a)
        if ab <= 0.0 or bc <= 0.0 or ca <= 0.0:
            continue
        radius = ab * bc * ca / (4.0 * area)
        if radius < minimum:
            minimum = radius
            worst = index
    return minimum, worst


def _transition_audit(record, role, step=VALIDATION_STEP_MM, stack=None,
                      expected_z=None):
    """Independent geometric audit of one transition record."""
    forward = dict(record['transition'])
    reverse = dict(record['reverse_transition'])
    z0 = float(record['z0'])
    z1 = float(record['z1'])
    radius = float(record.get('radius_mm', RADIUS_MM))
    layer_id = int(record['target_layer'])
    if expected_z is not None:
        # the assignment row's target z is authoritative for this experiment
        expected_z = float(expected_z)
    else:
        expected_z = None
        if stack is not None:
            try:
                expected_z = float(stack.z_for_layer(layer_id))
            except Exception:
                expected_z = None
        if expected_z is None:
            try:
                expected_z = common.layer_z(layer_id)
            except Exception:
                expected_z = None
    start_xy = _xy_tuple(record['start_xy'])
    end_xy = _xy_tuple(record['end_xy'])
    direction = _unit(record['direction'])
    expected_footprint = 2.0 * radius * math.sin(
        math.acos(max(-1.0, min(1.0, 1.0 - abs(z1 - z0) / (2.0 * radius)))))
    forward_samples = [tuple(float(v) for v in sample)
                       for sample in transition_samples(forward, step=step)]
    reverse_samples = [tuple(float(v) for v in sample)
                       for sample in transition_samples(reverse, step=step)]
    min_radius, _index = _samples_curvature_radius(forward_samples)
    min_radius_rev, _index_rev = _samples_curvature_radius(reverse_samples)
    # G1: chord direction must rotate by at most one sample step of arc angle,
    # the two-arc S-curve must not contain a tangent discontinuity.
    max_chord_angle = 0.0
    for samples in (forward_samples, reverse_samples):
        for index in range(len(samples) - 2):
            first = tuple(samples[index + 1][axis] - samples[index][axis]
                          for axis in range(3))
            second = tuple(samples[index + 2][axis] - samples[index + 1][axis]
                           for axis in range(3))
            max_chord_angle = max(max_chord_angle, _chord_angle(first, second))
    start_tangent_error = 0.0
    end_tangent_error = 0.0
    for samples, expected in ((forward_samples, direction),
                              (reverse_samples, (-direction[0], -direction[1]))):
        first_chord = tuple(samples[1][axis] - samples[0][axis] for axis in range(3))
        last_chord = tuple(samples[-1][axis] - samples[-2][axis] for axis in range(3))
        start_tangent_error = max(start_tangent_error, _chord_angle(
            first_chord, (expected[0], expected[1], 0.0)))
        end_tangent_error = max(end_tangent_error, _chord_angle(
            last_chord, (expected[0], expected[1], 0.0)))
    z_values = [sample[2] for sample in forward_samples]
    z_values += [sample[2] for sample in reverse_samples]
    floor_z = min(z_values)
    ceiling_z = max(z_values)
    checks = dict(
        forward_start_matches=(_dist3((float(forward['start'][0]),
                                       float(forward['start'][1]),
                                       float(forward['z0'])),
                                      (start_xy[0], start_xy[1], z0)) <= 1e-9),
        forward_end_matches=(_dist3((float(forward['end'][0]),
                                     float(forward['end'][1]),
                                     float(forward['z1'])),
                                    (end_xy[0], end_xy[1], z1)) <= 1e-9),
        reverse_start_matches=(_dist3((float(reverse['start'][0]),
                                       float(reverse['start'][1]),
                                       float(reverse['z0'])),
                                      (end_xy[0], end_xy[1], z1)) <= 1e-9),
        reverse_end_matches=(_dist3((float(reverse['end'][0]),
                                     float(reverse['end'][1]),
                                     float(reverse['z1'])),
                                    (start_xy[0], start_xy[1], z0)) <= 1e-9),
        z_span_matches=(abs(float(forward['z0']) - z0) <= 1e-12
                        and abs(float(forward['z1']) - z1) <= 1e-12
                        and abs(float(reverse['z0']) - z1) <= 1e-12
                        and abs(float(reverse['z1']) - z0) <= 1e-12),
        footprint_matches=(abs(float(record['footprint_mm'])
                               - expected_footprint) <= 1e-9
                           and abs(float(forward['footprint_mm'])
                                   - expected_footprint) <= 1e-9),
        length_matches=(abs(float(record['length_mm'])
                            - float(forward['length_mm'])) <= 1e-9
                        and abs(float(forward['length_mm'])
                                - 2.0 * radius * float(forward['theta_rad'])) <= 1e-9),
        radius_15=(abs(radius - RADIUS_MM) <= 1e-12
                   and abs(float(forward['radius_mm']) - RADIUS_MM) <= 1e-12
                   and abs(float(reverse['radius_mm']) - RADIUS_MM) <= 1e-12),
        min_radius_ok=(min(min_radius, min_radius_rev) >= RADIUS_MM - R15_TOL_MM),
        g1_ok=(max_chord_angle <= 1e-2 and start_tangent_error <= 1e-2
               and end_tangent_error <= 1e-2),
        glass_bounds=(floor_z >= common.GLASS_Z_MIN_MM - 1e-9
                      and ceiling_z <= common.GLASS_Z_MAX_MM + 1e-9),
        z0_at_interface=(abs(z0 - common.interface_z('z1')) <= 1e-12
                         or abs(z0 - common.interface_z('z2')) <= 1e-12),
        target_layer_z=(expected_z is not None
                        and abs(z1 - expected_z) <= 1e-9),
    )
    return dict(
        route_id=int(record['route_id']), endpoint_role=str(role),
        candidate_id=record.get('candidate_id'),
        lead_mm=float(record['lead_mm']),
        z0=z0, z1=z1,
        min_radius_mm=float(min_radius),
        min_radius_reverse_mm=float(min_radius_rev),
        max_chord_angle_rad=float(max_chord_angle),
        start_tangent_error_rad=float(start_tangent_error),
        end_tangent_error_rad=float(end_tangent_error),
        floor_z_mm=float(floor_z),
        ceiling_z_mm=float(ceiling_z),
        sample_count=len(forward_samples),
        checks=checks,
        passed=bool(all(checks.values())),
    )


def _endpoint_audit(record, row, role, endpoints):
    """Port/lead/landing identity audit of one selected transition record."""
    port_xy, direction, endpoint_id = _pose_from_row(row, role, endpoints)
    z0 = float(record['z0'])
    z1 = float(record['z1'])
    lead = float(record['lead_mm'])
    start_xy = _xy_tuple(record['start_xy'])
    end_xy = _xy_tuple(record['end_xy'])
    expected_start = (port_xy[0] + direction[0] * lead,
                      port_xy[1] + direction[1] * lead)
    expected_end = (start_xy[0] + direction[0] * float(record['footprint_mm']),
                    start_xy[1] + direction[1] * float(record['footprint_mm']))
    checks = dict(
        lead_at_least_min=(lead >= MIN_LEAD_MM - 1e-9),
        lead_exact=(abs(lead - _dist2(port_xy, start_xy)) <= 1e-9
                    and abs(float(record['lead_part']['length_mm']) - lead) <= 1e-9),
        start_at_expected_q=(_dist2(start_xy, expected_start) <= 1e-9),
        end_at_expected_landing=(_dist2(end_xy, expected_end) <= 1e-9),
        end_on_target_z=(abs(float(record['end_xyz'][2]) - z1) <= 1e-12),
        start_on_interface_z=(abs(float(record['start_xyz'][2]) - z0) <= 1e-12),
        direction_matches=(_dist2(direction, _unit(record['direction'])) <= 1e-12),
        lead_part_matches=(int(record['lead_part']['layer_id']) == INTERFACE_LAYER_ID
                           and abs(float(record['lead_part']['z_mm']) - z0) <= 1e-12
                           and len(record['lead_part']['primitives']) == 1),
    )
    return dict(route_id=int(row['route_id']), endpoint_role=role,
                endpoint_id=endpoint_id, lead_mm=lead,
                checks=checks, passed=bool(all(checks.values())))


def _direct_endpoint_audit(record, row, role, endpoints):
    """Identity audit of one interface-direct endpoint record."""
    port_xy, direction, endpoint_id = _pose_from_row(row, role, endpoints)
    z0 = float(record['z0'])
    start_xy = _xy_tuple(record['start_xy'])
    end_xy = _xy_tuple(record['end_xy'])
    z_interface = float(row.get('interface_z_mm', z0))
    checks = dict(
        direct_flag=bool(record.get('direct')),
        no_transition=(record.get('transition') is None
                       and record.get('reverse_transition') is None),
        zero_lead=(abs(float(record['lead_mm'])) <= 1e-12),
        start_at_port=(_dist2(start_xy, port_xy) <= 1e-12),
        end_at_port=(_dist2(end_xy, port_xy) <= 1e-12),
        on_interface_z=(abs(z0 - z_interface) <= 1e-12
                        and abs(float(record['z1']) - z_interface) <= 1e-12),
        direction_matches=(_dist2(direction, _unit(record['direction'])) <= 1e-12),
        port_xy_present=(record.get('port_xy') is not None
                         and _dist2(_xy_tuple(record['port_xy']), port_xy) <= 1e-12),
    )
    return dict(route_id=int(row['route_id']), endpoint_role=role,
                endpoint_id=endpoint_id, lead_mm=0.0, direct=True,
                checks=checks, passed=bool(all(checks.values())))


def _sampled_curve(record, step):
    return [tuple(float(v) for v in sample)
            for sample in transition_samples(record['transition'], step=step)]


def _pair_distance_audit(selected, step=PAIR_AUDIT_STEP_MM):
    """Independent transition/lead pair distances (sampled + Lipschitz bound)."""
    transitions = []
    leads = []
    for route_id in sorted(int(key) for key in selected):
        pair = selected[route_id]
        for role in ('source', 'target'):
            record = pair[role]
            if record.get('direct') or record.get('transition') is None:
                # interface-direct endpoints have no transition/lead geometry
                continue
            transitions.append((route_id, role, _sampled_curve(record, step)))
            lead_part = record.get('lead_part')
            if lead_part is not None:
                primitive = lead_part['primitives'][0]
                p0 = (float(primitive['p0'][0]), float(primitive['p0'][1]),
                      float(lead_part['z_mm']))
                p1 = (float(primitive['p1'][0]), float(primitive['p1'][1]),
                      float(lead_part['z_mm']))
                leads.append((route_id, role, p0, p1))

    def _worst(minimum, candidate, identifier):
        return (candidate, identifier) if candidate < minimum else (minimum, identifier)

    # --- transition versus transition (different and same routes) ----------
    grid = defaultdict(set)
    for index, (_route_id, _role, samples) in enumerate(transitions):
        for sample in samples:
            grid[_cell_key(sample)].add(index)
    best = float('inf')
    best_ids = None
    best_same_route = float('inf')
    best_same_ids = None
    for index, (route_id, role, samples) in enumerate(transitions):
        nearby = set()
        for sample in samples:
            for key in _neighbour_keys(sample):
                bucket = grid.get(key)
                if bucket:
                    nearby.update(bucket)
        for other_index in nearby:
            if other_index <= index:
                continue
            other_route, other_role, other_samples = transitions[other_index]
            distance = float('inf')
            for sample in samples:
                for other_sample in other_samples:
                    current = _dist3(sample, other_sample)
                    if current < distance:
                        distance = current
                        if distance <= 1e-12:
                            break
            if distance < best:
                best = distance
                best_ids = (route_id, role, other_route, other_role)
            if route_id == other_route and distance < best_same_route:
                best_same_route = distance
                best_same_ids = (route_id, role, other_role)
    transition_vs_transition = dict(
        sampled_min_mm=(None if not math.isfinite(best) else round(best, 9)),
        certified_min_mm=(None if not math.isfinite(best) else round(best - step, 9)),
        worst_pair=list(best_ids) if best_ids else None,
        same_route_sampled_min_mm=(None if not math.isfinite(best_same_route)
                                   else round(best_same_route, 9)),
        same_route_worst=list(best_same_ids) if best_same_ids else None,
    )

    # --- transition versus foreign interface lead --------------------------
    lead_grid = defaultdict(set)
    lead_samples = []
    for lead_index, (route_id, role, p0, p1) in enumerate(leads):
        length = _dist3(p0, p1)
        count = max(1, int(math.ceil(length / step)))
        for index in range(count + 1):
            fraction = index / count
            sample = (p0[0] + (p1[0] - p0[0]) * fraction,
                      p0[1] + (p1[1] - p0[1]) * fraction, p0[2])
            position = len(lead_samples)
            lead_samples.append((route_id, role, sample))
            lead_grid[_cell_key(sample)].add(position)
    best_lead = float('inf')
    best_lead_ids = None
    for route_id, role, samples in transitions:
        nearby = set()
        for sample in samples:
            for key in _neighbour_keys(sample):
                bucket = lead_grid.get(key)
                if bucket:
                    nearby.update(bucket)
        for position in nearby:
            other_route, other_role, other_point = lead_samples[position]
            if other_route == route_id:
                continue
            for sample in samples:
                current = _dist3(sample, other_point)
                if current < best_lead:
                    best_lead = current
                    best_lead_ids = (route_id, role, other_route, other_role)
    transition_vs_lead = dict(
        sampled_min_mm=(None if not math.isfinite(best_lead)
                        else round(best_lead, 9)),
        certified_min_mm=(None if not math.isfinite(best_lead)
                          else round(best_lead - step, 9)),
        worst_pair=list(best_lead_ids) if best_lead_ids else None,
    )

    # --- refine the global minimum pairs with a dense local pass -----------
    def _refine_transition_pair(ids):
        if not ids:
            return None
        lookup = {(route_id, role): samples
                  for route_id, role, samples in transitions}
        first = _sampled_curve_from_lookup(selected, ids[0], ids[1],
                                           PAIR_AUDIT_REFINE_STEP_MM)
        second = _sampled_curve_from_lookup(selected, ids[2], ids[3],
                                            PAIR_AUDIT_REFINE_STEP_MM)
        if not first or not second:
            return None
        minimum = float('inf')
        for sample in first:
            for other_sample in second:
                minimum = min(minimum, _dist3(sample, other_sample))
        return round(minimum, 9)

    transition_vs_transition['refined_min_mm'] = _refine_transition_pair(best_ids)
    if not transitions:
        # only interface-direct endpoints: the pair-clearance rule is vacuous
        return dict(
            transition_vs_transition=transition_vs_transition,
            transition_vs_foreign_lead=transition_vs_lead,
            pass_clearance=True,
            sample_step_mm=step,
            transition_sample_count=0,
        )
    return dict(
        transition_vs_transition=transition_vs_transition,
        transition_vs_foreign_lead=transition_vs_lead,
        pass_clearance=bool(
            (transition_vs_transition['certified_min_mm'] is not None
             and transition_vs_transition['certified_min_mm'] >= CLEARANCE_MM - 1e-9)
            and (transition_vs_lead['certified_min_mm'] is not None
                 and transition_vs_lead['certified_min_mm'] >= CLEARANCE_MM - 1e-9)),
        sample_step_mm=step,
    )


def _sampled_curve_from_lookup(selected, route_id, role, step):
    pair = selected.get(int(route_id))
    if not pair or role not in pair:
        return None
    return _sampled_curve(pair[role], step)


def _fresh_world_recheck(selected, rows, stack, clearance, seed=_FRESH_WORLD_SEED):
    """Rebuild a fresh ``World`` from the selected partials in a new order.

    Interface-direct routes have no fanout partial route (their interface flat
    body is routed later and validated in the assembled world), so they are
    skipped and counted separately.
    """
    row_by_id = {int(row['route_id']): row for row in rows}
    items = []
    missing_rows = []
    direct_route_ids = []
    for route_id in sorted(int(key) for key in selected):
        row = row_by_id.get(route_id)
        if row is None:
            missing_rows.append(route_id)
            continue
        pair = selected[route_id]
        if pair['source'].get('direct') or pair['target'].get('direct'):
            direct_route_ids.append(route_id)
            continue
        for role in ('source', 'target'):
            record = _ensure_record(row, role, pair[role])
            world_id = 2 * route_id + (0 if role == 'source' else 1)
            partial = partial_route(row, role, record, world_id)
            if partial is not None:
                items.append((world_id, role, partial))
    order = list(range(len(items)))
    random.Random(seed).shuffle(order)
    world = World(stack, clearance=clearance)
    violations = []
    for index in order:
        world_id, role, route = items[index]
        found = world.check_route(route)
        if found:
            violations.append(dict(world_id=int(world_id), role=role,
                                   route_id=int(world_id // 2),
                                   violations=_summarise_violations(found, {})))
        world.add_route(route)
    return dict(
        partial_route_count=len(items),
        world_route_count=len(world.plan),
        direct_route_count=len(direct_route_ids),
        skipped_direct_route_ids=direct_route_ids[:50],
        missing_row_route_ids=missing_rows,
        violation_count=len(violations),
        violations=violations[:20],
        passed=not violations and not missing_rows,
    )


def validate_selected(selected, rows=None, stack=None, clearance=CLEARANCE_MM,
                      fresh_world=True, pair_audit=True, log=None):
    """Independent re-validation of the complete selected fanout."""
    stack = stack if stack is not None else common.layer_stack()
    clearance = float(clearance)
    if rows is None:
        rows = []
    normalised = normalize_rows(rows, stack=stack) if rows else []
    row_by_id = {row['route_id']: row for row in normalised}
    selected = {int(key): value for key, value in selected.items()}
    endpoints = common.endpoints()

    transition_audits = []
    endpoint_audits = []
    transition_audit_failures = []
    endpoint_audit_failures = []
    per_route_min_radius = {}
    direct_route_ids = []
    for route_id in sorted(selected):
        pair = selected[route_id]
        row = row_by_id.get(route_id)
        is_direct_route = bool(pair['source'].get('direct')
                               or pair['target'].get('direct'))
        if is_direct_route:
            direct_route_ids.append(route_id)
        min_radius = float('inf')
        for role in ('source', 'target'):
            record = pair[role] if row is None else _ensure_record(
                row, role, pair[role])
            record_direct = (is_direct_route or bool(record.get('direct'))
                             or record.get('transition') is None)
            if row is not None:
                if record_direct:
                    endpoint_audit = _direct_endpoint_audit(record, row, role,
                                                            endpoints)
                else:
                    endpoint_audit = _endpoint_audit(record, row, role, endpoints)
                endpoint_audits.append(endpoint_audit)
                if not endpoint_audit['passed']:
                    endpoint_audit_failures.append(endpoint_audit)
            if record_direct:
                continue
            audit = _transition_audit(
                record, role, stack=stack,
                expected_z=(float(row['target_z_mm']) if row is not None
                            else None))
            transition_audits.append(audit)
            if not audit['passed']:
                transition_audit_failures.append(audit)
            min_radius = min(min_radius,
                             audit['min_radius_mm'],
                             audit['min_radius_reverse_mm'])
        if math.isfinite(min_radius):
            per_route_min_radius[route_id] = round(min_radius, 9)
    transition_route_count = len(selected) - len(direct_route_ids)

    min_radius_all = min((audit['min_radius_mm']
                          for audit in transition_audits), default=None)
    max_chord_angle = max((audit['max_chord_angle_rad']
                           for audit in transition_audits), default=None)
    max_start_tangent_error = max((audit['start_tangent_error_rad']
                                   for audit in transition_audits), default=None)
    max_end_tangent_error = max((audit['end_tangent_error_rad']
                                 for audit in transition_audits), default=None)
    floor_z = min((audit['floor_z_mm'] for audit in transition_audits), default=None)
    ceiling_z = max((audit['ceiling_z_mm'] for audit in transition_audits),
                    default=None)
    worst_radius = sorted(transition_audits,
                          key=lambda item: item['min_radius_mm'])[:5]

    # ---- endpoint coverage -------------------------------------------------
    row_ids = [row['route_id'] for row in normalised]
    selected_ids = sorted(selected)
    missing = [route_id for route_id in row_ids if route_id not in selected]
    extra = [route_id for route_id in selected_ids if route_id not in row_by_id] \
        if normalised else []
    endpoint_counts = Counter()
    for row in normalised:
        endpoint_counts[str(row['source_endpoint'])] += 1
        endpoint_counts[str(row['target_endpoint'])] += 1
    duplicate_endpoints = {key: value for key, value in endpoint_counts.items()
                           if value > 1}
    coverage_checks = dict(
        rows_present=bool(normalised),
        all_rows_selected=(not missing),
        no_unknown_selected=(not extra),
        every_route_has_source=all('source' in selected[route_id]
                                   for route_id in selected_ids),
        every_route_has_target=all('target' in selected[route_id]
                                   for route_id in selected_ids),
        endpoints_unique=(not duplicate_endpoints),
        endpoint_count=(2 * len(selected_ids)),
    )

    pair_distance = _pair_distance_audit(selected) if pair_audit else None
    world_recheck = (_fresh_world_recheck(selected, normalised, stack, clearance)
                     if fresh_world and normalised else None)

    checks = dict(
        transition_count_ok=(len(transition_audits) == 2 * transition_route_count),
        all_transitions_geometrically_valid=(not transition_audit_failures),
        endpoint_identity_ok=(not endpoint_audit_failures),
        min_radius_ge_15=(not transition_audits
                          or (min_radius_all is not None
                              and min_radius_all >= RADIUS_MM - R15_TOL_MM)),
        g1_continuity=(not transition_audits
                       or (max_chord_angle is not None
                           and max_chord_angle <= 1e-2
                           and max_start_tangent_error <= 1e-2
                           and max_end_tangent_error <= 1e-2)),
        glass_bounds_ok=(not transition_audits
                         or (floor_z is not None
                             and floor_z >= common.GLASS_Z_MIN_MM - 1e-9
                             and ceiling_z <= common.GLASS_Z_MAX_MM + 1e-9)),
        pair_clearance_ok=(pair_distance is None
                           or pair_distance['pass_clearance']),
        fresh_world_ok=(world_recheck is None or world_recheck['passed']),
        coverage_ok=all(coverage_checks.values()),
    )
    payload = dict(
        schema='fanout_validation_v1',
        radius_mm=RADIUS_MM,
        clearance_mm=clearance,
        route_count=len(selected_ids),
        transition_count=len(transition_audits),
        transition_route_count=transition_route_count,
        direct_route_count=len(direct_route_ids),
        direct_route_ids=direct_route_ids[:50],
        endpoint_count=len(endpoint_audits),
        passed=bool(all(checks.values())),
        checks=checks,
        radius_audit=dict(
            min_radius_mm=min_radius_all,
            min_radius_required_mm=RADIUS_MM - R15_TOL_MM,
            max_chord_angle_rad=max_chord_angle,
            max_start_tangent_error_rad=max_start_tangent_error,
            max_end_tangent_error_rad=max_end_tangent_error,
            worst_transitions=[dict(route_id=item['route_id'],
                                    endpoint_role=item['endpoint_role'],
                                    min_radius_mm=item['min_radius_mm'])
                               for item in worst_radius],
            per_route_min_radius_mm={str(key): value
                                     for key, value in sorted(per_route_min_radius.items())},
        ),
        glass_bounds=dict(floor_z_mm=floor_z, ceiling_z_mm=ceiling_z,
                          allowed_z_mm=[common.GLASS_Z_MIN_MM,
                                        common.GLASS_Z_MAX_MM]),
        endpoint_audit=dict(passed=not endpoint_audit_failures,
                            failures=endpoint_audit_failures[:20]),
        coverage=coverage_checks,
        missing_route_ids=missing[:50],
        extra_route_ids=extra[:50],
        duplicate_endpoints=duplicate_endpoints,
        pair_distance_audit=pair_distance,
        fresh_world_recheck=world_recheck,
        transition_failures=transition_audit_failures[:20],
    )
    # ``pass`` is the key used by the report/validator tooling; keep the Python
    # friendly ``passed`` spelling as well.
    payload['pass'] = payload['passed']
    return payload


# ============================================================ artifacts
def _json_counter(counter):
    return {str(key): int(value) for key, value in
            sorted(counter.items(), key=lambda item: str(item[0]))}


def _route_group_name(row):
    manual_group = str(row.get('manual_group') or '').strip()
    if manual_group:
        return manual_group
    layer_role = str(row.get('layer_role') or '').strip() or 'other'
    return f"{row.get('plane')}|{row.get('relation_geom') or 'other'}|{layer_role}"


def _group_stats(result, validation):
    rows = result.get('rows') or []
    selected = result.get('selected') or {}
    failures = result.get('failures') or []
    attempts = result.get('attempts') or []
    failure_by_route = {int(item['route_id']): item for item in failures}
    per_route_min_radius = {}
    if validation:
        per_route_min_radius = {
            int(key): float(value) for key, value in
            (validation.get('radius_audit', {})
             .get('per_route_min_radius_mm', {}) or {}).items()}
    conflict_by_route = Counter()
    checks_by_route = Counter()
    for attempt in attempts:
        route_id = int(attempt.get('route_id', -1))
        checks_by_route[route_id] += 1
        if not attempt.get('accepted'):
            conflict_by_route[route_id] += 1
    groups = OrderedDict()
    for row in rows:
        group = _route_group_name(row)
        bucket = groups.setdefault(group, dict(
            group=group,
            input_routes=0,
            input_rows=0,
            endpoints_needing_transition=0,
            success_routes=0,
            success_endpoints=0,
            direct_routes=0,
            failed_routes=0,
            failed_route_ids=[],
            failure_reasons=Counter(),
            transition_conflicts=0,
            candidate_checks=0,
            r15_legal_routes=0,
            r15_failed_route_ids=[],
            min_radius_mm=None,
            lead_histogram=Counter(),
            selected_leads={},
        ))
        route_id = int(row['route_id'])
        needs_transition = bool(row.get('needs_transition', True))
        bucket['input_routes'] += 1
        bucket['input_rows'] += 1
        if needs_transition:
            bucket['endpoints_needing_transition'] += 2
        bucket['candidate_checks'] += checks_by_route.get(route_id, 0)
        bucket['transition_conflicts'] += conflict_by_route.get(route_id, 0)
        pair = selected.get(route_id)
        if pair is None:
            failure = failure_by_route.get(route_id, {})
            bucket['failed_routes'] += 1
            bucket['failed_route_ids'].append(route_id)
            bucket['failure_reasons'][str(failure.get('reason', 'unknown'))] += 1
            continue
        bucket['success_routes'] += 1
        if pair['source'].get('direct') or not needs_transition:
            # interface-direct: no transition endpoint, no lead histogram entry
            bucket['direct_routes'] += 1
            continue
        bucket['success_endpoints'] += 2
        bucket['selected_leads'][str(route_id)] = [
            float(pair['source']['lead_mm']),
            float(pair['target']['lead_mm'])]
        bucket['lead_histogram'][
            f"{float(pair['source']['lead_mm']):g}/"
            f"{float(pair['target']['lead_mm']):g}"] += 1
        radius = per_route_min_radius.get(route_id)
        if radius is None:
            continue
        bucket['min_radius_mm'] = radius if bucket['min_radius_mm'] is None \
            else min(bucket['min_radius_mm'], radius)
        if radius >= RADIUS_MM - R15_TOL_MM:
            bucket['r15_legal_routes'] += 1
        else:
            bucket['r15_failed_route_ids'].append(route_id)
    ordered = OrderedDict()
    for group in sorted(groups):
        bucket = groups[group]
        bucket['failure_reasons'] = _json_counter(bucket['failure_reasons'])
        bucket['lead_histogram'] = _json_counter(bucket['lead_histogram'])
        bucket['failed_route_ids'] = bucket['failed_route_ids'][:200]
        bucket['r15_failed_route_ids'] = bucket['r15_failed_route_ids'][:200]
        ordered[group] = bucket
    return ordered


def write_artifacts(result, out_dir, experiment_name='experiment_B',
                    landings_out=True, validation=None, log=None):
    """Write every fanout artifact of one planning stage.

    Top level of ``out_dir``: ``fanout_candidates.json``,
    ``fanout_selected.json``, ``fanout_validation.json`` and
    ``layerwise_endpoints/endpoints.json``.
    ``out_dir/<experiment_name>/``: per-experiment summary for the manual 8
    groups (experiment B) or for all groups (experiment D), including
    ``failed_routes.json`` and ``per_group.json``.  Calling the function again
    with a different ``experiment_name`` never overwrites the previous
    experiment directory.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = {int(key): value for key, value in
                (result.get('selected') or {}).items()}
    rows = result.get('rows') or []
    stack = result.get('stack')
    clearance = float(result.get('clearance', CLEARANCE_MM))
    failures = list(result.get('failures') or [])
    if validation is None:
        validation = validate_selected(selected, rows, stack=stack,
                                       clearance=clearance)
    stats = dict(result.get('stats') or {})
    stats.setdefault('success_routes', len(selected))
    stats.setdefault('failures', len(failures))

    # ---- fanout_candidates.json -------------------------------------------
    attempts = list(result.get('attempts') or [])
    accepted = [item for item in attempts if item.get('accepted')]
    rejected = [item for item in attempts if not item.get('accepted')]
    reason_counter = Counter(str(item.get('reason')) for item in rejected)
    candidates_payload = dict(
        schema='fanout_candidates_v1',
        radius_mm=RADIUS_MM,
        clearance_mm=clearance,
        lead_candidates=[float(value) for value in
                         stats.get('lead_candidates', LEAD_CANDIDATES)],
        route_count=len(selected),
        candidate_check_count=len(attempts),
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        rejected_reason_counts=_json_counter(reason_counter),
        attempts=attempts,
        failures=failures,
        stats=stats,
    )
    common.write_json(out_dir / 'fanout_candidates.json', candidates_payload)

    # ---- fanout_selected.json ---------------------------------------------
    selected_payload = dict(
        schema='fanout_selected_v1',
        radius_mm=RADIUS_MM,
        clearance_mm=clearance,
        route_count=len(selected),
        selected={str(route_id): dict(source=pair['source'],
                                      target=pair['target'])
                  for route_id, pair in sorted(selected.items())},
    )
    common.write_json(out_dir / 'fanout_selected.json', selected_payload)

    # ---- fanout_validation.json -------------------------------------------
    common.write_json(out_dir / 'fanout_validation.json', validation)

    # ---- layerwise_endpoints/endpoints.json -------------------------------
    if landings_out:
        endpoints_payload = []
        for route_id in sorted(selected):
            pair = selected[route_id]
            for role in ('source', 'target'):
                record = pair[role]
                is_direct = bool(record.get('direct'))
                endpoints_payload.append(dict(
                    route_id=route_id,
                    endpoint_role=role,
                    plane=(record.get('plane') if record.get('plane') is not None
                           else None),
                    endpoint_id=record.get('endpoint_id'),
                    candidate_id=record.get('candidate_id'),
                    direct=is_direct,
                    n_transitions=(0 if is_direct else 1),
                    lead_mm=float(record['lead_mm']),
                    direction=[float(record['direction'][0]),
                               float(record['direction'][1])],
                    z0=float(record['z0']),
                    z1=float(record['z1']),
                    target_layer=int(record['target_layer']),
                    target_z_mm=float(record['target_z_mm']),
                    start_xy=[float(record['start_xy'][0]),
                              float(record['start_xy'][1])],
                    start_xyz=[float(value) for value in record['start_xyz']],
                    end_xy=[float(record['end_xy'][0]),
                            float(record['end_xy'][1])],
                    end_xyz=[float(value) for value in record['end_xyz']],
                    footprint_mm=float(record['footprint_mm']),
                    length_mm=float(record['length_mm']),
                    theta_rad=float(record['theta_rad']),
                    radius_mm=float(record['radius_mm']),
                    geometry=str(record['geometry']),
                    port_xy=([float(record['port_xy'][0]),
                              float(record['port_xy'][1])]
                             if record.get('port_xy') is not None else None),
                    transition=record['transition'],
                    reverse_transition=record['reverse_transition'],
                ))
        common.write_json(out_dir / 'layerwise_endpoints' / 'endpoints.json',
                          dict(schema='fanout_layerwise_endpoints_v1',
                               endpoint_count=len(endpoints_payload),
                               endpoints=endpoints_payload))

    # ---- per-experiment summary -------------------------------------------
    experiment_dir = out_dir / experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    groups = _group_stats(result, validation)
    manual_groups = OrderedDict(
        (name, groups[name]) for name in common.MANUAL_GROUPS if name in groups)
    validation_passed = bool(validation.get('pass'))
    failed_rows = []
    row_by_id = {int(row['route_id']): row for row in rows}
    for failure in failures:
        route_id = int(failure['route_id'])
        row = row_by_id.get(route_id, {})
        failed_rows.append(dict(
            route_id=route_id,
            role=failure.get('role'),
            reason=failure.get('reason'),
            blockers=failure.get('blockers') or [],
            manual_group=row.get('manual_group') or '',
            plane=row.get('plane'),
            target_layer=row.get('target_layer'),
            detail=failure.get('detail'),
        ))
    per_group_payload = dict(
        schema='fanout_experiment_per_group_v1',
        experiment=experiment_name,
        route_count=len(rows),
        group_count=len(groups),
        manual_group_count=len(manual_groups),
        manual_groups=manual_groups,
        groups=groups,
    )
    common.write_json(experiment_dir / 'per_group.json', per_group_payload)
    validation_direct = int((validation or {}).get('direct_route_count', 0))
    validation_transition_routes = int((validation or {}).get(
        'transition_route_count', len(selected) - validation_direct))
    validation_transitions = int((validation or {}).get(
        'transition_count', 2 * validation_transition_routes))
    summary = dict(
        schema='fanout_experiment_summary_v1',
        experiment=experiment_name,
        input_line_count=len(rows),
        input_manual_routes=sum(1 for row in rows if str(row.get('manual_group') or '')),
        attempted_routes=int(stats.get('planned_routes', len(rows))),
        candidate_checks=int(stats.get('candidate_checks', len(attempts))),
        success_routes=len(selected),
        success_endpoints=2 * len(selected),
        direct_routes=validation_direct,
        transition_routes=validation_transition_routes,
        transition_count=validation_transitions,
        success_transition_endpoints=validation_transitions,
        failure_count=len(failures),
        failure_reasons=_json_counter(Counter(
            str(item.get('reason')) for item in failures)),
        transition_conflicts=sum(int(bucket['transition_conflicts'])
                                 for bucket in groups.values()),
        fixed_routes=int(stats.get('fixed_routes', 0)),
        fixed_conflicts=int(stats.get('fixed_conflicts', 0)),
        ripups=int(stats.get('ripups', 0)),
        r15_legal=(validation.get('radius_audit', {}) or {}).get('min_radius_mm')
        is not None and validation['checks'].get('min_radius_ge_15', False),
        min_radius_mm=(validation.get('radius_audit', {}) or {}).get('min_radius_mm'),
        validation_pass=validation_passed,
        validation_checks=validation.get('checks'),
        pair_clearance_ok=(validation.get('checks') or {}).get('pair_clearance_ok'),
        fresh_world_ok=(validation.get('checks') or {}).get('fresh_world_ok'),
        lead_histogram=stats.get('lead_histogram'),
        seconds=stats.get('seconds'),
        failed_route_ids=[item['route_id'] for item in failed_rows][:500],
    )
    common.write_json(experiment_dir / 'summary.json', summary)
    common.write_json(experiment_dir / 'failed_routes.json', dict(
        schema='fanout_experiment_failed_routes_v1',
        experiment=experiment_name,
        failure_count=len(failed_rows),
        failures=failed_rows,
    ))
    if manual_groups:
        common.write_json(experiment_dir / 'manual_group_summary.json', dict(
            schema='fanout_manual_group_summary_v1',
            experiment=experiment_name,
            manual_groups=manual_groups,
        ))
    if log is not None:
        log(f'[fanout] wrote artifacts: {out_dir} '
            f'(experiment={experiment_name}, routes={len(selected)}, '
            f'failures={len(failures)}, validation_pass={validation_passed})')
    return dict(validation=validation, summary=summary, per_group=groups,
                experiment_dir=str(experiment_dir))
