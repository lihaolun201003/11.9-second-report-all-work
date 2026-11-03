"""True-XYZ collision world for the corrected L1–L5 model.

The model keeps two collision mechanisms that mirror the frozen rules:

* **same physical plane** (identical ``z_mm``): the frozen strict 2D D56 index is
  used, including its legal-crossing windows.  A "physical plane" is identified by
  the real ``z`` coordinate, never by ``layer_id``: L1 therefore contributes TWO
  physical planes (z1 row z=0.0 and z2 row z=0.5).
* **different physical planes** (any two parts whose z differ): true 3D
  centre-line distance must be >= 0.08 mm; no crossing exemption is applied.  This
  covers transitions versus flats/transitions and cross-plane flat pairs.
* **self clearance** of one route is checked in true 3D.
"""
from __future__ import annotations

import math

from ..d56.index import D56Index, prepare
from ..fsd25d.world25d import ClearanceWorld3D
from ..fslw import config as C
from .layers import INTERFACE_LAYER_ID


def part_id(route_id, index):
    return int(route_id) * 1000 + int(index)


def plane_key(z_mm):
    return round(float(z_mm), 9)


class PlaneWorld:
    """Strict 2D worlds, one per *physical* z plane."""

    def __init__(self):
        self.indices = {}
        self.parts = {}

    def _index(self, z_mm):
        key = plane_key(z_mm)
        index = self.indices.get(key)
        if index is None:
            index = D56Index(width=C.WIDTH_MM, gap=C.EDGE_GAP_MM,
                             sagitta=C.SAGITTA_MM,
                             min_cross_angle_deg=C.MIN_CROSS_ANGLE_DEG,
                             crossing_policy='strict')
            self.indices[key] = index
            self.parts[key] = {}
        return index

    def evaluate(self, primitives, z_mm):
        if not primitives:
            return None
        return self._index(z_mm).evaluate(prepare(primitives))

    def add(self, part_id_, primitives, z_mm):
        if not primitives:
            return
        key = plane_key(z_mm)
        self._index(z_mm).add(part_id_, prepare(primitives))
        self.parts[key][part_id_] = list(primitives)

    def remove(self, part_id_, z_mm):
        key = plane_key(z_mm)
        index = self.indices.get(key)
        if index is not None:
            index.remove(part_id_)
        self.parts.get(key, {}).pop(part_id_, None)

    def counts(self):
        return {key: len(parts) for key, parts in self.parts.items()}


