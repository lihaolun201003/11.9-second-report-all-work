# -*- coding: utf-8 -*-
"""Shared constants, data loaders and IO helpers for the Fanout-First 1024 system.

This module is the single source of truth for the process/layer model, the true
1024-channel connectivity, the physical port table and the manual-U templates.

Nothing here re-generates connections: every route identity and every port pair
comes from the original V4 1024-connection dataset.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
"""...\\OpticalWaveguideRouter2D"""

OUTPUT_ROOT = ROOT / 'outputs' / 'manual_c4_new_connectivity'
RUN_NAME = 'FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024'
RUN_DIR = OUTPUT_ROOT / RUN_NAME

#: original (never modified) 1024-channel connection dataset of the previous
#: accepted 2D campaign.  ``routes_1024.json`` holds the true route table.
V4_DIR = OUTPUT_ROOT / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN' / 'phase2_2d_selected'
V4_ROUTES_JSON = V4_DIR / 'routes_1024.json'
V4_CONNECTIVITY_JSON = V4_DIR / 'connectivity_1024.json'
INPUT_DIR = OUTPUT_ROOT / 'inputs'
INPUT_CONNECTIVITY_CSV = INPUT_DIR / 'connectivity_1024.csv'
INPUT_CONNECTIVITY_JSON = INPUT_DIR / 'connectivity_1024.json'

EXCEL_PATH = Path(r'C:\Users\lihao\Desktop\Z2人工U_具体端口分组_L10-L13_源数据待校验.xlsx')

#: previous-round experiment boundaries (used only as the comparison baseline)
PREV_DIR = OUTPUT_ROOT / 'BIDIRECTIONAL_1MM_50UM_CORRECTED_FULL'
PREV_ASSIGNMENT = PREV_DIR / 'assignment_1024.csv'
PREV_ROUTES = PREV_DIR / 'routes_l3d.json'
PREV_VALIDATION = PREV_DIR / 'validation.json'
PREV_STATS = PREV_DIR / 'final_stats.json'

# ---------------------------------------------------------------- process rules
GLASS_THICKNESS_MM = 1.000
GLASS_Z_MIN_MM = -0.35
GLASS_Z_MAX_MM = 0.65
Z1_INTERFACE_MM = 0.0
Z2_INTERFACE_MM = 0.5
MIN_LAYER_PITCH_MM = 0.05      # confirmed process input (50 um)
MIN_3D_CLEARANCE_MM = 0.05     # true 3D centre-line clearance used by the world
WIDTH_MM = 0.05
EDGE_GAP_MM = 0.03             # same-layer 2D rule (original D56: 0.05 + 0.03)
CLEARANCE_2D_MM = WIDTH_MM + EDGE_GAP_MM
MIN_BEND_RADIUS_MM = 15.0
R15_MM = 15.0
LEGACY_GLOBAL_CLEARANCE_MM = 0.08   # NEVER restored as a global 3D rule

#: 18 routing body layers of the 1 mm / 50 um model (z in mm).
PHYSICAL_LAYERS = OrderedDict([
    (2, -0.35), (3, -0.29), (4, -0.23), (5, -0.17),   # Z1 manual U (fixed)
    (6, -0.11), (7, -0.05),                            # Z1 remaining opposite
    (8, 0.05), (9, 0.10),                              # Z2 remaining candidates
    (10, 0.15), (11, 0.20), (12, 0.25), (13, 0.30),    # Z2 manual U (fixed)
    (14, 0.35), (15, 0.40), (16, 0.45),                # Z2 remaining (down)
    (17, 0.55), (18, 0.60), (19, 0.65),                # Z2 remaining (up)
])
ROUTING_LAYER_IDS = tuple(PHYSICAL_LAYERS)
INTERFACE_Z = {'z1': Z1_INTERFACE_MM, 'z2': Z2_INTERFACE_MM}

#: fixed manual-group -> physical layer mapping (the user's template).
MANUAL_GROUPS = OrderedDict([
    # group        plane  target layer  pattern             sides
    ('Z1-U1', dict(plane='z1', layer=2, pattern='NS-first',  sides='NS')),
    ('Z1-U2', dict(plane='z1', layer=3, pattern='NS-second', sides='NS')),
    ('Z1-U3', dict(plane='z1', layer=4, pattern='EW-first',  sides='EW')),
    ('Z1-U4', dict(plane='z1', layer=5, pattern='EW-second', sides='EW')),
    ('Z2-U1', dict(plane='z2', layer=10, pattern='NS-first',  sides='NS')),
    ('Z2-U2', dict(plane='z2', layer=11, pattern='EW-first',  sides='EW')),
    ('Z2-U3', dict(plane='z2', layer=12, pattern='NS-second', sides='NS')),
    ('Z2-U4', dict(plane='z2', layer=13, pattern='EW-second', sides='EW')),
])
MANUAL_LAYER_TO_GROUP = {spec['layer']: name
                         for name, spec in MANUAL_GROUPS.items()}

#: Z2 manual-U connector-number templates (user provided; NOT generated data).
Z2_TEMPLATES = OrderedDict([
    ('Z2-U1', dict(side_kind='NS', layer=10, numbering='first',
                   pairs=[('01', '08'), ('02', '08'), ('02', '07'), ('03', '07'),
                          ('09', '16'), ('09', '15'), ('10', '15'), ('10', '14')])),
    ('Z2-U2', dict(side_kind='EW', layer=11, numbering='first',
                   pairs=[('01', '08'), ('02', '08'), ('02', '07'), ('03', '07'),
                          ('09', '16'), ('09', '15'), ('10', '15'), ('10', '14')])),
    ('Z2-U3', dict(side_kind='NS', layer=12, numbering='second',
                   pairs=[('01', '16'), ('02', '15'), ('03', '14'),
                          ('04', '13'), ('05', '12'), ('06', '11')])),
    ('Z2-U4', dict(side_kind='EW', layer=13, numbering='second',
                   pairs=[('01', '16'), ('02', '15'), ('03', '14'),
                          ('04', '13'), ('05', '12'), ('06', '11')])),
])

SIDE_INWARD = {'N': (0.0, -1.0), 'S': (0.0, 1.0),
               'E': (-1.0, 0.0), 'W': (1.0, 0.0)}
SIDE_ORDER = ('N', 'E', 'S', 'W')


# ---------------------------------------------------------------- basic IO
def write_json(path, obj, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent,
                               default=_json_default), encoding='utf-8')
    return path


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:  # pragma: no cover
        pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_csv_rows(path):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    return rows, digest


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return path


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- endpoints
_ENDPOINTS = None


def endpoints():
    """All 2048 physical ports (authoritative fslw port model)."""
    global _ENDPOINTS
    if _ENDPOINTS is None:
        from ..v3c4 import inputs as V3
        _ENDPOINTS = V3.ENDPOINTS
    return _ENDPOINTS


def endpoint_pose(endpoint_id):
    ep = endpoints()[endpoint_id]
    return ((float(ep['routing_xy'][0]), float(ep['routing_xy'][1])),
            (float(ep['inward'][0]), float(ep['inward'][1])),
            float(ep['z_mm']))


# ---------------------------------------------------------------- 1024 routes
_ROUTES = None
_ROUTE_GROUPS = None


def _build_route_records(payload):
    routes = []
    for record in payload['routes']:
        rid = int(record['route_id'])
        src = str(record['source_endpoint'])
        dst = str(record['target_endpoint'])
        eps = endpoints()
        if src not in eps or dst not in eps:
            raise KeyError(f'route {rid}: endpoint not in port table')
        se, te = eps[src], eps[dst]
        routes.append(dict(
            route_id=rid,
            plane=record['plane'],
            z_mm=float(record.get('z_mm', INTERFACE_Z[record['plane']])),
            relation=record.get('relation') or record.get('pair'),
            pair=record.get('pair'),
            source_endpoint=src,
            target_endpoint=dst,
            source_side=se['side'],
            target_side=te['side'],
            source_connector=se['connector'],
            target_connector=te['connector'],
            source_row=int(se['row']), target_row=int(te['row']),
            source_column=int(se['column']), target_column=int(te['column']),
            source_channel=int(se['channel']), target_channel=int(te['channel']),
            source_xy=(float(se['routing_xy'][0]), float(se['routing_xy'][1])),
            target_xy=(float(te['routing_xy'][0]), float(te['routing_xy'][1])),
            source_inward=(float(se['inward'][0]), float(se['inward'][1])),
            target_inward=(float(te['inward'][0]), float(te['inward'][1])),
            status=record.get('status'),
        ))
    return routes


def routes():
    """The true 1024 original connections (never modified)."""
    global _ROUTES
    if _ROUTES is None:
        payload = read_json(V4_ROUTES_JSON)
        _ROUTES = _build_route_records(payload)
        if len(_ROUTES) != 1024:
            raise ValueError(f'expected 1024 routes, got {len(_ROUTES)}')
    return _ROUTES


def route_by_id():
    return {route['route_id']: route for route in routes()}


def rotation_groups():
    """Original C4 rotation groups (256 x 4 routes), plane-local."""
    global _ROUTE_GROUPS
    if _ROUTE_GROUPS is None:
        payload = read_json(V4_ROUTES_JSON)
        groups = payload['rotation_groups']
        _ROUTE_GROUPS = [dict(group_id=int(g['group_id']), plane=g['plane'],
                              kind=g['kind'], pair=g.get('pair'),
                              route_ids=[int(v) for v in g['route_ids']])
                         for g in groups]
        seen = {}
        for group in _ROUTE_GROUPS:
            for rid in group['route_ids']:
                if rid in seen:
                    raise ValueError(f'route {rid} in two rotation groups')
                seen[rid] = group['group_id']
        if len(seen) != 1024:
            raise ValueError('rotation-group coverage is not 1024')
    return _ROUTE_GROUPS


def route_group_map():
    mapping = {}
    for group in rotation_groups():
        for rid in group['route_ids']:
            mapping[rid] = group
    return mapping


# ---------------------------------------------------------------- layer stack
_STACK = None


def layer_stack():
    """18-layer 1 mm / 50 um stack accepted by the l3d world."""
    global _STACK
    if _STACK is None:
        from ..l3d.layers import build_stack
        _STACK = build_stack(
            'fanout_first_18l',
            heights={int(k): float(v) for k, v in PHYSICAL_LAYERS.items()},
            note='1 mm glass, 50 um minimum pitch, Z1 interface z=0, Z2 z=0.5')
    return _STACK


def layer_z(layer_id):
    return float(PHYSICAL_LAYERS[int(layer_id)])


def interface_z(plane):
    return INTERFACE_Z[str(plane)]


# ---------------------------------------------------------------- payloads
def process_rules_payload():
    return dict(
        schema='fanout_first_process_rules_v1',
        mode='corrected_50um',
        glass_thickness_mm=GLASS_THICKNESS_MM,
        glass_z_range_mm=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM],
        z1_interface_mm=Z1_INTERFACE_MM,
        z2_interface_mm=Z2_INTERFACE_MM,
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
        min_3d_clearance_mm=MIN_3D_CLEARANCE_MM,
        same_layer_2d_clearance_mm=CLEARANCE_2D_MM,
        same_layer_2d_rules='original strict D56 index (width 0.05 + edge gap '
                            '0.03); legal transverse crossings preserved',
        min_bend_radius_mm=MIN_BEND_RADIUS_MM,
        transition_geometry='two exact R=15 mm circular arcs in the vertical '
                            'plane of the local inward direction (G1 S-curve)',
        different_physical_planes='legal when |dz| >= 0.05 mm; XY overlap alone '
                                  'is not a violation',
        transition_vs_other='true 3D centre-line distance must be >= 0.05 mm',
        explicitly_not_restored=dict(
            global_80um_clearance=False,
            note='the unconfirmed 80 um global clearance is never used as a '
                 '3D rule; 0.08 mm only survives as the same-layer 2D centreline '
                 'rule of the original D56 geometry'),
        unconfirmed=dict(
            optical_crosstalk='not verified',
            fabrication_tolerance='not verified',
            surface_process_margin='not verified; the boundary waveguides only '
                                   'satisfy the current exploratory centreline model'),
    )


def physical_layer_stack_payload():
    stack = layer_stack()
    payload = stack.to_dict()
    payload.update(dict(
        schema='fanout_first_physical_layer_stack_v1',
        provenance='exploratory_simulation',
        formal_acceptance_allowed=False,
        glass_thickness_mm=GLASS_THICKNESS_MM,
        glass_z_range_mm=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM],
        route_count=1024,
        interface=dict(z1=Z1_INTERFACE_MM, z2=Z2_INTERFACE_MM),
        assignments={str(layer): MANUAL_LAYER_TO_GROUP.get(layer, 'other')
                     for layer in ROUTING_LAYER_IDS},
    ))
    return payload


def port_xy(endpoint_id):
    ep = endpoints()[endpoint_id]
    return (float(ep['routing_xy'][0]), float(ep['routing_xy'][1]))


def inward(endpoint_id):
    ep = endpoints()[endpoint_id]
    return (float(ep['inward'][0]), float(ep['inward'][1]))


def board_mm():
    from ..fslw import config as C
    return float(C.BOARD_MM)
