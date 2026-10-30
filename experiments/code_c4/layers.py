# -*- coding: utf-8 -*-
"""C4 layer stack: L2..L13 on the frozen 150 um pitch above Z2 = 0.5 mm."""
from __future__ import annotations

import math

from four_side_1024.manual_c4 import z1_multilayer_150um as Z

Z = Z
Z1, Z2 = 0.0, 0.5
PITCH = 0.15
BASE_Z = 0.65
HEIGHTS = {layer: round(BASE_Z + (layer - 2) * PITCH, 6)
           for layer in range(2, 14)}
ALL_LAYERS = tuple(sorted(HEIGHTS))
MAX_SUPPORTED_LAYER = 13
RADIUS = 15.0
CLEARANCE = 0.08


def layer_z(layer):
    return float(HEIGHTS[int(layer)])


def max_layer_for(total_layers):
    """7/9/11/13 total layers -> highest routing layer id (L2..L_max)."""
    return int(total_layers)


def stack_payload(max_layer):
    routing = list(range(2, int(max_layer) + 1))
    all_ids = [1] + routing
    allowed = {layer_id: list(all_ids) for layer_id in all_ids}
    layers = {'1': dict(layer_id=1, layer_type='interface',
                        physical_z_mm=None,
                        interface_rows={'z1': Z1, 'z2': Z2},
                        allowed_transitions=allowed[1])}
    for layer_id in routing:
        layers[str(layer_id)] = dict(
            layer_id=int(layer_id), layer_type='routing',
            physical_z_mm=float(HEIGHTS[layer_id]), interface_rows={},
            allowed_transitions=allowed[layer_id])
    return dict(schema='four_side_1024_v2_l3d_layer_stack_v1',
                provenance='unconfirmed_simulation',
                formal_acceptance_allowed=False,
                note=('c4_symmetric_multilayer: 0.15 mm pitch above Z2=0.5; '
                      f'layers L2..L{max_layer}; strict C4 orbits'),
                interface_layer=1, layers=layers,
                routing_heights_mm={str(k): float(HEIGHTS[k]) for k in routing})


def transition_geometry(dz, radius=RADIUS):
    dz = abs(float(dz))
    theta = math.acos(max(-1.0, min(1.0, 1.0 - dz / (2.0 * radius))))
    return dict(dz_mm=dz, theta_rad=float(theta),
                footprint_mm=2.0 * radius * math.sin(theta),
                length_mm=2.0 * radius * theta)


def footprint(ride_layer, base_z=Z1, radius=RADIUS):
    return float(transition_geometry(layer_z(ride_layer) - base_z,
                                     radius)['footprint_mm'])


def validate_payload(payload, max_layer, log=print):
    """Validate with the frozen validator extended to ``max_layer`` layers."""
    from four_side_1024.l3d import validate_l3d_multi as V
    from four_side_1024.v3c4.inputs import ENDPOINTS
    routing = tuple(range(2, int(max_layer) + 1))
    V.ROUTING_LAYER_IDS = routing
    records_payload = Z.read_json(Z.CAMPAIGN / 'phase2_2d' / 'routes_1024.json')
    identity = {'available': True, 'error': None, 'planes': {}}
    for plane in ('z1', 'z2'):
        routes = {}
        for record in records_payload['routes']:
            if record.get('plane') != plane:
                continue
            rid = int(record['route_id'])
            routes[rid] = dict(
                route_id=rid,
                source_endpoint=record['source_endpoint'],
                target_endpoint=record['target_endpoint'],
                source_side=record['source_side'],
                target_side=record['target_side'],
                source_row=int(record['source_row']),
                target_row=int(record['target_row']),
                relation=record['relation'],
                pair=record['pair'])
        identity['planes'][plane] = {'routes': routes, 'endpoints': ENDPOINTS}
    V._PORT_CACHE['identity'] = identity
    V._port_identity = lambda: identity
    log(f'[c4] validator routing layers: {routing}')
    return V.validate_payload(payload, allow_exploratory=True)