class World:
    """Combined true-3D world for the corrected model."""

    def __init__(self, layer_stack, clearance=None):
        self.stack = layer_stack
        self.clearance = float(C.CLEARANCE_MM if clearance is None else clearance)
        self.planes = PlaneWorld()
        self.clearance_world = ClearanceWorld3D(self.clearance)
        self.plan = {}

    # -- route helpers -----------------------------------------------------
    @staticmethod
    def flat_route(route_id, plane, primitives, z_mm, layer_id=INTERFACE_LAYER_ID,
                   row=None):
        from ..fsd25d.path3d import path_length
        prims = [dict(prim) for prim in primitives]
        return dict(route_id=int(route_id), plane=plane,
                    source_row=(row if row is not None else
                                (1 if plane == 'z1' else 2)),
                    target_row=(row if row is not None else
                                (1 if plane == 'z1' else 2)),
                    start_z_mm=float(z_mm), end_z_mm=float(z_mm),
                    layer_sequence=[int(layer_id)],
                    layer_z_sequence=[float(z_mm)], n_transitions=0,
                    lifted=False, layers_used=[int(layer_id)],
                    xy_length_mm=float(path_length(prims)),
                    length_mm=float(path_length(prims)), z_span_mm=0.0,
                    parts=[dict(kind='flat', layer_id=int(layer_id),
                                z_mm=float(z_mm),
                                length_mm=float(path_length(prims)),
                                primitives=prims)])

    @staticmethod
    def check_structure(route):
        """Cheap structural sanity check of a built route (router-side)."""
        parts = route.get('parts') or []
        if not parts:
            return ['empty_parts']
        errors = []
        if parts[0]['kind'] != 'flat' or parts[-1]['kind'] != 'flat':
            errors.append('route_must_start_and_end_flat')
        previous = None
        for part in parts:
            if part['kind'] == 'flat':
                if not part.get('primitives'):
                    errors.append('empty_flat_part')
                if previous is not None:
                    if previous['kind'] == 'flat':
                        errors.append('consecutive_flats')
                    else:
                        end = (previous['end'][0], previous['end'][1],
                               previous['z1'])
                        start = (part['primitives'][0]['p0'][0],
                                 part['primitives'][0]['p0'][1],
                                 part['z_mm'])
                        if math.dist(end, start) > 1e-6:
                            errors.append('transition_flat_position_mismatch')
                        if abs(previous['z1'] - part['z_mm']) > 1e-9:
                            errors.append('transition_flat_height_mismatch')
            else:
                if previous is None or previous['kind'] != 'flat':
                    errors.append('transition_not_between_flats')
                else:
                    end = previous['primitives'][-1]['p1']
                    start = part['start']
                    if math.dist((end[0], end[1]), (start[0], start[1])) > 1e-6:
                        errors.append('flat_transition_position_mismatch')
                    if abs(previous['z_mm'] - part['z0']) > 1e-9:
                        errors.append('flat_transition_height_mismatch')
            previous = part
        return errors

    # -- world maintenance -------------------------------------------------
    def add_route(self, route):
        for index, part in enumerate(route['parts']):
            if part['kind'] == 'flat':
                self.planes.add(part_id(route['route_id'], index),
                                part['primitives'], part['z_mm'])
        self.clearance_world.add_route(route)
        self.plan[int(route['route_id'])] = route

    def remove_route(self, route_id):
        route = self.plan.pop(int(route_id), None)
        if route is None:
            return None
        for index, part in enumerate(route['parts']):
            if part['kind'] == 'flat':
                self.planes.remove(part_id(route_id, index), part['z_mm'])
        # ClearanceWorld3D has no incremental removal: rebuild it from the
        # remaining plan so that a removed route can never block later checks.
        self.clearance_world = ClearanceWorld3D(self.clearance)
        for remaining in self.plan.values():
            self.clearance_world.add_route(remaining)
        return route

    def rebuild(self, plan=None):
        plan = self.plan if plan is None else plan
        self.planes = PlaneWorld()
        self.clearance_world = ClearanceWorld3D(self.clearance)
        self.plan = {}
        for route in plan.values():
            self.add_route(route)

    # -- checks ------------------------------------------------------------
    def check_flat(self, primitives, z_mm):
        """Strict same-physical-plane check of one flat sub-chain."""
        return self.planes.evaluate(primitives, z_mm)

    def check_route(self, route, check_self=True):
        violations = []
        # Corrected process rule: different physical planes are legal when
        # their vertical separation is at least the confirmed 50 um layer
        # pitch.  This is a global layer-stack condition independent of XY;
        # checking it online prevents the builder from accepting a plane that
        # is closer than the pitch to an existing plane.
        flat_zs = sorted(float(key) for key in self.planes.parts)
        for part in route.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            z = float(part['z_mm'])
            for other_z in flat_zs:
                dz = abs(z - other_z)
                if 1e-9 < dz < self.clearance - 1e-9:
                    violations.append(dict(
                        kind='flat_cross_plane_too_close',
                        route_id=int(route['route_id']),
                        z_mm=z, other_z_mm=other_z,
                        detail=f'layer_gap={dz:.9g}<{self.clearance:g}'))
                    return violations
        for index, part in enumerate(route['parts']):
            if part['kind'] != 'flat':
                continue
            evaluation = self.planes.evaluate(part['primitives'], part['z_mm'])
            if evaluation is not None and not evaluation.valid:
                blockers = list(getattr(evaluation, 'blockers', []) or [])
                violations.append(dict(kind='flat_same_plane_conflict',
                                       route_id=int(route['route_id']),
                                       z_mm=float(part['z_mm']),
                                       blockers=blockers[:20]))
                return violations
        violations.extend(self.clearance_world.check_route(
            route, check_self=bool(check_self)))
        return violations

    def stats(self):
        return dict(planes=self.planes.counts(), routes=len(self.plan))
